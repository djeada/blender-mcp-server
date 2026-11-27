<!-- {"version": 1, "domain": "lighting", "title": "Light types, units, distance and softness",
"summary": "Pick light types and compute power from distance; control shadow softness with apparent source size.",
"tags": ["light", "lighting", "lamp", "units", "watts", "power", "energy", "distance", "falloff", "softness", "shadow", "area", "point", "sun", "spot", "scale"],
"related": ["lighting-mood", "lighting-diagnosis", "environment-lighting"]} -->
# Light types, units, distance and softness

## Use when
Placing any light, and whenever a scene is much larger or smaller than a few meters.

## Avoid when
The environment alone lights the scene (see environment-lighting).

## Tradeoffs
- **Area:** soft, directional shadows and controllable reflections; the default for subjects.
- **Point:** emits in all directions: bulbs, flames. **Spot:** a point light in a cone.
- **Sun:** parallel light from infinitely far; its power does not fall off with distance.

**Units.** Point, spot and area `energy` is total power in watts. Sun `energy` is irradiance in W/m². Measured in Cycles: a point light gives about P / (4πd²) W/m² at distance d, and a small area light facing the surface about P / (πd²). Large sources deliver somewhat less (about 10% less when the width is 0.75 d). So **no power value is right by itself**: doubling the distance needs four times the power, and a model ten times larger needs a hundred times the power for the same look.

**Softness** depends on the source's size as seen from the subject: width divided by distance. A big, close source is soft; a small or distant one is hard.

## Pattern
Choose the light you want at the subject, then solve for power. Distances come from the subject's size.

```python
import math

radius = float(args.get("subject_radius", 1.0))
distance = 4.0 * radius
irradiance = float(args.get("irradiance", 3.0))  # W/m² at the subject; compare lights by this, not by watts
data = bpy.data.lights.new("GuideKey", type="AREA")
data.shape = "DISK"
data.size = 1.5 * radius  # softness stays the same at any scale
data.energy = irradiance * math.pi * distance**2
light = bpy.data.objects.new("GuideKey", data)
light.location = (distance * 0.57, -distance * 0.66, distance * 0.49)
light.rotation_euler = (-light.location).to_track_quat("-Z", "Y").to_euler()
bpy.context.scene.collection.objects.link(light)
__result__ = {"light": light.name, "watts": round(data.energy, 2), "distance": distance}
```

`blender_lighting_rig_apply` does this fitting for you.

## Pitfalls
- Copying watt values from a scene of another size.
- Moving a light farther away to soften it: that makes it harder and dimmer. Make it larger.
- Unapplied scale or a model built in the wrong units.
- EEVEE and Cycles differ in shadows, soft light and indirect bounce; check the engine you deliver in.
- Cycles can clamp very strong or very small lights.

## Checks
`blender_lighting_inspect` lists each light with its position, power and size. Estimate each light's irradiance at the subject with the formulas and compare them as ratios, then confirm with a render.
