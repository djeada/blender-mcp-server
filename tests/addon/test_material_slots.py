"""Tests for material slot editing and face assignment."""

from types import SimpleNamespace

import pytest


class _Mesh(SimpleNamespace):
    def update(self):
        pass

    def copy(self):
        return _Mesh(
            name=f"{self.name}.001",
            is_editmode=False,
            library=None,
            materials=_Materials(self.materials),
            polygons=[SimpleNamespace(**vars(polygon)) for polygon in self.polygons],
            vertices=self.vertices,
        )

    def __eq__(self, other):
        return self is other

    __hash__ = object.__hash__


class _Materials(list):
    """Mesh materials whose pop() renumbers nothing, as the code must not rely on Blender doing it."""

    def pop(self, index):
        return list.pop(self, index)


class _Slot:
    def __init__(self, obj, index):
        self.obj, self.index = obj, index

    @property
    def link(self):
        return self.obj.links.get(self.index, "DATA")

    @link.setter
    def link(self, value):
        self.obj.links[self.index] = value

    @property
    def material(self):
        if self.link == "OBJECT":
            return self.obj.own.get(self.index)
        return self.obj.data.materials[self.index]

    @material.setter
    def material(self, value):
        if self.link == "OBJECT":
            self.obj.own[self.index] = value
        else:
            self.obj.data.materials[self.index] = value


class _Object:
    """Object-linked slot data is stored by position, which is what makes slot removal dangerous."""

    def __init__(self, name, mesh, groups=()):
        self.name, self.type, self.data, self.library = name, "MESH", mesh, None
        self.links, self.own = {}, {}
        self.vertex_groups = {group: SimpleNamespace(index=index, name=group) for index, group in enumerate(groups)}

    @property
    def material_slots(self):
        return [_Slot(self, index) for index in range(len(self.data.materials))]


def _named(name):
    return SimpleNamespace(name=name)


@pytest.fixture
def scene(mock_bpy):
    """A strip of four faces, one in each of slots 0-3, used by objects A and B."""
    materials = {name: _named(name) for name in ("M0", "M1", "M2", "M3", "Extra", "OwnA", "OwnB")}
    # Face i uses vertices 2i..2i+3; group "half" covers the first three vertex pairs.
    vertices = [
        SimpleNamespace(groups=[SimpleNamespace(group=0, weight=1.0 if index < 4 else 0.2)] if index < 6 else [])
        for index in range(10)
    ]
    mesh = _Mesh(
        name="Strip",
        is_editmode=False,
        library=None,
        materials=_Materials(materials[f"M{i}"] for i in range(4)),
        polygons=[
            SimpleNamespace(material_index=i, vertices=[2 * i, 2 * i + 1, 2 * i + 3, 2 * i + 2]) for i in range(4)
        ],
        vertices=vertices,
    )
    first, second = _Object("A", mesh, ["half"]), _Object("B", mesh, ["half"])
    first.links[2], first.own[2] = "OBJECT", materials["OwnA"]
    second.links[3], second.own[3] = "OBJECT", materials["OwnB"]
    objects = {"A": first, "B": second}
    mock_bpy.data.objects.get = objects.get
    mock_bpy.data.objects.__iter__ = lambda self: iter(objects.values())
    mock_bpy.data.materials.get = materials.get
    return SimpleNamespace(mesh=mesh, a=first, b=second, materials=materials)


def _shown(obj):
    return [(slot.link, slot.material.name if slot.material else None) for slot in obj.material_slots]


def _faces(obj):
    """The material each face actually shows on this object."""
    return [obj.material_slots[p.material_index].material.name for p in obj.data.polygons]


def _state(scene):
    return (_shown(scene.a), _shown(scene.b), [p.material_index for p in scene.mesh.polygons])


def test_inspection_counts_faces_and_reports_sharing(handler, scene):
    report = handler.handle("material.list_slots", {"object": "A"})
    assert [(slot["material"], slot["link"], slot["faces"]) for slot in report["slots"]] == [
        ("M0", "DATA", 1),
        ("M1", "DATA", 1),
        ("OwnA", "OBJECT", 1),
        ("M3", "DATA", 1),
    ]
    assert report["slots"][2]["data_material"] == "M2"
    assert report["mesh_shared_by"] == {"count": 2, "objects": ["A", "B"]}
    page = handler.handle("material.list_slots", {"object": "A", "limit": 3})
    assert len(page["slots"]) == 3 and page["next_offset"] == 3


@pytest.mark.parametrize("removed", [0, 1, 2, 3])
def test_removal_keeps_what_every_other_face_and_object_showed(handler, scene, removed):
    keep = 0 if removed else 1
    before = {obj.name: _faces(obj) for obj in (scene.a, scene.b)}
    kept_slot = {obj.name: obj.material_slots[keep].material.name for obj in (scene.a, scene.b)}
    result = handler.handle(
        "material.slot_remove", {"object": "A", "index": removed, "remap_to": keep, "shared_data": "update_all"}
    )
    assert result["removed_index"] == removed and result["faces_moved"] == 1
    for obj in (scene.a, scene.b):
        expected = [kept_slot[obj.name] if face == removed else shown for face, shown in enumerate(before[obj.name])]
        assert _faces(obj) == expected, obj.name
        assert len(obj.material_slots) == 3


