"""N58 圆周阵列工具——PM 面板驱动通道（2026-09-20）。

机器定谳（tools/INDEX.md N58/U9 行）：pattern 族的纯 COM 通道全部不可行——
CreateDefinition/CreateFeature 扁平重放返 Nothing（PM 隐式挂接态不被录制），
AccessSelections 外部 SERVERFAULT / 进程内 80010108，legacy FeatureCirPattern
在 COM 种子上特征落树但构建败（「无法找到该特征的终点」）。唯一端到端实证
通道 = 驱动真实 PropertyManager 面板（本会话 UI 实录两次建成阵列）。

工具流程：
    1. COM 校验（活动零件文档；种子/轴特征在树中；参数合法）
    2. COM 预选（录制契约：种子 BODYFEATURE mark4 → 轴 AXIS mark1，
       预选流入 PM 默认框）
    3. UI 驱动（drive_pattern_pane，pywinauto 惰性导入）：
       插入→阵列/镜向→圆周阵列（弹出菜单 #32768 矩形点击）→
       等间距/实例数（PM 顶部固定偏移）→ OK
    4. 判据 = 树 diff（N29 纪律：返回值不可信）；失败 ESC 撤面板

约束（v1，如实声明）：SW 窗口需可见且最大化、标准工具栏布局、
FeatureManager 面板默认宽度——PM 控件为自绘控件 UIA 不可见，
偏移按窗口左上角锚定。pywinauto 为可选运行时依赖（pip install pywinauto）。
"""

from __future__ import annotations

from typing import Any, Optional

import pythoncom

from solidworks_mcp.solidworks_api.geometry import walk_feature_names
from solidworks_mcp.utils.common import error_response, success_response
from solidworks_mcp.utils.com import call_or_value

# PM 面板控件相对 SW 窗口左上角的偏移（标准布局实测锚定，
# 2026-09-20 真机 1920×1040 最大化窗口标定）
PM_OFFSETS = {
    "ok": (17, 265),
    "cancel": (42, 265),
    "equal_spacing": (43, 378),
    "instance_count": (120, 440),
}


def _selection_nothing() -> Any:
    return pythoncom.Nothing


