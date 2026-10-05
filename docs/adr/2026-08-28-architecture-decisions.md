# ADR-0007：通用环形阵列工具契约（2026-08-28 独立立项）

- **背景**：ADR-0006.6 声明"完整通用环形阵列工具应独立立项而非继续膨胀 examples"。用户裁决立项，并选定契约（双工具+pydantic 模型校验）与实机验证方式（留一键脚本）。
- **决策**：
  1. **双工具分工**：`solidworks_pattern_annular_layout`（READ_ONLY 纯几何预览，不触碰 SW）+ `solidworks_part_create_annular_pattern`（DESTRUCTIVE 执行）。预览与执行分离让布局数学可离线核验、执行可独立标注破坏性。
  2. **逐项 schema 校验**：环参数用 pydantic `AnnularRing`（radius_mm>0 / count 1-1000 / diameter_mm>0 / phase 0-360），FastMCP 生成 `$defs` 引用——补上审查 P2-7 指出的聚合参数（List[Dict]）无逐项校验短板；上限（环 100/环内 1000/总量 5000）防特征数爆炸 DoS。
  3. **实现路线**：沿用本仓实机验证过的"逐环单草图 + 单特征"（同 ring_light LED 标记路径），复用 geometry/sketch 原语；放弃 SW 原生 FeatureCircularPattern4（参数序无文档佐证，需实机摸索，风险高）。
  4. **相位优化**：环未显式给 phase 且提供避让角时，沿用 ring_light 实机验证过的 72 步最大间隙搜索；显式 phase 永远优先。
  5. **重叠只警不拒**：环内弦距<孔径、环间径向<半径和时给 warning（SolidWorks 会合并特征），不报错——合并是合法建模意图。
  6. **生命周期边界**：脚本验证完即 `CloseDoc`（示范 P2-8 的新实践）；产物落 gitignored 的 output/。
- **验证**：185 passed / 51 subtests；pattern.py 覆盖率 94%；实机一键脚本 `tools/validate_annular_pattern.py`（建板→三环 cut（一环相位优化）+一环 boss→特征树/体积窗口断言→SLDPRT+STEP 存档→关闭，退出码语义化）。

# ADR-0001：所有 SolidWorks COM 调用收束到单一 STA 线程

- **状态**：已接受（2026-07 实施，2026-08-28 记录）
- **背景**：SolidWorks 的 COM 接口是单线程套间（STA）语义；pywin32 从多线程并发调用会引发 RPC 错误与不可复现的崩溃。MCP server 的工具回调可能来自框架线程池。
- **决策**：进程级单例 `ComExecutor`（[utils/com_executor.py](../solidworks_mcp/utils/com_executor.py)）持有一个名为 `solidworks-com-sta` 的 daemon 工作线程，线程内 `CoInitialize` 后循环消费任务队列；`run_com()` 是唯一入口。缓存连接与全部 `SolidWorksApp` 状态只在该线程内触碰。
- **后果**：并发模型极简（天然串行、无锁）；代价是**任一 COM 调用挂死会瘫痪全部工具**（无超时，见 ADR-0005 待办）；关停时在途调用被 daemon 硬杀。测试以 `test_calls_share_one_com_thread` 锁定同线程契约。
- **替代方案**：每请求一线程（COM 套间爆炸）、每文档一线程（SolidWorks 不支持）、主线程调用（阻塞 stdio 事件循环）——均被否决。

# ADR-0002：COM 晚绑定 + 手工镜像常量，不使用 makepy 早绑定

- **状态**：已接受
- **背景**：pywin32 可用 makepy 生成早绑定包装获得常量与类型，但生成物绑定 SolidWorks 版本且部署复杂。
- **决策**：全程 `Dispatch`/`GetActiveObject` 晚绑定；用到的 SW 枚举常量手工镜像，**集中存放于 [solidworks_api/constants.py](../solidworks_mcp/solidworks_api/constants.py)**（2026-08-28 前曾分散在 5+ 个文件，已收敛）。pywin32 属性/方法暴露差异由 `call_or_value` 统一适配。
- **后果**：零部署依赖、跨 SW 小版本稳健；代价是无 IDE 常量提示、参数个数错误只能在运行期暴露（由 FakeModel 双打测试兜底）。`_band_crosses_mount_zone` 恒 True 期间观察到的 FeatureRevolve2 晚绑定被拒现象即源于此，v1 因此降级为 24 环带近似。

# ADR-0003：产品专用工具物理隔离到 products 子包（原 examples）

- **状态**：已接受（2026-08-28，用户裁决"子包隔离+保留工具"；2026-10-05 更名 examples→products）
- **背景**：ring_light v1/v3 是 MV-LRSS-H-80-W 环形灯产品的一次性设计工具（1439 行、占源码 37%），与通用建模工具混在 `solidworks_api/` 里侵蚀了分层边界。
- **决策**：两个模块迁至产品子包；server 继续注册全部工具（**行为零变化**）；包 docstring 声明边界——新的通用能力进 `solidworks_api`，一次性产品案例进产品包。
- **后果**：未来若要注销这两个工具，只需删 server.py 的两行 import 与两个注册函数；反向（迁回）同样便宜。备选方案（删除 v1 / 完全移出并注销 / 维持原位）见架构审查文档 §11.4 P1-4。
- **增补（2026-10-05，工程审查 A-2 清障）**：`examples/` 更名 `products/`——该包被 `registry/products.py` 无条件 import 进生产进程，"示例"之名名不副实；更名后目录语义与职责对齐（同步删除了 N14 拆分遗留的空壳 `tools/` 目录）。

