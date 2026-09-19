# tools/ 探针与验证脚本索引

> 每个探针 = 一份实机 API 取证记录（探针先行协议，§2.4）。
> 有效签名结论同步在各任务执行记录与 `solidworks_api/` 各模块 docstring。
> 目录按域分组（T18，2026-08-30）；脚本用 `parents[2]` 定位仓库根。

## probe_part/ — 零件/特征/面域

| 脚本 | 验证对象 | 有效结论 | 任务 |
|---|---|---|---|
| probe_face_naming.py | 面枚举与命名 | SetEntityName 宿主是 ModelDoc2；SelectByID2 按名选不中 FACE——面选择=遍历+face.Select2(False,0) | T5 |
| probe_revolve.py | 旋转特征 | FeatureRevolve2 20 参实际顺序以 typelib 为准；ConstructionGeometry 中心线为轴 | T6 |
| probe_fillet_chamfer.py | 圆角/倒角 | FeatureFillet 5 参旧版可用；FeatureFillet3+ variant 数组编组不稳（RPC_E_SERVER_FAULT） | T7 |
| probe_shell_draft_mirror_pattern.py | 抽壳/拔模/镜像/阵列 | InsertFeatureShell(米,False) 可用；mirror/pattern 9 组合零产出 BLOCKED；DraftBody 数组编组崩 | T8 |
| probe_front_blind_bands.py | 前视盲孔/深度带 | 前视面上盲孔的深度-平面映射 | 治理期 |
| probe_hole_plane_context.py | 孔-平面上下文 | cut 特征的平面上下文选择 | 治理期 |
| probe_imported_annular_cut.py | 导入体环形切除 | STEP 导入体上的 annular cut | 治理期 |
| probe_sheet_metal_thread.py | 钣金基体法兰/真实螺纹 | BaseFlange 16 参（PCBA=Nothing）；InsertHelix 10 参 def=0 可建可选中（REFERENCECURVES）但 InsertCutSwept4 三形态零产出 BLOCKED | T21 |
| probe_featuremgr_enum.py | FeatureManager 类型库枚举 | makepy def 签名：FLP4=20 参/FLP5=22、InsertMirrorFeature2=5 参(ScopeOptions)、InsertMultiFaceDraft=6 参、InsertCutSwept5=22 参(CircularProfile)；枚举常量不在 makepy vars()，需 PowerShell 反射 swconst.dll（swFmLPattern=6/swFmLocalLPattern=108/swFmSweepThread=87） | N9 |
| probe_loft_sweep_enum.py | loft/sweep 类型库枚举 | **sweep 首选 IFeatureManager.InsertProtrusionSwept4（20 参，尾部 CircularProfile/Diameter/Direction——圆截面可免轮廓草图）**；**凸台放样无 InsertProtrusionLoft 直接 API**（IFeatureManager/IModelDoc2 双查实证，仅曲面 InsertLoftRefSurface2 与老式 AddLoftSection），loft 走 CreateDefinition(swTnLoft?)+LoftFeatureData 或 AddLoftSection 序列——swTn* 值仍需 PS 反射 | N28 |
| probe_n32_bom_balloon.py | 装配图 BOM 表/气泡 | **BOM 表 OK**（InsertBomTable5 11 参，PartsOnly=1/TopLevel=2，表进 PDF）；**AutoBalloon 家族 BLOCKED**（AB1/AB2/AB4×typed/dynamic×Style/Size/Layout 10+ 变体全静默 None=T8 族）；**add_component 生产 bug 已修**（preopen 切活动文档→_get_or_create_assembly 每次新建装配→组件丢失；修复=先取装配+AddComponent4 落对+ActivateDoc3 回） | N32 |
| probe_n30_unblock.py ✅已完成·N30（契约已转录生产 docstring） | 多边形/槽/combine/样条实机收敛 | **2/4 原生+1 替代+1 延后**：polygon=CreatePolygon 8 参标量（六边形 R10×h10=2598.08 **0.000%**）；slot=CreateSketchSlot **14 参**（尾参易漏；面积=L·W+π(W/2)² 中心线含端半圆，1186.19 **0.000%**）；**combine BLOCKED**（9+ 变体：body 级 NonApiBody 语义墙/特征级静默拒收= T8 族；**数学替代=Merge=True 挤出自动融合**已有）；样条=variant 数组+dynamic 属性化双坑延后；SWBODYADD=15903/CUT=15902（**非 0/1/2**）；Merge=False（FeatureExtrusion2 第 18 参）可造双实体 | N30 |
| probe_n29_unblock.py ✅已完成·N29（契约已转录生产 docstring） | 基准轴/筋/圆顶实机收敛 | **3/4 可达**：基准轴=柱面 GetSurface().IsCylinder 走查+Select2(0)+`InsertAxis()` 零参（dynamic 属性语义触发；InsertAxis2 报非选择性的参数）；**圆顶=顶面 Select2(mark=1) 解锁**（mark=0 零产出）+typed InsertDome(3 参)，球冠 850.85 精确；**筋 BLOCKED**（13 变体零产出=T8 同族；swFeatureNameID_e 无 Rib 项 CreateDefinition 死路→数学替代薄板+宏录制器队列） | N29 |
| probe_n28_unblock.py ✅已完成·N28（契约已转录生产 docstring） | loft/sweep 实机收敛 | **2/2 一次收敛**：sweep=路径草图 mark4+Alignment=False+typed fm.InsertProtrusionSwept4（20 参 CircularProfile=True 免轮廓，⌀10×R20 弧 2467.40 精确）；loft=剖面 mark1 累加+typed doc2.InsertProtrusionBlend2(False×3)（14922.04，±1% 窗口）；**修正步骤1误报：SW 放样叫 Blend（swFmBlend=9），直接 API 存在**；基准面=fm.InsertRefPlane(8,dist)（N29 数据点）；弧=ISketchManager.CreateArc 10 参（CreateArc2 属 ModelDoc） | N28 |
| probe_n9_unblock.py ✅已完成·N9（契约已转录生产 docstring） | mirror/draft/pattern/螺纹解锁 | 13 轮收敛 3/4：mirror=InsertMirrorFeature2(...,ScopeOptions=0)+基准面 mark2；draft=typed FM InsertMultiFaceDraft+拔模面 mark1 先中性面 mark2 后；thread=helix REFERENCECURVES mark4+InsertCutSwept5(**Alignment=False**)+CircularProfile；pattern BLOCKED（直调全组合零产出/AccessSelections serverfault/属性 put 编组崩）→生产走数学替代；typed FM 铁律+call_or_value 方法/属性二义 | N9 |
| probe_n33_explode.py | 爆炸视图全链 | **AutoExplode 一次通过**（typed 零参=dynamic 属性语义；count=1「爆炸视图1」）；图纸投影=CreateDrawViewFromModelView3 第 2 参**空串**可行（「爆炸视图1」/「默认」名被拒——爆炸视图非配置名）；AddExplodeStep 4 参手工步进未走（v1 自动）；**爆炸态图纸投影留观察项** | N33 |
## probe_assembly/ — 装配域

