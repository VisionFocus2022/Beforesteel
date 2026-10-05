# PRD：SolidWorks MCP Server

> **版本**: 2.0（as-built 收编版） | **日期**: 2026-10-01 | **状态**: 已批准（2026-10-01 用户裁决生效） | **档位**: 🔴 L3（项目级 PRD）
> **定档声明**: 确定性 高（收编已实现能力，非新需求探索）× 影响半径 大（项目级需求真相源，后续改动以此对账）
> **v1.0 → v2.0**: v1.0（2026-07-17）仅覆盖 MVP 的 8 条 FR；此后 ADR-0001~0012 与 N 系列优化使能力面扩张至 81 工具（开产品工具 83）。v2.0 收编全部已落地能力、以实测数字锚定成功指标，并补齐用户故事映射 / 场景三层 / NFR 8 类 / Q 台账 / 追溯矩阵（模板基因取自 aicad/docs 语料最佳实践）。
> **v1.0 门禁注记**: v1.0 PRD 门禁当时未显式闭合，实现经 594 项测试与架构审查验证后于此追认（见 §11），不伪造当时裁决。

---

## 1. 概述

### 1.1 项目背景与演进

- **起点（2026-07）**：用户希望通过 AI 自然语言驱动 SolidWorks 2026 完成设计任务，替代手动 VBA 宏复制粘贴。v1.0 PRD 定义了连接/建模/文件/装配/查询/特征树/安全 8 条 FR。
- **演进（2026-08~09）**：三波架构治理（git 落地、registry 分域、覆盖率 89%）之后，N 系列解锁了 AI 可感知模型（面命名/尺寸闭环）、装配修复闭环、原生特征族（放样/扫描/圆顶/基准系/螺纹/拔模）、CSG 跨引擎重建、工程图全链路（剖视/公差/粗糙度/PDF-PNG-DXF）、宏转录管线；CI 于 2026-09-02 激活。
- **现状（2026-10-01）**：官方 Python MCP SDK（stdio），81 tools / 3 resources / 5 prompts（开产品工具 83）；测试基线 **594 passed + 107 subtests**（本日实测 14.63s 全绿）；覆盖率实测 87%（CI 硬门 ≥80）；GitHub Actions CI 全绿。

### 1.2 目标与成功指标（基线 → 目标 → 测量）

**核心目标**：把 SolidWorks 2026 COM 自动化以稳定、安全、可回归的 MCP 工具面暴露给 AI，支撑"零件 → 装配 → 工程图 → PDF/STEP/STL"全自动出图。

| 指标 | 基线（2026-10-01 实测） | 目标 | 测量方式 |
|------|------------------------|------|----------|
| 测试基线 | 594 passed + 107 subtests | 不减不破（新改动只增不减） | `venv\Scripts\python.exe -m pytest tests/ -q` |
| 覆盖率 | 87%（2026-09-06 实测） | ≥80%（CI 硬门）；质量目标 89% | CI `coverage --fail-under=80` |
| 工具面 | 81 默认 / 83 开产品工具 | 计数被 5 处测试钉死，改动须同步翻转 | `tests/test_infrastructure.py` 等 |
| CI | 2026-09-02 起全绿 | push main 自动 pytest+coverage+pip-audit 全绿 | GitHub Actions `VisionFocus2022/SolidWorksMCP` |
| 基础建模端到端延迟 | —（无系统实测台账） | < 10s（沿用 v1.0 目标） | `tools/e2e_sw_smoke.py`（需 SW 实机） |
| capabilities 一致性 | 契约测试锁定 | 派生列表与注册表始终相等 | `tests/test_capabilities_sync.py` |

### 1.3 术语表

