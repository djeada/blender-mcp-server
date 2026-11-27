"""Read-only mesh inspection and topology diagnostics.

Nothing here writes to Blender data. Triangle counts are derived from corner counts
instead of tessellating, and evaluated meshes are temporary and always released.
"""

import math
from collections import Counter

import bpy

from .protocol import BridgeError, MissingResourceError, UnsupportedError

MAX_LISTED = 64  # material slots, vertex groups and modifiers
MIN_SPATIAL_TOLERANCE = 1e-12  # below this, duplicate vertices must match exactly

_MESSAGES = {
    "non_finite_vertices": ("error", "vertex", "Vertices have NaN or infinite coordinates"),
    "non_manifold_edges": ("error", "edge", "Edges are shared by more than two faces"),
    "zero_area_faces": ("error", "face", "Faces are no wider than the tolerance"),
    "inconsistent_winding": ("error", "edge", "Adjacent faces cross these edges in the same direction"),
    "loose_vertices": ("warning", "vertex", "Vertices belong to no edge"),
    "loose_edges": ("warning", "edge", "Edges belong to no face; this may be intentional wire geometry"),
    "duplicate_vertices": (
        "warning",
        "vertex",
        "Vertices lie within the tolerance of an earlier vertex; split seams may be intentional",
    ),
    "boundary_edges": ("info", "edge", "Edges border one face; expected for open surfaces, otherwise a hole"),
}


def inspect(params: dict) -> dict:
    obj = bpy.data.objects.get(params["name"])
    if obj is None:
        raise MissingResourceError("Object not found")
    if obj.type != "MESH":
        raise UnsupportedError(f"Mesh inspection requires a MESH object, not {obj.type}")
    if obj.data.is_editmode:
        raise UnsupportedError("The mesh is in Edit Mode and its data is stale; leave Edit Mode before inspecting")
    source = params["source"]
    if source not in {"raw", "evaluated"}:
        raise ValueError("Parameter 'source' must be 'raw' or 'evaluated'")

    depsgraph = bpy.context.evaluated_depsgraph_get()
    evaluated = obj.evaluated_get(depsgraph)
    # Blender hands back the original for objects it does not evaluate, such as ones
    # disabled in viewports or excluded from the view layer. Their matrix_world is stale too.
    is_evaluated = evaluated != obj
    if source == "evaluated" and not is_evaluated:
        raise UnsupportedError(
            "Blender does not evaluate this object (disabled in viewports, excluded from the view layer, "
            "or outside the scene); use source='raw'"
        )

    evaluated_mesh = None
    try:
        if is_evaluated:
            evaluated_mesh = evaluated.to_mesh(preserve_all_data_layers=True, depsgraph=depsgraph)
        counts = {
            "raw": _counts(obj.data),
            "evaluated": None if evaluated_mesh is None else _counts(evaluated_mesh),
        }
        mesh = evaluated_mesh if source == "evaluated" else obj.data
        target = evaluated if source == "evaluated" else obj
        _require_budget(mesh, params["element_budget"], source, counts)
        report = _analyze(mesh, target, evaluated if is_evaluated else obj, params)
    finally:
        if evaluated_mesh is not None:
            evaluated.to_mesh_clear()

    notes = []
    if not is_evaluated:
        notes.append(
            "Blender does not evaluate this object, so evaluated counts are unavailable "
            "and the world transform may be stale"
        )
    shape_keys = obj.data.shape_keys
    return {
        "object": obj.name,
        "mesh": obj.data.name,
        "source": source,
        "counts": counts,
        "world_transform_current": is_evaluated,
        "shape_keys": len(shape_keys.key_blocks) if shape_keys else 0,
        "modifiers": _bounded(
            [
                {
                    "name": modifier.name,
                    "type": modifier.type,
                    "show_viewport": bool(modifier.show_viewport),
                    "show_render": bool(modifier.show_render),
                }
                for modifier in obj.modifiers
            ]
        ),
        **report,
        "notes": notes,
    }


def _counts(mesh) -> dict:
    faces = len(mesh.polygons)
    return {
        "vertices": len(mesh.vertices),
        "edges": len(mesh.edges),
        "faces": faces,
        # An n-sided face always splits into n - 2 triangles.
        "triangles": len(mesh.loops) - 2 * faces,
    }


