"""Tests for read-only mesh inspection."""

import math
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

IDENTITY = [[1, 0, 0, 0], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]

CUBE_VERTICES = [(x, y, z) for x in (0, 1) for y in (0, 1) for z in (0, 1)]
CUBE_FACES = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]


def _area(points):
    """Newell's method, which matches Blender for planar polygons."""
    normal = [0.0, 0.0, 0.0]
    for a, b in zip(points, points[1:] + points[:1], strict=True):
        for i in range(3):
            j, k = (i + 1) % 3, (i + 2) % 3
            normal[i] += (a[j] - b[j]) * (a[k] + b[k])
    return math.hypot(*normal) / 2


def _mesh(vertices, faces=(), loose_edges=(), materials=None, groups=None):
    edges = dict.fromkeys(tuple(sorted(edge)) for edge in loose_edges)
    for face in faces:
        edges.update(dict.fromkeys(tuple(sorted(pair)) for pair in zip(face, face[1:] + face[:1], strict=True)))
    polygons = [
        SimpleNamespace(
            vertices=list(face),
            area=_area([vertices[i] for i in face]),
            material_index=materials[index] if materials else 0,
        )
        for index, face in enumerate(faces)
    ]
    return SimpleNamespace(
        name="Mesh",
        is_editmode=False,
        shape_keys=None,
        vertices=[
            SimpleNamespace(co=co, groups=[SimpleNamespace(group=g) for g in (groups or {}).get(i, ())])
            for i, co in enumerate(vertices)
        ],
        edges=[SimpleNamespace(vertices=list(edge)) for edge in edges],
        polygons=polygons,
        loops=[None] * sum(len(face) for face in faces),
    )


class _Object:
    """An object whose evaluated copy is distinct, as Blender's is."""

    def __init__(self, mesh, evaluated_mesh=None, *, is_evaluated=True, matrix=IDENTITY):
        self.name = "Thing"
        self.type = "MESH"
        self.data = mesh
        self.matrix_world = matrix
        self.modifiers = []
        self.material_slots = []
        self.vertex_groups = []
        self.released = 0
        self.evaluated = self
        if is_evaluated:
            self.evaluated = SimpleNamespace(
                matrix_world=matrix,
                material_slots=self.material_slots,
                vertex_groups=self.vertex_groups,
                to_mesh=MagicMock(return_value=evaluated_mesh or mesh),
                to_mesh_clear=self._release,
            )

    def _release(self):
        self.released += 1

    def evaluated_get(self, depsgraph):
        return self.evaluated


@pytest.fixture
def inspect(handler, mock_bpy):
    def run(obj, **params):
        mock_bpy.data.objects.get = lambda name: obj if name == obj.name else None
        return handler.handle("mesh.inspect", {"name": obj.name, **params})

    return run


def _findings(report):
    return {finding["check"]: finding for finding in report["findings"]}


def test_clean_cube(inspect):
    obj = _Object(_mesh(CUBE_VERTICES, CUBE_FACES))
    report = inspect(obj, check_duplicates=True)
    assert report["counts"]["raw"] == {"vertices": 8, "edges": 12, "faces": 6, "triangles": 12}
    assert report["findings"] == []
    assert report["summary"]["status"] == "ok"
    assert report["summary"]["closed_edge_manifold"] is True
    assert report["components"]["count"] == 1
    assert report["bounds"]["local"] == {"min": [0, 0, 0], "max": [1, 1, 1], "size": [1, 1, 1]}
    assert report["checks_skipped"] == []
    assert obj.released == 1


def test_open_plane_is_informational(inspect):
    report = inspect(_Object(_mesh([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)], [(0, 1, 2, 3)])))
    assert report["summary"]["status"] == "ok"
    assert report["summary"]["closed_edge_manifold"] is False
    assert _findings(report)["boundary_edges"]["severity"] == "info"
    assert _findings(report)["boundary_edges"]["count"] == 4
    assert report["checks_skipped"][0]["check"] == "duplicate_vertices"
    assert "duplicate_vertices" not in report["checks_run"]


def test_disconnected_components_are_ordered_by_size(inspect):
    vertices = [(9, 9, 9), (0, 0, 0), (1, 0, 0), (0, 1, 0), (5, 0, 0), (6, 0, 0), (6, 1, 0), (5, 1, 0)]
    report = inspect(_Object(_mesh(vertices, [(1, 2, 3), (4, 5, 6, 7)])), max_ids=2)
    components = report["components"]
    assert components["count"] == 3
    assert components["truncated"] is True
    assert [(item["first_vertex"], item["vertices"], item["faces"]) for item in components["items"]] == [
        (4, 4, 1),
        (1, 3, 1),
    ]
    assert components["items"][0]["bounds_local"]["min"] == [5, 0, 0]


