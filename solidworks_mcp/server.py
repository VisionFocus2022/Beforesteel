"""Standard MCP server for SolidWorks 2026 COM automation.

Assembly facade (N14): this module owns the FastMCP instance, the three
read-only resources, and stdio entry point. Every tool lives in its
per-domain module under :mod:`solidworks_mcp.registry` and is wired in
by :func:`~solidworks_mcp.registry.register_all`; the imports below
re-export the tool functions so long-standing callers (tests, tooling)
keep the ``server.<tool>`` spelling. Product tools (ring_light) register
only when ``SOLIDWORKS_MCP_PRODUCT_TOOLS`` lists them.
"""

from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from solidworks_mcp import __version__
from solidworks_mcp.config import get_config
from solidworks_mcp.registry import register_all
from solidworks_mcp.registry.base import (
    active_document_data,
    call_connected,
    com_timeout,
    get_sw,
    run_com,
    set_capabilities_provider,
)
from solidworks_mcp.utils.security import default_allowed_root

# -- Domain re-exports (registry.<domain> defines and registers them) --------
#
# DEPRECATED (A-5, 2026-10-05): this compatibility block is frozen —
# do NOT add new tools here and do NOT reference ``server.<tool>`` in
# new code. Import from the owning domain module instead:
#   from solidworks_mcp.registry.part import solidworks_part_create_box
# Tests migrated 2026-10-05 (test_infrastructure / test_config_timeout /
# test_pattern); remaining ``server.*`` uses are intentional facade tests.
# Removal target: v0.5.0 (track in AGENTS.md tooling notes).
from solidworks_mcp.registry.misc import (  # noqa: F401
    solidworks_connect,
    solidworks_design_capabilities,
    solidworks_get_active_document,
    solidworks_get_bounding_box,
    solidworks_measure_distance,
)
from solidworks_mcp.registry.part import (  # noqa: F401
    solidworks_design_execute_plan,
    solidworks_part_apply_chamfer,
    solidworks_part_apply_dome,
    solidworks_part_apply_fillet,
    solidworks_part_apply_shell,
    solidworks_part_create_annular_pattern,
    solidworks_part_circular_pattern,
    solidworks_part_create_box,
    solidworks_part_create_cone,
    solidworks_part_create_cylinder,
    solidworks_part_create_linear_holes,
    solidworks_part_create_loft,
    solidworks_part_create_plate,
    solidworks_part_create_polygon,
    solidworks_part_create_ref_axis,
    solidworks_part_create_ref_plane,
    solidworks_part_create_revolved,
    solidworks_part_create_rib,
    solidworks_part_create_slot,
    solidworks_part_create_swept,
    solidworks_part_cut_real_thread,
    solidworks_part_cut_round_hole,
    solidworks_part_cut_threaded_hole,
    solidworks_part_get_mass_properties,
    solidworks_part_list_bodies,
    solidworks_part_list_faces,
    solidworks_part_new,
    solidworks_pattern_annular_layout,
    solidworks_sheet_metal_base_flange,
)
from solidworks_mcp.registry.features import (  # noqa: F401
    solidworks_dimension_set,
    solidworks_dimension_set_angle,
    solidworks_feature_delete,
    solidworks_feature_rename,
    solidworks_feature_set_suppression,
    solidworks_features_apply_draft,
    solidworks_features_get_details,
    solidworks_features_list,
    solidworks_features_mirror,
    solidworks_features_rebuild_csg,
)
from solidworks_mcp.registry.properties import (  # noqa: F401
    solidworks_part_activate_configuration,
    solidworks_part_add_configuration,
    solidworks_part_add_equation,
    solidworks_part_delete_equation,
    solidworks_part_edit_equation,
    solidworks_part_get_custom_properties,
    solidworks_part_get_material,
    solidworks_part_list_equations,
    solidworks_part_set_custom_property,
    solidworks_part_set_material,
)
from solidworks_mcp.registry.file_io import (  # noqa: F401
    solidworks_file_close,
    solidworks_file_export_dxf,
    solidworks_file_export_step,
    solidworks_file_export_stl,
    solidworks_file_import_step,
    solidworks_file_open,
)
from solidworks_mcp.registry.drawing import (  # noqa: F401
    solidworks_drawing_create_from_part,
    solidworks_drawing_export_pdf,
    solidworks_drawing_export_png,
    solidworks_drawing_insert_bom_table,
    solidworks_drawing_insert_dimensions,
    solidworks_drawing_insert_gtol,
    solidworks_drawing_insert_note,
    solidworks_drawing_insert_section_view,
    solidworks_drawing_insert_surface_finish,
    solidworks_drawing_organize_dimensions,
    solidworks_drawing_set_tolerance,
)
from solidworks_mcp.registry.assembly import (  # noqa: F401
    solidworks_assembly_add_component,
    solidworks_assembly_add_mate,
    solidworks_assembly_check_interference,
    solidworks_assembly_delete_mate,
    solidworks_assembly_explode,
    solidworks_assembly_get_bom,
    solidworks_assembly_list_components,
    solidworks_assembly_move_component,
    solidworks_assembly_new,
    solidworks_assembly_rotate_component,
)
from solidworks_mcp.registry.products import (  # noqa: F401
    solidworks_part_create_ring_light,
    solidworks_part_create_ring_light_v3,
)
from solidworks_mcp.registry.prompts import (  # noqa: F401
    solidworks_assembly_prompt,
    solidworks_csg_rebuild_prompt,
    solidworks_design_part_prompt,
    solidworks_drawing_prompt,
    solidworks_parametric_prompt,
)


