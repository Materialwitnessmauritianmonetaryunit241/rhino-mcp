# RhinoAIBridge v4.5 — MCP Server
# by tanishqb | https://github.com/tanishqb/rhino-ai-bridge

"""Rhino AI Bridge v4.5 — MCP Server.

This release combines:
  Phase 1 — lean responses (dicts Ã¢â€ ' FastMCP Ã¢â€ ' orjson on wire)
  Phase 2 — scene_version etag surfaced on every response (cache key for the model)
  Phase 3 — atomic batches + reference resolution ($1.object_ids[0] chaining)
  Phase 5 — architect intelligence layer (massing, floors, core, facade, schedules)
  Phase 6 — consolidated 28-tool MCP surface (was 66 in v3)

Phase 4 (multiplexed protocol) and Phase 7 (System.Text.Json) intentionally deferred —
both buy less than the cache + tool-surface work, and both have correctness pitfalls
we'd rather defer than ship hastily.

The plugin still understands the full v3/v4 command vocabulary so older flows and
direct-batch sub-ops keep working. The MCP-exposed surface here is the curated subset
that maps cleanly to how architects work.
"""
from __future__ import annotations

import logging
import sys
from typing import Any, Optional

import json
import orjson
from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field

from rhino_architect.protocol import (
    RhinoCommandError,
    RhinoConnectionError,
    get_connection,
)

logging.basicConfig(level=logging.INFO, stream=sys.stderr)
logger = logging.getLogger("rhino_ai_bridge")

import os

# ── Safe mode ─────────────────────────────────────────────────────────────────
# Set RHINO_SAFE_MODE=1 to block destructive commands.
# Safe, trusted (default), or developer — controlled by env var.
_SAFE_MODE = os.environ.get("RHINO_SAFE_MODE", "").strip().lower() in ("1", "true", "yes")
_TRUSTED_MODE = not _SAFE_MODE  # default

_SAFE_MODE_BLOCKED = {"execute_script", "run_command", "delete_objects", "boolean_operation"}

def _check_safe_mode(tool_name: str) -> dict | None:
    """Return an error dict if safe mode blocks this tool, else None."""
    if _SAFE_MODE and tool_name in _SAFE_MODE_BLOCKED:
        return {
            "status": "error",
            "error_code": "COMMAND_BLOCKED_BY_SAFE_MODE",
            "message": f"Tool '{tool_name}' is blocked in safe mode. "
                       f"Set RHINO_SAFE_MODE=0 or unset the variable to allow it.",
            "safe_mode": True,
            "blocked_tools": sorted(_SAFE_MODE_BLOCKED),
        }
    return None
mcp = FastMCP("RhinoAIBridge")


# Ã¢"â‚¬Ã¢"â‚¬ Helpers Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬
async def _exec(command: str, params: dict[str, Any]) -> dict:
    conn = await get_connection()
    resp = await conn.send_command(command, params)
    if not resp.ok:
        raise RhinoCommandError(resp.message, resp.result)
    return resp.result


async def _exec_simple(command: str, params: dict[str, Any]) -> dict:
    """Execute a command and return the raw result dict.

    Returns dict, not str: FastMCP serializes once on the way out.
    Phase 2: surfaces scene_version on every response so the model can use it as
    an etag for caching scene queries between turns.
    """
    blocked = _check_safe_mode(command)
    if blocked:
        return blocked
    try:
        conn = await get_connection()
        resp = await conn.send_command(command, params)
        if not resp.ok:
            return {"status": "error", "message": resp.message, **(resp.result or {})}
        result = dict(resp.result) if resp.result else {}
        result.setdefault("status", "ok")
        if resp.scene_version is not None and "scene_version" not in result:
            result["scene_version"] = resp.scene_version
        return result
    except (RhinoConnectionError, RhinoCommandError) as e:
        return {"status": "error", "message": str(e)}


async def _exec_batch(
    commands: list[dict[str, Any]],
    atomic: bool = True,
    stop_on_error: Optional[bool] = None,
) -> dict:
    """Phase 3 — execute a batch with optional atomic semantics."""
    try:
        conn = await get_connection()
        resp = await conn.send_batch(commands, atomic=atomic, stop_on_error=stop_on_error)
        result = dict(resp.result) if resp.result else {}
        result.setdefault("status", resp.status)
        if resp.message:
            result.setdefault("message", resp.message)
        if resp.scene_version is not None and "scene_version" not in result:
            result["scene_version"] = resp.scene_version
        return result
    except (RhinoConnectionError, RhinoCommandError) as e:
        return {"status": "error", "message": str(e)}


# Tool annotation hints for the MCP client.
RO = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
WR = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": False, "openWorldHint": False}
WI = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
DE = {"readOnlyHint": False, "destructiveHint": True, "idempotentHint": True, "openWorldHint": False}


# Ã¢"â‚¬Ã¢"â‚¬ Input Models Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬
class Empty(BaseModel):
    model_config = ConfigDict(extra="forbid")


class QuerySceneInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scope: str = "objects"  # objects | layers | summary | scene
    filter: dict[str, Any] = Field(default_factory=dict)
    detail: str = "summary"  # ids | summary | full
    limit: int = Field(default=80, ge=1, le=500)


class CreateObjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type: str = Field(
        default="box",
        description=(
            "What to create. Architectural: wall, slab/floor, column, opening/window/door, roof, "
            "massing/building_mass, core. Primitives: point, line, polyline, circle, arc, ellipse, "
            "curve, box, sphere, cone, cylinder, surface."
        ),
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Type-specific parameters. Examples: "
            "box {origin:[0,0,0], size_x:6000, size_y:6000, size_z:3000}; "
            "wall {start_point:[0,0,0], end_point:[6000,0,0], height:3000, thickness:200}; "
            "massing {footprint:[[0,0,0],[30000,0,0],[30000,18000,0],[0,18000,0]], levels:4, level_height:3600}; "
            "core {boundary:[[9000,6000,0],[15000,6000,0],[15000,12000,0],[9000,12000,0]], height:14400}."
        ),
    )
    layer: Optional[str] = None
    name: Optional[str] = None
    color: Optional[list[int]] = None
    measure: bool = False
    translation: Optional[list[float]] = None
    rotation: Optional[list[float]] = None
    scale: Optional[Any] = None


class TransformObjectsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_ids: list[str] = Field(..., min_length=1)
    operations: list[dict[str, Any]] = Field(
        default_factory=list,
        description=(
            "Optional sequence. Each op has type move/rotate/scale/mirror/array/align_to_grid. "
            "Example: [{type:'move', translation:[3000,0,0]}, {type:'array', count_x:4, spacing_x:8000}]."
        ),
    )
    copy: bool = False
    translation: Optional[list[float]] = None
    angle_degrees: Optional[float] = None
    center: Optional[list[float]] = None
    axis: Optional[list[float]] = None
    scale_factor: Optional[float] = None
    base_point: Optional[list[float]] = None
    mirror_plane_start: Optional[list[float]] = None
    mirror_plane_end: Optional[list[float]] = None
    count_x: Optional[int] = None
    count_y: Optional[int] = None
    spacing_x: Optional[float] = None
    spacing_y: Optional[float] = None


class ModifyObjectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: Optional[str] = None
    object_id: Optional[str] = None
    name: Optional[str] = None
    new_name: Optional[str] = None
    new_color: Optional[list[int]] = None
    new_layer: Optional[str] = None
    visible: Optional[bool] = None
    translation: Optional[list[float]] = None
    rotation: Optional[list[float]] = None
    scale: Optional[Any] = None


