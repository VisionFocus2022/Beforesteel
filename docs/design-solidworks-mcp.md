# Design：SolidWorks MCP Server

**版本**: 1.2（as-built 修订 + 并发模型补章）
**日期**: 2026-07-17（v1.0）｜ 2026-08-28（v1.1 as-built 附录）｜ 2026-10-01（v1.2 补 §2.4 时序 / §2.5 并发线程模型）
**关联 PRD**: `docs/prd-solidworks-mcp.md`

> ⚠️ **As-built 说明（2026-08-28）**：本文以下内容为 2026-07-17 的**原始设计**，保留作历史记录。与实现的主要偏差见文末「附录 A：As-built 对账」与 `docs/adr/2026-08-28-architecture-decisions.md`（决策记录）。
>
> 📌 **v1.2 补章说明（2026-10-01）**：§2.4「关键流程时序」与 §2.5「并发与线程模型」为 as-built 补章——承载 ADR-0001（STA 单线程）与 ADR-0006.1（COM 超时/毒化）已实现但原文档缺失的运行时行为，依据 `solidworks_mcp/utils/com_executor.py` 源码与 README/AGENTS.md 现行口径撰写。

---

## 1. 代码库探索

本项目为新建项目，无既有代码需要适配。可复用的外部能力：

- **SolidWorks 2026 COM API**: 通过 `pywin32` 的 `win32com.client.Dispatch` 调用。
- **MCP Python SDK**: 选择 `fastmcp`（更简洁）或官方 `modelcontextprotocol/python-sdk`。
- **现有 VBA 宏**: `E:\SolidWorks 2026\VBA\Verify_API_Stability.bas` 中的模板查找逻辑可复用到 Python。

---

## 2. 架构设计

### 2.1 总体架构

```
┌─────────────────────────────────────────────────────────────┐
│                    Claude Code (用户界面)                     │
│                  自然语言 → MCP 工具调用                      │
└───────────────────────┬─────────────────────────────────────┘
                        │ stdio / sse
                        ▼
┌─────────────────────────────────────────────────────────────┐
│              SolidWorks MCP Server (Python)                  │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────┐  │
│  │   server.py │  │   tools/    │  │   solidworks_api/   │  │
│  │  MCP 协议层 │  │  工具注册   │  │   SolidWorks 封装   │  │
│  └─────────────┘  └─────────────┘  └─────────────────────┘  │
└───────────────────────┬─────────────────────────────────────┘
                        │ pywin32 COM
                        ▼
┌─────────────────────────────────────────────────────────────┐
│                 SolidWorks 2026 Application                  │
│                         SldWorks.exe                         │
└─────────────────────────────────────────────────────────────┘
```

### 2.2 组件关系

| 组件 | 职责 | 依赖 |
|------|------|------|
| `server.py` | MCP 协议入口，注册所有 tools | `fastmcp`, `tools` 包 |
| `tools/` | 每个工具一个模块，参数校验 + 业务编排 | `solidworks_api/`, `utils/` |
| `solidworks_api/` | 封装 SolidWorks COM API 调用 | `pywin32` |
| `utils/` | 公共工具：模板查找、单位转换、路径安全校验 | 无 |
| `tests/` | 单元测试和集成测试 | `pytest` |

### 2.3 数据流

1. 用户输入自然语言指令。
2. Claude Code 选择 MCP tool，发送 JSON-RPC 请求。
3. `server.py` 路由到对应 tool。
4. tool 调用 `solidworks_api/` 中的函数。
5. `solidworks_api/` 通过 pywin32 调用 SolidWorks。
6. 结果沿原路返回，Claude Code 汇总给用户。

### 2.4 关键流程时序（v1.2 as-built 补章）

**正常调用路径**：
```
Claude Code → server.py:        stdio JSON-RPC tools/call（如 solidworks_part_create_cylinder）
server.py → registry/<域>.py:    路由到分域注册的工具函数（ADR-0012；入参 pydantic 校验，长度单位 mm）
registry → com_executor:        run_com(fn, *args, timeout=120)——任务入队
com-sta 线程:                    pythoncom.CoInitialize 公寓内 Dispatch/GetActiveObject 调 SW COM
com_executor ← future.result(): COM 返回值/异常回传调用线程
registry → Claude Code:         五段统一响应 {success, data, message, warning}
```

