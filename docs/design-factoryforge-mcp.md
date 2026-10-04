# Design — factoryforge-mcp 架构设计

> **版本**：v1.0（2026-10-04）
> **定档**：🔴 L3 · Phase 2 产物
> **关联**：`docs/prd-factoryforge-mcp.md`（FR-001~009）· `docs/roadmap-factoryforge-integration.md`
> **上游取证补充**（2026-10-04）：EngineStub 为**通用**引擎基类（吃任意 scene 对象，serves exactly one sidecar）；grader 建于其上（`grading.core.GradedEngine` 子类）→ **18 场景 headless 进程内可跑且 tag 可交互**；sidecar 包硬依赖仅 `websockets>=12`，**requires-python ≥3.11**（新仓独立 venv，不影响主仓 3.10）；`TagBusClient` 现成；grading registry 提供 `rubrics()/references()/default_scene()`。

## ✅ 门禁裁决记录

| 门禁 | 日期 | 结论 |
|---|---|---|
| Design 门禁 | 2026-10-04 | 通过：统一 tag bus 协议路径 + 15 工具面确认；新仓落点 `E:\SolidWorks 2026\SolidWorksMCP\factoryforge-mcp\`；进 Phase 3 |

## §1 架构总览

### 1.1 核心架构决策：统一 tag bus 协议路径

**两种引擎模式共享同一条客户端代码路径**（MCP server 永远以 sidecar 角色经 `ws://127.0.0.1:7411/tagbus` 交互）：

```
MCP 客户端（Claude / aicad agent / 任意 MCP host）
   │ stdio (JSON-RPC)
   ▼
factoryforge-mcp server（FastMCP，asyncio 单循环）
   ├── registry/（域模块，对齐主仓 N14 架构）
   │   ├── base.py      共享类型 / 统一返回结构 / 错误码 / DESTRUCTIVE 注解
   │   ├── engine.py    FR-001  engine_start/stop/status
   │   ├── scenes.py    FR-002  scenes_list / scene_load / scene_generate
   │   ├── tags.py      FR-003/004/007  tags_list/read/write · tag_force/release
   │   ├── grading.py   FR-005  grade_run
   │   └── fault.py     FR-006  fault_inject/clear
   ├── core/
   │   ├── session.py       EngineSession 状态机（stopped→starting→running→poisoned）
   │   ├── bus.py           TagBusClient 封装：握手/epoch/重连/批量写残差处理
   │   ├── headless.py      headless 引擎宿主：同循环后台 task 跑 EngineStub/场景
   │   ├── godot.py         godot 引擎宿主：子进程 spawn + 端口等待 + stderr 监控
   │   └── part_schema.py   44 件 schema 校验（生成物 part_schema.json + 锁测）
   └── 上游依赖：factoryforge-sidecar==1.1.1（本地路径 editable install）

模式 A：headless（默认）
  server 同进程 asyncio task 内跑 EngineStub(scene) ──loopback WS── TagBusClient
  （grader 例外：grading 直接进程内调 GradedEngine，不走 WS——见 §1.3）

模式 B：godot（env 门控 FACTORYFORGE_MCP_ENGINE=godot）
  spawn `godot --path <FF>/engine/` ──WS:7411── TagBusClient（同一条 bus.py）
```

**为什么 headless 也走 WS 而不内存直调**：单一代码路径 = 协议语义（epoch/bad_value/already_connected/重握手）只实现一次、测一次；避免内存捷径与协议路径行为分叉。loopback 往返 ~1ms 级，相对 P95 <100ms 预算可忽略。

### 1.2 数据流（headless 交互闭环）

AI → `tags_write(panel.start=true)` → registry/tags → bus.py（值域校验→帧编码）→ WS → EngineStub 权威表 → scene tick（物理/工艺）→ delta 更新 → bus.py 缓存 → AI 读 `remover.count` 验证。

### 1.3 grader 通路（唯一不走 WS 的能力）

