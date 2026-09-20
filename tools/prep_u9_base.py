r"""U9 录宏前置——经生产 run_com STA 线程预建录制基体。

录制纪律：本脚本只建「被阵列的素材」，阵列操作本身必须发生在 UI 录制
开始之后（反目标②）。全部几何走生产 API（本机实机 PASS 过的典范组合）：
create_plate(120×90×8) → cut_round_hole(⌀8 @ (35,20) 贯穿) →
N29 契约基准轴（孔柱面 Select2(False,0) → InsertAxis 属性语义）→ 特征重命名。

用法：venv\Scripts\python.exe tools\prep_u9_base.py
退出码：0=基体就绪（文档保持打开、不保存——回滚=关闭不保存）；2=失败即停。
"""

from __future__ import annotations

import sys
from pathlib import Path

import pythoncom

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from solidworks_mcp.solidworks_api.app import _sw_app
from solidworks_mcp.solidworks_api.design import create_plate, cut_round_hole
from solidworks_mcp.utils.com import call_or_value
from solidworks_mcp.utils.com_executor import run_com
from solidworks_mcp.utils.templates import get_part_template


def _feature_walk(model):
    feat = call_or_value(model, "FirstFeature")
    while feat is not None:
        if not isinstance(getattr(feat, "Name", None), str):
            break
        yield feat
        feat = call_or_value(feat, "GetNextFeature")


def _tree(model) -> list[tuple[str, str]]:
    return [
        (feat.Name, call_or_value(feat, "GetTypeName2"))
        for feat in _feature_walk(model)
    ]


CUT_TYPE_NAMES = ("ICE", "Cut")  # SW2026 实测：切除-拉伸报告 ICE


def build(sw_app) -> dict:
    if not sw_app.connected:
        sw_app.connect()
    template = get_part_template()
    if not template:
        return {"step": "template", "success": False, "error": "no part template found"}

    # 显式新建文档并激活——避开 _get_or_create_part 对旧文档的复用叠加
    # （前两轮失败运行已在同一 doc 叠了板+孔）
    model = sw_app.app.NewDocument(template, 0, 0, 0)
    if model is None:
        return {"step": "new-doc", "success": False, "error": "NewDocument returned None"}
    doc_title = call_or_value(model, "GetTitle")

    r = create_plate(sw_app, 120.0, 90.0, 8.0)
    if not r["success"]:
        return {"step": "plate", "success": False, "error": r.get("error")}
    r = cut_round_hole(
        sw_app, diameter=8.0, x=35.0, y=20.0, plane="top", through_all=True
    )
    if not r["success"]:
        return {"step": "hole", "success": False, "error": r.get("error")}

    model = sw_app.get_active_document()
    model.ClearSelection2(True)

    cut_feat = None
    for feat in _feature_walk(model):
        if call_or_value(feat, "GetTypeName2") in CUT_TYPE_NAMES:
            cut_feat = feat  # 取最后一个 Cut（= 本次贯穿孔）
    if cut_feat is None:
        return {"step": "find-cut", "success": False, "error": "tree has no Cut feature"}

    # 基准轴必须过原点（板中心）而非孔自身轴线——孔同心轴会使阵列实例全部
    # 重叠（首跑教训）。两平面交线法：前视(XY)∩右视(YZ)=Y 轴，垂直于板面。
    ext = model.Extension
    Nothing = pythoncom.Nothing
    model.ClearSelection2(True)
    ok1 = ext.SelectByID2("前视基准面", "PLANE", 0, 0, 0, False, 0, Nothing, 0)
    ok2 = ext.SelectByID2("右视基准面", "PLANE", 0, 0, 0, True, 0, Nothing, 0)
    if not (ok1 and ok2):
        return {"step": "axis-planes", "success": False, "error": f"plane select failed {ok1}/{ok2}"}
    count_before = len(_tree(model))
    call_or_value(model, "InsertAxis")  # N29：属性语义触发
    tree_after = _tree(model)
    if len(tree_after) == count_before:
        return {"step": "axis", "success": False, "error": "InsertAxis produced no feature"}

    cut_feat.Name = "HoleToPattern"
    axis_feat = None
    for feat in _feature_walk(model):
        if call_or_value(feat, "GetTypeName2") == "RefAxis":
            axis_feat = feat
    if axis_feat is None:
        return {"step": "axis-name", "success": False, "error": "no RefAxis in tree"}
    axis_feat.Name = "AxisToPattern"

    # 关闭本会话失败运行遗留的未保存垃圾文档（按标题排除当前 doc）
    closed = []
    sw = sw_app.app
    doc = call_or_value(sw, "GetFirstDocument")
    titles = []
    while doc is not None:
        titles.append(call_or_value(doc, "GetTitle"))
        doc = call_or_value(doc, "GetNext")
    for title in titles:
        if title != doc_title:
            try:
                sw.CloseDoc(title)
                closed.append(title)
            except Exception:
                continue

    return {"success": True, "title": doc_title, "closed": closed, "tree": _tree(model)}


def main() -> int:
    result = run_com(build, _sw_app)
    if not result.get("success"):
        print(f"FAIL at {result.get('step')}: {result.get('error')}", file=sys.stderr)
        return 2
    print(f"base part ready: {result['title']} (unsaved — close without saving to roll back)")
    for title in result["closed"]:
        print(f"  closed junk doc: {title}")
    for name, kind in result["tree"]:
        marker = ""
        if name in ("HoleToPattern", "AxisToPattern"):
            marker = "  <-- pattern material"
        print(f"  {name}  [{kind}]{marker}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
