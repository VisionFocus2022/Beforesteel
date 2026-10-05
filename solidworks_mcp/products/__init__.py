"""Product-specific tools kept outside the generic API layer.

Modules here implement one-off designs (e.g. the MV-LRSS-H-80-W ring
light) rather than reusable SolidWorks operations. The MCP server
registers them as gated product tools (SOLIDWORKS_MCP_PRODUCT_TOOLS),
but new generic capabilities belong in
``solidworks_mcp.solidworks_api`` instead of this package.

Renamed from ``examples/`` (2026-10-05, ADR-0003 addendum): this
package is imported unconditionally by ``registry/products.py``, so it
is production code, not samples.
"""
