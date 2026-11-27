<!-- {"version": 1, "domain": "surfacing", "title": "Mapping, scale, texel density and color spaces",
"summary": "Place textures at a real-world scale with consistent density, correct color spaces and the right relief method.",
"tags": ["texture", "mapping", "texel", "density", "scale", "tiling", "color-space", "triplanar", "box", "object", "uv", "normal-map", "bump", "displacement"],
"related": ["uv-unwrapping", "texture-pipeline", "procedural-materials"]} -->
# Mapping, scale, texel density and color spaces

## Use when
Any textured surface, before choosing resolutions or judging detail. Wrong scale makes good textures look fake.

## Avoid when
The surface is a flat color with no maps.

## Tradeoffs
- **UV mapping** exports everywhere and follows deformation, but needs unwrapping and has seams.
- **Object coordinates** need no UVs and stick to a moving object, but stretch on faces parallel to an axis and do not export to glTF.
- **Box (triplanar) projection** on an Image Texture node (`projection` `BOX` with a blend) avoids stretching without UVs. It is a Blender render feature; engines need their own triplanar shader or baked UVs.

**Texel density** is texture pixels per meter. Pick one for the asset class (for example 512 px/m for props seen at arm's length, more for a hero close-up) and keep neighbouring objects similar. **Relief:** a normal map or bump only changes shading, so the silhouette stays smooth; displacement moves geometry, needs dense meshes and is for forms visible in outline.

**Color spaces:** color images (base color, emission) are sRGB. Roughness, metallic, normal, occlusion, opacity and height are data: Non-Color. Alpha is always linear.

## Pattern
Measure the density the UVs give, from the ratio of UV area to surface area.

```python
import math

resolution = int(args.get("resolution", 1024))
mesh = bpy.data.meshes.new("GuideDensity")
mesh.from_pydata([(0, 0, 0), (4, 0, 0), (4, 2, 0), (0, 2, 0)], [], [(0, 1, 2, 3)])
layer = mesh.uv_layers.new(name="UVMap")
for index, uv in enumerate([(0, 0), (1, 0), (1, 0.5), (0, 0.5)]):
    if hasattr(layer, "uv"):
        layer.uv[index].vector = uv
    else:  # before Blender 3.5
        layer.data[index].uv = uv
obj = bpy.data.objects.new("GuideDensity", mesh)
bpy.context.scene.collection.objects.link(obj)


def area_2d(points):
    return abs(sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:] + points[:1]))) / 2


uv_area = world_area = 0.0
for polygon in mesh.polygons:
    corners = []
    for loop in polygon.loop_indices:
        corners.append(tuple(layer.uv[loop].vector if hasattr(layer, "uv") else layer.data[loop].uv))
    uv_area += area_2d(corners)
    world_area += polygon.area * obj.scale.x * obj.scale.y  # assumes uniform scale
texels_per_meter = resolution * math.sqrt(uv_area / world_area)
__result__ = {"texels_per_meter": round(texels_per_meter, 1), "object": obj.name}
```

To change tiling of a bound texture set, pass `mapping={"scale": [2, 2]}` to `blender_material_set_texture_set`; glTF carries it as `KHR_texture_transform`, which not every viewer supports.

## Pitfalls
- Unapplied object scale changes density without changing UVs.
- An image used as both color and data needs two datablocks; a shared one cannot be both sRGB and Non-Color.
- Mixing OpenGL and DirectX normal maps inverts relief in one direction. Ask which the source uses.
- Bump strength depends on scale: a value right for a brick is far too strong for a pore.

## Checks
Apply a checker image and view with `blender_view_capture(mode="material")`: squares should be square and the same size across parts. Run `blender_material_diagnose` for color-space and mapping problems. Compare capture sizes against real object sizes: grain, pores and bricks have known dimensions.
