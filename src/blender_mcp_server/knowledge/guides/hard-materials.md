<!-- {"version": 1, "domain": "art-direction", "title": "Wood, stone and metals",
"summary": "Give wood grain, stone and metals their identity through reflectance, roughness, grain direction and scale.",
"tags": ["wood", "wooden", "plank", "timber", "grain", "stone", "rock", "marble", "concrete", "metal", "steel", "iron", "gold", "copper", "brass", "aluminium", "texture"],
"related": ["material-layering", "pbr-materials", "procedural-materials"]} -->
# Wood, stone and metals

## Use when
Props, architecture and anything where a viewer must recognise the material at a glance.

## Avoid when
Reference photos or scanned texture sets are available and licensed; use them and check them with the diagnostics.

## Tradeoffs
Identity comes from structure (grain, veins, aggregate), reflectance and roughness more than from hue. Procedural versions are editable; photographic sets are more convincing but need matching scale.

- **Wood:** grain runs along the log; end grain shows rings; planks vary in tone from board to board; sealed wood is smoother (0.35–0.5), raw wood rougher (0.6–0.8).
- **Stone:** non-metal, mostly rough; features at several sizes; marble veins branch rather than repeat evenly; mortar and joints matter as much as blocks.
- **Metals:** metallic 1; the base color is the reflectance. Linear values: iron about (0.56, 0.57, 0.58), aluminium (0.91, 0.92, 0.92), gold (1.0, 0.71, 0.29), copper (0.95, 0.64, 0.54). Character comes from roughness: brushing, scratches and oxide.

## Pattern
Wood rings from a wave texture in object space, distorted by noise, with the grain along Z.

```python
material = bpy.data.materials.new("GuideWood")
material.use_nodes = True
tree = material.node_tree
nodes, links = tree.nodes, tree.links
shader = next(node for node in nodes if node.type == "BSDF_PRINCIPLED")
coordinates = nodes.new("ShaderNodeTexCoord")
mapping = nodes.new("ShaderNodeMapping")
mapping.inputs["Scale"].default_value = (1.0, 1.0, 0.12)  # stretch features along the grain
rings = nodes.new("ShaderNodeTexWave")
rings.wave_type = "RINGS"
rings.rings_direction = "Z"
rings.inputs["Scale"].default_value = float(args.get("rings_per_meter", 12.0))
rings.inputs["Distortion"].default_value = 4.0
rings.inputs["Detail"].default_value = 3.0
tone = nodes.new("ShaderNodeValToRGB")
elements = tone.color_ramp.elements
elements[0].position, elements[0].color = 0.2, (0.13, 0.055, 0.018, 1.0)
elements[1].position, elements[1].color = 0.85, (0.36, 0.19, 0.075, 1.0)
bump = nodes.new("ShaderNodeBump")
bump.inputs["Strength"].default_value = 0.15
bump.inputs["Distance"].default_value = 0.002  # meters
links.new(coordinates.outputs["Object"], mapping.inputs["Vector"])
links.new(mapping.outputs["Vector"], rings.inputs["Vector"])
links.new(rings.outputs["Fac"], tone.inputs["Fac"])
links.new(tone.outputs["Color"], shader.inputs["Base Color"])
links.new(rings.outputs["Fac"], bump.inputs["Height"])
links.new(bump.outputs["Normal"], shader.inputs["Normal"])
shader.inputs["Roughness"].default_value = 0.45
__result__ = {"material": material.name}
```

## Pitfalls
- Grain running across a plank, or identical on every plank.
- Metal with a dark "paint" base color: use the real reflectance and let lighting darken it.
- Metals look black in a dark scene because they only reflect. Give them an environment or softboxes before judging.
- Procedural wood does not export to glTF; bake it.

## Checks
Preview under `studio_softbox` or an environment, not one point light. Capture the asset beside a known material. Run `blender_material_diagnose` when image maps are used.