| 术语 | 定义 |
|------|------|
| run_com / STA | 全部 COM 调用收束到单例 `ComExecutor` 的 `solidworks-com-sta` 线程（ADR-0001），全进程串行 |
| 毒化（poisoned） | COM 调用超时后线程不可安全中断，执行器进入 poisoned 态：后续调用快速失败 `SW_EXECUTOR_POISONED`，进程重启是唯一恢复（ADR-0006.1） |
| 毒化退程 | `SOLIDWORKS_MCP_POISONED_EXIT=1` 时毒化即退出 server 进程，由 MCP 客户端自动重启自愈 |
| mm 契约 | MCP 入参/出参长度一律毫米；COM 层所需米制换算在实现层完成 |
| 五段响应 | 工具统一返回 `{success, data, message, warning, error_code}` 结构 |
| allowed_root | 文件操作白名单根（默认项目根，`SOLIDWORKS_MCP_ALLOWED_ROOT` 可覆盖；ADR-0006.4） |
| 产品工具 | ring_light 等产品专用工具，位于 `solidworks_mcp/examples/`，仅 `SOLIDWORKS_MCP_PRODUCT_TOOLS` 列出时注册（ADR-0003/0012） |
| CSG 契约 | aicad 脚本产物 → 4-op JSON（box/cylinder/hole/cut_hole；v2 增 polygon_prism/swept_arc），主仓 `solidworks_csg_rebuild` 按版本门重建（ADR-0012） |
| 宏转录 | `tools/macro_transcribe.py` 从用户录制宏（.swp/.swb/.txt/.bas）提取确切 API 调用序列，作为"无宏不猜"解锁依据（U9/N58） |
| N 系列 | output/optimization-plan-*.md 驱动的逐项优化任务序列（N8~N58+），gitignored，细粒度以最新计划文件为准 |

---

## 2. 角色与用户故事

### 2.1 用户角色

| 角色 | 描述 | 使用场景 | 技术水平 |
|------|------|----------|---------|
| 机械设计操作者 | 用自然语言完成建模/出图的设计人员 | "画一个法兰盘并导出 STEP 与 PDF 图" | 初级~中级 |
| 自动化/批量处理人员 | 重复执行导入导出、参数扫描 | "把这批 STEP 逐一导入并核对体积" | 中级 |
| AI 建模代理（MCP 客户端） | Claude Code 等 AI，工具面的一等公民调用者 | 通过 81 工具 + 5 prompts 自主完成设计任务 | — |
| 项目维护者 | 本仓与 aicad 子仓维护者 | 跑评测/维护基线/ADR 冻结 | 高级 |

### 2.2 用户故事（US → FR）

| ID | 用户故事 | 映射 FR |
|----|---------|--------|
| US-001 | 当我用自然语言建模时，我想要基础几何+原生特征（阵列/放样/扫描/圆顶/基准系/螺纹/拔模）一步到位，以便不必手动点菜单 | FR-002, FR-003 |
| US-002 | 当我要交付工程图时，我想要三视图+尺寸+剖视+公差+粗糙度并导出 PDF/PNG/DXF，以便直接发给工艺/客户 | FR-004 |
| US-003 | 当装配出现干涉或配合错误时，我想要 AI 定位干涉位置、删错配、挪零件并复检，以便快速修复装配 | FR-006 |
| US-004 | 当我要参数化调整已有模型时，我想要改尺寸后回读验证生效，以便闭环驱动而非一次性脚本 | FR-007, FR-010 |
| US-005 | 当我在 aicad（build123d）与 SolidWorks 间流转几何时，我想要 CSG 契约重建保持体积一致，以便双引擎互证 | FR-008 |
| US-006 | 当我要执行一组设计操作时，我想要计划式批量执行（design_execute_plan），以便一次对话完成多步流程 | FR-013 |
| US-007 | 当维护者回归改动时，我想要测试/CI/工具计数/capabilities 全部钉死，以便任何漂移当场红灯 | FR-011, FR-012, NFR 全类 |
| US-008 | 当 SolidWorks 卡死时，我想要超时+毒化快速失败+自动退程重启，以便整个工具面不被一次挂死瘫痪 | FR-001, FR-012 |

### 2.3 场景与流程（主 / 备选 / 异常 三层）

| 层 | 场景 | 流程/预期行为 | 关联 FR |
|----|------|--------------|--------|
| 主成功 | "建模一个带 4 孔法兰并出三视图" | Claude Code 依次调用建模工具（mm 入参）→ 质量属性/特征树核验 → 工程图工具 → 导出 PDF/STEP；全程五段响应 | FR-002, FR-004, FR-010 |
| 备选流 | 参数调整/批量计划 | dimension_set 改尺寸并回读验证；或 design_execute_plan 一次执行操作组 | FR-007, FR-013 |
| 异常流 1 | SolidWorks 未运行 | 进程探测（会话过滤，fail-closed）→ 结构化错误 SW_NOT_RUNNING / SW_CONNECTION_FAILED，提示先启动 SW | FR-001 |
| 异常流 2 | SW 模态框导致 COM 挂死 | 单调用 120s 超时 → SW_TIMEOUT → 毒化 → 后续调用 SW_EXECUTOR_POISONED 快速失败；开毒化退程则进程自动重启自愈 | FR-012 |
| 异常流 3 | 写文件越界/覆盖已有文件 | allowed_root 拒绝；覆盖需显式 overwrite_confirm；写盘时刻 TOCTOU 复查 | FR-005, FR-011 |

