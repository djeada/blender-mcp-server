"""Command metadata, validation, and dispatch; implementations live in feature modules."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Any

import bpy

from . import (
    animation,
    batch,
    camera,
    capture,
    collections,
    color_management,
    lighting,
    lighting_report,
    material_slots,
    materials,
    mesh,
    models,
    modifiers,
    objects,
    pbr,
    project,
    rendering,
    scene,
    world,
)
from .execution import ScriptExecutor
from .jobs import JobManager
from .paths import PathPolicy
from .protocol import InvalidArgumentsError
from .settings import RuntimeSettings

if TYPE_CHECKING:
    from collections.abc import Callable

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class Command:
    handler: Callable[[dict], Any]
    validator: type[models.BridgeParams] | None = None
    mutates: bool = False
    worker_thread: bool = False


class CommandHandler:
    """Compose feature commands with one runtime's policy, executor, and jobs."""

    def __init__(self, settings: RuntimeSettings | None = None):
        self.settings = settings or RuntimeSettings()
        self.policy = PathPolicy(self.settings)
        self.executor = ScriptExecutor(self.settings, self.policy)
        self.jobs = JobManager(self.executor)
        self.commands: dict[str, Command] = {
            "scene.get_info": Command(scene.get_info),
            "scene.execute_batch": Command(partial(batch.execute, handler=self), models.BatchParams),
            "project.get_info": Command(project.get_info),
            "project.save": Command(partial(project.save, policy=self.policy), models.ProjectSaveParams),
            "project.open": Command(partial(project.open_project, policy=self.policy), models.ProjectOpenParams),
            "project.revert": Command(partial(project.revert, policy=self.policy), models.ProjectRevertParams),
            "object.list_modifiers": Command(modifiers.list_modifiers, models.ModifierListParams),
            "object.add_modifier": Command(modifiers.add, models.ModifierAddParams, mutates=True),
            "object.update_modifier": Command(modifiers.update, models.ModifierUpdateParams, mutates=True),
            "object.remove_modifier": Command(modifiers.remove, models.ModifierRemoveParams, mutates=True),
            "scene.list_objects": Command(scene.list_objects, models.SceneListObjectsParams),
            "object.get_transform": Command(objects.get_transform, models.ObjectGetTransformParams),
            "object.get_hierarchy": Command(objects.get_hierarchy, models.ObjectGetHierarchyParams),
            "material.list": Command(materials.list_materials, models.PageParams),
            "material.list_slots": Command(material_slots.list_slots, models.MaterialSlotsListParams),
            "material.slot_append": Command(material_slots.append, models.MaterialSlotAppendParams, mutates=True),
            "material.slot_replace": Command(material_slots.replace, models.MaterialSlotReplaceParams, mutates=True),
            "material.slot_remove": Command(material_slots.remove, models.MaterialSlotRemoveParams, mutates=True),
            "material.assign_faces": Command(
                material_slots.assign_faces, models.MaterialAssignFacesParams, mutates=True
            ),
            "mesh.inspect": Command(mesh.inspect, models.MeshInspectParams),
            "object.create_mesh": Command(objects.create_mesh, models.ObjectCreateMeshParams, mutates=True),
            "object.delete": Command(objects.delete, models.ObjectDeleteParams, mutates=True),
            "object.translate": Command(objects.translate, models.ObjectTranslateParams, mutates=True),
            "object.rotate": Command(objects.rotate, models.ObjectRotateParams, mutates=True),
            "object.scale": Command(objects.scale, models.ObjectScaleParams, mutates=True),
            "object.duplicate": Command(objects.duplicate, models.ObjectDuplicateParams, mutates=True),
            "material.create": Command(materials.create, models.MaterialCreateParams, mutates=True),
            "material.assign": Command(materials.assign, models.MaterialAssignParams, mutates=True),
            "material.set_color": Command(materials.set_color, models.MaterialSetColorParams, mutates=True),
            "material.set_texture": Command(
                partial(materials.set_texture, policy=self.policy), models.MaterialSetTextureParams, mutates=True
            ),
            "material.set_texture_set": Command(
                partial(pbr.set_texture_set, policy=self.policy), models.MaterialTextureSetParams, mutates=True
            ),
            "camera.create": Command(camera.create, models.CameraCreateParams, mutates=True),
            "camera.update": Command(camera.update, models.CameraUpdateParams, mutates=True),
            "lighting.inspect": Command(lighting_report.inspect, models.LightingInspectParams),
            "render.set_color_management": Command(color_management.update, models.ColorManagementParams, mutates=True),
            "world.get": Command(world.get),
            "world.set": Command(partial(world.update, policy=self.policy), models.WorldSetParams, mutates=True),
            "light.create": Command(lighting.create, models.LightCreateParams, mutates=True),
            "light.update": Command(lighting.update, models.LightUpdateParams, mutates=True),
            "timeline.get": Command(animation.timeline_get),
            "timeline.set": Command(animation.timeline_set, models.TimelineSetParams, mutates=True),
            "keyframe.insert": Command(animation.keyframe_insert, models.KeyframeInsertParams, mutates=True),
            "keyframe.list": Command(animation.keyframe_list, models.KeyframeListParams),
            "keyframe.remove": Command(animation.keyframe_remove, models.KeyframeRemoveParams, mutates=True),
            "collection.create": Command(collections.create, models.CollectionCreateParams, mutates=True),
            "collection.list": Command(collections.list_collections, models.PageParams),
            "collection.rename": Command(collections.rename, models.CollectionRenameParams, mutates=True),
            "collection.add_object": Command(collections.add_object, models.CollectionObjectParams, mutates=True),
            "collection.remove_object": Command(collections.remove_object, models.CollectionObjectParams, mutates=True),
            "object.rename": Command(objects.rename, models.ObjectRenameParams, mutates=True),
            "object.parent": Command(objects.parent, models.ObjectParentParams, mutates=True),
            "object.unparent": Command(objects.unparent, models.ObjectUnparentParams, mutates=True),
            "render.still": Command(partial(rendering.render_still, policy=self.policy), models.RenderStillParams),
            "render.animation": Command(
                partial(rendering.render_animation, policy=self.policy), models.RenderAnimationParams
            ),
            "view.capture": Command(partial(capture.capture, policy=self.policy), models.ViewCaptureParams),
            "export.gltf": Command(partial(rendering.export_gltf, policy=self.policy), models.ExportFileParams),
            "export.obj": Command(partial(rendering.export_obj, policy=self.policy), models.ExportFileParams),
            "export.fbx": Command(partial(rendering.export_fbx, policy=self.policy), models.ExportFileParams),
            "history.undo": Command(objects.history_undo),
            "history.redo": Command(objects.history_redo),
            "python.execute": Command(self.executor.execute, models.PythonExecuteParams),
            "python.execute_async": Command(self.jobs.execute_async, models.PythonExecuteParams),
            "job.status": Command(
                lambda params: self.jobs.get_status(params["job_id"]), models.JobIdParams, worker_thread=True
            ),
            "job.cancel": Command(
                lambda params: self.jobs.cancel(params["job_id"]), models.JobIdParams, worker_thread=True
            ),
            "job.list": Command(lambda params: self.jobs.list_jobs(), worker_thread=True),
        }

    @property
    def mutation_commands(self) -> frozenset[str]:
        return frozenset(name for name, command in self.commands.items() if command.mutates)

    def is_worker_command(self, name: str) -> bool:
        command = self.commands.get(name)
        return command is not None and command.worker_thread

    def prepare(self, name: str, params: dict | None, sync_settings: bool = True) -> tuple[Command, dict]:
        """Authorize and validate before callers perform side effects such as undo pushes."""
        if sync_settings:
            self.settings.sync_preferences()
        self._authorize(name)
        if params is None:
            params = {}
        if not isinstance(params, dict):
            raise InvalidArgumentsError("Command parameters must be an object")
        command = self.commands.get(name)
        if command is None:
            raise InvalidArgumentsError("Unknown command")
        if command.validator is not None:
            params = command.validator.model_validate(params).model_dump(exclude_none=True)
        return command, params

    def handle(self, command: str, params: dict, sync_settings: bool = True) -> Any:
        specification, values = self.prepare(command, params, sync_settings)
        return specification.handler(values)

    def _authorize(self, name: str) -> None:
        self.settings.policy.require_command(name)
        if self.settings.tool_whitelist is not None and name not in self.settings.tool_whitelist:
            raise PermissionError(f"Command '{name}' is not in the tool whitelist")

    def available_commands(self) -> list[str]:
        available = []
        for name in self.commands:
            try:
                self._authorize(name)
            except PermissionError:
                continue
            available.append(name)
        return available

    def dispatch(self, name: str, params: dict, *, sync_settings: bool = True) -> Any:
        specification, values = self.prepare(name, params, sync_settings)
        return self.execute_prepared(name, specification, values)

    @staticmethod
    def execute_prepared(name: str, specification: Command, values: dict) -> Any:
        result = specification.handler(values)
        if specification.mutates:
            undo_push = bpy.ops.ed.undo_push
            poll = getattr(undo_push, "poll", None)
            try:
                if not callable(poll) or poll():
                    # Blender undo restores the previous checkpoint; record the new state.
                    undo_push(message=f"MCP: {name}")
            except RuntimeError:
                logger.debug("Blender undo checkpoint unavailable for %s", name)
        return result