class BatchSubCommand(BaseModel):
    """One sub-command inside a batch. The plugin routes on `type`; `params` is passed verbatim.

    `type` must be one of the plugin command names — same names as the MCP tools
    (create_object, derive_floors_from_mass, create_core, transform_objects, modify_object,
    delete_objects, query_scene, setup_arch_layers, batch_layer_visibility, execute_script,
    undo, Ã¢â‚¬Â¦) plus any legacy commands listed in rhino://capabilities.

    `params` is the argument dict exactly as you'd pass to the corresponding standalone tool,
    EXCEPT that any string value may start with a `$N` reference to resolve to a prior result:
        "$1"                Ã¢â€ ' whole result dict of op 1
        "$1.object_ids[0]"  Ã¢â€ ' first GUID from op 1
        "$2.mass_id"        Ã¢â€ ' mass_id field from op 2
        "$3.bounding_box.min" Ã¢â€ ' nested path
    """
    model_config = ConfigDict(extra="forbid")
    type: str = Field(
        ...,
        description=(
            "Plugin command name. Same names as the MCP tools: create_object, "
            "derive_floors_from_mass, create_core, transform_objects, modify_object, "
            "delete_objects, query_scene, report_areas, place_openings_on_facade, "
            "align_to_grid, setup_arch_layers, batch_layer_visibility, create_layer, "
            "capture_viewport, set_view, set_display_mode, select_objects, get_cross_section, "
            "boolean_operation, execute_script, undo. Legacy commands also accepted."
        ),
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Arguments for the command — same shape as calling the tool standalone. "
            "Any string value may be a $N reference to a prior op's result, e.g. "
            "'$1.object_ids[0]' or '$2.mass_id'."
        ),
    )


class BatchCommandInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    commands: list[BatchSubCommand] = Field(
        ...,
        min_length=1,
        description=(
            "Ordered list of sub-commands. Each has a `type` (the plugin command name) "
            "and a `params` dict. Reference earlier results with $N paths in param values."
        ),
    )
    atomic: bool = True
    stop_on_error: Optional[bool] = None


class DeriveFloorsFromMassInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mass_id: str
    level_heights: list[float] = []
    levels: Optional[int] = None
    level_height: float = Field(default=3000, gt=0)
    slab_thickness: float = Field(default=250, gt=0)
    start_z: Optional[float] = None
    layer: Optional[str] = "Slab"


class CreateCoreInput(BaseModel):
    model_config = ConfigDict(extra="allow")
    boundary: list[list[float]] = Field(..., min_length=3)
    height: float = Field(default=3000, gt=0)
    z_level: Optional[float] = None
    wall_thickness: float = Field(default=200, gt=0)
    walls: list[dict[str, Any]] = []
    modules: list[dict[str, Any]] = []
    punch_through: list[str] = []
    wall_layer: Optional[str] = "Core::Walls"
    shaft_layer: Optional[str] = "Core::Shafts"


class PlaceOpeningsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    wall_ids: list[str] = Field(..., min_length=1)
    rhythm: float = Field(default=3000, gt=0)
    sill: float = 900
    head: float = 2400
    width: float = Field(default=1200, gt=0)
    height: Optional[float] = None
    margin: Optional[float] = None
    layer: Optional[str] = "Opening"


class AlignGridInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_ids: list[str] = Field(..., min_length=1)
    grid_spacing: float = Field(default=1000, gt=0)
    snap_z: bool = False


class ReportAreasInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    by: str = "layer"  # layer | level | name
    level_height: float = Field(default=3000, gt=0)


class LayerInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    color: Optional[list[int]] = None
    visible: bool = True
    locked: bool = False
    parent: Optional[str] = None


class SetupLayersInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    prefix: str = ""


class BatchLayerVisInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    show: list[str] = []
    hide: list[str] = []
    isolate: Optional[str] = None


class ObjectIdInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_id: str = Field(..., min_length=1)


class ObjectIdsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_ids: list[str] = Field(..., min_length=1)


class MeasureDistInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    point_a: list[float]
    point_b: list[float]


class CheckIntInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_id_a: str
    object_id_b: str


class ValidateInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_ids: list[str] = []


class DeleteInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_ids: list[str] = Field(..., description="GUIDs to delete, or selectors: 'all', 'by_layer:Layer', 'by_name:Pattern', 'selected'.")


class CaptureInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    width: int = 800
    height: int = 600
    max_bytes: int = 800000
    format: str = "auto"   # "auto" | "png" | "jpeg"
    quality: int = Field(default=80, ge=1, le=100)
    restore_state: bool = Field(default=True, description="Restore viewport camera and display mode after capture. Default True — the AI can inspect the model from any angle without disrupting the user's current view.")
    view: Optional[str] = Field(default=None, description="Temporarily switch to this named view before capturing (Top, Front, Right, Perspective, etc.). Restored if restore_state=True.")
    display_mode: Optional[str] = Field(default=None, description="Temporarily switch to this display mode before capturing (Wireframe, Shaded, Rendered, Arctic, etc.). Restored if restore_state=True.")


class ViewInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    view_name: str


class DisplayInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    mode: str


class SelectInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_ids: list[str]
    clear_selection: bool = True


class CrossSectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    object_id: str
    z_height: float
    layer: Optional[str] = None
    name: Optional[str] = None


class BooleanInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    operation: str
    object_id_a: str
    object_id_b: str
    delete_input: bool = True


class ScriptInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: str
    undo_name: Optional[str] = None
    default_layer: Optional[str] = None


class UndoInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    count: int = 1


class LogInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    count: int = 50
    errors_only: bool = False


class SetCameraInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    location: Optional[list[float]] = Field(None, description="Camera position [x, y, z] in model units. Omit when using box_min/box_max.")
    target: Optional[list[float]] = Field(None, description="Camera target [x, y, z]. Omit when using box_min/box_max.")
    lens_length: Optional[float] = Field(None, description="Lens focal length in mm. 50=normal, 24=wide, 135=tele.")
    projection: Optional[str] = Field(None, description="'perspective' | 'parallel'. Defaults to current.")
    box_min: Optional[list[float]] = Field(None, description="Bounding box min [x,y,z] to zoom-frame. Provide with box_max — camera distance auto-computed.")
    box_max: Optional[list[float]] = Field(None, description="Bounding box max [x,y,z] to zoom-frame. Provide with box_min.")


class GetRhinoCommandsInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filter: str = Field(default="", description="Case-insensitive substring filter. Empty = return all (capped to 200).")


class LayerMaterialInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    layer: str = Field(..., description="Layer name (full path or short name).")
    color: Optional[list[int]] = Field(None, description="Diffuse color [R, G, B] or [R, G, B, A], 0-255.")
    roughness: Optional[float] = Field(None, ge=0.0, le=1.0, description="PBR roughness 0=mirror, 1=matte.")
    metallic: Optional[float] = Field(None, ge=0.0, le=1.0, description="PBR metallic factor 0=dielectric, 1=metal.")
    opacity: Optional[float] = Field(None, ge=0.0, le=1.0, description="Opacity 0=transparent, 1=opaque.")
    emission: Optional[list[int]] = Field(None, description="Emissive color [R, G, B], 0-255.")


class RunCommandInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    command: str = Field(..., description="Rhino command string, exactly as typed in the command line (e.g. 'Contour', '_Box 0,0,0 1000,1000,3000').")
    echo: bool = Field(default=False, description="Echo the command to Rhino's command line. Default False (silent).")