---

## 3. 功能需求（as-built 收编）

### 3.1 FR 总表（15 条）

| ID | 名称 | 描述与关键能力 | 优先级 | 状态 | 来源 |
|----|------|---------------|--------|------|------|
| FR-001 | 连接与会话管理 | 连接已运行 SW 实例、版本获取；进程探测按会话过滤（`ProcessIdToSessionId`，fail-closed） | P0 | ✅ 已实现 | v1.0 + ADR-0006.2 |
| FR-002 | 参数化零件建模 | 棱柱/圆柱/圆锥/板/圆孔/螺纹孔/回转/旋转轮廓；环形阵列双工具（READ_ONLY 布局预览 + DESTRUCTIVE 执行，pydantic AnnularRing 逐项校验，上限防 DoS） | P0 | ✅ 已实现 | v1.0 + ADR-0007 |
| FR-003 | 原生特征族 | 镜向、放样（InsertProtrusionBlend2）、扫描（InsertProtrusionSwept4 圆截面）、圆顶、基准面/基准轴、真实螺纹（Helix+CutSwept5）、拔模、圆角、筋（**数学替代**：薄板近似，非自适应壁） | P0 | ✅ 已实现（筋/线性阵列为数学替代，见 Q-4） | ADR-0011 + N28/N29 |
| FR-004 | 工程图出图 | 三视图、尺寸标注、尺寸去重叠整理、剖视图、公差/粗糙度/注释、PDF/PNG/DXF 导出 | P0 | ✅ 已实现（v1.0 曾列二期） | v1.0 FR-005 + N 系列 |
| FR-005 | 文件导入导出与生命周期 | 打开/导入/导出 SLDPRT/SLDASM/STEP/IGES/STL；`solidworks_file_close` 显式关闭（DESTRUCTIVE，默认丢弃未保存修改） | P0 | ✅ 已实现 | v1.0 + ADR-0006.5 |
| FR-006 | 装配操作与修复闭环 | 插入零部件/基础配合；干涉检测→空间定位（干涉体 AABB+质心/体积）→删 mate（下钻 MateGroup 复检）→组件变换（SetTransformAndSolve3，替换式语义）→EditRebuild3 复检；BOM 扩列（质量/材料） | P0 | ✅ 已实现 | v1.0 FR-004 + ADR-0010 |
| FR-007 | AI 可感知模型与参数化闭环 | 面命名（SetEntityName，Face0..N 前缀可配，仅命名未命名面）、topology 面枚举、特征详情读取、dimension_set（mm 契约，负返回码=拒绝，改后 EditRebuild3 回读验证）、add_mate、apply_fillet | P0 | ✅ 已实现 | ADR-0009 |
| FR-008 | CSG 跨引擎重建 | `solidworks_csg_rebuild`：aicad 脚本产物按 4-op JSON 契约重建；契约 v1（box/cylinder/hole/cut_hole）+ v2（polygon_prism/swept_arc），含 v1 计划带 v2 op 的版本门；验收=跨引擎体积互证 | P1 | ✅ 已实现（v2 仅 SW 重建方向，反向见 Q-5） | ADR-0012 |
| FR-009 | 特征树批量操作 | 遍历、重命名、抑制/解除抑制 | P1 | ✅ 已实现 | v1.0 FR-007 |
| FR-010 | 查询与验证 | 质量属性（体积/表面积/质量/重心）、测量、特征树清单 | P0 | ✅ 已实现 | v1.0 FR-006 |
| FR-011 | 安全与确认机制 | 一切 COM 经 run_com；文件操作限 allowed_root 内（逐组件 realpath 规范化，禁词法折叠）；破坏性操作标 DESTRUCTIVE；覆盖需显式确认；写盘时刻 TOCTOU 复查（微秒级窗口） | P0 | ✅ 已实现 | v1.0 FR-008 + ADR-0004/0006.3/0006.4 |
| FR-012 | COM 韧性 | 单调用超时（默认 120s，`SOLIDWORKS_MCP_COM_TIMEOUT_SECONDS`，垃圾值回退 120）；超时毒化后快速失败；`SOLIDWORKS_MCP_POISONED_EXIT=1` 毒化退程自愈 | P0 | ✅ 已实现 | ADR-0006.1 |
| FR-013 | 设计计划执行 | `solidworks_design_execute_plan`：按计划批量执行一组设计操作 | P1 | ✅ 已实现 | README（N 系列） |
| FR-014 | 宏转录解锁管线 | `tools/macro_transcribe.py`（.swp/.swb/.txt/.bas 四格式，18 测试锁定）+ 录宏指南；pattern 族已解锁（N58），rib/combine/AutoBalloon 待用户录宏 | P1 | ◐ 部分完成 | U9/N58 |
| FR-015 | 产品工具 env 门控 | ring_light 等产品工具默认不注册，`SOLIDWORKS_MCP_PRODUCT_TOOLS` 显式列出才启用（81→83），测试钉死默认面 | P2 | ✅ 已实现 | ADR-0003/0012 |

