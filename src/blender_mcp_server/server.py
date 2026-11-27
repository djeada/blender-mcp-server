"""Assemble the feature tools and expose the stdio server entrypoint."""

import sys
from collections.abc import Sequence

from blender_mcp_server.app import blender_status, mcp
from blender_mcp_server.capabilities import parse_exposure
from blender_mcp_server.tools.animation import (
    keyframe_add,
    keyframe_list,
    keyframe_remove,
    timeline_get,
    timeline_set,
)
from blender_mcp_server.tools.camera import (
    camera_create,
    camera_update,
)
from blender_mcp_server.tools.discovery import (
    capability_describe,
    capability_invoke,
    capability_reset,
    capability_search,
)
from blender_mcp_server.tools.execution import (
    job_cancel,
    job_list,
    job_status,
    python_exec,
    python_exec_async,
)
from blender_mcp_server.tools.exports import (
    export_fbx,
    export_gltf,
    export_obj,
)
from blender_mcp_server.tools.lighting import (
    light_create,
    light_update,
)
from blender_mcp_server.tools.materials import (
    material_assign,
    material_create,
    material_list,
    material_set_color,
    material_set_texture,
)
from blender_mcp_server.tools.mesh import mesh_inspect
from blender_mcp_server.tools.objects import (
    history_redo,
    history_undo,
    object_add_modifier,
    object_create,
    object_delete,
    object_duplicate,
    object_get_hierarchy,
    object_get_transform,
    object_list_modifiers,
    object_parent,
    object_remove_modifier,
    object_rename,
    object_rotate,
    object_scale,
    object_translate,
    object_unparent,
    object_update_modifier,
)
from blender_mcp_server.tools.output import output_read
from blender_mcp_server.tools.project import project_get_info, project_open, project_revert, project_save
from blender_mcp_server.tools.rendering import (
    render_animation,
    render_still,
)
from blender_mcp_server.tools.scene import (
    collection_add_object,
    collection_create,
    collection_list,
    collection_remove_object,
    collection_rename,
    scene_execute_batch,
    scene_get_info,
    scene_list_objects,
)

__all__ = [
    "main",
    "mcp",
    "blender_status",
    "capability_search",
    "capability_describe",
    "capability_invoke",
    "capability_reset",
    "output_read",
    "scene_get_info",
    "scene_execute_batch",
    "project_get_info",
    "project_save",
    "project_open",
    "project_revert",
    "object_list_modifiers",
    "object_add_modifier",
    "object_update_modifier",
    "object_remove_modifier",
    "scene_list_objects",
    "collection_create",
    "collection_list",
    "collection_rename",
    "collection_add_object",
    "collection_remove_object",
    "object_get_transform",
    "object_get_hierarchy",
    "object_create",
    "object_delete",
    "object_translate",
    "object_rotate",
    "object_scale",
    "object_duplicate",
    "object_rename",
    "object_parent",
    "object_unparent",
    "history_undo",
    "history_redo",
    "material_list",
    "material_create",
    "material_assign",
    "material_set_color",
    "material_set_texture",
    "mesh_inspect",
    "camera_create",
    "camera_update",
    "light_create",
    "light_update",
    "timeline_get",
    "timeline_set",
    "keyframe_add",
    "keyframe_list",
    "keyframe_remove",
    "render_still",
    "render_animation",
    "export_gltf",
    "export_obj",
    "export_fbx",
    "python_exec",
    "python_exec_async",
    "job_status",
    "job_cancel",
    "job_list",
]


def main(argv: Sequence[str] | None = None):
    mcp.exposure = parse_exposure(sys.argv[1:] if argv is None else argv)
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
