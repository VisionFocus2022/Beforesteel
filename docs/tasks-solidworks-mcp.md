# Tasks：SolidWorks MCP Server

**版本**: 1.1（历史归档 + 执行状态回填）
**日期**: 2026-07-17（v1.0）｜ 2026-10-01（v1.1 回填）
**关联 PRD**: `E:\SolidWorks 2026\SolidWorksMCP\docs\prd-solidworks-mcp.md`  
**关联 Design**: `E:\SolidWorks 2026\SolidWorksMCP\docs\design-solidworks-mcp.md`

> 🗄️ **Superseded 声明（2026-10-01）**：本文件是 **MVP 期（2026-07）的历史任务清单**，T1-T15 已全部完成（状态回填见 §1）。后续工作由以下文档接续，请勿在本文件追加任务：
> - `docs/tasks-solidworksmcp-optimization.md`（三波架构治理，2026-08-28，✅ 大部分完成）
> - `docs/prd-annular-pattern-tool.md` + `docs/tasks-annular-pattern-tool.md`（独立立项范例，✅）
> - `output/optimization-plan-<最新日期>.md`（N 系列逐项队列，gitignored，细粒度以此为准）
> - `docs/roadmap-solidworksmcp-optimization.md`（程序层总览，2026-10-01 起）

---

## 1. 任务分解

| 编号 | 任务 | 描述 | 依赖 | 估算 | 风险 | 状态 |
|------|------|------|------|------|------|------|
| T1 | 初始化项目结构 | 创建 Python 包目录、pyproject.toml、requirements.txt | 无 | S | 低 | ✅ |
| T2 | 安装 pywin32 和 fastmcp | 在本地 Python 环境安装依赖并验证可用 | T1 | S | 低 | ✅（后切官方 mcp SDK，见 design 附录 A） |
| T3 | 实现 SolidWorks 连接管理 | 封装 `win32com.client.Dispatch`，检测运行状态，获取版本 | T2 | S→M | 中 | ✅ |
| T4 | 实现模板路径查找工具 | 动态搜索中英文 Part.prtdot 模板路径 | T1 | S | 低 | ✅（后版本参数化，ADR 动作 18） |
| T5 | 实现路径安全校验工具 | 路径规范化、目录遍历防护、确认模式检查 | T1 | S | 低 | ✅（后升级逐组件解析，ADR-0004） |
| T6 | 实现基础零件建模 API | 圆柱体、立方体创建 | T3, T4 | M | 中 | ✅ |
| T7 | 实现文件导入导出 API | 打开 SLDPRT、导入/导出 STEP | T3, T5 | M | 中 | ✅ |
| T8 | 实现查询与验证 API | 质量属性、特征树读取 | T3 | M | 中 | ✅ |
| T9 | 实现特征树批量操作 API | 重命名、抑制/解除抑制 | T3, T8 | M | 中 | ✅ |
| T10 | 实现装配体操作 API | 插入零件、添加基础配合 | T3, T7 | L | 高 | ✅（后扩展修复闭环，ADR-0010） |
| T11 | 实现 MCP Server 入口 | 使用 MCP SDK 注册所有工具 | T6-T10 | M | 中 | ✅（后收缩为门面，ADR-0012） |
| T12 | 配置 Claude Code MCP | 编写并应用 claude_mcp_config.json | T11 | S | 低 | ✅ |
| T13 | 编写单元测试 | 测试模板查找、路径安全、参数校验 | T1-T5 | M | 低 | ✅（基线已增长至 594 passed + 107 subtests，2026-10-01 实测） |
| T14 | 集成验证 | 启动 SolidWorks，用 Claude Code 自然语言完成 5 个操作 | T12 | L | 高 | ✅（一次性验证完成；持续验证由 `tools/e2e_sw_smoke.py` + output/e2e-summary.md 台账承接） |
| T15 | 编写 README 和使用文档 | 安装、配置、示例命令 | T12 | S | 低 | ✅ |

> 状态回填说明（2026-10-01）：以上状态依据 as-built 证据（README/AGENTS.md/design 附录 A/ADR）重建回填，非执行期逐任务记录——本文件属历史归档，重建粒度到任务级即可。

---

## 2. 依赖排序

```
T1 ──┬── T2 ── T3 ──┬── T6 ───┐
     │              ├── T7 ───┼── T11 ── T12 ── T14
     ├── T4 ────────┤         │
     ├── T5 ────────┘         │
     └── T13 ─────────────────┘

T3 ── T8 ── T9
T3, T7 ── T10
T12 ── T15
```