**超时与毒化路径**（ADR-0006.1，默认超时 120s，`SOLIDWORKS_MCP_COM_TIMEOUT_SECONDS` 可调）：
```
com-sta 线程:   卡在 SW 模态框/长运算上（COM 调用无法从外部安全中断）
run_com:        future.result(timeout=120) 超时 → ComCallTimeoutError（错误码 SW_TIMEOUT）
com_executor:   标记 poisoned——STA 线程与滞留任务保留，后续一切工具调用
                入队前快速失败 ComExecutorPoisonedError（错误码 SW_EXECUTOR_POISONED）
SOLIDWORKS_MCP_POISONED_EXIT=1 时：毒化即退出 server 进程 → MCP 客户端自动拉起新进程自愈
```

**进程关闭路径**：
```
atexit → com_executor.shutdown(): 投递 _STOP 哨兵，join(timeout=2s) 不无限阻塞
```

### 2.5 并发与线程模型（v1.2 as-built 补章）

| 线程/执行面 | 职责 | 并发语义 |
|------------|------|---------|
| MCP SDK 调用线程（FastMCP 工具分发） | 接收 stdio JSON-RPC、参数校验、组装五段响应 | 可并发进入 |
| `solidworks-com-sta`（唯一 COM STA daemon 线程） | `CoInitialize` 后循环消费任务队列，执行全部 SW COM 调用 | **全进程串行**——并发 MCP 调用在队列处排队 |
| 非 COM 工作（环形阵列 layout 预览、schema 校验、capabilities 派生等） | 纯几何/纯数据计算 | 在调用线程执行，不占 COM 队列 |

- **铁则**（AGENTS.md 安全红线 #1）：一切 SW COM 调用必须经 `run_com(...)` 收束到 STA 线程，禁止在其他线程直接触碰 COM 对象。测试 `test_calls_share_one_com_thread` 钉死（ADR-0001）。
- **可重入短路**：若当前已在 COM 线程上（COM 回调内再调用），`call()` 直接同步执行不入队。
- **毒化单向性**：超时不杀线程（COM 无法安全中断），poisoned 状态不可恢复，**进程重启是唯一解**；`SOLIDWORKS_MCP_POISONED_EXIT=1` 把"需人工重启"变成"退程+客户端自动重启"的自愈路径。
- **设计演进注**：v1.0 §7 仅一句"工具调用串行化"；实际机制由 ADR-0001（STA 收束）与 ADR-0006.1（超时/毒化/退程）先后定型，本节为对账补章。

---

## 3. 方案评估

### 方案 A：基于 `fastmcp` 的 stdio MCP Server（推荐）

**实现**: 使用 `fastmcp` 库，通过 stdio 与 Claude Code 通信。

**优点**:
- 开发简单，代码量少。
- `fastmcp` 自动处理工具注册和类型转换。
- stdio 通信稳定，无需额外端口。

**缺点**:
- 每次 Claude Code 会话启动时都需要启动 server。
- 跨进程状态管理简单，但不支持多实例并发。

**风险**: 低

### 方案 B：基于官方 `mcp` SDK 的 SSE Server

**实现**: 使用官方 `modelcontextprotocol/python-sdk`，通过 SSE（Server-Sent Events）通信。

**优点**:
- 符合官方标准，扩展性好。
- 可独立运行，支持多个客户端连接。

**缺点**:
- 配置复杂，需要处理端口、CORS、心跳等。
- 对初学者不够友好。

**风险**: 中

### 方案 C：直接 Python 脚本（非 MCP）

**实现**: 不封装成 MCP server，用户每次让 Claude Code 生成 Python 脚本并运行。

**优点**:
- 最简单，无需配置 MCP。

**缺点**:
- 不是自然语言交互，每次都要写脚本。
- 无法复用上下文，扩展性差。

**风险**: 低（但不符合用户需求）

### 最终选择：方案 A

理由：满足用户"自然语言控制 SolidWorks"的核心需求，开发成本最低，稳定性最好，最适合作为 MVP。

---

## 4. 接口与契约

### 4.1 工具命名规范

```
solidworks_<resource>_<action>
```

例如：
- `solidworks_connect_get_version`
- `solidworks_part_create_cylinder`
- `solidworks_file_import_step`
- `solidworks_assembly_add_component`

### 4.2 统一返回结构

每个工具返回一个 JSON 对象：

```json
{
  "success": true,
  "data": { ... },
  "message": "操作成功",
  "warning": null
}
```

失败时：

```json
{
  "success": false,
  "data": null,
  "message": "具体错误原因",
  "warning": null
}
```

### 4.3 错误契约