# Ã¢"â‚¬Ã¢"â‚¬ Capabilities Resource Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬
# Long-tail commands (still callable inside `batch`) and discoverable workflows.
CAPABILITIES: dict[str, Any] = {
    "version": "4.5.0",
    "phase": "1+2+3+5+6",
    "deferred_phases": {
        "phase_4": "multiplexed protocol — deferred (UI-thread serialization makes the gain marginal)",
        "phase_7": "System.Text.Json source generators — deferred (low ROI vs. wider risk)",
    },
    "tool_surface": "consolidated",
    "preferred_tools": [
        "query_scene", "create_object", "transform_objects", "batch", "report_areas",
        "capture_viewport", "derive_floors_from_mass", "place_openings_on_facade",
    ],
    "universal_create_types": {
        "architecture": ["wall", "slab", "floor", "column", "opening", "window", "door", "roof", "massing", "building_mass", "core"],
        "primitives": ["point", "line", "polyline", "circle", "arc", "ellipse", "curve", "box", "sphere", "cone", "cylinder", "surface"],
    },
    "transform_operations": ["move", "rotate", "scale", "mirror", "array", "align_to_grid"],
    "object_selectors": ["selected", "all", "last_created", "by_layer:LayerName", "by_name:Pattern", "<guid>"],
    "batch_features": {
        "atomic": True,
        "rollback_on_failure": True,
        "reference_resolution": "$N or $N.path[i]",
        "examples": ["$1.object_ids[0]", "$2.mass_id", "$3.bounding_box.min"],
        "per_op_errors": True,
    },
    "etag": {
        "field": "scene_version",
        "use": "Compare across calls. Same version = scene unchanged. Skip redundant queries.",
    },
    "legacy_plugin_commands_available_via_batch": [
        "create_wall", "create_slab", "create_column", "create_opening", "create_roof",
        "create_box", "create_cylinder", "create_sphere", "create_line", "create_polyline",
        "loft", "sweep1", "pipe", "extrude_curve", "fillet_edges", "offset_curve",
        "extrude_curves", "join_curves", "offset_and_extrude", "move_objects",
        "rotate_objects", "scale_objects", "mirror_objects", "array_objects",
        "list_layers", "set_active_layer", "delete_layer",
        "set_object_layer", "get_context", "get_scene_summary", "get_objects",
        "get_object_details", "validate_architecture", "suggest_tools", "lint_script",
        "get_camera_target", "redo", "get_log_stats", "create_floor_stack",
        "group_objects", "ungroup_objects", "get_groups", "hollow_solid",
        "create_objects_batch",
    ],
    "examples": {
        "massing_first_move": {
            "tool": "create_object",
            "args": {
                "type": "massing",
                "params": {
                    "footprint": [[0, 0, 0], [30000, 0, 0], [30000, 18000, 0], [0, 18000, 0]],
                    "levels": 4,
                    "level_height": 3600,
                },
                "layer": "Massing",
                "name": "Office_4L",
            },
        },
        "atomic_office_in_one_call": {
            "tool": "batch",
            "args": {
                "atomic": True,
                "commands": [
                    {"type": "create_object", "params": {"type": "massing", "params": {
                        "footprint": [[0, 0, 0], [30000, 0, 0], [30000, 18000, 0], [0, 18000, 0]],
                        "levels": 4, "level_height": 3600,
                    }}},
                    {"type": "derive_floors_from_mass", "params": {
                        "mass_id": "$1.mass_id",
                        "level_heights": [4200, 3600, 3600, 3600],
                    }},
                ],
            },
        },
        "facade_in_one_call": {
            "tool": "place_openings_on_facade",
            "args": {
                "wall_ids": ["by_layer:Wall"],
                "rhythm": 3000,
                "width": 1500,
                "sill": 900,
                "head": 2400,
            },
        },
    },
}


# Ã¢"â‚¬Ã¢"â‚¬ Resource Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬
@mcp.resource("rhino://capabilities")
def capabilities() -> str:
    """Long-tail capabilities, examples, legacy command names, preferred workflows.

    Resources are returned as serialized text; this one ships as JSON for easy parsing.
    """
    caps = dict(CAPABILITIES)
    caps["safe_mode"] = _SAFE_MODE
    caps["safe_mode_blocked_tools"] = sorted(_SAFE_MODE_BLOCKED)
    return orjson.dumps(caps).decode("utf-8")


@mcp.resource("rhino://arch-defaults")
async def arch_defaults_resource() -> str:
    """Standard architectural defaults: wall thicknesses, opening sizes, layer names."""
    return orjson.dumps({
        "wall": {"height": 3000, "thickness": 200},
        "slab": {"thickness": 200},
        "column": {"width": 400, "depth": 400, "height": 3000},
        "door": {"width": 900, "height": 2100},
        "window": {"width": 1200, "height": 1500, "sill": 900},
        "roof": {"thickness": 200},
        "massing": {"level_height": 3000, "core_layer": "Core"},
        "layers": ["Wall", "Slab", "Column", "Beam", "Opening", "Roof", "Stair", "Furniture", "Site", "Grid", "Annotation", "Massing", "Core::Walls", "Core::Shafts"],
    }).decode("utf-8")


# Ã¢"â‚¬Ã¢"â‚¬ Tools Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬

@mcp.tool(name="ping", annotations=RO)
async def ping(params: Empty) -> dict:
    """Verify Rhino is reachable. Returns build hash, doc info, units, and current scene_version.

    Cheap (sub-ms on server). Useful at conversation start, and as an etag check —
    if scene_version matches what you saw last time, the scene is unchanged and you
    can skip re-querying."""
    try:
        conn = await get_connection()
        data = await conn.ping()
        data["capabilities_resource"] = "rhino://capabilities"
        data["safe_mode"] = _SAFE_MODE
        # Version compatibility check
        plugin_ver = data.get("protocol_version", "")
        if plugin_ver and plugin_ver != "4.5":
            data["version_warning"] = (f"MCP server expects protocol 4.5; plugin reports {plugin_ver}. " f"Update the .rhp plugin to v4.5 for full compatibility.")
        return data
    except Exception as e:
        return {"status": "error", "message": str(e)}


@mcp.tool(name="query_scene", annotations=RO)
async def query_scene(params: QuerySceneInput) -> dict:
    """Universal scene query — replaces get_context, get_scene_summary, get_objects, list_layers.

    scope='summary' for full scene summary (counts, bbox, layers).
    scope='layers' for layer list with counts.
    scope='objects' (default) with filter={layer, type, name_pattern} and detail=ids/summary/full.

    Phase 2: served from the snapshot cache, so all branches are O(1) or O(M) rather than O(N).
    Returns scene_version — use it as an etag across calls."""
    return await _exec_simple("query_scene", params.model_dump(exclude_none=True))


@mcp.tool(name="create_object", annotations=WR)
async def create_object(params: CreateObjectInput) -> dict:
    """Universal creation tool. Prefer this over primitive-specific tools.

    Architecture types route to specialized creators (wall, slab, column, opening, roof,
    massing, core). Primitives (box, sphere, cylinder, etc.) go through the generic path.

    Returns object_ids and bounding_box. Pass measure=true to also compute area/volume
    (off by default — saves a Brep integration on every floor of a 30-floor stack).

    Examples:
    - type='massing', params={footprint:[[0,0,0],[30000,0,0],[30000,18000,0],[0,18000,0]], levels:4, level_height:3600}
    - type='wall', params={start_point:[0,0,0], end_point:[6000,0,0], height:3000, thickness:200}
    - type='box', params={origin:[0,0,0], size_x:8000, size_y:8000, size_z:3600}
    - type='core', params={boundary:[[9000,6000,0],[15000,6000,0],[15000,12000,0],[9000,12000,0]], height:14400}
    """
    return await _exec_simple("create_object", params.model_dump(exclude_none=True))