def _configure_logging() -> None:
    config = get_config()
    try:
        log_path = Path(config.log_path)
        handler: logging.Handler = RotatingFileHandler(
            log_path,
            maxBytes=2_000_000,
            backupCount=3,
            encoding="utf-8",
        )
    except OSError:
        handler = logging.StreamHandler()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[handler],
        force=True,  # M-5: hosts that pre-configure root must not silently win
    )


mcp = FastMCP(
    "solidworks-mcp",
    instructions=(
        "Design and inspect SolidWorks documents. All lengths are millimeters. "
        "Call solidworks_design_capabilities before planning geometry, keep file "
        "paths under allowed_root, and require explicit confirmation to overwrite."
    ),
)

def _apply_version(instance, version: str) -> None:
    """Pin the handshake version (A-7, 2026-10-05).

    Isolated to a single function because FastMCP 1.x has no public
    version setter — this private-attribute touch is the only place to
    revisit when the 1.28 pin is lifted.
    """
    instance._mcp_server.version = version


_apply_version(mcp, __version__)


def _build_capabilities() -> dict:
    """Capabilities payload (A-3, 2026-10-05: moved from registry.base —
    the content is facade-owned because it needs ``mcp`` and is 80%
    server responsibility; base now consumes it via an injected provider)."""
    config = get_config()
    return {
        "name": "solidworks-mcp",
        "version": __version__,
        "solidworks_version": config.solidworks_version,
        "transport": "stdio",
        "units": {
            "tool_length": "millimeter",
            "solidworks_internal_length": "meter",
            "angle": "radian unless a tool says otherwise",
        },
        "allowed_root": default_allowed_root(),
        "auto_start": config.auto_start,
        "tools": [tool.name for tool in mcp._tool_manager.list_tools()],
        "design_plan_operations": [
            {"type": "new_part"},
            {"type": "box", "width": 100, "depth": 60, "height": 10},
            {"type": "plate", "width": 100, "depth": 60, "thickness": 6},
            {"type": "cylinder", "diameter": 20, "height": 40},
            {"type": "cone", "bottom_diameter": 30, "top_diameter": 10, "height": 40},
            {
                "type": "hole",
                "diameter": 6,
                "x": 15,
                "y": 10,
                "plane": "top",
                "through_all": True,
            },
            {
                "type": "threaded_hole",
                "spec": "M6",
                "x": 15,
                "y": 10,
                "plane": "top",
                "through_all": True,
            },
            {
                "type": "annular_pattern",
                "rings": [{"radius_mm": 30, "count": 6, "diameter_mm": 6}],
                "plane": "top",
                "feature_kind": "cut",
                "through_all": True,
            },
        ],
        "safety": [
            "All file paths must stay under allowed_root.",
            "Outputs require an existing parent directory and the correct extension.",
            "Overwriting an existing file requires overwrite_confirm=true.",
            "SolidWorks auto-start follows configuration unless a tool overrides it.",
            "SolidWorks COM calls are serialized on one STA thread.",
        ],
        "limitations": [
            "Design plans currently support primitive bosses (box/plate/cylinder/cone), round cut holes, ISO threaded holes, and annular patterns.",
            "solidworks_part_create_ring_light generates a validated spherical-dome LED layout (row_counts is free-form, defaulting to the confirmed 9-row product layout); the native SLDPRT uses 24 annular bands when FeatureRevolve2 is unavailable.",
            "Assembly mates use the compatibility AddMate5 API for basic mate types.",
            "Complex surfaces, GD&T feature-control frames, simulation, and PDM are not yet exposed.",
            "Drawing BOM balloons (AutoBalloon family) are blocked by the SolidWorks API on this machine; use drawing_insert_bom_table instead.",
            "Exploded-state drawing projection is an open observation item; project from the saved model configuration.",
            "solidworks_part_circular_pattern drives the PropertyManager pane via UI automation: it needs a visible, maximized SolidWorks window with the standard toolbar layout on a 1920x1040 desktop (N58; pixel-calibrated offsets).",
        ],
    }


# Wire in every domain's tools and prompts (products honour their env gate).
# A-3: install the capabilities builder BEFORE registration so any tool
# defined today can answer capabilities queries without upward imports.
set_capabilities_provider(_build_capabilities)
register_all(mcp)

# Compatibility alias: long-standing callers (tests, tooling) use the
# ``server._capabilities`` spelling from before the A-3 move.
_capabilities = _build_capabilities


@mcp.resource(
    "solidworks://capabilities",
    title="SolidWorks MCP capabilities",
    mime_type="application/json",
)
def solidworks_capabilities_resource() -> str:
    """Read supported operations, units, safety rules, and limitations."""
    return json.dumps(_build_capabilities(), ensure_ascii=False, indent=2)


@mcp.resource(
    "solidworks://status",
    title="SolidWorks connection status",
    mime_type="application/json",
)
def solidworks_status_resource() -> str:
    """Probe the cached SolidWorks connection without launching the application."""
    from solidworks_mcp.utils.com_executor import _executor

    try:
        status = run_com(get_sw().status, timeout=com_timeout())
    except Exception:
        status = {"connected": False, "version": None}
    status["allowed_root"] = default_allowed_root()
    # C-2（2026-10-05）：毒化状态外显——宿主/客户端可据 'poisoned' 字段
    # 决定重启会话，而不是对每个工具调用失败逐个排障。
    status["poisoned"] = _executor.is_poisoned()
    return json.dumps(status, ensure_ascii=False, indent=2)


@mcp.resource(
    "solidworks://active-document",
    title="Active SolidWorks document",
    mime_type="application/json",
)
def solidworks_active_document_resource() -> str:
    """Read the active document, attaching only to an already running SolidWorks."""
    result = call_connected(active_document_data, launch_if_needed=False)
    return json.dumps(result, ensure_ascii=False, indent=2)


def main() -> None:
    """Run the local MCP server over stdio."""
    _configure_logging()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
