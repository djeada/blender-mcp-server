#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
VENV_DIR="${REPO_ROOT}/.venv"
PYTHON_BIN="${PYTHON_BIN:-python3}"
INSTALL_TARGET="${INSTALL_TARGET:-${REPO_ROOT}}"

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
    echo "error: ${PYTHON_BIN} is not available" >&2
    exit 1
fi

if [ ! -d "${VENV_DIR}" ]; then
    echo "Creating virtual environment at ${VENV_DIR}"
    "${PYTHON_BIN}" -m venv "${VENV_DIR}"
fi

echo "Using virtual environment: ${VENV_DIR}"
"${VENV_DIR}/bin/python" -m pip install --upgrade pip
"${VENV_DIR}/bin/pip" install -e "${INSTALL_TARGET}"

echo "Starting blender-mcp-server"
exec "${VENV_DIR}/bin/blender-mcp-server" "$@"
