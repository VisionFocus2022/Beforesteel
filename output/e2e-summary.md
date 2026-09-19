# 实机 E2E 验收台账

- 运行时间：2026-09-06T22:00:16
- git 提交：7b948ed
- SolidWorks 版本：N/A
- 状态：SKIPPED（退出码 2）
- 步骤：0/0 通过
- 备注：SolidWorks 未运行（.mcp.json auto_start=false，脚本不自动拉起）

---

- 运行时间：2026-09-12 22:59–23:06（N57 实机三合一；本条 2026-09-19 收官对账补记）
- git 提交：70f8e64（预置）/ 14842b1（定谳）
- SolidWorks 版本：2026（实机真附着，frozen exe 全链 2.7s）
- 状态：PASS（三批全绿，专用脚本 e2e_n57_{gtol_e2e,frozen_sw,csg_roundtrip}.py）
- 步骤：A=GTOL 框格落图 PDF（GetFrameCount==1，typed IDrawingDoc 路径）；B=frozen 80 工具 connect→part_new→create_box→bbox [60,40,10] 精确；C=CSG 双引擎 rel diff 1.75e-16 逐位一致
- 备注：本批走专用探针脚本而非 e2e_sw_smoke.py 主口径——判据与证据归 tools/INDEX.md N57 三行 + probe_out/ 产物（JSON 报告不入库）
