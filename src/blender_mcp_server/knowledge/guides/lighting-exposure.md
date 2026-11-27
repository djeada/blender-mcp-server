<!-- {"version": 1, "domain": "lighting", "title": "Exposure and color management",
"summary": "Set overall brightness with exposure and view transforms without disturbing light balance or texture colors.",
"tags": ["lighting", "exposure", "color-management", "view-transform", "agx", "filmic", "standard", "tone-mapping", "highlight", "clipping", "brightness", "gamma", "baked"],
"related": ["lighting-diagnosis", "lighting-fundamentals", "texture-pipeline"]} -->
# Exposure and color management

## Use when
The balance between lights is right but the whole picture is too dark, bright or harsh, and before judging any material color.

## Avoid when
Only part of the picture is wrong: change that light instead.

## Tradeoffs
- **Exposure** (in stops) scales the whole scene without changing ratios. Prefer it to rescaling every light.
- **View transforms** compress bright values. AgX and Filmic roll highlights off gently but change saturation and contrast; Standard shows colors directly but clips highlights hard. Pick one early, because lights and materials get tuned against it.
- **Gamma** and looks are final grading, not fixes for lighting.

Scene lighting and **baked texture color** are different: base color textures should not contain strong light or shadow if real-time lights will light the asset. Data textures are never affected by the view transform.

## Pattern
Set the transform explicitly and record what you changed.

```python
view = bpy.context.scene.view_settings
before = {"view_transform": view.view_transform, "exposure": view.exposure}
try:
    view.view_transform = args.get("view_transform", "AgX")
except TypeError:
    view.view_transform = "Standard"  # older builds name their transforms differently
view.exposure = float(args.get("exposure", 0.0))
__result__ = {"before": before, "after": {"view_transform": view.view_transform, "exposure": view.exposure}}
```

Prefer `blender_color_management_set`, which validates names and changes nothing if one is invalid; `blender_lighting_inspect(include_options=true)` lists valid ones.

## Pitfalls
- Compensating a bad view transform by crushing light power.
- Comparing renders made with different transforms or exposure.
- Judging texture colors under AgX or Filmic and expecting the same hex values on screen.
- Engines apply their own tone mapping; a Blender preview is not the engine.

## Checks
Render with the final settings. Look at the brightest highlight and the darkest shadow: both should keep some detail unless clipping is intended. Change exposure by half a stop to compare.