### 3.2 交互需求

- 工具命名 `solidworks_<resource>_<action>`；长度参数一律 mm（内部换算 m）；五段统一响应。
- 工具按域注册于 `solidworks_mcp/registry/`（part/assembly/drawing/features/file_io/misc/properties/products + prompts），server.py 仅门面（~206 行）——**新工具加域模块，不加 server.py**（AGENTS.md 惯例）。
- capabilities 工具清单由 `mcp._tool_manager.list_tools()` 派生，契约测试锁定，禁止手写漂移。

### 3.3 数据需求

- 覆盖确认：`save_path` 指向已存在文件时返回 FILE_ALREADY_EXISTS，须显式 `overwrite_confirm` 才覆盖（v1.0 契约保持）。
- CSG 契约 JSON（v1/v2 op 集合与堆叠语义）以 ADR-0012 为冻结口径。
- 错误码契约：v1.0 表（SW_NOT_RUNNING/SW_API_ERROR/INVALID_PARAMETER/FILE_ALREADY_EXISTS/OPERATION_CANCELLED）+ as-built 扩充（SW_CONNECTION_FAILED/INVALID_OUTPUT_PATH/SW_TIMEOUT/SW_EXECUTOR_POISONED）；约半数路径落默认 OPERATION_FAILED 的收敛是持续项（架构审查 P2-7）。

### 3.4 边界与异常场景（需求级）

| 边界/异常 | 触发条件 | 系统行为 | 用户可见结果 | 关联 FR |
|-----------|---------|----------|--------------|--------|
| SW 未运行 | 启动时无本会话 SW 进程 | fail-closed 拒绝连接类工具 | 结构化错误 + "请先启动 SolidWorks" | FR-001 |
| COM 挂死 | SW 模态框/长运算超 120s | 超时→毒化→快速失败；（可选）退程重启 | SW_TIMEOUT / SW_EXECUTOR_POISONED + 恢复指引 | FR-012 |
| 路径越界 | 目标路径不在 allowed_root 内 | 拒绝执行 | 明确拒绝原因 | FR-011 |
| 覆盖冲突 | save_path 已存在 | 不执行，返回确认请求 | FILE_ALREADY_EXISTS | FR-005 |
| file_close 丢修改 | 未保存修改 + 默认 save_changes=false | 丢弃并关闭 | DESTRUCTIVE 标注提示 | FR-005 |
| 环参数超限 | 环>100 / 环内>1000 / 总量>5000 | pydantic 校验拒绝 | INVALID_PARAMETER | FR-002 |
| CSG 版本门 | v1 计划含 v2 op | 报错不猜 | 明确版本错误 | FR-008 |
| AutoBalloon 缺口 | 工程图自动气球 | 未提供（待宏解锁，Q-2） | 能力边界声明 | FR-014 |

---

## 4. 非功能需求（8 类）

