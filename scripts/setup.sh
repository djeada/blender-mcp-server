#!/usr/bin/env bash
# One-time setup for macOS and Linux:
#   1. create .venv and install the MCP server
#   2. build the Blender add-on and install + enable it in Blender
#   3. optionally register the server with AI clients
#
# Usage: scripts/setup.sh [--blender PATH] [--register claude,codex,claude-desktop] [--skip-addon]
#
# Honoured environment: BLENDER_BIN, PYTHON_BIN, BLENDER_MCP_PORT, BLENDER_MCP_TOKEN_FILE,
# BLENDER_USER_RESOURCES (install into a separate Blender profile).

set -euo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

REGISTER=""
SKIP_ADDON=0

usage() {
    sed -n '2,11p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

while [ $# -gt 0 ]; do
    case "$1" in
        --blender)
            [ $# -ge 2 ] || die "--blender needs a path"
            export BLENDER_BIN="$2"
            shift 2
            ;;
        --register)
            [ $# -ge 2 ] || die "--register needs a client list"
            REGISTER="$2"
            shift 2
            ;;
        --skip-addon)
            SKIP_ADDON=1
            shift
            ;;
        -h | --help) usage 0 ;;
        *)
            warn "unknown option: $1"
            usage 1
            ;;
    esac
done

[ "$(os_name)" != "other" ] || die "only macOS and Linux are supported by this script"

# -- 1. Python environment ---------------------------------------------------
PYTHON="$(find_python)" || die "Python 3.10+ is required (set PYTHON_BIN to choose one)"
log "Python: ${PYTHON} ($("${PYTHON}" --version 2>&1))"
if [ ! -x "${VENV_PYTHON}" ]; then
    log "Creating ${VENV_DIR}"
    "${PYTHON}" -m venv "${VENV_DIR}"
fi
log "Installing blender-mcp-server into the venv"
# Venvs made by tools such as uv ship without pip
"${VENV_PYTHON}" -m pip --version >/dev/null 2>&1 || "${VENV_PYTHON}" -m ensurepip --upgrade >/dev/null
"${VENV_PYTHON}" -m pip install --quiet --upgrade pip
"${VENV_PYTHON}" -m pip install --quiet -e "${REPO_ROOT}"
[ -x "${SERVER_BIN}" ] || die "install finished but ${SERVER_BIN} is missing"
ok "MCP server: ${SERVER_BIN}"

# -- 2. Blender add-on -------------------------------------------------------
BLENDER=""
if BLENDER="$(find_blender)"; then
    VERSION="$(blender_version "${BLENDER}")"
    [ -n "${VERSION}" ] || die "could not run '${BLENDER} --version'"
    ok "Blender ${VERSION}: ${BLENDER}"
    version_ge "${VERSION}" "3.6" || die "Blender 3.6 or newer is required"
elif [ "${SKIP_ADDON}" -eq 0 ]; then
    die "Blender not found. Install it from https://www.blender.org/download/ or pass --blender /path/to/blender"
fi

run_blender_helper() {
    "${BLENDER}" -b --python "${REPO_ROOT}/scripts/lib/blender_addon_setup.py" -- "$@" 2>&1
}

if [ "${SKIP_ADDON}" -eq 0 ]; then
    log "Building the add-on zip"
    "${REPO_ROOT}/scripts/build_addon_zip.sh" >/dev/null
    if version_ge "${VERSION}" "4.2"; then
        # A legacy copy with the same name would also bind the bridge port.
        run_blender_helper remove-legacy | grep '^MCP_LEGACY' | sed 's/^/    /' >&2 || true
        log "Installing the add-on as a Blender extension"
        "${BLENDER}" -b --factory-startup --command extension install-file -r user_default -e "${ADDON_ZIP}" 2>&1 |
            grep -E 'STATUS|ERROR|Error' | sed 's/^/    /' >&2 || true
    else
        log "Installing the add-on (legacy add-on for Blender < 4.2)"
        run_blender_helper install-legacy "${ADDON_ZIP}" | grep '^MCP_' | sed 's/^/    /' >&2 || true
    fi
    RESULT="$(run_blender_helper verify | grep '^MCP_ADDON_' | head -n 1)"
    case "${RESULT}" in
        MCP_ADDON_OK*) ok "Add-on enabled (${RESULT#MCP_ADDON_OK })" ;;
        MCP_ADDON_OUTDATED*) die "an outdated copy of the add-on is still active: ${RESULT}. Remove it in Blender's preferences and rerun." ;;
        *) die "the add-on did not load in Blender. Try installing ${ADDON_ZIP} manually (Preferences > Add-ons > Install from Disk)." ;;
    esac
fi

# -- 3. Client registration (optional) -------------------------------------------
load_server_env

# env_flags FLAG: SERVER_ENV as repeated "FLAG KEY=VALUE" arguments in the FLAGS array
env_flags() {
    FLAGS=()
    local pair
    for pair in "${SERVER_ENV[@]}"; do
        FLAGS+=("$1" "${pair}")
    done
}

register_claude() {
    command -v claude >/dev/null 2>&1 || {
        warn "claude CLI not found; skipping"
        return
    }
    claude mcp remove blender -s user >/dev/null 2>&1 || true
    claude mcp add-json -s user blender \
        "$("${VENV_PYTHON}" "${CLIENT_CONFIG}" server-json "${SERVER_BIN}" "${SERVER_ENV[@]}")" >/dev/null
    ok "Registered 'blender' with Claude Code (user scope)"
}

register_codex() {
    command -v codex >/dev/null 2>&1 || {
        warn "codex CLI not found; skipping"
        return
    }
    codex mcp remove blender >/dev/null 2>&1 || true
    env_flags --env
    codex mcp add "${FLAGS[@]}" blender -- "${SERVER_BIN}" >/dev/null
    ok "Registered 'blender' with Codex"
}

register_claude_desktop() {
    local config
    if [ -n "${CLAUDE_DESKTOP_CONFIG:-}" ]; then
        config="${CLAUDE_DESKTOP_CONFIG}"
    elif [ "$(os_name)" = macos ]; then
        config="${HOME}/Library/Application Support/Claude/claude_desktop_config.json"
    else
        config="${HOME}/.config/Claude/claude_desktop_config.json"
    fi
    "${VENV_PYTHON}" "${CLIENT_CONFIG}" claude-desktop "${config}" "${SERVER_BIN}" "${SERVER_ENV[@]}"
    ok "Registered 'blender' in ${config} (restart Claude Desktop)"
}

if [ -n "${REGISTER}" ]; then
    IFS=',' read -r -a CLIENTS <<<"${REGISTER}"
    for client in "${CLIENTS[@]}"; do
        case "${client}" in
            claude) register_claude ;;
            codex) register_codex ;;
            claude-desktop) register_claude_desktop ;;
            *) warn "unknown client '${client}' (expected claude, codex, claude-desktop)" ;;
        esac
    done
fi

log "Setup complete. Next:"
cat >&2 <<EOF
    scripts/start.sh claude     # open Blender + Claude Code, connected
    scripts/start.sh codex      # open Blender + Codex, connected
    scripts/start.sh none       # just open Blender with the bridge running
EOF
