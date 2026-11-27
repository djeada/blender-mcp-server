"""The recipe catalog: manifest quality, validation, permissions and execution requests."""

import json
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from jsonschema import Draft202012Validator

from blender_mcp_server.recipes import MANIFEST, RECIPE_PATH, catalog, get_recipe
from blender_mcp_server.shared import policy, protocol
from blender_mcp_server.tools.recipes import recipe_get, recipe_run, recipe_search, search_recipes

ROOT = Path(__file__).resolve().parents[2]


def _context(configured=None, outcome=None):
    ctx = MagicMock()
    connection = ctx.request_context.lifespan_context
    connection.policy = configured or policy.Policy()
    connection.send_command = AsyncMock(
        return_value=outcome or {"result": {"ok": True}, "stdout": "", "stderr": "", "error": None}
    )
    return ctx, connection.send_command


def test_manifest_is_complete_and_consistent():
    entries = json.loads(MANIFEST.read_text())["recipes"]
    assert len(entries) == len(catalog()) >= 8
    for recipe in catalog().values():
        assert re.fullmatch(r"[a-z]+(-[a-z]+)*", recipe.id)
        assert recipe.path.is_file() and recipe.path.parent == RECIPE_PATH and recipe.path.name == recipe.file
        assert recipe.version >= 1 and recipe.blender_min and recipe.side_effects and recipe.tags
        for schema in (recipe.input_schema, recipe.output_schema):
            Draft202012Validator.check_schema(schema)
        assert recipe.input_schema["additionalProperties"] is False
        for example in recipe.examples:
            recipe.arguments(example)
        for name, spec in recipe.input_schema["properties"].items():
            assert spec.get("description"), (recipe.id, name)
            if "default" in spec:
                recipe.arguments({**recipe.examples[0], name: spec["default"]})


def test_every_argument_the_manifest_offers_is_read_by_its_script():
    for recipe in catalog().values():
        source = recipe.source()
        for name in recipe.input_schema["properties"]:
            assert re.search(
                rf"""(args|params|globals\(\)\.get\("args", \{{\}}\))(\.get\(|\[)\s*["']{name}["']""", source
            ) or (f'"{name}"' in source), (recipe.id, name)


def test_the_wheel_packages_exactly_the_catalog():
    tomllib = pytest.importorskip("tomllib")  # Python 3.11+
    config = tomllib.loads((ROOT / "pyproject.toml").read_text())
    packaged = {
        Path(path).name
        for path in config["tool"]["hatch"]["build"]["targets"]["wheel"]["only-include"]
        if path.startswith("examples/")
    }
    assert packaged == {recipe.file for recipe in catalog().values()}
    assert "COPY examples/library/" in (ROOT / "Dockerfile").read_text()


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("add a primitive cube", "create-mesh"),
        ("scatter rocks around", "scatter-objects"),
        ("physics simulation falling debris", "rigid-body"),
        ("camera shot", "setup-camera"),
        ("glowing neon material", "emissive-material"),
    ],
)
def test_search_finds_reviewed_recipes(query, expected):
    assert search_recipes(query)[0] == expected


@pytest.mark.asyncio
async def test_search_is_bounded_and_get_is_one_card():
    page = await recipe_search(limit=3)
    assert len(page["recipes"]) == 3 and page["next_offset"] == 3 and page["total"] == len(catalog())
    assert "input_schema" not in json.dumps(page)
    ctx, send = _context()
    card = await recipe_get(ctx, "create-tree")
    assert card["input_schema"]["properties"]["height"]["default"] == 3.0
    assert card["allowed_by_server_policy"] is True and "script_root_to_approve" not in card
    assert len(json.dumps(card)) < 3_000
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_search_filters_by_blender_version():
    assert (await recipe_search(blender_version="3.5"))["total"] == 0
    assert (await recipe_search(blender_version="3.6.23"))["total"] == len(catalog())


@pytest.mark.parametrize("bad_id", ["nope", "../create_tree", "create_tree.py", "/etc/passwd", "create-tree/../x", ""])
@pytest.mark.asyncio
async def test_ids_are_only_looked_up_in_the_manifest(bad_id):
    ctx, send = _context()
    for call in (recipe_get(ctx, bad_id), recipe_run(ctx, bad_id)):
        with pytest.raises(protocol.BridgeError) as error:
            await call
        assert error.value.code == "not_found"
    send.assert_not_awaited()


