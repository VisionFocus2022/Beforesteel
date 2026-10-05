# -*- coding: utf-8 -*-
"""F-03 DoD verifier: import BeforeSteel layouts into live SW2026 and assert
manifest-backed integrity ("10 scenes, zero broken faces").

PROVEN CHAIN (2026-10-05, SW 34.2.1 / SW2026, live-machine evidence):
  1. GetActiveObject("SldWorks.Application")          (user must have SW open)
  2. toggle 691 (swMultiCAD_Enable3DInterconnect) OFF — foreign-mode import
     hides Body APIs; native import exposes Component2.GetBodies2. Restored
     in finally.
  3. LoadFile4(path, "", importData, 0) — typed wrapper wants int errors param
     (raw VARIANT byref → TypeError); raw dynamic wants VARIANT. We use the
     generated-module typed dispatch obtained via GetActiveObject + temp
     gen_py wrappers; passing 0 works on the typed path.
  4. doc.GetType -> 2 (assembly); GetComponents(False) -> Component2 list
  5. per comp: GetBodies2(0, True) with arg-combo fallback; body.GetFaceCount()

Assertion matrix per scene:
  A1 import ok (model doc + assembly type)          hard
  A2 components >= manifest stations; bodies >= manifest devices  hard
  A3 every body face_count > 0                      hard (zero broken faces)
  A4 bbox of walked bodies vs manifest bbox ± tol   recorded (assembly walk
     covers all comps -> full bbox comparable); tol 2mm + 2% for big scenes
Ledger: factoryforge-mcp/output/sw-verify/ledger.md (append-only) + per-scene json.

Usage (SolidWorksMCP repo root, main venv):
  python tools/validate/verify_factoryforge_step.py --all
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path

import pythoncom
import win32com.client

MAIN_REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(MAIN_REPO))

FF_REPO = MAIN_REPO.parent / "factoryforge-mcp"
LAYOUT_DIR = FF_REPO / "output" / "layout"
LEDGER_DIR = FF_REPO / "output" / "sw-verify"

SCENES = [
    "demo-line-01", "lod-full-library", "mixed-line-01",
    "multi-line-plant-01", "safety-cell-01", "process-loop-01",
    "vertical-flow-01", "agv-line-01", "inspection-line-01",
    "mixed-jlc-parts-02",
]

TOGGLE_3DIC = 691  # swMultiCAD_Enable3DInterconnect (swUserPreferenceToggle_e)
BBOX_TOL_MM = 2.0
BIG_BBOX_PCT = 0.02  # +2% relative for scenes > 10 m span


def m2mm(x):
    return x * 1000.0


def comp_transform(c):
    """Component2.Transform2 -> 16-array MathTransform. Late-bound attr fails
    on dynamic dispatch; direct InvokeTypes(dispid=78, propget) works (proven)."""
    try:
        t = c._oleobj_.InvokeTypes(78, 0, 2, (9, 0), ())
        arr = win32com.client.Dispatch(t).ArrayData
        arr = arr() if callable(arr) else arr
        return list(arr)
    except Exception:
        return None


def xform_point(arr, x, y, z):
    """Apply SW MathTransform (16-array) to a point. v' = v·Q*scale + T."""
    q, T, s = arr[0:9], arr[9:12], arr[12] or 1.0
    return (
        x * q[0] + y * q[3] + z * q[6]
    ) * s + T[0], (
        x * q[1] + y * q[4] + z * q[7]
    ) * s + T[1], (
        x * q[2] + y * q[5] + z * q[8]
    ) * s + T[2]


def body_box_assembly_mm(b, arr):
    """Local GetBodyBox -> assembly-space min/max (mm) via component transform."""
    bbx = list(b.GetBodyBox() or [])
    if len(bbx) != 6:
        return None
    corners = [(x, y, z) for x in (bbx[0], bbx[3]) for y in (bbx[1], bbx[4]) for z in (bbx[2], bbx[5])]
    pts = [xform_point(arr, *p) if arr else p for p in corners]
    xs, ys, zs = zip(*pts)
    return min(xs) * 1000, min(ys) * 1000, min(zs) * 1000, max(xs) * 1000, max(ys) * 1000, max(zs) * 1000


def get_bodies(comp):
    """Component2.GetBodies2 arg-combo fallback (proven on SW2026)."""
    for args in ((0, True), (0, False), (0,)):
        try:
            r = comp.GetBodies2(*args)
            return list(r) if r else []
        except Exception:
            continue
    return []