def _require_budget(mesh, budget: int, source: str, counts: dict) -> None:
    elements = len(mesh.vertices) + len(mesh.edges) + len(mesh.loops)
    if elements > budget:
        raise BridgeError(
            "budget_exceeded",
            f"The {source} mesh has {elements} vertices, edges and face corners; element_budget is {budget}",
            details={"elements": elements, "element_budget": budget, "source": source, "counts": counts},
        )


def _analyze(mesh, target, transform_owner, params: dict) -> dict:
    tolerance = params["tolerance"]
    max_ids = params["max_ids"]
    coords = [tuple(float(value) for value in vertex.co) for vertex in mesh.vertices]
    edges = [(edge.vertices[0], edge.vertices[1]) for edge in mesh.edges]
    faces = [tuple(polygon.vertices) for polygon in mesh.polygons]
    finite = [all(math.isfinite(value) for value in co) for co in coords]

    found: dict[str, list[int]] = {"non_finite_vertices": [i for i, ok in enumerate(finite) if not ok]}

    edge_ids = {_key(a, b): index for index, (a, b) in enumerate(edges)}
    uses: list[list[bool]] = [[] for _ in edges]  # one direction flag per adjacent face
    for face in faces:
        for a, b in zip(face, face[1:] + face[:1], strict=True):
            uses[edge_ids[_key(a, b)]].append(a < b)
    found["non_manifold_edges"] = [i for i, directions in enumerate(uses) if len(directions) > 2]
    found["boundary_edges"] = [i for i, directions in enumerate(uses) if len(directions) == 1]
    found["loose_edges"] = [i for i, directions in enumerate(uses) if not directions]
    found["inconsistent_winding"] = [
        i for i, directions in enumerate(uses) if len(directions) == 2 and directions[0] == directions[1]
    ]

    connected = {index for edge in edges for index in edge}
    found["loose_vertices"] = [i for i in range(len(coords)) if i not in connected]
    found["zero_area_faces"] = [
        index
        for index, (polygon, face) in enumerate(zip(mesh.polygons, faces, strict=True))
        if all(finite[i] for i in face) and _is_degenerate(float(polygon.area), [coords[i] for i in face], tolerance)
    ]

    checks = [name for name in _MESSAGES if name != "duplicate_vertices"]
    skipped = []
    if params["check_duplicates"]:
        found["duplicate_vertices"] = _duplicates(coords, finite, tolerance)
        checks.append("duplicate_vertices")
    else:
        skipped.append({"check": "duplicate_vertices", "reason": "not requested; set check_duplicates=true"})

    findings = []
    for check, (severity, element, message) in _MESSAGES.items():
        if ids := found.get(check):
            findings.append(
                {
                    "check": check,
                    "severity": severity,
                    "element": element,
                    "count": len(ids),
                    "ids": ids[:max_ids],
                    "truncated": len(ids) > max_ids,
                    "message": message,
                }
            )
    severities = Counter(finding["severity"] for finding in findings)

    matrix = [[float(transform_owner.matrix_world[row][column]) for column in range(4)] for row in range(3)]
    local = [co for co, ok in zip(coords, finite, strict=True) if ok]
    world = [tuple(sum(row[i] * co[i] for i in range(3)) + row[3] for row in matrix) for co in local]

    report = {
        "bounds": {"local": _bounds(local), "world": _bounds(world)},
        "material_slots": _material_slots(mesh, target),
        "vertex_groups": _bounded([group.name for group in target.vertex_groups]),
        "components": _components(coords, finite, edges, faces, max_ids),
        "summary": {
            "status": "errors" if severities["error"] else "warnings" if severities["warning"] else "ok",
            "error_checks": severities["error"],
            "warning_checks": severities["warning"],
            "info_checks": severities["info"],
            # Edge-based only: faces that touch at a single vertex are not detected.
            "closed_edge_manifold": bool(faces)
            and not any(found[name] for name in ("non_manifold_edges", "boundary_edges", "loose_edges")),
        },
        "findings": findings,
        "checks_run": checks,
        "checks_skipped": skipped,
        "tolerance": tolerance,
    }
    if params["include_regions"]:
        report["regions"] = _regions(mesh, target, coords, finite, faces)
    return report


