"""Open Blender GUI with the stable procedural dam-break scene built.

Run:
    blender --factory-startup --python examples/demos/open_dam_break_gui.py
"""

from __future__ import annotations

from pathlib import Path

import bpy

SCENE_SCRIPT = Path(__file__).with_name("procedural_dam_break_scene.py")


def main() -> None:
    args = {
        "frame_end": 120,
        "output_dir": "//",
    }
    namespace = {
        "__name__": "__main__",
        "args": args,
    }

    code = SCENE_SCRIPT.read_text(encoding="utf-8")
    exec(compile(code, str(SCENE_SCRIPT), "exec"), namespace)
    bpy.context.scene.frame_set(min(70, bpy.context.scene.frame_end))
    print("Procedural dam-break scene ready in Blender GUI")


if __name__ == "__main__":
    main()
