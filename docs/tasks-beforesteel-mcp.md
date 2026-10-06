# Tasks — factoryforge-mcp Wave 1 实施任务列表

> **版本**：v1.0（2026-10-04）
> **定档**：🔴 L3 · Phase 3 产物（tasks-full）
> **关联**：`docs/prd-beforesteel-mcp.md`（FR/成功指标）· `docs/design-beforesteel-mcp.md`（§3 工具面/§10 探针）
> **执行节奏**：对齐主仓 N 系列惯例——每晚 1-2 任务、TDD、不自动 commit、总览表状态实时翻转

## ✅ 门禁裁决记录

| 门禁 | 日期 | 结论 |
|---|---|---|
| Tasks 门禁 | 2026-10-04 | 通过：11 任务确认；执行模式=逐任务推进（用户选「开始执行 T1」） |

## 任务总览

| ID | 任务 | 依赖 | 估算 | 风险 | 状态 |
|---|---|---|---|---|---|
| T1 | 仓骨架 + 契约基座 + 上游安装 | — | M | 低 | `[x]` 2026-10-04：RED→GREEN（4 tests）；py_compile 绿；stdio 冒烟 server=factoryforge/tools=0；上游 editable 装（18 graded 实证）；git init 本地仓（未 commit，待批） |
| T2 | 【探针 P-2】44 件 schema 提取器 + 锁测 | T1 | S | 低 | `[x]` 2026-10-04：P-2 定谳=fixtures 是协议用例非件 schema，**PartCatalog.cs 为权威源**（44 件/7 组正则提取）+ templates 属性聚合（43/44 件带实测属性；18 场景文件——README「19 模板」含 built-in sorting 场景不在目录内，基线修正为 18）；11 tests 绿；--check 幂等过；未 commit（待批） |
| T3 | core/bus：TagBusClient 封装 + mock 总线测试 | T1 | M | **中**（协议细节） | `[x]` 2026-10-04：BusBridge（毒化不重连——与上游 PLC sidecar 的 FF-03 存活策略相反，MCP 会话语义）；批量写残差（tag_not_found/tag_is_input/bad_value 预校验，镜像 Tag.coerce）；start 等到**首个 describe** 而非 hello（空表假阴性修复）；22 tests 绿（真 EngineStub+sorting 联测）；bus 90%/总 84%；**websockets 17.2 兼容定谳=OK**（观察项关闭）；新增错误码 tag_is_input；未 commit（待批） |
| T4 | core/session + registry/engine（headless 宿主+自连冒烟） | T3 | M | **中**（自连死锁） | `[x]` 2026-10-05（夜 W1）：29 tests（+7）；计数 0→3 钉名；自连冒烟 start→写读→stop 全链过+毒化重建用例；红阶段抓到 start 失败未回 stopped 真 bug 并修 |
| T5 | registry/scenes（list/load/generate） | T2,T4 | M | 低 | `[x]` 2026-10-05（夜 W2）：46 tests（+17）；计数 6；scene_invalid 逐条明细用例过；coverage 88%；定谳 sorting-by-height ∈ rubrics 18 场景（headless 18 非 19，all=19）、builtin 遮蔽行为 |
| T6 | registry/tags（read/write/force/release，DESTRUCTIVE） | T4 | M | 低 | `[x]` 2026-10-05（夜 W3）：67 tests（+21）；计数 11；write/force=DESTRUCTIVE、release=IDEMPOTENT_WRITE 注解断言过；批量部分失败残差清单落地 |
| T7 | registry/grading（grade_run）+ 18 场景全景台账 | T4 | M | **中**（plant API） | `[x]` 2026-10-05（夜 W4）：77 tests（+10）；计数 13；**全景台账 18/18 PASS（lockstep 11.3s）** 落 output/grade-panorama.{md,json}；P-3 定谳：故障=考官 Script 置 `<part>.fault`，无公共注入 API |
| T8 |【探针 P-3】registry/fault（inject/clear） | T6 | S | 低 | `[x]` 2026-10-05（夜 W5）：87 tests（+10）；**计数 15 全集达成**；故障语义 part 级分型（9 个 physics-affecting tag 源码定谳，其余 visible-only/unknown）；能力面从活 tag 表推导 |
| T9 |【探针 P-1】core/godot + env 门控接线 | T4 | M | **高**（CLI 未知） | `[x]` 2026-10-05（夜 W6）：109 tests（+22）；coverage 87%；**P-1 定谳：CLI 场景参数化成立**（Main.cs `--scene=`/`--bus-port=`，行号在案）——godot 真实现非兜底；本机无 Godot，实机 e2e 留晨间观察项 |
| T10 | 测试收口：全集守护断言 + coverage≥80 + 契约审计 | T1-T9 | S | 低 | `[x]` 2026-10-05（夜 W7）：111 tests（+2）；全集守护相等断言+假名自证（FB-016）；15 工具统一结构真调用审计全过；coverage 87% 维持（fail_under=80） |
| T11 | 集成验证：种子任务闭环 ≥80% + DoD 核验 + README 收口 | T10 | M | **中**（AI 行为） | `[x]` 2026-10-05（夜 W8）：**种子首过 3/3=100%（目标 ≥80%，87 断言）**；113 tests；DoD 五项核验全过；README 收口+版本 0.2.0；台账 output/seed-tasks.md（append-only 首过史） |

