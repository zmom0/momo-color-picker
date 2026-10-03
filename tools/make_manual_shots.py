# -*- coding: utf-8 -*-
r"""馍馍拾色器 manual 图片资产生成工具（无文字成品图版）。

两种运行身份（同一个文件）：
  * 系统 Python：`python tools/make_manual_shots.py`
      1) 把自己同步到 `%APPDATA%\kritarunner\pykrita\make_manual_shots.py`；
      2) 用 kritarunner 在内嵌 Python 里抓 QWidget.grab() 原始 PNG；
      3) 从仓库 `pykrita` 路径导入插件（不用已安装版本）；
      4) 用 PIL 拼出成品 PNG / GIF；11、12 号图调用
         `tools/preview_ring_modes.py --no-labels --badges` 生成；
      5) `--check` 校验尺寸、帧数、体积、首屏帧不变量，并确认 logo / social-preview 已不存在。
  * kritarunner：`kritarunner.com -s make_manual_shots -f main` —— 抓图入口 main()。

硬规则：成品图不叠加任何标题 / 图例 / 说明文字（UI 自带文字除外）；
对比图只允许叠语言中性的数字/箭头编号（03 = ①/②，10 = ①/②，11/12 = 模式号 1/2/3 与
第一组行号 1~4），编号含义一律写在 `manual/manual.md` 正文/图注里；
浮层、弹窗按实际像素呈现；中英共用同一批图。

产物：`pykrita/hsv_picker/manual/images/*.png|gif`。
原始帧与布局元数据：`tmp/manual_shots_raw/`（不入交付，幂等覆盖）。
评审 contact sheet：`tmp/_review_after_D3.png`（`--contact` 单独生成，全量运行自动生成）。

命令行：
  python tools/make_manual_shots.py            # 抓图 + 拼图 + 自检 + contact sheet
  python tools/make_manual_shots.py --capture  # 只跑 kritarunner 抓图
  python tools/make_manual_shots.py --build    # 只做 PIL 拼图 / GIF
  python tools/make_manual_shots.py --check    # 只校验产物
  python tools/make_manual_shots.py --contact  # 只生成评审 contact sheet
"""
import argparse
import configparser
import json
import math
import os
import shutil
import subprocess
import sys

def _momo_repo_root():
    root = os.environ.get("MOMO_REPO")
    if not root:
        try:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        except NameError:
            base = ""
        if base and os.path.isfile(os.path.join(base, "tools", "math_selftest.py")):
            root = base
    if not root:
        import tempfile
        root = tempfile.gettempdir()
    return root


REPO = _momo_repo_root()
IMAGES = os.path.join(REPO, "pykrita", "hsv_picker", "manual", "images")
RAW = os.path.join(REPO, "tmp", "manual_shots_raw")
PROBE_DIR = os.path.join(os.environ.get("APPDATA", ""), "kritarunner", "pykrita")
KRITARUNNER = os.environ.get("MOMO_KRITARUNNER",
                             r"C:\Program Files\Krita (x64)\bin\kritarunner.com")
KRITA_COLORS = os.environ.get("MOMO_KRITA_COLORS",
                              r"C:\Program Files\Krita (x64)\share\color-schemes\KritaDark.colors")
GIF_LIMIT = int(1.5 * 1024 * 1024)

# 复现用的固定颜色/历史（不含任何用户环境信息）
HIST16 = ["#E84A5F", "#F2A365", "#F7D060", "#9BC53D", "#4CC9A0", "#3AA6B9",
          "#4D6CFA", "#7B61FF", "#B15BFF", "#E756A9", "#FF6B6B", "#FF9F45",
          "#FFD166", "#8AC926", "#52B788", "#2D9CDB"]
OVERVIEW_COLOR = (210.0, 0.75, 0.85)
RING_COLOR = (117.0, 0.62, 0.68)


def _log(msg):
    sys.stdout.write(str(msg) + "\n")
    sys.stdout.flush()


def _fp(path, mode="r", **kw):
    if "encoding" not in kw and "b" not in mode:
        kw["encoding"] = "utf-8"
    if "newline" not in kw and "b" not in mode:
        kw["newline"] = "\n"
    return open(path, mode, **kw)


def _write_json(path, obj):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with _fp(path, "w") as fh:
        json.dump(obj, fh, ensure_ascii=False, indent=1, sort_keys=True)


def _read_json(path, default=None):
    try:
        with _fp(path, "r") as fh:
            return json.load(fh)
    except Exception:
        return default


# ======================================================================
# 一、kritarunner 侧：在 Krita 内嵌 Python 里构造仓库代码的面板并抓图
# ======================================================================
_APP = None
_HP = None


def _qt():
    from PyQt5.QtCore import QPoint, QRect, QPointF, Qt
    from PyQt5.QtGui import QColor, QPalette, QPixmap
    from PyQt5.QtWidgets import QApplication
    return QApplication, QPoint, QRect, QPointF, Qt, QColor, QPalette, QPixmap


def _dark_palette(app):
    """用 Krita 默认主题 KritaDark.colors 的色板，保证截图与用户默认外观一致。"""
    from PyQt5.QtGui import QColor, QPalette
    cp = configparser.ConfigParser(strict=False)
    try:
        cp.read(KRITA_COLORS, encoding="utf-8")
    except Exception:
        cp = None

    def rgb(section, key, default):
        if cp is not None:
            try:
                return tuple(int(x) for x in cp.get(section, key).split(",")[:3])
            except Exception:
                pass
        return default

    win = rgb("Colors:Window", "BackgroundNormal", (71, 71, 71))
    win_fg = rgb("Colors:Window", "ForegroundNormal", (200, 200, 200))
    view = rgb("Colors:View", "BackgroundNormal", (56, 56, 56))
    view_alt = rgb("Colors:View", "BackgroundAlternate", (50, 50, 50))
    btn = rgb("Colors:Button", "BackgroundNormal", (54, 54, 54))
    sel = rgb("Colors:Selection", "BackgroundNormal", (83, 114, 142))
    sel_fg = rgb("Colors:Selection", "ForegroundNormal", (235, 235, 235))
    tip = rgb("Colors:Tooltip", "BackgroundNormal", (54, 54, 54))
    tip_fg = rgb("Colors:Tooltip", "ForegroundNormal", (156, 162, 174))
    link = rgb("Colors:Window", "ForegroundLink", (216, 216, 216))
    pal = app.palette()
    R = QPalette
    pairs = [
        (R.Window, win), (R.WindowText, win_fg), (R.Base, view),
        (R.AlternateBase, view_alt), (R.Text, win_fg), (R.Button, btn),
        (R.ButtonText, win_fg), (R.BrightText, (255, 255, 255)),
        (R.Highlight, sel), (R.HighlightedText, sel_fg),
        (R.ToolTipBase, tip), (R.ToolTipText, tip_fg), (R.Link, link),
    ]
    for role, value in pairs:
        pal.setColor(role, QColor(*value))
    for role in (R.Text, R.WindowText, R.ButtonText):
        pal.setColor(R.Disabled, role, QColor(118, 118, 118))
    app.setPalette(pal)