| 脚本 | 验证对象 | 有效结论 | 任务 |
|---|---|---|---|
| probe_assembly_extras.py | 新建装配/干涉/BOM/mate 常量 | AddComponent4 要求零件预开；InterferenceDetectionManager 干涉/体积；AddMate5 角度走 Angle 槽；tangent=4/angle=6/width=17 | T11 |
| probe_interference_transform.py | 干涉空间/组件变换/mate 删除 | GetInterferenceBody→GetBodyBox()+GetMassProperties(1000)[0:3]；TransformComponent2 已移除→CreateTransform(16 元素 VARIANT)→SetTransformAndSolve3(替换式)+EditRebuild3 才刷新；mate 删除=SelectByID2(name,"MATE")+EditDelete（复检须含 MateGroup 一层子特征）；装配面选择唯一可靠=IEntity(face).Select2；typed 包装 gencache.GetModuleForProgID | N8 |
| probe_tangent_width.py | tangent mate 复验 + delete_mate 闭环 | 面遍历 GetNextFace 仅 typed 可达；面积最大面启发（box 顶面 2400/cyl 侧面 2513 mm²）；AddMate5(4)→「相切1」实机成功；生产 delete_mate 删除复检通过；width 需 4 面 fixture→N15 | N8 |

## probe_drawing/ — 工程图域

