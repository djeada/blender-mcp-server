<!-- {"version": 1, "domain": "lighting", "title": "Key, fill, rim, contrast and color",
"summary": "Shape subjects and set mood with light roles, contrast in stops, motivated sources and color temperature.",
"tags": ["lighting", "key", "fill", "rim", "ratio", "contrast", "mood", "cinematic", "night", "dramatic", "portrait", "practical", "motivated", "temperature", "kelvin", "warm", "cool", "silhouette"],
"related": ["lighting-fundamentals", "lighting-composition", "lighting-diagnosis"]} -->
# Key, fill, rim, contrast and color

## Use when
Lighting a subject, character or scene where shape and mood matter.

## Avoid when
You only need even, neutral light to inspect an asset: use the `turntable` rig.

## Tradeoffs
- **Key** gives the main shape and shadow direction. **Fill** lifts shadows without adding a second shadow. **Rim** separates the subject from the background.
- Think of contrast in **stops** between key and fill at the subject: about half to one stop reads open and cheerful, around two stops reads dimensional, three or more reads dramatic. These are starting points; the surface colors, exposure and background change the result.
- **Motivated** light seems to come from something visible: a window, lamp, screen, fire or moon. **Practicals** are the visible sources themselves; add a hidden larger light near them to do the real work.
- **Color temperature:** lower kelvin is warmer. Warm key against cool fill (or the reverse) separates planes. Night is not just blue and dim: it has a few motivated pools of light, deep but readable shadows and a cool ambient.

## Pattern
Three roles whose strengths differ in stops, computed so their effect at the subject is what you chose.

```python
import math


def add_light(role, position, stops_below_key, kelvin_color, size):
    distance = math.dist(position, (0, 0, 0))
    irradiance = 3.0 * 2.0**-stops_below_key
    data = bpy.data.lights.new(f"GuideMood{role}", type="AREA")
    data.size, data.color = size, kelvin_color
    data.energy = irradiance * math.pi * distance**2
    light = bpy.data.objects.new(data.name, data)
    light.location = position
    light.rotation_euler = (-light.location).to_track_quat("-Z", "Y").to_euler()
    bpy.context.scene.collection.objects.link(light)
    return {"role": role, "watts": round(data.energy, 1)}


__result__ = [
    add_light("Key", (3.0, -3.0, 2.5), 0.0, (1.0, 0.82, 0.62), 1.0),
    add_light("Fill", (-4.0, -2.0, 0.8), 2.5, (0.62, 0.75, 1.0), 3.0),
    add_light("Rim", (-1.5, 4.0, 2.5), 0.3, (0.75, 0.85, 1.0), 0.8),
]
```

With the typed tools: `blender_lighting_rig_apply(rig="low_key", ratios={"fill": 0.1})`, and `temperatures` for warm and cool roles.

## Pitfalls
- Fill so strong that shadows vanish and forms flatten.
- Several equal lights casting several competing shadows.
- A rim that looks like a second key.
- Saturated colored lights that hide the material colors.

## Checks
Capture with `lighting="scene"` from the camera angle. Check the silhouette against the background, one clear shadow direction, and readable shadow detail. Change one light at a time and compare.
