#!/usr/bin/env bash
# Run a demo scene script yourself, no AI involved.
#
# Usage: scripts/run_demo.sh [--gui|--background|--bridge] DEMO [script options...]
#
#   DEMO is 1, 2, 3 or a path to a .py file (see docs/demos/scripts/).
#   --gui         (default) open Blender, build the scene and render it; Blender stays open
#   --background  build and render in a background Blender; only the image files are produced
#   --bridge      send the script to the Blender that is already running with the MCP add-on
#                 (e.g. after scripts/start.sh), exactly as an AI's blender_python_exec call would
#
# Script options go to the demo script, for example:
#   scripts/run_demo.sh --background 2 --seed 3 --output /tmp/city.png
#   scripts/run_demo.sh --bridge 3 --no-render
# Renders land in /tmp/blender-mcp-demos/ unless you pass --output / --output-dir.

set -euo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

MODE="gui"
case "${1:-}" in
    --gui | --background | --bridge)
        MODE="${1#--}"
        shift
        ;;
    -h | --help | "")
        sed -n '2,17p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'
        exit 0
        ;;
esac

DEMO="$1"
shift
case "${DEMO}" in
    [0-9])
        SCRIPT=""
        for candidate in "${REPO_ROOT}/docs/demos/scripts/0${DEMO}_"*.py; do
            [ -f "${candidate}" ] && SCRIPT="${candidate}" && break
        done
        [ -n "${SCRIPT}" ] || die "no demo script numbered ${DEMO} in docs/demos/scripts/"
        ;;
    *) SCRIPT="${DEMO}" ;;
esac
[ -f "${SCRIPT}" ] || die "no such script: ${SCRIPT}"
mkdir -p /tmp/blender-mcp-demos

case "${MODE}" in
    gui | background)
        BLENDER="$(find_blender)" || die "Blender not found (set BLENDER_BIN)"
        if [ "${MODE}" = gui ]; then
            log "Opening Blender with ${SCRIPT#"${REPO_ROOT}"/}"
            exec "${BLENDER}" --python "${SCRIPT}" -- "$@"
        fi
        log "Running ${SCRIPT#"${REPO_ROOT}"/} in background Blender"
        exec "${BLENDER}" -b --factory-startup --python "${SCRIPT}" -- "$@"
        ;;
    bridge)
        [ -x "${VENV_PYTHON}" ] || die "run scripts/setup.sh first"
        port_open || die "no Blender bridge on ${BRIDGE_HOST}:${BRIDGE_PORT}; start one with scripts/start.sh none"
        # Turn "--seed 3 --no-render" into the args dict the script reads under blender_python_exec.
        PARAMS="$("${VENV_PYTHON}" - "${SCRIPT}" "$@" <<'PY'
import json, sys
script, rest = sys.argv[1], sys.argv[2:]
args, i = {}, 0
while i < len(rest):
    key = rest[i].lstrip("-").replace("-", "_")
    values = []
    while i + 1 < len(rest) and not rest[i + 1].startswith("--"):
        i += 1
        values.append(int(rest[i]) if rest[i].lstrip("-").isdigit() else rest[i])
    if key.startswith("no_"):
        args[key[3:]] = False
    else:
        args[key] = values if len(values) > 1 or key == "frames" else (values[0] if values else True)
    i += 1
print(json.dumps({"code": open(script).read(), "args": args, "timeout_seconds": 300}))
PY
)"
        log "Sending ${SCRIPT#"${REPO_ROOT}"/} to Blender at ${BRIDGE_HOST}:${BRIDGE_PORT}"
        BLENDER_MCP_TOKEN_FILE="${TOKEN_FILE}" "${VENV_PYTHON}" "${REPO_ROOT}/scripts/blender_bridge_request.py" \
            python.execute --params "${PARAMS}" --host "${BRIDGE_HOST}" --port "${BRIDGE_PORT}" --timeout 600 |
            "${VENV_PYTHON}" -c '
import json, sys
response = json.load(sys.stdin)
result = response.get("result") or {}
sys.stdout.write(result.get("stdout", ""))
error = response.get("error") or result.get("error")
if error:
    sys.exit("error: " + error)'
        ;;
esac