def verify_scene(sw, stem: str) -> dict:
    step = LAYOUT_DIR / f"{stem}.step"
    man = json.loads((LAYOUT_DIR / f"{stem}.manifest.json").read_text(encoding="utf-8"))
    t0 = time.time()
    r = {"scene": stem, "started": datetime.now().isoformat(timespec="seconds")}

    # A1 import (native mode enforced by caller-side toggle)
    try:
        idata = sw.GetImportFileData(str(step))
        sw.LoadFile4(str(step), "", idata, 0)
        doc = sw.ActiveDoc
        dtype = doc.GetType
        dtype = dtype() if callable(dtype) else dtype
    except Exception as e:
        r.update(verdict="FAIL", failed_at="import", error=str(e)[:300])
        return r
    if doc is None or dtype != 2:
        r.update(verdict="FAIL", failed_at="import", error=f"doctype={dtype} (expected 2=assembly)")
        return r
    r["import_mode"] = "assembly(native)"

    comps = list(doc.GetComponents(False) or [])
    r["components"] = len(comps)

    # walk bodies (assembly-space bbox via per-component transform)
    n_bodies = n_faces = 0
    zero_face = 0
    box_min, box_max = [1e12] * 3, [-1e12] * 3
    for c in comps:
        arr = comp_transform(c)
        for b in get_bodies(c):
            fc = b.GetFaceCount()
            fc = fc if not callable(fc) else fc()
            n_faces += fc
            if fc <= 0:
                zero_face += 1
            n_bodies += 1
            ab = body_box_assembly_mm(b, arr)
            if ab:
                for i in range(3):
                    box_min[i] = min(box_min[i], ab[i])
                    box_max[i] = max(box_max[i], ab[i + 3])
    r["bodies"] = n_bodies
    r["faces"] = n_faces
    r["zero_face_bodies"] = zero_face

    # A2 counts vs manifest
    n_dev = man["counts"]["devices"]
    n_st = man["counts"]["stations"]
    r["manifest"] = {"devices": n_dev, "stations": n_st}
    r["a2_counts_ok"] = (len(comps) >= n_st) and (n_bodies >= n_dev)

    # A3 zero broken faces
    r["a3_zero_broken"] = zero_face == 0 and n_bodies > 0

    # A4 bbox (walk covers all comps -> comparable)
    m_bb = man.get("bbox_mm")
    a4 = None
    if m_bb and n_bodies > 0 and box_min[0] < 1e11:
        dmin = [abs(box_min[i] - m_bb["min"][i]) for i in range(3)]
        dmax = [abs(box_max[i] - m_bb["max"][i]) for i in range(3)]
        span = max(m_bb["max"][i] - m_bb["min"][i] for i in range(3))
        tol = BBOX_TOL_MM + span * BIG_BBOX_PCT
        a4 = {"delta_min": [round(x, 1) for x in dmin],
              "delta_max": [round(x, 1) for x in dmax],
              "tol_mm": round(tol, 1),
              "within": all(x <= tol for x in dmin + dmax)}
    r["a4_bbox"] = a4

    r["elapsed_s"] = round(time.time() - t0, 1)
    r["verdict"] = "PASS" if (r["a2_counts_ok"] and r["a3_zero_broken"] and (a4 is None or a4["within"])) else "FAIL"
    # cleanup doc
    try:
        title = doc.GetTitle
        title = title() if callable(title) else title
        sw.CloseDoc(title)
    except Exception:
        pass
    return r


def append_ledger(reports):
    LEDGER_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y-%m-%d %H:%M")
    n_pass = sum(1 for r in reports if r["verdict"] == "PASS")
    lines = [f"\n## SW2026 native-import verify — {ts}",
             f"- SW 3D Interconnect temporarily OFF during run (restored). Verdicts: **{n_pass}/{len(reports)} PASS**", ""]
    for r in reports:
        line = (f"- **{r['verdict']}** `{r['scene']}` comps={r.get('components','?')} "
                f"bodies={r.get('bodies','?')} (manifest dev={r.get('manifest',{}).get('devices','?')}) "
                f"faces={r.get('faces','?')} zero-face={r.get('zero_face_bodies','?')}")
        if r.get("a4_bbox"):
            line += f" bbox={'ok' if r['a4_bbox']['within'] else 'DRIFT'}(tol {r['a4_bbox']['tol_mm']}mm)"
        if r["verdict"] == "FAIL":
            line += f" — {r.get('failed_at','assert')}: {str(r.get('error',''))[:150]}"
        lines.append(line)
    with open(LEDGER_DIR / "ledger.md", "a", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    for r in reports:
        (LEDGER_DIR / f"{r['scene']}.json").write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    stems = SCENES if "--all" in sys.argv else (args or SCENES[:1])
    print(f"SW2026 verify (native import): {len(stems)} scene(s). SW must be running.")
    pythoncom.CoInitialize()
    reports = []
    try:
        sw = win32com.client.GetActiveObject("SldWorks.Application")
        rev = sw.RevisionNumber
        rev = rev() if callable(rev) else rev
        print(f"connected: SW {rev}")
        cur = sw.GetUserPreferenceToggle(TOGGLE_3DIC)
        print(f"3D Interconnect={cur} -> disabling for native import")
        sw.SetUserPreferenceToggle(TOGGLE_3DIC, False)
        try:
            for stem in stems:
                print(f"--- {stem} ...", flush=True)
                try:
                    r = verify_scene(sw, stem)
                except Exception as e:
                    r = {"scene": stem, "verdict": "FAIL", "failed_at": "exception", "error": str(e)[:300]}
                reports.append(r)
                print(f"    {r['verdict']} bodies={r.get('bodies','?')} faces={r.get('faces','?')} ({r.get('elapsed_s','?')}s)")
        finally:
            sw.SetUserPreferenceToggle(TOGGLE_3DIC, cur)
            print(f"3D Interconnect restored = {cur}")
    finally:
        pythoncom.CoUninitialize()
    append_ledger(reports)
    n_pass = sum(1 for r in reports if r["verdict"] == "PASS")
    print(f"\nRESULT: {n_pass}/{len(reports)} PASS — ledger: {LEDGER_DIR / 'ledger.md'}")
    return 0 if n_pass == len(reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
