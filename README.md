# SolidWorks MCP

面向 SolidWorks 2026 的本地标准 MCP Server。MCP 客户端可以通过自然语言调用参数化零件建模、文件转换、特征树查询和基础装配工具。

当前版本：0.3.0

## 主要能力

- 使用官方 Python MCP SDK，通过 stdio 提供 81 个 tools、3 个 resources、5 个 prompts
- 连接正在运行的 SolidWorks，或在明确允许时自动启动
- 新建零件，创建板件、块体、圆柱体和圆孔
- 生成 9 行球形穹顶环形灯零件（产品专用工具，代码位于 solidworks_mcp/examples/，默认不注册；设 `SOLIDWORKS_MCP_PRODUCT_TOOLS=ring_light` 后启用，工具数 80 → 82）
- 按顺序执行 new_part、plate、box、cylinder、cone、hole、threaded_hole、annular_pattern 设计计划
- 打开 SolidWorks 文件，导入 STEP，导出 STEP/STL
- 查询活动文档、质量属性、特征树和装配零部件
- 重命名、抑制或解除抑制特征
- 插入装配零部件，添加重合、同心和距离配合
- 所有 SolidWorks COM 调用固定在同一个 STA 线程串行执行

## 环境要求

- Windows 10/11
- SolidWorks 2026
- Python 3.10 或更高版本

安装依赖：

~~~powershell
cd "E:\SolidWorks 2026\SolidWorksMCP\SolidWorksMCP"
python -m venv venv
.\venv\Scripts\activate
pip install -r requirements.txt
~~~

## MCP 配置

项目根目录已经提供 .mcp.json，当前机器可直接使用：

~~~json
{
  "mcpServers": {
    "solidworks": {
      "command": "E:\\SolidWorks 2026\\SolidWorksMCP\\SolidWorksMCP\\venv\\Scripts\\python.exe",
      "args": ["-m", "solidworks_mcp.server"],
      "env": {
        "SOLIDWORKS_MCP_ALLOWED_ROOT": "E:\\SolidWorks 2026\\SolidWorksMCP",
        "SOLIDWORKS_MCP_SOLIDWORKS_VERSION": "2026",
        "SOLIDWORKS_MCP_AUTO_START": "false"
      }
    }
  }
}
~~~

重启 MCP 客户端后即可重新加载工具。

## 推荐工作流

1. 手动启动 SolidWorks 2026。
2. 调用 solidworks_connect。
3. 调用 solidworks_design_capabilities 读取单位和能力边界。
4. 使用单个设计工具，或通过 solidworks_design_execute_plan 执行一组操作。
5. 使用质量属性和特征树工具核验结果。
6. 保存或导出文件。

设计计划示例：

~~~json
[
  {"type": "new_part"},
  {"type": "plate", "width": 120, "depth": 80, "thickness": 8},
  {
    "type": "hole",
    "diameter": 12,
    "x": 0,
    "y": 0,
    "plane": "top",
    "through_all": true
  }
]
~~~

所有工具长度参数使用毫米。SolidWorks COM 内部所需的长度会自动转换为米。

## MCP 接口

Resources：

- solidworks://capabilities
- solidworks://status
- solidworks://active-document

Prompt：

- solidworks_design_part_prompt

Tools 按领域分为：

- 连接：solidworks_connect、solidworks_get_active_document
- 设计：solidworks_design_capabilities、solidworks_design_execute_plan
- 零件：solidworks_part_new、solidworks_part_create_plate、solidworks_part_create_box、solidworks_part_create_cylinder、solidworks_part_cut_round_hole、solidworks_part_create_revolved、solidworks_part_create_loft、solidworks_part_create_swept、solidworks_part_create_polygon、solidworks_part_create_slot、solidworks_part_create_ref_plane、solidworks_part_create_ref_axis、solidworks_part_create_rib、solidworks_part_apply_dome、solidworks_part_apply_fillet、solidworks_part_apply_chamfer、solidworks_part_apply_shell、solidworks_part_get_mass_properties
- 阵列：solidworks_pattern_annular_layout、solidworks_part_create_annular_pattern（通用同心环圆特征阵列，cut/boss，支持避让角相位优化）
- 阵列：solidworks_part_circular_pattern（圆周阵列，PM 面板 UI 驱动通道——需可见最大化 SW 窗口与 pywinauto；N58）
- 文件：solidworks_file_open、solidworks_file_close、solidworks_file_import_step、solidworks_file_export_step、solidworks_file_export_stl
- 特征：solidworks_features_list、solidworks_feature_rename、solidworks_feature_set_suppression
- 装配：solidworks_assembly_add_component、solidworks_assembly_explode、solidworks_assembly_list_components、solidworks_assembly_add_mate