@mcp.tool(name="transform_objects", annotations=WR)
async def transform_objects(params: TransformObjectsInput) -> dict:
    """Universal transform tool — replaces move/rotate/scale/mirror/array.

    For one transform, use shorthand fields. For chained transforms, use operations[]:
    each op's output object_ids feed the next, so you can move-then-array in a single call.

    Selectors: 'selected', 'all', 'last_created', 'by_layer:Wall', 'by_name:Floor*', or GUIDs."""
    return await _exec_simple("transform_objects", params.model_dump(exclude_none=True))


@mcp.tool(name="modify_object", annotations=WR)
async def modify_object(params: ModifyObjectInput) -> dict:
    """Rename, recolor, change layer, show/hide, or apply a simple transform to one object."""
    return await _exec_simple("modify_object", params.model_dump(exclude_none=True))


@mcp.tool(name="batch", annotations=WR)
async def batch(params: BatchCommandInput) -> dict:
    """Run many Rhino commands in one round-trip. Supports atomic rollback and $N references.

    WHEN TO USE BATCH (already know all params upfront):
    - Creating many independent objects (walls, slabs, columns in bulk)
    - Layer setup, material assignment, bulk visibility changes
    - Linked ops via $N reference (e.g. massing -> derive_floors in one shot)

    WHEN TO USE INDIVIDUAL TOOL CALLS INSTEAD (step-by-step is more accurate):
    - You need to READ a result before deciding the next step (inspect IDs, bbox, count)
    - Complex boolean/modification ops where geometry must be verified first
    - Placing openings referencing wall IDs returned from a previous create
    - Any workflow needing capture_viewport or validate_objects between steps
    - Debugging: one tool at a time isolates failures
    - Any op where a wrong param would be hard to undo

    RULE: if the next command depends on INSPECTING this command's output (not just
    chaining IDs via $N), use individual calls. If you already know all params, batch.

    Each sub-command: {"type": "<command_name>", "params": {...}}

    References: "$N" resolves to the Nth (1-indexed) prior result:
        $1.object_ids[0]      -> first GUID created by op 1
        $2.mass_id            -> mass_id field from op 2

    With atomic=True: whole batch rolls back on any failure (one undo record).
    With atomic=False: each sub-op commits independently â€” use for large bulk builds.
    Legacy commands (any name from rhino://capabilities) are callable inside batch."""
    raw_commands = [c.model_dump() for c in params.commands]
    return await _exec_batch(raw_commands, atomic=params.atomic, stop_on_error=params.stop_on_error)


# Ã¢"â‚¬Ã¢"â‚¬ Architect intelligence layer Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬

@mcp.tool(name="derive_floors_from_mass", annotations=WR)
async def derive_floors_from_mass(params: DeriveFloorsFromMassInput) -> dict:
    """Section a massing solid at floor heights and extrude each section into a slab.

    Variable level_heights[] for non-uniform floor heights (e.g. taller ground floor).
    Pair with create_object(type='massing') in a batch — chain via $1.mass_id."""
    return await _exec_simple("derive_floors_from_mass", params.model_dump(exclude_none=True))


@mcp.tool(name="create_core", annotations=WR)
async def create_core(params: CreateCoreInput) -> dict:
    """Create a building core as a unit — perimeter walls plus lift, stair, and shaft modules.

    Optional punch_through[] subtracts the core modules from listed massing solids,
    carving the actual voids in your floor stack."""
    return await _exec_simple("create_core", params.model_dump(exclude_none=True))


@mcp.tool(name="place_openings_on_facade", annotations=WR)
async def place_openings_on_facade(params: PlaceOpeningsInput) -> dict:
    """Distribute repeated openings (windows or doors) along walls at a constant rhythm.

    The whole facade in one call. Pass wall_ids=['by_layer:Wall'] to facade-ize every wall."""
    return await _exec_simple("place_openings_on_facade", params.model_dump(exclude_none=True))


@mcp.tool(name="align_to_grid", annotations=WR)
async def align_to_grid(params: AlignGridInput) -> dict:
    """Snap object bounding-box centers to an architectural grid. snap_z controls vertical."""
    return await _exec_simple("align_to_grid", params.model_dump())


@mcp.tool(name="report_areas", annotations=RO)
async def report_areas(params: ReportAreasInput) -> dict:
    """GFA / NFA-style area schedule grouped by layer, level, or name.

    For solid Breps with known volume and bbox height, plan_area = volume / height.
    Falls back to top-face area, then to bbox footprint."""
    return await _exec_simple("report_areas", params.model_dump())


# Ã¢"â‚¬Ã¢"â‚¬ Layers Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬

@mcp.tool(name="create_layer", annotations=WI)
async def create_layer(params: LayerInput) -> dict:
    """Create or update a layer."""
    return await _exec_simple("create_layer", params.model_dump(exclude_none=True))


@mcp.tool(name="setup_arch_layers", annotations=WI)
async def setup_arch_layers(params: SetupLayersInput) -> dict:
    """Create the standard architectural layer set: Wall, Slab, Column, Beam, Opening, Roof, Stair, etc."""
    return await _exec_simple("setup_arch_layers", {"prefix": params.prefix})


@mcp.tool(name="batch_layer_visibility", annotations=WI)
async def batch_layer_visibility(params: BatchLayerVisInput) -> dict:
    """Show/hide/isolate layers in one call."""
    return await _exec_simple("batch_layer_visibility", params.model_dump(exclude_none=True))


# Ã¢"â‚¬Ã¢"â‚¬ Analysis Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬

@mcp.tool(name="measure_object", annotations=RO)
async def measure_object(params: ObjectIdInput) -> dict:
    """Measure area, volume, length, and bounding box for one object."""
    return await _exec_simple("measure_object", {"object_id": params.object_id})


@mcp.tool(name="measure_distance", annotations=RO)
async def measure_distance(params: MeasureDistInput) -> dict:
    """Distance between two points."""
    return await _exec_simple("measure_distance", params.model_dump())


@mcp.tool(name="check_intersection", annotations=RO)
async def check_intersection(params: CheckIntInput) -> dict:
    """Check whether two Rhino objects intersect (bounding-box check)."""
    return await _exec_simple("check_intersection", params.model_dump())


@mcp.tool(name="validate_objects", annotations=RO)
async def validate_objects(params: ValidateInput) -> dict:
    """Validate geometry. Empty object_ids means whole scene (capped to 100 Breps)."""
    return await _exec_simple("validate_objects", params.model_dump())


# Ã¢"â‚¬Ã¢"â‚¬ Viewport Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬

@mcp.tool(name="capture_viewport", annotations=RO)
async def capture_viewport(params: CaptureInput) -> dict:
    """Capture the active viewport as JPEG (default for shaded) or PNG (default for wireframe).

    Phase 1 — no disk round-trip. format='auto' picks based on display mode.
    restore_state=True (default) saves and restores the viewport camera + display mode after
    capture, so inspecting the model from any angle never disrupts the user's current view.
    Pass view= and/or display_mode= to temporarily switch before capturing."""
    return await _exec_simple("capture_viewport", params.model_dump())


@mcp.tool(name="set_view", annotations=WI)
async def set_view(params: ViewInput) -> dict:
    """Switch viewport to a named projection: Top, Front, Right, Left, Back, Perspective."""
    return await _exec_simple("set_view", params.model_dump())