| 错误码 | 含义 | 示例 |
|--------|------|------|
| `SW_NOT_RUNNING` | SolidWorks 未运行 | 用户未启动 SolidWorks |
| `SW_API_ERROR` | COM API 调用失败 | 模板不存在、特征创建失败 |
| `INVALID_PARAMETER` | 参数不合法 | 直径为负数、路径为空 |
| `FILE_ALREADY_EXISTS` | 文件已存在，需要确认 | 保存路径冲突 |
| `OPERATION_CANCELLED` | 用户取消操作 | 确认弹窗选择否 |
| `TIMEOUT` | 操作超时 | SolidWorks 响应过慢 |

### 4.4 核心工具列表（第一期）

| 工具名 | 功能 | 关键参数 |
|--------|------|---------|
| `solidworks_connect` | 连接 SolidWorks 并返回版本 | 无 |
| `solidworks_part_create_cylinder` | 创建圆柱体 | diameter, height, save_path（可选） |
| `solidworks_part_create_box` | 创建立方体 | width, depth, height |
| `solidworks_file_open` | 打开文件 | file_path |
| `solidworks_file_import_step` | 导入 STEP | file_path |
| `solidworks_file_export_step` | 导出 STEP | file_path, overwrite_confirm |
| `solidworks_part_get_mass_properties` | 获取质量属性 | 无 |
| `solidworks_part_get_features` | 获取特征树 | 无 |
| `solidworks_feature_rename` | 重命名特征 | old_name, new_name |
| `solidworks_feature_set_suppression` | 抑制/解除抑制 | feature_name, suppressed |
| `solidworks_assembly_add_component` | 装配体插入零件 | file_path, x, y, z |

---

## 5. 数据模型

### 5.1 内部状态

```python
class SolidWorksAppState:
    app: Any  # SldWorks.SldWorks COM 对象
    connected: bool
    version: str
```

### 5.2 配置模型

```python
class ServerConfig:
    solidworks_version: str = "2026"
    template_search_paths: List[str]
    confirm_destructive: bool = True  # 始终为 True（严格确认模式）
```

### 5.3 工具参数模型（Pydantic）

```python
class CreateCylinderParams(BaseModel):
    diameter: float = Field(gt=0, description="圆柱直径，单位 mm")
    height: float = Field(gt=0, description="圆柱高度，单位 mm")
    save_path: Optional[str] = None
```

---

## 6. 安全设计

### 6.1 确认机制

- 所有 `save_path` 指向已存在文件时，工具返回 `FILE_ALREADY_EXISTS`，不执行覆盖。
- Claude Code 需要再次调用工具并传入 `overwrite_confirm=True` 才能覆盖。
- 删除特征、删除文件等操作需要显式 `confirm=True` 参数。

### 6.2 路径安全