@pytest.mark.parametrize(
    ("recipe", "arguments", "message"),
    [
        ("scatter-objects", {}, "'source' is a required property"),
        ("scatter-objects", {"source": "A", "count": 501}, "count"),
        ("scatter-objects", {"source": "A", "count": 2.5}, "count"),
        ("create-mesh", {"mesh_type": "teapot"}, "mesh_type"),
        ("create-mesh", {"location": [0, 0]}, "location"),
        ("create-mesh", {"script_path": "/tmp/x.py"}, "Additional properties"),
        ("create-mesh", {"size": float("inf")}, "finite"),
        ("rigid-body", {"objects": []}, "objects"),
        ("setup-camera", {"set_active": "yes"}, "set_active"),
    ],
)
@pytest.mark.asyncio
async def test_invalid_arguments_never_reach_blender(recipe, arguments, message):
    ctx, send = _context()
    with pytest.raises(protocol.BridgeError, match=re.escape(message)) as error:
        await recipe_run(ctx, recipe, arguments)
    assert error.value.code == "invalid_arguments"
    send.assert_not_awaited()


@pytest.mark.asyncio
async def test_run_sends_the_reviewed_source_with_defaults_filled_in():
    ctx, send = _context()
    result = await recipe_run(ctx, "create-mesh", {"name": "Orb"}, timeout_seconds=20)
    command, params = send.await_args.args
    assert command == "python.execute"
    assert params == {
        "code": get_recipe("create-mesh").source(),
        "args": {"mesh_type": "cube", "location": [0, 0, 0], "size": 2.0, "name": "Orb"},
        "timeout_seconds": 20,
    }
    assert result == {"recipe": "create-mesh", "version": 1, "result": {"ok": True}}


@pytest.mark.asyncio
async def test_without_inline_permission_only_the_approved_path_route_is_used():
    ctx, send = _context(policy.Policy(allow_inline_code=False))
    await recipe_run(ctx, "create-mesh")
    params = send.await_args.args[1]
    assert params["script_path"] == str(get_recipe("create-mesh").path) and "code" not in params
    assert (await recipe_get(ctx, "create-mesh"))["script_root_to_approve"] == str(RECIPE_PATH)


@pytest.mark.asyncio
async def test_a_blender_side_inline_refusal_falls_back_to_the_path_which_blender_still_authorizes():
    refusal = protocol.BridgeError("permission_denied", "Inline code execution is disabled")
    denied = protocol.BridgeError("permission_denied", "Script path denied: file is outside approved script roots")
    ctx, send = _context()
    send.side_effect = [refusal, denied]
    with pytest.raises(protocol.BridgeError, match="outside approved script roots"):
        await recipe_run(ctx, "create-mesh")
    assert [sorted(call.args[1])[:2] for call in send.await_args_list] == [["args", "code"], ["args", "script_path"]]


@pytest.mark.asyncio
async def test_other_bridge_failures_are_not_retried():
    ctx, send = _context()
    send.side_effect = protocol.BridgeError("response_timeout", "late")
    with pytest.raises(protocol.BridgeError, match="late"):
        await recipe_run(ctx, "create-mesh")
    send.assert_awaited_once()


@pytest.mark.parametrize(
    ("outcome", "code"),
    [
        ({"error": "ValueError: Blender script failed"}, "command_failed"),
        ({"error": "Execution exceeded timeout", "timed_out": True}, "execution_timeout"),
    ],
)
@pytest.mark.asyncio
async def test_script_failures_are_errors(outcome, code):
    ctx, _ = _context(outcome=outcome)
    with pytest.raises(protocol.BridgeError) as error:
        await recipe_run(ctx, "create-tree")
    assert error.value.code == code and "create-tree" in str(error.value)


@pytest.mark.parametrize(
    "configured", [policy.Policy(allow_python=False), policy.Policy(allowed_commands=("scene.get_info",))]
)
@pytest.mark.parametrize("transport", ["bridge", "headless"])
@pytest.mark.asyncio
async def test_disabled_execution_is_refused(configured, transport):
    from dataclasses import replace

    from blender_mcp_server.connection import BlenderConnection

    ctx = MagicMock()
    connection = BlenderConnection(
        configured_policy=replace(configured, transports=("bridge",) if transport == "bridge" else ("headless",))
    )
    ctx.request_context.lifespan_context = connection
    with pytest.raises(PermissionError):
        await recipe_run(ctx, "create-mesh", transport=transport)
    assert connection._writer is None


@pytest.mark.asyncio
async def test_headless_without_inline_code_needs_the_recipe_folder_approved(tmp_path):
    ctx, _ = _context(policy.Policy(transports=("headless",), allow_inline_code=False, script_roots=(str(tmp_path),)))
    with pytest.raises(PermissionError, match="outside approved script roots"):
        await recipe_run(ctx, "create-mesh", transport="headless")
