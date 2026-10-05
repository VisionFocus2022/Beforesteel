# eval 覆盖矩阵分析

> 2026-10-02 创建。分析 aicad eval 任务（52 个）对 build123d 操作的覆盖，
> 以及 SolidWorksMCP 工具（81 个）的测试覆盖。

## aicad eval × build123d 操作覆盖

| build123d 操作 | eval 使用次数 | 对应 MCP 工具 | 覆盖状态 |
|---------------|-------------|-------------|---------|
| Pos | 89 | （变换，无直接工具） | ✅ 充分覆盖 |
| Cylinder | 86 | solidworks_part_create_cylinder | ✅ 充分覆盖 |
| Box | 55 | solidworks_part_create_box / plate | ✅ 充分覆盖 |
| extrude | 3 | solidworks_part_create_plate | ✅ 少量覆盖 |
| Line | 3 | （草图图元） | ✅ 少量覆盖 |
| sweep | 2 | solidworks_part_create_swept | ✅ 少量覆盖 |
| RegularPolygon | 2 | solidworks_part_create_polygon | ✅ 少量覆盖 |
| Circle | 2 | （草图图元） | ✅ 少量覆盖 |
| fillet | 1 | solidworks_part_apply_fillet | ⚠️ 仅 1 次 |
| Cone | 1 | solidworks_part_create_cone | ⚠️ 仅 1 次 |

### 未覆盖的 build123d 操作

| 操作 | 对应 MCP 工具 | 建议 |
|------|-------------|------|
| revolve | solidworks_part_create_revolved | 添加旋转体 eval（如轴类零件） |
| loft | solidworks_part_create_loft | 添加放样 eval（如变截面梁） |
| chamfer | solidworks_part_apply_chamfer | 添加倒角 eval |
| CounterBore | solidworks_part_cut_round_hole（沉孔模式） | 添加沉孔 eval |
| Thread | solidworks_part_cut_threaded_hole | 添加螺纹 eval |
| Sphere | （无直接工具） | 低优先级 |
| Torus | （无直接工具） | 低优先级 |
| Rectangle 草图 | solidworks_part_create_slot | 添加槽形 eval |

## SolidWorksMCP 工具测试覆盖

| 工具域 | 工具数 | 测试覆盖 | 说明 |
|--------|--------|---------|------|
| 连接 | 2 | ✅ | connect + get_active_document |
| 设计 | 3 | ✅ | capabilities + execute_plan + part_prompt |
| 零件 | 28 | ✅ | plate/box/cylinder/cone/hole/threaded/polygon/slot/rib/dome/fillet/chamfer/shell/revolved/loft/swept/annular_pattern/circular_pattern/ring_light |
| 装配 | 8 | ✅ | new/add_component/add_mate/explode/list/move/rotate/check_interference |
| 工程图 | 12 | ✅ | create/export/insert dimensions/section/gtol/note/surface_finish/bom/organize/tolerance |
| 特征 | 7 | ✅ | list/details/rename/set_suppression/delete/mirror/rebuild_csg/apply_draft |
| 文件 | 6 | ✅ | open/close/import_step/export_step/export_stl/export_dxf |
| 属性 | 8 | ✅ | mass_properties/material/faces/bodies/bounding_box/equations/configurations/custom_properties |
| 阵列 | 2 | ✅ | annular_layout + create_annular_pattern |
| 产品 | 2 | ✅ | ring_light + ring_light_v |
| Prompt | 5 | ✅ | 5 个 prompt 工具 |

**总覆盖率**：81/81 工具均有测试（87% 代码覆盖率）

## 覆盖盲区与建议

| 盲区 | 影响 | 补充优先级 |
|------|------|-----------|
| eval 缺少 revolve/loft/chamfer | AI 可能不擅长生成这些操作 | 中 |
| eval 缺少螺纹/沉孔 | 标准件场景覆盖不足 | 中 |
| eval fillet 仅 1 次 | 圆角经验不足 | 低 |
| MCP 工程图工具无 eval | 工程图生成能力未验证 | 高（但属于 SW COM 范围） |