# PRD — factoryforge-mcp：把 FactoryForge 工厂仿真暴露为 MCP 工具面

> **版本**：v1.0（2026-10-04）
> **定档**：🔴 L3（结构化开发工作流）
> - 确定性：低→**已收敛**（探索门禁 2026-10-04 三项裁决：分两波 / 独立新仓 / 小步并行主线不变）
> - 影响半径：大（新子产品线 + 外部依赖锁定；**不动主仓 81/83 工具契约**——独立仓方案规避硬触发器 7）
> - 规模：大（预估 >1500 行 / >15 文件，Wave 1）
> - 可逆性：双向门（独立新仓，可整仓废弃）
> **关联**：`docs/roadmap-factoryforge-integration.md`（程序计划层，两波结构）
> **上游**：FactoryForge 1.1.1（MIT，`E:\开源项目\factoryforge-1.1.1\`，消费不 fork）

## ✅ 门禁裁决记录

| 门禁 | 日期 | 结论 |
|---|---|---|
| 探索门禁（三栏账） | 2026-10-04 | 通过：方向=分两波（先 MCP 化后 CAD 闭环）；落点=独立新仓；优先级=小步并行、用户验证主线不变 |
| PRD 门禁 | 2026-10-04 | 通过：PRD v1.0 确认进 Phase 2；附带裁决 Q-1=env 门控可选、Q-2=本地独立仓、Q-3=fixtures 提取+锁测 |
| Design 门禁 | 2026-10-04 | 通过（详见 design-factoryforge-mcp.md 门禁表）：统一 tag bus 协议路径 + 15 工具面 |
| Tasks 门禁 | 2026-10-04 | 通过（详见 tasks-factoryforge-mcp.md 门禁表）：11 任务；执行模式=逐任务推进，后转夜间波次执行 |
| Execute 门禁 | 2026-10-05 | **通过（晨验）**：夜间执行 W1-W9 全波（overnight-execution 协议）+ 晨报验收批准。AC 全过：15 工具 / 113 tests 绿 / coverage 87% / 18 场景台账 18-18 / 种子 3-3=100%（目标 ≥80%）；待裁决 10 条按默认接受（2026-10-05）；夜间分支已 merge main |

## 1. 背景与目标

### 1.1 背景

主仓能力面已收官（北极星 98%），产品化主线（真实用户验证）进行中。本程序为**小步并行**的第二战线：把开源工厂仿真器 FactoryForge 1.1.1（MIT）的能力暴露为标准 MCP 工具面，延伸「AI 全自动」从机械设计域到控制/产线域。

**外部取证（2026-10-04 web search）**：市面无「物理仿真 + 评分」级别的工厂仿真 MCP server——现有工业 MCP 均为协议级零星项目（LobeHub Modbus TCP MCP、py-mcp-line PLC 读写、FestOS iec-61131-3 ST 生成）。factoryforge-mcp 为**先行者定位**。

**可行性关键证据**（源仓取证）：
- tag bus 协议 v0 文档化（`docs/tag-bus.md`）：JSON over WebSocket loopback:7411，引擎权威，**单 sidecar 座位**
- 场景即 JSON（`engine/templates/*.json`）：schema 薄（parts+position+properties），可程序化生成
- **18 个可评分场景全部在 Python sidecar 包内**（`factoryforge_sidecar/grading/scenes/`），headless 可跑，不依赖 Godot——`engine_stub` 提供无 Godot 仿真
- MIT 许可，sidecar 为纯 Python 包可 import 复用

### 1.2 目标

Wave 1（本 PRD 主体）：任何 MCP 客户端的 AI agent 可以——**生成/加载工厂场景 → 驱动仿真（tag 读写/强制/故障注入） → 运行 grader 取回 verdict + evidence**，全程无人值守、诚实失败。

Wave 2（粗粒度占位，届时独立定档）：CAD 侧布局导出（SW/aicad 设计参数 → scene JSON）+ 仿真反馈报告，打通「机械设计→控制仿真」数字孪生。

## 2. 用户故事（US 映射）

| US | 用户 | 当……时想要……以便…… | 映射 FR |
|---|---|---|---|
| US-001 | AI agent 集成者（小李） | agent 接到「为这条分拣线写控制逻辑并验证」的任务时，想要通过 MCP 工具面驱动 FactoryForge 仿真，以便交付带评分证据的控制方案 | FR-001~006 |
| US-002 | 机械工程师（老张） | 在 SW 里设计完产线部件/夹具时，想要把布局参数转成仿真场景验证产线协同，以便不等实物调试就发现设计问题 | FR-101/102（Wave 2） |
| US-003 | 开发线（ourselves） | 每晚无人值守迭代时，想要测试护栏与计数锁，以便能力扩张不破坏已交付面 | FR-007/008 |

## 3. 功能需求（FR）

> 三要素：输入 → 处理 → 输出。优先级 KANO 校准：P0=基本型（缺了不可用）/ P1=期望型 / P2=兴奋型与 Wave 2 占位。

### Wave 1

| ID | 优先级 | 需求 | 三要素 |
|---|---|---|---|
| FR-001 | P0 | 引擎会话管理 | 入参 mode（`headless`默认/`godot`）→ 启动 engine_stub 或探测 Godot 进程（`godot --path engine/`）+ tag bus 握手（hello/describe，校验 protocol 版本）→ 会话句柄 + 场景/驱动能力清单 |
| FR-002 | P0 | 场景枚举与加载 | 入参 scene_id 或内联 scene JSON → 校验（44 件 type 白名单、position/rotation 数值有限、properties schema）→ 写入 allowed_root 场景目录并加载，返回注册的 tag 清单 |
| FR-003 | P0 | tag 读 | 入参 tag_id 或过滤前缀 → 从 sidecar 缓存/总线读 → 值+类型+kind+时间戳 |
| FR-004 | P0 | tag 写 | 入参 [{tag_id, value}] 批量 → 值域校验（bit∈{0,1,true,false}；int 为 signed 32-bit；float 有限且非 NaN/Inf）→ 按协议部分失败返回 `bad_value` + 被拒清单，成功清单照常落 |
| FR-005 | P0 | grader 评分 | 入参 scene_id + 可选 seed/控制器配置 → 调 `factoryforge_sidecar` grading（headless）→ verdict（PASS/FAIL）+ exit code + evidence JSON；**FAIL 诚实返回归因，不重试掩盖** |
| FR-006 | P1 | 故障注入 | 入参 part_id + fault 类型 → 驱动仿真故障（皮带违令/缸中途卡死/阀保持开度）→ 故障态确认 + `<part>.fault` tag 置位证据。**标注 DESTRUCTIVE** |
| FR-007 | P1 | tag 强制/释放 | 入参 tag_id + typed value → force 写入并计数；release 单个/全部 → 强制状态清单。**标注 DESTRUCTIVE** |
| FR-008 | P0 | 安全与契约继承 | 所有工具返回统一结构（success/data/message/warning/error+稳定 code）；场景文件限于 allowed_root；数值有限校验；破坏性工具注解（对齐主仓红线） |
| FR-009 | P0 | 测试护栏 | mock tag bus 单测（无引擎实机全绿）；工具计数锁（数量断言钉死）；capabilities 与实现同步锁；CI（pytest + coverage ≥80%） |

### Wave 2 占位（届时独立 PRD 定档）

| ID | 优先级 | 需求 |
|---|---|---|
| FR-101 | P2 | CAD 布局导出器：SW/aicad 布局参数（件类型/位姿/属性）→ scene JSON 映射器 |
| FR-102 | P2 | 仿真反馈报告：节拍/阻塞/故障统计 → 设计改进建议（对接主仓交付包 report 结构） |

## 4. 场景三层（核心场景）

### 场景 A：agent 闭环评分（主）
1. agent 调 `factoryforge_engine_start(mode=headless)` → 握手成功，返回 18 graded + 19 template 场景清单。
2. 调 `factoryforge_scene_generate`（parts spec：belt+sensor+pusher+panel）→ 校验通过，加载，返回 tag 清单。
3. 写 `panel.start=true`、按反馈写 `div.divert` → 读 `remover.count` 验证。
4. 调 `factoryforge_grade_run(scene=sorting_by_height)` → **PASS + evidence**。

**备选**：场景 id 不存在 / 引擎未启动 → 稳定错误码 `scene_not_found` / `engine_not_started` + 下一步提示（先 start 或 list）。

**异常**：① godot 模式但 Godot 不在 PATH → 诚实失败 + 明示 headless 可用；② tag bus 座位被官方 sidecar 占用（`already_connected`）→ 返回占用状态与处置建议（停官方 sidecar 或等其退出），**不静默抢座**；③ 协议版本不匹配（上游升级）→ `protocol_mismatch` + 锁定版本说明。

### 场景 B：故障注入验证联锁（主）
agent 写 `conveyor.rotate=true` 运行 → `factoryforge_fault_inject(conveyor)` → belt 违令停转、`conveyor.fault=true`、beacon 亮 → agent 的控制逻辑读 fault 联锁停机 → `factoryforge_fault_clear` 恢复。
**备选**：part 不存在 → `part_not_found` + 场景内 part 清单。**异常**：注入时引擎崩溃 → 会话状态报告 + 自动收尸子进程。

### 场景 C：Wave 2 数字孪生（占位，粗）
SW 布局草图（6 条传送带坐标）→ FR-101 导出 scene JSON → 加载仿真 → 阻塞统计反馈 → 设计调整坐标重跑。

## 5. NFR（8 类）

| 类 | 要求 |
|---|---|
| 性能 | tag 读写 P95 <100ms（loopback WS）；单场景 headless grade <60s；18 场景全套 <10min |
| 可靠性 | sidecar 单座位：MCP server 独占管理连接生命周期；断线按协议重握手（hello/describe，epoch 重取）；引擎子进程崩溃自动收尸并诚实报错 |
| 安全 | 继承 loopback-only（无鉴权设计不得暴露网络）；场景文件 allowed_root 白名单；破坏性工具 DESTRUCTIVE 注解 |
| 可维护 | registry 域模块架构对齐主仓（新工具进域模块，不堆 server.py）；ruff/py_compile 门禁 |
| 兼容 | **锁 FactoryForge 1.1.1**（协议 v0 无稳定性承诺）：hello.protocol 探测，不匹配即 `protocol_mismatch` 诚实失败；Python 3.10+（对齐主仓） |
| 观测 | `FACTORYFORGE_MCP_LOG_PATH` 可配（对齐主仓日志惯例）；grade/fault 操作留审计行 |
| 合规 | MIT 消费：NOTICE 声明上游归属；**不 fork**（上游更新走版本升级路径，不改其源码） |
| 部署 | Wave 1 源码 + venv + pip install（不做 frozen——对齐「不见真实用户不立项」）；.mcp.json 样例随仓 |

## 6. 成功指标（基线 → 目标 → 测量）

| 指标 | 基线 | 目标（Wave 1 DoD） | 测量方式 |
|---|---|---|---|
| 种子任务闭环率（agent 自然语言→grader PASS，3-5 个种子任务） | 无（新仓） | ≥80% 首过 | 种子任务台账（对齐 aicad eval 惯例） |
| headless grade 全景 | 18 场景未在本仓测过 | 18/18 verdict 可得（PASS 或诚实 FAIL 均算达成） | grade 冒烟台账 |
| 契约测试 | 无 | 计数锁 + capabilities 锁 + mock 总线全绿 | CI（pytest） |
| 覆盖率 | 无 | ≥80%（CI 硬门，对齐主仓） | coverage |
| 主线不受损 | 主仓 594+107 / CI 绿 | 维持不变（小步并行裁决的验收面） | 主仓 CI |

## 7. Q 待决台账

| ID | 问题 | 影响 | 建议 | 状态 |
|---|---|---|---|---|
| Q-1 | Godot 实机模式 Wave 1 是否必须交付 | FR-001 范围 | ✅ 已裁决（2026-10-04 PRD 门禁）：env 门控可选路径 + headless 默认；实机 e2e 挂机验证一次收观察项 |
| Q-2 | 新仓归属（本地独立 git / 推 GitHub org） | 仓库与 CI | ✅ 已裁决（2026-10-04 PRD 门禁）：Wave 1 本地独立 git；公开与否留主线决策 |
| Q-3 | 44 件 schema 元数据来源（手写 vs 从 engine fixtures 提取） | FR-002 校验精度 | ✅ 已裁决（2026-10-04 PRD 门禁）：fixtures+templates 提取生成 + 测试锁定 |
| Q-4 | Wave 2 布局语义映射（SW 坐标系→FactoryForge 网格，含单位/朝向约定） | FR-101 可行性 | 届时独立定档，先在 roadmap 记依赖 | 已挂 roadmap |

## 8. 追溯矩阵

| FR | US | 场景 | 验证载体 |
|---|---|---|---|
| FR-001~005 | US-001 | A 主/备/异常 | mock 总线单测 + 种子任务台账 |
| FR-006/007 | US-001 | B 主/备/异常 | mock 单测 + DESTRUCTIVE 注解断言 |
| FR-008 | US-001/003 | 横切 | 契约测试（统一结构断言） |
| FR-009 | US-003 | 横切 | CI |
| FR-101/102 | US-002 | C（占位） | Wave 2 PRD |

## 9. 非目标（Out of Scope）

- ❌ 不 fork / 不修改 FactoryForge 源码（含 Godot C# 侧自定义件——44 内置件够 Wave 1/2 用）
- ❌ 不做 PLC 固件 / 真实控制器直连（那是 FactoryForge sidecar 自己的事；MCP 面向仿真域）
- ❌ 不动主仓 solidworks_mcp 任何代码与工具契约
- ❌ Wave 1 不做 frozen 打包 / 安装器（不见真实用户不立项）
- ❌ 不做云端/多机（继承 vision §8）

## 10. 风险与依赖

| 风险 | 概率/影响 | 缓解 |
|---|---|---|
| tag bus v0 上游漂移（1.1.2+ 破坏协议） | 中/高 | 锁 1.1.1；hello.protocol 探测；升级走显式版本任务 |
| engine_stub 物理 vs Godot Jolt 物理行为差异（grading plant 是简化模型） | 中/中 | 文档明示两模式边界；实机 e2e 定谳（挂机窗口） |
| 单座位与官方 sidecar 冲突 | 低/中 | FR-001 会话管理独占；冲突诚实报错（场景 A 异常③） |
| 主线工时被挤占 | 中/高 | 裁决③已锁：夜间 N 系列节奏、不占门面改造/种子用户工时；主线 CI 为共享验收面（§6 末行） |

## 11. 自检清单（prd-full 12 项）

- [x] 定档声明头部 + 门禁裁决区
- [x] 背景含真实取证数据（源仓接缝 + 外部竞品 web search）
- [x] US 映射（每条 US ≥1 FR）
- [x] FR 原子·可测·三要素·优先级（KANO 校准，P0 占比 6/9 合理）
- [x] 场景三层（主/备选/异常）覆盖 P0 FR
- [x] AC 可观察（成功指标表带测量方式）
- [x] NFR 8 类齐
- [x] Q 待决台账（4 项集中，非散标）
- [x] 追溯矩阵 FR↔US↔场景↔验证
- [x] 非目标显式
- [x] 风险带缓解
- [x] 基线数字与探索取证同源（18 场景/44 件/协议 v0/端口 7411 均出源仓实测）
