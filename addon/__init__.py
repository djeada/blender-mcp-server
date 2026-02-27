bl_info = {
    "name": "Blender MCP Bridge",
    "author": "Blender MCP Server",
    "version": (0, 1, 0),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > MCP",
    "description": "TCP bridge for MCP server to control Blender",
    "category": "Development",
}

import bpy
import json
import os
import socket
import threading
import traceback
import logging
from typing import Any

logger = logging.getLogger(__name__)

HOST = "127.0.0.1"
PORT = 9876
BUFFER_SIZE = 65536

# Security: restrict file operations to these directories (set via addon preferences)
SAFE_MODE = False
ALLOWED_PATHS: list[str] = []
TOOL_WHITELIST: set[str] | None = None  # None = all tools allowed


class CommandHandler:
    """Dispatches JSON commands to the appropriate bpy operations."""

    def __init__(self):
        self._handlers: dict[str, callable] = {}
        self._register_builtins()

    def _register_builtins(self):
        self._handlers["scene.get_info"] = self._scene_get_info
        self._handlers["scene.list_objects"] = self._scene_list_objects
        self._handlers["object.get_transform"] = self._object_get_transform
        self._handlers["object.get_hierarchy"] = self._object_get_hierarchy
        self._handlers["material.list"] = self._material_list
        self._handlers["object.create_mesh"] = self._object_create_mesh
        self._handlers["object.delete"] = self._object_delete
        self._handlers["object.translate"] = self._object_translate
        self._handlers["object.rotate"] = self._object_rotate
        self._handlers["object.scale"] = self._object_scale
        self._handlers["object.duplicate"] = self._object_duplicate
        self._handlers["material.create"] = self._material_create
        self._handlers["material.assign"] = self._material_assign
        self._handlers["material.set_color"] = self._material_set_color
        self._handlers["material.set_texture"] = self._material_set_texture
        self._handlers["render.still"] = self._render_still
        self._handlers["render.animation"] = self._render_animation
        self._handlers["export.gltf"] = self._export_gltf
        self._handlers["export.obj"] = self._export_obj
        self._handlers["export.fbx"] = self._export_fbx
        self._handlers["history.undo"] = self._history_undo
        self._handlers["history.redo"] = self._history_redo

    def handle(self, command: str, params: dict) -> Any:
        # Security: check tool whitelist
        if TOOL_WHITELIST is not None and command not in TOOL_WHITELIST:
            raise PermissionError(f"Command '{command}' is not in the tool whitelist")
        handler = self._handlers.get(command)
        if not handler:
            raise ValueError(f"Unknown command: {command}")
        return handler(params)

    # -- Scene tools --

    @staticmethod
    def _validate_filepath(filepath: str) -> str:
        """Security: validate that a filepath is within allowed directories."""
        if not SAFE_MODE:
            return filepath
        abs_path = os.path.abspath(bpy.path.abspath(filepath))
        if not ALLOWED_PATHS:
            # In safe mode with no allowed paths, only allow the blend file directory
            blend_dir = os.path.dirname(bpy.data.filepath) if bpy.data.filepath else os.getcwd()
            ALLOWED_PATHS.append(blend_dir)
        for allowed in ALLOWED_PATHS:
            if abs_path.startswith(os.path.abspath(allowed)):
                return filepath
        raise PermissionError(
            f"File access denied: '{filepath}' is outside allowed directories. "
            f"Allowed: {ALLOWED_PATHS}"
        )

    def _scene_get_info(self, params: dict) -> dict:
        scene = bpy.context.scene
        return {
            "name": scene.name,
            "frame_current": scene.frame_current,
            "frame_start": scene.frame_start,
            "frame_end": scene.frame_end,
            "render_engine": scene.render.engine,
            "resolution_x": scene.render.resolution_x,
            "resolution_y": scene.render.resolution_y,
            "object_count": len(scene.objects),
        }

    def _scene_list_objects(self, params: dict) -> dict:
        type_filter = params.get("type")
        objects = []
        for obj in bpy.context.scene.objects:
            if type_filter and obj.type != type_filter.upper():
                continue
            objects.append({
                "name": obj.name,
                "type": obj.type,
                "location": list(obj.location),
                "visible": obj.visible_get(),
            })
        return {"objects": objects}

    def _object_get_transform(self, params: dict) -> dict:
        name = params["name"]
        obj = bpy.data.objects.get(name)
        if not obj:
            raise ValueError(f"Object '{name}' not found")
        return {
            "name": obj.name,
            "location": list(obj.location),
            "rotation_euler": list(obj.rotation_euler),
            "scale": list(obj.scale),
        }

    def _object_get_hierarchy(self, params: dict) -> dict:
        def build_tree(obj):
            return {
                "name": obj.name,
                "type": obj.type,
                "children": [build_tree(c) for c in obj.children],
            }

        name = params.get("name")
        if name:
            obj = bpy.data.objects.get(name)
            if not obj:
                raise ValueError(f"Object '{name}' not found")
            return build_tree(obj)

        roots = [o for o in bpy.context.scene.objects if o.parent is None]
        return {"roots": [build_tree(r) for r in roots]}

    def _material_list(self, params: dict) -> dict:
        materials = []
        for mat in bpy.data.materials:
            materials.append({
                "name": mat.name,
                "use_nodes": mat.use_nodes,
                "user_count": mat.users,
            })
        return {"materials": materials}

    # -- Object mutation tools --

    def _object_create_mesh(self, params: dict) -> dict:
        mesh_type = params.get("type", "cube").lower()
        name = params.get("name")
        location = params.get("location", [0, 0, 0])
        size = params.get("size", 2.0)

        # Track existing objects to find the newly created one
        existing = set(bpy.data.objects.keys())

        creators = {
            "cube": lambda: bpy.ops.mesh.primitive_cube_add(size=size, location=location),
            "sphere": lambda: bpy.ops.mesh.primitive_uv_sphere_add(radius=size / 2, location=location),
            "cylinder": lambda: bpy.ops.mesh.primitive_cylinder_add(radius=size / 2, depth=size, location=location),
            "plane": lambda: bpy.ops.mesh.primitive_plane_add(size=size, location=location),
            "cone": lambda: bpy.ops.mesh.primitive_cone_add(radius1=size / 2, depth=size, location=location),
            "torus": lambda: bpy.ops.mesh.primitive_torus_add(location=location),
        }

        creator = creators.get(mesh_type)
        if not creator:
            raise ValueError(f"Unknown mesh type: {mesh_type}. Options: {list(creators.keys())}")

        creator()

        # Find the new object by diffing
        new_names = set(bpy.data.objects.keys()) - existing
        if not new_names:
            raise RuntimeError("Failed to create object")
        obj = bpy.data.objects[new_names.pop()]
        if name:
            obj.name = name
        return {"name": obj.name, "type": obj.type, "location": list(obj.location)}

    def _object_delete(self, params: dict) -> dict:
        name = params["name"]
        obj = bpy.data.objects.get(name)
        if not obj:
            raise ValueError(f"Object '{name}' not found")
        bpy.data.objects.remove(obj, do_unlink=True)
        return {"deleted": name}

    def _object_translate(self, params: dict) -> dict:
        name = params["name"]
        obj = bpy.data.objects.get(name)
        if not obj:
            raise ValueError(f"Object '{name}' not found")
        offset = params.get("offset", [0, 0, 0])
        absolute = params.get("location")
        if absolute:
            obj.location = absolute
        else:
            obj.location.x += offset[0]
            obj.location.y += offset[1]
            obj.location.z += offset[2]
        return {"name": obj.name, "location": list(obj.location)}

    def _object_rotate(self, params: dict) -> dict:
        import math
        name = params["name"]
        obj = bpy.data.objects.get(name)
        if not obj:
            raise ValueError(f"Object '{name}' not found")
        rotation = params.get("rotation", [0, 0, 0])
        degrees = params.get("degrees", True)
        if degrees:
            rotation = [math.radians(r) for r in rotation]
        obj.rotation_euler = rotation
        return {"name": obj.name, "rotation_euler": list(obj.rotation_euler)}

    def _object_scale(self, params: dict) -> dict:
        name = params["name"]
        obj = bpy.data.objects.get(name)
        if not obj:
            raise ValueError(f"Object '{name}' not found")
        scale = params.get("scale", [1, 1, 1])
        obj.scale = scale
        return {"name": obj.name, "scale": list(obj.scale)}

    def _object_duplicate(self, params: dict) -> dict:
        name = params["name"]
        obj = bpy.data.objects.get(name)
        if not obj:
            raise ValueError(f"Object '{name}' not found")
        new_obj = obj.copy()
        new_obj.data = obj.data.copy()
        new_name = params.get("new_name")
        if new_name:
            new_obj.name = new_name
        bpy.context.collection.objects.link(new_obj)
        return {"name": new_obj.name, "original": obj.name, "location": list(new_obj.location)}

    # -- Material tools --

    def _material_create(self, params: dict) -> dict:
        name = params.get("name", "Material")
        mat = bpy.data.materials.new(name=name)
        mat.use_nodes = True
        color = params.get("color")
        if color:
            bsdf = mat.node_tree.nodes.get("Principled BSDF")
            if bsdf:
                # color is [r, g, b] or [r, g, b, a], values 0-1
                rgba = list(color) + [1.0] * (4 - len(color))
                bsdf.inputs["Base Color"].default_value = rgba[:4]
        return {"name": mat.name, "use_nodes": mat.use_nodes}

    def _material_assign(self, params: dict) -> dict:
        obj_name = params["object"]
        mat_name = params["material"]
        obj = bpy.data.objects.get(obj_name)
        if not obj:
            raise ValueError(f"Object '{obj_name}' not found")
        mat = bpy.data.materials.get(mat_name)
        if not mat:
            raise ValueError(f"Material '{mat_name}' not found")
        if obj.data.materials:
            obj.data.materials[0] = mat
        else:
            obj.data.materials.append(mat)
        return {"object": obj.name, "material": mat.name}

    def _material_set_color(self, params: dict) -> dict:
        mat_name = params["name"]
        color = params["color"]  # [r, g, b] or [r, g, b, a]
        mat = bpy.data.materials.get(mat_name)
        if not mat:
            raise ValueError(f"Material '{mat_name}' not found")
        if not mat.use_nodes:
            mat.use_nodes = True
        bsdf = mat.node_tree.nodes.get("Principled BSDF")
        if not bsdf:
            raise ValueError(f"Material '{mat_name}' has no Principled BSDF node")
        rgba = list(color) + [1.0] * (4 - len(color))
        bsdf.inputs["Base Color"].default_value = rgba[:4]
        return {"name": mat.name, "color": rgba[:4]}

    def _material_set_texture(self, params: dict) -> dict:
        mat_name = params["name"]
        filepath = params["filepath"]
        self._validate_filepath(filepath)
        mat = bpy.data.materials.get(mat_name)
        if not mat:
            raise ValueError(f"Material '{mat_name}' not found")
        if not mat.use_nodes:
            mat.use_nodes = True
        tree = mat.node_tree
        bsdf = tree.nodes.get("Principled BSDF")
        if not bsdf:
            raise ValueError(f"Material '{mat_name}' has no Principled BSDF node")
        tex_node = tree.nodes.new("ShaderNodeTexImage")
        tex_node.image = bpy.data.images.load(filepath)
        tree.links.new(tex_node.outputs["Color"], bsdf.inputs["Base Color"])
        return {"name": mat.name, "texture": filepath}

    # -- Render tools --

    def _render_still(self, params: dict) -> dict:
        scene = bpy.context.scene
        output_path = params.get("output_path", "//render.png")
        self._validate_filepath(output_path)
        resolution_x = params.get("resolution_x")
        resolution_y = params.get("resolution_y")
        engine = params.get("engine")

        if engine:
            scene.render.engine = engine.upper()
        if resolution_x:
            scene.render.resolution_x = resolution_x
        if resolution_y:
            scene.render.resolution_y = resolution_y

        scene.render.filepath = output_path
        bpy.ops.render.render(write_still=True)
        abs_path = bpy.path.abspath(output_path)
        return {
            "output_path": abs_path,
            "engine": scene.render.engine,
            "resolution": [scene.render.resolution_x, scene.render.resolution_y],
        }

    def _render_animation(self, params: dict) -> dict:
        scene = bpy.context.scene
        output_path = params.get("output_path", "//render_")
        self._validate_filepath(output_path)
        frame_start = params.get("frame_start")
        frame_end = params.get("frame_end")
        engine = params.get("engine")

        if engine:
            scene.render.engine = engine.upper()
        if frame_start is not None:
            scene.frame_start = frame_start
        if frame_end is not None:
            scene.frame_end = frame_end

        scene.render.filepath = output_path
        bpy.ops.render.render(animation=True)
        abs_path = bpy.path.abspath(output_path)
        return {
            "output_path": abs_path,
            "frame_range": [scene.frame_start, scene.frame_end],
            "engine": scene.render.engine,
        }

    # -- Export tools --

    def _export_gltf(self, params: dict) -> dict:
        filepath = params["filepath"]
        self._validate_filepath(filepath)
        if not filepath.endswith((".glb", ".gltf")):
            filepath += ".glb"
        bpy.ops.export_scene.gltf(filepath=filepath)
        return {"filepath": filepath, "format": "glTF"}

    def _export_obj(self, params: dict) -> dict:
        filepath = params["filepath"]
        self._validate_filepath(filepath)
        if not filepath.endswith(".obj"):
            filepath += ".obj"
        bpy.ops.wm.obj_export(filepath=filepath)
        return {"filepath": filepath, "format": "OBJ"}

    def _export_fbx(self, params: dict) -> dict:
        filepath = params["filepath"]
        self._validate_filepath(filepath)
        if not filepath.endswith(".fbx"):
            filepath += ".fbx"
        bpy.ops.export_scene.fbx(filepath=filepath)
        return {"filepath": filepath, "format": "FBX"}

    # -- History tools --

    def _history_undo(self, params: dict) -> dict:
        bpy.ops.ed.undo()
        return {"action": "undo"}

    def _history_redo(self, params: dict) -> dict:
        bpy.ops.ed.redo()
        return {"action": "redo"}


