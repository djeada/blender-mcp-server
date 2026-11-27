"""End-to-end tests against a real Blender process.

Opt in with BLENDER_MCP_INTEGRATION=1 (and BLENDER_BIN if blender is not on PATH):

    BLENDER_MCP_INTEGRATION=1 pytest tests/integration --no-cov
"""

import asyncio
import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import time
import zlib
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from blender_mcp_server import server
from blender_mcp_server.connection import BlenderConnection
from blender_mcp_server.headless import HeadlessBlenderExecutor
from blender_mcp_server.shared import protocol

BLENDER = os.environ.get("BLENDER_BIN", "blender")
EXAMPLE_LIBRARY = Path(__file__).resolve().parents[2] / "examples" / "library"

pytestmark = pytest.mark.skipif(
    os.environ.get("BLENDER_MCP_INTEGRATION") != "1" or shutil.which(BLENDER) is None,
    reason="set BLENDER_MCP_INTEGRATION=1 and install Blender to run integration tests",
)


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def _tiny_png(path: Path) -> None:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))

    raw = zlib.compress(b"\x00\xff\x00\x00")
    ihdr = struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0)
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", raw) + chunk(b"IEND", b""))


@pytest.fixture(scope="module")
def bridge(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("bridge")
    port = _free_port()
    env = dict(os.environ)
    env.pop("BLENDER_MCP_TOKEN", None)
    # TMPDIR keeps the add-on's fallback output folder for unsaved files inside the test directory.
    env.update({"BLENDER_MCP_PORT": str(port), "BLENDER_MCP_TOKEN_FILE": str(tmp / "token"), "TMPDIR": str(tmp)})
    harness = Path(__file__).with_name("blender_bridge_harness.py")
    log_dir = Path(os.environ.get("BLENDER_MCP_TEST_LOG_DIR", tmp))
    log_dir.mkdir(parents=True, exist_ok=True)
    log = log_dir / "bridge.log"
    with log.open("w", encoding="utf-8") as output:
        proc = subprocess.Popen(
            [BLENDER, "-b", "--factory-startup", "-t", "4", "--python-exit-code", "1", "--python", str(harness)],
            env=env,
            stdout=output,
            stderr=subprocess.STDOUT,
        )
        try:
            deadline = time.monotonic() + 45
            while "BRIDGE_READY" not in log.read_text(encoding="utf-8", errors="replace"):
                if proc.poll() is not None or time.monotonic() >= deadline:
                    pytest.fail(log.read_text(encoding="utf-8", errors="replace"))
                time.sleep(0.05)
            yield {"port": port, "token_file": tmp / "token", "tmp": tmp}
        finally:
            proc.kill()
            proc.wait(timeout=10)


@pytest.fixture
def call(bridge, monkeypatch):
    monkeypatch.delenv("BLENDER_MCP_TOKEN", raising=False)
    monkeypatch.setenv("BLENDER_MCP_TOKEN_FILE", str(bridge["token_file"]))
    conn = BlenderConnection(port=bridge["port"])
    ctx = MagicMock()
    ctx.request_context.lifespan_context = conn

    loop = asyncio.new_event_loop()

    def run(tool, **kwargs):
        result = loop.run_until_complete(getattr(server, tool)(ctx, **kwargs))
        return json.loads(result) if isinstance(result, str) else result.get("result", result)

    yield run
    loop.run_until_complete(conn.disconnect())
    loop.close()


def _raw(port: int, payload: bytes) -> list[dict]:
    with socket.create_connection(("127.0.0.1", port), timeout=10) as s:
        s.sendall(payload)
        s.shutdown(socket.SHUT_WR)
        data = b""
        while chunk := s.recv(65536):
            data += chunk
    return [json.loads(line) for line in data.splitlines() if line.strip()]


def test_token_file_is_private(bridge):
    assert (bridge["token_file"].stat().st_mode & 0o777) == 0o600


def test_scene_and_object_tools(call):
    assert call("scene_get_info")["name"] == "Scene"
    created = call("object_create", mesh_type="cube", name="ITCube", location=[1, 2, 3])
    assert created["location"] == [1.0, 2.0, 3.0]
    moved = call("object_translate", name="ITCube", offset=[1, 0, 0])
    assert moved["location"] == [2.0, 2.0, 3.0]


def test_typed_camera_light_animation_and_collection_tools(call):
    camera = call("camera_create", name="ITCamera", location=[3, -4, 5], look_at=[0, 0, 0], lens=35)
    assert camera["lens"] == 35
    assert call("camera_update", name="ITCamera", projection="ORTHO", ortho_scale=4)["projection"] == "ORTHO"
    assert call("light_create", name="ITLight", light_type="AREA", energy=100, size=2)["light_type"] == "AREA"
    assert call("light_update", name="ITLight", energy=200)["energy"] == 200
    assert call("timeline_set", frame_current=1, frame_start=1, frame_end=120)["frame_end"] == 120
    call("object_create", name="ITAnimated")
    for frame in (1, 10):
        call("keyframe_add", name="ITAnimated", property="location", frame=frame, value=[frame, 0, 0])
    assert call("keyframe_list", name="ITAnimated", property="location")["keyframe_count"] == 6
    assert call("keyframe_remove", name="ITAnimated", property="location", frame=10)["keyframe_count"] == 3
    call("collection_create", name="ITProps")
    assert call("collection_add_object", collection="ITProps", object="ITAnimated")["moved"] is True
    assert call("scene_list_objects", collection="ITProps")["total"] == 1
    assert call("collection_remove_object", collection="ITProps", object="ITAnimated")["relinked_to_scene"] is True


def test_parenting_and_unparenting_keep_world_transform(call):
    call("object_create", name="ITParent", location=[5, 0, 0])
    call("object_create", name="ITChild", location=[1, 2, 3])

    def world_transform():
        result = call(
            "python_exec",
            code="bpy.context.view_layer.update()\n__result__ = [v for row in bpy.data.objects['ITChild'].matrix_world for v in row]",
        )
        assert result["error"] is None
        return result["result"]

    original = world_transform()
    call("object_parent", name="ITChild", parent="ITParent", keep_transform=True)
    assert world_transform() == pytest.approx(original)
    call("object_translate", name="ITParent", offset=[5, 0, 0])
    moved = world_transform()
    assert moved != pytest.approx(original)
    call("object_unparent", name="ITChild", keep_transform=True)
    assert world_transform() == pytest.approx(moved)


def test_material_tools(call, bridge):
    call("object_create", mesh_type="plane", name="ITPlane")
    call("material_create", name="ITMat")
    call("material_assign", object="ITPlane", material="ITMat")
    assert call("material_set_color", name="ITMat", color=[1, 0, 0])["color"] == [1.0, 0.0, 0.0, 1.0]
    texture = bridge["tmp"] / "tex.png"
    _tiny_png(texture)
    assert call("material_set_texture", name="ITMat", filepath=str(texture))["texture"] == str(texture)


def test_failed_texture_load_leaves_material_untouched(call):
    call("material_create", name="ITTexMat")
    with pytest.raises(RuntimeError, match="Cannot read"):
        call("material_set_texture", name="ITTexMat", filepath="/nonexistent/texture.png")
    nodes = call(
        "python_exec", code="__result__ = [n.bl_idname for n in bpy.data.materials['ITTexMat'].node_tree.nodes]"
    )
    assert "ShaderNodeTexImage" not in nodes["result"]


def test_objects_without_mesh_data(call):
    call("python_exec", code="bpy.context.scene.collection.objects.link(bpy.data.objects.new('ITEmpty', None))")
    assert call("object_duplicate", name="ITEmpty", new_name="ITEmpty2")["name"] == "ITEmpty2"
    call("material_create", name="ITEmptyMat")
    with pytest.raises(RuntimeError, match="type EMPTY, which cannot have materials"):
        call("material_assign", object="ITEmpty", material="ITEmptyMat")


def test_export_creates_folders_and_reports_absolute_path(call, bridge):
    target = bridge["tmp"] / "exports" / "nested" / "scene"
    result = call("export_obj", filepath=str(target))
    assert result["filepath"] == f"{target}.obj"
    assert Path(result["filepath"]).is_file()


def test_blend_relative_export_from_unsaved_file(call, bridge):
    result = call("export_obj", filepath="//it_unsaved.obj")
    assert result["filepath"] == str(bridge["tmp"] / "blender-mcp" / "it_unsaved.obj")
    assert Path(result["filepath"]).is_file()


_USE_FAST_CYCLES = """
scene = bpy.context.scene
try:
    scene.render.engine = "CYCLES"
    scene.cycles.samples = 1
    scene.cycles.use_denoising = False
    __result__ = True
except (TypeError, AttributeError):
    __result__ = False
"""


def test_render_with_default_path_from_unsaved_file(call, bridge):
    """Cycles renders on the CPU, so this also runs where background Blender has no GPU or display."""
    if not call("python_exec", code=_USE_FAST_CYCLES)["result"]:
        pytest.skip("Cycles is not available in this Blender build")
    result = call("render_still", resolution_x=16, resolution_y=16, engine="cycles")
    assert result["engine"] == "CYCLES"
    assert result["output_path"] == str(bridge["tmp"] / "blender-mcp" / "render.png")
    assert Path(result["output_path"]).is_file()


def test_large_response(call):
    result = call("python_exec", code="print('y' * 49000)\n__result__ = 'x' * 200000")
    assert len(result["result"]) == 200000
    assert call("scene_get_info")["name"] == "Scene"


def test_system_exit_does_not_break_bridge(call):
    result = call("python_exec", code="raise SystemExit(3)")
    assert "SystemExit" in result["error"]
    assert call("scene_get_info")["name"] == "Scene"


def test_running_async_job_can_be_cancelled(call):
    """job.cancel must reach a job that is busy on Blender's main thread."""
    code = "import time\nwhile not __cancel_event__.is_set():\n    time.sleep(0.01)\n"
    job_id = call("python_exec_async", code=code, timeout_seconds=60)["job_id"]
    deadline = time.monotonic() + 10
    while call("job_status", job_id=job_id)["status"] != "running":
        assert time.monotonic() < deadline, "job never started"
        time.sleep(0.05)
    assert call("job_cancel", job_id=job_id)["cancellation_requested"] is True
    while (status := call("job_status", job_id=job_id)["status"]) == "running":
        assert time.monotonic() < deadline, "cancellation never took effect"
        time.sleep(0.05)
    assert status == "cancelled"


def test_unauthenticated_request_rejected(bridge):
    responses = _raw(bridge["port"], b'{"id": "1", "command": "scene.get_info"}\n')
    assert responses[0]["id"] is None
    assert responses[0]["error_details"]["code"] == "permission_denied"


def test_http_smuggled_command_not_executed(bridge):
    token = bridge["token_file"].read_text()
    body = json.dumps({"id": "x", "command": "python.execute", "params": {"code": "pass"}, "token": token})
    http = f"POST / HTTP/1.1\r\nHost: 127.0.0.1\r\nContent-Type: text/plain\r\n\r\n{body}\n".encode()
    responses = _raw(bridge["port"], http)
    assert len(responses) == 1
    assert "Invalid JSON" in responses[0]["error"]


def test_headless_execution_and_system_exit(headless_policy):
    executor = HeadlessBlenderExecutor(BLENDER, headless_policy)
    ok = asyncio.run(executor.execute(code="__result__ = bpy.app.version_string", timeout_seconds=120))
    assert ok["error"] is None and ok["result"]
    exited = asyncio.run(executor.execute(code="import sys; sys.exit(0)", timeout_seconds=120))
    assert "SystemExit" in exited["error"]


def _recipe_source(filename):
    return (EXAMPLE_LIBRARY / filename).read_text(encoding="utf-8")


def test_tree_scatter_and_emission_examples_via_bridge(call):
    """Asset recipes use Python execution and need no dedicated bridge commands."""
    tree = call("python_exec", code=_recipe_source("create_tree.py"), args={"name": "ITOak", "height": 2.5, "seed": 7})
    assert tree["error"] is None
    assert tree["result"]["materials"] == ["TreeBark", "TreeLeaves"]
    assert tree["result"]["vertices"] > 100
    copies = call(
        "python_exec",
        code=_recipe_source("scatter_objects.py"),
        args={"source": "ITOak", "count": 3, "radius": 2.0, "seed": 7},
    )
    assert copies["error"] is None
    assert copies["result"]["count"] == 3
    emission = call(
        "python_exec",
        code=_recipe_source("create_emissive_material.py"),
        args={"name": "ITGlow", "emission_color": [0, 1, 1], "emission_strength": 8},
    )
    assert emission["error"] is None
    assert emission["result"]["emission_color"] == [0, 1, 1, 1]
    assert call("material_assign", object="ITOak", material="ITGlow")["material"] == "ITGlow"
    inspected = call(
        "python_exec",
        code="""
source = bpy.data.objects['ITOak']
copies = [bpy.data.objects[name] for name in args['names']]
__result__ = {
    'linked': all(obj.data is source.data for obj in copies),
    'materials': sorted({face.material_index for face in source.data.polygons}),
    'strength': bpy.data.materials['ITGlow'].node_tree.nodes['Principled BSDF'].inputs['Emission Strength'].default_value,
}
""",
        args={"names": copies["result"]["names"]},
    )
    assert inspected["error"] is None
    assert inspected["result"] == {"linked": True, "materials": [0, 1], "strength": 8}


def test_tree_example_is_seeded_in_headless_transport(headless_policy):
    code = "\n".join(
        [
            _recipe_source("create_tree.py"),
            "first = bpy.data.objects[__result__['name']]",
            "second = create_tree(args)",
            "third = create_tree({**args, 'seed': args['seed'] + 1})",
            "vertices = lambda obj: [tuple(v.co) for v in obj.data.vertices]",
            "assert vertices(first) == vertices(bpy.data.objects[second['name']])",
            "assert vertices(first) != vertices(bpy.data.objects[third['name']])",
            _recipe_source("scatter_objects.py"),
            _recipe_source("create_emissive_material.py"),
        ]
    )
    result = asyncio.run(
        HeadlessBlenderExecutor(BLENDER, headless_policy).execute(
            code=code,
            args={"name": "SeededTree", "seed": 7, "source": "SeededTree", "count": 3},
            timeout_seconds=120,
        )
    )
    assert result["error"] is None
    assert result["result"]["emission_strength"] == 5.0


def test_ordered_batch_and_three_modifier_types(call):
    steps = [
        {"command": "object.create_mesh", "params": {"name": "BatchCube"}},
        {"command": "object.translate", "params": {"name": "BatchCube", "offset": [2, 0, 0]}},
        {"command": "material.create", "params": {"name": "BatchMaterial", "color": [0.25, 0.5, 0.75]}},
        {"command": "material.assign", "params": {"object": "BatchCube", "material": "BatchMaterial"}},
        {"command": "object.get_transform", "params": {"name": "Nonexistent"}},
        {"command": "object.delete", "params": {"name": "BatchCube"}},
    ]
    batch = call("scene_execute_batch", commands=steps)
    assert [step["status"] for step in batch["steps"]] == ["succeeded"] * 4 + ["failed", "skipped"]
    assert call("object_get_transform", name="BatchCube")["location"][0] == 2
    for name, mesh, kind, settings in (
        ("BatchCube", None, "BEVEL", {"segments": 3}),
        ("BatchPlane", "plane", "SOLIDIFY", {"thickness": 0.2}),
        ("BatchSphere", "sphere", "MIRROR", {"use_axis": [True, False, True]}),
    ):
        if mesh:
            call("object_create", mesh_type=mesh, name=name)
        fixed = call("object_add_modifier", name=name, modifier_type="SUBSURF", modifier_name="Base")
        assert fixed["modifier"]["type"] == "SUBSURF"
        call("object_add_modifier", name=name, modifier_type=kind, modifier_name="Detail")
        updated = call("object_update_modifier", name=name, modifier_name="Detail", properties=settings)
        with pytest.raises(protocol.BridgeError) as invalid:
            call("object_update_modifier", name=name, modifier_name="Detail", properties={"forbidden": 0})
        assert invalid.value.code == "invalid_arguments"
        stack = call("object_list_modifiers", name=name)["modifiers"]
        assert [modifier["name"] for modifier in stack] == ["Base", "Detail"]
        assert stack[-1] == updated["modifier"]
        call("object_remove_modifier", name=name, modifier_name="Detail")
        assert call("object_list_modifiers", name=name)["modifiers"] == stack[:1]


def test_project_persistence_and_recovery_across_multiple_loads(call, bridge):
    path = bridge["tmp"] / "project.blend"
    before = call("blender_status")
    assert before["bridge"]["main_thread_progress"]
    assert "project.save" in before["bridge"]["commands"]
    assert "blender_project_save" in before["mcp_tools"]
    call("object_create", name="PersistedCube", location=[3, 0, 0])
    saved = call("project_save", filepath=str(path))
    assert saved["saved"] and saved["filepath"] == str(path)
    for _ in range(2):
        call("object_translate", name="PersistedCube", offset=[2, 0, 0])
        opened = call("project_open", filepath="//project.blend", discard_changes=True)
        assert opened["filepath"] == saved["filepath"]
        assert call("object_get_transform", name="PersistedCube")["location"][0] == 3
        status = call("blender_status")
        assert status["bridge"]["generation"] != before["bridge"]["generation"]
        before = status
    call("project_revert", confirm=True)
    assert call("scene_get_info")["name"] == "Scene"


_RECIPE_RUN_ORDER = (
    # (recipe, arguments); later steps use objects the earlier ones create.
    ("create-mesh", {"mesh_type": "sphere", "name": "RecipeOrb", "location": [0, 0, 5]}),
    ("create-mesh", {"mesh_type": "plane", "name": "RecipeGround"}),
    ("create-tree", {"name": "RecipeOak", "height": 2.5, "seed": 7}),
    ("scatter-objects", {"source": "RecipeOak", "count": 3, "seed": 1}),
    ("emissive-material", {"name": "RecipeGlow", "emission_color": [0, 1, 1]}),
    ("setup-camera", {"name": "RecipeCam", "location": [6, -6, 4], "focal_length": 70}),
    ("rigid-body", {"objects": ["RecipeOrb", "Missing"], "mass": 2.0}),
    ("physics-effector", {"objects": ["RecipeGround"]}),
    ("apply-transforms", {"objects": ["RecipeGround"], "location": True}),
)


def _check_recipe_result(recipe_id, result):
    from jsonschema import validate

    from blender_mcp_server.recipes import get_recipe

    validate(result, get_recipe(recipe_id).output_schema)


def test_every_recipe_runs_through_the_bridge_and_matches_its_contract(call):
    from blender_mcp_server.recipes import catalog

    assert {recipe for recipe, _ in _RECIPE_RUN_ORDER} == set(catalog())
    results = {}
    for recipe, arguments in _RECIPE_RUN_ORDER:
        results[recipe] = call("recipe_run", recipe=recipe, arguments=arguments)  # the fixture unwraps "result"
        _check_recipe_result(recipe, results[recipe])
    assert results["rigid-body"] == {"configured": ["RecipeOrb"], "skipped": ["Missing"], "rb_type": "ACTIVE"}
    assert results["setup-camera"]["is_active"] is True
    state = call(
        "python_exec",
        code="""
orb, ground = bpy.data.objects['RecipeOrb'], bpy.data.objects['RecipeGround']
__result__ = [orb.rigid_body.mass, sorted(m.type for m in ground.modifiers), list(ground.location),
              bpy.context.scene.camera.name]
""",
    )
    assert state["error"] is None
    assert state["result"] == [2.0, ["COLLISION", "FLUID"], [0, 0, 0], "RecipeCam"]
    with pytest.raises(protocol.BridgeError, match="scatter-objects failed"):
        call("recipe_run", recipe="scatter-objects", arguments={"source": "NoSuchObject"})


def test_a_recipe_runs_headless(call, headless_policy):
    context = MagicMock()
    context.request_context.lifespan_context.policy = headless_policy
    outcome = asyncio.run(
        server.recipe_run(context, "create-tree", {"seed": 3}, transport="headless", timeout_seconds=120)
    )
    _check_recipe_result("create-tree", outcome["result"])


def test_every_guide_pattern_runs_and_builds_clean_meshes(call):
    """Guide examples are instructions to a model, so they must work and must not teach broken topology."""
    from blender_mcp_server import knowledge

    def mesh_names():
        return {obj["name"] for obj in call("scene_list_objects", type="MESH")["objects"]}

    def run_python(code):
        result = call("python_exec", code=code)
        assert result["error"] is None, (result["error"], result["stderr"])
        return result["result"]

    for guide in knowledge.guides().values():
        for block in guide.python_blocks():
            before = mesh_names()
            run_python(block)
            for name in sorted(mesh_names() - before):
                for source in ("raw", "evaluated"):
                    report = call("mesh_inspect", name=name, source=source, check_duplicates=True)
                    assert report["summary"]["status"] == "ok", (guide.id, name, source, report["findings"])
            if guide.id == "geometry-nodes":
                assert (
                    run_python(
                        "__result__ = sum(i.is_instance for i in bpy.context.evaluated_depsgraph_get().object_instances)"
                    )
                    > 10
                )
            if guide.id == "rigging":
                moved = run_python(
                    """
import math
arm = next(o for o in bpy.context.scene.objects if o.name.startswith('GuideArm'))
rig = arm.modifiers['Skeleton'].object
def points():
    evaluated = arm.evaluated_get(bpy.context.evaluated_depsgraph_get())
    mesh = evaluated.to_mesh()
    found = (mesh.vertices[-1].co.copy(), mesh.vertices[0].co.copy())
    evaluated.to_mesh_clear()
    return found
tip, base = points()
bone = rig.pose.bones['lower']
bone.rotation_mode = 'XYZ'
bone.rotation_euler.x = math.radians(60)
bpy.context.view_layer.update()
posed_tip, posed_base = points()
bone.rotation_euler.x = 0
__result__ = [(posed_tip - tip).length, (posed_base - base).length, bpy.context.mode]
"""
                )
                assert moved[0] > 0.5 and moved[1] < 1e-5 and moved[2] == "OBJECT"


_BUILD_MESH_FIXTURES = """
def add(name, vertices, edges=(), faces=()):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, list(edges), list(faces))
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.scene.collection.objects.link(obj)
    return obj

square = [(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0)]
cube = [(x, y, z) for x in (0, 1) for y in (0, 1) for z in (0, 1)]
sides = [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)]
modified = add('MeshCube', cube, faces=sides)
modified.modifiers.new('Smooth', 'SUBSURF').levels = 1
modified.location = (10, 0, 0)
modified.vertex_groups.new(name='corner').add([0], 1.0, 'REPLACE')
add('MeshPlane', square, faces=[(0, 1, 2, 3)])
add('MeshParts', square + [(x + 5, y, z) for x, y, z in square], faces=[(0, 1, 2, 3), (4, 5, 6, 7)])
add(
    'MeshDefects',
    [(0, 0, 0), (1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (2, 0, 0), (3, 3, 3), (4, 4, 4), (5, 4, 4), (1, 0, 0)],
    edges=[(7, 8)],
    faces=[(0, 1, 2), (0, 1, 3), (1, 0, 4), (0, 1, 5)],
)
hidden = add('MeshHidden', cube, faces=sides)
hidden.modifiers.new('Smooth', 'SUBSURF').levels = 1
hidden.hide_viewport = True
for obj in bpy.context.selected_objects:
    obj.select_set(False)
bpy.data.objects['MeshPlane'].select_set(True)
bpy.context.view_layer.objects.active = bpy.data.objects['MeshParts']
bpy.context.view_layer.update()
__result__ = True
"""

_SNAPSHOT_STATE = """
__result__ = {
    'active': bpy.context.view_layer.objects.active.name,
    'mode': bpy.context.mode,
    'datablocks': [len(bpy.data.meshes), len(bpy.data.objects), len(bpy.data.materials)],
    'objects': {
        obj.name: [
            obj.select_get(),
            [list(row) for row in obj.matrix_world],
            [(m.name, m.show_viewport) for m in obj.modifiers],
            [list(v.co) + [v.select] for v in obj.data.vertices],
            [list(e.vertices) for e in obj.data.edges],
            [list(p.vertices) for p in obj.data.polygons],
        ]
        for obj in bpy.context.scene.objects
        if obj.name.startswith('Mesh')
    },
}
"""


def test_mesh_inspection_diagnoses_fixtures_without_changing_state(call):
    def run_python(code):
        result = call("python_exec", code=code)
        assert result["error"] is None, result["error"]
        return result["result"]

    run_python(_BUILD_MESH_FIXTURES)
    before = run_python(_SNAPSHOT_STATE)

    def inspect(name, **params):
        return call("mesh_inspect", name=name, check_duplicates=True, **params)

    raw = inspect("MeshCube", include_regions=True)
    assert raw["counts"]["raw"] == {"vertices": 8, "edges": 12, "faces": 6, "triangles": 12}
    assert raw["counts"]["evaluated"] == {"vertices": 26, "edges": 48, "faces": 24, "triangles": 48}
    assert raw["findings"] == [] and raw["summary"]["closed_edge_manifold"]
    assert raw["bounds"]["world"] == {"min": [10, 0, 0], "max": [11, 1, 1], "size": [1, 1, 1]}
    assert raw["regions"]["vertex_groups"]["items"][0]["vertices"] == 1
    evaluated = inspect("MeshCube", source="evaluated", include_regions=True)
    assert evaluated["bounds"]["local"]["size"][0] < 1
    assert evaluated["regions"]["vertex_groups"]["items"][0]["vertices"] > 1
    assert inspect("MeshCube", source="evaluated", include_regions=True) == evaluated

    plane = inspect("MeshPlane")
    assert plane["summary"]["status"] == "ok"
    assert [(f["check"], f["severity"], f["count"]) for f in plane["findings"]] == [("boundary_edges", "info", 4)]
    assert inspect("MeshParts")["components"]["count"] == 2

    defects = {finding["check"]: finding["count"] for finding in inspect("MeshDefects")["findings"]}
    assert defects == {
        "non_manifold_edges": 1,
        "zero_area_faces": 1,
        "loose_vertices": 2,
        "loose_edges": 1,
        "duplicate_vertices": 1,
        "boundary_edges": 8,  # two unshared edges on each of the four faces
    }

    hidden = inspect("MeshHidden")
    assert hidden["counts"]["evaluated"] is None and hidden["world_transform_current"] is False

    for kwargs, code in (
        ({"name": "MeshHidden", "source": "evaluated"}, "unsupported"),
        ({"name": "MeshCube", "element_budget": 10}, "budget_exceeded"),
        ({"name": "Missing"}, "not_found"),
    ):
        with pytest.raises(protocol.BridgeError) as failure:
            call("mesh_inspect", **kwargs)
        assert failure.value.code == code

    assert run_python(_SNAPSHOT_STATE) == before

    run_python("bpy.ops.object.mode_set(mode='EDIT')")
    with pytest.raises(protocol.BridgeError, match="Edit Mode"):
        call("mesh_inspect", name="MeshParts")
    assert run_python("__result__ = bpy.context.mode") == "EDIT_MESH"
    run_python("bpy.ops.object.mode_set(mode='OBJECT')")


_BUILD_CAPTURE_FIXTURE = """
root = bpy.data.objects.new('CaptureRoot', None)
bpy.context.scene.collection.objects.link(root)
group = bpy.data.collections.new('CaptureParts')
bpy.context.scene.collection.children.link(group)
for name, location, hidden in (('CaptureBox', (20, 0, 0), False), ('CaptureTall.001', (23, 0, 2), False),
                               ('CaptureSecret', (60, 0, 0), True)):
    mesh = bpy.data.meshes.new(name)
    cube = [(x, y, z) for x in (-1, 1) for y in (-1, 1) for z in (-1, 1)]
    mesh.from_pydata(cube, [], [(0, 1, 3, 2), (4, 6, 7, 5), (0, 4, 5, 1), (2, 3, 7, 6), (0, 2, 6, 4), (1, 5, 7, 3)])
    obj = bpy.data.objects.new(name, mesh)
    group.objects.link(obj)
    obj.location = location
    obj.parent = root
    obj.hide_render = hidden
instancer = bpy.data.objects.new('CaptureInstancer', None)
bpy.context.scene.collection.objects.link(instancer)
instancer.instance_type = 'COLLECTION'
instancer.instance_collection = group
instancer.location = (0, 40, 0)
moving = bpy.data.objects['CaptureBox']
moving.keyframe_insert('location', frame=1)
bpy.context.view_layer.update()
__result__ = True
"""

_SNAPSHOT_CAPTURE = """
scene = bpy.context.scene
render = scene.render
__result__ = {
    'scene': scene.name,
    'camera': scene.camera.name if scene.camera else None,
    'frame': scene.frame_current,
    'render': [render.engine, render.resolution_x, render.resolution_y, render.resolution_percentage,
               render.filepath, render.use_compositing, render.film_transparent, render.image_settings.file_format],
    'view_transform': scene.view_settings.view_transform,
    'datablocks': {kind: sorted(block.name for block in getattr(bpy.data, kind))
                   for kind in ('scenes', 'objects', 'meshes', 'materials', 'cameras', 'lights', 'worlds',
                                'collections')},
    'objects': {o.name: [o.select_get(), o.hide_render, o.hide_viewport, list(o.color),
                         [list(row) for row in o.matrix_world], [m.name for m in o.modifiers],
                         len(o.users_collection)]
                for o in scene.objects},
}
"""


def _png_size(data: bytes) -> tuple[int, int]:
    assert data.startswith(b"\x89PNG\r\n\x1a\n")
    return struct.unpack(">II", data[16:24])


def test_view_capture_returns_images_and_leaves_the_project_unchanged(bridge, call):
    """Background Blender captures with Cycles on the CPU, so no GPU or display is needed."""

    def run_python(code):
        result = call("python_exec", code=code)
        assert result["error"] is None, result["error"]
        return result["result"]

    if not run_python(_USE_FAST_CYCLES):
        pytest.skip("Cycles is not available in this Blender build")
    run_python(_BUILD_CAPTURE_FIXTURE)
    before = run_python(_SNAPSHOT_CAPTURE)

    loop = asyncio.new_event_loop()
    connection = BlenderConnection(port=bridge["port"])
    context = MagicMock()
    context.request_context.lifespan_context = connection

    def capture(**arguments):
        blocks = loop.run_until_complete(server.view_capture(context, resolution=96, **arguments))
        return json.loads(blocks[0].text), [base64.b64decode(b.data) for b in blocks if b.type == "image"]

    try:
        saved = bridge["tmp"] / "captures"
        report, images = capture(object="CaptureRoot", views=["front", "top"], save_directory=str(saved))
        assert report["engine"] == "CYCLES"
        assert [_png_size(image) for image in images] == [(96, 96), (96, 96)]
        assert images[0] != images[1]
        assert (saved / "capture_front.png").read_bytes() == images[0]
        assert report["bounds_world"] == {"min": [19, -1, -1], "max": [24, 1, 3], "size": [5, 2, 4]}
        assert {item["object"] for item in report["excluded"]["items"]} == {"CaptureRoot", "CaptureSecret"}

        # Instanced collections are framed from their instances.
        instanced, images = capture(object="CaptureInstancer", projection="perspective", mode="material")
        assert instanced["bounds_world"]["min"][1] == 39 and len(images) == 1
        wire, images = capture(collection="CaptureParts", mode="wireframe")
        assert wire["objects_shown"] == 2 and wire["notes"] == [] and len(images) == 1
        run_python("bpy.data.objects['CaptureBox'].modifiers.new('s', 'SUBSURF').render_levels = 3")
        assert "render modifier settings" in capture(object="CaptureBox", include_images=False)[0]["notes"][0]
        run_python("box = bpy.data.objects['CaptureBox']; box.modifiers.remove(box.modifiers['s'])")
        metadata, images = capture(object="CaptureBox", include_images=False)
        assert images == [] and metadata["engine"] is None and metadata["views"][0]["ortho_scale"] > 2

        for arguments, code in (
            ({"object": "CaptureSecret"}, "unsupported"),
            ({"object": "Missing"}, "not_found"),
            ({"object": "CaptureBox", "collection": "CaptureParts"}, "invalid_arguments"),
        ):
            with pytest.raises(protocol.BridgeError) as failure:
                capture(**arguments)
            assert failure.value.code == code
        # Fails after rendering has started, with temporary scene, mesh copies and materials in place.
        with pytest.raises(protocol.BridgeError) as failure:
            loop.run_until_complete(
                server.view_capture(
                    context,
                    object="CaptureBox",
                    views=["front", "back"],
                    mode="wireframe",
                    resolution=512,
                    max_bytes=10_000,
                )
            )
        assert failure.value.code == "budget_exceeded"
    finally:
        loop.run_until_complete(connection.disconnect())
        loop.close()

    assert run_python(_SNAPSHOT_CAPTURE) == before


def test_headless_view_capture_of_a_saved_project(call, bridge, headless_policy):
    path = bridge["tmp"] / "capture-source.blend"
    call("object_create", name="HeadlessShot")
    saved = call("python_exec", code=f"bpy.ops.wm.save_as_mainfile(filepath={str(path)!r}, copy=True)")
    assert saved["error"] is None
    report = asyncio.run(
        HeadlessBlenderExecutor(BLENDER, headless_policy).execute_command(
            "view.capture",
            {"object": "HeadlessShot", "resolution": 64, "views": ["front"]},
            blend_file=str(path),
            factory_startup=True,
            timeout_seconds=120,
        )
    )
    assert _png_size(base64.b64decode(report["views"][0]["png_base64"])) == (64, 64)


def _python(call, code):
    result = call("python_exec", code=code)
    assert result["error"] is None, (result["error"], result["stderr"])
    return result["result"]


_LIGHT_IDS = "__result__ = [sorted(o.name for o in bpy.data.objects), sorted(l.name for l in bpy.data.lights)]"


def test_lighting_validation_inspection_and_shared_data(call):
    before = _python(call, _LIGHT_IDS)
    with pytest.raises(protocol.BridgeError, match="does not apply to SUN"):
        call("light_create", name="ITRejected", light_type="SUN", size=2.0)
    assert _python(call, _LIGHT_IDS) == before  # no orphan object or light data

    call("light_create", name="ITInsPoint", light_type="POINT", size=0.4, energy=50)
    call("light_create", name="ITInsSun", light_type="SUN", angle=3, location=[0, 0, 5])
    call("light_create", name="ITInsSpot", light_type="SPOT", spot_angle=40, spot_blend=0.5)
    area = call(
        "light_create",
        name="ITInsArea",
        light_type="AREA",
        shape="ELLIPSE",
        size=2,
        size_y=0.5,
        location=[3, 0, 0],
        look_at=[0, 0, 0],
        temperature=3000,
    )
    assert area["shape"] == "ELLIPSE" and area["color"][0] == pytest.approx(1) and area["color"][2] < 0.5

    with pytest.raises(protocol.BridgeError, match="does not apply to SUN"):
        call("light_update", name="ITInsPoint", light_type="SUN", size=2.0)
    report = call("lighting_inspect")
    found = {light["name"]: light for light in report["lights"] if light["name"].startswith("ITIns")}
    assert found["ITInsPoint"]["light_type"] == "POINT" and found["ITInsPoint"]["size"] == pytest.approx(0.4)
    assert found["ITInsSun"]["angle"] == pytest.approx(3) and found["ITInsSun"]["world_direction"] == [0, 0, -1]
    assert found["ITInsSpot"]["spot_angle"] == pytest.approx(40) and found["ITInsSpot"]["spot_blend"] == 0.5
    assert found["ITInsArea"]["size_y"] == pytest.approx(0.5)
    assert found["ITInsArea"]["world_direction"] == pytest.approx([-1, 0, 0], abs=1e-5)
    # Changing the type really changes the settings Blender exposes.
    assert call("light_update", name="ITInsPoint", light_type="SPOT", spot_angle=30)["spot_angle"] == 30

    _python(
        call,
        "o = bpy.data.objects['ITInsSun'].copy(); o.name = 'ITInsSunCopy'; bpy.context.scene.collection.objects.link(o)",
    )
    with pytest.raises(protocol.BridgeError, match="shared by 2 objects"):
        call("light_update", name="ITInsSun", energy=9)
    call("light_update", name="ITInsSun", energy=9, shared_data="make_single_user")
    energies = _python(call, "__result__ = [bpy.data.objects[n].data.energy for n in ('ITInsSun', 'ITInsSunCopy')]")
    assert energies[0] == 9 and energies[1] != 9


_MEAN_BRIGHTNESS = """
image = bpy.data.images.load(args['path'], check_existing=False)
pixels = list(image.pixels)
bpy.data.images.remove(image)
values = [v for i, v in enumerate(pixels) if i % 4 != 3]
__result__ = sum(values) / len(values)
"""


def test_color_management_changes_rendered_brightness_and_rejects_invalid_looks(call, bridge):
    if not _python(call, _USE_FAST_CYCLES):
        pytest.skip("Cycles is not available in this Blender build")
    _python(
        call,
        """
scene = bpy.context.scene
camera = bpy.data.objects.new('ITColorCam', bpy.data.cameras.new('ITColorCam'))
scene.collection.objects.link(camera)
camera.location = (100, 100, 10)
scene.camera = camera
mesh = bpy.data.meshes.new('ITColorPlane')
mesh.from_pydata([(95, 95, 0), (105, 95, 0), (105, 105, 0), (95, 105, 0)], [], [(0, 1, 2, 3)])
scene.collection.objects.link(bpy.data.objects.new('ITColorPlane', mesh))
""",
    )
    call("light_create", name="ITColorSun", light_type="SUN", energy=1, location=[100, 100, 20])
    # Lights left by other tests would clip the picture to white, hiding any exposure change.
    hidden = _python(
        call,
        """
__result__ = [o.name for o in bpy.context.scene.objects
              if o.type == 'LIGHT' and o.name != 'ITColorSun' and not o.hide_render]
for name in __result__:
    bpy.data.objects[name].hide_render = True
""",
    )
    options = call("lighting_inspect", include_options=True)["color_management_options"]
    assert "Standard" in options["view_transforms"] and options["looks"] and options["display_devices"]
    original = call("lighting_inspect")["color_management"]

    def brightness(name):
        path = bridge["tmp"] / f"color-{name}.png"
        call("render_still", output_path=str(path), resolution_x=16, resolution_y=16)
        return call("python_exec", code=_MEAN_BRIGHTNESS, args={"path": str(path)})["result"]

    result = call("color_management_set", view_transform="Standard", exposure=0, gamma=1)
    assert result["color_management"]["view_transform"] == "Standard"
    base = brightness("base")
    call("color_management_set", exposure=1)
    brighter = brightness("brighter")
    assert 0.05 < base < 0.9, base  # not black or clipped, so the comparison means something
    assert brighter > base * 1.15, (base, brighter)

    state = call("lighting_inspect")["color_management"]
    for settings, message in (
        ({"view_transform": "NoSuchTransform"}, "Choose from"),
        ({"view_transform": "Raw", "look": "NoSuchLook", "exposure": 3}, "Choose from"),
    ):
        with pytest.raises(protocol.BridgeError, match=message):
            call("color_management_set", **settings)
        assert call("lighting_inspect")["color_management"] == state
    call(
        "color_management_set",
        view_transform=original["view_transform"],
        look=original["look"],
        exposure=original["exposure"],
        gamma=original["gamma"],
    )
    call("python_exec", code="for n in args['names']: bpy.data.objects[n].hide_render = False", args={"names": hidden})


# A generated test environment (no external assets): the equirectangular width is split into red, green,
# blue and yellow quarters, so the color seen in a direction identifies the part of the image facing it.
_MAKE_QUADRANT_ENVIRONMENT = """
image = bpy.data.images.new('ITQuadrants', 64, 32, alpha=True, float_buffer=True)
colors = [(1, 0, 0, 1), (0, 1, 0, 1), (0, 0, 1, 1), (1, 1, 0, 1)]
image.pixels = [c for y in range(32) for x in range(64) for c in colors[x * 4 // 64]]
image.filepath_raw = args['path']
image.file_format = 'OPEN_EXR'
image.save()
bpy.data.images.remove(image)
"""

_SAMPLE_WORLD = """
from mathutils import Vector
scene = bpy.context.scene
camera = scene.camera
samples = {}
for label, direction in args['directions'].items():
    camera.rotation_euler = Vector(direction).to_track_quat('-Z', 'Y').to_euler()
    scene.render.resolution_x = scene.render.resolution_y = 8
    scene.render.filepath = args['path']
    bpy.ops.render.render(write_still=True)
    image = bpy.data.images.load(args['path'], check_existing=False)
    pixels = list(image.pixels)
    bpy.data.images.remove(image)
    samples[label] = pixels[(4 * 8 + 4) * 4:(4 * 8 + 4) * 4 + 3]
__result__ = samples
"""

_WORLD_SCENE = """
original = bpy.context.scene
scene = bpy.data.scenes.new('ITWorld')
camera = bpy.data.objects.new('ITWorldCam', bpy.data.cameras.new('ITWorldCam'))
camera.data.lens = 120
scene.collection.objects.link(camera)
scene.camera = camera
scene.render.engine = 'CYCLES'
scene.cycles.samples = 4
scene.cycles.use_denoising = False
scene.view_settings.view_transform = 'Standard'
"""


def _color_name(rgb):
    table = {"red": (1, 0, 0), "green": (0, 1, 0), "blue": (0, 0, 1), "yellow": (1, 1, 0)}
    return min(table, key=lambda name: sum((a - b) ** 2 for a, b in zip(table[name], rgb, strict=True)))


def test_world_orientation_sky_and_preview_renders(call, bridge):
    if not _python(call, _USE_FAST_CYCLES):
        pytest.skip("Cycles is not available in this Blender build")
    environment = bridge["tmp"] / "quadrants.exr"
    assert call("python_exec", code=_MAKE_QUADRANT_ENVIRONMENT, args={"path": str(environment)})["error"] is None
    call("object_create", mesh_type="sphere", name="ITWorldBall", location=[300, 0, 0])

    # Plain color and strength on the scene's existing world.
    color = call("world_set", mode="color", color=[0.4, 0.4, 0.4], strength=1.5, on_conflict="new_world")
    assert color["settings"] == {"mode": "color", "color": [0.4, 0.4, 0.4], "strength": 1.5}
    ball = {"object": "ITWorldBall", "mode": "material", "lighting": "world", "resolution": 64, "views": ["front"]}

    def preview_center():
        loop = asyncio.new_event_loop()
        connection = BlenderConnection(port=bridge["port"])
        context = MagicMock()
        context.request_context.lifespan_context = connection
        try:
            blocks = loop.run_until_complete(server.view_capture(context, **ball))
        finally:
            loop.run_until_complete(connection.disconnect())
            loop.close()
        path = bridge["tmp"] / "ball.png"
        path.write_bytes(base64.b64decode(blocks[-1].data))
        return _python(
            call,
            f"""
image = bpy.data.images.load({str(path)!r}, check_existing=False)
pixels = list(image.pixels)
bpy.data.images.remove(image)
__result__ = pixels[(32 * 64 + 32) * 4:(32 * 64 + 32) * 4 + 3]
""",
        )

    neutral = preview_center()
    assert 0.1 < neutral[0] < 0.95 and max(neutral) - min(neutral) < 0.02  # neutral grey environment light

    # A missing image must not change anything.
    before = call("world_get")["settings"]
    with pytest.raises(protocol.BridgeError, match="not found"):
        call("world_set", mode="environment", filepath=str(bridge["tmp"] / "missing.hdr"))
    assert call("world_get")["settings"] == before

    environment_result = call("world_set", mode="environment", filepath=str(environment), strength=1)
    assert environment_result["settings"]["image"]["size"] == [64, 32]
    _python(call, _WORLD_SCENE + "scene.world = original.world\nbpy.app.driver_namespace['it_scene'] = original.name")
    # Render the shared world from a scene of its own, so other tests' objects stay out of the picture.
    diagonals = {"+X+Y": (1, 1, 0), "-X+Y": (-1, 1, 0), "-X-Y": (-1, -1, 0), "+X-Y": (1, -1, 0)}

    def seen():
        switch = "scene = bpy.data.scenes['ITWorld']\nscene.world = bpy.data.scenes[bpy.app.driver_namespace['it_scene']].world\n"
        render = _SAMPLE_WORLD.replace("scene = bpy.context.scene", switch).replace(
            "bpy.ops.render.render(write_still=True)", "bpy.ops.render.render(write_still=True, scene=scene.name)"
        )
        result = call(
            "python_exec", code=render, args={"directions": diagonals, "path": str(bridge["tmp"] / "world.png")}
        )
        assert result["error"] is None, result
        return {label: _color_name(rgb) for label, rgb in result["result"].items()}

    # Another scene now uses this world, so changing it needs an explicit choice.
    with pytest.raises(protocol.BridgeError, match="shared with scene"):
        call("world_set", rotation=90)
    call("world_set", rotation=0, on_conflict="replace")
    # The middle of the image faces +X, and moving right across the image turns clockwise seen from above.
    assert seen() == {"+X+Y": "green", "-X+Y": "red", "-X-Y": "yellow", "+X-Y": "blue"}
    call("world_set", rotation=90, on_conflict="replace")
    # Positive rotation turns the environment counterclockwise: blue moved from +X-Y to +X+Y.
    assert seen() == {"+X+Y": "blue", "-X+Y": "green", "-X-Y": "red", "+X-Y": "yellow"}
    _python(call, "bpy.data.scenes.remove(bpy.data.scenes['ITWorld'])")

    # A custom node setup is protected, and new_world keeps it intact.
    _python(
        call,
        """
world = bpy.data.worlds.new('ITCustomWorld')
world.use_nodes = True
tree = world.node_tree
noise = tree.nodes.new('ShaderNodeTexNoise')
background = next(n for n in tree.nodes if n.type == 'BACKGROUND')
tree.links.new(noise.outputs[0], background.inputs['Color'])
bpy.context.scene.world = world
""",
    )
    count = "__result__ = [len(bpy.data.worlds['ITCustomWorld'].node_tree.nodes), len(bpy.data.worlds['ITCustomWorld'].node_tree.links)]"
    graph = _python(call, count)
    with pytest.raises(protocol.BridgeError) as conflict:
        call("world_set", mode="sky")
    assert conflict.value.code == "conflict" and _python(call, count) == graph

    sky = call("world_set", mode="sky", sun_elevation=35, sun_rotation=90, strength=0.1, on_conflict="new_world")
    assert sky["kept_world"] == "ITCustomWorld" and _python(call, count) == graph
    assert sky["settings"]["sun_rotation"] == pytest.approx(90) and sky["settings"]["sun_elevation"] == pytest.approx(
        35
    )
    call("color_management_set", view_transform="Standard", exposure=-3)
    outdoor = preview_center()
    call("color_management_set", exposure=0)
    assert 0.02 < max(outdoor) < 0.999 and outdoor[2] != pytest.approx(neutral[2])
    for sky_type in call("world_get")["sky_types"]:
        assert call("world_set", sky_type=sky_type)["settings"]["sky_type"] == sky_type
    call("world_set", mode="color", color=[0.05, 0.05, 0.05], strength=1)


# Four faces in four slots on a mesh shared by two objects, each with one object-linked slot. This is
# the layout where Blender's own slot removal drops one object's material and misaligns the other's.
_SLOT_FIXTURE = """
suffix = args['suffix']
mesh = bpy.data.meshes.new('ITSlotMesh' + suffix)
mesh.from_pydata([(i, j, 0) for i in range(5) for j in range(2)], [],
                 [(i * 2, i * 2 + 2, i * 2 + 3, i * 2 + 1) for i in range(4)])
names = [f'ITSlot{i}{suffix}' for i in range(4)]
for name in names:
    mesh.materials.append(bpy.data.materials.new(name))
for index, polygon in enumerate(mesh.polygons):
    polygon.material_index = index
objects = []
for letter, slot in (('A', 2), ('B', 3)):
    obj = bpy.data.objects.new('ITSlot' + letter + suffix, mesh)
    bpy.context.scene.collection.objects.link(obj)
    obj.material_slots[slot].link = 'OBJECT'
    obj.material_slots[slot].material = bpy.data.materials.new('ITOwn' + letter + suffix)
    obj.vertex_groups.new(name='strip').add([0, 1, 2, 3], 1.0, 'REPLACE') if letter == 'A' else None
    objects.append(obj.name)
__result__ = objects
"""

_FACE_MATERIALS = """
__result__ = {
    name: [bpy.data.objects[name].material_slots[p.material_index].material.name
           for p in bpy.data.objects[name].data.polygons]
    for name in args['names']
}
"""


def test_material_slots_preserve_what_other_objects_show(call):
    def fixture(suffix):
        result = call("python_exec", code=_SLOT_FIXTURE, args={"suffix": suffix})
        assert result["error"] is None, result
        return result["result"]

    def shown(names):
        result = call("python_exec", code=_FACE_MATERIALS, args={"names": names})
        assert result["error"] is None, result
        return result["result"]

    for removed in range(4):
        suffix = f"_r{removed}"
        first, second = fixture(suffix)
        before = shown([first, second])
        keep = 0 if removed else 1
        slots = call("material_slots", object=first)["slots"]
        assert [slot["faces"] for slot in slots] == [1, 1, 1, 1]
        replacement = {}
        for name in (first, second):
            code = f"__result__ = bpy.data.objects[{name!r}].material_slots[{keep}].material.name"
            replacement[name] = _python(call, code)
        with pytest.raises(protocol.BridgeError, match="pass 'remap_to'"):
            call("material_slot_remove", object=first, index=removed, shared_data="update_all")
        with pytest.raises(protocol.BridgeError, match="shared by 2 objects"):
            call("material_slot_remove", object=first, index=removed, remap_to=keep)
        assert shown([first, second]) == before
        call("material_slot_remove", object=first, index=removed, remap_to=keep, shared_data="update_all")
        after = shown([first, second])
        for name in (first, second):
            expected = [replacement[name] if face == removed else m for face, m in enumerate(before[name])]
            assert after[name] == expected, (removed, name)

    # Making a single user must carry object-linked materials over and leave the other object alone.
    first, second = fixture("_single")
    before = shown([first, second])
    added = call("material_slot_append", object=first, material="ITSlot0_single", shared_data="make_single_user")
    assert "mesh_shared_by" not in added and added["added_index"] == 4
    assert shown([first, second]) == before

    # Three independent regions on one mesh, using each selector, with exact counts.
    call("object_create", name="ITRegions")
    for name in ("ITSkin", "ITTeeth", "ITArmor"):
        call("material_create", name=name)
        call("material_slot_append", object="ITRegions", material=name)
    _python(
        call,
        """
obj = bpy.data.objects['ITRegions']
top = max(v.co.z for v in obj.data.vertices)
obj.vertex_groups.new(name='top').add([v.index for v in obj.data.vertices if v.co.z == top], 1.0, 'REPLACE')
""",
    )
    call("material_assign_faces", object="ITRegions", material="ITTeeth", vertex_group="top")
    result = call("material_assign_faces", object="ITRegions", material="ITArmor", face_indices=[0, 2])
    counts = {slot["material"]: slot["faces"] for slot in result["slots"]}
    assert counts["ITTeeth"] == 1 and counts["ITArmor"] == 2 and counts["ITSkin"] == 3
    assert call("material_assign_faces", object="ITRegions", slot=1, from_slot=2)["selected_faces"] == 2
    linked = call("material_slot_replace", object="ITRegions", index=0, material="ITArmor", link="OBJECT")
    assert linked["slots"][0]["link"] == "OBJECT" and linked["slots"][0]["data_material"] == "ITSkin"
    # The original single-material assign keeps its behaviour: it sets the mesh's slot 0 only.
    before_assign = call("material_slots", object="ITRegions")["slots"]
    assert before_assign[0]["data_material"] == "ITSkin"
    call("material_assign", object="ITRegions", material="ITTeeth")
    after_assign = call("material_slots", object="ITRegions")["slots"]
    assert after_assign[0]["data_material"] == "ITTeeth"
    assert after_assign[0]["material"] == "ITArmor" and after_assign[1:] == before_assign[1:]


_MAKE_TEXTURES = """
import os
for name, color in args['colors'].items():
    image = bpy.data.images.new('ITMake', 8, 8, alpha=True)
    image.colorspace_settings.name = 'Non-Color'
    image.pixels = list(color) * 64
    image.filepath_raw = os.path.join(args['directory'], name + '.png')
    image.file_format = 'PNG'
    image.save()
    bpy.data.images.remove(image)
"""

_TEXTURE_COLORS = {
    "base": (0.8, 0.6, 0.4, 1),
    "orm": (0.25, 0.6, 0.9, 1),
    "dx_normal": (0.5, 0.2, 1.0, 1),
    "gl_normal": (0.5, 0.8, 1.0, 1),  # the same surface in the OpenGL convention
    "emit": (0.0, 0.5, 1.0, 1),
    "alpha": (1.0, 1.0, 1.0, 0.4),
}

_GRAPH = """
tree = bpy.data.materials[args['name']].node_tree
__result__ = [
    sorted((n.name, n.bl_idname) for n in tree.nodes),
    sorted((l.from_node.name, l.from_socket.name, l.to_node.name, l.to_socket.name) for l in tree.links),
]
"""

_EXPORTED_MATERIAL = """
import json, os, struct
bpy.ops.export_scene.gltf(filepath=args['path'], export_format='GLB')
data = open(args['path'], 'rb').read()
length = struct.unpack('<I', data[12:16])[0]
document = json.loads(data[20:20 + length])
blob = data[20 + length + 8:]
material = next(m for m in document['materials'] if m['name'] == args['name'])
pbr = material.get('pbrMetallicRoughness', {})

def pixel(reference):
    if reference is None:
        return None
    image = document['images'][document['textures'][reference['index']]['source']]
    view = document['bufferViews'][image['bufferView']]
    start = view.get('byteOffset', 0)
    path = args['path'] + '.png'
    open(path, 'wb').write(blob[start:start + view['byteLength']])
    loaded = bpy.data.images.load(path, check_existing=False)
    loaded.colorspace_settings.name = 'Non-Color'
    value = list(loaded.pixels[:3])
    bpy.data.images.remove(loaded)
    return value

__result__ = {
    'base': pixel(pbr.get('baseColorTexture')),
    'normal': pixel(material.get('normalTexture')),
    'metallic_roughness': pbr.get('metallicRoughnessTexture', {}).get('index'),
    'occlusion': material.get('occlusionTexture', {}).get('index'),
    'emissive': 'emissiveTexture' in material,
    'alpha_mode': material.get('alphaMode'),
    'alpha_cutoff': material.get('alphaCutoff'),
    'transform': pbr.get('baseColorTexture', {}).get('extensions', {}).get('KHR_texture_transform'),
}
"""

_RENDER_NORMAL = """
scene = bpy.data.scenes.new('ITNormal')
mesh = bpy.data.meshes.new('ITNormalPlane')
mesh.from_pydata([(-1, -1, 0), (1, -1, 0), (1, 1, 0), (-1, 1, 0)], [], [(0, 1, 2, 3)])
layer = mesh.uv_layers.new(name='UVMap')
for index, uv in enumerate([(0, 0), (1, 0), (1, 1), (0, 1)]):
    (layer.uv[index] if hasattr(layer, 'uv') else layer.data[index]).__setattr__('vector' if hasattr(layer, 'uv') else 'uv', uv)
mesh.materials.append(bpy.data.materials[args['name']])
scene.collection.objects.link(bpy.data.objects.new('ITNormalPlane', mesh))
camera = bpy.data.objects.new('ITNormalCam', bpy.data.cameras.new('ITNormalCam'))
camera.location = (0, 0, 3)
camera.data.type = 'ORTHO'
camera.data.ortho_scale = 1.0
scene.collection.objects.link(camera)
scene.camera = camera
light = bpy.data.objects.new('ITNormalSun', bpy.data.lights.new('ITNormalSun', 'SUN'))
light.data.energy = 3.0
light.rotation_euler = (0.9, 0.0, 0.0)  # tilted toward +Y, so flipping the green channel matters
scene.collection.objects.link(light)
scene.render.engine = 'CYCLES'
scene.cycles.samples = 4
scene.cycles.seed = 0
scene.cycles.use_denoising = False
scene.render.resolution_x = scene.render.resolution_y = 8
scene.view_settings.view_transform = 'Standard'
scene.render.filepath = args['path']
bpy.ops.render.render(write_still=True, scene=scene.name)
image = bpy.data.images.load(args['path'], check_existing=False)
pixels = list(image.pixels)
bpy.data.images.remove(image)
for obj in list(scene.collection.objects):
    bpy.data.objects.remove(obj)
bpy.data.scenes.remove(scene)
__result__ = pixels[(4 * 8 + 4) * 4:(4 * 8 + 4) * 4 + 3]
"""


def test_pbr_texture_sets_in_blender_and_gltf(call, bridge):
    folder = bridge["tmp"] / "pbr"
    folder.mkdir(exist_ok=True)

    def python(code, **arguments):
        result = call("python_exec", code=code, args=arguments)
        assert result["error"] is None, (result["error"], result["stderr"])
        return result["result"]

    python(_MAKE_TEXTURES, directory=str(folder), colors=_TEXTURE_COLORS)
    path = {name: str(folder / f"{name}.png") for name in _TEXTURE_COLORS}
    call("object_create", mesh_type="cube", name="ITPbrCube")
    python("import bpy\nbpy.data.objects['ITPbrCube'].data.uv_layers.new(name='UVMap')")
    call("material_create", name="ITPbr")
    call("material_assign", object="ITPbrCube", material="ITPbr")

    def graph():
        return python(_GRAPH, name="ITPbr")

    def bind(**arguments):
        return call("material_set_texture_set", name="ITPbr", **arguments)  # the fixture unwraps "result"

    def export(label):
        return python(_EXPORTED_MATERIAL, name="ITPbr", path=str(folder / f"{label}.glb"))

    full = {
        "orm": path["orm"],
        "maps": {
            "base_color": path["base"],
            "normal": {"path": path["gl_normal"], "convention": "opengl", "strength": 0.7},
            "emission": {"path": path["emit"], "strength": 3},
        },
    }
    result = bind(**full)
    spaces = {item["map"]: (item["color_space"], item.get("channel")) for item in result["bindings"]}
    assert spaces == {
        "base_color": ("sRGB", None),
        "metallic": ("Non-Color", "B"),
        "roughness": ("Non-Color", "G"),
        "normal": ("Non-Color", None),
        "ao": ("Non-Color", "R"),
        "emission": ("sRGB", None),
    }
    links = {(link[0], link[1], link[2], link[3]) for link in graph()[1]}
    ends = {(link[0], link[3]) for link in links}
    assert ("MCP normal:map", "Normal") in ends and ("MCP roughness:through", "Roughness") in ends
    # The green channel of the packed image feeds roughness through its labelled pass-through node.
    assert any(
        link[0] == "MCP separate" and link[1] == "Green" and link[2] == "MCP roughness:through" for link in links
    )
    built = graph()
    bind(**full)
    assert graph() == built  # binding again reuses nodes instead of duplicating them
    exported = export("full")
    assert exported["base"] == pytest.approx(_TEXTURE_COLORS["base"][:3], abs=0.02)
    assert exported["metallic_roughness"] is not None and exported["occlusion"] == exported["metallic_roughness"]
    assert exported["normal"] == pytest.approx(_TEXTURE_COLORS["gl_normal"][:3], abs=0.02) and exported["emissive"]

    # A missing file or a foreign link leaves the graph exactly as it was.
    for arguments, code in (
        ({"maps": {"roughness": str(folder / "missing.png")}}, "not_found"),
        ({"maps": {"base_color": path["base"], "roughness": "https://example.com/r.png"}}, "invalid_arguments"),
    ):
        with pytest.raises(protocol.BridgeError) as failure:
            bind(**arguments)
        assert failure.value.code == code and graph() == built
    python(
        """
tree = bpy.data.materials['ITPbr'].node_tree
noise = tree.nodes.new('ShaderNodeTexNoise')
noise.name = 'Mine'
shader = next(n for n in tree.nodes if n.type == 'BSDF_PRINCIPLED')
tree.links.new(noise.outputs[0], shader.inputs['Roughness'])
"""
    )
    mine = graph()
    with pytest.raises(protocol.BridgeError, match="ShaderNodeTexNoise") as failure:
        bind(maps={"base_color": path["emit"], "roughness": path["base"]})
    assert failure.value.code == "conflict" and graph() == mine
    replaced = bind(maps={"roughness": {"path": path["orm"], "channel": "G"}}, on_conflict="replace")
    assert "roughness" in replaced["replaced"] and ["Mine", "ShaderNodeTexNoise"] in graph()[0]

    # Binding an image already used as color for data loads a separate copy.
    bind(maps={"roughness": path["base"]})
    spaces_of_base = python(
        "__result__ = sorted(i.colorspace_settings.name for i in bpy.data.images if i.filepath.endswith('base.png'))"
    )
    assert spaces_of_base == ["Non-Color", "sRGB"]

    clipped = bind(
        maps={"opacity": {"path": path["alpha"], "channel": "A", "mode": "clip", "threshold": 0.3}},
        mapping={"scale": [2, 3]},
        uv_map="UVMap",
    )
    assert clipped["mapping"]["scale"] == [2, 3] and clipped["uv_map"] == "UVMap"
    exported = export("clip")
    assert exported["alpha_mode"] == "MASK" and exported["alpha_cutoff"] == pytest.approx(0.3)
    assert exported["transform"]["scale"] == [2, 3]
    bind(maps={"opacity": {"path": path["alpha"], "channel": "A", "mode": "blend"}})
    assert export("blend")["alpha_mode"] == "BLEND"

    # The export limits described by the warnings: neither effect reaches the GLB.
    multiplied = bind(maps={"ao": {"path": path["orm"], "mode": "multiply"}})
    assert "without it" in multiplied["warnings"][0]
    occluded = export("multiply")
    assert occluded["base"] is None or occluded["base"] == pytest.approx(_TEXTURE_COLORS["base"][:3], abs=0.02)
    directx = bind(maps={"normal": {"path": path["dx_normal"], "convention": "directx"}})
    assert "inverted" in directx["warnings"][0]
    exported = export("directx")
    flipped = pytest.approx(_TEXTURE_COLORS["gl_normal"][:3], abs=0.02)
    assert exported["normal"] is None or exported["normal"] != flipped

    bump = bind(maps={"height": {"path": path["orm"], "mode": "bump"}})
    assert "not exported" in bump["warnings"][0]
    assert ("MCP normal:map", "Normal") in {(link[0], link[3]) for link in graph()[1] if link[2] == "MCP height:bump"}
    displaced = bind(maps={"height": {"path": path["orm"], "mode": "displacement", "distance": 0.1}})
    assert [item["mode"] for item in displaced["bindings"] if item["map"] == "height"] == ["displacement"]

    removed = bind(remove=["base_color", "metallic", "roughness", "normal", "ao", "emission", "opacity", "height"])
    assert removed["bindings"] == []
    assert not [name for name, _ in graph()[0] if name.startswith("MCP ") and name not in {"MCP uv", "MCP mapping"}]
    assert ["Mine", "ShaderNodeTexNoise"] in graph()[0]


def test_directx_normal_conversion_renders_like_the_opengl_equivalent(call, bridge):
    if not _python(call, _USE_FAST_CYCLES):
        pytest.skip("Cycles is not available in this Blender build")
    folder = bridge["tmp"] / "normals"
    folder.mkdir(exist_ok=True)
    made = call("python_exec", code=_MAKE_TEXTURES, args={"directory": str(folder), "colors": _TEXTURE_COLORS})
    assert made["error"] is None

    def render(name, texture, convention):
        call("material_create", name=name, color=[0.5, 0.5, 0.5])
        call(
            "material_set_texture_set",
            name=name,
            maps={"normal": {"path": str(folder / f"{texture}.png"), "convention": convention}},
        )
        result = call("python_exec", code=_RENDER_NORMAL, args={"name": name, "path": str(folder / f"{name}.png")})
        assert result["error"] is None, result
        return result["result"]

    opengl = render("ITNormalGL", "gl_normal", "opengl")
    directx = render("ITNormalDX", "dx_normal", "directx")
    unconverted = render("ITNormalWrong", "dx_normal", "opengl")
    assert directx == pytest.approx(opengl, abs=0.01)
    assert unconverted != pytest.approx(opengl, abs=0.05)  # the test would notice a missing flip


_GRAPH_STATE = """
def state(tree):
    return [
        sorted((n.name, n.bl_idname) for n in tree.nodes),
        sorted((l.from_node.name, l.from_socket.identifier, l.to_node.name, l.to_socket.identifier) for l in tree.links),
    ]
__result__ = [
    state(bpy.data.materials[args['name']].node_tree),
    [len(bpy.data.materials), len(bpy.data.node_groups), len(bpy.data.worlds)],
]
"""


def _noise_chain(shader):
    """Noise -> color ramp -> base color, and noise -> bump -> normal, with no Python."""
    return [
        {"op": "add_node", "id": "coords", "type": "ShaderNodeTexCoord", "location": [-900, 0]},
        {"op": "add_node", "id": "noise", "type": "ShaderNodeTexNoise", "inputs": {"Scale": 6.0, "Detail": 3.0}},
        {"op": "add_node", "id": "ramp", "type": "ShaderNodeValToRGB"},
        {
            "op": "set_color_ramp",
            "node": "ramp",
            "stops": [
                {"position": 0.4, "color": [0.05, 0.02, 0.01]},
                {"position": 0.6, "color": [0.8, 0.5, 0.2]},
            ],
        },
        {"op": "add_node", "id": "bump", "type": "ShaderNodeBump", "inputs": {"Strength": 0.4}},
        {"op": "connect", "from": "coords", "from_socket": "Object", "to": "noise", "to_socket": "Vector"},
        {"op": "connect", "from": "noise", "from_socket": "Fac", "to": "ramp", "to_socket": "Fac"},
        {"op": "connect", "from": "ramp", "from_socket": "Color", "to": shader, "to_socket": "Base Color"},
        {"op": "connect", "from": "noise", "from_socket": "Fac", "to": "bump", "to_socket": "Height"},
        {"op": "connect", "from": "bump", "from_socket": "Normal", "to": shader, "to_socket": "Normal"},
    ]


def test_shader_graphs_are_inspected_and_patched_all_or_nothing(call, bridge):
    if not _python(call, _USE_FAST_CYCLES):
        pytest.skip("Cycles is not available in this Blender build")
    call("material_create", name="ITGraph")

    def state():
        result = call("python_exec", code=_GRAPH_STATE, args={"name": "ITGraph"})
        assert result["error"] is None, result
        return result["result"]

    def edit(operations, **options):
        return call("shader_graph_edit", operations=operations, material="ITGraph", **options)

    listed = call("shader_graph_inspect", material="ITGraph")
    shader = next(node["id"] for node in listed["nodes"] if node["type"] == "ShaderNodeBsdfPrincipled")
    output = next(node["id"] for node in listed["nodes"] if node["type"] == "ShaderNodeOutputMaterial")
    assert listed["node_count"] == 2 and "inputs" not in listed["nodes"][0]

    before = state()
    chain = _noise_chain(shader)
    # Each bad final operation must leave the tree and the datablock counts exactly as they were,
    # even though every operation before it is valid.
    for last, code, message in (
        (
            {"op": "connect", "from": shader, "from_socket": "BSDF", "to": "bump", "to_socket": "Strength"},
            "invalid_arguments",
            "cannot feed",
        ),
        (
            {"op": "connect", "from": "ramp", "from_socket": "Color", "to": "noise", "to_socket": "Scale"},
            "invalid_arguments",
            "cycle",
        ),
        (
            {"op": "connect", "from": "noise", "from_socket": "Fac", "to": "noise", "to_socket": "Scale"},
            "invalid_arguments",
            "cycle",
        ),
        (
            {"op": "connect", "from": "noise", "from_socket": "Fac", "to": shader, "to_socket": "Base Color"},
            "conflict",
            "already fed",
        ),
        ({"op": "set_input", "node": "noise", "socket": "Nope", "value": 1}, "invalid_arguments", "Use one of"),
        (
            {"op": "set_property", "node": "bump", "property": "name", "value": "x"},
            "invalid_arguments",
            "cannot be set",
        ),
        (
            {"op": "set_property", "node": "noise", "property": "noise_dimensions", "value": "9D"},
            "invalid_arguments",
            "must be one of",
        ),
        ({"op": "add_node", "id": shader, "type": "ShaderNodeMath"}, "invalid_arguments", "already exists"),
        ({"op": "remove_node", "node": output}, "invalid_arguments", "Output nodes"),
        ({"op": "remove_node", "node": "ghost"}, "not_found", "No node named"),
    ):
        with pytest.raises(protocol.BridgeError, match=message) as failure:
            edit([*chain, last])  # ten valid operations, then the bad one
        assert failure.value.code == code, last
        assert state() == before, last

    result = edit(chain)
    assert result["applied"] == 10 and result["node_count"] == 6 and "warnings" not in result
    detail = call("shader_graph_inspect", material="ITGraph", nodes=["ramp", shader])
    ramp = detail["nodes"][0]
    assert [round(stop["position"], 2) for stop in ramp["color_ramp"]["stops"]] == [0.4, 0.6]
    assert {(link["from"], link["to_socket"]) for link in detail["links"]} == {
        ("noise", "Fac"),
        ("ramp", "Base Color"),
        ("bump", "Normal"),
    }
    page = call("shader_graph_inspect", material="ITGraph", limit=4)
    assert len(page["nodes"]) == 4 and page["next_offset"] == 4

    # Sockets that only exist after a setting changes can be used in the same patch.
    edit(
        [
            {
                "op": "add_node",
                "id": "mix",
                "type": "ShaderNodeMix",
                "properties": {"data_type": "RGBA"},
                "inputs": {"Factor_Float": 0.5, "B_Color": [0.1, 0.2, 0.9]},
            },
            {"op": "connect", "from": "ramp", "from_socket": "Color", "to": "mix", "to_socket": "A_Color"},
            {
                "op": "connect",
                "from": "mix",
                "from_socket": "Result_Color",
                "to": shader,
                "to_socket": "Base Color",
                "replace": True,
            },
        ]
    )
    with pytest.raises(protocol.BridgeError, match="does not exist or is disabled"):
        edit([{"op": "set_input", "node": "mix", "socket": "A_Float", "value": 1}])

    # The patched material renders, and the procedural pattern varies across the surface.
    call("object_create", mesh_type="sphere", name="ITGraphBall", location=[500, 0, 0])
    call("material_assign", object="ITGraphBall", material="ITGraph")
    loop = asyncio.new_event_loop()
    connection = BlenderConnection(port=bridge["port"])
    context = MagicMock()
    context.request_context.lifespan_context = connection
    try:
        blocks = loop.run_until_complete(
            server.view_capture(context, object="ITGraphBall", mode="material", resolution=64, views=["front"])
        )
    finally:
        loop.run_until_complete(connection.disconnect())
        loop.close()
    picture = bridge["tmp"] / "graph.png"
    picture.write_bytes(base64.b64decode(blocks[-1].data))
    spread = _python(
        call,
        f"""
image = bpy.data.images.load({str(picture)!r}, check_existing=False)
pixels = list(image.pixels)
bpy.data.images.remove(image)
reds = [pixels[(y * 64 + x) * 4] for y in range(24, 40) for x in range(24, 40)]
__result__ = max(reds) - min(reds)
""",
    )
    assert spread > 0.05

    # Shared node groups need an explicit choice.
    _python(
        call,
        """
group = bpy.data.node_groups.new('ITSharedGroup', 'ShaderNodeTree')
value = group.nodes.new('ShaderNodeValue')
value.name = 'level'
for name in ('ITGroupA', 'ITGroupB'):
    material = bpy.data.materials.new(name)
    material.use_nodes = True
    node = material.node_tree.nodes.new('ShaderNodeGroup')
    node.name = 'shared'
    node.node_tree = group
""",
    )
    inside = call("shader_graph_inspect", material="ITGroupA", group_path=["shared"], sockets=True)
    assert inside["tree"] == "ITSharedGroup" and inside["tree_users"] == 2
    change = [{"op": "set_property", "node": "level", "property": "value", "value": 0.75}]
    levels = (
        "__result__ = [bpy.data.materials[n].node_tree.nodes['shared'].node_tree.nodes['level'].outputs[0]"
        ".default_value for n in ('ITGroupA', 'ITGroupB')]"
    )
    with pytest.raises(protocol.BridgeError, match="used 2 times"):
        call("shader_graph_edit", material="ITGroupA", group_path=["shared"], operations=change)
    call(
        "shader_graph_edit",
        material="ITGroupA",
        group_path=["shared"],
        operations=change,
        shared_data="make_single_user",
    )
    assert _python(call, levels) == [0.75, 0.0]

    call("world_set", mode="color", color=[0.2, 0.2, 0.2], on_conflict="new_world")
    nodes = call("shader_graph_inspect", world=True)["nodes"]
    background = next(node["id"] for node in nodes if node["type"] == "ShaderNodeBackground")
    call(
        "shader_graph_edit",
        world=True,
        operations=[{"op": "set_input", "node": background, "socket": "Strength", "value": 2.5}],
    )
    assert call("world_get")["settings"]["strength"] == 2.5


_MATERIAL_SNAPSHOT = """
__result__ = {
    'counts': [len(bpy.data.materials), len(bpy.data.images), len(bpy.data.meshes), len(bpy.data.objects),
               len(bpy.data.scenes), len(bpy.data.node_groups)],
    'images': sorted((i.name, i.colorspace_settings.name, i.filepath) for i in bpy.data.images
                     if i.source != 'VIEWER'),
    'graphs': {
        m.name: [sorted(n.name for n in m.node_tree.nodes),
                 sorted((l.from_node.name, l.from_socket.name, l.to_node.name, l.to_socket.name)
                        for l in m.node_tree.links)]
        for m in bpy.data.materials if m.name.startswith('ITDiag')
    },
    'selected': sorted(o.name for o in bpy.context.scene.objects if o.select_get()),
}
"""


def test_material_diagnostics_find_planted_defects_without_changing_anything(call, bridge):
    folder = bridge["tmp"] / "diagnostics"
    folder.mkdir(exist_ok=True)

    def python(code, **arguments):
        result = call("python_exec", code=code, args=arguments)
        assert result["error"] is None, (result["error"], result["stderr"])
        return result["result"]

    colors = {
        "d_basecolor": (0.5, 0.4, 0.3, 1),
        "d_orm": (1, 0.5, 0, 1),
        "d_normal": (0.5, 0.5, 1, 1),
        "d_leaf": (0.2, 0.6, 0.2, 0.5),
        "d_gone": (1, 1, 1, 1),
    }
    python(_MAKE_TEXTURES, directory=str(folder), colors=colors)
    path = {name: str(folder / f"{name}.png") for name in colors}
    for name in ("ITDiagGood", "ITDiagBad", "ITDiagProcedural", "ITDiagCutout"):
        call("material_create", name=name)

    def bind(name, **arguments):
        call("material_set_texture_set", name=name, **arguments)

    bind(
        "ITDiagGood",
        orm=path["d_orm"],
        maps={"base_color": path["d_basecolor"], "normal": {"path": path["d_normal"], "convention": "opengl"}},
    )
    # A cutout takes its alpha from the sRGB color image: alpha is linear, so this is correct.
    bind("ITDiagCutout", maps={"base_color": path["d_leaf"]})
    python(
        """
tree = bpy.data.materials['ITDiagCutout'].node_tree
shader = next(n for n in tree.nodes if n.type == 'BSDF_PRINCIPLED')
texture = next(n for n in tree.nodes if n.type == 'TEX_IMAGE')
tree.links.new(texture.outputs['Alpha'], shader.inputs['Alpha'])
"""
    )
    bind("ITDiagBad", maps={"roughness": path["d_gone"]})
    os.remove(path["d_gone"])
    python(
        """
tree = bpy.data.materials['ITDiagBad'].node_tree
shader = next(n for n in tree.nodes if n.type == 'BSDF_PRINCIPLED')
normal = tree.nodes.new('ShaderNodeTexImage')
normal.name = 'raw normal'
normal.image = bpy.data.images.load(args['normal'], check_existing=False)   # left as sRGB
tree.links.new(normal.outputs['Color'], shader.inputs['Normal'])
metal = tree.nodes.new('ShaderNodeTexImage')
metal.name = 'metal map'
metal.image = bpy.data.images.load(args['color'], check_existing=False)     # left as sRGB
tree.links.new(metal.outputs['Color'], shader.inputs['Metallic'])
empty = tree.nodes.new('ShaderNodeTexImage')
empty.name = 'no image'
tree.links.new(empty.outputs['Color'], shader.inputs['Base Color'])
tree.nodes.new('ShaderNodeTexNoise').name = 'leftover'
""",
        normal=path["d_normal"],
        color=path["d_basecolor"],
    )
    call(
        "shader_graph_edit",
        material="ITDiagProcedural",
        operations=_noise_chain("Principled BSDF"),
    )

    before = python(_MATERIAL_SNAPSHOT)

    def diagnose(**arguments):
        return call("material_diagnose", **arguments)  # the fixture unwraps "result"

    def checks(report):
        return {(item["check"], item["severity"]) for item in report["findings"]}

    good = diagnose(material="ITDiagGood")
    assert good["summary"]["status"] == "ok", good["findings"]
    assert good["materials"][0]["gltf_export"] == {"status": "supported", "reasons": []}
    assert {b["semantic"] for b in good["materials"][0]["bindings"]} == {
        "base_color",
        "metallic",
        "roughness",
        "normal",
        "occlusion",
    }
    assert good["estimated_texture_bytes"] == 3 * int(8 * 8 * 4 * 4 / 3)

    cutout = diagnose(material="ITDiagCutout")
    assert not [item for item in cutout["findings"] if item["check"] in {"color_space", "mixed_use"}], cutout

    bad = diagnose(material="ITDiagBad")
    assert {
        ("missing_file", "error"),
        ("normal_without_normal_map", "error"),
        ("color_space", "error"),
        ("no_image", "error"),
        ("unused_nodes", "warning"),
    } <= checks(bad)
    assert bad["summary"]["status"] == "errors"
    wrong_spaces = {item["subject"].split(".png")[0] for item in bad["findings"] if item["check"] == "color_space"}
    assert wrong_spaces == {"d_basecolor", "d_normal"}  # the metallic and normal images left as sRGB
    assert str(folder) not in json.dumps(bad)

    procedural = diagnose(material="ITDiagProcedural")
    verdict = procedural["materials"][0]["gltf_export"]
    assert verdict["status"] == "unsupported" and any("ShaderNodeTexNoise" in reason for reason in verdict["reasons"])
    assert diagnose(material="ITDiagProcedural", profile="render")["summary"]["errors"] == 0

    budget = diagnose(material="ITDiagGood", max_texture_size=4)
    assert ("texture_size", "error") in checks(budget)
    excused = diagnose(material="ITDiagGood", max_texture_size=4, allow=["texture_size"])
    assert excused["summary"]["status"] == "ok" and excused["summary"]["allowed"] == 3
    assert python(_MATERIAL_SNAPSHOT) == before

    # The export verdict matches what the exporter really does with the supported material.
    call("object_create", mesh_type="cube", name="ITDiagCube")
    python("bpy.data.objects['ITDiagCube'].data.uv_layers.new(name='UVMap')")
    call("material_assign", object="ITDiagCube", material="ITDiagGood")
    exported = python(_EXPORTED_MATERIAL, name="ITDiagGood", path=str(folder / "good.glb"))
    assert exported["base"] and exported["normal"] and exported["occlusion"] is not None
    assert exported["metallic_roughness"] is not None

    # Previews return an image and leave no temporary data behind, also when they fail.
    if python(_USE_FAST_CYCLES):
        before = python(_MATERIAL_SNAPSHOT)
        loop = asyncio.new_event_loop()
        connection = BlenderConnection(port=bridge["port"])
        context = MagicMock()
        context.request_context.lifespan_context = connection
        try:
            for shape in ("sphere", "plane", "cube"):
                blocks = loop.run_until_complete(
                    server.material_preview(context, material="ITDiagGood", shape=shape, resolution=64)
                )
                assert _png_size(base64.b64decode(blocks[-1].data)) == (64, 64), shape
            with pytest.raises(protocol.BridgeError, match="not found"):
                loop.run_until_complete(server.material_preview(context, material="Nope"))
        finally:
            loop.run_until_complete(connection.disconnect())
            loop.close()
        assert python(_MATERIAL_SNAPSHOT) == before


# A matte sphere of the requested radius, far from every other test object, in a scene of its own with a
# black world, so only the rig lights it.
_RIG_SCENE = """
import bmesh
name = args['name']
scene = bpy.data.scenes.new(name)
mesh = bpy.data.meshes.new(name)
bm = bmesh.new()
bmesh.ops.create_icosphere(bm, subdivisions=5, radius=args['radius'])
for face in bm.faces:
    face.smooth = True
bm.to_mesh(mesh)
bm.free()
material = bpy.data.materials.new(name)
material.use_nodes = True
shader = next(n for n in material.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
shader.inputs['Base Color'].default_value = (0.18, 0.18, 0.18, 1)
shader.inputs['Roughness'].default_value = 1.0
mesh.materials.append(material)
obj = bpy.data.objects.new(name, mesh)
scene.collection.objects.link(obj)
obj.location = (args['radius'] * 3, 0, 0)
"""

_RENDER_SCENE = """
scene = bpy.data.scenes[args['scene']]
world = bpy.data.worlds.new(args['scene'])
world.use_nodes = False
world.color = (0, 0, 0)
scene.world = world
for obj in args['objects']:
    scene.collection.objects.link(bpy.data.objects[obj])
scene.camera = bpy.data.objects[args['camera']]
scene.render.engine = 'CYCLES'
scene.cycles.samples = 64
scene.cycles.seed = 1
scene.cycles.use_denoising = False
scene.render.resolution_x = scene.render.resolution_y = 32
scene.view_settings.view_transform = 'Standard'
scene.render.filepath = args['path']
bpy.ops.render.render(write_still=True, scene=scene.name)
image = bpy.data.images.load(args['path'], check_existing=False)
pixels = list(image.pixels)
bpy.data.images.remove(image)
__result__ = [pixels[i] for i in range(0, len(pixels), 4)]
"""

# Blender's own projection: where each bounding box corner lands in the camera frame (0-1).
_PROJECT = """
from bpy_extras.object_utils import world_to_camera_view
from mathutils import Vector
scene = bpy.context.scene
scene.render.resolution_x, scene.render.resolution_y = args['resolution']
bpy.context.view_layer.update()
camera = bpy.data.objects[args['camera']]
obj = bpy.data.objects[args['object']]
corners = [world_to_camera_view(scene, camera, obj.matrix_world @ Vector(c)) for c in obj.bound_box]
__result__ = [[min(c.x for c in corners), max(c.x for c in corners)],
              [min(c.y for c in corners), max(c.y for c in corners)], min(c.z for c in corners)]
"""

_SCENE_LIGHTS_AND_CAMERAS = """
__result__ = {
    'active': bpy.context.scene.camera.name if bpy.context.scene.camera else None,
    'objects': {o.name: [list(map(list, o.matrix_world)),
                         [o.data.energy, list(o.data.color)] if o.type == 'LIGHT' else o.data.lens]
                for o in bpy.context.scene.objects if o.type in {'LIGHT', 'CAMERA'} and not o.get('mcp_rig')
                and not o.name.startswith('ITRigCam')},
}
"""


def test_camera_framing_matches_blender_projection(call):
    call("object_create", mesh_type="cube", name="ITFrameBox", location=[700, 0, 0])
    call("object_scale", name="ITFrameBox", scale=[2.0, 0.5, 1.0])
    original = _python(call, "r = bpy.context.scene.render\n__result__ = [r.resolution_x, r.resolution_y]")
    for resolution, projection in (
        ([1920, 1080], "PERSP"),
        ([600, 900], "PERSP"),
        ([800, 800], "ORTHO"),
        ([600, 900], "ORTHO"),
    ):
        framed = call(
            "camera_frame",
            camera="ITRigCamFrame",
            object="ITFrameBox",
            azimuth=30,
            elevation=25,
            projection=projection,
            margin=1.2,
            aspect=resolution[0] / resolution[1],
        )
        assert framed["active"] is False
        result = call(
            "python_exec",
            code=_PROJECT,
            args={"camera": "ITRigCamFrame", "object": "ITFrameBox", "resolution": resolution},
        )
        assert result["error"] is None, result
        (x_low, x_high), (y_low, y_high), depth = result["result"]
        inside = (1 - 1 / 1.2) / 2
        assert depth > 0
        for low, high in ((x_low, x_high), (y_low, y_high)):
            assert low >= inside - 0.01 and high <= 1 - inside + 0.01, (resolution, projection, result["result"])
        # The subject fills the frame in at least one direction.
        assert max(x_high - x_low, y_high - y_low) > 0.7, (resolution, projection)
    _python(call, f"bpy.context.scene.render.resolution_x, bpy.context.scene.render.resolution_y = {original}")


def test_lighting_rigs_keep_exposure_across_scales_and_leave_other_objects_alone(call, bridge):
    if not _python(call, _USE_FAST_CYCLES):
        pytest.skip("Cycles is not available in this Blender build")
    call("light_create", name="ITRigBystander", light_type="POINT", energy=5, location=[900, 0, 0])
    before = _python(call, _SCENE_LIGHTS_AND_CAMERAS)

    renders = {}
    for label, radius in (("small", 0.01), ("large", 100.0)):
        name = f"ITRigSubject_{label}"
        built = call(
            "python_exec",
            code=_RIG_SCENE + "bpy.context.scene.collection.objects.link(obj)",
            args={"name": name, "radius": radius},
        )
        assert built["error"] is None, built
        camera = f"ITRigCam_{label}"
        call("camera_frame", camera=camera, object=name, azimuth=20, elevation=10, lens=85)
        rig = call("lighting_rig_apply", rig="three_point", object=name, name=f"IT{label}", camera=camera)
        assert rig["camera"] == camera and len(rig["lights"]) == 3
        assert rig["subject_radius"] == pytest.approx(radius * 3**0.5, rel=0.02)
        render = call(
            "python_exec",
            code=_RENDER_SCENE,
            args={
                "scene": name,
                "objects": [light["name"] for light in rig["lights"]],
                "camera": camera,
                "path": str(bridge["tmp"] / f"rig-{label}.png"),
            },
        )
        assert render["error"] is None, render
        renders[label] = render["result"]
    small, large = renders["small"], renders["large"]
    lit = [value for value in small if value > 0.02]
    assert len(lit) > 200 and 0.1 < sum(lit) / len(lit) < 0.9  # neither black nor clipped
    # A 2 cm and a 200 m subject look the same.
    assert sum(abs(a - b) for a, b in zip(small, large, strict=True)) / len(small) < 0.01

    assert _python(call, _SCENE_LIGHTS_AND_CAMERAS) == before

    with pytest.raises(protocol.BridgeError, match="already exists") as conflict:
        call("lighting_rig_apply", rig="three_point", object="ITRigSubject_small", name="ITsmall")
    assert conflict.value.code == "conflict"
    replaced = call(
        "lighting_rig_apply", rig="low_key", object="ITRigSubject_small", name="ITsmall", on_existing="replace"
    )
    assert len(replaced["replaced"]) == 3
    assert sorted(light["name"] for light in replaced["lights"]) == ["ITsmall fill", "ITsmall key", "ITsmall rim"]
    rig_lights = "__result__ = sorted(o.name for o in bpy.data.objects if o.get('mcp_rig') == 'ITsmall')"
    assert len(_python(call, rig_lights)) == 3

    # Removing a rig keeps anything the user put in its collection.
    _python(
        call, "o = bpy.data.objects.new('ITRigKeepsake', None)\nbpy.data.collections['MCP Rig ITsmall'].objects.link(o)"
    )
    removed = call("lighting_rig_remove", name="ITsmall")
    assert len(removed["removed"]) == 3 and removed["kept_in_collection"] == ["ITRigKeepsake"]
    assert call("lighting_rig_remove", name="ITlarge")["kept_in_collection"] == []
    gone = "__result__ = [c.name for c in bpy.data.collections if c.name.startswith('MCP Rig IT')]"
    assert _python(call, gone) == ["MCP Rig ITsmall"]

    # A subject with no size creates nothing.
    _python(
        call,
        "m = bpy.data.meshes.new('ITDot'); m.from_pydata([(0, 0, 0)], [], [])\n"
        "bpy.context.scene.collection.objects.link(bpy.data.objects.new('ITDot', m))",
    )
    counts = "__result__ = [len(bpy.data.lights), len(bpy.data.collections), len(bpy.data.scenes)]"
    existing = _python(call, counts)
    with pytest.raises(protocol.BridgeError, match="no size|no geometry"):
        call("lighting_rig_apply", rig="turntable", object="ITDot")
    assert _python(call, counts) == existing
    assert _python(call, _SCENE_LIGHTS_AND_CAMERAS) == before


@pytest.mark.asyncio
async def test_mcp_stdio_compact_profile_discovers_and_invokes(bridge):
    async with (
        stdio_client(
            StdioServerParameters(
                command=sys.executable,
                args=["-m", "blender_mcp_server", "--profile", "compact"],
                env={
                    **os.environ,
                    "BLENDER_MCP_PORT": str(bridge["port"]),
                    "BLENDER_MCP_TOKEN_FILE": str(bridge["token_file"]),
                    "BLENDER_MCP_TOKEN": "",
                },
            )
        ) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        assert len((await session.list_tools()).tools) == 15

        async def call(tool, **arguments):
            result = await session.call_tool(tool, arguments)
            assert not result.isError, result.content[0].text
            return json.loads(result.content[0].text)

        await call("blender_object_create", name="ITCompact")
        found = await call("blender_capability_search", query="check mesh topology")
        assert found["actions"][0]["action"] == "blender_mesh_inspect"
        await call("blender_capability_describe", actions=["blender_mesh_inspect"])
        report = await call("blender_capability_invoke", action="blender_mesh_inspect", arguments={"name": "ITCompact"})
        assert report["result"]["counts"]["raw"]["faces"] == 6


@pytest.mark.asyncio
async def test_mcp_stdio_preserves_legacy_success_and_exposes_structured_errors(bridge):
    async with (
        stdio_client(
            StdioServerParameters(
                command=sys.executable,
                args=["-m", "blender_mcp_server"],
                env={
                    **os.environ,
                    "BLENDER_MCP_PORT": str(bridge["port"]),
                    "BLENDER_MCP_TOKEN_FILE": str(bridge["token_file"]),
                    "BLENDER_MCP_TOKEN": "",
                },
            )
        ) as (read, write),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        scene = await session.call_tool("blender_scene_get_info")
        assert not scene.isError and json.loads(scene.content[0].text)["name"] == "Scene"
        missing = await session.call_tool("blender_object_get_transform", {"name": "Missing"})
        assert missing.isError and missing.structuredContent["error"]["code"] == "not_found"
        assert missing.structuredContent["error"]["request_id"]
        invalid = await session.call_tool("blender_object_translate", {"name": "Cube", "offset": ["private", 0, 0]})
        assert invalid.isError and invalid.structuredContent["error"]["code"] == "invalid_arguments"
        assert "private" not in invalid.content[0].text


def test_headless_save_preserves_its_source(call, bridge, headless_policy):
    from dataclasses import replace

    directory = bridge["tmp"]
    source = directory / "source.blend"
    output = directory / "copy.blend"
    call("project_save", filepath=str(source))
    executor = HeadlessBlenderExecutor(BLENDER, replace(headless_policy, output_roots=(str(directory),)))
    original = source.read_bytes()
    with pytest.raises(protocol.BridgeError) as denied:
        asyncio.run(
            executor.execute_command(
                "project.save", {"filepath": str(source), "overwrite": True}, blend_file=str(source)
            )
        )
    assert denied.value.code == "permission_denied"
    copied = asyncio.run(executor.execute_command("project.save", {"filepath": "//copy.blend"}, blend_file=str(source)))
    assert copied["filepath"] == str(output) and output.is_file()
    assert source.read_bytes() == original


@pytest.mark.asyncio
async def test_managed_client_refuses_an_unmanaged_live_bridge(bridge, monkeypatch):
    from dataclasses import replace

    from blender_mcp_server.shared import policy

    monkeypatch.delenv("BLENDER_MCP_TOKEN")
    monkeypatch.setenv("BLENDER_MCP_TOKEN_FILE", str(bridge["token_file"]))
    managed = replace(policy.Policy(), output_roots=(str(bridge["tmp"]),))
    connection = BlenderConnection(port=bridge["port"], configured_policy=managed)
    try:
        with pytest.raises(protocol.BridgeError) as denied:
            await connection.send_command("object.create_mesh", {"name": "ShouldNotExist"})
        assert denied.value.code == "policy_mismatch"
    finally:
        await connection.disconnect()


def test_restricted_headless_export_checks_companion_paths(call, bridge, headless_policy):
    from dataclasses import replace

    directory = bridge["tmp"]
    artifacts = directory / "approved"
    artifacts.mkdir()
    outside = directory / "external.mtl"
    outside.write_text("preserve existing contents")
    companion = artifacts / "export.mtl"
    companion.symlink_to(outside)
    source = artifacts / "export-source.blend"
    material = call("material_create", name="ExportMaterial")["name"]
    cube = call("object_create", name="ExportCube")["name"]
    call("material_assign", object=cube, material=material)
    call("project_save", filepath=str(source))
    executor = HeadlessBlenderExecutor(BLENDER, replace(headless_policy, output_roots=(str(artifacts),)))
    with pytest.raises(protocol.BridgeError) as denied:
        asyncio.run(executor.execute_command("export.obj", {"filepath": "//export.obj"}, blend_file=str(source)))
    assert denied.value.code == "permission_denied"
    assert not (artifacts / "export.obj").exists()
    assert outside.read_text() == "preserve existing contents"
    companion.unlink()
    result = asyncio.run(executor.execute_command("export.obj", {"filepath": "//export.obj"}, blend_file=str(source)))
    assert Path(result["filepath"]).is_file() and companion.is_file()
