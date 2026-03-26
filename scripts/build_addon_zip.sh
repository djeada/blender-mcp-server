#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
DIST_DIR="${REPO_ROOT}/dist"
ADDON_DIR="${DIST_DIR}/blender_mcp_bridge"
ZIP_PATH="${DIST_DIR}/blender_mcp_bridge.zip"

if ! command -v zip >/dev/null 2>&1; then
    echo "error: zip is not available" >&2
    exit 1
fi

mkdir -p "${DIST_DIR}"
rm -rf "${ADDON_DIR}"
rm -f "${ZIP_PATH}"

mkdir -p "${ADDON_DIR}"
cp "${REPO_ROOT}/addon/__init__.py" "${ADDON_DIR}/__init__.py"

(
    cd "${DIST_DIR}"
    zip -rq "$(basename "${ZIP_PATH}")" "$(basename "${ADDON_DIR}")"
)

echo "Created ${ZIP_PATH}"