| 脚本 | 验证对象 | 有效结论 | 任务 |
|---|---|---|---|
| gtol 实机定谳（N57 批次 A，2026-09-12，probe_n52_gtol.py + e2e_n57_gtol_e2e.py） | NewGtol 实机契约 | **NewGtol 在 NewDocument 返回的 dynamic dispatch 上报 DISP_E_MEMBERNOTFOUND（成员面受限，quirks#26③ 同族）——必须转 typed IDrawingDoc：gencache.GetModuleForProgID("SldWorks.Application").IDrawingDoc(model._oleobj_)（传 CDispatch 会 AttributeError InvokeTypes，必须 _oleobj_）**；SetFrameSymbols2/Values2/Position 可用（返回值不可靠）；判据 GetFrameCount==1；PDF 导出 40-45KB 正常。生产工具 insert_gtol 已加 typed fallback+测试钉死。**GTOL 非 AutoBalloon 同族——可用定谳** | N57 |
| frozen COM 实机（N57 批次 B，e2e_n57_frozen_sw.py） | frozen exe 附着真 SW | **全链 PASS**：80 工具 frozen exe 2.7s 完成 connect(34.2.1)→part_new→create_box→bbox [60,40,10] 精确→close——frozen 分发形态实机可用，gen_py 首生成路径正常 | N57 |
| CSG SW roundtrip（N57 批次 C，e2e_n57_csg_roundtrip.py） | 导出方向实机闭环 | **双引擎逐位一致 rel diff 1.75e-16**（build123d extrude(RegularPolygon(20,6),10)=10392.305 ↔ SW rebuild_csg polygon_prism 同值）；**过程中挖出并修复 N54 真 bug：csg_export 硬编码 version:1，polygon_prism(v2 op) 永远过不了主仓校验**——修为按 op 代级推导（+2 测试）；沙箱须用 aicad venv 跑（主仓 venv 无 build123d） | N57 |
| gtol 取证（N52，2026-09-10，非探针=typelib+PS 反射） | GD&T 框格契约 | **宿主=IDrawingDoc.NewGtol() 零参工厂**（非 ModelDoc）；IGtol.SetFrameSymbols2 九参全标量（FrameNumber, GCS, TolDia1, TolMC1, TolDia2, TolMC2, DatumMC1-3）/SetFrameValues2 六参字符串（FrameNumber, Tol1, Tol2, Datum1-3）/SetPosition(米)；判据=GetFrameCount 零参属性（成功=1）；GCS 枚举 PS 反射 swconst.dll（flatness=15/round=16/cyl=17/perp=21/position=23/runout=25/26），MC（MMC=1/RFS=2/LMC=3）；基准符号另有 IDrawingDoc.InsertDatumTag()（首版未做）；**实机 e2e 留观察项（SW 未运行窗口）**——NewGtol 静默 None 风险待实机定谳 | N52 |
| probe_drawing.py | 建图/三视图/标注/导出 | 模板 GetUserPreferenceStringValue(10)；Create1stAngleViews2 恒 False→手动三视图；InsertModelAnnotations2(0,True,0,True,True,False) 唯一有效；PDF/PNG SaveAs3 | T12 |
| probe_dim_organize_section.py | 尺寸遍历/删除/错开+剖视图 | GetDisplayDimensions 零参属性；删除链 GetNameForSelection→SelectByID2("DIMENSION")→DeleteSelection(True)；SetPosition 错开；CreateSectionViewAt4(x,y,0,草图名,0,0) | N4 |
| probe_section_debug.py | 剖切线放置契约 | 剖切线必须画 sheet 空白区（视图区域上的线归视图草图→失败）；At5/ICreate/MakeSectionLine 全拒；SW 长会话后 InsertModelAnnotations2 可能零产出，重启恢复 | N4 |
| probe_tolerance_finish_dxf.py | 公差/粗糙度/注释/DXF | IDimension 需 makepy 静态包装（mods.IDimension(dim._oleobj_)）；SetToleranceType(5)+SetToleranceValues(min,max 米)；粗糙度 14 参签名；CreateText2；DXF SaveAs3 恒返 1，判据=文件+SECTION 头 | N5 |