class BlenderMCPServer:
    """TCP socket server running inside Blender."""

    def __init__(self):
        self._server_socket: socket.socket | None = None
        self._thread: threading.Thread | None = None
        self._running = False
        self._handler = CommandHandler()

    def start(self):
        if self._running:
            return
        self._running = True
        self._server_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._server_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._server_socket.settimeout(1.0)
        self._server_socket.bind((HOST, PORT))
        self._server_socket.listen(1)
        self._thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._thread.start()
        logger.info(f"Blender MCP Bridge listening on {HOST}:{PORT}")

    def stop(self):
        self._running = False
        if self._server_socket:
            self._server_socket.close()
            self._server_socket = None
        if self._thread:
            self._thread.join(timeout=3)
            self._thread = None
        logger.info("Blender MCP Bridge stopped")

    def _accept_loop(self):
        while self._running:
            try:
                conn, addr = self._server_socket.accept()
                logger.info(f"MCP client connected from {addr}")
                client_thread = threading.Thread(
                    target=self._handle_client, args=(conn,), daemon=True
                )
                client_thread.start()
            except socket.timeout:
                continue
            except OSError:
                break

    def _handle_client(self, conn: socket.socket):
        conn.settimeout(None)
        buffer = b""
        try:
            while self._running:
                data = conn.recv(BUFFER_SIZE)
                if not data:
                    break
                buffer += data
                # Messages are newline-delimited JSON
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if not line.strip():
                        continue
                    try:
                        request = json.loads(line)
                        response = self._process_request(request)
                    except json.JSONDecodeError as e:
                        response = {
                            "id": None,
                            "success": False,
                            "error": f"Invalid JSON: {e}",
                        }
                    conn.sendall(json.dumps(response).encode() + b"\n")
        except Exception as e:
            logger.error(f"Client handler error: {e}")
        finally:
            conn.close()

    # Commands that modify scene state and need undo push
    MUTATION_COMMANDS = {
        "object.create_mesh", "object.delete", "object.translate", "object.rotate",
        "object.scale", "object.duplicate", "material.create", "material.assign",
        "material.set_color", "material.set_texture",
    }

    def _process_request(self, request: dict) -> dict:
        req_id = request.get("id")
        command = request.get("command", "")
        params = request.get("params", {})
        try:
            # Auto-push undo before mutations
            if command in self.MUTATION_COMMANDS:
                bpy.ops.ed.undo_push(message=f"MCP: {command}")
            result = self._handler.handle(command, params)
            return {"id": req_id, "success": True, "result": result}
        except Exception as e:
            logger.error(f"Command '{command}' failed: {e}\n{traceback.format_exc()}")
            return {"id": req_id, "success": False, "error": str(e)}


