<!-- {"version": 1, "domain": "delivery", "title": "Texture budgets, packing and export",
"summary": "Choose resolutions and channel packing for game or offline targets, check export support and preview consistently.",
"tags": ["pipeline", "budget", "resolution", "memory", "orm", "packing", "channel", "atlas", "export", "gltf", "game", "engine", "mipmap", "bake", "offline", "texture"],
"related": ["texture-mapping", "game-optimization", "pbr-materials"]} -->
# Texture budgets, packing and export

## Use when
Before creating maps for an engine or web viewer, and again before delivery.

## Avoid when
A one-off offline render where memory is not a constraint.

## Tradeoffs
Larger textures hold more detail but cost memory and load time. Packing saves memory and samples but ties channels to one resolution and can bleed between channels under some compression.

**Decisions.** Game assets: one material per asset where possible, power-of-two sizes, maps baked to images, occlusion, roughness and metallic packed as R, G and B (glTF's layout), OpenGL normals for glTF. Offline renders: more materials and procedural detail are fine, and resolution follows the closest camera. Choose resolution from texel density times the surface size, not by habit. Baking and UV tools are planned separately; this server does not bake yet.

## Pattern
Estimate uncompressed memory before creating maps: four bytes per pixel, plus a third for mipmaps.

```python
def megabytes(width, height, bytes_per_channel=1):
    return width * height * 4 * bytes_per_channel * 4 / 3 / (1024 * 1024)


maps = args.get("maps") or {"base_color": 2048, "normal": 2048, "orm": 2048, "emission": 1024}
sizes = {name: round(megabytes(size, size), 1) for name, size in maps.items()}
power_of_two = all(size & (size - 1) == 0 for size in maps.values())
__result__ = {"megabytes": sizes, "total": round(sum(sizes.values()), 1), "power_of_two": power_of_two}
```

GPU compression usually reduces this several times; the figure is for comparing choices.

**What glTF carries:** base color, metallic-roughness, normal (OpenGL), occlusion, emission, alpha blend or mask, and UV transforms through an extension. It does **not** carry procedural nodes, color ramps, bump or height, displacement, occlusion multiplied into color, or flipped DirectX normals.

## Pitfalls
- Four separate grayscale maps where one packed image would do.
- Preview lighting that differs for each asset hides inconsistency.
- Assuming an engine reads channels the same way as glTF; check its documentation.

## Checks
`blender_material_diagnose(profile="gltf" or "mobile")` checks sizes, memory, color spaces and export limits. Preview every asset with `blender_material_preview` so lighting is identical, then export and open the file in the target.