def test_defective_mesh_reports_each_problem(inspect):
    vertices = [
        (0, 0, 0),
        (1, 0, 0),
        (0, 1, 0),
        (0, -1, 0),
        (0, 0, 1),  # 0-4: three faces on edge 0-1
        (2, 0, 0),  # 5: collinear with 0 and 1
        (3, 3, 3),  # 6: loose vertex
        (4, 4, 4),
        (5, 4, 4),  # 7-8: loose edge
        (1, 0, 0),  # 9: duplicate of 1
    ]
    # Faces 0 and 1 both walk edge 0-1 forwards.
    faces = [(0, 1, 2), (0, 1, 3), (1, 0, 4), (0, 1, 5)]
    report = inspect(_Object(_mesh(vertices, faces, loose_edges=[(7, 8)])), check_duplicates=True)
    findings = _findings(report)
    assert findings["non_manifold_edges"]["ids"] == [1]  # edge 0 is the loose one
    assert findings["zero_area_faces"]["ids"] == [3]
    assert findings["loose_vertices"]["ids"] == [6, 9]
    assert findings["loose_edges"]["count"] == 1
    assert findings["duplicate_vertices"]["ids"] == [9]
    assert report["summary"]["status"] == "errors"
    assert [finding["check"] for finding in report["findings"]] == [
        "non_manifold_edges",
        "zero_area_faces",
        "loose_vertices",
        "loose_edges",
        "duplicate_vertices",
        "boundary_edges",
    ]


@pytest.mark.parametrize(("second_face", "inconsistent"), [((2, 1, 3), False), ((1, 2, 3), True)])
def test_winding(inspect, second_face, inconsistent):
    vertices = [(0, 0, 0), (1, 0, 0), (0, 1, 0), (1, 1, 0)]
    findings = _findings(inspect(_Object(_mesh(vertices, [(0, 1, 2), second_face]))))
    assert ("inconsistent_winding" in findings) is inconsistent


def test_duplicate_tolerance_crosses_grid_cells(inspect):
    vertices = [(0.0999, 0, 0), (0.1001, 0, 0), (0.5, 0, 0), (0.5, 0, 0)]
    loose = _Object(_mesh(vertices))
    assert _findings(inspect(loose, check_duplicates=True, tolerance=0.1))["duplicate_vertices"]["ids"] == [1, 3]
    assert _findings(inspect(loose, check_duplicates=True, tolerance=0))["duplicate_vertices"]["ids"] == [3]


def test_many_coincident_vertices_stay_linear(inspect):
    report = inspect(_Object(_mesh([(1, 1, 1)] * 50_000)), check_duplicates=True, max_ids=0)
    finding = _findings(report)["duplicate_vertices"]
    assert finding["count"] == 49_999
    assert finding["ids"] == [] and finding["truncated"] is True


def test_non_finite_vertices_do_not_leak_into_results(inspect):
    import json

    mesh = _mesh([(0, 0, 0), (1, 0, 0), (float("nan"), 1, 0)], [(0, 1, 2)])
    report = inspect(_Object(mesh), check_duplicates=True, include_regions=True)
    assert _findings(report)["non_finite_vertices"]["ids"] == [2]
    assert report["bounds"]["world"]["max"] == [1, 0, 0]
    json.dumps(report, allow_nan=False)


def test_evaluated_source_and_world_transform(inspect):
    raw = _mesh(CUBE_VERTICES, CUBE_FACES)
    modified = _mesh([(0, 0, 0), (2, 0, 0), (0, 2, 0)], [(0, 1, 2)])
    # 90 degrees about Z, then translated along X.
    matrix = [[0, -1, 0, 10], [1, 0, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]]
    obj = _Object(raw, modified, matrix=matrix)
    obj.modifiers = [SimpleNamespace(name="Gen", type="NODES", show_viewport=True, show_render=False)]

    raw_report = inspect(obj)
    assert raw_report["counts"]["raw"]["faces"] == 6
    assert raw_report["counts"]["evaluated"]["faces"] == 1
    assert raw_report["bounds"]["local"]["size"] == [1, 1, 1]

    report = inspect(obj, source="evaluated")
    assert report["bounds"]["local"]["size"] == [2, 2, 0]
    assert report["bounds"]["world"] == {"min": [8, 0, 0], "max": [10, 2, 0], "size": [2, 2, 0]}
    assert report["modifiers"]["items"][0]["show_render"] is False
    assert obj.released == 2


