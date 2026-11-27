<!-- {"version": 1, "domain": "lighting", "title": "EEVEE, Cycles and real-time delivery",
"summary": "Know how engines differ in shadows, bounce light and noise, and separate preview lighting from engine lighting.",
"tags": ["lighting", "eevee", "cycles", "engine", "render", "samples", "noise", "realtime", "real-time", "baked", "game", "offline", "indirect", "shadow"],
"related": ["lighting-diagnosis", "texture-pipeline", "game-optimization"]} -->
# EEVEE, Cycles and real-time delivery

## Use when
Choosing a render engine, or lighting an asset that will be shown in another engine.

## Avoid when
Only the look inside one engine matters and it is already chosen.

## Tradeoffs
- **Cycles:** path traced; accurate soft shadows, bounces and reflections; slower and noisy until it converges. Runs on the CPU without a display.
- **EEVEE:** fast rasterization; indirect light, soft shadows and reflections are approximations that depend on version and settings. Settings and behaviour changed substantially in Blender 4.2 and later.
- **Game engines and viewers:** use their own lights, shadows and tone mapping. glTF carries materials, and optionally punctual lights (point, spot, directional) without area lights; Blender's lighting does not travel with the asset. For real-time, keep light out of base color, or bake lighting deliberately as a separate map.

## Pattern
Fixed, comparable settings for judging lighting changes in Cycles.

```python
scene = bpy.context.scene
scene.render.engine = "CYCLES"
scene.cycles.samples = int(args.get("samples", 64))
scene.cycles.seed = 0
scene.cycles.use_denoising = False  # denoising can hide noise problems and is missing from some builds
__result__ = {"engine": scene.render.engine, "samples": scene.cycles.samples}
```

`blender_view_capture` and `blender_material_preview` render in a temporary scene, so they do not need these changes.

## Pitfalls
- Approving lighting in EEVEE and delivering in Cycles, or the reverse.
- Expecting area lights, world lighting or color grading to survive a glTF export.
- Comparing noisy low-sample renders as if differences were lighting.

## Checks
Render the same frame in the delivery engine before sign-off. For game assets, view the exported file in the target viewer under its default lighting.
