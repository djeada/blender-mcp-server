<!-- {"version": 1, "domain": "surfacing", "title": "PBR materials",
"summary": "Set metallic-roughness materials with believable values and correct color spaces for texture maps.",
"tags": ["pbr", "material", "shader", "metal", "roughness", "metallic", "texture", "normal-map", "color", "wood", "stone", "skin", "game"],
"related": ["uv-unwrapping", "game-optimization", "hard-surface"]} -->
# PBR materials

## Use when
Nearly every surface meant to look physical, in renders or engines that follow the metallic-roughness model, as glTF does.

## Avoid when
The style is deliberately flat or toon shaded.

## Tradeoffs
A few parameters give consistent results under any lighting. Believability depends more on roughness variation than on color detail.

## Values
Metallic is 0 or 1; in-between values are for dirt or transitions only. Typical roughness: polished metal 0.1–0.25, brushed or worn metal 0.3–0.5, painted surface 0.35–0.6, wood 0.5–0.8, stone and cloth 0.7–0.95, skin about 0.45. Non-metal base colors stay roughly between 0.02 and 0.8 in linear values; avoid pure black and pure white.

## Pattern

```python
def material(name, color, metallic, roughness):
    mat = bpy.data.materials.new(name)
    mat.use_nodes = True
    shader = next(node for node in mat.node_tree.nodes if node.type == "BSDF_PRINCIPLED")
    shader.inputs["Base Color"].default_value = (*color, 1.0)
    shader.inputs["Metallic"].default_value = metallic
    shader.inputs["Roughness"].default_value = roughness
    mat.diffuse_color = (*color, 1.0)  # viewport color
    return mat


steel = material("GuideSteel", (0.55, 0.56, 0.58), 1.0, 0.3)
leather = material("GuideLeather", (0.09, 0.035, 0.015), 0.0, 0.7)
__result__ = {"materials": [steel.name, leather.name]}
```

## Pitfalls
- Roughness, metallic and normal images are data: set `image.colorspace_settings.name = "Non-Color"`. Only color maps stay sRGB.
- A normal image goes through a Normal Map node, never straight into the Normal input.
- OpenGL and DirectX normal maps differ in the green channel.
- Typed tools set base color and a base color texture only; other channels need a script.
- Complex node graphs are usually lost on export. Bake them to images.

## Checks
Capture in `material` mode from `three_quarter`. Its fixed lights compare materials fairly but are not your scene lighting; also render with `blender_render_still`. After a glTF export, re-import or view the file to confirm which maps survived.
