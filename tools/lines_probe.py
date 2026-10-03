# -*- coding: utf-8 -*-
"""过点线分线冻结探针（kritarunner）：锁定的线完全不动，另一根实时更新。

用法：kritarunner.com -s linesprobe -f main
"""

import os
import sys
import traceback

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


LOG = os.path.join(_momo_repo_root(), "tmp", "lines_probe.log")
PASS = [0]
FAIL = []
_OUT = None


def put(msg=""):
    global _OUT
    if _OUT is None:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        _OUT = open(LOG, "w", encoding="utf-8", newline="\n")
    _OUT.write(str(msg) + "\n")
    _OUT.flush()


def check(name, ok, detail=""):
    if ok:
        PASS[0] += 1
    else:
        FAIL.append("%s %s" % (name, detail))
        put("[FAIL] %s %s" % (name, detail))


class Ev(object):
    def __init__(self, x, y, button, buttons=None, mods=None):
        from PyQt5.QtCore import QPointF, Qt
        self._p = QPointF(float(x), float(y))
        self._b = button
        self._bs = buttons if buttons is not None else button
        self._m = mods if mods is not None else Qt.NoModifier

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


def _same(a, b):
    import numpy as np
    if a is None or b is None:
        return a is b
    return a is b or (np.array_equal(a[0], b[0]) and np.array_equal(a[1], b[1]))