**并行路径**:
- 路径 A: T1 → T2 → T3 → T6 → T11
- 路径 B: T1 → T4, T5（可与 T2/T3 并行）
- 路径 C: T3 → T7 → T10（装配体，依赖文件 I/O）
- 路径 D: T3 → T8 → T9（查询与特征操作）
- 路径 E: T1-T5 → T13（单元测试可与核心开发并行）

---

## 3. 验证定义

| 任务 | 验证方式 | 通过标准 |
|------|---------|---------|
| T1 | 检查目录结构和文件存在 | `pyproject.toml`、`requirements.txt`、包目录存在 |
| T2 | 运行 `python -c "import win32com.client; import fastmcp"` | 无 ImportError |
| T3 | 在 SolidWorks 运行时执行连接测试脚本 | 返回版本号且 `connected=True` |
| T4 | 运行模板查找单元测试 | 至少找到一个存在的 `Part.prtdot` |
| T5 | 运行路径安全单元测试 | 非法路径被拒绝，合法路径通过 |
| T6 | 在 SolidWorks 中运行创建圆柱体/立方体脚本 | 文档创建成功，质量属性体积 > 0 |
| T7 | 导入/导出 STEP 测试 | 文件成功生成且可重新打开 |
| T8 | 读取质量属性和特征树 | 返回非空结果 |
| T9 | 重命名和抑制特征 | 特征树状态正确变更 |
| T10 | 装配体插入和配合 | 装配体中零部件数量增加，配合添加成功 |
| T11 | 启动 MCP server 并列出工具 | `list_tools` 返回所有注册工具 |
| T12 | Claude Code 能识别 MCP server | Claude Code 提示 tools 可用 |
| T13 | 运行 `pytest tests/` | 单元测试全部通过 |
| T14 | 自然语言端到端测试 | 至少完成 5 个不同操作且结果正确 |
| T15 | 文档完整性检查 | README 包含安装、配置、示例三步 |

---

## 4. 工作量估算

| 规模 | 任务数 | 任务编号 |
|------|--------|---------|
| S（小） | 6 | T1, T2, T4, T5, T12, T15 |
| M（中） | 6 | T3, T6, T7, T8, T9, T11, T13 |
| L（大） | 2 | T10, T14 |

**预计总开发时间**: 1-2 天（含调试和 SolidWorks 环境适配）

---

## 5. 跨阶段一致性检查

| PRD FR | Design 组件 | 任务 | 测试 |
|--------|------------|------|------|
| FR-001 连接管理 | `solidworks_api/app.py` | T3 | T3, T14 |
| FR-002 基础零件建模 | `solidworks_api/part.py` | T4, T6 | T6, T14 |
| FR-003 文件导入导出 | `solidworks_api/file_io.py` | T5, T7 | T7, T14 |
| FR-004 装配体操作 | `solidworks_api/assembly.py` | T10 | T10, T14 |
| FR-005 工程图出图 | `solidworks_api/drawing.py` | 二期 | 二期 |
| FR-006 查询与验证 | `solidworks_api/part.py` + `features.py` | T8 | T8, T14 |
| FR-007 特征树批量操作 | `solidworks_api/features.py` | T9 | T9, T14 |
| FR-008 安全与确认 | `utils/security.py` | T5 | T5, T13 |

**说明**: FR-005（工程图出图）因复杂度较高，放入二期，本期不包含在任务列表中。PRD 中保留该 FR，但 tasks 中标注为二期。

---

## 6. 高风险任务与缓解

| 任务 | 风险 | 缓解措施 |
|------|------|---------|
| T3 连接管理 | SolidWorks 未启动或 COM 注册问题 | 提供清晰错误提示，要求用户先启动 SolidWorks |
| T6 基础建模 | API 参数顺序/单位错误导致特征创建失败 | 使用 VBA 宏中已验证的参数模板 |
| T10 装配体 | 配合对象选择复杂，易失败 | 先实现 MVP 配合（重合/同心），文档说明限制 |
| T14 集成验证 | 依赖用户 SolidWorks 环境 | 准备测试清单，允许部分测试跳过 |

---

## 7. 门禁记录

- [✅] 探索门禁已通过
- [✅] PRD 门禁已通过
- [✅] Design 门禁已通过
- [x] Tasks 门禁——**事后追认（2026-10-01）**：v1.0 当时未显式闭合，15 项任务已全部完成并经测试基线验证（见 §1 状态回填），此处补记追认。