def drive_pattern_pane(
    window_title_regex: str,
    seed_feature: str,
    axis_feature: str,
    instance_count: int,
    equal_spacing: bool,
) -> None:
    """打开圆周阵列 PM 并提交（UI 通道；测试经 monkeypatch 替换）。

    前置：种子/轴已由 COM 预选（mark4/mark1），PM 打开时自动入框。
    """
    import ctypes
    import time

    import win32gui
    import win32process

    try:
        import pywinauto.mouse as mouse
        from pywinauto import Application
        from pywinauto.keyboard import send_keys
    except ImportError as exc:  # pragma: no cover - 环境缺失路径
        raise RuntimeError(
            "pywinauto 未安装（venv 内 pip install pywinauto）"
        ) from exc

    u32 = ctypes.windll.user32
    buf = ctypes.create_unicode_buffer(256)

    def _popup_hwnds():
        out = []

        def cb(hwnd, _):
            if win32gui.GetClassName(hwnd) == "#32768":
                out.append(hwnd)

        win32gui.EnumWindows(cb, None)
        return out

    def _wait_popup(timeout: float) -> bool:
        deadline = time.time() + timeout
        while time.time() < deadline:
            if _popup_hwnds():
                return True
            time.sleep(0.25)
        return False

    def _ensure_foreground(timeout: float = 6.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if win32gui.GetForegroundWindow() == win.handle:
                    return
            except Exception:
                pass
            try:
                win.set_focus()
            except Exception:
                pass
            time.sleep(0.5)

    def _click_menu_item(target: str) -> bool:
        for hwnd in _popup_hwnds():
            try:
                hmenu = win32gui.SendMessage(hwnd, 0x01E1)  # MN_GETHMENU
                n = win32gui.GetMenuItemCount(hmenu)
            except Exception:
                continue
            for i in range(n):
                if u32.GetMenuStringW(hmenu, i, buf, 256, 0x400) and target in buf.value:
                    ok, (l, t, r, b) = win32gui.GetMenuItemRect(hwnd, hmenu, i)
                    mouse.click(coords=((l + r) // 2, (t + b) // 2))
                    return True
        return False

    app = Application(backend="uia").connect(title_re=window_title_regex, timeout=10)
    win = app.window(title_re=window_title_regex)
    try:
        win.maximize()  # 归一化偏移锚定（非最大化窗口布局不同，实测偏移全错）
    except Exception:
        pass
    time.sleep(1.0)
    _ensure_foreground()

    # 插入 → 阵列/镜向 → 圆周阵列（后台线程焦点竞态：开菜单轮询+重试）
    send_keys("%i")
    if not _wait_popup(3.0):
        send_keys("{ESC}")
        time.sleep(0.5)
        _ensure_foreground()
        send_keys("%i")
        if not _wait_popup(3.0):
            raise RuntimeError("插入菜单未能打开（焦点抢占）")
    time.sleep(0.4)
    if not _click_menu_item("阵列/镜向"):
        raise RuntimeError("插入菜单中未找到「阵列/镜向」")
    if not _wait_popup(2.5):
        raise RuntimeError("「阵列/镜向」子菜单未能打开")
    time.sleep(0.3)
    if not _click_menu_item("圆周阵列"):
        raise RuntimeError("阵列/镜向菜单中未找到「圆周阵列」")
    time.sleep(2.5)  # PM 面板展开

    def _click(offset) -> None:
        dx, dy = offset
        mouse.click(coords=(win.element_info.rectangle.left + dx,
                            win.element_info.rectangle.top + dy))
        time.sleep(0.6)

    def _tree_click(name: str) -> None:
        for it in win.descendants(control_type="TreeItem"):
            try:
                n = it.element_info.name or ""
            except Exception:
                continue
            if name in n:
                it.click_input()
                time.sleep(1.0)
                return
        raise RuntimeError(f"特征树中未找到 {name!r}")

    # 预选择不自动流入 PM 框（实测）——点框→点树逐项填充
    _click((120, 327))                      # 1. 阵列轴框
    _click((22, 208))                       # 2. FeatureManager 树图标
    _tree_click(axis_feature)               # 3. 树选轴
    _click((130, 538))                      # 4. 特征和面框
    _tree_click(seed_feature)               # 5. 树选种子
    if equal_spacing:
        _click((43, 378))                   # 6a. 等间距
    _click((120, 440))                      # 6b. 实例数框
    send_keys("^a")
    send_keys(str(instance_count))
    time.sleep(0.3)
    send_keys("{TAB}")
    time.sleep(0.6)
    _click((17, 265))                       # OK 勾
    time.sleep(3.0)  # 等待重建


def esc_cancel_pane(window_title_regex: str = "SOLIDWORKS.*") -> None:
    """失败路径：ESC×2 取消活动 PM 面板（尽力而为，不抛错）。"""
    try:
        import time as _t

        from pywinauto import Application
        from pywinauto.keyboard import send_keys

        app = Application(backend="uia").connect(title_re=window_title_regex, timeout=5)
        win = app.window(title_re=window_title_regex)
        win.set_focus()
        _t.sleep(0.4)
        send_keys("{ESC}")
        _t.sleep(0.4)
        send_keys("{ESC}")
    except Exception:  # noqa: BLE001 — 清理尽力而为
        pass


def create_circular_pattern(
    sw_app: Any,
    seed_feature: str,
    axis_feature: str,
    instance_count: int,
    angle_deg: float = 360.0,
    equal_spacing: bool = True,
    pattern_name: Optional[str] = None,
) -> dict:
    """Create a circular pattern by driving the PM pane (N58 channel).

    种子/轴为特征树名称；实例数含种子；角度为总角度（默认 360° 等间距）。
    判据 = 树 diff（新特征名）；驱动失败 ESC 撤面板并报错。
    """
    if instance_count < 2:
        return error_response("instance_count must be >= 2 (seed included)", code="INVALID_PARAMETER")
    if not (0.0 < angle_deg <= 360.0):
        return error_response("angle_deg must be in (0, 360]", code="INVALID_PARAMETER")

    model = sw_app.get_active_document()
    if model is None:
        return error_response("No active document", code="NO_DOCUMENT")

    before = walk_feature_names(model)
    if seed_feature not in before:
        return error_response(
            f"seed feature {seed_feature!r} not in feature tree", code="INVALID_PARAMETER"
        )
    if axis_feature not in before:
        return error_response(
            f"axis feature {axis_feature!r} not in feature tree", code="INVALID_PARAMETER"
        )

    ext = model.Extension
    Nothing = _selection_nothing()
    model.ClearSelection2(True)
    ok_seed = ext.SelectByID2(
        seed_feature, "BODYFEATURE", 0.0, 0.0, 0.0, False, 4, Nothing, 0
    )
    ok_axis = ext.SelectByID2(
        axis_feature, "AXIS", 0.0, 0.0, 0.0, True, 1, Nothing, 0
    )
    if not (ok_seed and ok_axis):
        model.ClearSelection2(True)
        return error_response(
            f"pre-selection failed (seed={ok_seed}, axis={ok_axis})", code="SW_API_ERROR"
        )

    try:
        drive_pattern_pane(
            "SOLIDWORKS.*", seed_feature, axis_feature, instance_count, equal_spacing
        )
    except Exception as exc:  # noqa: BLE001 — 驱动失败统一撤面板
        esc_cancel_pane()
        model.ClearSelection2(True)
        return error_response(f"PM drive failed: {exc}", code="SW_UI_ERROR")

    after = walk_feature_names(model)
    model.ClearSelection2(True)
    created = [n for n in after if n not in before]
    if not created:
        return error_response(
            "pattern feature was not created (tree diff empty — "
            "check the pane state / seed-end-tag boundary, see INDEX N58/U9)",
            code="SW_API_ERROR",
        )
    feature_name = created[-1]
    if pattern_name:
        for feat in _iter_features(model):
            if feat.Name == feature_name:
                feat.Name = pattern_name
                feature_name = pattern_name
                break
    return success_response(
        data={
            "feature_name": feature_name,
            "seed_feature": seed_feature,
            "axis_feature": axis_feature,
            "instance_count": instance_count,
            "angle_deg": angle_deg,
            "equal_spacing": equal_spacing,
        },
        message=f"Created circular pattern {feature_name} ({instance_count} instances)",
    )


def _iter_features(model):
    feat = call_or_value(model, "FirstFeature")
    while feat is not None and isinstance(getattr(feat, "Name", None), str):
        yield feat
        feat = call_or_value(feat, "GetNextFeature")
