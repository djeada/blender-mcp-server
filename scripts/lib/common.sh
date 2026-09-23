# shellcheck shell=bash
# Shared helpers for setup.sh / start.sh / stop.sh. Source, don't execute.
# Written for bash 3.2 so it runs on the stock macOS shell.
# shellcheck disable=SC2034 # variables below are used by the scripts that source this file

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
VENV_DIR="${REPO_ROOT}/.venv"
SERVER_BIN="${VENV_DIR}/bin/blender-mcp-server"
VENV_PYTHON="${VENV_DIR}/bin/python"
ADDON_ZIP="${REPO_ROOT}/dist/blender_mcp_bridge.zip"
ADDON_ID="blender_mcp_bridge"

BRIDGE_HOST="${BLENDER_MCP_HOST:-127.0.0.1}"
BRIDGE_PORT="${BLENDER_MCP_PORT:-9876}"
TOKEN_FILE="${BLENDER_MCP_TOKEN_FILE:-${HOME}/.blender-mcp/token}"
STATE_DIR="${BLENDER_MCP_STATE_DIR:-${HOME}/.blender-mcp}"

log() { printf '\033[1;34m==>\033[0m %s\n' "$*" >&2; }
ok() { printf '\033[1;32m ✓\033[0m %s\n' "$*" >&2; }
warn() { printf '\033[1;33m !\033[0m %s\n' "$*" >&2; }
die() {
    printf '\033[1;31merror:\033[0m %s\n' "$*" >&2
    exit 1
}

os_name() {
    case "$(uname -s)" in
        Darwin) echo macos ;;
        Linux) echo linux ;;
        *) echo other ;;
    esac
}

# find_python: print a python3 >= 3.10 interpreter or fail.
find_python() {
    local candidate
    for candidate in "${PYTHON_BIN:-}" python3.13 python3.12 python3.11 python3.10 python3; do
        [ -n "${candidate}" ] || continue
        command -v "${candidate}" >/dev/null 2>&1 || continue
        if "${candidate}" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' 2>/dev/null; then
            command -v "${candidate}"
            return 0
        fi
    done
    return 1
}

# find_blender: honour BLENDER_BIN, then PATH, then the usual install locations.
find_blender() {
    local candidate
    if [ -n "${BLENDER_BIN:-}" ]; then
        if [ -x "${BLENDER_BIN}" ] || command -v "${BLENDER_BIN}" >/dev/null 2>&1; then
            command -v "${BLENDER_BIN}" 2>/dev/null || echo "${BLENDER_BIN}"
            return 0
        fi
        return 1
    fi
    for candidate in \
        "$(command -v blender 2>/dev/null)" \
        "/Applications/Blender.app/Contents/MacOS/Blender" \
        "${HOME}/Applications/Blender.app/Contents/MacOS/Blender" \
        "/snap/bin/blender" \
        "${HOME}/.local/bin/blender"; do
        if [ -n "${candidate}" ] && [ -x "${candidate}" ]; then
            echo "${candidate}"
            return 0
        fi
    done
    # Unpacked tarballs such as /opt/blender-4.2.1-linux-x64/blender (newest last)
    # shellcheck disable=SC2012 # plain glob listing; paths have no newlines
    candidate="$(ls -d /opt/blender*/blender "${HOME}"/blender*/blender 2>/dev/null | sort | tail -n 1)"
    if [ -n "${candidate}" ] && [ -x "${candidate}" ]; then
        echo "${candidate}"
        return 0
    fi
    return 1
}

# blender_version BIN -> "4.2.1"
blender_version() {
    "$1" --version 2>/dev/null | awk '/^Blender [0-9]/ { print $2; exit }'
}

# version_ge A B -> success when A >= B (numeric, dot separated)
version_ge() {
    awk -v a="$1" -v b="$2" 'BEGIN {
        n = split(a, x, "."); m = split(b, y, ".");
        for (i = 1; i <= (n > m ? n : m); i++) {
            if ((x[i] + 0) > (y[i] + 0)) exit 0;
            if ((x[i] + 0) < (y[i] + 0)) exit 1;
        }
        exit 0
    }'
}

port_open() {
    local py
    py="$(find_python)" || return 1
    "${py}" - "${BRIDGE_HOST}" "${BRIDGE_PORT}" <<'PY'
import socket, sys
try:
    socket.create_connection((sys.argv[1], int(sys.argv[2])), timeout=1).close()
except OSError:
    sys.exit(1)
PY
}

# bridge_check: authenticated scene.get_info round trip through the add-on.
bridge_check() {
    BLENDER_MCP_TOKEN_FILE="${TOKEN_FILE}" "${VENV_PYTHON}" "${REPO_ROOT}/scripts/blender_bridge_request.py" \
        scene.get_info --host "${BRIDGE_HOST}" --port "${BRIDGE_PORT}" --timeout 10
}

CLIENT_CONFIG="${REPO_ROOT}/scripts/lib/client_config.py"

# load_server_env: fill the SERVER_ENV array with KEY=VALUE pairs from mcp_server_env.
load_server_env() {
    SERVER_ENV=()
    local line
    while IFS= read -r line; do
        SERVER_ENV+=("${line}")
    done < <(mcp_server_env)
}

# Environment the MCP server needs, as KEY=VALUE lines. Passed explicitly because some
# clients (e.g. Codex) only forward a minimal environment to MCP servers.
mcp_server_env() {
    local blender
    echo "BLENDER_MCP_HOST=${BRIDGE_HOST}"
    echo "BLENDER_MCP_PORT=${BRIDGE_PORT}"
    echo "BLENDER_MCP_TOKEN_FILE=${TOKEN_FILE}"
    if blender="$(find_blender)"; then
        echo "BLENDER_BIN=${blender}"
    fi
}