工具返回统一结构：

~~~json
{
  "success": true,
  "data": {},
  "message": "操作说明",
  "warning": null,
  "error": null
}
~~~

失败时 error 包含稳定的 code 和可选 details，不会把完整异常堆栈返回给 MCP 客户端。

## 安全规则

- 所有输入和输出文件必须位于 SOLIDWORKS_MCP_ALLOWED_ROOT 下。
- 路径会解析 ..、符号链接和 Windows junction，防止绕过允许目录。
- 输出目录必须已经存在。
- 零件保存只接受 .sldprt，STEP 只接受 .step/.stp，STL 只接受 .stl。
- 覆盖文件必须传入 overwrite_confirm=true。
- launch_if_needed=null 时遵循 SOLIDWORKS_MCP_AUTO_START；默认不自动启动。
- 数值必须有限，长度必须为正数；设计计划中的布尔值采用严格解析。

可选环境变量：

- SOLIDWORKS_MCP_PART_TEMPLATE
- SOLIDWORKS_MCP_ASSEMBLY_TEMPLATE
- SOLIDWORKS_MCP_DRAWING_TEMPLATE
- SOLIDWORKS_MCP_LOG_PATH
- SOLIDWORKS_MCP_COM_TIMEOUT_SECONDS（COM 调用超时，秒；默认 120，超时后 COM 执行器毒化、该 MCP server 需重启才能恢复工具；垃圾/非正数回退到 120）
- SOLIDWORKS_MCP_POISONED_EXIT（默认 0；设 1 时 COM 执行器毒化即退出进程（exit 1），交由 stdio 宿主 supervisor 拉起重启，适用于无人值守长期运行场景）

## 测试

不依赖 SolidWorks 的测试：

~~~powershell
python -m coverage run -m unittest discover -s tests
python -m coverage report
~~~

覆盖率配置启用分支统计并要求业务包总覆盖率不低于 80%。MCP 注册检查涵盖工具数量、资源、提示词、输入 Schema、输出 Schema 和标准工具注解。

## 当前边界

当前设计能力适合棱柱、圆柱、圆锥、板件、圆孔和螺纹孔等基础参数化零件，并支持环形阵列、旋转轮廓、放样/扫描（多截面与沿路径特征）、基准面/基准轴、圆顶与筋板（筋为薄板数学替代——非自适应壁，InsertRib 不可用）、回转与工程图（三视图+尺寸+尺寸去重叠整理+剖视图+公差/粗糙度/注释+PDF/PNG/DXF 导出）。圆周阵列已通过 PM 面板 UI 驱动通道解锁（N58）。复杂草图约束、线性/草图驱动阵列、曲面、GD&T 形位公差框格、仿真和 PDM 尚未作为稳定工具暴露。基础装配配合仍使用 SolidWorks 兼容 API，建议在正式生产装配上先使用副本验证。
## 面向 AI 的工作流提示词

MCP prompts（5 个）：`solidworks_design_part_prompt`（零件设计+感知精修工作流：
特征详情→尺寸修改→面命名→装饰特征→材料/方程式）、
`solidworks_assembly_prompt`（装配：新建→加组件→list_faces 命名→mate→
干涉检查→BOM）、`solidworks_drawing_prompt`（工程图：建图→投三视图→
入尺寸→导出 PDF/PNG）、`solidworks_csg_rebuild_prompt`（跨引擎 CSG 重建：
box 首操作+沿轴堆叠+原子回滚契约，附 4-op 示例）、
`solidworks_parametric_prompt`（参数化件族：材料→方程式→驱动尺寸→配置快照）。
跨引擎几何迁移见 `docs/csg-plan-v1.md`。
