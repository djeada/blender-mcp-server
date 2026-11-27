<!-- {"version": 1, "domain": "surfacing", "title": "Layering, masks, wear and decals",
"summary": "Layer rust, paint, dirt and decals with masks placed where wear really happens, in a clear detail hierarchy.",
"tags": ["layer", "layering", "mask", "decal", "wear", "dirt", "rust", "rusty", "weathered", "edge", "scratch", "grunge", "paint", "damage"],
"related": ["hard-materials", "procedural-materials", "texture-pipeline"]} -->
# Layering, masks, wear and decals

## Use when
A surface has a history: paint over metal, rust under chips, dirt in corners, stickers and signs.

## Avoid when
The object should look new, or the target budget allows one simple material only.

## Tradeoffs
Layers built in nodes stay editable but must be baked for engines. Baked layers are portable but fixed. Decals as separate planes or textures keep resolution where needed but add draw calls and can z-fight.

**Wear is not random.** Edges and handles polish and chip; rust and dirt collect in crevices, under horizontal ledges and where water sits or drips; the lowest parts are dirtiest. Keep most of the surface intact: wear that is everywhere stops reading as wear. Build detail in order: large color and material zones, then medium chips and streaks, then fine grain.

## Pattern
One mask drives color, roughness and metallic together: rust is a rough non-metal over smooth metal. Here, rust grows from the bottom with noisy edges.

```python
material = bpy.data.materials.new("GuideRustedSteel")
material.use_nodes = True
tree = material.node_tree
nodes, links = tree.nodes, tree.links
shader = next(node for node in nodes if node.type == "BSDF_PRINCIPLED")

coordinates = nodes.new("ShaderNodeTexCoord")
split = nodes.new("ShaderNodeSeparateXYZ")
noise = nodes.new("ShaderNodeTexNoise")
noise.inputs["Scale"].default_value = 5.0
noise.inputs["Detail"].default_value = 8.0
wobble = nodes.new("ShaderNodeMath")
wobble.operation = "MULTIPLY_ADD"
wobble.inputs[1].default_value, wobble.inputs[2].default_value = 1.6, -0.8
height = nodes.new("ShaderNodeMath")
height.operation = "ADD"
mask = nodes.new("ShaderNodeValToRGB")  # white where rusty: low places
elements = mask.color_ramp.elements
elements[0].position, elements[0].color = 0.0, (1, 1, 1, 1)
elements[1].position, elements[1].color = 0.12, (0, 0, 0, 1)

links.new(coordinates.outputs["Object"], split.inputs["Vector"])
links.new(coordinates.outputs["Object"], noise.inputs["Vector"])
links.new(noise.outputs["Fac"], wobble.inputs[0])
links.new(split.outputs["Z"], height.inputs[0])
links.new(wobble.outputs[0], height.inputs[1])
links.new(height.outputs[0], mask.inputs["Fac"])


def blend(socket_name, steel, rust, is_color=False):
    mix = nodes.new("ShaderNodeMix")  # Blender 3.4+
    mix.data_type = "RGBA" if is_color else "FLOAT"
    a, b, out = (6, 7, 2) if is_color else (2, 3, 0)  # sockets of each data type
    mix.inputs[a].default_value = steel
    mix.inputs[b].default_value = rust
    links.new(mask.outputs["Color"], mix.inputs[0])
    links.new(mix.outputs[out], shader.inputs[socket_name])


blend("Base Color", (0.45, 0.46, 0.48, 1), (0.23, 0.07, 0.02, 1), is_color=True)
blend("Metallic", 1.0, 0.0)
blend("Roughness", 0.32, 0.85)
__result__ = {"material": material.name}
```

## Pitfalls
- Rust left metallic looks like orange chrome.
- Procedural edge detection (the Geometry node's pointiness) works only in Cycles and depends on mesh density.
- Uniform noise everywhere is the commonest mistake. Tie each effect to a cause.
- These node layers do not export to glTF; bake color, metallic-roughness and normal maps.

## Checks
Preview at several distances. Ask where water, hands and impacts would act, and whether the mask agrees. Compare with reference photographs of the same material.
