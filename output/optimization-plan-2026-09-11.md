# AI 驱动 3D 机械图全自动绘制——优化改进规划（第十一期：用户解锁冲刺波）

> **生成**：2026-09-11 结构化会话（蓝本：PM 回顾裁决——能力面收官，剩余杠杆全在用户侧；用户指令「今晚 12 点后开展实机三合一（挂机）」）
> **主题**：触发驱动冲刺——用户动作（SW 窗口/宏/批准/上游）→ AI 批量兑现；北极星 90% → 95% 冲线
> **用途**：供每日 02:30 自动实施任务读取执行；亦供人工实施参考（AGENTS.md 契约：自动任务读本文件=最新日期计划）
> **承接**：第十期 `output/optimization-plan-2026-09-10-3.md` N52-N54/N56 ✅+残留裁决 ✅（终态 45/50=90%）；**N55 等 U9 续挂**。测试基线继承（主仓 565+106/80 工具；aicad 741 not-perf）。
> **收官对账 2026-09-19**：双仓离线基线复验全绿（主仓 566+106；aicad 全集 763/not-perf 745+18 deselected）+N60 补推部分回填 ✅（见 §6）；N57/N59/U10/U11 终态维持（北极星 98%）。剩余=N58 挂 U9（录宏）、N60 CI re-run 挂 U8、U4——**AI 侧可做项清零，全部杠杆在用户侧**。

---

## 1. 事实基线（2026-09-11 立项取证）

| 事实 | 状态 | 意义 |
|---|---|---|
| 北极星 | **46/50=92%**（U10 后终态）；95% 差 2 任务（装配堆叠=plan 强档域） | N59 冲线 |
| 待清观察项 | ①N52 GTOL 实机 e2e（NewGtol 定谳）②N48/49 frozen COM 实机 ③N54 CSG SW roundtrip | N57 一晚清（互独立） |
| 装配堆叠败 | b7 系列+mate_shaft_stack+stepped_sleeve_pair=plan 强档域 | N59（等上游第二家） |
| two_step_bore_plate | 稳定 24504 超窗 2.1%（窗口边际） | **U10 批准即 +1（92%）** |
| 四族 BLOCKED | **勘误 2026-09-12**：mirror 已 N9 原生解锁（51bd1c3）+当晚实机复验 PASS（切特征×右视基准面→「镜向1」）；真正待宏=pattern/rib/combine/AutoBalloon | N58（等 U9） |
| github pending | aicad 061402c/53d8917+主仓 3d1d09a（网络窗口） | 窗口恢复即补推 |

## 2. 任务进度总览

| ID | 优先级 | 标题 | 仓 | 依赖 | 预估 | 状态 | 完成日期 |
|---|---|---|---|---|---|---|---|
| N57 | P0 | **实机三合一**（GTOL e2e / frozen COM / CSG SW roundtrip） | 主 | SW 窗口（用户挂机） | 1晚 | `[x]` 2026-09-12（**三批全 PASS**：A=GTOL 实机可用——NewGtol 必须 typed IDrawingDoc 路径（dynamic MEMBERNOTFOUND），生产 fallback 已修+测试钉死，全链 e2e 框格落图 PDF 45KB；B=frozen exe 真附着 2.7s 全链 bbox [60,40,10] 精确；C=双引擎 rel diff **1.75e-16** 逐位一致+**顺带挖修 N54 version bug**（aicad 导出端硬编码 v1，v2 op 永远过不了主仓校验——按 op 代级推导，+2 测）；主仓 566+106/aicad 745 not-perf 绿） | 2026-09-12 |
| N58 | P1 | G4 宏转录管线首跑（用户交 .swp 即开工该族；~~mirror 优先~~→**勘误 09-12：mirror 已解，改四族 pattern/rib/combine/AutoBalloon 任一优先**） | 主 | U9 | 1晚/族 | `[ ]` 条件 | |
| N59 | P0 | plan 强档路由对比评测 → 装配堆叠回收 → **95% 冲线** | ai | 上游第二家 provider | 1晚 | `[x]` ✅ 2026-09-13 终态 **48/50=96% 北极星达成**（双会话并集：连跑 47+泵座复跑转绿；双臂证伪路由增益=归因漂移；唯二稳定败=b7_flange_bolts/stepped_sleeve_pair；详见 §5+报告 §9-§10） | 2026-09-13 |
| N60 | P2 | github pending 补推 + U8 后双仓 CI re-run 收口 | — | 网络窗口/U8 | 0.1晚 | `[ ]` 部分：**补推 ✅ 2026-09-13**（09-19 对账回填：ls-remote github main==本地 f127434、aicad b8536d3 0/0 同步）；CI re-run 仍挂 U8 | |