def main(*args):
    sys.path.insert(0, os.path.join(os.environ["APPDATA"], "krita", "pykrita"))
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    try:
        from hsv_picker import hsv_picker as hp
    except Exception:
        put("导入插件失败:\n" + traceback.format_exc())
        return 1

    panel = hp.HsvPickerPanel()
    panel.resize(560, 900)
    panel.mid_box.resize(548, 640)
    panel._layout_picker()
    c = panel.picker
    g = c._geometry()
    cx = g["sq"][0] + (g["sq"][2] - g["sq"][0]) / 2.0
    cy = g["sq"][1] + (g["sq"][3] - g["sq"][1]) / 2.0
    # 方块内中/右键动作由自定义按键表决定。先按「中=改彩度、右=改明度」的键表
    # 核对冻结线，末尾再补「默认表」两组断言。
    _km0 = hp.keymap_core.default_keymap()
    hp.keymap_core.set_action(_km0, "square", "none", "middle", "rel_c")
    hp.keymap_core.set_action(_km0, "square", "none", "right", "rel_l")
    c.set_keymap(_km0)

    # 右键（锁彩度）：蓝线冻结、红线实时
    c.set_color(117.0, 0.6, 0.6)
    c.mousePressEvent(Ev(cx, cy, Qt.RightButton))
    frozen_crel = c._frozen_crel
    check("右键拖动：蓝线已冻结", frozen_crel is not None and c._frozen_iso is None,
          "crel=%s iso=%s" % (frozen_crel is not None, c._frozen_iso is None))
    lines1 = c._through_lines()
    check("右键拖动：冻结线就是按下时的蓝线", _same(lines1["crel"], frozen_crel))
    c.mouseMoveEvent(Ev(cx + 6, cy + 30, Qt.NoButton, Qt.RightButton))
    lines2 = c._through_lines()
    check("右键拖动：蓝线完全不动（同一快照）", lines2["crel"] is frozen_crel)
    check("右键拖动：红线实时更新", not _same(lines1["iso"], lines2["iso"]),
          "iso 是否变化=%s" % (not _same(lines1["iso"], lines2["iso"])))
    c.mouseReleaseEvent(Ev(cx + 6, cy + 30, Qt.RightButton))
    check("右键松手：解冻", c._frozen_iso is None and c._frozen_crel is None)

    # 中键（锁明度）：红线冻结、蓝线实时
    c.set_color(200.0, 0.5, 0.5)
    c.mousePressEvent(Ev(cx, cy, Qt.MiddleButton))
    frozen_iso = c._frozen_iso
    check("中键拖动：红线已冻结", frozen_iso is not None and c._frozen_crel is None)
    lines1 = c._through_lines()
    c.mouseMoveEvent(Ev(cx + 30, cy + 4, Qt.NoButton, Qt.MiddleButton))
    lines2 = c._through_lines()
    check("中键拖动：红线完全不动", lines2["iso"] is frozen_iso)
    check("中键拖动：蓝线实时更新", not _same(lines1["crel"], lines2["crel"]))
    c.mouseReleaseEvent(Ev(cx + 30, cy + 4, Qt.MiddleButton))
    check("中键松手：解冻", c._frozen_iso is None and c._frozen_crel is None)

    # 默认键表：中键 = 改明度 -> 蓝线冻结；右键 = 改彩度 -> 红线冻结
    c.set_keymap(hp.keymap_core.default_keymap())
    c.set_color(117.0, 0.6, 0.6)
    c.mousePressEvent(Ev(cx, cy, Qt.MiddleButton))
    check("方块内交换后中键（改明度）：蓝线冻结",
          c._frozen_crel is not None and c._frozen_iso is None)
    c.mouseReleaseEvent(Ev(cx, cy, Qt.MiddleButton))
    c.set_color(200.0, 0.5, 0.5)
    c.mousePressEvent(Ev(cx, cy, Qt.RightButton))
    check("方块内交换后右键（改彩度）：红线冻结",
          c._frozen_iso is not None and c._frozen_crel is None)
    c.mouseReleaseEvent(Ev(cx, cy, Qt.RightButton))
    c.set_keymap(hp.keymap_core.default_keymap())

    # 明度条（锁 C_rel）：蓝线冻结
    panel.set_color(60.0, 0.6, 0.6, write_fg=False)
    panel._on_strip_l_press()
    check("明度条按下：蓝线冻结", c._frozen_crel is not None and c._frozen_iso is None)
    panel._on_strip_release()
    check("明度条松手：解冻", c._frozen_iso is None and c._frozen_crel is None)

    # 彩度条（锁 L）：红线冻结
    panel._on_strip_c_press()
    check("彩度条按下：红线冻结", c._frozen_iso is not None and c._frozen_crel is None)
    panel._on_strip_release()
    check("彩度条松手：解冻", c._frozen_iso is None and c._frozen_crel is None)

    # 左键绝对拖动：两条都实时
    c.set_color(300.0, 0.5, 0.5)
    c.mousePressEvent(Ev(cx, cy, Qt.LeftButton))
    check("左键拖动：两条都实时（不冻结）", c._frozen_iso is None and c._frozen_crel is None)
    c.mouseReleaseEvent(Ev(cx, cy, Qt.LeftButton))

    # 色相环上中/右键拖动：红蓝线都实时（不冻结）
    import time as _t
    ring_pt = (g["cx"] - (g["r_in"] + g["r_out"]) / 2.0, g["cy"])
    c.set_color(60.0, 0.5, 0.5)
    c.mousePressEvent(Ev(ring_pt[0], ring_pt[1], Qt.MiddleButton))
    check("中键环拖动：两条都实时（不冻结）",
          c._frozen_iso is None and c._frozen_crel is None)
    l1 = c._through_lines()
    _t.sleep(0.03)                    # 越过 14ms 环拖动节流
    c.mouseMoveEvent(Ev(ring_pt[0], ring_pt[1] - 30, Qt.NoButton, Qt.MiddleButton))
    l2 = c._through_lines()
    check("中键环拖动：红线蓝线都更新",
          not _same(l1["iso"], l2["iso"]) and not _same(l1["crel"], l2["crel"]))
    c.mouseReleaseEvent(Ev(ring_pt[0], ring_pt[1] - 30, Qt.MiddleButton))

    c.set_color(60.0, 0.5, 0.5)
    c.mousePressEvent(Ev(ring_pt[0], ring_pt[1], Qt.RightButton))
    check("右键环拖动：两条都实时（不冻结）",
          c._frozen_iso is None and c._frozen_crel is None)
    l1 = c._through_lines()
    _t.sleep(0.03)
    c.mouseMoveEvent(Ev(ring_pt[0], ring_pt[1] + 30, Qt.NoButton, Qt.RightButton))
    l2 = c._through_lines()
    check("右键环拖动：红线蓝线都更新",
          not _same(l1["iso"], l2["iso"]) and not _same(l1["crel"], l2["crel"]))
    c.mouseReleaseEvent(Ev(ring_pt[0], ring_pt[1] + 30, Qt.RightButton))

    # 方块与环内圈之间的死角（R12：兜底按色相环处理）；控件的真空白角落仍是 None
    from hsv_picker import render as rd
    blank_x = g["cx"] + g["half_sq"] + 2.0
    check("死角（方块与环之间）命中为 ring、控件角落仍为 None",
          rd.hit_area(g, blank_x, g["cy"]) == "ring"
          and rd.hit_area(g, 2.0, 2.0) is None,
          "blank_x=%.1f half=%.1f r_in=%.1f" % (blank_x, g["half_sq"], g["r_in"]))
    check("方块内命中为 square",
          rd.hit_area(g, g["cx"] + g["half_sq"] - 2.0, g["cy"]) == "square")
    c.set_color(60.0, 0.5, 0.5)
    c.mousePressEvent(Ev(blank_x, g["cy"], Qt.LeftButton))
    check("点死角进入环拖动（不再是无反应的死区）", c._drag_mode is not None,
          "drag_mode=%r" % c._drag_mode)
    c.mouseReleaseEvent(Ev(blank_x, g["cy"], Qt.LeftButton))

    # 线簇：50% 的簇线略粗且两族同色（轻微高亮，不喧宾夺主）
    check("50% 线簇略粗（1.5）", hp.picker_widget.cluster_pen_width(0.5) == 1.5,
          "%.2f" % hp.picker_widget.cluster_pen_width(0.5))
    check("其它线簇保持细线（1.0）",
          hp.picker_widget.cluster_pen_width(0.4) == 1.0
          and hp.picker_widget.cluster_pen_width(0.6) == 1.0)
    iso_styles = hp.picker_widget.cluster_line_styles((150, 190, 225, 160), 0.5)
    crel_styles = hp.picker_widget.cluster_line_styles((195, 170, 120, 160), 0.5)
    check("50% 簇线两族使用相同颜色",
          iso_styles == crel_styles and len(iso_styles) == 1,
          "iso=%r crel=%r" % (iso_styles, crel_styles))
    check("50% 簇线为轻微高亮（单笔、低对比）",
          len(iso_styles) == 1 and iso_styles[0][1] <= 1.6
          and iso_styles[0][0][3] <= 200,
          "%r" % (iso_styles,))
    check("非 50% 簇线仍用各族原色",
          hp.picker_widget.cluster_line_styles((150, 190, 225, 160), 0.4)
          != hp.picker_widget.cluster_line_styles((195, 170, 120, 160), 0.4))
    # ============ T-48：abs 口径的过点线 / 线簇 / 冻结语义（rel 旧断言全部保留） ============
    import numpy as _np
    import time as _t
    mc = hp.math_core
    panel.set_chroma_mode("abs", _broadcast=False)
    check("abs 口径已灌进拾色器", c.chroma_mode == "abs", "picker=%s" % c.chroma_mode)
    c.set_keymap(hp.keymap_core.default_keymap())
    c.set_color(117.0, 0.62, 0.70)
    c._through_cache = None
    c._through_key = None
    abs_line = c._crel_line_now()
    c_now = float(mc.ok_L_C(c.h, c.s, c.v)[1])
    abs_err = 9.9
    if abs_line is not None and len(abs_line[0]) >= 2:
        cc = _np.asarray(mc.ok_L_C(c.h, abs_line[0], abs_line[1])[1], dtype=float)
        abs_err = float(_np.max(_np.abs(cc - c_now)))
    check("abs 蓝过点线：线上采样 |C-C_now| < 1e-4",
          abs_line is not None and abs_err < 1e-4,
          "点数=%s maxΔC=%.2e" % (0 if abs_line is None else len(abs_line[0]), abs_err))

    # T-48 修复：等绝对 C 线必须真的穿过当前色点（S=1 边界的颜色也不能断头），
    # 否则中键拖动起手会瞬移（旧采样漏掉 v_lo 端点）。
    worst_pt = 0.0
    worst_curve = 0.0
    for _h, _s, _v in ((184.0, 1.0, 0.6), (120.0, 0.99, 0.4), (210.0, 0.999, 0.2)):
        c.set_color(_h, _s, _v)
        _line = c._crel_line_now()
        if _line is not None:
            worst_pt = max(worst_pt,
                           float(_np.hypot(_line[0] - _s, _line[1] - _v).min()))
        c.btn_c = True
        c._refresh_locks()
        _curve = c.constraint_curve()
        if _curve is not None:
            worst_curve = max(worst_curve,
                              float(_np.hypot(_curve[:, 0] - _s,
                                              _curve[:, 1] - _v).min()))
        c.btn_c = False
        c._refresh_locks()
    check("abs 蓝线/约束曲线严格过当前色点（含 S=1 边界）",
          worst_pt < 1e-6 and worst_curve < 1e-6,
          "maxΔ线=%.2e maxΔ曲线=%.2e" % (worst_pt, worst_curve))

    c.set_color(184.0, 1.0, 0.6)
    c.mousePressEvent(Ev(cx, cy, Qt.MiddleButton))
    _s0, _v0 = c.s, c.v
    c._last_heavy = 0.0
    _t.sleep(0.02)
    c.mouseMoveEvent(Ev(cx, cy - 2, Qt.NoButton, Qt.MiddleButton))
    _jump = float(_np.hypot(c.s - _s0, c.v - _v0))
    c.mouseReleaseEvent(Ev(cx, cy - 2, Qt.MiddleButton, Qt.NoButton))
    check("abs 中键在 S=1 边界起手 2px 不瞬移（Δ(S,V) < 0.02）",
          _jump < 0.02, "Δ=%.4f" % _jump)

    c.set_color(117.0, 0.62, 0.70)      # 上面的过点检查改过颜色，线簇仍按 117° 核对
    _ax, _cg = mc.cabs_field(c.h, n=41)
    _allowed = [0.04 * i for i in range(1, 10)]
    worst_line = 0.0
    n_line = 0
    for _tgt, (_ss, _vv) in zip(_allowed, mc.cabs_isoline_many(_ax, _cg, _allowed)):
        if len(_ss) < 2:
            continue
        n_line += 1
        cc = _np.asarray(mc.ok_L_C(c.h, _ss, _vv)[1], dtype=float)
        worst_line = max(worst_line, float(_np.max(_np.abs(cc - _tgt))))
    check("abs 线簇：9 档固定 0.04~0.36、每条 C 误差 < 1e-4",
          n_line >= 4 and worst_line < 1e-4,
          "非空 %d 条 maxΔC=%.2e" % (n_line, worst_line))

    c.set_color(117.0, 0.62, 0.70)
    c.mousePressEvent(Ev(cx, cy, Qt.MiddleButton))
    f_blue = c._frozen_crel
    check("abs 中键（改明度）：蓝线（等绝对 C）冻结、红线实时",
          f_blue is not None and c._frozen_iso is None)
    C_t = c.target_cabs
    worst_drag = 0.0
    lines2 = None
    for d in (6, 18, 30):
        c._last_heavy = 0.0
        _t.sleep(0.02)
        c.mouseMoveEvent(Ev(cx, cy + d, Qt.NoButton, Qt.MiddleButton))
        lines2 = c._through_lines()
        worst_drag = max(worst_drag,
                         abs(float(mc.ok_L_C(c.h, c.s, c.v)[1]) - C_t))
    check("abs 中键拖动：蓝线快照完全不动、当前色 C 漂移 < 1e-5",
          lines2 is not None and lines2["crel"] is f_blue and worst_drag < 1e-5,
          "同一快照=%s maxΔC=%.2e"
          % (lines2 is not None and lines2["crel"] is f_blue, worst_drag))
    c.mouseReleaseEvent(Ev(cx, cy + 30, Qt.MiddleButton, Qt.NoButton))
    check("abs 中键松手解冻", c._frozen_iso is None and c._frozen_crel is None)

    c.set_color(200.0, 0.5, 0.5)
    c.mousePressEvent(Ev(cx, cy, Qt.RightButton))
    check("abs 右键（改彩度）：红线冻结、蓝线实时",
          c._frozen_iso is not None and c._frozen_crel is None)
    c.mouseReleaseEvent(Ev(cx, cy, Qt.RightButton, Qt.NoButton))

    panel.set_chroma_mode("rel", _broadcast=False)
    c.set_keymap(hp.keymap_core.default_keymap())


    put("")
    put("=" * 56)
    put("通过 %d 项，失败 %d 项" % (PASS[0], len(FAIL)))
    for item in FAIL:
        put("  - %s" % item)
    put("结论：%s" % ("全部通过" if not FAIL else "存在失败"))
    return 0 if not FAIL else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        put("顶层异常:\n" + traceback.format_exc())
        sys.exit(1)
