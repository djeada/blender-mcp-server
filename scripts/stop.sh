#!/usr/bin/env bash
# Stop the Blender instance that scripts/start.sh launched (a Blender you opened yourself is left alone).

set -euo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

PID_FILE="${STATE_DIR}/blender.pid"
if [ ! -f "${PID_FILE}" ]; then
    log "No Blender started by start.sh is recorded"
    exit 0
fi
PID="$(cat "${PID_FILE}")"
if kill -0 "${PID}" 2>/dev/null; then
    kill "${PID}"
    for _ in $(seq 1 20); do
        kill -0 "${PID}" 2>/dev/null || break
        sleep 0.25
    done
    kill -0 "${PID}" 2>/dev/null && kill -9 "${PID}"
    ok "Stopped Blender (pid ${PID})"
else
    log "Blender (pid ${PID}) is not running"
fi
rm -f "${PID_FILE}"