### 2.4 用户动作清单（顺承）

| ID | 动作 | 状态 |
|---|---|---|
| **U4** | coderabbit auth login | ⏳ |
| **U8** | Billing 失败发票清算（页无欠款仍拦则工单） | 🔴 |
| **U9** | 录宏目标勘误（09-12）：mirror 已解免录；**改录 pattern/rib/combine/AutoBalloon 任一族** ~30min（如需 boss 级镜像原生亦可录 mirror 宏）→ .swp 路径一句话通知 | ⏳ 条件 |
| **U11** | hex_nut_plate 措辞消歧 | ✅ 2026-09-13 用户批准并执行：「对顶距40」→「外接圆直径40（顶点距40、对边距34.64）」三重标注（断言/mock 零动）；离线 50/50 维持+live 复跑 PASS——**终态 49/50 = 98%**（aicad b8536d3；报告 §10.4；全套 745 绿）；唯二稳定败=b7_flange_bolts/stepped_sleeve_pair（长尾不强凑） |
| **U10（新增）** | 批准 two_step_bore_plate 体积窗口 [21000,24000]→[21000,24800] → +1 任务=92% | ✅ 2026-09-12 批准并执行：改窗+离线 50/50 维持+live 复跑 PASS——**终态 46/50=92%**（aicad e4c7b92）；报告 §8.5 补记 |

---

## 3. N57 实机三合一（P0，今晚执行详案）

**启动机制**：定时任务 fireAt 2026-09-12T00:05——自包含 prompt：检 SW 进程→按本节顺序执行→回填本表。
**红线**：探针随手 `CloseAllDocuments(True)`；全部文件在 allowed_root 下；探针先行（每批次先最小观测再全链）；每批独立定谳互不阻塞。

### 批次 A：GTOL 实机 e2e（N52 观察项）

- [x] A1 **探针** `tools/probe_n52_gtol.py`（已预置）：建图纸→`NewGtol()` 返回值观测（**None=AutoBalloon 同族 BLOCKED 定谳**）→ SetFrameSymbols2(flatness)/SetFrameValues2/SetPosition → GetFrameCount 判据 → 清理。
- [x] A2 A1 通过→MCP 工具链 e2e：connect→part_new+create_box→drawing_create_from_part→`drawing_insert_gtol`(flatness 0.05)→export_pdf；判据=GetFrameCount==1+PDF %PDF 头+体积正常。A1 BLOCKED→如实定谳（工具降级观察+数学替代评估，不硬凑）。

### 批次 B：frozen COM 实机（N48/N49 观察项）

- [x] B1 **预置批（白天已完成）**：frozen 重建（N52 后代码→80 工具）+ smoke_frozen EXPECTED_TOOLS 79→80 同步（N52 遗漏联动补）+ smoke PASS。
- [x] B2 实机：MCP stdio 起 frozen exe→`solidworks_connect`（真附着）→part_new→create_box→get_bounding_box（实机值 [60,40,10] 断言）→关闭。判据=frozen 下 COM 附着+gen_py typed 缓存首生成路径工作。

### 批次 C：CSG SW roundtrip（N54 观察项）

- [x] C1 build123d 六角柱（R20 h10 理论 2598.08）→ `csg_plan_from_script`（离线已验 2.33e-16）→ 主仓 `rebuild_csg` SW 实机重建 → 体积互证（窗口 ±1%）→ 清理。判据=导出方向在 SW 实机闭环。

### 收尾

- [x] 三项各自定谳（tools/INDEX 取证行+本表回填+必要时修复走 TDD）；全套回归；提交推送。

**验收**：3 观察项各有定谳（通过/如实 BLOCKED）；无静默失败；全套绿。
**反目标**：不为过 e2e 硬凑判据；SW 异常状态不强行续跑（如实报告暂停）。

