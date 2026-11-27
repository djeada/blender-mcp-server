<!-- {"version": 1, "domain": "lighting", "title": "HDRI, sun and sky, indoors and outdoors",
"summary": "Choose between HDRI, sun with sky and studio lights, and light interiors and exteriors believably.",
"tags": ["lighting", "hdri", "environment", "sky", "sun", "outdoor", "exterior", "indoor", "interior", "window", "daylight", "ambient", "world"],
"related": ["lighting-fundamentals", "lighting-exposure", "render-engines"]} -->
# HDRI, sun and sky, indoors and outdoors

## Use when
Outdoor scenes, realistic ambient light, reflective materials and product or asset previews.

## Avoid when
A fully art-directed studio look is wanted and the environment would fight it.

## Tradeoffs
- **HDRI:** realistic light and reflections from one image; direction is baked in (rotate it), and it cannot cast sharp shadows unless the image holds a bright sun. Ordinary 8-bit images cannot hold that range.
- **Procedural sky:** controllable sun position and time of day; very bright, so lower exposure.
- **Sun light plus world color:** simple, art-directable sun shadows with a flat fill.

**Exteriors:** one sun (hard shadows, warm when low) plus sky ambient (cool). **Interiors:** daylight enters through openings: use large area lights just outside windows, plus practicals; light does not bounce much in EEVEE without extra setup, and Cycles needs samples for indirect light.

## Pattern
A plain environment color sets an even ambient level; here a cool, dim night ambient. Blender 5 ignores `world.use_nodes = False`, so set the Background node.

```python
world = bpy.data.worlds.new("GuideNightAmbient")
world.use_nodes = True
background = next(node for node in world.node_tree.nodes if node.type == "BACKGROUND")
background.inputs["Color"].default_value = (0.02, 0.035, 0.07, 1.0)  # linear color
background.inputs["Strength"].default_value = float(args.get("strength", 1.0))
__result__ = {"world": world.name}  # assign it with scene.world, or use blender_world_set
```

Prefer `blender_world_set` (`mode="environment"` with a local HDR, or `mode="sky"`), which protects existing worlds. Rotate an HDRI with `rotation`; `sun_rotation` turns the sky's sun the opposite way.

## Pitfalls
- Using an HDRI for light but showing an unrelated background: use `camera_background`.
- A physical sky with default exposure renders white.
- An interior lit only by the world through small windows is noisy and dark.
- HDRIs found online need a license that allows your use.

## Checks
`blender_view_capture(mode="material", lighting="world")` shows environment light alone; `lighting="scene"` adds lamps. Check that shadow direction matches the visible sun or window.
