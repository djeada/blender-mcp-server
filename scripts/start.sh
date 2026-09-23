#!/usr/bin/env bash
# Open Blender with the MCP bridge and an AI client that is already connected to it.
#
# Usage: scripts/start.sh [claude|codex|none] [client args...]
#
#   scripts/start.sh claude                          # interactive Claude Code session
#   scripts/start.sh codex "Build a snowman"         # Codex, starting with a prompt
#   scripts/start.sh claude -p "List my objects" --allowedTools mcp__blender
#   scripts/start.sh none                            # only start Blender + bridge
#
# Blender is reused if the bridge is already listening; otherwise it is launched in the
# background (log: ~/.blender-mcp/blender.log) and stopped again with scripts/stop.sh.
# The MCP server is handed to the client on the command line, so no client config
# is modified. Set BLENDER_ARGS to pass extra arguments (e.g. a .blend file) to Blender.

set -euo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

CLIENT="${1:-claude}"
[ $# -gt 0 ] && shift
case "${CLIENT}" in
    claude | codex | none) ;;
    -h | --help)
        sed -n '2,15p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
        exit 0
        ;;
    *) die "unknown client '${CLIENT}' (expected claude, codex or none)" ;;
esac

if [ "${CLIENT}" != none ]; then
    command -v "${CLIENT}" >/dev/null 2>&1 || die "'${CLIENT}' is not installed or not on PATH"
fi

if [ ! -x "${SERVER_BIN}" ]; then
    log "First run: running setup"
    "${REPO_ROOT}/scripts/setup.sh"
fi

mkdir -p "${STATE_DIR}"
BLENDER_LOG="${STATE_DIR}/blender.log"
BLENDER_PID_FILE="${STATE_DIR}/blender.pid"

# -- Blender + bridge ------------------------------------------------------------
if port_open; then
    ok "Bridge already listening on ${BRIDGE_HOST}:${BRIDGE_PORT}; reusing that Blender"
else
    BLENDER="$(find_blender)" || die "Blender not found (set BLENDER_BIN)"
    log "Launching Blender: ${BLENDER}"
    # shellcheck disable=SC2086 # BLENDER_ARGS is intentionally word-split
    BLENDER_MCP_PORT="${BRIDGE_PORT}" BLENDER_MCP_TOKEN_FILE="${TOKEN_FILE}" \
        nohup "${BLENDER}" ${BLENDER_ARGS:-} </dev/null >"${BLENDER_LOG}" 2>&1 &
    echo $! >"${BLENDER_PID_FILE}"
    log "Waiting for the bridge on ${BRIDGE_HOST}:${BRIDGE_PORT}"
    for _ in $(seq 1 120); do
        port_open && break
        if ! kill -0 "$(cat "${BLENDER_PID_FILE}")" 2>/dev/null; then
            tail -n 20 "${BLENDER_LOG}" >&2 || true
            die "Blender exited during startup (log: ${BLENDER_LOG})"
        fi
        sleep 0.5
    done
    port_open || die "the bridge did not start within 60s. Is the add-on enabled? Run scripts/setup.sh (log: ${BLENDER_LOG})"
fi

if ! RESPONSE="$(bridge_check 2>&1)"; then
    echo "${RESPONSE}" >&2
    case "${RESPONSE}" in
        *Unauthorized* | *token*) die "the bridge rejected our token. Rerun scripts/setup.sh to update the add-on, then restart Blender." ;;
        *) die "the bridge is listening but did not answer scene.get_info" ;;
    esac
fi
ok "Bridge answered an authenticated request"

# -- AI client ---------------------------------------------------------------
case "${CLIENT}" in
    none)
        log "Blender is running with the bridge. Stop it with scripts/stop.sh"
        ;;
    claude)
        CONFIG="${STATE_DIR}/claude-mcp.json"
        load_server_env
        "${VENV_PYTHON}" "${CLIENT_CONFIG}" claude-json "${CONFIG}" "${SERVER_BIN}" "${SERVER_ENV[@]}"
        log "Starting Claude Code with the Blender MCP server"
        exec claude --mcp-config "${CONFIG}" "$@"
        ;;
    codex)
        load_server_env
        ENV_TOML="$("${VENV_PYTHON}" "${CLIENT_CONFIG}" codex-env "${SERVER_ENV[@]}")"
        log "Starting Codex with the Blender MCP server"
        exec codex \
            -c "mcp_servers.blender.command=\"${SERVER_BIN}\"" \
            -c "mcp_servers.blender.args=[]" \
            -c "mcp_servers.blender.env=${ENV_TOML}" \
            "$@"
        ;;
esac