`grade_run` 进程内直接调用 grading registry + `GradedEngine`（其本身是 EngineStub 子类，自带场景与 rubric）。**理由**：grader 契约是「verdict+exit code+evidence」，进程内调用保 evidence 结构完整（JSON 对象而非 CLI stdout 解析）；且 18 场景的 plant 实现只在 grading 包内。**边界如实声明**：grade 的仿真来源=grading plant（简化物理），与 godot Jolt 物理结论可能不同——evidence 中标注 `engine=grading-plant`。

### 1.4 关键时序：engine_start（godot 模式）

```
tool(engine_start) → session.state=starting
  → core/godot.py: 探测 godot 可执行（PATH + 常见安装根，参照上游 run.py 搜索策略）
     ├─ 未找到 → error(godot_not_found) + message 附 headless 可用提示 → state=stopped
  → spawn 子进程（stdout/stderr pipe）→ 轮询 7411 监听（超时 15s，上游 connect 同参）
     ├─ 超时/进程退出 → error(engine_start_failed, 附 stderr 尾部) → 收尸 → state=stopped
  → bus.py: WS connect → 收 hello（校验 protocol 版本，不符→protocol_mismatch）
     ├─ already_connected（官方 sidecar 在座）→ error(seat_occupied) + 处置建议 → state=stopped
  → describe（epoch++，全量 tag 表）→ 缓存 → state=running → 返回会话信息+能力清单
```

headless 模式同构，仅引擎宿主换为 `core/headless.py`（同循环 task，无子进程，冷启动 <2s）。

### 1.5 会话状态机

`stopped → starting → running →（总线断连/协议异常）→ poisoned`；`engine_stop` 任何态可调（收尸+断连+回 stopped）；poisoned 态下所有工具返回稳定错误 `engine_poisoned`，唯一出路是 stop→start 重建（比主仓 COM 毒化轻：无需退进程，会话对象可重建）。

## §2 方案评估（含四视角交叉评审）

### 2.1 备选对比

| 方案 | 描述 | 复杂度 | 性能 | 可维护 | 风险 | 结论 |
|---|---|---|---|---|---|---|
| **A. 统一 tag bus 协议路径**（本设计） | 两模式同走 WS；grader 进程内 | 中 | 好（loopback ~1ms） | 好（单路径单测面） | 上游协议 v0 漂移→锁 1.1.1+探测 | ✅ 选定 |
| B. 纯 CLI 包装 | 一切经 `factoryforge-sidecar` 子进程 | 低 | 差（每次冷启 ~300ms+，交互闭环不可用；evidence 靠 stdout 解析） | 中 | 文本契约脆弱 | 否决 |
| C. 双路径 | headless 内存直调 + godot 走 WS | 高 | headless 最快 | 差（协议语义复刻两遍，测试面翻倍） | 模式间行为分叉 | 否决 |

### 2.2 四视角交叉评审纪要（2026-10-04）

- **架构**：A 的单路径是最大胜因；registry 域模块对齐主仓 N14，认知成本最低。风险=EngineStub 作为 server 与 TagBusClient 同循环跑（自连）——asyncio 无阻塞点，可行，但需一个冒烟测试钉死（无死锁/自连成功）。
- **安全**：loopback 127.0.0.1 **硬编码不可配**（继承上游「不得有理由暴露网络」）；场景文件 allowed_root 白名单；写侧工具（write/force/fault）全标 DESTRUCTIVE。
- **性能**：headless 自连 WS 往返预估 <10ms，预算内；grade 同步等待上限 300s（上游单场景 <60s）；18 场景全套 <10min 与 PRD 一致。
- **存量**：零接触主仓（独立仓独立 venv）；Python 3.11 边界由新仓 venv 隔离；上游 editable install 锁路径锁版本。

## §3 接口契约（MCP 工具面，15 个）

