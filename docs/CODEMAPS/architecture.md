<!-- Generated: 2026-08-28 | Files scanned: 43 .py | Tools: 25 | Tests: 191 passed | Token estimate: ~700 -->

> ⚠️ **本快照已过时（2026-08-28 生成，停留在 25 工具时代）**——当前代码为
> 81/83 工具 + `server → registry → solidworks_api → utils → config` 五层
> （N14 拆分引入 registry 层；产品包已更名 products/，空壳 tools/ 已删除）。
> **架构地图以 `AGENTS.md` 为准**；本文件仅存档历史形态，待重生成。

# Architecture

## System

```
MCP client (Claude etc.)
  │ stdio (JSON-RPC)
  ▼
solidworks_mcp/server.py — FastMCP (mcp SDK 1.28.1)
  │  25 @mcp.tool + 3 resources + 1 prompt, all registered here
  │  _call_connected → run_com(optional timeout) → SolidWorksApp.connect
  ▼
utils/com_executor.py — single STA worker thread "solidworks-com-sta"
  │  every COM call serialized; timeout → poisoned executor fails fast
  │  pywin32 late binding (Dispatch / GetActiveObject, call_or_value shim)
  ▼
SLDWORKS.exe (SolidWorks 2026, external process, user-launched)
```

## Layers (one-way deps: server → api/examples → utils → config)

| Layer | Files | Role |
|-------|-------|------|
| Protocol | server.py (679) | tool registration, annotations (READ_ONLY/STATE_CHANGE/DESTRUCTIVE/IDEMPOTENT_WRITE), capabilities derived from registry |
| Generic API | solidworks_api/{app, part, design, features, file_io, assembly, pattern}.py | reusable CAD operations |
| Shared primitives | solidworks_api/{constants, geometry, sketch}.py | SW enums (single source), mm_to_m/linspace/select_plane, FeatureExtrusion2/FeatureCut3 arg vectors (written once) |
| Product examples | examples/{ring_light, ring_light_v3}.py (1276) | MV-LRSS-H-80-W one-off tools; new generic work must NOT go here (ADR-0003/0006.6) |
| Cross-cutting | utils/{com, com_executor, common, security, templates, validation}.py, config.py | response envelope, path security, env config |

## Entry points

- `python -m solidworks_mcp.server` (stdio; .mcp.json points venv python here)
- main() configures logging then mcp.run(); module import is side-effect free

## Key invariants

- All file IO under allowed_root: validate_output_file → (modeling) → ensure_sink_path re-check at write time (TOCTOU narrowed); normalize_path resolves junctions component-wise (never folds `..` across links)
- Overwrites require overwrite_confirm (incl. derived .generated.stl/.layout.json)
- Units: tools take mm; COM receives meters via mm_to_m
- Version control: git main, 14 commits (baseline e6916e1 → c420172); CI file ready, activates on first remote push
