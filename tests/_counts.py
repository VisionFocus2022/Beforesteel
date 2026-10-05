"""Tool-count pins — single source of truth (R3, 2026-10-05).

基线纪律（AGENTS.md）：改工具数时，同一 commit 更新下面两个数字与
AGENTS.md 首行计数；此前 5 处散落的硬编码（test_server ×3、
test_infrastructure ×2 与 delegation sweep）已全部收敛到这里。

计数测试护栏的是"数字一致"而非"语义一致"——这是项目有意选择的
防漂移债（ADR-0012/N14），不要为自动化而自动化。
"""

from __future__ import annotations

# 默认注册的工具数（产品工具 env 门关闭时）。
DEFAULT_TOOLS = 81

# SOLIDWORKS_MCP_PRODUCT_TOOLS=ring_light 时的工具数（81 + 2 个 ring_light）。
PRODUCT_TOOLS = 83

# MCP prompts 数量（registry/prompts.py）。
PROMPT_COUNT = 5
