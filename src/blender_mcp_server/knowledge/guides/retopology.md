<!-- {"version": 1, "domain": "modeling", "title": "Retopology with a shrinkwrapped cage",
"summary": "Rebuild a light, deformable mesh over a dense surface and keep the dense one for baking.",
"tags": ["retopology", "retopo", "shrinkwrap", "low-poly", "cage", "deformation", "game", "high-poly", "creature", "realistic"],
"related": ["sculpting-remeshing", "uv-unwrapping", "rigging", "game-optimization"]} -->
# Retopology with a shrinkwrapped cage

## Use when
A dense, uneven source (voxel result, scan, boolean soup) must animate, take UVs or run in real time.

## Avoid when
The source already has usable quads, or the asset is a static render where density does not matter. Decimation is enough for some distant static props.

## Tradeoffs
A cage built on purpose gives loops where the form bends, but automatic wrapping only places vertices; it does not design edge flow. For characters, build the cage from lofted parts (see organic-modeling) so that joints have loops, then wrap it.

## Pattern

```python
import bmesh


def make(name, build):
    mesh = bpy.data.meshes.new(name)
    bm = bmesh.new()
    build(bm)
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj


def dense(bm):
    bmesh.ops.create_icosphere(bm, subdivisions=5, radius=1.0)


def cage_shape(bm):
    bmesh.ops.create_cube(bm, size=2.4)
    bmesh.ops.subdivide_edges(bm, edges=bm.edges, cuts=5, use_grid_fill=True)


high = make("GuideHigh", dense)
low = make("GuideLow", cage_shape)
wrap = low.modifiers.new("Wrap", "SHRINKWRAP")
wrap.target = high
wrap.wrap_method = "NEAREST_SURFACEPOINT"
__result__ = {"high": high.name, "low": low.name}
```

## Pitfalls
- Nearest-point wrapping collapses vertices in tight folds, between fingers or lips. Keep the cage close, or use `PROJECT` with a chosen axis.
- Hide the dense mesh from render only after you have compared both.
- Apply the modifier before unwrapping or weighting if the final vertex positions matter.

## Checks
Compare `counts.evaluated` of the cage with your budget. Inspect it for `zero_area_faces` and non-manifold edges, which collapsed vertices cause. Capture both meshes in the same view and compare silhouettes; use `wireframe` to review loops at joints.
