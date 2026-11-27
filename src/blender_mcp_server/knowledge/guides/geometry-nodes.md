<!-- {"version": 1, "domain": "modeling", "title": "Procedural modeling with modifiers and Geometry Nodes",
"summary": "Generate repetition and variation from parameters, and handle the node group API across Blender versions.",
"tags": ["procedural", "geometry-nodes", "nodes", "scatter", "instance", "array", "environment", "foliage", "city", "fence", "house", "variation"],
"related": ["modular-modeling", "curves", "game-optimization"]} -->
# Procedural modeling with modifiers and Geometry Nodes

## Use when
You need many repeats or variants that must stay editable: scattered rocks and grass, fences, windows, bolts. Try a plain modifier (Array, Mirror) first.

## Avoid when
There are a handful of unique pieces, or the target format must contain real geometry and nobody will realise the instances.

## Tradeoffs
One graph drives many results, but it is harder to write and debug from a script than direct geometry, and its API differs between versions.

## Pattern
Scatter cubes over a grid. Sockets are declared on `group.interface` from Blender 4.0 and on `inputs`/`outputs` before.

```python
group = bpy.data.node_groups.new("GuideScatter", "GeometryNodeTree")
if hasattr(group, "interface"):
    group.interface.new_socket("Geometry", in_out="INPUT", socket_type="NodeSocketGeometry")
    group.interface.new_socket("Geometry", in_out="OUTPUT", socket_type="NodeSocketGeometry")
else:
    group.inputs.new("NodeSocketGeometry", "Geometry")
    group.outputs.new("NodeSocketGeometry", "Geometry")

nodes, links = group.nodes, group.links
source = nodes.new("NodeGroupInput")
result = nodes.new("NodeGroupOutput")
points = nodes.new("GeometryNodeDistributePointsOnFaces")
cube = nodes.new("GeometryNodeMeshCube")
cube.inputs["Size"].default_value = (0.15, 0.15, 0.15)
instances = nodes.new("GeometryNodeInstanceOnPoints")
join = nodes.new("GeometryNodeJoinGeometry")
points.inputs["Density"].default_value = 4.0
points.inputs["Seed"].default_value = int(args.get("seed", 3))

links.new(source.outputs[0], points.inputs["Mesh"])
links.new(points.outputs["Points"], instances.inputs["Points"])
links.new(cube.outputs[0], instances.inputs["Instance"])
links.new(instances.outputs[0], join.inputs[0])
links.new(source.outputs[0], join.inputs[0])
links.new(join.outputs[0], result.inputs[0])

mesh = bpy.data.meshes.new("GuideGround")
mesh.from_pydata([(-2, -2, 0), (2, -2, 0), (2, 2, 0), (-2, 2, 0)], [], [(0, 1, 2, 3)])
obj = bpy.data.objects.new("GuideGround", mesh)
bpy.context.scene.collection.objects.link(obj)
modifier = obj.modifiers.new("Scatter", "NODES")
modifier.node_group = group
__result__ = {"object": obj.name, "node_group": group.name}
```

## Pitfalls
- Fix random seeds so results can be reproduced.
- Instances are not real geometry: `blender_mesh_inspect` counts do not include them unless the graph ends with Realize Instances.
- Realizing thousands of instances can produce millions of triangles.
- Look sockets up by name only for nodes whose names are stable in your versions; test on the version you target.

## Checks
`blender_view_capture` frames and renders instances, so use it to judge density and overlap. Compare `counts.raw` with `counts.evaluated` to see what the graph realizes.
