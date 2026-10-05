# Changelog

All notable changes to SolidWorksMCP will be documented in this file.

## [0.3.0] — 2026-09-20

### Added
- 81 个 MCP 工具（零件/装配/工程图/特征/文件/属性/阵列/产品/prompt 域）
- 环形阵列工具（annular_pattern，含避让角相位优化）
- 圆周阵列工具（circular_pattern，PM 面板 UI 驱动通道，N58）
- 工程图工具链（三视图+尺寸+剖视图+公差/粗糙度+PDF/PNG/DXF 导出）
- CSG 重建 prompt（跨引擎几何迁移）
- 参数化件族 prompt（材料→方程式→驱动尺寸→配置快照）
- CI 全绿（GitHub Actions：pytest+coverage≥80+pip-audit）

### Changed
- 覆盖率 CI 硬门 ≥80%（实测 87%）
- COM 调用超时可配置（SOLIDWORKS_MCP_COM_TIMEOUT_SECONDS）
- COM 毒化退程机制（SOLIDWORKS_MCP_POISONED_EXIT）

### Test Baseline
- 594 passed + 107 subtests（~9s）
- 覆盖率 87%

## [0.2.0] — 2026-08-xx

### Added
- 基础装配工具（AddComponent4 + AddMate5）
- 文件 IO 工具（STEP 导入导出 + STL 导出）
- 特征管理工具（列表/重命名/抑制）
- 质量属性查询
- 基准面/基准轴创建
- 圆顶与筋板

## [0.1.0] — 2026-07-xx

### Added
- MCP Server 基础架构（stdio 协议）
- 零件建模工具（plate/box/cylinder/cone/hole/threaded_hole）
- 设计计划执行器（solidworks_design_execute_plan）
- 安全模型（allowed_root 路径白名单）
- COM STA 线程串行执行