## 4. N58 宏转录管线（条件 on U9，1晚/族）

- [ ] .swp 宏解析器（VBA 提取 API 调用序列→typelib 对照契约卡）→ 探针复现 → TDD → 工具+计数锁+示例卡+BLOCKED 撤销。无宏不猜。

> **2026-09-12 前置核证（FB-020，N58 未开工即拦）**：用户指令声称「mirror 等五族 BLOCKED+已录宏」，但占位符未填路径、全盘无 mirror 宏文件。按核证铁律以 HEAD+实机裁决：「五族含 mirror」为 T8 时代旧枚举——**mirror 已于 08-30 N9 原生解锁**（commit 51bd1c3；契约=特征 SelectByID2(BODYFEATURE,mark1)+基准面(PLANE,append,mark2)+`fm.InsertMirrorFeature2(False,True,True,False,0)`，第 5 参 ScopeOptions=0 为解锁关键）并当晚经生产 MCP 工具链实机复验 **PASS**（box 30×20×10+⌀8 孔@x10 → `features_mirror(切除-拉伸1, right)` → 树新增「镜向1」）。真正待宏解锁=**四族 pattern/rib/combine/AutoBalloon**。另两条实证：①镜像 boss 特征（凸台-拉伸1）被 SW 静默拒收=工具边界观察项（registry 文案宜明示 cut-symmetric）；②核证中发现**另一进程并发修改本仓库+同一 SW 实例**（drawing.py/test_drawing.py/probe_n52_gtol.py 在变+e2e_n57_{gtol_e2e,frozen_sw,csg_roundtrip}.py 陆续出现，高度疑似 N57 批次提前执行；其 CloseAllDocuments 与我进行中 COM 调用竞态→RPC_E_DISCONNECTED(0x80010108) 瞬态）——实机批次跨会话应串行。**U9 未交付 → N58 维持条件挂起，无宏不猜。**

## 5. N59 路由对比+95% 冲线（条件 on 上游第二家）✅ 完成 2026-09-13

- [x] routing-guide §4 命令取数（plan 强档 vs 全快档）→ b7/mate/stepped 装配堆叠复跑 → 50 任务终态 ≥95% → vision 北极星结项回填。
  **结果：终态 48/50 = 96% ≥ 95%，北极星达成**（连跑 47/50 report-20260913-000634 + b7_pump_base 复跑转绿）。
  - 前置实测：中继上游=deepseek-flash/deepseek-v4-pro 两档；harness 补 `--plan-model` 透传（TDD 3 红→33 绿；同 provider 双模型路由 else 分支丢弃 plan_model 的缺口一并修复）。
  - 双臂对比（4 任务 × 全flash / plan=v4-pro）：结果逐项一致——回收 2（b7_frame_stack/mate_shaft_stack）归因**上游漂移非路由**；b7_flange_bolts/stepped_sleeve_pair 5 次观测逐位复现=确定性能力败（不强凑）。
  - vision G1+§6 已结项（口径链 92→96）；aicad 报告 §9-§10 全记录（§10=并发会话对账：47→48 并集定谳、mate 增益归因更正为漂移、U11 降级可选）；全套 pytest 745 绿零回归。

## 6. N60 补推+CI 收口（条件）

- [x] 网络窗口恢复→双仓补推 ✅ 2026-09-13 早晨已发生（主仓 f127434 / aicad b8536d3；**2026-09-19 收官对账核验**：`git ls-remote github refs/heads/main`==本地 HEAD，双仓 0/0 同步——原表未回填系计划文件最后写入 06:31 早于 push 06:32）。
- [ ] U8 后 re-run 最新 run（2026-09-19 核验：GitHub 网络通；本机无 gh CLI+仓库私有 → CI 运行状态离线不可见，仍挂 U8 Billing 清算）。

---

## 7. 风险与未决

- **N57 批次 A 的 NewGtol 可能静默 None**（AutoBalloon 同族）——A1 探针首跑即定谳，BLOCKED 不阻塞 B/C。
- **SW 挂机窗口内许可弹窗/睡眠**——执行前检查进程+首调用连通性；异常即停如实报告。
- **frozen 80 工具重建**若失败（依赖面变化）→ 白天预置批即发现即修，不带病过夜。
- U10 未批不影响 N57-N59；批准即 +1（92%）。
