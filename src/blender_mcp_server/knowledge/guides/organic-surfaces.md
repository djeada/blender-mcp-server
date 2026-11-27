<!-- {"version": 1, "domain": "art-direction", "title": "Skin, leather and cloth",
"summary": "Vary color and roughness by anatomy and use: skin zones, creased leather and woven fabric.",
"tags": ["skin", "leather", "cloth", "fabric", "creature", "character", "anatomy", "subsurface", "pores", "weave", "hide", "texture"],
"related": ["anatomy-proportions", "material-layering", "stylized-texturing"]} -->
# Skin, leather and cloth

## Use when
Characters, creatures, clothing, bags, straps and soft furnishings.

## Avoid when
The surface is hard or the character is deliberately flat shaded (see stylized-texturing).

## Tradeoffs
Believable skin comes mostly from variation, not from a perfect base color. Subsurface scattering adds softness in renders but engines and glTF support it unevenly.

**Skin zones:** thin skin over blood (nose, ears, cheeks, knuckles, lips) is redder; skin over bone (forehead) is paler and yellower; around eyes and in folds is darker and cooler. Oily areas (nose, forehead, lips) are smoother (roughness about 0.35); elsewhere about 0.45–0.6. Creature skin follows the same logic: thicker, rougher, darker on exposed backs, softer and lighter underneath, with scale or wrinkle size changing by body region and bending direction.

**Leather:** rough, non-metal; creases run across the bending direction; edges and contact points polish and lighten. **Cloth:** high roughness, little specular; the weave sets a real-world repeat size; folds and seams carry the form; worn fabric fades where it rubs.

## Pattern
Broad color zones plus fine roughness variation, in object coordinates so sizes are physical.

```python
material = bpy.data.materials.new("GuideCreatureSkin")
material.use_nodes = True
tree = material.node_tree
nodes, links = tree.nodes, tree.links
shader = next(node for node in nodes if node.type == "BSDF_PRINCIPLED")
coordinates = nodes.new("ShaderNodeTexCoord")


def noise(scale, detail=4.0):
    node = nodes.new("ShaderNodeTexNoise")
    node.inputs["Scale"].default_value = scale
    node.inputs["Detail"].default_value = detail
    links.new(coordinates.outputs["Object"], node.inputs["Vector"])
    return node


zones = nodes.new("ShaderNodeValToRGB")
elements = zones.color_ramp.elements
elements[0].position, elements[0].color = 0.4, (0.09, 0.14, 0.04, 1.0)
elements[1].position, elements[1].color = 0.62, (0.2, 0.25, 0.08, 1.0)
links.new(noise(1.5).outputs["Fac"], zones.inputs["Fac"])
links.new(zones.outputs["Color"], shader.inputs["Base Color"])

roughness = nodes.new("ShaderNodeMapRange")
roughness.inputs["From Min"].default_value, roughness.inputs["From Max"].default_value = 0.3, 0.7
roughness.inputs["To Min"].default_value, roughness.inputs["To Max"].default_value = 0.4, 0.65
links.new(noise(12.0, 2.0).outputs["Fac"], roughness.inputs["Value"])
links.new(roughness.outputs["Result"], shader.inputs["Roughness"])

subsurface = shader.inputs.get("Subsurface Weight") or shader.inputs.get("Subsurface")
subsurface.default_value = 0.1  # renamed in Blender 4.0; its scale settings depend on the model size
__result__ = {"material": material.name}
```

## Pitfalls
- One flat flesh color looks like plastic or clay.
- Pores and weave at the wrong size are immediately wrong; check real dimensions.
- Strong subsurface on a small model glows like wax.
- These nodes do not export to glTF; bake maps for engines.

## Checks
Use `blender_view_capture(mode="material")` front and three-quarter views, then your lighting rig. Zones should be visible but quiet; roughness should change the highlights across the face.