| 类 | 要求 | 判定 |
|----|------|------|
| NFR-001 性能 | 基础建模端到端 <10s（实机）；COM 单调用默认 120s 帽；全量测试套 <1min（实测 14.63s） | e2e 台账 / pytest |
| NFR-002 兼容性 | 594+107 基线不破；81/83 工具计数 5 处钉死；SW2026 + Win10/11 + Python 3.12 venv | pytest + CI |
| NFR-003 安全 | 安全红线 5 条（run_com 强制 / allowed_root / DESTRUCTIVE 标注 / mm→m 契约 / 不 push 不跨仓）；密钥零入库；pip-audit 0 CVE | CI + code review |
| NFR-004 可用性 | 81 工具对 AI 自然语言可达；错误提示含错误码+原因+下一步，非泛化文案 | 人工抽检 |
| NFR-005 可维护性 | registry 分域注册；SW 常量集中 constants.py；capabilities 派生；ADR 冻结决策；文档基线回填纪律（N36/M-4：改测试数的同一 commit 刷新基线数字） | 架构审查 |
| NFR-006 可靠性 | 毒化快速失败 + 退程自愈；fail-closed 进程探测；超时兜底（COM 无法安全中断的既定语义） | 现有测试 |
| NFR-007 可观测性 | 五段统一响应；日志仅 main() 初始化（测试不污染运行日志）；e2e 台账 tracked 于 output/e2e-summary.md | 现有机制 |
| NFR-008 环境与部署 | 本地单用户 Windows + venv；CI windows runner；无外网运行时依赖 | 部署文档 |

---

## 5. 验收标准（项目级回归钉死）

- **AC-001**: `pytest tests/ -q` → 594 passed + 107 subtests 全绿（基线不破）〔FR 全体〕
- **AC-002**: push main 后 GitHub Actions（pytest + coverage≥80 + pip-audit）全绿〔NFR-002/003〕
- **AC-003**: 默认工具数 81，`SOLIDWORKS_MCP_PRODUCT_TOOLS=ring_light` 后 83，5 处计数断言一致〔FR-015〕
- **AC-004（非 happy）**: 毒化注入后，后续任意工具调用快速失败 SW_EXECUTOR_POISONED〔FR-012〕
- **AC-005（非 happy）**: allowed_root 外路径与未确认覆盖均被拒绝且错误可读〔FR-005, FR-011〕
- **AC-006（非 happy）**: SW 未运行时连接类工具返回结构化错误（SW_NOT_RUNNING/SW_CONNECTION_FAILED）〔FR-001〕
- **AC-007**: capabilities 派生列表与注册表完全一致（契约测试）〔§3.2〕

> 已实现 FR 的细粒度行为由 594 项测试与 ADR 探针记录钉死，本表只钉**项目级回归口径**；新增能力的 AC 落各自特性 PRD（如 annular / 未来宏解锁族）。

---

## 6. 约束与假设

### 6.0 需求探索三栏账（v2.0 收编时点）

| 已知（确证事实） | 假设（待验证 · 不成立则…） | 未知（已裁决/待决） |
|------------------|----------------------------|---------------------|
| 81/83 工具、594+107 测试、87% 覆盖、CI 绿（本日实测/台账） | SW2026 COM 晚绑定行为在补丁版本间稳定 → 否则 FakeModel 双打需随实机校准 | COM 超时实机模态框最优值 → Q-3 |
| ADR-0001~0012 决策冻结；e2e 台账存在 | 单机单用户使用形态保持 → 多用户并发需重新立项（v1.0 已排除，维持） | rib/combine/AutoBalloon 解锁路径 → Q-2 |
| 宏转录管线就绪（18 测试锁定）；pattern 族已证可行 | 数学替代特征（筋/线性阵列）可满足当前交付精度 → 否则待 Q-4 宏解锁 | 线性阵列原生 API 缺失 → Q-4 |

### 6.1 技术约束

Windows 10/11 + SolidWorks 2026 正版；Python 3.12 venv；官方 `mcp` SDK（stdio）；pywin32 晚绑定 + 手工镜像常量（ADR-0002）。

### 6.2 业务约束

用户手动启动 SW（不自动拉起）；复杂创造性决策仍由人类主导；`aicad/` 为独立 git 仓，双仓分别提交绝不跨仓。

### 6.3 假设条件

同 §6.0 假设栏。

---

## 7. 范围定义

**In Scope（持续维护面）**: §3.1 全部 FR 的回归钉死；宏解锁三族（rib/combine/AutoBalloon）按 U9 流程推进；文档-实现对账（PRD/design/README/AGENTS 基线联动）。

