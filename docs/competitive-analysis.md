# SolidWorksMCP 竞品分析

> 2026-10-02 创建。聚焦 AI-CAD 自动化领域的差异化定位。

## 竞品矩阵

| 维度 | SolidWorksMCP | Fusion 360 API | OnShape FeatureScript | CAD GPT / Zoo AI | SolidWorks VBA |
|------|---------------|----------------|----------------------|-------------------|----------------|
| AI 集成 | ✅ MCP 协议原生 | ❌ 需自行封装 | ❌ 需自行封装 | ✅ 内置 AI | ❌ 无 AI |
| 自动化方式 | 自然语言→工具调用 | Python/JS 脚本 | FeatureScript | 自然语言→代码 | VBA 宏 |
| 运行环境 | 本地实机 SW | 本地/云端 | 云端 | 云端 | 本地 SW |
| 工具数量 | 81 MCP 工具 | ~200 API | ~150 API | 通用 | 无限制 |
| 参数化建模 | ✅ 板/柱/锥/孔/阵 | ✅ 完整 | ✅ 完整 | ⚠️ 基础 | ✅ 完整 |
| 装配约束 | ✅ 基础 mate | ✅ 完整 | ✅ 完整 | ❌ 无 | ✅ 完整 |
| 工程图 | ✅ 三视图+PDF | ✅ 完整 | ✅ 完整 | ❌ 无 | ✅ 完整 |
| 曲面/仿真 | ❌ 未暴露 | ✅ 完整 | ✅ 完整 | ❌ 无 | ✅ 完整 |
| 学习曲线 | 低（MCP 接入） | 中（API 学习） | 中（FS 语言） | 低（对话） | 高（VBA） |
| 开源/许可 | proprietary | 商业 | 商业 | 商业 | 商业 |

## 差异化优势

### 1. MCP 协议原生
SolidWorksMCP 是唯一使用 MCP（Model Context Protocol）标准协议的 CAD 自动化工具。这意味着：
- 任何 MCP 兼容客户端（Claude Desktop / 自定义 AI 应用）可直接接入
- 无需自行封装 AI↔CAD 的通信层
- 工具 Schema 自描述，AI 可自动发现能力

### 2. 本地实机 + 全链路
- 直接操作 SolidWorks 2026 实例（非云端代理），保留完整 SW 功能
- 零件→装配→工程图→PDF/STEP/STL 全链路 81 工具覆盖
- 与 aicad 子仓三通道互通（STEP/COM 特征树/参数同步）

### 3. 安全模型
- allowed_root 路径白名单（防目录遍历）
- COM 调用固定 STA 串行（防并发崩溃）
- 破坏性工具标记 + 覆盖确认
- 超时毒化退程机制

## 劣势与应对

| 劣势 | 影响 | 应对策略 |
|------|------|---------|
| 仅支持 SolidWorks | 用户群受限 | MCP 协议抽象层未来可扩展到其他 CAD |
| 无曲面/仿真 | 复杂件无法处理 | v0.4 补曲面，仿真明确 Won't |
| 本地部署 | 无法云端规模化 | 定位为工程师个人工具，非 SaaS |
| 81 工具有限 | 复杂操作需多步组合 | 设计计划执行器支持批量操作 |

## 市场定位

```
                    AI 集成度
                        ↑
                        │
        SolidWorksMCP ●  │  ● CAD GPT
                        │
    ───────────────────┼────────────────→ 专业深度
                        │
        Fusion 360 API ●│  ● OnShape FS
                        │
        SolidWorks VBA ●│
                        │
```

SolidWorksMCP 定位于 **AI 集成度 × 专业深度** 的交叉点：
- 比 CAD GPT 更专业（81 工具覆盖完整建模链路）
- 比 Fusion 360 API 更 AI 友好（MCP 协议原生，无需封装）
- 比 SolidWorks VBA 更现代（Python + MCP + AI 自然语言）