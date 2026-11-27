<!-- {"version": 1, "domain": "surfacing", "title": "Procedural versus image-based materials",
"summary": "Build noise, wave and ramp materials, choose coordinates deliberately, and know what must be baked.",
"tags": ["procedural", "noise", "voronoi", "wave", "ramp", "shader", "nodes", "graph", "material", "texture", "tileable"],
"related": ["texture-mapping", "texture-pipeline", "material-layering"]} -->
# Procedural versus image-based materials

## Use when
Renders in Blender, endless non-repeating surfaces, quick variation, and masks. Resolution never runs out.

## Avoid when
The asset ships to a game engine or glTF without a baking step, or must match a reference photograph or painted style exactly.

## Tradeoffs
Procedural graphs are small and editable but render-engine specific and costly per pixel. Images are predictable, portable and fast but fixed in resolution and need UVs. **Procedural nodes do not export to glTF.** They must be baked to images first; this server has no baking tool yet, so bake in Blender or by script and verify the result.

## Pattern
Use object coordinates so the pattern keeps a real size in meters. A noise value drives color and roughness together, which reads as one material.

```python
material = bpy.data.materials.new("GuideClay")
material.use_nodes = True
tree = material.node_tree
shader = next(node for node in tree.nodes if node.type == "BSDF_PRINCIPLED")

coordinates = tree.nodes.new("ShaderNodeTexCoord")
mapping = tree.nodes.new("ShaderNodeMapping")
mapping.inputs["Scale"].default_value = (1.0, 1.0, 1.0)  # 1 = noise features sized in object units
noise = tree.nodes.new("ShaderNodeTexNoise")
noise.inputs["Scale"].default_value = float(args.get("features_per_meter", 4.0))
noise.inputs["Detail"].default_value = 6.0
color = tree.nodes.new("ShaderNodeValToRGB")
stops = color.color_ramp.elements
stops[0].position, stops[0].color = 0.35, (0.22, 0.09, 0.04, 1.0)
stops[1].position, stops[1].color = 0.65, (0.36, 0.17, 0.08, 1.0)
rough = tree.nodes.new("ShaderNodeMapRange")
rough.inputs["From Min"].default_value, rough.inputs["From Max"].default_value = 0.3, 0.7
rough.inputs["To Min"].default_value, rough.inputs["To Max"].default_value = 0.55, 0.85

tree.links.new(coordinates.outputs["Object"], mapping.inputs["Vector"])
tree.links.new(mapping.outputs["Vector"], noise.inputs["Vector"])
tree.links.new(noise.outputs["Fac"], color.inputs["Fac"])
tree.links.new(color.outputs["Color"], shader.inputs["Base Color"])
tree.links.new(noise.outputs["Fac"], rough.inputs["Value"])
tree.links.new(rough.outputs["Result"], shader.inputs["Roughness"])
__result__ = {"material": material.name}
```

Without Python, build the same graph with `blender_shader_graph_edit`.

## Pitfalls
- One noise for everything at one size reads as "computer noise". Combine two or three scales with different strengths.
- Generated coordinates stretch with object dimensions; object coordinates keep a physical size but change if you scale the mesh.
- Seams appear when a 2D procedural pattern is baked without padding or tiling.
- Names and settings of texture nodes change between Blender versions; inspect before editing.

## Checks
Preview with `blender_material_preview` on a sphere and a cube, then on the real object. Run `blender_material_diagnose(profile="gltf")` before export; it reports procedural nodes as unsupported.
