"""The registry of capability groups and the startup choice of what to advertise.

Advertising only controls which tool schemas a client receives. It grants nothing:
the shared policy and the Blender add-on authorize every command wherever it comes from.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from blender_mcp_server.shared import protocol
from blender_mcp_server.wire import OutputBudget

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence


@dataclass(frozen=True)
class Group:
    summary: str
    # Tool name -> the bridge commands it sends.
    tools: Mapping[str, tuple[str, ...]]
    prerequisites: str = "A running Blender with the MCP Bridge add-on."


GROUPS: dict[str, Group] = {
    "core": Group(
        "Status, scene overview, primitive objects, transforms and undo. Always available.",
        {
            "blender_status": (),
            "blender_scene_get_info": ("scene.get_info",),
            "blender_scene_list_objects": ("scene.list_objects",),
            "blender_object_get_transform": ("object.get_transform",),
            "blender_object_create": ("object.create_mesh",),
            "blender_object_delete": ("object.delete",),
            "blender_object_translate": ("object.translate",),
            "blender_object_rotate": ("object.rotate",),
            "blender_object_scale": ("object.scale",),
            "blender_history_undo": ("history.undo",),
        },
    ),
    "scene": Group(
        "Hierarchy, duplicating, naming, parenting, collections, ordered batches, redo and .blend project files.",
        {
            "blender_object_get_hierarchy": ("object.get_hierarchy",),
            "blender_object_duplicate": ("object.duplicate",),
            "blender_object_rename": ("object.rename",),
            "blender_object_parent": ("object.parent",),
            "blender_object_unparent": ("object.unparent",),
            "blender_history_redo": ("history.redo",),
            "blender_collection_create": ("collection.create",),
            "blender_collection_list": ("collection.list",),
            "blender_collection_rename": ("collection.rename",),
            "blender_collection_add_object": ("collection.add_object",),
            "blender_collection_remove_object": ("collection.remove_object",),
            "blender_scene_execute_batch": ("scene.execute_batch",),
            "blender_project_get_info": ("project.get_info",),
            "blender_project_save": ("project.save",),
            "blender_project_open": ("project.open",),
            "blender_project_revert": ("project.revert",),
        },
    ),
    "modeling": Group(
        "Mesh topology diagnostics and non-destructive modifier stacks (bevel, subdivision, mirror, solidify).",
        {
            "blender_mesh_inspect": ("mesh.inspect",),
            "blender_object_list_modifiers": ("object.list_modifiers",),
            "blender_object_add_modifier": ("object.add_modifier",),
            "blender_object_update_modifier": ("object.update_modifier",),
            "blender_object_remove_modifier": ("object.remove_modifier",),
        },
    ),
    "materials": Group(
        "Create, assign and color materials, set image textures, and manage material slots and face regions.",
        {
            "blender_material_slots": ("material.list_slots",),
            "blender_material_slot_append": ("material.slot_append",),
            "blender_material_slot_replace": ("material.slot_replace",),
            "blender_material_slot_remove": ("material.slot_remove",),
            "blender_material_assign_faces": ("material.assign_faces",),
            "blender_material_list": ("material.list",),
            "blender_material_create": ("material.create",),
            "blender_material_assign": ("material.assign",),
            "blender_material_set_color": ("material.set_color",),
            "blender_material_set_texture": ("material.set_texture",),
            "blender_material_set_texture_set": ("material.set_texture_set",),
        },
    ),
    "lighting": Group(
        "Inspect scene lighting, create and adjust point, sun, spot and area lights, set environment and sky "
        "lighting, exposure and view transforms.",
        {
            "blender_world_get": ("world.get",),
            "blender_world_set": ("world.set",),
            "blender_lighting_inspect": ("lighting.inspect",),
            "blender_color_management_set": ("render.set_color_management",),
            "blender_light_create": ("light.create",),
            "blender_light_update": ("light.update",),
        },
    ),
    "animation": Group(
        "Timeline range and transform keyframes.",
        {
            "blender_timeline_get": ("timeline.get",),
            "blender_timeline_set": ("timeline.set",),
            "blender_keyframe_add": ("keyframe.insert",),
            "blender_keyframe_list": ("keyframe.list",),
            "blender_keyframe_remove": ("keyframe.remove",),
        },
    ),
    "rendering": Group(
        "Inspection views returned as images, cameras, still and animation renders, and glTF, OBJ and FBX export.",
        {
            "blender_camera_create": ("camera.create",),
            "blender_camera_update": ("camera.update",),
            "blender_view_capture": ("view.capture",),
            "blender_render_still": ("render.still",),
            "blender_render_animation": ("render.animation",),
            "blender_export_gltf": ("export.gltf",),
            "blender_export_obj": ("export.obj",),
            "blender_export_fbx": ("export.fbx",),
        },
        "A running Blender with the MCP Bridge add-on, or transport='headless' with a .blend file for captures, "
        "renders and exports. Still and animation renders need a scene camera; captures bring their own.",
    ),
    "knowledge": Group(
        "Offline modeling, texturing and rigging guides, and staged workflows for tasks such as characters, props "
        "and buildings.",
        {
            "blender_workflow": (),
            "blender_guide_search": (),
            "blender_guide_get": (),
        },
        "None. Works without Blender.",
    ),
    "recipes": Group(
        "Reviewed ready-made scripts run by ID with validated arguments: primitives, trees, scattering, glowing "
        "materials, cameras, physics and transform cleanup.",
        {
            "blender_recipe_search": (),
            "blender_recipe_get": (),
            "blender_recipe_run": ("python.execute",),
        },
        "Searching works offline. Running needs the same permission as Python execution.",
    ),
    "scripting": Group(
        "Run Python in Blender, immediately or as cancellable background jobs.",
        {
            "blender_python_exec": ("python.execute",),
            "blender_python_exec_async": ("python.execute_async",),
            "blender_job_status": ("job.status",),
            "blender_job_cancel": ("job.cancel",),
            "blender_job_list": ("job.list",),
        },
        "Python execution allowed by policy, on a running Blender or with transport='headless'.",
    ),
}

# Task words that a tool's name and description may not contain.
KEYWORDS: dict[str, str] = {
    "blender_workflow": "plan how to start approach steps stage guidance orc sword house character prop building",
    "blender_guide_search": "how to technique learn tutorial help advice best practice",
    "blender_guide_get": "read documentation tutorial technique",
    "blender_recipe_search": "ready-made template tree scatter glow emissive physics rigid camera",
    "blender_recipe_run": "ready-made template tree scatter glow emissive physics rigid apply transform",
    "blender_status": "health connection troubleshoot reconnect recover version",
    "blender_scene_get_info": "overview",
    "blender_scene_list_objects": "find search outliner",
    "blender_object_create": "add primitive cube sphere cylinder plane cone torus shape blockout",
    "blender_object_delete": "remove",
    "blender_object_translate": "move position place",
    "blender_object_rotate": "turn orient angle",
    "blender_object_scale": "resize size",
    "blender_history_undo": "revert mistake recover",
    "blender_object_duplicate": "copy clone instance",
    "blender_object_parent": "attach hierarchy",
    "blender_object_unparent": "detach",
    "blender_collection_create": "organize group folder",
    "blender_scene_execute_batch": "multiple several sequence bulk",
    "blender_project_save": "persist write",
    "blender_project_open": "load",
    "blender_mesh_inspect": "topology geometry diagnostic validate check hole manifold watertight triangle polygon "
    "vertex count normal duplicate dimension bound game ready",
    "blender_object_add_modifier": "bevel round edge subdivide subdivision smooth mirror symmetry symmetric thickness "
    "solidify nondestructive",
    "blender_material_create": "shader surface color pbr",
    "blender_material_set_texture": "image map albedo basecolor pbr texturing uv",
    "blender_material_set_color": "paint tint albedo",
    "blender_material_set_texture_set": "pbr texture maps roughness metallic normal ambient occlusion orm emission "
    "opacity alpha height bump displacement gltf game ready",
    "blender_material_assign": "apply shader whole object",
    "blender_material_slots": "multiple materials regions list",
    "blender_material_slot_append": "multiple materials add second another region",
    "blender_material_assign_faces": "paint part region face selection multiple materials skin teeth eyes armor "
    "vertex group",
    "blender_light_create": "lamp illuminate illumination lighting brightness sun spot area key fill rim",
    "blender_light_update": "lamp illumination lighting brightness energy warm cool temperature kelvin softness",
    "blender_lighting_inspect": "lights check review current setup report world exposure",
    "blender_world_get": "environment hdri sky background ambient",
    "blender_world_set": "environment hdri hdr sky sun outdoor daylight background ambient studio backdrop",
    "blender_color_management_set": "exposure brightness contrast tone mapping filmic agx look gamma too dark bright",
    "blender_keyframe_add": "animate animation motion",
    "blender_timeline_set": "animate animation frame duration",
    "blender_camera_create": "view viewpoint shot framing composition lens",
    "blender_camera_update": "view viewpoint framing composition lens zoom",
    "blender_view_capture": "see look visual picture image screenshot preview silhouette front side multiview "
    "wireframe check inspect verify",
    "blender_render_still": "image picture preview screenshot output png",
    "blender_render_animation": "video frames movie",
    "blender_export_gltf": "glb game engine web asset download",
    "blender_export_obj": "wavefront asset",
    "blender_export_fbx": "unity unreal game engine asset",
    "blender_python_exec": "script code bpy custom automation procedural rig bake sculpt uv unwrap",
    "blender_python_exec_async": "script code long running bake simulation physics",
}

PROFILES: dict[str, frozenset[str]] = {
    "compact": frozenset({"core"}),
    "standard": frozenset({"core", "scene", "modeling", "materials", "lighting", "rendering", "knowledge"}),
    "full": frozenset(GROUPS),
}
DEFAULT_PROFILE = "full"

# Advertised only while some allowed group is not, so a full server keeps its original tool list.
DISCOVERY_TOOLS = frozenset(
    {
        "blender_capability_search",
        "blender_capability_describe",
        "blender_capability_invoke",
        "blender_capability_reset",
    }
)

# Advertised with compact output, the only mode that truncates responses.
OUTPUT_TOOL = "blender_output_read"
SUPPORT_TOOLS = DISCOVERY_TOOLS | {OUTPUT_TOOL}
OUTPUT_MODES = ("auto", "compact", "full")

TOOL_GROUPS = {tool: name for name, group in GROUPS.items() for tool in group.tools}
_COMMAND_GROUPS = {
    command: TOOL_GROUPS[tool] for group in GROUPS.values() for tool, cmds in group.tools.items() for command in cmds
}


def _names(kind: str, values: Iterable[str], known: Iterable[str]) -> frozenset[str]:
    names = frozenset(values)
    if unknown := names - set(known):
        raise ValueError(f"Unknown {kind}: {', '.join(sorted(unknown))}. Choose from: {', '.join(known)}")
    return names


@dataclass(frozen=True)
class Exposure:
    profile: str = DEFAULT_PROFILE
    advertised: frozenset[str] = PROFILES[DEFAULT_PROFILE]
    allowed: frozenset[str] = frozenset(GROUPS)
    output: OutputBudget = field(default_factory=OutputBudget)

    @classmethod
    def create(
        cls,
        profile: str = DEFAULT_PROFILE,
        enable: Iterable[str] = (),
        allow: Iterable[str] | None = None,
        output: str = "auto",
        **budgets: int,
    ) -> Exposure:
        """Build a validated exposure. `allow` limits every group, including on-demand use; core is always kept."""
        _names("profile", [profile], PROFILES)
        enabled = _names("capability group", enable, GROUPS)
        allowed = frozenset(GROUPS) if allow is None else _names("capability group", allow, GROUPS) | {"core"}
        if blocked := enabled - allowed:
            raise ValueError(f"Enabled groups are not in the allowed groups: {', '.join(sorted(blocked))}")
        _names("output mode", [output], OUTPUT_MODES)
        compact = profile == "compact" if output == "auto" else output == "compact"
        return cls(profile, (PROFILES[profile] | enabled) & allowed, allowed, OutputBudget(compact, **budgets))

    @property
    def compact_output(self) -> bool:
        return self.output.compact

    @property
    def on_demand(self) -> frozenset[str]:
        """Allowed groups whose tools are not advertised."""
        return self.allowed - self.advertised

    def advertises(self, tool: str) -> bool:
        if tool in DISCOVERY_TOOLS:
            return bool(self.on_demand)
        if tool == OUTPUT_TOOL:
            return self.compact_output
        return TOOL_GROUPS.get(tool) in self.advertised

    def require_allowed_group(self, group: str, subject: str) -> None:
        if group not in self.allowed:
            raise protocol.BridgeError(
                "permission_denied", f"{subject} is in the '{group}' group, which this server does not allow"
            )

    def require_advertised(self, tool: str) -> None:
        if tool in SUPPORT_TOOLS:
            if not self.advertises(tool):
                reason = "every allowed tool is already advertised" if tool in DISCOVERY_TOOLS else "output is full"
                raise protocol.BridgeError("tool_not_enabled", f"{tool} is unavailable because {reason}")
            return
        group = TOOL_GROUPS[tool]
        self.require_allowed_group(group, tool)
        if group not in self.advertised:
            raise protocol.BridgeError(
                "tool_not_enabled",
                f"{tool} is not advertised in the '{self.profile}' profile. Call it through "
                f"blender_capability_describe and blender_capability_invoke, or restart with --enable-groups {group}",
                details={"tool": tool, "group": group, "profile": self.profile},
            )

    def require_arguments(self, tool: str, arguments: Mapping[str, Any]) -> None:
        """Batches reach other groups' commands, so the allowed groups apply to each step."""
        if tool != "blender_scene_execute_batch":
            return
        steps = arguments.get("commands")
        for step in steps if isinstance(steps, list) else ():
            command = step.get("command") if isinstance(step, dict) else None
            if isinstance(command, str) and (group := _COMMAND_GROUPS.get(command)):
                self.require_allowed_group(group, f"Batch command {command}")


