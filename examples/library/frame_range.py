"""Set the scene frame range and optionally jump to a frame.

Args:
    frame_start (int): Start frame. Default: 1
    frame_end (int): End frame. Default: 250
    frame_current (int|None): Frame to jump to. Default: None (no change)
    fps (int|None): Frames per second. Default: None (no change)

Result:
    frame_start (int): Start frame set
    frame_end (int): End frame set
    frame_current (int): Current frame after change
    fps (int): Scene FPS
"""

import bpy

scene = bpy.context.scene
scene.frame_start = args.get("frame_start", 1)
scene.frame_end = args.get("frame_end", 250)

frame_current = args.get("frame_current")
if frame_current is not None:
    scene.frame_set(frame_current)

fps = args.get("fps")
if fps is not None:
    scene.render.fps = fps

__result__ = {
    "frame_start": scene.frame_start,
    "frame_end": scene.frame_end,
    "frame_current": scene.frame_current,
    "fps": scene.render.fps,
}