> **完成摘要（2026-10-05）**：T4-T11 于 2026-10-04/05 夜间在分支 `night/wave1-20261004` 执行完成（W1-W8 各一检查点 commit，W9 尾波全量回归 113 绿+coverage 87%+stdio 冒烟 15 工具+种子复跑 3/3）；关键数字：**15 工具全注册 / pytest 113 passed / coverage 87%（≥80 硬门）/ 18 场景评分台账 18-18 / 种子闭环 3-3=100%**；主仓夜间零触碰（仅本白名单 docs 工作树回填，未 commit）。待晨验：夜间分支 merge 裁决 + 偏差记录复核（见夜间仓 docs/night-brief-factoryforge-mcp.md §7 与 docs/morning-report-20261005.md）。

## 依赖图

```
T1 ──→ T2（schema）
 │
 └──→ T3（bus）──→ T4（engine/session）──→ T5（scenes ← T2）
                    │                ├─→ T6（tags）──→ T8（fault ← P-3）
                    │                ├─→ T7（grading）
                    │                └─→ T9（godot ← P-1）
                                          T1..T9 ──→ T10（收口）──→ T11（集成验证）
```

- **可并行对**（不同文件，满足并行安全铁则）：T5∥T6∥T7∥T8∥T9（均只读 T4 接口、各写各的 registry 域模块）；T2∥T3。
- 实际执行按夜间单会话串行（N 系列惯例），并行标记仅供多会话窗口参考。

## 任务明细（输入→动作→验证 HOW）