# ADR-0004：路径校验采用逐组件解析，禁止跨链接的词法折叠

- **状态**：已接受（2026-08-28）
- **背景**：原 `normalize_path` 先 `abspath`（内含 normpath 词法折叠）再 `realpath`。当允许根内存在外指 junction 时，`root\link\..\out` 被折叠成 `root\out`（校验通过），而文件系统按对象管理器语义经链接解析到根外——校验与实际落盘位置发散（审查 P1-7）。且历史上校验用规范化路径、落盘 sink 用原始字符串，进一步扩大缺口。
- **决策**：[security.py](../solidworks_mcp/utils/security.py) 的 `normalize_path` 逐组件解析：每个**存在**的组件经 `realpath`（`_getfinalpathname`，OS 语义）规范化，`..` 只对**已规范化的前缀**做 pop，绝不词法折叠；全部 COM sink（SaveAs3/OpenDoc6/LoadFile4）与派生文件写入改用规范化路径（响应中仍回显调用方原始路径）。
- **后果**：真实 junction 回归测试（mklink /J 构造）锁定该行为——旧实现在该测试上失败。已知的残余窗口：校验与写盘之间的 TOCTOU（分钟级，需攻击者能在此窗口改写父目录），留待后续收紧；`realpath` 对 UNC/`\\?\` 前缀的极端形态未全覆盖测试。

# ADR-0006：三波收尾五决策（2026-08-28 第二批）

- **6.1 COM 超时采用"可选超时 + poisoned executor 快速失败"**：`run_com(fn, timeout=...)` 超时后不杀 STA 线程（COM 无法安全中断），标记 poisoned，后续调用立即报 `SW_EXECUTOR_POISONED` 并提示重启 server。默认关闭，经 `SOLIDWORKS_MCP_COM_TIMEOUT_SECONDS` 开启——因此无需实机验证即可安全合入；启用后的模态框场景验证仍建议在实机做。同时落地了 design 文档承诺的 `SW_TIMEOUT` 错误码（P2-7 部分）。
- **6.2 进程探测按会话过滤**：`_same_session` 用 `ProcessIdToSessionId` 过滤快照结果，其他用户会话的 SLDWORKS.exe 不再误判为本机可用实例（P1-8）；无法查询的进程按"非本会话"处理（fail-closed）。
- **6.3 写盘 sink 时刻包含性复查**：`ensure_sink_path` 在每次 SaveAs3/布局 JSON 写入前重解析+重查包含性，TOCTOU 窗口从"分钟级建模期"收窄到"解析到写盘的微秒级"；残余窗口（sink 解析与 OS 写入之间）为已接受风险（本地单用户威胁模型）。
- **6.4 默认 allowed_root 收敛到项目根**：无环境变量时不再默认整个父工作区（曾传递包含 aicad/）；显式配置不受影响（P2-3）。注意 `DEFAULT_ALLOWED_ROOT` 仍在 import 期冻结——与入口校验一致，保持同根语义。
- **6.5 文档生命周期采用显式 close 工具而非自动关闭**：自动关闭会破坏"建件→测量→导出"的有状态工作流；新增 `solidworks_file_close`（DESTRUCTIVE 注解，`save_changes=false` 丢弃未保存修改）让生命周期管理成为显式调用（P2-8，用户裁决）。
- **6.6 ring_light 行数通用化**：row_counts 放开为 1-64 行（默认仍为已确认的 9 行产品布局，默认行为零变化）；安装孔/线缆盒仍为产品常量——完整"通用环形阵列工具"若未来需要，应以独立工具立项而非继续膨胀 examples（动作 16 本轮范围，用户裁决实施）。

# ADR-0005：能力清单从注册表派生（含遗留待办）

- **状态**：已接受（2026-08-28）
- **决策**：`_capabilities()["tools"]` 由 `mcp._tool_manager.list_tools()` 派生，替代 22 项手维护清单；契约测试断言**列表相等**（含顺序）。历史上 README(20)/test(21)/实际(22) 三重漂移即源于多处人肉同步。
- **遗留待办**（三波，需实机 PoC 或远端）：①COM 调用超时与挂死检测（`run_com` 无超时参数，SW 模态框即全服务瘫痪——审查 P1-1，含 design 文档承诺未兑现）；②auto-start 进程探测收紧（Toolhelp32 快照全系统按名匹配，跨会话/僵尸进程会误判，审查 P1-8）；③CloseDoc/文档生命周期策略（当前只开不关，审查 P2-8）；④CI 流水线（pytest+coverage≥80+pip-audit）。