# Global server instance
_server: BlenderMCPServer | None = None


class MCP_AddonPreferences(bpy.types.AddonPreferences):
    bl_idname = __name__

    safe_mode: bpy.props.BoolProperty(
        name="Safe Mode",
        description="Restrict file access to project directory and enable tool whitelist",
        default=False,
    )
    port: bpy.props.IntProperty(
        name="Port",
        description="TCP port for the MCP bridge",
        default=9876,
        min=1024,
        max=65535,
    )

    def draw(self, context):
        layout = self.layout
        layout.prop(self, "safe_mode")
        layout.prop(self, "port")


class MCP_PT_Panel(bpy.types.Panel):
    bl_label = "MCP Bridge"
    bl_idname = "MCP_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "MCP"

    def draw(self, context):
        layout = self.layout
        global _server
        if _server and _server._running:
            layout.label(text=f"● Listening on {HOST}:{PORT}", icon="LINKED")
            layout.operator("mcp.stop_server", text="Stop Server")
        else:
            layout.label(text="○ Server stopped", icon="UNLINKED")
            layout.operator("mcp.start_server", text="Start Server")


class MCP_OT_StartServer(bpy.types.Operator):
    bl_idname = "mcp.start_server"
    bl_label = "Start MCP Server"

    def execute(self, context):
        global _server
        if _server is None:
            _server = BlenderMCPServer()
        _server.start()
        self.report({"INFO"}, f"MCP Bridge started on {HOST}:{PORT}")
        return {"FINISHED"}


class MCP_OT_StopServer(bpy.types.Operator):
    bl_idname = "mcp.stop_server"
    bl_label = "Stop MCP Server"

    def execute(self, context):
        global _server
        if _server:
            _server.stop()
        self.report({"INFO"}, "MCP Bridge stopped")
        return {"FINISHED"}


classes = (MCP_AddonPreferences, MCP_PT_Panel, MCP_OT_StartServer, MCP_OT_StopServer)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    # Auto-start the server
    global _server
    _server = BlenderMCPServer()
    _server.start()


def unregister():
    global _server
    if _server:
        _server.stop()
        _server = None
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