- 所有路径通过 `os.path.abspath` 规范化。
- 拒绝包含 `..` 的相对路径，防止目录遍历。
- 只允许操作 `E:\SolidWorks 2026\` 及其子目录（可通过配置放宽）。

### 6.3 API 安全

- 不在工具中暴露任何密码、密钥、许可证信息。
- 所有异常返回给用户时，不泄露内部堆栈（仅返回 message）。

---

## 7. 性能设计

- 工具调用默认超时 30 秒。
- 文件导入/导出等可能耗时操作超时 120 秒。
- 所有工具调用串行化，避免 SolidWorks COM API 并发问题（**机制详见 §2.5**；as-built 现行口径：默认超时 120s，`SOLIDWORKS_MCP_COM_TIMEOUT_SECONDS` 可调）。
- 对频繁读取的模型属性做本地缓存（如特征列表）。

---

## 8. 文件变更清单

> ⚠️ **过期标注（2026-10-01）**：下表为 v1.0 原始规划清单，仅作历史记录。实际落地以附录 A、ADR-0003（tools/ 分域未建→22 工具集中注册）、ADR-0012（server.py 收缩为门面 + `registry/` 10 文件分域注册）为准。

| 文件/目录 | 类型 | 说明 |
|----------|------|------|
| `E:\SolidWorks 2026\SolidWorksMCP\pyproject.toml` | 新增 | 项目依赖与配置 |
| `E:\SolidWorks 2026\SolidWorksMCP\requirements.txt` | 新增 | 运行时依赖 |
| `E:\SolidWorks 2026\SolidWorksMCP\solidworks_mcp\server.py` | 新增 | MCP server 入口 |
| `E:\SolidWorks 2026\SolidWorksMCP\solidworks_mcp\__init__.py` | 新增 | 包初始化 |
| `E:\SolidWorks 2026\SolidWorksMCP\solidworks_mcp\solidworks_api\__init__.py` | 新增 | API 包初始化 |
| `E:\SolidWorks 2026\SolidWorksMCP\solidworks_mcp\solidworks_api\app.py` | 新增 | SolidWorks 连接管理 |
| `E:\SolidWorks 2026\SolidWorksMCP\solidworks_mcp\solidworks_api\part.py` | 新增 | 零件操作 API |
| `E:\SolidWorks 2026\SolidWorksMCP\solidworks_mcp\solidworks_api\assembly.py` | 新增 | 装配体操作 API |
| `E:\SolidWorks 2026\SolidWorksMCP\solidworks_mcp\solidworks_api\drawing.py` | 新增 | 工程图操作 API |
| `E:\SolidWorks 2026\SolidWorksMCP\solidworks_mcp\solidworks_api\file_io.py` | 新增 | 文件导入导出 API |
| `E:\SolidWorks 2026\SolidWorksMCP\solidworks_mcp\solidworks_api\features.py` | 新增 | 特征树操作 API |
| `E:\SolidWorks 2026\SolidWorksMCP\solidworks_mcp\tools\__init__.py` | 新增 | 工具包初始化 |
| `E:\SolidWorks 2026\SolidWorksMCP\solidworks_mcp\tools\connect.py` | 新增 | 连接类工具 |
| `E:\SolidWorks 2026\SolidWorksMCP\solidworks_mcp\tools\part.py` | 新增 | 零件类工具 |
| `E:\SolidWorks 2026\SolidWorksMCP\solidworks_mcp\tools\file_io.py` | 新增 | 文件类工具 |
| `E:\SolidWorks 2026\SolidWorksMCP\solidworks_mcp\tools\features.py` | 新增 | 特征类工具 |
| `E:\SolidWorks 2026\SolidWorksMCP\solidworks_mcp\utils\__init__.py` | 新增 | 工具包初始化 |
| `E:\SolidWorks 2026\SolidWorksMCP\solidworks_mcp\utils\templates.py` | 新增 | 模板路径查找 |
| `E:\SolidWorks 2026\SolidWorksMCP\solidworks_mcp\utils\security.py` | 新增 | 路径安全校验 |
| `E:\SolidWorks 2026\SolidWorksMCP\tests\test_app.py` | 新增 | 连接测试 |
| `E:\SolidWorks 2026\SolidWorksMCP\tests\test_utils.py` | 新增 | 工具函数测试 |
| `E:\SolidWorks 2026\SolidWorksMCP\README.md` | 新增 | 使用说明 |
| `E:\SolidWorks 2026\SolidWorksMCP\claude_mcp_config.json` | 新增 | Claude Code MCP 配置示例 |

---

## 9. 向后兼容与迁移

本项目为新建项目，无向后兼容问题。后续若升级工具签名，需保持旧版本兼容或提供迁移说明。

---

## 10. 门禁记录

- [✅] 探索门禁已通过
- [✅] PRD 门禁已通过
- [x] Design 门禁——**事后追认（2026-10-01）**：v1.0 当时未走显式 AskUserQuestion 闭合，实现已按本文档完成且经架构审查（`docs/architecture-review-solidworksmcp.md`）与 594 项测试基线验证，此处补记追认而非伪造当时裁决；as-built 偏差见附录 A 与 ADR。

---

## 附录 A：As-built 对账（2026-08-28）

| 原设计 | 实际实现 | 说明 |
|--------|----------|------|
| `tools/` 分域工具层（每域一模块） | **未建**——全部 22 个工具集中注册于 `server.py` | 漂移；架构审查列入二三波演进项 |
| 选型 `fastmcp` 库 | 官方 `mcp` SDK 1.28.x 的 `server.fastmcp.FastMCP` | 2026-07-21 切换，venv 曾残留 fastmcp 3.4.4（已清理） |
| stdio 传输 | stdio ✓ | 一致 |
| 工具超时 30s/120s | **未实现**（`run_com` 无超时参数） | ADR-0005 遗留待办（需实机 PoC） |
| 错误码表（含 TIMEOUT/SW_NOT_RUNNING） | 部分实现：INVALID_PARAMETER/SW_API_ERROR/SW_CONNECTION_FAILED/INVALID_OUTPUT_PATH 等；约半数路径落默认 OPERATION_FAILED | 详见架构审查 P2-7 |
| 分层 | `solidworks_api/`（通用）+ `utils/` + `examples/`（产品专用，2026-08-28 隔离）| ADR-0003 |
| `drawing.py` 工程图模块 | 未实现（README 已声明边界） | 一致（明确排除） |

**当前基线**：150 通过 / 0 失败 / 42 子测试；覆盖率 89%（fail_under=80 绿）；git 版本管理已建立（main 分支）。