def _import_pkg():
    """把仓库 pykrita 放到 sys.path 最前，确保用的是仓库代码而不是已安装旧插件。"""
    global _HP
    if _HP is not None:
        return _HP
    repo_pkg = os.path.join(REPO, "pykrita")
    if repo_pkg in sys.path:
        sys.path.remove(repo_pkg)
    sys.path.insert(0, repo_pkg)
    mod = sys.modules.get("hsv_picker")
    if mod is not None:
        where = os.path.abspath(getattr(mod, "__file__", "") or "")
        if not where.lower().startswith(os.path.abspath(repo_pkg).lower()):
            for name in [n for n in list(sys.modules)
                         if n == "hsv_picker" or n.startswith("hsv_picker.")]:
                sys.modules.pop(name, None)
            mod = None
    if mod is None:
        import hsv_picker as mod
    where = os.path.abspath(getattr(mod, "__file__", "") or "")
    assert where.lower().startswith(os.path.abspath(repo_pkg).lower()), \
        "导入到非仓库代码: %s" % where
    try:
        mod.i18n._LANG = "zh"
    except Exception:
        pass
    _HP = mod
    return _HP


class Ev(object):
    """轻量鼠标事件替身（只实现控件真正用到的接口）。"""

    def __init__(self, x, y, button, buttons=None, mods=None):
        _QApplication, _QPoint, _QRect, QPointF, Qt, _C, _P, _PX = _qt()
        self._p = QPointF(float(x), float(y))
        self._b = button
        self._bs = buttons if buttons is not None else button
        self._m = Qt.NoModifier if mods is None else mods

    def localPos(self):
        return self._p

    def button(self):
        return self._b

    def buttons(self):
        return self._bs

    def modifiers(self):
        return self._m

    def accept(self):
        pass

    def ignore(self):
        pass


def _flush():
    if _APP is not None:
        _APP.processEvents()
        _APP.processEvents()


def _new_panel(width, height, metric="oklab", chroma="rel", ab_mode="box",
               show_ab=True, show_unreachable=True, show_clusters=True,
               show_lines=True):
    hp = _import_pkg()
    _QApplication, _QPoint, _QRect, _QPointF, Qt, _C, _P, _PX = _qt()
    p = hp.HsvPickerPanel()
    p.setAttribute(Qt.WA_DontShowOnScreen, True)
    p.resize(int(width), int(height))
    p.show()
    _flush()
    p.set_lightness_metric(metric, _broadcast=False)
    p.set_chroma_mode(chroma, _broadcast=False)
    p.set_chroma_full(False, _broadcast=False)
    p.set_ab_mode(ab_mode, _broadcast=False)
    p.set_show_ab(show_ab, _broadcast=False)
    p.set_show_unreachable(show_unreachable, _broadcast=False)
    p.set_show_clusters(show_clusters, _broadcast=False)
    p.set_show_lines(show_lines, _broadcast=False)
    p.set_keymap(hp.keymap_core.default_keymap(), _broadcast=False)
    p._layout_picker()
    _flush()
    return p


def _rect_of(panel, widget):
    if widget is None:
        return None
    _QApplication, QPoint, _QRect, _QPointF, _Qt, _C, _P, _PX = _qt()
    try:
        tl = widget.mapTo(panel, QPoint(0, 0))
        return [int(tl.x()), int(tl.y()), int(widget.width()), int(widget.height())]
    except Exception:
        return None


_PANEL_WIDGETS = ("mid_box", "picker", "history", "btn_menu", "menu", "edit_h", "edit_s",
                  "edit_v", "edit_hex", "swatch_cur", "strip_l", "edit_l", "lbl_l",
                  "strip_c", "edit_c", "lbl_c", "strip_a", "edit_a", "lbl_a",
                  "strip_b", "edit_b", "lbl_b")


def _layout_dict(panel):
    out = {"panel": [int(panel.width()), int(panel.height())]}
    for name in _PANEL_WIDGETS:
        w = getattr(panel, name, None)
        if w is None:
            continue
        r = _rect_of(panel, w)
        if r is not None:
            out[name] = r
    return out


def _save_pix(pm, name):
    os.makedirs(RAW, exist_ok=True)
    path = os.path.join(RAW, name + ".png")
    if not pm.save(path, "PNG"):
        raise RuntimeError("QPixmap.save 失败: %s" % path)
    return path


def _save_layout(panel, name, extra=None):
    data = _layout_dict(panel)
    if extra:
        data.update(extra)
    _write_json(os.path.join(RAW, name + ".json"), data)
    return data


