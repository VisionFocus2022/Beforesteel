"""Product-specific tools behind an env gate (registry/products, N14).

The ring-light generators are niche product-validation workflows, not
general CAD primitives, so they stay out of the default tool list:
set ``SOLIDWORKS_MCP_PRODUCT_TOOLS=ring_light`` to register both.
The functions remain importable (and unit-tested) unconditionally.
"""

from __future__ import annotations

import os
from typing import List, Optional

from solidworks_mcp.products.ring_light import create_ring_light
from solidworks_mcp.products.ring_light_v3 import create_ring_light_v3

from .base import (
    STATE_CHANGE,
    PositiveMM,
    NonEmptyString,
    ToolResult,
    call_connected,
)

GATE_ENV = "SOLIDWORKS_MCP_PRODUCT_TOOLS"


def _product_tools_enabled() -> bool:
    return "ring_light" in os.environ.get(GATE_ENV, "")


def solidworks_part_create_ring_light(
    save_path: NonEmptyString,
    outer_diameter: PositiveMM = 80.0,
    center_hole_diameter: PositiveMM = 40.0,
    carrier_thickness: PositiveMM = 60.0,
    led_diameter: PositiveMM = 2.6,
    row_counts: Optional[List[int]] = None,
    start_angle_degrees: float = 30.0,
    end_angle_degrees: float = 60.0,
    overwrite_confirm: bool = False,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Create a dome ring-light part (defaults to the confirmed 9-row layout) and save it as .sldprt."""
    return call_connected(
        lambda sw: create_ring_light(
            sw,
            save_path=save_path,
            overwrite_confirm=overwrite_confirm,
            outer_diameter=outer_diameter,
            center_hole_diameter=center_hole_diameter,
            carrier_thickness=carrier_thickness,
            led_diameter=led_diameter,
            row_counts=row_counts,
            start_angle_degrees=start_angle_degrees,
            end_angle_degrees=end_angle_degrees,
        ),
        launch_if_needed,
    )


def solidworks_part_create_ring_light_v3(
    source_path: NonEmptyString,
    save_path: NonEmptyString,
    row_counts: Optional[List[int]] = None,
    overwrite_confirm: bool = False,
    launch_if_needed: Optional[bool] = None,
) -> ToolResult:
    """Preserve a STEP-derived housing and replace its front annulus with a concave dish (defaults to the confirmed 9-row layout)."""
    return call_connected(
        lambda sw: create_ring_light_v3(
            sw,
            source_path=source_path,
            save_path=save_path,
            overwrite_confirm=overwrite_confirm,
            row_counts=row_counts,
        ),
        launch_if_needed,
    )


def register(mcp) -> None:
    if not _product_tools_enabled():
        return
    mcp.tool(title="Create 9-row ring light", annotations=STATE_CHANGE, structured_output=True)(
        solidworks_part_create_ring_light
    )
    mcp.tool(
        title="Create STEP-based concave 9-row ring light",
        annotations=STATE_CHANGE,
        structured_output=True,
    )(solidworks_part_create_ring_light_v3)