@mcp.tool(name="set_display_mode", annotations=WI)
async def set_display_mode(params: DisplayInput) -> dict:
    """Set the active viewport display mode: Wireframe, Shaded, Rendered, Arctic, Ghosted, etc."""
    return await _exec_simple("set_display_mode", params.model_dump())


@mcp.tool(name="select_objects", annotations=WI)
async def select_objects(params: SelectInput) -> dict:
    """Select objects by GUID. clear_selection=True (default) deselects everything first."""
    return await _exec_simple("select_objects", params.model_dump())


@mcp.tool(name="set_camera", annotations=WI)
async def set_camera(params: SetCameraInput) -> dict:
    """Precisely position the viewport camera.

    Two modes:
    1. Explicit: supply location + target (+ optional lens_length, projection).
    2. Bbox framing: supply box_min + box_max — the plugin auto-computes a camera distance
       that fits the bounding box in the viewport.

    Examples:
        set_camera(location=[10000, -15000, 8000], target=[0, 0, 3000])
        set_camera(box_min=[0,0,0], box_max=[12000,8000,15000], projection="perspective")"""
    return await _exec_simple("set_camera", params.model_dump(exclude_none=True))


@mcp.tool(name="get_rhino_commands", annotations=RO)
async def get_rhino_commands(params: GetRhinoCommandsInput) -> dict:
    """List all registered Rhino command names (live, not hardcoded).

    Use this to discover whether a command like Contour, FilletEdge, or ProjectCurves exists
    before calling it via execute_script or batch. filter narrows by substring (case-insensitive)."""
    return await _exec_simple("get_rhino_commands", params.model_dump())


# Ã¢"â‚¬Ã¢"â‚¬ Geometry ops Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬

@mcp.tool(name="get_cross_section", annotations=WR)
async def get_cross_section(params: CrossSectionInput) -> dict:
    """Cut a solid at a Z height and return section curves — useful for plan views."""
    return await _exec_simple("get_cross_section", params.model_dump(exclude_none=True))


@mcp.tool(name="boolean_operation", annotations=WR)
async def boolean_operation(params: BooleanInput) -> dict:
    """Boolean union / difference / intersection between two objects."""
    return await _exec_simple("boolean_operation", params.model_dump())


@mcp.tool(name="delete_objects", annotations=WR)
async def delete_objects(params: DeleteInput) -> dict:
    """Delete objects by GUID or selector string: 'all', 'by_layer:Layer', 'by_name:Pattern', 'selected'."""
    return await _exec_simple("delete_objects", params.model_dump())

# Ã¢"â‚¬Ã¢"â‚¬ Escape hatches Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬

@mcp.tool(name="execute_script", annotations=WR)
async def execute_script(params: ScriptInput) -> dict:
    """Run arbitrary Python 3 inside Rhino. Powerful escape hatch — prefer structured tools.

    Auto-imported preamble: rhinoscriptsyntax as rs, scriptcontext as sc, Rhino, System.
    Use undo_name to wrap in an undo record."""
    return await _exec_simple("execute_script", params.model_dump(exclude_none=True))


@mcp.tool(name="undo", annotations=WI)
async def undo(params: UndoInput) -> dict:
    """Undo one or more Rhino operations."""
    return await _exec_simple("undo", params.model_dump())


@mcp.tool(name="get_log", annotations=RO)
async def get_log(params: LogInput) -> dict:
    """Fetch recent bridge log entries for debugging. errors_only=True filters to errors/warnings."""
    return await _exec_simple("get_log", params.model_dump())


# Ã¢"â‚¬Ã¢"â‚¬ Materials Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬

@mcp.tool(name="set_layer_material", annotations=WI)
async def set_layer_material(params: LayerMaterialInput) -> dict:
    """Set PBR material properties on a layer — color, roughness, metallic, opacity, emission.

    Updates both the layer display color and the render material (Rendered/Arctic/Raytraced).

    Examples:
        set_layer_material(layer="Wall", color=[220, 210, 195], roughness=0.8)
        set_layer_material(layer="Glass", color=[180, 220, 255], opacity=0.2, roughness=0.05)
        set_layer_material(layer="Core::Walls", color=[80, 80, 80], metallic=0.0, roughness=0.9)"""
    return await _exec_simple("set_layer_material", params.model_dump(exclude_none=True))


# Ã¢"â‚¬Ã¢"â‚¬ Native commands Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬

@mcp.tool(name="run_command", annotations=WR)
async def run_command(params: RunCommandInput) -> dict:
    """Execute any Rhino command string via RhinoApp.RunScript.

    Escape hatch for commands not covered by structured tools. Tracks newly created objects.
    Prefer structured tools when available — run_command has no rollback guarantee.

    Examples:
        run_command(command="_Contour _SelAll _Enter 0,0,0 0,0,1 3000")
        run_command(command="_FilletEdge _SelId <guid> _Enter 50")
        run_command(command="_Make2D _SelAll _Enter")"""
    return await _exec_simple("run_command", params.model_dump())


# Ã¢"â‚¬Ã¢"â‚¬ Entry point Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬Ã¢"â‚¬



# =============================================================================
# SECTIONS & PLANS
# =============================================================================

@mcp.tool()
async def create_section(label: str = "", start_x: float = None, start_y: float = None, start_z: float = None, end_x: float = None, end_y: float = None, end_z: float = None, view_side: str = "left") -> str:
    """Create an architectural section line with arrowheads on a dedicated layer. The model will place a default section line at the model center — reposition it and call cut_section when satisfied."""
    params = {"view_side": view_side}
    if label: params["label"] = label
    if start_x is not None: params["start_point"] = {"x": start_x, "y": start_y or 0, "z": start_z or 0}
    if end_x is not None: params["end_point"] = {"x": end_x, "y": end_y or 0, "z": end_z or 0}
    return json.dumps(await _exec_simple("create_section", params))


@mcp.tool()
async def create_elevation(label: str = "", direction: str = "north", offset: float = None) -> str:
    """Create an elevation marker for the specified direction (north/south/east/west)."""
    params = {"direction": direction}
    if label: params["label"] = label
    if offset is not None: params["offset"] = offset
    return json.dumps(await _exec_simple("create_elevation", params))


@mcp.tool()
async def cut_section(label: str, capture: bool = True) -> str:
    """Cut the named section — creates clipping plane, aligns view, captures result. Call after user has confirmed section line position."""
    return json.dumps(await _exec_simple("cut_section", {"label": label, "capture": capture}))


@mcp.tool()
async def align_view_to_section(label: str) -> str:
    """Align the viewport camera perpendicular to the named section/elevation cut plane."""
    return json.dumps(await _exec_simple("align_view_to_section", {"label": label}))


@mcp.tool()
async def create_plan(floor: str, cut_height_mm: float = 1200.0, capture: bool = True) -> str:
    """Generate a floor plan for the specified floor (e.g. '1', '8', 'ground', 'G', 'B1'). Automatically places a horizontal clipping plane at cut_height_mm above the floor level and captures a top-down orthographic view."""
    return json.dumps(await _exec_simple("create_plan", {"floor": floor, "cut_height_mm": cut_height_mm, "capture": capture}))


@mcp.tool()
async def create_all_plans(cut_height_mm: float = 1200.0, capture: bool = True) -> str:
    """Generate floor plans for ALL detected floor levels simultaneously."""
    return json.dumps(await _exec_simple("create_all_plans", {"cut_height_mm": cut_height_mm, "capture": capture}))


