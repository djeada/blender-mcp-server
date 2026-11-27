<!-- {"version": 1, "domain": "lighting", "title": "Diagnosing lighting problems",
"summary": "Fix flat light, crushed shadows, blown highlights, noise, glare and scale errors by changing one thing at a time.",
"tags": ["lighting", "diagnosis", "problem", "flat", "dark", "bright", "crushed", "blown", "noise", "noisy", "glare", "glossy", "specular", "washed", "contrast", "fix", "preview", "scale"],
"related": ["lighting-exposure", "lighting-mood", "render-engines"]} -->
# Diagnosing lighting problems

## Use when
A preview looks wrong.

## Avoid when
The mesh or material is broken; check with `blender_mesh_inspect` and `blender_material_diagnose` first.

## Tradeoffs
Change **one variable at a time** and compare renders with the same camera, engine, samples and exposure; changing several hides which one mattered.

| Symptom | Likely cause | First change |
|---|---|---|
| Flat, no shape | Key too frontal, or fill too strong | Move the key 30–60° off the camera; lower fill by a stop |
| Crushed shadows | No fill or ambient; view transform | Add soft fill or world light; try AgX or Filmic |
| Blown highlights | Too much light, or Standard transform | Lower exposure by a stop; then reduce the offending light |
| Everything washed out | World or fill too bright; excessive exposure | Reduce world strength, then exposure |
| Noisy render | Too few samples; small bright lights; indirect light through small openings | Raise samples; enlarge lights; add a portal-sized area light |
| Glare hides material | Small bright source reflected; roughness too low | Move or enlarge the source; check roughness |
| Black metal | Nothing to reflect | Add an environment or softboxes |
| Light seems wrong at any power | Scene scale | Compare light distances and sizes with the subject radius |
| Muddy colors | Mixed saturated lights | Neutralize colors, then reintroduce one |

## Pattern
List each light's rough contribution at the subject, to find the one that dominates.

```python
import math

target = mathutils.Vector(args.get("target", (0.0, 0.0, 0.0)))
report = []
for obj in bpy.context.scene.objects:
    if obj.type != "LIGHT" or obj.hide_render:
        continue
    data = obj.data
    distance = max((obj.matrix_world.translation - target).length, 1e-6)
    if data.type == "SUN":
        irradiance = data.energy
    else:
        spread = math.pi if data.type == "AREA" else 4 * math.pi
        irradiance = data.energy / (spread * distance**2)
    report.append({"light": obj.name, "distance": round(distance, 3), "irradiance": round(irradiance, 4)})
__result__ = sorted(report, key=lambda item: -item["irradiance"])[:20]
```

It ignores aiming, shadowing, spot cones and the world, so use it to rank lights, not to predict a render.

## Pitfalls
- Fixing exposure by editing many lights.
- Concluding from viewport shading instead of a render.
- Comparing renders with random seeds or sample counts that differ.

## Checks
Keep the before image. Make one change, render with identical settings, and compare. Undo the change if the symptom did not improve.
