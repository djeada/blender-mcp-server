<!-- {"version": 1, "domain": "surfacing", "title": "Stylized and hand-painted textures",
"summary": "Design readable flat colors, gradients and toon bands that follow the style instead of physical realism.",
"tags": ["stylized", "hand-painted", "handpainted", "cartoon", "toon", "cel", "flat", "gradient", "painterly", "lowpoly", "low-poly", "texture", "color", "character"],
"related": ["pbr-materials", "organic-surfaces", "texture-pipeline"]} -->
# Stylized and hand-painted textures

## Use when
Cartoon, painterly, low-poly or hand-painted art direction, where readability and shape matter more than physical accuracy.

## Avoid when
The target is photorealism, or a game that relies on physically based lighting for consistency across assets.

## Tradeoffs
Painted-in light and shadow give strong, controllable style but fight real-time lighting when the light moves. Keep painted lighting subtle if the engine lights the asset. Flat palettes are cheap and clear but need good shapes to carry them.

Principles: a small palette with one dominant, one secondary and one accent color; value (light and dark) separates forms more than hue; warmer lights with cooler shadows; large clean areas with detail only where the eye should go; edges and gradients that follow the form.

## Pattern
A vertical gradient with hard bands, driven by object height, needs no images or UVs.

```python
material = bpy.data.materials.new("GuideToonGradient")
material.use_nodes = True
tree = material.node_tree
shader = next(node for node in tree.nodes if node.type == "BSDF_PRINCIPLED")
coordinates = tree.nodes.new("ShaderNodeTexCoord")
split = tree.nodes.new("ShaderNodeSeparateXYZ")
height = tree.nodes.new("ShaderNodeMapRange")
height.inputs["From Min"].default_value, height.inputs["From Max"].default_value = -1.0, 1.0  # object units
bands = tree.nodes.new("ShaderNodeValToRGB")
bands.color_ramp.interpolation = "CONSTANT"
elements = bands.color_ramp.elements
elements[0].position, elements[0].color = 0.0, (0.05, 0.12, 0.05, 1.0)  # cool, dark base
elements[1].position, elements[1].color = 0.45, (0.18, 0.35, 0.08, 1.0)  # main color
top = elements.new(0.8)
top.color = (0.45, 0.55, 0.12, 1.0)  # warm highlight
shader.inputs["Roughness"].default_value = 0.9
tree.links.new(coordinates.outputs["Object"], split.inputs["Vector"])
tree.links.new(split.outputs["Z"], height.inputs["Value"])
tree.links.new(height.outputs["Result"], bands.inputs["Fac"])
tree.links.new(bands.outputs["Color"], shader.inputs["Base Color"])
__result__ = {"material": material.name}
```

For painted textures, paint or generate an sRGB color image on clean UVs and bind it as `base_color`. A node gradient like this one does not export to glTF; bake it to an image or vertex colors first.

## Pitfalls
- Mid-grey everywhere: push value contrast between major forms.
- Photographic noise on stylized shapes reads as dirt.
- Toon bands made from lighting need engine-specific shaders; color-ramp bands from height do not react to light.
- Very high saturation clips in bright light; check under the final lighting.

## Checks
Squint test: a small, desaturated capture should still separate the main forms. Preview with `blender_view_capture(mode="material")` and the project lighting (`lighting="scene"`).