def _key(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


def _is_degenerate(area: float, points: list, tolerance: float) -> bool:
    """A face is degenerate when its width, relative to its longest side, is within tolerance."""
    longest = max(math.dist(a, b) for a, b in zip(points, points[1:] + points[:1], strict=True))
    return longest <= tolerance or 2 * area / longest <= tolerance


def _duplicates(coords: list, finite: list, tolerance: float) -> list[int]:
    """Greedy clustering in index order: each vertex is compared with earlier cluster representatives."""
    duplicates = []
    if tolerance < MIN_SPATIAL_TOLERANCE:
        seen = set()
        for index, co in enumerate(coords):
            if not finite[index]:
                continue
            if co in seen:
                duplicates.append(index)
            seen.add(co)
        return duplicates
    # Representatives are more than `tolerance` apart, so each grid cell holds only a few.
    # That keeps the search linear even when every vertex is in the same place.
    grid: dict[tuple[int, ...], list[tuple]] = {}
    offsets = [(x, y, z) for x in (-1, 0, 1) for y in (-1, 0, 1) for z in (-1, 0, 1)]
    for index, co in enumerate(coords):
        if not finite[index]:
            continue
        cell = tuple(math.floor(value / tolerance) for value in co)
        if any(
            math.dist(co, other) <= tolerance
            for offset in offsets
            for other in grid.get((cell[0] + offset[0], cell[1] + offset[1], cell[2] + offset[2]), ())
        ):
            duplicates.append(index)
        else:
            grid.setdefault(cell, []).append(co)
    return duplicates


def _components(coords: list, finite: list, edges: list, faces: list, limit: int) -> dict:
    """Group vertices connected through edges. A lone vertex is its own component."""
    parent = list(range(len(coords)))

    def root(index):
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    for a, b in edges:
        first, second = root(a), root(b)
        if first != second:
            parent[max(first, second)] = min(first, second)

    members: dict[int, list[int]] = {}
    for index in range(len(coords)):
        members.setdefault(root(index), []).append(index)
    edge_counts = Counter(root(a) for a, _ in edges)
    face_counts = Counter(root(face[0]) for face in faces)
    ordered = sorted(members, key=lambda key: (-len(members[key]), key))
    return {
        "count": len(ordered),
        "items": [
            {
                "first_vertex": key,
                "vertices": len(members[key]),
                "edges": edge_counts[key],
                "faces": face_counts[key],
                "bounds_local": _bounds([coords[i] for i in members[key] if finite[i]]),
            }
            for key in ordered[:limit]
        ],
        "truncated": len(ordered) > limit,
    }


def _material_slots(mesh, target) -> dict:
    usage = Counter(polygon.material_index for polygon in mesh.polygons)
    slots = list(target.material_slots)
    result = _bounded(
        [
            {
                "index": index,
                "material": slot.material.name if slot.material else None,
                "link": slot.link,
                "faces": usage[index],
            }
            for index, slot in enumerate(slots)
        ]
    )
    result["faces_without_slot"] = sum(count for index, count in usage.items() if index >= len(slots))
    return result


def _regions(mesh, target, coords: list, finite: list, faces: list) -> dict:
    """Local bounds of the geometry in each vertex group and material index."""
    groups: dict[int, set[int]] = {}
    for index, vertex in enumerate(mesh.vertices):
        for membership in vertex.groups:
            groups.setdefault(membership.group, set()).add(index)
    materials: dict[int, list] = {}
    for polygon, face in zip(mesh.polygons, faces, strict=True):
        materials.setdefault(polygon.material_index, []).append(face)

    def bounds(indices):
        return _bounds([coords[i] for i in sorted(indices) if finite[i]])

    return {
        "vertex_groups": _bounded(
            [
                {
                    "name": group.name,
                    "vertices": len(groups.get(group.index, ())),
                    "bounds_local": bounds(groups.get(group.index, ())),
                }
                for group in target.vertex_groups
            ]
        ),
        "materials": _bounded(
            [
                {
                    "material_index": index,
                    "faces": len(materials[index]),
                    "bounds_local": bounds({vertex for face in materials[index] for vertex in face}),
                }
                for index in sorted(materials)
            ]
        ),
    }


def _bounds(points: list) -> dict | None:
    if not points:
        return None
    low = [min(point[axis] for point in points) for axis in range(3)]
    high = [max(point[axis] for point in points) for axis in range(3)]
    return {
        "min": [round(value, 6) for value in low],
        "max": [round(value, 6) for value in high],
        "size": [round(high[axis] - low[axis], 6) for axis in range(3)],
    }


def _bounded(items: list) -> dict:
    return {"count": len(items), "items": items[:MAX_LISTED], "truncated": len(items) > MAX_LISTED}
