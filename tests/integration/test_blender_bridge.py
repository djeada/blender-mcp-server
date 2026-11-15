"""End-to-end tests against a real Blender process.

Opt in with BLENDER_MCP_INTEGRATION=1 (and BLENDER_BIN if blender is not on PATH):

    BLENDER_MCP_INTEGRATION=1 pytest tests/integration --no-cov
"""

import asyncio
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