### T1 仓骨架 + 契约基座
- 建 `E:\SolidWorks 2026\SolidWorksMCP\factoryforge-mcp\`：`pyproject.toml`（deps: `mcp`、`factoryforge-sidecar @ file:本地路径`、dev: pytest/pytest-asyncio/coverage）、`server.py` 门面（FastMCP 实例 + stdio 入口）、`registry/base.py`（统一返回结构/错误码表 §6/DESTRUCTIVE 注解助手）、`NOTICE`（MIT 归属 factoryforge 上游）、`.mcp.json` 样例、`README.md` 骨架；`git init` 本地仓。
- venv（Python ≥3.11）+ editable 安装上游 sidecar。
- **验证**：`python -m py_compile` 全绿；`python -m pytest` 空集绿；`tests/test_infrastructure.py` 骨架立计数锁断言=**0**（红→绿纪律：先断言后实现）；server 可 stdio 握手（冒烟脚本）。
- 守护行：`test_tool_count==0`。

### T2【P-2】schema 提取器
- `tools/extract_part_schema.py`：扫上游 `engine/templates/*.json` + `engine/fixtures/`（P-2 探针：验证 fixtures 是否含全件 schema；不全→白名单缺项如实列）→ 生成 `core/part_schema.json`（入库）。
- `tests/test_part_schema.py`：件数断言、每件 type/必填属性断言（锁测防上游漂移）。
- **验证**：提取器 idempotent（重跑 diff=0）；pytest 绿。守护行 +1（件数）。

### T3 core/bus
- `TagBusClient` 封装：connect→hello（protocol 版本校验→`protocol_mismatch`）→describe（epoch/tag 缓存）→write（值域前校验：bit/int32/float 有限；部分失败残差=bad_value 清单）→订阅 delta 更新缓存→断连回调（→session 毒化）。
- `tests/test_bus.py`：**mock 总线**（本地起真 `EngineStub`+sorting_scene 即为最真实的 mock——上游包自带，CI 无需 Godot）+ 故障注入用例（错帧/bad_value/断连）。
- **验证**：pytest 绿（握手/读写/残差/毒化四组用例）。守护行 +1。

### T4 core/session + registry/engine
- EngineSession 状态机（§1.5）；`core/headless.py`：同循环 task 跑 `EngineStub(scene)`（sorting 默认）+ 自连 TagBusClient。
- `registry/engine.py`：`engine_start(mode)`/`engine_stop`/`engine_status` 三工具（idempotent、收尸保证、能力清单返回）。
- **验证**：**自连冒烟**（防死锁专项：start→读写一 tag→stop 全链 pytest-asyncio）；状态机全迁移用例；计数锁断言 0→**3**。

### T5 registry/scenes
- `scenes_list`（聚合 templates JSON 清单 + grading registry `rubrics()`）；`scene_load`（headless 限 Python 实现场景——18 graded+sorting，能力清单如实；内联 JSON 同校验）；`scene_generate`（PartSpec→白名单/数值有限校验→落盘 allowed_root）。
- **验证**：校验违例逐条明细用例（scene_invalid details）；load 后 tag 清单非空；计数锁 3→**6**。

### T6 registry/tags
- `tags_list/read/write` + `tag_force/tag_release`：值域校验、部分失败语义、forced 集合与计数、DESTRUCTIVE 注解（write/force）。
- **验证**：bit=2 拒绝、int 溢出拒绝、NaN 拒绝、批量部分失败残差清单；注解断言（titledestructive hint）；计数锁 6→**11**。

### T7 registry/grading
- `grade_run`：进程内调 grading registry（`references()/reference_for()`）→ GradeResult（verdict/exit_code/evidence/engine=grading-plant 标注）；verdict FAIL=正常返回；执行异常→`grade_execution_failed`；300s 超时取消。
- 【P-3 探针并入】：取证 GradedEngine 交互驱动通道（供 T8 fault 复用结论）。
- **验证**：18 场景全景台账（18/18 verdict 可得，PASS/FAIL 均记）落 `output/grade-panorama.md`；单测 mock grading；计数锁 11→**13**（grade_run + design_capabilities 横切）。

### T8【P-3 落地】registry/fault
- `fault_inject/fault_clear`：按 P-3 结论实现（plant 支持的故障类型按场景能力声明；不支持→稳定错误+能力边界，不硬凑）；DESTRUCTIVE。
- **验证**：sorting 场景 fault 注入→`<part>.fault` 置位证据用例；能力边界用例；计数锁 13→**15**。

### T9【P-1】core/godot
- 探针先行：godot CLI 场景参数化取证（`godot --path engine/ -- --scene?`）。**兜底**：CLI 不支持→godot 模式限默认场景+UI 手动加载，README/工具 description 如实声明。
- `core/godot.py`：探测（PATH+安装根，参照上游 run.py）→spawn→端口轮询 15s→stderr 监控；`godot_not_found/seat_occupied` 路径。
- **验证**：无 godot 环境→`godot_not_found` 用例绿；有 godot 挂机窗口 e2e 一次（观察项收口，对齐 D-4 裁决）。

### T10 测试收口（Task N-1）
- 守护全集翻新：计数锁 15 的**全集相等断言**（枚举 registry 全工具 vs 断言集合——FB-016：守护抓守护作者自身 bug）；统一返回结构全工具审计测试；capabilities 与实现同步锁。
- coverage ≥80% 硬门（pyproject fail_under，对齐主仓）。
- **验证**：`pytest --cov` ≥80% 全绿。

### T11 集成验证（Task N）
- 种子任务 3-5 个（场景 A 闭环评分 / 场景 B 故障联锁，见 PRD §4），经真实 MCP 客户端（或 stdio 驱动脚本）跑 agent 闭环，首过率 ≥80% 记台账。
- README 收口（Quickstart/两模式边界/毒化差异说明）；roadmap §7 快照回写 + DoD 先验。
- **验证**：PRD §6 成功指标五行全过；DoD 勾选。

## 跨阶段一致性矩阵

| FR | 任务 | AC/指标 | 任务 |
|---|---|---|---|
| FR-001 | T4/T9 | 种子闭环率 ≥80% | T11 |
| FR-002 | T2/T5 | 18/18 grade verdict | T7/T11 |
| FR-003/004 | T6 | 计数锁+capabilities 锁全绿 | T10 |
| FR-005 | T7 | coverage ≥80% | T10 |
| FR-006 | T8 | 主仓 CI 维持绿 | 零改动声明（T11 复核 git -C 主仓 status） |
| FR-007 | T6/T10 | DoD 清单 | T11 |
| FR-008 | T1/T10 | | |
| FR-009 | T1-T10 横切 | | |
| Design §10 探针 | P-1→T9 / P-2→T2 / P-3→T7+T8 | | |

## 风险任务盯防

- **T3（协议细节）**：mock 用真 EngineStub 而非手写假 server——上游即参照实现，杜绝自造协议。
- **T4（自连死锁）**：冒烟测试先行（红→绿），任何 await 饥饿即停。
- **T9（CLI 未知，高）**：探针兜底已预置，不强凑。