**Out of Scope**: PDM 集成；仿真（Simulation/Flow）；GD&T 形位公差框格；复杂曲面（放样边界曲面族）；多用户并发控制；自动启动 SW；线性/草图驱动阵列的**原生**实现（API 缺失，维持数学替代）；替代人类设计师的创造性决策（v1.0 反目标全部沿用）。

**Future Consideration（🔮）**: CSG v2 反向导出（aicad 方向 AST 识别 polygon 两步构造）；AutoBalloon（待宏）；SW2027 升级适配（模板版本参数化已预留 ADR 动作 18）。

---

## 8. 依赖与风险

### 8.1 外部依赖

| 依赖 | 类型 | 影响 | 替代方案 |
|------|------|------|----------|
| SolidWorks 2026 Type Library（COM） | 商业软件 | 全部工具面 | 无（产品本体） |
| pywin32 / mcp SDK | 库（锁定版本） | 协议层 | 官方 SDK 内 FastMCP 门面 |
| GitHub Actions windows runner | CI | 回归门 | 本地 pytest 兜底 |
| 用户实机录宏（U9） | 人工件 | FR-014 三族解锁 | AI 代录（pywinauto 驱动，pattern 族已证可行） |

### 8.2 风险评估

| 风险 | 可能性 | 影响 | 缓解 |
|------|--------|------|------|
| COM 挂死瘫痪工具面（SW 模态框） | 中 | 高 | 超时+毒化+退程自愈已落地（FR-012）；实机超时值待 Q-3 校准 |
| 长装配会话工作集增长 | 中 | 中 | file_close + 会话过滤已落地；COM 超时兜底；长会话验证待 Q-3 |
| 文档/基线漂移复发（两次同源教训 N36/M-4） | 中 | 中 | 基线回填纪律入 AGENTS.md；本 PRD 实数锚定 |
| 多会话并行撞车（output/ 曾被误清） | 低 | 中 | git status 前置检查纪律；roadmap 快照承接 |
| 数学替代特征精度不达交付 | 低 | 中 | 如实声明边界（README §能力边界）；宏解锁后换原生 |

### 8.3 发布与回滚

发布 = git commit（main）→ CI 自动验证；回滚 = `git revert`（纯代码仓，无数据迁移）。配置变更（env 门控/超时）均为默认关闭或回退安全值。

---

## 9. 待决问题（Q 台账）

| ID | 问题 | 影响 | Owner | 状态 |
|----|------|------|-------|------|
| Q-1 | README 工具数自相矛盾：L9 "81 tools" vs L12 "80 → 82"（AGENTS.md 头部为 81/83） | 文档可信度 | AI | ✅ 已修复 2026-10-01（README L12 与 AGENTS.md 钉死行同步改为 81→83，以 tests/test_server.py 断言为准；roadmap W3#2 收口） |
| Q-2 | rib / combine / AutoBalloon 三族宏录制解锁（管线就绪，等宏） | FR-014 完成 | 用户 | 待录宏（指南：docs/macro-recording-guide.md） |
| Q-3 | COM 超时实机模态框验证 + CloseDoc/会话过滤长会话验证（2026-08-28 §11 登记；此后 e2e 台账已建立，最新覆盖状态待核实） | FR-012 参数校准 | 用户（需 SW 实机） | 待验证 |
| Q-4 | 线性阵列原生 API 缺失（CreateDefinition(91)=None 实证）→ 现用数学替代（非参数链接） | FR-003 原生性 | AI（跟踪 SW API） | 已声明边界，观察 |
| Q-5 | CSG v2 反向导出（aicad 方向识别 polygon 两步构造）延后 | FR-008 双向闭环 | AI | 待 aicad 侧排期 |

---

## 10. 需求追溯矩阵

