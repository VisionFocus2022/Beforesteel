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
    _active_document_data,
    _call_connected,
    _capabilities,
    _com_timeout,
    _sw,
    run_com,
)
from solidworks_mcp.utils.security import DEFAULT_ALLOWED_ROOT

# -- Domain re-exports (registry.<domain> defines and registers them) --------
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
    )


mcp = FastMCP(
    "solidworks-mcp",
    instructions=(
        "Design and inspect SolidWorks documents. All lengths are millimeters. "
        "Call solidworks_design_capabilities before planning geometry, keep file "
        "paths under allowed_root, and require explicit confirmation to overwrite."
    ),
)

# FastMCP 1.x does not expose version in its constructor.
mcp._mcp_server.version = __version__

# Wire in every domain's tools and prompts (products honour their env gate).
register_all(mcp)


@mcp.resource(
    "solidworks://capabilities",
    title="SolidWorks MCP capabilities",
    mime_type="application/json",
)
def solidworks_capabilities_resource() -> str:
    """Read supported operations, units, safety rules, and limitations."""
    return json.dumps(_capabilities(), ensure_ascii=False, indent=2)


@mcp.resource(
    "solidworks://status",
    title="SolidWorks connection status",
    mime_type="application/json",
)
def solidworks_status_resource() -> str:
    """Probe the cached SolidWorks connection without launching the application."""
    status = run_com(_sw().status, timeout=_com_timeout())
    status["allowed_root"] = DEFAULT_ALLOWED_ROOT
    return json.dumps(status, ensure_ascii=False, indent=2)


@mcp.resource(
    "solidworks://active-document",
    title="Active SolidWorks document",
    mime_type="application/json",
)
def solidworks_active_document_resource() -> str:
    """Read the active document, attaching only to an already running SolidWorks."""
    result = _call_connected(_active_document_data, launch_if_needed=False)
    return json.dumps(result, ensure_ascii=False, indent=2)


def main() -> None:
    """Run the local MCP server over stdio."""
    _configure_logging()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