def test_unevaluated_object(inspect):
    obj = _Object(_mesh(CUBE_VERTICES, CUBE_FACES), is_evaluated=False)
    report = inspect(obj)
    assert report["counts"]["evaluated"] is None
    assert report["world_transform_current"] is False
    assert report["notes"]
    with pytest.raises(ValueError, match="does not evaluate"):
        inspect(obj, source="evaluated")


def test_materials_groups_and_regions(inspect):
    obj = _Object(_mesh(CUBE_VERTICES, CUBE_FACES, materials=[0, 0, 1, 1, 1, 5], groups={0: [0], 1: [0]}))
    obj.material_slots.extend(
        [
            SimpleNamespace(material=SimpleNamespace(name="Steel"), link="DATA"),
            SimpleNamespace(material=None, link="OBJECT"),
        ]
    )
    obj.vertex_groups.extend([SimpleNamespace(name="hand", index=0), SimpleNamespace(name="empty", index=1)])
    report = inspect(obj, include_regions=True)
    assert [(slot["material"], slot["faces"]) for slot in report["material_slots"]["items"]] == [
        ("Steel", 2),
        (None, 3),
    ]
    assert report["material_slots"]["faces_without_slot"] == 1
    assert report["vertex_groups"]["items"] == ["hand", "empty"]
    hand, empty = report["regions"]["vertex_groups"]["items"]
    assert hand["vertices"] == 2 and hand["bounds_local"]["size"] == [0, 0, 1]
    assert empty["vertices"] == 0 and empty["bounds_local"] is None
    assert [item["material_index"] for item in report["regions"]["materials"]["items"]] == [0, 1, 5]


def test_long_lists_are_bounded(inspect):
    obj = _Object(_mesh(CUBE_VERTICES, CUBE_FACES))
    obj.vertex_groups.extend(SimpleNamespace(name=f"g{i}", index=i) for i in range(100))
    groups = inspect(obj)["vertex_groups"]
    assert (groups["count"], len(groups["items"]), groups["truncated"]) == (100, 64, True)


def test_budget_failure_is_explicit_and_releases_temporary_mesh(inspect, addon_module):
    obj = _Object(_mesh(CUBE_VERTICES, CUBE_FACES))
    with pytest.raises(addon_module.protocol.BridgeError) as error:
        inspect(obj, element_budget=43)
    assert error.value.code == "budget_exceeded"
    assert error.value.details["elements"] == 44
    assert error.value.details["counts"]["raw"]["faces"] == 6
    assert obj.released == 1


def test_temporary_mesh_is_released_when_analysis_fails(inspect, addon_module, monkeypatch):
    obj = _Object(_mesh(CUBE_VERTICES, CUBE_FACES))
    monkeypatch.setattr(addon_module.mesh, "_analyze", MagicMock(side_effect=RuntimeError("boom")))
    with pytest.raises(RuntimeError, match="boom"):
        inspect(obj)
    assert obj.released == 1


def test_invalid_targets(inspect, handler):
    obj = _Object(_mesh(CUBE_VERTICES, CUBE_FACES))
    with pytest.raises(ValueError, match="not found"):
        handler.handle("mesh.inspect", {"name": "Nope"})
    obj.type = "CURVE"
    with pytest.raises(ValueError, match="requires a MESH object, not CURVE"):
        inspect(obj)
    obj.type = "MESH"
    obj.data.is_editmode = True
    with pytest.raises(ValueError, match="Edit Mode"):
        inspect(obj)


@pytest.mark.parametrize(
    "params",
    [
        {"source": "render"},
        {"tolerance": -1},
        {"tolerance": float("inf")},
        {"max_ids": 101},
        {"max_ids": -1},
        {"element_budget": 0},
        {"element_budget": 2_000_001},
        {"check_duplicates": 1},
    ],
)
def test_invalid_parameters(inspect, params):
    with pytest.raises(ValueError):
        inspect(_Object(_mesh(CUBE_VERTICES, CUBE_FACES)), **params)


def test_policy_allowlist_applies(handler, runtime):
    from dataclasses import replace

    runtime.settings.policy = replace(runtime.settings.policy, allowed_commands=("scene.get_info",))
    with pytest.raises(PermissionError):
        handler.handle("mesh.inspect", {"name": "Cube"})


def test_inspection_adds_no_undo_checkpoint(handler):
    assert "mesh.inspect" not in handler.mutation_commands
