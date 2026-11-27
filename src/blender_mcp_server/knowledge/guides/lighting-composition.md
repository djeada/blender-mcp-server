<!-- {"version": 1, "domain": "lighting", "title": "Composition, silhouettes and reflections",
"summary": "Frame the subject, separate it from the background and shape reflections on glossy and metal surfaces.",
"tags": ["lighting", "composition", "framing", "silhouette", "reflection", "reflective", "product", "glossy", "metal", "glass", "background", "camera", "shot", "softbox"],
"related": ["lighting-mood", "lighting-diagnosis", "hard-materials"]} -->
# Composition, silhouettes and reflections

## Use when
Hero shots, products, thumbnails, and any glossy or metallic subject.

## Avoid when
A technical inspection view is all that is needed.

## Tradeoffs
- Decide what the eye should see first: the highest contrast and brightest value should be there.
- Separate subject from background with value, rim light or color, not only with depth.
- **Reflective surfaces show the lights, not light on them.** On metal and gloss, light placement is the reflection you see. Large soft sources make clean gradient stripes that describe curves; small sources make dots. Dark areas that are reflected (flags) define edges.
- A longer lens flattens and flatters; a wide lens close up distorts. Leave space in the direction the subject faces.

## Pattern
A tall, narrow softbox draws a vertical highlight down a curved product.

```python
import math

data = bpy.data.lights.new("GuideStripBox", type="AREA")
data.shape = "RECTANGLE"
data.size, data.size_y = 0.5, 4.0
distance = 4.0
data.energy = 2.0 * math.pi * distance**2
strip = bpy.data.objects.new("GuideStripBox", data)
strip.location = (distance * math.sin(math.radians(55)), -distance * math.cos(math.radians(55)), 0.5)
strip.rotation_euler = (-strip.location).to_track_quat("-Z", "Y").to_euler()
bpy.context.scene.collection.objects.link(strip)
__result__ = {"light": strip.name, "size": [data.size, data.size_y]}
```

Frame with `blender_camera_frame(camera=..., object=..., margin=1.2)` and light with `blender_lighting_rig_apply(rig="studio_softbox")`.

## Pitfalls
- Judging metals in an empty black world: they look black except for the lights.
- Highlights merging with the background and eating the silhouette.
- Reflections of hard, tiny sources that read as noise.
- Centering everything with equal space on all sides by default.

## Checks
Capture from the real camera angle. Squint or shrink the image: the silhouette and focal point should still read. Move a softbox a little and watch the highlight travel.