统一返回结构对齐主仓：`{success, data, message, warning, error:{code, details?}}`。

| 工具 | 入参（摘） | 输出（摘） | FR | 注解 |
|---|---|---|---|---|
| factoryforge_engine_start | mode: headless\|godot（默认 headless） | 会话信息+场景/驱动能力清单 | 001 | idempotent（running 再调→warning+现态） |
| factoryforge_engine_stop | — | 清理确认 | 001 | 收尸保证 |
| factoryforge_engine_status | — | state/epoch/mode/forced 计数 | 001 | |
| factoryforge_scenes_list | scope: templates\|graded\|all | 场景清单（id+件数+tag 数） | 002 | |
| factoryforge_scene_load | scene_id 或 scene_json | 加载确认+tag 清单 | 002 | headless 仅限有 Python 实现的场景（18 graded+sorting，如实清单）；godot=任意 JSON |
| factoryforge_scene_generate | parts_spec[{id,type,position,rotation,properties}] | 校验报告+落盘路径 | 002 | 44 件白名单+数值有限校验；交互可用性按模式标注 |
| factoryforge_tags_list | prefix? | tag 表（id/type/kind/当前值/forced 标记） | 003 | |
| factoryforge_tags_read | ids[] | 值清单 | 003 | |
| factoryforge_tags_write | writes[{id,value}] | 成功清单+拒绝清单（bad_value） | 004 | **DESTRUCTIVE**；部分失败语义按协议 |
| factoryforge_tag_force | id, value | 强制确认+forced 计数 | 007 | **DESTRUCTIVE** |
| factoryforge_tag_release | id 或 all | 释放确认 | 007 | |
| factoryforge_fault_inject | part_id, fault | 故障态证据（fault tag 置位） | 006 | **DESTRUCTIVE**；godot 模式=⚠Fault 工具协议化，headless 按 plant 支持 |
| factoryforge_fault_clear | part_id | 恢复确认 | 006 | |
| factoryforge_grade_run | scene_id, seed?, reference? | verdict(PASS/FAIL)+exit_code+evidence | 005 | **verdict=FAIL 是正常返回不是 error** |
| factoryforge_design_capabilities | — | 单位/边界/模式差异说明 | 008 | 对齐主仓同名城工具惯例 |

计数锁初值 **15**，钉入 `tests/test_infrastructure.py`（对齐主仓惯例：改工具数先改断言）。

## §4 影响分析