def _picker_anchors(c):
    """拾色器内部标注锚点（图标坐标）。"""
    from hsv_picker import render as rd
    g = c._geometry()
    r_mid = (g["r_in"] + g["r_out"]) / 2.0
    out = {
        "geom": {k: (list(v) if isinstance(v, tuple) else v)
                 for k, v in g.items() if k in ("cx", "cy", "r_in", "r_out", "half_sq")},
        "sq": list(g["sq"]),
        "ring_pt": list(rd.pos_from_hue(g, c.h, r_mid)),
        "square_pt": list(c._sv_to_px(c.s, c.v)),
        "gap_pts": [
            [g["cx"] + (g["half_sq"] + g["r_in"]) / 2.0, g["cy"]],
            [g["cx"] - (g["half_sq"] + g["r_in"]) / 2.0, g["cy"]],
            [g["cx"], g["cy"] + (g["half_sq"] + g["r_in"]) / 2.0],
            [g["cx"], g["cy"] - (g["half_sq"] + g["r_in"]) / 2.0],
        ],
    }
    lines = c._through_lines()
    for key in ("iso", "crel"):
        line = lines.get(key)
        if line is not None and len(line[0]) >= 2:
            xs, ys = c._to_px(line[0], line[1], g)
            n = len(xs)
            idxs = [max(1, n // 4), max(1, n // 2), max(1, 3 * n // 4)]
            out[key + "_pts"] = [[float(xs[i]), float(ys[i])] for i in idxs]
    return out


def _panel_color_texts(panel, hp):
    mc = hp.math_core
    r, g, b = panel.picker_rgb()
    L = float(mc.lightness(panel.h, panel.s, panel.v, panel.lightness_metric))
    C = float(mc.ok_L_C(panel.h, panel.s, panel.v)[1])
    crel = float(mc.crel_of_xyz(panel.h, panel.lightness_metric, panel.s, panel.v)[0])
    L_ok, ab_a, ab_b = (float(x) for x in mc.oklab_ab(panel.h, panel.s, panel.v))
    return {
        "hex": "#%02X%02X%02X" % (r, g, b),
        "h": float(panel.h), "s": float(panel.s), "v": float(panel.v),
        "L": L, "C": C, "crel": crel, "a": ab_a, "b": ab_b,
        "gray": float(mc.lightness(panel.h, panel.s, panel.v, "gray")),
        "L_oklab": float(mc.lightness(panel.h, panel.s, panel.v, "oklab")),
        "metric": str(panel.lightness_metric),
    }


def _cap_overview():
    p = _new_panel(880, 1080)
    p.set_history(HIST16, save=False)
    p.set_color(OVERVIEW_COLOR[0], OVERVIEW_COLOR[1], OVERVIEW_COLOR[2], write_fg=False)
    p._layout_picker()
    _flush()
    _save_pix(p.grab(), "01-overview")
    _save_layout(p, "01-overview", {"color": _panel_color_texts(p, _import_pkg())})
    return p


def _cap_ring_square(p):
    p.set_color(RING_COLOR[0], RING_COLOR[1], RING_COLOR[2], write_fg=False)
    _flush()
    c = p.picker
    _save_pix(c.grab(), "02-ring-square")
    data = _picker_anchors(c)
    data["color"] = _panel_color_texts(p, _import_pkg())
    _write_json(os.path.join(RAW, "02-ring-square.json"), data)


def _cap_unreachable():
    hp = _import_pkg()
    mc = hp.math_core
    from hsv_picker import render as rd
    # L=0.70 / C=0.18：可达 78~152 与 262~388，其余为不可达弧，两种斜纹都看得到
    L, C, REQ = 0.70, 0.18, 200.0
    got = mc.sv_at_L_C(90.0, L, C, "oklab")
    p = _new_panel(880, 880)
    p.set_history(HIST16, save=False)
    s, v = (float(got[0]), float(got[1]))
    p.set_color(90.0, s, v, write_fg=False)
    p.set_show_ab(False, _broadcast=False)
    _flush()
    c = p.picker
    g = c._geometry()
    _save_pix(c.grab(), "03-before")
    before = _picker_anchors(c)
    # 环上右键（默认动作 = 锁 L + 锁绝对 C）点在不可达色相上 -> 钳到最近可达边界
    _QApplication, _QPoint, _QRect, _QPointF, Qt, _C, _P, _PX = _qt()
    x, y = rd.pos_from_hue(g, REQ, (g["r_in"] + g["r_out"]) / 2.0)
    c._last_heavy = 0.0
    c.mousePressEvent(Ev(x, y, Qt.RightButton))
    _flush()
    c.mouseReleaseEvent(Ev(x, y, Qt.RightButton, Qt.NoButton))
    _flush()
    _save_pix(c.grab(), "03-after")
    after = _picker_anchors(c)
    spans = mc.hue_reachable_spans(L, C, 1.0, "oklab")
    nearest = mc.nearest_reachable_hue(REQ, L, C, metric="oklab")
    _write_json(os.path.join(RAW, "03-unreachable.json"), {
        "L": L, "C": C, "request_h": REQ,
        "reachable_spans": [[float(a), float(b)] for a, b in spans],
        "nearest_reachable_hue": (None if nearest is None else float(nearest)),
        "before": before, "after": after,
        "before_color": _panel_color_texts(p, hp),
    })
    return p


def _cap_strips():
    p = _new_panel(600, 640, ab_mode="box")
    p.set_history(HIST16, save=False)
    p.set_color(210.0, 0.75, 0.85, write_fg=False)
    _flush()
    _save_pix(p.grab(), "04-panel")
    strips = {}
    for name in ("strip_l", "strip_c", "strip_a", "strip_b"):
        w = getattr(p, name, None)
        if w is None:
            continue
        item = {"width": int(w.width()), "height": int(w.height())}
        try:
            item["ranges"] = [[float(a), float(b)] for a, b in w.ranges()]
        except Exception:
            pass
        try:
            dead = w.dead_mask(max(2, w.width()))
            if dead is not None:
                import numpy as _np
                idx = _np.flatnonzero(_np.asarray(dead, dtype=bool))
                spans = []
                if idx.size:
                    start = prev = int(idx[0])
                    for raw in idx[1:]:
                        i = int(raw)
                        if i != prev + 1:
                            spans.append([start, prev])
                            start = i
                        prev = i
                    spans.append([start, prev])
                item["dead"] = bool(spans)
                item["dead_spans"] = spans
            else:
                item["dead"] = False
        except Exception:
            pass
        strips[name] = item
    _save_layout(p, "04-strips", {"color": _panel_color_texts(p, _import_pkg()),
                                  "strips": strips})
    return p


def _cap_keymap():
    """按键功能对话框：按内容高度放大，保证 24 行 + 底部「恢复默认」全部可见、无滚动裁切。"""
    hp = _import_pkg()
    p = _new_panel(520, 760)
    p.show_keymap_dialog()
    _flush()
    dlg = getattr(p, "_keymap_dialog", None)
    if dlg is None:
        raise RuntimeError("按键功能对话框没有创建")
    if hasattr(dlg, "rebuild"):
        try:
            dlg.rebuild()
        except Exception:
            pass
    table = getattr(dlg, "table", None)
    rows = int(table.rowCount()) if table is not None else 0
    hint_h = int(dlg.lbl_hint.height()) if getattr(dlg, "lbl_hint", None) else 0
    row_h = int(table.rowHeight(0)) if rows else 26
    header_h = int(table.horizontalHeader().height()) if table is not None else 0
    frame = 2 * int(table.frameWidth()) if table is not None else 0
    reset_h = int(dlg.btn_reset.height()) if getattr(dlg, "btn_reset", None) else 0
    lay = dlg.layout()
    m = lay.contentsMargins() if lay is not None else None
    mt, mb = (int(m.top()), int(m.bottom())) if m is not None else (9, 9)
    sp = int(lay.spacing()) if lay is not None and lay.spacing() >= 0 else 6
    need_h = mt + mb + hint_h + header_h + rows * row_h + frame + reset_h + 2 * sp + 8
    try:
        dlg.resize(820, max(int(dlg.minimumHeight()), int(need_h)))
    except Exception:
        pass
    for _ in range(8):
        _flush()
        if table is None:
            break
        vmax = int(table.verticalScrollBar().maximum())
        hmax = int(table.horizontalScrollBar().maximum())
        if vmax == 0 and hmax == 0:
            break
        grow_h = (vmax + 1) * row_h + 12 if vmax > 0 else 0
        grow_w = 60 if hmax > 0 else 0
        dlg.resize(int(dlg.width()) + grow_w, int(dlg.height()) + grow_h)
    _flush()
    scroll = ([0, 0] if table is None else
              [int(table.verticalScrollBar().maximum()),
               int(table.horizontalScrollBar().maximum())])
    _save_pix(dlg.grab(), "05-keymap")
    _write_json(os.path.join(RAW, "05-keymap.json"), {
        "size": [int(dlg.width()), int(dlg.height())], "rows": int(rows),
        "scroll_max": scroll, "hint_h": int(hint_h),
        "title": str(dlg.windowTitle()),
    })
    dlg.hide()
    p.hide()
    return p


def _cap_popup():
    hp = _import_pkg()
    _QApplication, _QPoint, _QRect, _QPointF, Qt, _C, _P, _PX = _qt()
    partner = _new_panel(600, 640)
    partner.set_history(HIST16, save=False)
    partner.set_color(30.0, 0.8, 0.9, write_fg=False)
    _flush()
    k = hp.Krita.instance()
    old_size = k.readSetting("", "HsvPickerPopupSizeUser", "") or ""
    try:
        # 文档展示出厂默认尺寸：临时清掉用户尺寸记忆，抓完恢复
        if old_size:
            k.writeSetting("", "HsvPickerPopupSizeUser", "")
        pop = hp.HsvPickerPopup(partner)
        pop.setAttribute(Qt.WA_DontShowOnScreen, True)
        pop.show()
        _flush()
        pop.panel.set_history(HIST16, save=False)
        pop.panel.set_color(30.0, 0.8, 0.9, write_fg=False)
        pop.panel._layout_picker()
        _flush()
        _save_pix(pop.grab(), "06-popup")
        _write_json(os.path.join(RAW, "06-popup.json"), {
            "size": [int(pop.width()), int(pop.height())],
            "panel": [int(pop.panel.width()), int(pop.panel.height())],
            "color": _panel_color_texts(pop.panel, hp),
        })
        return pop
    finally:
        if old_size:
            k.writeSetting("", "HsvPickerPopupSizeUser", old_size)


def _cap_overlay():
    hp = _import_pkg()
    p = _new_panel(600, 640)
    p.set_preview_mode("hover", _broadcast=False)
    p.set_history(["#FF8800", "#33AACC"], save=False)
    p.set_color(280.0, 0.80, 0.90, write_fg=False)
    # 上一次 / 上上次：直接给定三格取值，保证图像稳定可复现
    p._preview_last_rgb = (255, 136, 0)
    p._preview_older_rgb = (51, 170, 204)
    p._preview_update(start_countdown=False)
    _flush()
    ov = p.preview_overlay()
    _save_pix(ov.grab(), "07-overlay")
    # 面板右侧局部，用于演示浮层贴边
    p._layout_picker()
    _flush()
    _save_pix(p.grab(), "07-panel")
    _save_layout(p, "07-overlay", {
        "overlay_size": [int(ov.width()), int(ov.height())],
        "overlay_cells": [[float(r.x()), float(r.y()), float(r.width()), float(r.height())]
                          for r, _c in [(r, c) for r, c in ov.cell_rects()]],
        "color": _panel_color_texts(p, hp),
    })
    return p


def _cap_history():
    p = _new_panel(560, 620, show_ab=True)
    p.set_history(HIST16 + ["#111111", "#F5F5F5"], save=False)
    p.set_color(320.0, 0.65, 0.95, write_fg=False)
    _flush()
    _save_pix(p.grab(), "08-panel")
    _save_layout(p, "08-history", {"color": _panel_color_texts(p, _import_pkg())})
    return p

def _menu_items(menu):
    out = []
    for act in menu.actions():
        if act.isSeparator():
            continue
        g = menu.actionGeometry(act)
        out.append({
            "text": str(act.text()),
            "geom": [int(g.x()), int(g.y()), int(g.width()), int(g.height())],
            "submenu": bool(act.menu()),
            "checkable": bool(act.isCheckable()),
            "checked": bool(act.isCheckable() and act.isChecked()),
            "enabled": bool(act.isEnabled()),
        })
    return out


SETTINGS_SUBMENU = "preview"     # 设置菜单图只展开这一个子菜单（其余两个在正文列表里解释）


def _cap_settings():
    hp = _import_pkg()
    _QApplication, QPoint, _QRect, _QPointF, Qt, _C, _P, _PX = _qt()
    p = _new_panel(520, 760)
    menu = p.menu
    menu.popup(QPoint(360, 360))
    _flush()
    _save_pix(menu.grab(), "09-menu")
    meta = {"menu_size": [int(menu.width()), int(menu.height())],
            "menu_items": _menu_items(menu), "subs": {}}
    menu_pos = menu.pos()
    for name, sub in (("metric", p.menu_metric), ("chroma", p.menu_chroma),
                      ("preview", p.menu_preview)):
        geom = menu.actionGeometry(sub.menuAction())
        sub.popup(menu.mapToGlobal(QPoint(geom.right() + 2, geom.top())))
        _flush()
        _save_pix(sub.grab(), "09-menu-" + name)
        off = sub.pos() - menu_pos
        meta["subs"][name] = {
            "offset": [int(off.x()), int(off.y())],
            "size": [int(sub.width()), int(sub.height())],
            "items": _menu_items(sub),
        }
    about = getattr(p, "act_about", None)
    meta["about"] = None
    if about is not None:
        g = menu.actionGeometry(about)
        meta["about"] = {"text": str(about.text()),
                         "geom": [int(g.x()), int(g.y()), int(g.width()), int(g.height())]}
    for sub in (p.menu_metric, p.menu_chroma, p.menu_preview):
        sub.hide()
    menu.hide()
    _flush()
    _write_json(os.path.join(RAW, "09-settings.json"), meta)
    p.hide()
    return p

def _cap_metric():
    hp = _import_pkg()
    meta = {"color_hsv": [0.0, 1.0, 1.0]}
    for mode in ("oklab", "gray"):
        p = _new_panel(880, 880, metric=mode)
        p.set_history(HIST16, save=False)
        p.set_color(0.0, 1.0, 1.0, write_fg=False)
        _flush()
        _save_pix(p.grab(), "10-" + mode)
        _save_layout(p, "10-" + mode, {"color": _panel_color_texts(p, hp)})
        meta[mode] = _panel_color_texts(p, hp)
        p.hide()
    _write_json(os.path.join(RAW, "10-metric.json"), meta)


def _cap_gif_ring():
    hp = _import_pkg()
    _QApplication, _QPoint, _QRect, _QPointF, Qt, _C, _P, _PX = _qt()
    from hsv_picker import render as rd
    p = _new_panel(520, 760)
    p.set_history(HIST16, save=False)
    p.set_color(20.0, 0.85, 0.95, write_fg=False)
    p._layout_picker()
    _flush()
    c = p.picker
    g = c._geometry()
    layout = _layout_dict(p)
    r_mid = (g["r_in"] + g["r_out"]) / 2.0
    frames = 14
    hues = [20.0 + (320.0 - 20.0) * i / (frames - 1) for i in range(frames)]
    frames_meta = []
    x0, y0 = rd.pos_from_hue(g, hues[0], r_mid)
    c._last_heavy = 0.0
    c.mousePressEvent(Ev(x0, y0, Qt.LeftButton))
    _flush()
    for i, hue in enumerate(hues):
        if i > 0:
            x, y = rd.pos_from_hue(g, hue, r_mid)
            c._last_heavy = 0.0
            c.mouseMoveEvent(Ev(x, y, Qt.NoButton, Qt.LeftButton))
            _flush()
        _save_pix(p.grab(), "ring-%02d" % i)
        frames_meta.append(_panel_color_texts(p, hp))
    x, y = rd.pos_from_hue(g, hues[-1], r_mid)
    c.mouseReleaseEvent(Ev(x, y, Qt.LeftButton, Qt.NoButton))
    _flush()
    _write_json(os.path.join(RAW, "ring.json"),
                {"layout": layout, "frames": frames_meta})
    p.hide()
    return p


def _cap_gif_ab():
    hp = _import_pkg()
    _QApplication, _QPoint, _QRect, _QPointF, Qt, _C, _P, _PX = _qt()
    p = _new_panel(760, 900, ab_mode="box")
    p.set_history(HIST16, save=False)
    p.set_color(210.0, 0.70, 0.80, write_fg=False)
    p._layout_picker()
    _flush()
    layout = _layout_dict(p)
    strip = p.strip_a
    t0 = float(strip.value)
    frames = 12
    if t0 < 0.65:
        ts = [t0 + (0.94 - t0) * i / (frames - 1) for i in range(frames)]
    else:
        ts = [t0 - (t0 - 0.06) * i / (frames - 1) for i in range(frames)]
    w = max(2, strip.width())
    x0 = int(round(ts[0] * (w - 1)))
    strip.mousePressEvent(Ev(x0, 11, Qt.LeftButton))
    _flush()
    frames_meta = []
    for i, t in enumerate(ts):
        if i > 0:
            x = int(round(t * (w - 1)))
            strip.mouseMoveEvent(Ev(x, 11, Qt.NoButton, Qt.LeftButton))
            _flush()
        _save_pix(p.grab(), "ab-%02d" % i)
        frames_meta.append(_panel_color_texts(p, hp))
    x = int(round(ts[-1] * (w - 1)))
    strip.mouseReleaseEvent(Ev(x, 11, Qt.LeftButton, Qt.NoButton))
    _flush()
    _write_json(os.path.join(RAW, "ab.json"),
                {"layout": layout, "frames": frames_meta, "axis": "a", "t": ts})
    p.hide()
    return p


def _cap_02_standalone():
    p = _new_panel(880, 1080)
    p.set_history(HIST16, save=False)
    p.set_color(RING_COLOR[0], RING_COLOR[1], RING_COLOR[2], write_fg=False)
    _flush()
    _cap_ring_square(p)
    p.hide()
    return p





def _cap_gif_first():
    """首屏 GIF：完整面板上的两个核心动作——

    1) 色相环左键（默认 = 锁明度 L + 锁相对彩度 C_rel）转色相：浓淡比例不变；
    2) 拖 L 条改明度（默认口径保持 C_rel）：浓淡比例仍然不变。
    """
    hp = _import_pkg()
    _QApplication, _QPoint, _QRect, _QPointF, Qt, _C, _P, _PX = _qt()
    from hsv_picker import render as rd
    p = _new_panel(720, 880)
    p.set_history(HIST16, save=False)
    p.set_color(210.0, 0.75, 0.85, write_fg=False)
    p._layout_picker()
    _flush()
    c = p.picker
    g = c._geometry()
    layout = _layout_dict(p)
    frames_meta = []
    state = {"i": 0}

    def shot(phase):
        _flush()
        _save_pix(p.grab(), "first-%02d" % state["i"])
        item = _panel_color_texts(p, hp)
        item["phase"] = phase
        frames_meta.append(item)
        state["i"] += 1

    shot("start")
    # ---- 动作 1：环上左键（锁 L + 锁 C_rel）转色相 ----
    r_mid = (g["r_in"] + g["r_out"]) / 2.0
    hues = [210.0, 175.0, 140.0, 105.0, 70.0, 35.0, 350.0]
    x0, y0 = rd.pos_from_hue(g, hues[0], r_mid)
    c._last_heavy = 0.0
    c.mousePressEvent(Ev(x0, y0, Qt.LeftButton))
    for hue in hues[1:]:
        x, y = rd.pos_from_hue(g, hue, r_mid)
        c._last_heavy = 0.0
        c.mouseMoveEvent(Ev(x, y, Qt.NoButton, Qt.LeftButton))
        shot("ring")
    x, y = rd.pos_from_hue(g, hues[-1], r_mid)
    c.mouseReleaseEvent(Ev(x, y, Qt.LeftButton, Qt.NoButton))
    _flush()
    # ---- 动作 2：拖 L 条改明度（保持 C_rel）----
    L0 = float(_panel_color_texts(p, hp)["L"])
    targets = [max(0.06, min(0.94, L0 + d))
               for d in (-0.05, -0.15, -0.25, -0.35, -0.45)]
    strip = p.strip_l
    w = max(2, strip.width())
    t0 = float(strip.value)
    x0 = int(round(t0 * (w - 1)))
    strip.mousePressEvent(Ev(x0, 11, Qt.LeftButton))
    _flush()
    for t in targets:
        strip.mouseMoveEvent(Ev(int(round(t * (w - 1))), 11, Qt.NoButton, Qt.LeftButton))
        shot("lightness")
    strip.mouseReleaseEvent(Ev(int(round(targets[-1] * (w - 1))), 11,
                               Qt.LeftButton, Qt.NoButton))
    shot("end")
    _write_json(os.path.join(RAW, "first.json"),
                {"layout": layout, "frames": frames_meta,
                 "ring_hues": hues, "lightness_targets": targets})
    p.hide()
    return p

def _requested():
    data = _read_json(os.path.join(RAW, "only.json"), {})
    only = data.get("only") if isinstance(data, dict) else None
    if not only:
        return None
    return [str(x) for x in only]


def main(*args):
    """kritarunner 入口：-s make_manual_shots -f main。"""
    global _APP
    import traceback
    os.makedirs(RAW, exist_ok=True)
    try:
        QApplication = _qt()[0]
        _APP = QApplication.instance() or QApplication([])
        _dark_palette(_APP)
        hp = _import_pkg()
        _log("== make_manual_shots: 仓库代码 = %s" % hp.__file__)
        only = _requested()
        want = list(only) if only else list(CAPTURE_FUNCS.keys())
        if only is None and "02-ring-square" in want:
            p = _cap_overview()           # 01 与 02 共用同一块面板，省一次构造
            _cap_ring_square(p)
            p.hide()
            want = [x for x in want if x not in ("01-overview", "02-ring-square")]
        for name in want:
            fn = CAPTURE_FUNCS.get(name)
            if fn is None:
                continue
            _log("-- capture %s" % name)
            obj = fn()
            if obj is not None and hasattr(obj, "hide"):
                try:
                    obj.hide()
                except Exception:
                    pass
        _write_json(os.path.join(RAW, "status.json"), {
            "ok": True, "error": "", "repo": REPO, "pkg_file": hp.__file__,
            "only": only or list(CAPTURE_FUNCS.keys()),
        })
        _log("== make_manual_shots: 抓图完成 pkg=%s" % hp.__file__)
        return 0
    except Exception:
        tb = traceback.format_exc()
        _write_json(os.path.join(RAW, "status.json"), {"ok": False, "error": tb})
        _log("!! 抓图失败:\n" + tb)
        return 2


# ======================================================================
# 二、PIL 侧：无文字成品图 / GIF / 自检
# ======================================================================
# 硬规则：成品图只保留界面自身像素，不叠加任何标题 / 图例 / 说明文字；
# 对比图允许语言中性数字编号（03/10 = 1、2；11/12 = 1/2/3 与第一组行号 1~4），
# 含义全部写在正文，中英共用同一批图。浮层、弹窗按实际像素呈现，
# 不放大到模糊、不描边、不遮挡 UI（04 为 2× 最近邻整数放大，像素不糊）。

CAPTURE_FUNCS = {
    "01-overview": _cap_overview,
    "02-ring-square": _cap_02_standalone,
    "03-unreachable": _cap_unreachable,
    "04-strips": _cap_strips,
    "05-keymap": _cap_keymap,
    "06-popup": _cap_popup,
    "07-overlay": _cap_overlay,
    "08-history": _cap_history,
    "09-settings": _cap_settings,
    "10-metric": _cap_metric,
    "demo-first.gif": _cap_gif_first,
    "demo-ring.gif": _cap_gif_ring,
    "demo-ab.gif": _cap_gif_ab,
}
_CAP_PREFIX = {
    "01-overview": ["01-"], "02-ring-square": ["02-"], "03-unreachable": ["03-"],
    "04-strips": ["04-"], "05-keymap": ["05-"], "06-popup": ["06-"],
    "07-overlay": ["07-"], "08-history": ["08-"], "09-settings": ["09-"],
    "10-metric": ["10-"], "demo-first.gif": ["first"], "demo-ring.gif": ["ring"],
    "demo-ab.gif": ["ab"],
}

PNG_IDS = (
    "01-overview", "02-ring-square", "03-unreachable", "04-strips",
    "05-keymap", "06-popup", "07-overlay", "08-history", "09-settings",
    "10-metric", "11-ring-modes-crel60", "12-ring-modes-crel100",
)
GIF_IDS = ("demo-first.gif", "demo-ring.gif", "demo-ab.gif")
PNG_REQUIRED = tuple(x + ".png" for x in PNG_IDS)

# 期望像素（由本工具生成，check 逐张核对）
EXPECTED_SIZE = {
    "01-overview.png": (880, 1080),
    "02-ring-square.png": (846, 846),
    "03-unreachable.png": (1556, 769),
    "04-strips.png": (1200, 276),
    "05-keymap.png": (820, 731),
    "06-popup.png": (493, 630),
    "07-overlay.png": (700, 640),
    "08-history.png": (240, 501),
    "09-settings.png": (605, 510),
    "10-metric.png": (1778, 880),
    "11-ring-modes-crel60.png": (856, 1292),
    "12-ring-modes-crel100.png": (856, 1292),
}
# 禁止再出现的旧资产（logo / 社交预览）；check 会逐一确认文件不存在
FORBIDDEN_IMAGES = ("logo-512.png", "logo-256.png", "logo-128.png", "logo-64.png")
FORBIDDEN_SOCIAL = os.path.join("manual", "social-preview.png")


def _pil():
    from PIL import Image, ImageDraw
    return Image, ImageDraw


def _open_raw(name, mode="RGB"):
    Image, _D = _pil()
    return Image.open(os.path.join(RAW, name + ".png")).convert(mode)


def _panel_bg():
    """从原始抓图空白角落取样面板底色，得不到就用 KritaDark 窗口色。"""
    try:
        Image, _D = _pil()
        im = Image.open(os.path.join(RAW, "01-overview.png")).convert("RGB")
        return im.getpixel((2, 2))
    except Exception:
        return (71, 71, 71)


def _on_bg(im, bg=None):
    """把带透明通道的抓图压到面板底色上：只补背景，不改 UI 像素。"""
    Image, _D = _pil()
    im = im.convert("RGBA")
    out = Image.new("RGB", im.size, bg or _panel_bg())
    out.paste(im, (0, 0), im)
    return out


def _number_badge(im, text, cx, cy, radius=17):
    """叠一个语言中性的数字圆徽（白底深字）；只允许放在空白角，不得遮挡控件。"""
    from PIL import ImageFont
    Image, ImageDraw = _pil()
    ss = 4
    size = radius * 2
    layer = Image.new("RGBA", (size * ss, size * ss), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    d.ellipse([2 * ss, 2 * ss, (size - 2) * ss, (size - 2) * ss],
              fill=(242, 242, 245, 255))
    font = None
    for path in ("C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/msyhbd.ttc",
                 "C:/Windows/Fonts/DejaVuSans-Bold.ttf"):
        try:
            font = ImageFont.truetype(path, int(radius * 1.2 * ss))
            break
        except Exception:
            font = None
    if font is None:
        font = ImageFont.load_default()
    box = d.textbbox((0, 0), str(text), font=font)
    d.text(((size * ss - (box[2] - box[0])) / 2.0 - box[0],
            (size * ss - (box[3] - box[1])) / 2.0 - box[1]),
           str(text), fill=(26, 26, 30, 255), font=font)
    layer = layer.resize((size, size), Image.LANCZOS)
    im.paste(layer, (int(round(cx - radius)), int(round(cy - radius))), layer)


def _save_png(im, name):
    os.makedirs(IMAGES, exist_ok=True)
    path = os.path.join(IMAGES, name)
    im.convert("RGB").save(path, "PNG", optimize=True)
    return path


def _save_gif(frames, name, duration=120, colors=128):
    Image, _D = _pil()
    os.makedirs(IMAGES, exist_ok=True)
    path = os.path.join(IMAGES, name)
    pal = [f.convert("RGB").convert("P", palette=Image.ADAPTIVE, colors=colors)
           for f in frames]
    pal[0].save(path, "GIF", save_all=True, append_images=pal[1:],
                duration=duration, loop=0, optimize=True)
    return path


def _raw_frames(prefix):
    names = sorted(n for n in os.listdir(RAW)
                   if n.startswith(prefix) and n.endswith(".png"))
    if not names:
        raise RuntimeError("原始帧缺失：%s*（先运行 --capture）" % prefix)
    return [_open_raw(n[:-4]) for n in names]


def build_01_overview():
    _save_png(_open_raw("01-overview"), "01-overview.png")


def build_02_ring_square():
    """从总览原图按 picker 实际矩形裁剪，保留真实底色。"""
    base = _open_raw("01-overview")
    lay = _read_json(os.path.join(RAW, "01-overview.json"), {})
    r = lay.get("picker") or [6, 34, 846, 846]
    box = (int(r[0]), int(r[1]), int(r[0] + r[2]), int(r[1] + r[3]))
    _save_png(base.crop(box), "02-ring-square.png")


def build_03_unreachable():
    """左=① 有不可达色相提示，右=② 环上拖动被钳到最近可达边界；两图并排。

    图内只叠语言中性的 ①/② 圆徽（正文解释含义），不写任何说明文字。
    """
    Image, _D = _pil()
    before = _on_bg(_open_raw("03-before", "RGBA"))
    after = _on_bg(_open_raw("03-after", "RGBA"))
    gap = 18
    W = before.width + gap + after.width
    H = max(before.height, after.height)
    canvas = Image.new("RGB", (W, H), _panel_bg())
    canvas.paste(before, (0, 0))
    canvas.paste(after, (before.width + gap, 0))
    _number_badge(canvas, "1", 22, 22)
    _number_badge(canvas, "2", before.width + gap + 22, 22)
    _save_png(canvas, "03-unreachable.png")


def build_04_strips():
    """裁出 L / C / a / b 四条色条 + 行标签 + 数值框，2× 最近邻整数放大（不模糊）。"""
    Image, _D = _pil()
    base = _open_raw("04-panel")
    lay = _read_json(os.path.join(RAW, "04-strips.json"), {})
    rows = [lay.get(k) for k in ("edit_l", "strip_l", "strip_b", "edit_b")]
    rows = [r for r in rows if isinstance(r, list) and len(r) == 4]
    if rows:
        y0 = max(0, min(int(r[1]) for r in rows) - 3)
        y1 = min(base.height, max(int(r[1] + r[3]) for r in rows) + 6)
    else:
        y0, y1 = 503, 640
    crop = base.crop((0, y0, base.width, y1))
    crop = crop.resize((crop.width * 2, crop.height * 2), Image.NEAREST)
    _save_png(crop, "04-strips.png")


def build_05_keymap():
    _save_png(_open_raw("05-keymap"), "05-keymap.png")


def build_06_popup():
    _save_png(_open_raw("06-popup"), "06-popup.png")


def build_07_overlay():
    """面板 + 预览浮层：浮层保持真实 100×150，紧贴面板右缘。"""
    Image, _D = _pil()
    panel = _open_raw("07-panel")
    ov = _open_raw("07-overlay")
    lay = _read_json(os.path.join(RAW, "07-overlay.json"), {})
    top = int((lay.get("picker") or [57, 6, 463, 463])[1])
    canvas = Image.new("RGB", (panel.width + ov.width, panel.height), _panel_bg())
    canvas.paste(panel, (0, 0))
    canvas.paste(ov, (panel.width, top))
    _save_png(canvas, "07-overlay.png")


def build_08_history():
    """历史列 + HEX / 当前色块：两处实际像素裁切后拼在一张图上，不缩放。"""
    Image, _D = _pil()
    base = _open_raw("08-panel")
    lay = _read_json(os.path.join(RAW, "08-history.json"), {})
    hexr = lay.get("edit_hex") or [364, 452, 89, 30]
    swr = lay.get("swatch_cur") or [463, 452, 131, 30]
    hist = lay.get("history") or [538, 6, 16, 443]
    x0 = max(0, min(int(hexr[0]), int(swr[0])) - 44)
    x1 = min(base.width, max(int(hexr[0] + hexr[2]), int(swr[0] + swr[2])) + 6)
    hy = int(hexr[1])
    hex_crop = base.crop((x0, max(0, hy - 4), x1,
                          min(base.height, hy + int(hexr[3]) + 6)))
    hx0 = max(0, int(hist[0]) - 2)
    hx1 = min(base.width, int(hist[0] + hist[2]) + 4)
    hist_crop = base.crop((hx0, max(0, int(hist[1]) - 4), hx1,
                           min(base.height, int(hist[1] + hist[3]) + 6)))
    W = hex_crop.width
    H = 8 + hex_crop.height + hist_crop.height
    canvas = Image.new("RGB", (W, H), _panel_bg())
    canvas.paste(hex_crop, (0, 0))
    canvas.paste(hist_crop, (W - hist_crop.width, hex_crop.height + 8))
    _save_png(canvas, "08-history.png")

def build_09_settings():
    """设置菜单 + 子菜单截图，按实际像素纵向排开，互不遮挡，不加说明文字。"""
    Image, _D = _pil()
    menu = _open_raw("09-menu")
    lay = _read_json(os.path.join(RAW, "09-settings.json"), {})
    placed = []
    y = 150
    for sub in ("chroma", "metric", "preview"):
        meta = (lay.get("subs") or {}).get(sub) or {}
        name = "09-menu-" + sub
        if not os.path.isfile(os.path.join(RAW, name + ".png")):
            continue
        im = _open_raw(name)
        off = meta.get("offset") or [menu.width + 1, 0]
        placed.append((im, int(off[0]), int(y)))
        y += im.height + 4
    height = max(menu.height, (placed[-1][2] + placed[-1][0].height) if placed else menu.height)
    canvas = Image.new("RGB", (605, height), menu.getpixel((2, 2)))
    canvas.paste(menu, (0, 0))
    for im, x, yy in placed:
        canvas.paste(im, (x, yy))
    _save_png(canvas, "09-settings.png")

def build_10_metric():
    """Oklab L / 灰阶两种明度标准的同一面板并排：左 ① Oklab L、右 ② 灰阶。"""
    Image, _D = _pil()
    a = _open_raw("10-oklab")
    b = _open_raw("10-gray")
    gap = 18
    canvas = Image.new("RGB", (a.width + gap + b.width, max(a.height, b.height)),
                       _panel_bg())
    canvas.paste(a, (0, 0))
    canvas.paste(b, (a.width + gap, 0))
    _number_badge(canvas, "1", 22, 22)
    _number_badge(canvas, "2", a.width + gap + 22, 22)
    _save_png(canvas, "10-metric.png")


def _build_ring_mode(crel, name):
    """调用 preview_ring_modes.py 生成无文字、只带语言中性编号的模式对比图。"""
    script = os.path.join(REPO, "tools", "preview_ring_modes.py")
    out = os.path.join(IMAGES, name)
    cmd = [sys.executable, script, "--no-labels", "--badges",
           "--crel", crel, "--out", out]
    proc = subprocess.run(cmd, cwd=REPO, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, timeout=600)
    if proc.returncode != 0 or not os.path.isfile(out):
        raise RuntimeError("生成 %s 失败：\n%s"
                           % (name, proc.stdout.decode("utf-8", "replace")))


def build_demo_first():
    frames = _raw_frames("first-")
    _save_gif(frames, "demo-first.gif", duration=260, colors=128)


def build_demo_ring():
    frames = _raw_frames("ring-")
    _save_gif(frames, "demo-ring.gif", duration=110, colors=160)


def build_demo_ab():
    frames = _raw_frames("ab-")
    _save_gif(frames, "demo-ab.gif", duration=120, colors=160)


BUILD_FUNCS = {
    "01-overview": build_01_overview,
    "02-ring-square": build_02_ring_square,
    "03-unreachable": build_03_unreachable,
    "04-strips": build_04_strips,
    "05-keymap": build_05_keymap,
    "06-popup": build_06_popup,
    "07-overlay": build_07_overlay,
    "08-history": build_08_history,
    "09-settings": build_09_settings,
    "10-metric": build_10_metric,
    "11-ring-modes-crel60": lambda: _build_ring_mode("0.60", "11-ring-modes-crel60.png"),
    "12-ring-modes-crel100": lambda: _build_ring_mode("1.00", "12-ring-modes-crel100.png"),
    "demo-first.gif": build_demo_first,
    "demo-ring.gif": build_demo_ring,
    "demo-ab.gif": build_demo_ab,
}


def build_all(only=None):
    os.makedirs(IMAGES, exist_ok=True)
    ids = [x for x in BUILD_FUNCS if (only is None or x in only)]
    if not ids:
        raise RuntimeError("没有可构建的资产：%s" % ",".join(only or []))
    for i in ids:
        BUILD_FUNCS[i]()
        _log("[build] %s" % i)
    return ids


def _kb(path):
    return "%.1f KB" % (os.path.getsize(path) / 1024.0)


def check_assets():
    """校验产物：存在、尺寸、帧数、体积；并确认 logo / social-preview 已不存在。"""
    from PIL import Image
    ok = True
    rows = []
    for name in PNG_REQUIRED:
        path = os.path.join(IMAGES, name)
        if not os.path.isfile(path):
            rows.append((name, "-", "-", "缺失"))
            ok = False
            continue
        im = Image.open(path)
        exp = EXPECTED_SIZE.get(name)
        note = "OK"
        if exp and im.size != exp:
            note = "尺寸错（期望 %dx%d）" % exp
            ok = False
        rows.append((name, "%dx%d" % im.size, _kb(path), note))
    for name in GIF_IDS:
        path = os.path.join(IMAGES, name)
        if not os.path.isfile(path):
            rows.append((name, "-", "-", "缺失"))
            ok = False
            continue
        im = Image.open(path)
        n = getattr(im, "n_frames", 1)
        size = os.path.getsize(path)
        note = "OK"
        if not (10 <= n <= 20):
            note = "帧数异常"
            ok = False
        if size > GIF_LIMIT:
            note = "超过 1.5MB"
            ok = False
        if name == "demo-first.gif" and im.size[0] < 600:
            note = "首屏 GIF 宽度 < 600"
            ok = False
        rows.append((name, "%dx%d / %d 帧" % (im.size[0], im.size[1], n),
                     "%.2f MB" % (size / 1024.0 / 1024.0), note))
    # 首屏 GIF 原始帧不变量：环上动作锁 L + 锁 C_rel，拖 L 条保持 C_rel
    first = _read_json(os.path.join(RAW, "first.json"))
    if isinstance(first, dict) and first.get("frames"):
        frames = first["frames"]

        def _spread(key, phase):
            vals = [float(f[key]) for f in frames
                    if f.get("phase") == phase and f.get(key) is not None]
            return (max(vals) - min(vals)) if len(vals) >= 2 else None

        n_ring = len([f for f in frames if f.get("phase") == "ring"])
        n_light = len([f for f in frames if f.get("phase") == "lightness"])
        d_l_ring = _spread("L", "ring")
        d_c_ring = _spread("crel", "ring")
        d_c_light = _spread("crel", "lightness")
        note = "OK"
        if n_ring < 4 or n_light < 4:
            note = "动作帧不足（环 %d / 明度 %d）" % (n_ring, n_light)
        elif d_l_ring is None or d_l_ring > 2e-3:
            note = "环上 L 漂移 %.5f" % (d_l_ring if d_l_ring is not None else -1)
        elif d_c_ring is None or d_c_ring > 2e-3:
            note = "环上 C_rel 漂移 %.5f" % (d_c_ring if d_c_ring is not None else -1)
        elif d_c_light is None or d_c_light > 2e-3:
            note = "拖 L 条时 C_rel 漂移 %.5f" % (d_c_light if d_c_light is not None else -1)
        if note != "OK":
            ok = False
        rows.append(("demo-first 原始帧", "%d 帧 / 环 %d / 明度 %d" % (len(frames), n_ring, n_light),
                     "", note))
    kmeta = _read_json(os.path.join(RAW, "05-keymap.json"))
    if isinstance(kmeta, dict) and "scroll_max" in kmeta:
        note = "OK"
        if list(kmeta.get("scroll_max") or []) != [0, 0]:
            note = "对话框仍有滚动裁切 %s" % (kmeta.get("scroll_max"),)
            ok = False
        rows.append(("05-keymap 滚动", "rows=%s" % kmeta.get("rows"), "", note))
    for name in FORBIDDEN_IMAGES:
        if os.path.exists(os.path.join(IMAGES, name)):
            rows.append((name, "-", "-", "应删除但仍存在"))
            ok = False
    social = os.path.join(REPO, FORBIDDEN_SOCIAL)
    if os.path.exists(social):
        rows.append((FORBIDDEN_SOCIAL, "-", "-", "应删除但仍存在"))
        ok = False
    print("%-30s %-20s %-12s %s" % ("文件", "像素 / 帧", "体积", "结论"))
    print("-" * 82)
    for r in rows:
        print("%-30s %-20s %-12s %s" % r)
    print("-" * 82)
    print("图片资产校验：%s" % ("全部通过" if ok else "存在失败"))
    return 0 if ok else 1


def make_contact_sheet(out_path=None):
    """给架构师目检的 contact sheet：12 张 PNG 缩略图 + 3 个 GIF 的首/中/末帧。

    这是 tmp/ 下的评审件（不是手册资产），因此允许写文件名字幕。
    """
    Image, ImageDraw = _pil()
    from PIL import ImageFont
    tiles = []
    for name in PNG_REQUIRED:
        path = os.path.join(IMAGES, name)
        if os.path.isfile(path):
            tiles.append((name, Image.open(path).convert("RGB")))
    for name in GIF_IDS:
        path = os.path.join(IMAGES, name)
        if not os.path.isfile(path):
            continue
        gif = Image.open(path)
        n = getattr(gif, "n_frames", 1)
        for idx, tag in ((0, "first"), (n // 2, "mid"), (max(0, n - 1), "last")):
            gif.seek(idx)
            tiles.append(("%s %s" % (name, tag), gif.convert("RGB").copy()))
    cols = 4
    thumb = 360
    pad = 12
    label_h = 24
    rows = (len(tiles) + cols - 1) // cols
    cell_w = thumb + pad * 2
    cell_h = thumb + label_h + pad * 2
    sheet = Image.new("RGB", (cols * cell_w, rows * cell_h), (24, 24, 28))
    d = ImageDraw.Draw(sheet)
    font = None
    for path in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/arial.ttf"):
        try:
            font = ImageFont.truetype(path, 15)
            break
        except Exception:
            font = None
    if font is None:
        font = ImageFont.load_default()
    for i, (label, im) in enumerate(tiles):
        r, c = divmod(i, cols)
        x0 = c * cell_w + pad
        y0 = r * cell_h + pad
        scale = min(thumb / float(im.width), thumb / float(im.height), 1.0)
        tw = max(1, int(im.width * scale))
        th = max(1, int(im.height * scale))
        th_im = im.resize((tw, th), Image.LANCZOS)
        px = x0 + (thumb - tw) // 2
        py = y0 + (thumb - th) // 2
        d.rectangle([x0 - 1, y0 - 1, x0 + thumb, y0 + thumb], outline=(70, 70, 80))
        sheet.paste(th_im, (px, py))
        d.text((x0, y0 + thumb + 4), label, fill=(220, 220, 226), font=font)
    path = out_path or os.path.join(REPO, "tmp", "_review_after_D3.png")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    sheet.save(path, "PNG", optimize=True)
    _log("[contact] %s  (%dx%d, %d 格)" % (path, sheet.width, sheet.height, len(tiles)))
    return path


def sync_probe():
    os.makedirs(PROBE_DIR, exist_ok=True)
    src = os.path.abspath(__file__)
    dst = os.path.join(PROBE_DIR, "make_manual_shots.py")
    shutil.copyfile(src, dst)
    _log("[sync] %s -> %s" % (src, dst))
    return dst


def run_capture(only=None):
    sync_probe()
    os.makedirs(RAW, exist_ok=True)
    prefixes = []
    for name in (only or []):
        prefixes.extend(_CAP_PREFIX.get(name, []))
    for fn in os.listdir(RAW):
        if not (fn.endswith(".png") or fn.endswith(".json")):
            continue
        drop = only is None
        if not drop:
            drop = (fn == "status.json" or fn == "only.json"
                    or (prefixes and fn.startswith(tuple(prefixes))))
        if drop:
            try:
                os.remove(os.path.join(RAW, fn))
            except OSError:
                pass
    only_path = os.path.join(RAW, "only.json")
    if only:
        _write_json(only_path, {"only": list(only)})
    elif os.path.isfile(only_path):
        try:
            os.remove(only_path)
        except OSError:
            pass
    cmd = [KRITARUNNER, "-s", "make_manual_shots", "-f", "main"]
    _log("[capture] " + " ".join(cmd))
    proc = subprocess.run(cmd, cwd=REPO, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                          timeout=1800, env=dict(os.environ, MOMO_REPO=REPO))
    out = proc.stdout.decode("utf-8", "replace")
    err = proc.stderr.decode("utf-8", "replace")
    tail = "\n".join((out + "\n" + err).strip().splitlines()[-14:])
    _log(tail)
    status = _read_json(os.path.join(RAW, "status.json"), {})
    if not status or not status.get("ok"):
        raise RuntimeError("kritarunner 抓图失败，rc=%s：\n%s"
                           % (proc.returncode, status.get("error", "")))
    _log("[capture] 原始帧：%d 个文件"
         % len([n for n in os.listdir(RAW) if n.endswith(".png")]))


def cli(argv=None):
    global _APP
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass
    ap = argparse.ArgumentParser(
        description="馍馍拾色器 manual 图片资产：kritarunner 抓图 + PIL 无文字拼图 + 自检")
    ap.add_argument("--capture", action="store_true", help="只通过 kritarunner 抓原始图")
    ap.add_argument("--build", action="store_true", help="只从原始图拼最终 PNG / GIF")
    ap.add_argument("--check", action="store_true", help="只校验产物")
    ap.add_argument("--contact", action="store_true",
                    help="只生成 tmp/_review_after_D3.png（12 PNG 缩略图 + 3 GIF 首/中/末帧）")
    ap.add_argument("--only", default=None, metavar="ID[,ID...]",
                    help="只处理指定资产，可用：" + ",".join(BUILD_FUNCS))
    args = ap.parse_args(argv)
    only = None
    if args.only:
        only = [x.strip() for x in args.only.split(",") if x.strip()]
        known = set(BUILD_FUNCS) | set(CAPTURE_FUNCS)
        bad = [x for x in only if x not in known]
        if bad:
            _log("未知资产 id：%s；可用：%s" % (",".join(bad), ",".join(sorted(known))))
            return 2
    if args.check:
        return check_assets()
    if args.contact:
        make_contact_sheet()
        return 0
    caps = None if only is None else [x for x in only if x in CAPTURE_FUNCS]
    if args.capture:
        if caps or only is None:
            run_capture(caps)
        if not args.build:
            return 0
    if args.build:
        build_all(only)
        rc = check_assets()
        if only is None:
            make_contact_sheet()
        return rc
    # 默认：抓图 -> 拼图 -> 自检 -> 评审 contact sheet
    if caps or only is None:
        run_capture(caps)
    build_all(only)
    rc = check_assets()
    if only is None:
        make_contact_sheet()
    return rc


if __name__ == "__main__":
    sys.exit(cli())