@mcp.tool()
async def list_sections() -> str:
    """List all sections, elevations, and plans currently defined in the model."""
    return json.dumps(await _exec_simple("list_sections", {}))


@mcp.tool()
async def update_section(label: str, start_x: float = None, start_y: float = None, start_z: float = None, end_x: float = None, end_y: float = None, end_z: float = None) -> str:
    """Reposition an existing section line and re-cut."""
    params = {"label": label}
    if start_x is not None: params["start_point"] = {"x": start_x, "y": start_y or 0, "z": start_z or 0}
    if end_x is not None: params["end_point"] = {"x": end_x, "y": end_y or 0, "z": end_z or 0}
    return json.dumps(await _exec_simple("update_section", params))


@mcp.tool()
async def remove_section(label: str) -> str:
    """Remove a section, elevation, or plan layer and its clipping plane."""
    return json.dumps(await _exec_simple("remove_section", {"label": label}))


# =============================================================================
# ILLUSTRATION & DISPLAY MODES
# =============================================================================

@mcp.tool()
async def create_display_mode(name: str, preset: str = "", base_mode: str = "", background_color: str = "", edge_color: str = "", edge_thickness: int = -1, silhouette_thickness: int = -1, show_edges: bool = None, show_silhouettes: bool = None, shading_enabled: bool = None) -> str:
    """Create a custom Rhino display mode for illustration. Presets: diagram, technical, blueprint, sketch, axonometric, atmospheric, monochrome, cutaway."""
    params = {"name": name}
    if preset: params["preset"] = preset
    if base_mode: params["base_mode"] = base_mode
    if background_color: params["background_color"] = background_color
    if edge_color: params["edge_color"] = edge_color
    if edge_thickness >= 0: params["edge_thickness"] = edge_thickness
    if silhouette_thickness >= 0: params["silhouette_thickness"] = silhouette_thickness
    if show_edges is not None: params["show_edges"] = show_edges
    if show_silhouettes is not None: params["show_silhouettes"] = show_silhouettes
    if shading_enabled is not None: params["shading_enabled"] = shading_enabled
    return json.dumps(await _exec_simple("create_display_mode", params))


@mcp.tool()
async def apply_display_mode(name: str) -> str:
    """Apply a display mode (built-in or custom AI- mode) to the active viewport."""
    return json.dumps(await _exec_simple("apply_display_mode", {"name": name}))


@mcp.tool()
async def list_display_modes() -> str:
    """List all available display modes including custom AI-created ones."""
    return json.dumps(await _exec_simple("list_display_modes", {}))


@mcp.tool()
async def adjust_display_mode(name: str, background_color: str = "", edge_color: str = "", edge_thickness: int = -1, silhouette_thickness: int = -1) -> str:
    """Adjust parameters of an existing custom AI display mode."""
    params = {"name": name}
    if background_color: params["background_color"] = background_color
    if edge_color: params["edge_color"] = edge_color
    if edge_thickness >= 0: params["edge_thickness"] = edge_thickness
    if silhouette_thickness >= 0: params["silhouette_thickness"] = silhouette_thickness
    return json.dumps(await _exec_simple("adjust_display_mode", params))


@mcp.tool()
async def delete_display_mode(name: str) -> str:
    """Delete a custom AI display mode (only AI- prefixed modes can be deleted)."""
    return json.dumps(await _exec_simple("delete_display_mode", {"name": name}))


@mcp.tool()
async def capture_illustration(display_mode: str = "", width: int = 1600, height: int = 1200, style_notes: str = "", restore_mode: bool = True) -> str:
    """Capture the viewport as an illustration using the specified or current display mode."""
    params = {"width": width, "height": height, "restore_mode": restore_mode}
    if display_mode: params["display_mode"] = display_mode
    if style_notes: params["style_notes"] = style_notes
    return json.dumps(await _exec_simple("capture_illustration", params))


# =============================================================================
# MATERIAL INTELLIGENCE
# =============================================================================

@mcp.tool()
async def search_materials(keyword: str, limit: int = 5) -> str:
    """Search AmbientCG for PBR materials matching keyword. Returns candidates with names, preview info, and real-world dimensions. Call download_material with a specific asset_id to proceed."""
    import json
    try:
        from rhino_architect.material_downloader import search_materials as _search
        results = _search(keyword, limit)
        return json.dumps({"status": "ok", "results": results, "count": len(results)})
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


@mcp.tool()
async def download_material(asset_id: str, layer_name: str, resolution: str = "2K", confirmed: bool = False) -> str:
    """
    Download and apply a PBR material from AmbientCG to a Rhino layer.
    IMPORTANT: First call with confirmed=False to get a preview of what will be downloaded.
    Only call with confirmed=True after the user has explicitly approved.
    asset_id: from search_materials results.
    layer_name: Rhino layer to assign the material to.
    resolution: '1K', '2K', or '4K'.
    """
    import json
    try:
        from rhino_architect.material_downloader import get_material_info, download_material as _download, compute_uv_repeat
        info = get_material_info(asset_id)
        if not info:
            return json.dumps({"status": "error", "message": f"Asset {asset_id} not found"})

        # Preview mode — return info without downloading
        if not confirmed:
            dims = info.get("dimensionsInMeters", [1.0, 1.0])
            size_m = dims[0] if dims else 1.0
            return json.dumps({
                "status": "preview",
                "asset_id": asset_id,
                "display_name": info.get("displayName", asset_id),
                "physical_size_m": size_m,
                "resolution": resolution,
                "license": "CC0 (free, no attribution required)",
                "message": f"Ready to download '{info.get('displayName', asset_id)}' ({resolution}, CC0). Call again with confirmed=True to proceed.",
                "confirmed_required": True
            })

        # Download
        result = _download(asset_id, resolution)

        # Get model unit system from Rhino
        ping_result = await _exec_simple("ping", {})
        unit_system = ping_result.get("unit_system", "Meters")

        physical_size_m = result.get("physical_size_m", 1.0)
        uv_repeat = compute_uv_repeat(physical_size_m, unit_system)

        # Apply via C# handler
        apply_params = {
            "layer_name": layer_name,
            "material_name": result["display_name"],
            "maps": result["local_paths"],
            "physical_size_m": physical_size_m,
            "uv_repeat": uv_repeat
        }
        return json.dumps(await _exec_simple("apply_downloaded_material", apply_params))
    except Exception as e:
        return json.dumps({"status": "error", "message": str(e)})


@mcp.tool()
async def edit_material(layer_name: str = "", material_name: str = "", roughness: float = -1, metallic: float = -1, diffuse_color: str = "", transparency: float = -1, texture_scale: float = -1, texture_rotation: float = -361) -> str:
    """Edit properties of an existing Rhino render material on a layer."""
    params = {}
    if layer_name: params["layer_name"] = layer_name
    if material_name: params["material_name"] = material_name
    if roughness >= 0: params["roughness"] = roughness
    if metallic >= 0: params["metallic"] = metallic
    if diffuse_color: params["diffuse_color"] = diffuse_color
    if transparency >= 0: params["transparency"] = transparency
    if texture_scale > 0: params["texture_scale"] = texture_scale
    if texture_rotation > -361: params["texture_rotation"] = texture_rotation
    return json.dumps(await _exec_simple("edit_material", params))


@mcp.tool()
async def list_materials() -> str:
    """List all render materials in the current Rhino document."""
    return json.dumps(await _exec_simple("list_materials", {}))


