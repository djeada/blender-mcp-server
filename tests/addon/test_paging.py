"""Source-side pagination of listing commands."""

from types import SimpleNamespace

import pytest


def _named(name, children=(), parent=None, kind="MESH"):
    return SimpleNamespace(name=name, type=kind, children=list(children), parent=parent, users=0, use_nodes=True)


@pytest.mark.parametrize("command", ["material.list", "collection.list"])
def test_pages_cover_every_record_once(handler, mock_bpy, command):
    items = [SimpleNamespace(name=f"item{index}", users=0, use_nodes=True, objects=[]) for index in range(7)]
    mock_bpy.data.materials.__iter__ = lambda self: iter(items)
    mock_bpy.data.collections.__iter__ = lambda self: iter(items)
    key = command.split(".")[0] + "s"
    assert set(handler.handle(command, {})) == {key}  # the unpaged shape is unchanged
    names, offset = [], 0
    while offset is not None:
        page = handler.handle(command, {"limit": 3, "offset": offset})
        assert page["total"] == 7 and page["count"] == len(page[key]) <= 3
        names += [item["name"] for item in page[key]]
        offset = page["next_offset"]
    assert names == [item.name for item in items]


def test_scene_listing_reports_the_next_offset_only_when_limited(handler):
    assert "next_offset" not in handler.handle("scene.list_objects", {})
    assert handler.handle("scene.list_objects", {"limit": 1})["next_offset"] == 1
    assert handler.handle("scene.list_objects", {"limit": 5})["next_offset"] is None


@pytest.fixture
def tree(mock_bpy):
    """A: (A1: (A1a, A1b), A2), B, C: (C1)."""
    a1 = _named("A1", [_named("A1b"), _named("A1a")])
    a = _named("A", [_named("A2"), a1])
    roots = [_named("C", [_named("C1")]), a, _named("B")]
    mock_bpy.context.scene.objects = roots
    mock_bpy.data.objects.get = lambda name: {"A": a, "A1": a1}.get(name)


def _names(nodes):
    for node in nodes:
        yield node["name"]
        yield from _names(node["children"])


def test_hierarchy_node_budget_marks_what_is_missing(handler, tree):
    page = handler.handle("object.get_hierarchy", {"max_nodes": 3})
    assert list(_names(page["roots"])) == ["A", "A1", "A1a"]
    assert page["roots"][0]["children_omitted"] == 1
    assert page["roots"][0]["children"][0]["children_omitted"] == 1
    assert (page["total"], page["count"], page["next_offset"]) == (3, 1, 1)
    rest = handler.handle("object.get_hierarchy", {"max_nodes": 10, "offset": page["next_offset"]})
    assert list(_names(rest["roots"])) == ["B", "C", "C1"] and rest["next_offset"] is None


def test_hierarchy_depth_and_subtree_paging(handler, tree):
    shallow = handler.handle("object.get_hierarchy", {"max_depth": 0})
    assert [(node["name"], node.get("children_omitted")) for node in shallow["roots"]] == [
        ("A", 2),
        ("B", None),
        ("C", 1),
    ]
    first = handler.handle("object.get_hierarchy", {"name": "A", "max_nodes": 2})
    assert list(_names([first])) == ["A", "A1"] and first["next_offset"] == 1
    second = handler.handle("object.get_hierarchy", {"name": "A", "max_nodes": 5, "offset": 1})
    assert list(_names([second])) == ["A", "A2"] and second["next_offset"] is None
    only = handler.handle("object.get_hierarchy", {"name": "A", "max_depth": 0})
    assert only["children"] == [] and only["children_omitted"] == 2 and only["next_offset"] is None


def test_unbounded_hierarchy_keeps_its_original_shape_and_order(handler, tree):
    result = handler.handle("object.get_hierarchy", {})
    assert set(result) == {"roots"}
    assert [node["name"] for node in result["roots"]] == ["C", "A", "B"]


@pytest.mark.parametrize("params", [{"limit": 0}, {"offset": -1}, {"limit": True}])
def test_invalid_paging_parameters(handler, params):
    with pytest.raises(ValueError):
        handler.handle("material.list", params)