- **新仓落点**：`E:\SolidWorks 2026\SolidWorksMCP\factoryforge-mcp\`（工作区根下与 SolidWorksMCP/ 平级；独立 git init，本地仓）。
- **文件清单（骨架 ~18 文件）**：`server.py`（门面 ~150 行）+ `registry/`（6 域模块）+ `core/`（5 模块）+ `tests/`（基础设施/契约/总线 mock/场景/评分 ~6 文件）+ `tools/extract_part_schema.py` + `pyproject.toml` + `README.md` + `NOTICE`（MIT 归属）+ `.mcp.json` 样例。
- **向后兼容**：无存量（新仓）；主仓/aicad 零改动。
- **迁移路径**：无（绿地）。上游升级路径：换 editable install 指向 → 跑 protocol 探测测试 → 显式版本任务，不追新。

## §5 数据模型

```python
SceneSpec    {name:str, version:str, parts:[PartSpec]}
PartSpec     {id:str, type:str(44白名单), position:[float×3], rotation:[float×3], properties:{str:str}}
TagRef       {id:"<part>.<name>", name:str, type:"bit"|"int"|"float", kind:"input"|"output", value, forced:bool}
EngineSession{mode, state, epoch:int, controller, tags_cache:dict, forced:set, started_at}
GradeResult  {scene, verdict:"PASS"|"FAIL", exit_code:int, evidence:dict, reference_kind, seed, engine:"grading-plant"}
```

值域契约（继承协议 v0）：bit∈{0,1,true,false}；int=signed 32-bit；float 有限非 NaN/Inf——在 `bus.py` 写路径统一前校验，越界按帧语义拒绝并归入 bad_value 清单。

## §6 错误码表（稳定 code）

| code | 触发 | message 要求 |
|---|---|---|
| engine_not_started | running 前调工具 | 附「先 engine_start」提示 |
| engine_already_running | start 重复 | 附现态（warning 级，非 error） |
| godot_not_found | godot 模式探测失败 | 附 headless 可用提示 |
| engine_start_failed | 端口等待超时/进程退出 | 附 stderr 尾部 |
| protocol_mismatch | hello.protocol ≠ 预期 | 附锁定版本说明 |
| seat_occupied | already_connected | 附处置建议（停官方 sidecar） |
| scene_not_found / scene_invalid | id 不存在 / schema 违例 | 后者附逐件违例明细 |
| tag_not_found / bad_value | id 不存在 / 值域拒绝 | bad_value 附被拒清单 |
| part_not_found | 故障注入目标不存在 | 附场景 part 清单 |
| grade_execution_failed | grader 执行异常（区别于 verdict FAIL） | 附异常摘要；**verdict FAIL 走正常返回** |
| engine_poisoned | 会话毒化态 | 附「engine_stop 后重启」提示 |

## §7 并发与生命周期

- **线程模型**：asyncio 单循环（FastMCP stdio 原生）；headless 引擎 task 同循环（自连 WS，无跨线程共享）；godot 子进程 stderr 用 `create_subprocess_exec` 异步管道监控。
- **毒化**：bus 断连/协议解析异常 → session=poisoned（一次即入，不重试掩盖）；可经 stop→start 重建（不退进程——与主仓 COM 毒化退程策略不同，因会话对象轻量可重建；差异在 README 注明）。
- **长任务**：grade_run 同步等待（上限 300s 超时，超时=grade_execution_failed+子任务取消）；Wave 1 不做异步任务句柄（P95 单场景 <60s，MCP 调用可承受）。

## §8 性能设计

| 点 | 预算 | 验证 |
|---|---|---|
| tags_read/write 往返 | P95 <100ms（headless 实测预期 <10ms） | bench 冒烟任务 |
| headless 冷启动 | <2s（无子进程） | 契约测试计时 |
| godot 冷启动 | <20s（含引擎加载，15s 端口等待上限内） | e2e 挂机 |
| grade 单场景 | <60s（上游参照） | 18 场景全景台账 |

## §9 安全设计

- bind 127.0.0.1:7411 **硬编码**（无 env 出口——继承上游红线「不得有理由暴露到网络」）。
- `FACTORYFORGE_MCP_ALLOWED_ROOT` 场景文件白名单（解析 ..／junction，对齐主仓安全模型）。
- DESTRUCTIVE 注解：tags_write / tag_force / fault_inject（写侧全覆盖）。
- 审计行：grade/fault/force 各留一行结构化日志（log path 可配 `FACTORYFORGE_MCP_LOG_PATH`）。

## §10 Design 遗留探针（转 Tasks 首批，不阻塞门禁）

| ID | 探针 | 影响 | 兜底 |
|---|---|---|---|
| P-1 | godot CLI 场景参数化（能否 `--scene` 指定加载） | godot 模式 scene_load 实现 | 若 CLI 不支持：godot 模式限默认场景+UI 手动加载，边界如实声明 |
| P-2 | fixtures 提取器首跑（44 件 schema 完整性） | FR-002 校验 | 提取不全的件→白名单缺项如实列出 |
| P-3 | GradedEngine 交互驱动 API 取证（grading plant 的 tag 读写通道与 fault 支持） | FR-005/006 headless 交互面 | plant 不支持的 fault 类型→工具按场景能力声明 |

## §11 Q 接续

无新增决策级待确认项（P-1~P-3 为执行级探针，有兜底路径，不进 Q 台账）。