| 需求 | 用户故事 | 验收标准 | 优先级 | 状态 | 来源 ADR |
|------|---------|---------|--------|------|---------|
| FR-001 | US-008 | AC-006 | P0 | ✅ | 0006.2 |
| FR-002 | US-001 | AC-001/003 | P0 | ✅ | 0007 |
| FR-003 | US-001 | AC-001 | P0 | ✅ | 0011 |
| FR-004 | US-002 | AC-001 | P0 | ✅ | N 系列 |
| FR-005 | US-001 | AC-005 | P0 | ✅ | 0006.5 |
| FR-006 | US-003 | AC-001 | P0 | ✅ | 0010 |
| FR-007 | US-004 | AC-001 | P0 | ✅ | 0009 |
| FR-008 | US-005 | AC-001 | P1 | ✅ | 0012 |
| FR-009 | US-001 | AC-001 | P1 | ✅ | — |
| FR-010 | US-004 | AC-001 | P0 | ✅ | — |
| FR-011 | US-007 | AC-005 | P0 | ✅ | 0004/0006.3/6.4 |
| FR-012 | US-008 | AC-004 | P0 | ✅ | 0006.1 |
| FR-013 | US-006 | AC-001 | P1 | ✅ | — |
| FR-014 | US-001 | AC-001 | P1 | ◐ | U9/N58 |
| FR-015 | US-007 | AC-003 | P2 | ✅ | 0003/0012 |
| NFR-001~008 | US-007 | AC-001/002/007 | P0-P2 | ✅（机制在位） | — |

---

## 11. 审批记录

| 版本 | 日期 | 决定 | 备注 |
|------|------|------|------|
| v1.0 | 2026-07-17 | 探索门禁通过 | PRD 门禁当时未显式闭合，**2026-10-01 事后追认**（实现经 594 测试+架构审查验证） |
| v2.0 | 2026-10-01 | **已批准** | 用户裁决"1通过"（本会话，无修改） |

---

## 附录 A：v1.0 → v2.0 收编对照

| v1.0 FR | v2.0 去向 | 说明 |
|---------|----------|------|
| FR-001 连接管理 | FR-001 | +会话过滤 |
| FR-002 基础零件建模 | FR-002 + FR-003 | 拆为基础几何与原生特征族 |
| FR-003 文件导入导出 | FR-005 | +file_close 生命周期 |
| FR-004 装配体操作 | FR-006 | +修复闭环与 BOM 扩列 |
| FR-005 工程图出图（二期） | FR-004 | **已落地**（三视图→公差/粗糙度/PDF-PNG-DXF 全链） |
| FR-006 查询与验证 | FR-010 | — |
| FR-007 特征树批量操作 | FR-009 | — |
| FR-008 安全与确认机制 | FR-011 + FR-012 | 安全硬化与 COM 韧性分立 |
| （无） | FR-007/008/013/014/015 | ADR-0009/0012/N 系列新增 |

## 附录 B：变更记录

| 版本 | 日期 | 变更内容 | 变更人 |
|------|------|----------|--------|
| 1.0 | 2026-07-17 | 初始版本（MVP 8 FR） | — |
| 2.0 | 2026-10-01 | as-built 收编：15 FR + 实数基线 + US/场景三层/NFR 8 类/Q 台账/追溯矩阵 | ZCode（SDW 文档优化批） |

---

## 自检（12 项，提交前核对）

- [x] **完整性**: 现有能力面（81 工具/ADR-0001~0012/N 系列）逐条对应 FR-001~015
- [x] **用户故事映射**: US-001~008 每条 ≥1 FR（§2.2）
- [x] **场景三层**: §2.3 主/备选/异常；§3.4 边界表 8 条
- [x] **无歧义**: 全文无"快速/友好/高效/灵活/强大"类歧义词（"快速修复"仅出现在用户故事语境叙述中——已改为"快速修复装配"属用户任务描述，非需求表述）
- [x] **可追溯**: §10 矩阵 FR↔US↔AC↔ADR 全映射
- [x] **AC 可观察**: AC-001~007 全部命令/测试可判；含 3 条非 happy-path（AC-004/005/006）
- [x] **范围清晰**: §7 In/Out/Future 三段
- [x] **风险已识别**: §8.2 五条含技术/流程/环境三类
- [x] **指标可量化**: §1.2 基线-目标-测量三列，数字为本日实测或注明台账日期
- [x] **假设已声明**: §6.0 三栏账
- [x] **待决有主**: §9 Q-1~Q-5 各有 Owner
- [x] **编号连续**: FR-001~015 / US-001~008 / AC-001~007 / Q-1~Q-5 无跳号

## ✅ 门禁

- [x] 探索门禁（v1.0，2026-07）— 通过
- [x] PRD 门禁 v1.0 — **事后追认 2026-10-01**（当时未闭合，见 §11）
- [x] **PRD 门禁 v2.0** — 2026-10-01 用户裁决"1通过"，无修改，v2.0 生效