@mcp.tool()
async def get_material(layer_name: str = "", material_index: int = -1) -> str:
    """Get full properties of a render material by layer name or material index."""
    params = {}
    if layer_name: params["layer_name"] = layer_name
    if material_index >= 0: params["material_index"] = material_index
    return json.dumps(await _exec_simple("get_material", params))


# =============================================================================
# FILE TRACING
# =============================================================================

@mcp.tool()
async def import_dwg(file_path: str) -> str:
    """Import a DWG or DXF file into Rhino using the native importer (100% accurate, no AI interpretation). Post-processes imported geometry."""
    return json.dumps(await _exec_simple("import_dwg", {"file_path": file_path}))


@mcp.tool()
async def calibrate_scale(point1_x: float, point1_y: float, point1_z: float, point2_x: float, point2_y: float, point2_z: float, known_distance: float, unit: str = "mm") -> str:
    """Calibrate model scale by specifying two points and their known real-world distance. Rescales all geometry to match. Use after importing or tracing files that may be at wrong scale."""
    return json.dumps(await _exec_simple("calibrate_scale", {
        "point1": {"x": point1_x, "y": point1_y, "z": point1_z},
        "point2": {"x": point2_x, "y": point2_y, "z": point2_z},
        "known_distance": known_distance,
        "unit": unit
    }))


# =============================================================================
# PDF / FILE TRACING TOOLS  (v4.7)
# =============================================================================

@mcp.tool()
async def get_pdf_info(pdf_path: str) -> str:
    """Inspect a PDF file: page count, page sizes in mm, vector/text content flag.

    Call this before trace_pdf to choose the right page number and confirm
    the file is a vector drawing (not a scanned raster).

    Args:
        pdf_path: Absolute path to the PDF file.
    """
    try:
        from rhino_architect.pdf_tracer import get_pdf_info as _info
        return json.dumps(_info(pdf_path))
    except ImportError as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def preview_pdf_page(pdf_path: str, page_number: int = 0) -> str:
    """Render a PDF page as a base64 PNG thumbnail for previewing before tracing.

    Args:
        pdf_path: Absolute path to the PDF file.
        page_number: 0-indexed page number (default 0).
    """
    try:
        from rhino_architect.pdf_tracer import render_page_preview
        b64 = render_page_preview(pdf_path, page_number)
        if b64:
            return json.dumps({"status": "ok", "page": page_number, "image_base64": b64,
                    "note": "Render the image to confirm the page looks correct before tracing."})
        return json.dumps({"error": "Could not render page"})
    except ImportError as e:
        return json.dumps({"error": str(e)})


@mcp.tool()
async def trace_pdf(
    pdf_path: str,
    page_number: int = 0,
    dpi: int = 300,
    model_unit: str = "mm",
    confidence_threshold: float = 0.65,
    layer_prefix: str = "Traced",
    z_elevation: float = 0.0,
    merge_tolerance_px: float = 5.0,
    min_line_length_px: float = 10.0,
) -> str:
    """Trace a PDF drawing page and import the geometry into Rhino as curves, arcs, polylines and text.

    Two-step process handled automatically:
      1. Python CV pipeline (PyMuPDF + OpenCV) extracts geometry from the PDF.
      2. C# TracingManager creates Rhino objects on organised layers.

    Low-confidence detections go to a '{layer_prefix}::REVIEW' layer (shown in red)
    so you can inspect and accept/reject them manually.

    Requirements: pip install pymupdf opencv-python numpy

    Args:
        pdf_path: Absolute path to the PDF file.
        page_number: 0-indexed page number (default 0).
        dpi: Render resolution. 300 is good for most drawings; use 600 for fine detail.
        model_unit: Target model unit ("mm", "cm", "m", "ft", "in"). Must match the Rhino document.
        confidence_threshold: Elements below this confidence go to the REVIEW layer (0.0–1.0).
        layer_prefix: Prefix for created layers (default "Traced").
        z_elevation: Z height at which all geometry is placed.
        merge_tolerance_px: Distance in pixels within which collinear segments are merged.
        min_line_length_px: Ignore detected lines shorter than this (pixels).
    """
    try:
        from rhino_architect.pdf_tracer import trace_pdf as _trace
    except ImportError as e:
        return json.dumps({"error": f"pdf_tracer import failed: {e}. Run: pip install pymupdf opencv-python numpy"})

    # Step 1: Extract geometry in Python
    trace_result = _trace(
        pdf_path=pdf_path,
        page_number=page_number,
        dpi=dpi,
        model_unit=model_unit,
        confidence_threshold=confidence_threshold,
        merge_tolerance_px=merge_tolerance_px,
        min_line_length_px=min_line_length_px,
    )

    if "error" in trace_result and not trace_result.get("elements"):
        return json.dumps(trace_result)

    meta = trace_result.get("metadata", {})
    elements = trace_result.get("elements", [])

    if not elements:
        return json.dumps({"status": "ok", "message": "No geometry detected in this page.",
                           "metadata": meta})

    # Step 2: Send to Rhino C# to create objects
    payload = {
        "elements": elements,
        "layer_prefix": layer_prefix,
        "confidence_threshold": confidence_threshold,
        "z_elevation": z_elevation,
        "source_file": meta.get("source_file", os.path.basename(pdf_path)),
        "page_number": page_number,
    }
    rhino_result = await _exec_simple("apply_traced_elements", payload)

    return json.dumps({
        "status": "ok",
        "trace_metadata": meta,
        "rhino_result": rhino_result,
        "note": f"Elements on REVIEW layer need manual inspection. Open layer panel to check '{layer_prefix}::REVIEW'.",
    }, default=str)


@mcp.tool()
async def clear_trace_layers(layer_prefix: str = "Traced") -> str:
    """Delete all objects and layers created by a previous trace_pdf call.

    Args:
        layer_prefix: The prefix used when the layers were created (default "Traced").
    """
    return json.dumps(await _exec_simple("clear_trace_layers", {"layer_prefix": layer_prefix}))


@mcp.tool()
async def get_trace_layers(layer_prefix: str = "Traced") -> str:
    """List all trace layers and their object counts.

    Args:
        layer_prefix: Layer prefix to search for (default "Traced").
    """
    return json.dumps(await _exec_simple("get_trace_layers", {"layer_prefix": layer_prefix}))


# =============================================================================
# DESIGN MEMORY TOOLS
# =============================================================================

@mcp.tool()
async def set_design_brief(brief: str) -> str:
    """Store the project design brief inside the Rhino file (.3dm UserData).

    Call this at the start of any significant design session. The brief persists
    in the .3dm file and survives save/reload. Include: building type, program,
    key constraints, structural approach, client requirements.
    """
    return json.dumps(await _exec_simple("set_design_brief", {"brief": brief}))


@mcp.tool()
async def get_design_brief() -> str:
    """Retrieve the project design brief and global design rules stored in the Rhino file."""
    return json.dumps(await _exec_simple("get_design_brief", {}))


@mcp.tool()
async def tag_object(ids: list[str], tags: dict) -> str:
    """Write metadata tags to one or more Rhino objects (stored in UserDictionary, persists in .3dm).

    Useful tag keys:
      ai_group    -- logical group name (e.g. 'tower_core_level_3')
      ai_rule     -- regeneration rule (e.g. 'concrete 300mm, 8.4m bay')
      ai_label    -- human-readable label
      ai_relations -- JSON string: {"children": ["id1", "id2"], "parent": "id0"}
    """
    return json.dumps(await _exec_simple("tag_object", {"ids": ids, "tags": tags}))


