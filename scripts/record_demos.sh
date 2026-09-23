#!/usr/bin/env bash
# Re-record the demos in docs/demos by running each prompt through a real AI client
# connected to a live Blender (via scripts/start.sh), then saving the renders, a
# screenshot of Blender and the list of tool calls into the demo's markdown file.
#
# Usage: scripts/record_demos.sh [claude|codex] [docs/demos/NN-name.md ...]
#
# Environment: DEMO_MODEL (client model override), plus everything start.sh honours.
# Screenshots: the Blender window via `import`/`xwininfo` on Linux (X11), the screen via
# `screencapture` on macOS (grant your terminal Screen Recording permission).

set -euo pipefail
# shellcheck source=lib/common.sh
source "$(dirname "${BASH_SOURCE[0]}")/lib/common.sh"

CLIENT="${1:-claude}"
[ $# -gt 0 ] && shift
case "${CLIENT}" in
    claude | codex) ;;
    *) die "usage: scripts/record_demos.sh [claude|codex] [demo.md ...]" ;;
esac
command -v "${CLIENT}" >/dev/null 2>&1 || die "'${CLIENT}' is not installed"

DEMOS=("$@")
if [ ${#DEMOS[@]} -eq 0 ]; then
    DEMOS=("${REPO_ROOT}"/docs/demos/[0-9]*.md)
fi
OUT_DIR="/tmp/blender-mcp-demos" # the prompts write here
IMAGES_DIR="${REPO_ROOT}/docs/demos/images"
mkdir -p "${OUT_DIR}" "${IMAGES_DIR}" "${STATE_DIR}"

record() { "${VENV_PYTHON}" "${REPO_ROOT}/scripts/lib/demo_record.py" "$@"; }

bridge_python() { # run inline Python in the live Blender through the bridge
    local params
    params="$("${VENV_PYTHON}" -c 'import json, sys; print(json.dumps({"code": sys.stdin.read()}))')"
    BLENDER_MCP_TOKEN_FILE="${TOKEN_FILE}" "${VENV_PYTHON}" "${REPO_ROOT}/scripts/blender_bridge_request.py" \
        python.execute --params "${params}" --host "${BRIDGE_HOST}" --port "${BRIDGE_PORT}" --timeout 60 >/dev/null
}

screenshot() { # screenshot OUT.png
    local raw="${STATE_DIR}/screenshot-raw.png"
    case "$(os_name)" in
        macos) screencapture -x "${raw}" ;;
        *)
            command -v import >/dev/null 2>&1 || {
                warn "ImageMagick 'import' not found; skipping screenshot"
                return
            }
            # Capture just the Blender window when xwininfo can find it, else the whole screen.
            local window="root"
            if command -v xwininfo >/dev/null 2>&1; then
                window="$(xwininfo -root -tree | awk '/ - Blender [0-9]/ { print $1; exit }')"
                [ -n "${window}" ] || window="root"
            fi
            import -window "${window}" "${raw}"
            ;;
    esac
    if command -v magick >/dev/null 2>&1; then
        magick "${raw}" -resize '1440x>' "$1"
    elif command -v convert >/dev/null 2>&1; then
        convert "${raw}" -resize '1440x>' "$1"
    elif command -v sips >/dev/null 2>&1; then
        sips -Z 1440 "${raw}" --out "$1" >/dev/null
    else
        cp "${raw}" "$1"
    fi
}

# -- Blender ------------------------------------------------------------------
if ! port_open; then
    # Opening a saved file skips the splash screen, which would cover the screenshots.
    START_BLEND="${STATE_DIR}/demo-start.blend"
    BLENDER="$(find_blender)" || die "Blender not found"
    "${BLENDER}" -b --factory-startup --python-expr \
        "import bpy; bpy.ops.wm.save_as_mainfile(filepath=r'${START_BLEND}')" >/dev/null 2>&1
    BLENDER_ARGS="--window-geometry 0 0 1600 1000 ${START_BLEND}" "${REPO_ROOT}/scripts/start.sh" none
fi

RESET_SCENE="$(
    cat <<'PY'
import bpy
for obj in list(bpy.data.objects):
    bpy.data.objects.remove(obj, do_unlink=True)
for datablocks in (bpy.data.meshes, bpy.data.materials, bpy.data.lights, bpy.data.cameras,
                   bpy.data.actions, bpy.data.curves, bpy.data.images):
    for block in list(datablocks):
        datablocks.remove(block)
for collection in list(bpy.context.scene.collection.children):
    bpy.data.collections.remove(collection)
scene = bpy.context.scene
scene.frame_start, scene.frame_end = 1, 250
scene.frame_set(1)
PY
)"

FRAME_VIEWPORT="$(
    cat <<'PY'
import bpy
for obj in bpy.context.view_layer.objects:
    obj.select_set(False)
# Solid mode draws each material's viewport colour; agents usually only set the render colour.
for mat in bpy.data.materials:
    nodes = mat.node_tree.nodes if mat.use_nodes and mat.node_tree else []
    bsdf = next((node for node in nodes if node.type == "BSDF_PRINCIPLED"), None)
    if bsdf is not None and not bsdf.inputs["Base Color"].is_linked:
        mat.diffuse_color = bsdf.inputs["Base Color"].default_value
for window in bpy.context.window_manager.windows:
    for area in window.screen.areas:
        if area.type == "VIEW_3D":
            space = area.spaces.active
            # Solid shading with material colours draws instantly, even on software OpenGL.
            space.shading.type = "SOLID"
            space.shading.color_type = "MATERIAL"
            if bpy.context.scene.camera:
                space.region_3d.view_perspective = "CAMERA"
            area.tag_redraw()
PY
)"

VERSION="$("${CLIENT}" --version 2>/dev/null | head -n 1)"

for demo in "${DEMOS[@]}"; do
    [ -f "${demo}" ] || die "no such demo: ${demo}"
    id="$(basename "${demo}" | cut -d- -f1)"
    log "Recording ${demo} with ${CLIENT}"
    rm -f "${OUT_DIR}/${id}-"*.png
    echo "${RESET_SCENE}" | bridge_python

    prompt="$(record prompt "${demo}")"
    transcript="${STATE_DIR}/demo-${id}-${CLIENT}.jsonl"
    case "${CLIENT}" in
        claude)
            "${REPO_ROOT}/scripts/start.sh" claude -p "${prompt}" \
                --strict-mcp-config --allowedTools mcp__blender Read \
                --output-format stream-json --verbose \
                ${DEMO_MODEL:+--model "${DEMO_MODEL}"} >"${transcript}"
            ;;
        codex)
            "${REPO_ROOT}/scripts/start.sh" codex exec --skip-git-repo-check --json \
                --dangerously-bypass-approvals-and-sandbox \
                ${DEMO_MODEL:+--model "${DEMO_MODEL}"} "${prompt}" </dev/null >"${transcript}"
            ;;
    esac

    record update "${demo}" "${transcript}" "${CLIENT}" "${VERSION}"

    found=0
    for image in "${OUT_DIR}/${id}-"*.png; do
        [ -f "${image}" ] || continue
        cp "${image}" "${IMAGES_DIR}/"
        found=1
    done
    [ "${found}" -eq 1 ] || warn "the agent did not write ${OUT_DIR}/${id}-*.png"

    echo "${FRAME_VIEWPORT}" | bridge_python
    sleep 2 # let the viewport redraw
    screenshot "${IMAGES_DIR}/${id}-blender.png"
    ok "Recorded ${demo}"
done