def _split(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def parse_exposure(argv: Sequence[str], environ: Mapping[str, str] | None = None) -> Exposure:
    """Read the startup choice. Command-line options take precedence over the environment."""
    env = os.environ if environ is None else environ
    parser = argparse.ArgumentParser(prog="blender-mcp-server", description="Blender MCP server (stdio).")
    parser.add_argument(
        "--profile",
        default=env.get("BLENDER_MCP_PROFILE") or DEFAULT_PROFILE,
        help=f"Which tools to advertise: {', '.join(PROFILES)} (env BLENDER_MCP_PROFILE, default {DEFAULT_PROFILE}).",
    )
    parser.add_argument(
        "--enable-groups",
        default=env.get("BLENDER_MCP_ENABLE_GROUPS", ""),
        help=f"Comma-separated groups to advertise in addition to the profile: {', '.join(GROUPS)} "
        "(env BLENDER_MCP_ENABLE_GROUPS).",
    )
    parser.add_argument(
        "--allow-groups",
        default=env.get("BLENDER_MCP_ALLOWED_GROUPS"),
        help="Comma-separated limit on usable groups, advertised or on demand. Default: all "
        "(env BLENDER_MCP_ALLOWED_GROUPS).",
    )
    parser.add_argument(
        "--output",
        default=env.get("BLENDER_MCP_OUTPUT") or "auto",
        help="'compact' bounds and pages responses; 'full' returns them whole. 'auto' is compact only with the "
        "compact profile (env BLENDER_MCP_OUTPUT).",
    )
    defaults = OutputBudget()
    for name, description in (
        ("max_response_bytes", "Largest compact response before it becomes a preview"),
        ("page_size", "Default page size for compact listings"),
        ("log_tail_chars", "Characters of stdout and stderr shown in compact output"),
    ):
        variable = f"BLENDER_MCP_{name.upper()}"
        parser.add_argument(
            f"--{name.replace('_', '-')}",
            type=int,
            default=env.get(variable) or getattr(defaults, name),  # argparse converts string defaults
            help=f"{description} (env {variable}, default {getattr(defaults, name)}).",
        )
    options = parser.parse_args(argv)
    allow = None if options.allow_groups is None else _split(options.allow_groups)
    try:
        return Exposure.create(
            options.profile,
            _split(options.enable_groups),
            allow,
            options.output,
            **{name: getattr(options, name) for name in OutputBudget.LIMITS},
        )
    except ValueError as exc:
        parser.error(str(exc))