@mcp.tool()
async def get_provenance(id: str) -> str:
    """Get the full creation context (provenance) for a Rhino object.

    Returns: which tool created it, with what parameters, in which session.
    Answers: 'why does this object exist?' and 'how was it created?'
    All AI-created objects are auto-tagged at creation time.
    """
    return json.dumps(await _exec_simple("get_provenance", {"id": id}))


@mcp.tool()
async def search_memory(query: str) -> str:
    """Search the design memory for objects, rules, groups, and sessions matching a keyword.

    Searches across: design brief, session logs, named groups, and all object tags.
    Returns matching results with source and context (max 50 hits).
    Example queries: 'tower core', 'concrete 300mm', 'facade A', 'level 3 columns'.
    """
    return json.dumps(await _exec_simple("search_memory", {"query": query}))


@mcp.tool()
async def get_related_objects(id: str, relation: str = "") -> str:
    """Get objects related to a given object via stored ai_relations tags.

    relation: 'parent', 'children', 'mirrors', 'group', or '' for all relations.
    Example: get all windows that belong to a specific facade wall.
    """
    return json.dumps(await _exec_simple("get_related_objects", {"id": id, "relation": relation}))


@mcp.tool()
async def name_group(name: str, ids: list[str]) -> str:
    """Create or update a named group of objects stored in the Rhino file.

    Named groups persist in the .3dm file. Use to label sets of objects:
    'tower_core', 'north_facade', 'level_3_columns'. Retrieve with get_group.
    """
    return json.dumps(await _exec_simple("name_group", {"name": name, "ids": ids}))


@mcp.tool()
async def get_group(name: str) -> str:
    """Get the object IDs belonging to a named group stored in the Rhino file."""
    return json.dumps(await _exec_simple("get_group", {"name": name}))


@mcp.tool()
async def get_all_groups() -> str:
    """List all named groups and their member object IDs stored in the Rhino file."""
    return json.dumps(await _exec_simple("get_all_groups", {}))


@mcp.tool()
async def add_design_rule(rule: str) -> str:
    """Add a global design rule to the project memory (persists in .3dm file).

    Rules guide future generation decisions. Examples:
      'bay spacing must be 8400mm'
      'concrete walls 300mm thick'
      'floor-to-floor height 3500mm'
      'no windows below 900mm sill height'
    """
    return json.dumps(await _exec_simple("add_design_rule", {"rule": rule}))


@mcp.tool()
async def log_session(summary: str) -> str:
    """Log a summary of the current AI session to the project memory (persists in .3dm).

    Call at the end of a work session with a brief description of what was done.
    Logs persist in the .3dm file and provide context for future sessions.
    """
    return json.dumps(await _exec_simple("log_session", {"summary": summary}))


# =============================================================================
# INCREMENTAL SCENE SYNC TOOLS
# =============================================================================

@mcp.tool()
async def get_scene_diff(from_version: int) -> str:
    """Get what changed in the Rhino scene since a specific version number.

    Returns arrays of added, deleted, and modified object refs.
    Use at the start of every session to catch up cheaply instead of
    re-querying the full scene. Get current version from ping or get_tracker_version.

    WHEN TO USE: much faster than get_scene_summary on large models --
    only returns what changed, not everything.
    """
    return json.dumps(await _exec_simple("get_scene_diff", {"from_version": from_version}))


@mcp.tool()
async def get_change_log(limit: int = 50, since_version: int = 0) -> str:
    """Get the chronological log of recent scene change events.

    Returns change events (added/deleted/modified) with timestamps and version numbers.
    Useful for understanding the sequence of recent edits or auditing a session.
    Max limit: 200 events.
    """
    return json.dumps(await _exec_simple("get_change_log", {
        "limit": limit, "since_version": since_version
    }))


@mcp.tool()
async def get_tracker_version() -> str:
    """Get the current change tracker version number.

    Workflow: store this version, do work or wait for user edits,
    then call get_scene_diff(from_version=stored_version) to see what changed.
    """
    return json.dumps(await _exec_simple("get_tracker_version", {}))


# =============================================================================
# SEMANTIC SCENE INTELLIGENCE TOOLS
# =============================================================================

@mcp.tool()
async def analyze_architecture() -> str:
    """Run a full semantic analysis of the Rhino scene.

    Classifies all geometry into architectural types: walls, slabs, columns,
    cores, facade panels, openings, stairs, massing. Detects floor levels by
    clustering Z-positions of flat geometry. Detects structural grid from
    column centroid positions.

    Returns: level count, system breakdown (counts + IDs), detected grid spacing,
    unclassified geometry ratio.

    Result is CACHED against scene_version -- calling twice costs almost nothing
    if the scene has not changed. Force refresh by modifying the scene.
    """
    return json.dumps(await _exec_simple("analyze_architecture", {}))


@mcp.tool()
async def get_building_systems(system: str = "all") -> str:
    """Get objects grouped by architectural building system.

    system options:
      'structure'   -- columns, slabs, cores
      'envelope'    -- walls, facade panels
      'openings'    -- windows, doors
      'circulation' -- stairs, ramps
      'all'         -- everything (default)

    Each object includes: id, level index, layer, bounding box size [dx, dy, dz] in mm.
    Call analyze_architecture first for an overview, then drill into systems.
    """
    return json.dumps(await _exec_simple("get_building_systems", {"system": system}))


@mcp.tool()
async def get_level_summary(level: int = -1) -> str:
    """Get a summary of one or all detected floor levels in the model.

    level: floor index (0 = ground floor), or -1 for all levels (default).
    Returns per level: elevation (mm), object count, count by architectural type.
    Levels are auto-detected by clustering the Z-positions of flat geometry.
    """
    params = {"level": level} if level >= 0 else {}
    return json.dumps(await _exec_simple("get_level_summary", params))


@mcp.tool()
async def detect_design_patterns() -> str:
    """Detect repeating design patterns in the Rhino model.

    Finds:
      - Structural grid: dominant X/Y spacing from column centroid positions
      - Repeated modules: bounding-box sizes that appear 3+ times
      - Level count and detected floor heights

    Use before adding new elements to understand the existing design logic
    (bay spacing, grid, typical element sizes) so you can match them.
    """
    return json.dumps(await _exec_simple("detect_design_patterns", {}))


@mcp.tool()
async def find_unassigned_geometry(min_volume: float = 0.0) -> str:
    """Find geometry that couldn't be classified into any architectural system.

    min_volume: minimum bounding box volume in mm^3 to filter tiny objects (default: 0 = all).
    Returns objects with layer and bounding box size [dx, dy, dz].

    Use to review orphaned geometry, decide what to do with it (tag it,
    assign to a layer, delete it, or reclassify it).
    """
    return json.dumps(await _exec_simple("find_unassigned_geometry", {"min_volume": min_volume}))


# =============================================================================
# SMART BATCHING -- PREVIEW
# =============================================================================

@mcp.tool()
async def batch_preview(commands: list[dict]) -> str:
    """Validate a batch plan without executing any commands (dry run, zero mutations).

    Checks each step:
      - Is it a known command?
      - Are  paths (, .object_ids, .object_ids[0]) forward-reference-free?
      - Are there destructive commands that need extra care?
      - Which steps involve viewport captures (consider capture_at_end)?

    Returns per-step status (valid/invalid/warning), estimated creates/deletes,
    and all warnings. Completely safe to call at any time -- does NOT modify Rhino.

    WHEN TO USE: before any complex or destructive batch, especially those with
    many  chains or boolean operations.
    """
    return json.dumps(await _exec_simple("batch_preview", {"commands": commands}))