## probe_properties/ — 材料与属性域

| 脚本 | 验证对象 | 有效结论 | 任务 |
|---|---|---|---|
| probe_material_props_eqs.py | 材料/自定义属性/方程式/配置 | byref VARIANT(VT_BSTR) 铁律；材料名必须中文；Add3/Add2/AddConfiguration 返回形态 | T17 |
| probe_equation_cfg_edit.py | 方程式删改/配置激活/按配置设尺寸 | EquationMgr 动态代理 propput 带参不可用→以强类型 gencache 形态为准（Delete(i)/SetEquation(i,text)）；配置激活 ShowConfiguration2 | N12 |

## validate/ — 验证与巡检脚本

| 脚本 | 用途 | 任务 |
|---|---|---|
| validate_annular_pattern.py | annular pattern 实机验证 | pattern 交付 |
| validate_cone_thread.py | 锥/螺纹孔实机验证 | 治理期 |
| inspect_golden_cyls.py | 金标圆柱几何巡检 | 治理期 |
| inspect_planar_faces.py | 平面巡检 | 治理期 |
| inspect_step_geometry.py | STEP 几何巡检 | 治理期 |
| csg_roundtrip.py | 跨引擎 CSG 往返（aicad build123d 基准体积 + CSG v1 契约 JSON → 主仓 rebuild_csg_plan → SW 体积互证），需 SW 实机 | N11 |
| triple_artifact.py | 验收清单 #5 三件套（HLR views.svg + .sldprt + .step 同脚本双引擎产出），需 SW 实机 | N11 |

## 根目录

| 脚本 | 用途 |
|---|---|
| e2e_sw_smoke.py | 全工具实机冒烟（T1 建立，每任务追加；99 步） |
| soak_session.py | 长会话 soak（T22 建立）；N10 加 --tool-filter 四组二分（box-only/+faces/+drawing/+assembly）与 --rounds；四组×50 轮实测：box 0.90、faces 0.67、drawing 2.78、assembly 3.17 MB/轮；add_component 预开滞留与 SW 装配语义持有详见 assembly.py N10 注释 |
| run_pytest_guarded.py / run_suite_traced.py | 测试运行器（守卫/追踪） |
| macro_transcribe.py | N58 宏转录管线解析器（2026-09-19 预建，等 U9 交付 .swp 首跑）：.swp（OLE 复合流→MS-OVBA 解压→dir 模块表）/ .swb/.txt/.bas（文本透传）→ VBA 源码 → SW API 调用序列（录制噪声标记+property_put 区分+参数原样保留）。纯 stdlib 零新依赖，不动 MCP 包/frozen 面。**与 oletools 参考逐字节一致**（dir 1345B、模块 304/7121B）；真实宏验证：RecordedExtrude.swp→3046B 源码/26 调用（FeatureExtrusion2 23 参完整+中文选择目标「前视基准面」cp936 解码正确）、CreateConnector_RecordStyle.swb→73 调用；CreateConnector_Final.swp 如实定谳=仅存 304+124B 存根（参考一致，文件本体无码）。MS-OVBA 三规范坑钉死成回归测试：①LengthMask=0xFFFF>>BitCount（16 位，12 位截断丢 length 高 4 位）②CopyToken Offset 右移 (16-BitCount)（12-BitCount 会算错偏移）③dir 的 PROJECTVERSION(0x0009) 记录破坏 [Id][Size][Data] 框架（Size=Reserved=4 但实载荷 Reserved+Major+Minor=12B）；另 MODULESTREAMNAME(0x001A) 的 Size=串长无内嵌长度前缀。测试 tests/test_macro_transcribe.py 18 例（真实宏用例 skipif，CI 可跑） | N58 |