@pytest.mark.parametrize(
    ("command", "params", "message"),
    [
        ("material.slot_remove", {"index": 1, "shared_data": "update_all"}, "1 faces use slot 1; pass 'remap_to'"),
        ("material.slot_remove", {"index": 1, "remap_to": 1}, "different slot"),
        ("material.slot_remove", {"index": 9}, "existing slot"),
        ("material.slot_remove", {"index": 1, "remap_to": 9}, "existing slot"),
        ("material.slot_remove", {"index": 1, "remap_to": 0}, r"shared by 2 objects \(A, B\)"),
        ("material.slot_append", {"material": "Extra"}, "shared by 2 objects"),
        ("material.slot_append", {"material": "Missing", "shared_data": "update_all"}, "Material not found"),
        ("material.slot_append", {"link": "WORLD"}, "link"),
        ("material.slot_replace", {"index": 0, "material": "Extra"}, "shared by 2 objects"),
        ("material.slot_replace", {"index": 4, "material": "Extra"}, "existing slot"),
        ("material.assign_faces", {"slot": 0, "face_indices": [1]}, "shared by 2 objects"),
        ("material.assign_faces", {"slot": 0, "face_indices": [4], "shared_data": "update_all"}, "from 0 to 3"),
        ("material.assign_faces", {"slot": 0, "face_indices": [1.5], "shared_data": "update_all"}, "integers"),
        ("material.assign_faces", {"slot": 0, "face_indices": []}, "no faces"),
        ("material.assign_faces", {"slot": 0}, "exactly one of 'face_indices'"),
        ("material.assign_faces", {"slot": 0, "from_slot": 1, "face_indices": [0]}, "exactly one"),
        ("material.assign_faces", {"face_indices": [0]}, "exactly one of 'slot'"),
        ("material.assign_faces", {"material": "Extra", "face_indices": [0]}, "not in any slot"),
        ("material.assign_faces", {"slot": 0, "vertex_group": "nope"}, "Vertex group not found"),
        ("material.assign_faces", {"slot": 0, "vertex_group": "half", "match": "most"}, "match"),
        ("material.slot_replace", {"index": 0, "shared_data": "sometimes"}, "shared_data"),
    ],
)
def test_invalid_requests_fail_before_any_change(handler, scene, command, params, message):
    before = _state(scene)
    with pytest.raises(ValueError, match=message):
        handler.handle(command, {"object": "A", **params})
    assert _state(scene) == before and scene.a.data is scene.mesh


def test_three_independent_regions_with_every_selector(handler, scene):
    shared = {"object": "A", "shared_data": "update_all"}
    all_match = handler.handle("material.assign_faces", {**shared, "slot": 1, "vertex_group": "half"})
    assert all_match["selected_faces"] == 2  # faces 0 and 1 have all vertices in the group
    any_match = handler.handle(
        "material.assign_faces", {**shared, "slot": 3, "vertex_group": "half", "match": "any", "min_weight": 0.5}
    )
    assert any_match["selected_faces"] == 2
    handler.handle("material.assign_faces", {**shared, "material": "M0", "face_indices": [3, 3]})
    moved = handler.handle("material.assign_faces", {**shared, "slot": 1, "from_slot": 2})
    assert moved["selected_faces"] == 1
    counts = {slot["index"]: slot["faces"] for slot in moved["slots"]}
    assert counts == {0: 1, 1: 1, 2: 0, 3: 2}
    assert [p.material_index for p in scene.mesh.polygons] == [3, 3, 1, 0]


def test_reassigning_the_same_faces_does_not_need_shared_consent(handler, scene):
    result = handler.handle("material.assign_faces", {"object": "A", "slot": 1, "face_indices": [1]})
    assert result["changed_faces"] == 0


def test_object_linked_replacement_affects_only_that_object(handler, scene):
    handler.handle("material.slot_replace", {"object": "A", "index": 0, "material": "Extra", "link": "OBJECT"})
    assert _shown(scene.a)[0] == ("OBJECT", "Extra") and _shown(scene.b)[0] == ("DATA", "M0")
    assert scene.mesh.materials[0].name == "M0"


def test_make_single_user_leaves_the_other_object_alone(handler, scene):
    before_b = (_shown(scene.b), _faces(scene.b))
    result = handler.handle(
        "material.slot_append", {"object": "A", "material": "Extra", "shared_data": "make_single_user"}
    )
    assert result["added_index"] == 4 and "mesh_shared_by" not in result
    assert scene.a.data is not scene.mesh and _shown(scene.a)[2] == ("OBJECT", "OwnA")
    assert (_shown(scene.b), _faces(scene.b)) == before_b


def test_append_object_linked_slot(handler, scene):
    handler.handle(
        "material.slot_append", {"object": "A", "material": "Extra", "link": "OBJECT", "shared_data": "update_all"}
    )
    assert _shown(scene.a)[4] == ("OBJECT", "Extra") and _shown(scene.b)[4] == ("DATA", None)


@pytest.mark.parametrize(("attribute", "value"), [("is_editmode", True), ("library", "lib")])
def test_edit_mode_and_linked_meshes_are_refused(handler, scene, attribute, value):
    setattr(scene.mesh, attribute, value)
    with pytest.raises(ValueError, match="Edit Mode|Linked library"):
        handler.handle("material.slot_replace", {"object": "A", "index": 0, "shared_data": "update_all"})


def test_undo_flags(handler):
    assert "material.list_slots" not in handler.mutation_commands
    assert {
        "material.slot_append",
        "material.slot_replace",
        "material.slot_remove",
        "material.assign_faces",
    } <= handler.mutation_commands
