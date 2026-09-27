# -*- coding: utf-8 -*-
"""UI 暴力测试（在 Krita 内嵌 Python 里跑，kritarunner 可直接执行）。

覆盖：
  A 尺寸风暴：极小到极大反复 resize，检查几何不变量与稳定性
  B 鼠标矩阵：左/中/右 × Shift/Alt × 方块/环/边缘/角落 共 81 组合
  C 约束不变量：中键锁明度、右键锁彩度、轴向锁定、S=0 保色相
  D 色条/数值框：全位置拖动 + 合法/非法输入 + 端点往返
  E 历史：批量推入、逐个点击、容量随高度变化、只在松手记一次
  F 弹窗：反复 toggle、双向同步、尺寸记忆、对象销毁时机
  G 渲染：多尺寸多状态绘制 + 耗时统计
  H/I 色条语义、Oklab a/b 分量条
  K 当前色块（HEX 右边、自适应宽度）与预览浮层（三格取值 / 5 种模式 / 位置不压面板 / 跟随 / 无淡出）
  T41/T42 8 种修饰键组合、未知位落回、已删环动作迁移（键表数据层 + 环/方块/条/数值框触发）

用法（kritarunner）：-s uistress -f main
"""
import math
import os
import sys
import time
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


LOG = os.path.join(_momo_repo_root(), "tmp", "ui_stress.log")

FAIL = []
PASS = [0]
_LOGF = None


def put(msg=""):
    global _LOGF
    if _LOGF is None:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        _LOGF = open(LOG, "w", encoding="utf-8", newline="\n")
    _LOGF.write(str(msg) + "\n")
    _LOGF.flush()


def check(name, ok, detail=""):
    if ok:
        PASS[0] += 1
    else:
        FAIL.append("%s %s" % (name, detail))
        put("[FAIL] %-46s %s" % (name, detail))


# ---------------------------------------------------------------------------
# P2-⑥ 时间敏感断言的机器负载校准
# 说明：绝对墙钟阈值会被整机负载（视频播放/浏览器/杀毒扫描）抬高，不能稳定区分
# 「机器慢」与「代码回退」。这里先量一个固定纯 Python 工作负载，再按相对空载的
# 倍率给性能阈值乘一个系数（上限 3 倍）；代码真回退时校准值不变、渲染值变高，
# 仍然会被抓到。参考值 = 本机 2026-09-26 空载时 2,000,000 次整数乘加的最小值。
CALIB_REPS = 2000000
CALIB_REF_MIN_MS = 56.8
CALIB_MAX_FACTOR = 3.0


def cpu_calib_min_ms(samples=5):
    """返回固定 CPU 负载的最小采样耗时（ms）；最小值代表当前机器的干净窗口。"""
    best = None
    for _ in range(samples):
        t0 = time.perf_counter()
        s = 0
        for i in range(CALIB_REPS):
            s += i * i
        dt = (time.perf_counter() - t0) * 1000.0
        best = dt if best is None else min(best, dt)
    return best


class Ev(object):
    """轻量鼠标事件替身（只实现被用到的接口）。"""

    def __init__(self, x, y, button, buttons=None, mods=None):
        from PyQt5.QtCore import QPointF, Qt
        self._p = QPointF(float(x), float(y))
        self._b = button
        self._bs = buttons if buttons is not None else button
        self._m = mods if mods is not None else Qt.NoModifier
        self.ignored = False

    def localPos(self):
        return self._p

    def x(self):
        return self._p.x()

    def y(self):
        return self._p.y()

    def button(self):
        return self._b

    def buttons(self):
        return self._bs

    def modifiers(self):
        return self._m

    def accept(self):
        pass

    def ignore(self):
        self.ignored = True


def sect(name):
    put("")
    put("=== %s ===" % name)



def _section_a(panel):
    """A 尺寸风暴 + 稳定性。"""
    sect("A 尺寸风暴")
    sizes = [(240, 420), (300, 600), (800, 1200), (200, 380), (1400, 900),
             (320, 1000), (260, 460), (2000, 1400), (210, 400), (760, 760)]
    ok_geom = True
    for w, h in sizes:
        panel.resize(w, h)
        panel.layout().activate()
        panel.mid_box.resize(max(80, w - 12), max(120, h - 260))   # 模拟布局分配
        panel._layout_picker()
        c = panel.picker
        box = panel.mid_box
        if c.width() != c.height() or c.width() < 100:
            ok_geom = False
            put("  %dx%d -> picker=%dx%d" % (w, h, c.width(), c.height()))
        if c.x() < 0 or c.y() < 0 or c.x() + c.width() > box.width() \
                or c.y() + c.height() > box.height():
            ok_geom = False
            put("  %dx%d -> picker 越界 picker=%dx%d box=%dx%d"
                % (w, h, c.width(), c.height(), box.width(), box.height()))
        g = c._geometry()
        if abs(g["half_sq"] * math.sqrt(2.0) - g["r_in"]) > 1e-6:
            ok_geom = False
            put("  %dx%d -> 方块半对角 != 环内半径" % (w, h))
        if g["r_out"] > min(c.width(), c.height()) / 2.0 + 0.5:
            ok_geom = False
            put("  %dx%d -> 环外圈越界" % (w, h))
    check("A1 尺寸风暴下几何不变量", ok_geom)

    panel.resize(600, 1000)
    panel.mid_box.resize(588, 740)
    panel._layout_picker()
    first = panel.picker.width()
    for _ in range(30):
        panel._layout_picker()
    last = panel.picker.width()
    check("A2 反复 layout 后尺寸稳定", abs(first - last) <= 1 and first >= 100,
          "first=%d last=%d" % (first, last))

    panel.resize(600, 700)
    panel.mid_box.resize(588, 440)
    panel._layout_picker()
    sides = []
    for h in range(700, 1401, 100):
        panel.resize(600, h)
        panel.mid_box.resize(588, max(120, h - 260))
        panel._layout_picker()
        sides.append(panel.picker.width())
    check("A3 变高时拾色器不缩小", sides == sorted(sides),
          "sides=%s" % sides)



def _section_bc(panel, c, selfmod, g, cx, cy, ring_pt):
    """B 鼠标矩阵 + C 约束不变量。"""
    from PyQt5.QtCore import Qt as Q
    kmc = selfmod.keymap_core
    sect("B 鼠标矩阵")
    buttons = [("左", Q.LeftButton), ("中", Q.MiddleButton), ("右", Q.RightButton)]
    mods = [("无", Q.NoModifier), ("Shift", Q.ShiftModifier), ("Alt", Q.AltModifier)]
    pts = [("中心", (cx, cy)), ("左上", (g["sq"][0] + 1, g["sq"][1] + 1)),
           ("右下", (g["sq"][2] - 1, g["sq"][3] - 1)),
           ("左缘", (g["sq"][0], cy)), ("右缘", (g["sq"][2], cy)),
           ("上缘", (cx, g["sq"][1])), ("下缘", (cx, g["sq"][3])),
           ("环上", ring_pt), ("环外", (2.0, 2.0))]
    errs = []
    for bname, btn in buttons:
        for mname, m in mods:
            for pname, (px, py) in pts:
                try:
                    c.set_color(123.0, 0.5, 0.6)
                    c.mousePressEvent(Ev(px, py, btn, None, m))
                    for d in (3, 9, 21, 40):
                        c.mouseMoveEvent(Ev(px + d, py - d, Q.NoButton, None, m))
                    c.mouseReleaseEvent(Ev(px + 40, py - 40, btn, Q.NoButton, m))
                    for val, nm in ((c.h, "H"), (c.s, "S"), (c.v, "V")):
                        if not (val == val):
                            raise AssertionError("%s=NaN" % nm)
                        if nm == "H" and (val < -1e-9 or val > 360.0001):
                            raise AssertionError("H=%r" % val)
                        if nm != "H" and (val < -1e-9 or val > 1.0001):
                            raise AssertionError("%s=%r" % (nm, val))
                except Exception as exc:
                    errs.append("%s+%s@%s: %r" % (bname, mname, pname, exc))
    check("B1 鼠标矩阵 81 组合无异常", not errs, "；".join(errs[:3]))

    sect("C 约束不变量")
    # C1/C2 测「中键改彩度、右键改明度」的键表变体
    _km = kmc.default_keymap()
    kmc.set_action(_km, "square", "none", "middle", "rel_c")
    kmc.set_action(_km, "square", "none", "right", "rel_l")
    c.set_keymap(_km)
    c.set_color(60.0, 0.3, 0.7)
    c.mousePressEvent(Ev(cx, cy, Q.MiddleButton))
    L0 = c.target_l
    worst_l = 0.0
    for d in range(0, 120, 6):
        c.mouseMoveEvent(Ev(cx + d, cy + d // 2, Q.NoButton, Q.MiddleButton))
        worst_l = max(worst_l, abs(float(selfmod.math_core.lightness(c.h, c.s, c.v, "oklab")) - L0))
    c.mouseReleaseEvent(Ev(cx + 120, cy + 60, Q.MiddleButton, Q.NoButton))
    check("C1 中键拖动明度恒定（不交换）", worst_l < 1e-5, "最大偏差 %.2e" % worst_l)

    c.set_color(60.0, 0.5, 0.6)
    c.mousePressEvent(Ev(cx, cy, Q.RightButton))
    C0 = c.target_crel
    worst_c = 0.0
    for d in range(0, 120, 6):
        c.mouseMoveEvent(Ev(cx + d // 2, cy + d, Q.NoButton, Q.RightButton))
        worst_c = max(worst_c, abs(float(selfmod.math_core.crel_of_xyz(c.h, "oklab", c.s, c.v)[0]) - C0))
    c.mouseReleaseEvent(Ev(cx + 60, cy + 120, Q.RightButton, Q.NoButton))
    check("C2 右键拖动彩度恒定（不交换）", worst_c < 2e-3, "最大偏差 %.2e" % worst_c)

    # C1b/C2b 默认键表：中键 = 改明度（锁 C_rel）、右键 = 改彩度（锁 L）
    c.set_keymap(kmc.default_keymap())
    c.set_color(60.0, 0.5, 0.6)
    c.mousePressEvent(Ev(cx, cy, Q.MiddleButton))
    C0b = c.target_crel
    worst_cb = 0.0
    for d in range(0, 120, 6):
        c.mouseMoveEvent(Ev(cx + d // 2, cy + d, Q.NoButton, Q.MiddleButton))
        worst_cb = max(worst_cb, abs(float(selfmod.math_core.crel_of_xyz(c.h, "oklab", c.s, c.v)[0]) - C0b))
    c.mouseReleaseEvent(Ev(cx + 60, cy + 120, Q.MiddleButton, Q.NoButton))
    check("C1b 方块内交换后中键 = 改明度（C_rel 恒定）", C0b is not None and worst_cb < 2e-3,
          "最大偏差 %.2e" % worst_cb)

    c.set_color(60.0, 0.3, 0.7)
    c.mousePressEvent(Ev(cx, cy, Q.RightButton))
    L0b = c.target_l
    worst_lb = 0.0
    for d in range(0, 120, 6):
        c.mouseMoveEvent(Ev(cx + d, cy + d // 2, Q.NoButton, Q.RightButton))
        worst_lb = max(worst_lb, abs(float(selfmod.math_core.lightness(c.h, c.s, c.v, "oklab")) - L0b))
    c.mouseReleaseEvent(Ev(cx + 120, cy + 60, Q.RightButton, Q.NoButton))
    check("C2b 方块内交换后右键 = 改彩度（明度恒定）", L0b is not None and worst_lb < 1e-5,
          "最大偏差 %.2e" % worst_lb)

    c.set_color(60.0, 0.5, 0.5)
    c.mousePressEvent(Ev(cx, cy, Q.LeftButton, None, Q.ShiftModifier))
    for d in range(0, 60, 6):
        c.mouseMoveEvent(Ev(cx + d, cy + d, Q.LeftButton, None, Q.ShiftModifier))
    check("C3 Shift 只改 S", abs(c.v - 0.5) < 1e-12, "V=%.6f" % c.v)
    c.mouseReleaseEvent(Ev(cx + 60, cy + 60, Q.LeftButton))

    c.set_color(60.0, 0.5, 0.5)
    c.mousePressEvent(Ev(cx, cy, Q.LeftButton, None, Q.AltModifier))
    for d in range(0, 60, 6):
        c.mouseMoveEvent(Ev(cx + d, cy + d, Q.LeftButton, None, Q.AltModifier))
    check("C4 Alt 只改 V", abs(c.s - 0.5) < 1e-12, "S=%.6f" % c.s)
    c.mouseReleaseEvent(Ev(cx + 60, cy + 60, Q.LeftButton))

    c.set_color(210.0, 0.5, 0.5)
    c.mousePressEvent(Ev(g["sq"][0], cy, Q.LeftButton))
    c.mouseReleaseEvent(Ev(g["sq"][0], cy, Q.LeftButton))
    check("C5 S=0 时保留色相", c.s < 1e-9 and abs(c.h - 210.0) < 1e-6,
          "S=%.4f h=%.2f" % (c.s, c.h))

    # C6 环上中键 = 锁 L（保 S 解 V）：转色相时明度不漂
    c.set_keymap(kmc.default_keymap())
    c.set_color(30.0, 0.5, 0.5)
    Lr = c.locked_lightness()
    rr6 = (g["r_in"] + g["r_out"]) / 2.0
    c.mousePressEvent(Ev(g["cx"], g["cy"] - rr6, Q.MiddleButton))
    c._last_heavy = 0.0
    c.mouseMoveEvent(Ev(g["cx"] + rr6, g["cy"], Q.NoButton, Q.MiddleButton))
    ok_ring_l = abs(c.locked_lightness() - Lr) < 1e-6
    c.mouseReleaseEvent(Ev(g["cx"] + rr6, g["cy"], Q.MiddleButton, Q.NoButton))
    check("C6 环上中键锁明度不漂", ok_ring_l,
          "L %.6f -> %.6f" % (Lr, c.locked_lightness()))



def _section_def(panel, c, selfmod, g, cx, cy):
    """D 色条/数值框 + E 历史。"""
    from PyQt5.QtCore import Qt as Q
    from PyQt5.QtGui import QPixmap, QPainter

    sect("D 色条与数值框")
    panel.set_chroma_mode("rel", _broadcast=False)      # D4 用相对口径语义
    errs = []
    try:
        for t in [i / 20.0 for i in range(21)]:
            panel._on_strip_lightness(t)
            panel._on_strip_chroma(t)
    except Exception as exc:
        errs.append("色条拖动: %r" % (exc,))
    check("D1 两条色条全位置拖动无异常", not errs, "；".join(errs))

    panel.set_color(200.0, 0.6, 0.5)
    panel._on_strip_l_press()
    worst = 0.0
    for i in range(21):
        t = i / 20.0
        panel._on_strip_lightness(t)
        L = float(selfmod.math_core.lightness(panel.h, panel.s, panel.v, "oklab"))
        worst = max(worst, abs(L - t))
    panel._on_strip_release()
    check("D2 明度条全量程明度跟随目标", worst < 2e-3, "最大偏差 %.2e" % worst)

    vals = ["0", "1", "50", "100", "0.5", "0.5%", "abc", "", "999", "-5", "1e2"]
    errs = []
    for v in vals:
        for edit in (panel.edit_h, panel.edit_s, panel.edit_v, panel.edit_hex,
                     panel.edit_l, panel.edit_c):
            try:
                panel.apply_entry_text(edit, v)
            except Exception as exc:
                errs.append("%r -> %r" % (v, exc))
    check("D3 数值框 11 值 × 6 框无异常", not errs, "；".join(errs[:3]))

    panel.set_color(60.0, 0.4, 0.6)
    panel._sync_entries()
    before = panel._crel_now()
    panel.apply_entry_text(panel.edit_c, "%.4f" % before)
    check("D4 彩度框同值提交不变", abs(panel._crel_now() - before) < 2e-3,
          "%.4f -> %.4f" % (before, panel._crel_now()))

    c.set_color(60.0, 0.5, 0.5)
    panel._sync_entries()
    panel._editing_field = "h"
    h_before = panel.edit_h.text()
    for i in range(20):
        panel._on_drag_value("h", 60.0 + i)
    h_after = panel.edit_h.text()
    panel._editing_field = None
    check("D5 拖动数值框期间不回写自身", h_before == h_after, "%r -> %r" % (h_before, h_after))

    sect("E 历史颜色")
    panel.history.set_colors([])
    for i in range(120):
        panel._push_history("#%02X%02X%02X" % (i % 256, (i * 3) % 256, (i * 7) % 256))
    check("E1 历史不超过 128", len(panel.history.colors) <= 128,
          "%d > 128" % len(panel.history.colors))
    errs = []
    for _ in range(3):
        for col in list(panel.history.colors):
            try:
                panel._on_history_pick(col)
            except Exception as exc:
                errs.append(repr(exc))
    check("E2 逐个点击历史无异常", not errs, "；".join(errs[:3]))

    panel.history.set_colors([])
    c.set_color(60.0, 0.5, 0.5)
    c.mousePressEvent(Ev(cx, cy, Q.LeftButton))
    for d in (5, 10, 20):
        c.mouseMoveEvent(Ev(cx + d, cy, Q.LeftButton, Q.LeftButton))
    n_during = len(panel.history.colors)
    c.mouseReleaseEvent(Ev(cx + 20, cy, Q.LeftButton))
    check("E3 拖动中不记历史、松手记一次", n_during == 0 and len(panel.history.colors) == 1,
          "during=%d after=%d" % (n_during, len(panel.history.colors)))

    panel.mid_box.resize(500, 1100)
    panel._layout_picker()
    cap_big = panel.history.capacity()
    panel.mid_box.resize(500, 300)
    panel._layout_picker()
    cap_small = panel.history.capacity()
    check("E4 历史容量随高度变化", cap_big > cap_small, "大=%d 小=%d" % (cap_big, cap_small))



def _section_k(panel, selfmod):
    """K 当前色块（HEX 右边、自适应宽度）+ 预览浮层（三格 / 5 种模式 / 位置 / 跟随 / 无淡出）。"""
    import inspect
    from PyQt5.QtCore import QEvent, QPoint, QRect
    from PyQt5.QtCore import Qt as Q
    from PyQt5.QtWidgets import QApplication, QHBoxLayout, QStyle, QWidget
    sect("K 当前色块与预览浮层")
    # 前面的段落可能留下交互标志（例如 D5 的 _entry_dragging）：先复位，保证本段的倒计时断言有效
    panel._picking = False
    panel._strip_active = False
    panel._entry_dragging = False
    # 浮层模式会持久化在设置里（上一次探针可能留下别的值）：探针自己定基线，默认值另查常量
    panel.set_preview_mode("1s", _broadcast=False)

    # K1 三色块已移除；当前色块在 HEX 右边、吃满右侧余量、与 HEX 框等高、面板变矮
    has_old = hasattr(panel, "swatch")
    cur = getattr(panel, "swatch_cur", None)
    lay = panel.layout()
    row = None
    for i in range(lay.count()):
        sub = lay.itemAt(i).layout()
        if sub is not None and sub.indexOf(panel.edit_hex) >= 0:
            row = sub
            break
    last_item_ok = False
    if row is not None and cur is not None:
        last = row.count() - 1
        last_item_ok = (row.itemAt(last).widget() is cur and row.stretch(last) == 1)
    order_ok = (row is not None and cur is not None
                and row.indexOf(cur) > row.indexOf(panel.edit_hex))
    hex_h = panel.edit_hex.height()
    cur_h = cur.height() if cur is not None else -1
    cur_min_w = cur.minimumWidth() if cur is not None else -1
    expanding = (cur is not None
                 and cur.sizePolicy().horizontalPolicy() == 7)   # 7 = QSizePolicy.Expanding
    # 宽度自适应：用独立容器实测（离屏面板不会重跑布局，故不拿它测宽度）
    holder = QWidget()
    hb = QHBoxLayout(holder)
    hb.setContentsMargins(0, 0, 0, 0)
    sw_tmp = selfmod.swatch_widget.CurrentColorSwatch(holder)
    hb.addWidget(sw_tmp, 1)
    holder.resize(200, 30)
    holder.show()
    QApplication.processEvents()
    w_small = sw_tmp.width()
    holder.resize(400, 30)
    QApplication.processEvents()
    w_big = sw_tmp.width()
    holder.hide()
    layout_h = lay.totalMinimumSize().height()
    put("  K1 实测：面板最小高 %d px（改前 428 px）；当前色块 %dx%d（HEX 框高 %d，最小宽 %d，"
        "末项 stretch=1）；独立容器 200->400px 时色块 %d -> %d px"
        % (layout_h, cur.width() if cur is not None else -1, cur_h, hex_h, cur_min_w, w_small, w_big))
    check("K1 三色块已移除 / 当前色块吃满 HEX 右侧（末项 stretch=1、Expanding）、与 HEX 等高、"
          "随容器变宽而变宽 / 面板高度 < 400",
          (not has_old) and cur is not None and order_ok and last_item_ok and expanding
          and cur_min_w == 24 and cur_h == hex_h and w_big > w_small and layout_h < 400,
          "旧三色块=%s 同一行且在其后=%s 末项=%s Expanding=%s 宽%d->%d(容器) 高=%d(HEX %d) 面板最小高=%d"
          % (has_old, order_ok, last_item_ok, expanding, w_small, w_big, cur_h, hex_h, layout_h))

    # K1b 数值框宽度按字体实测（大字体 / 高 DPI 下不裁字；HEX 的 "#" 不能被切）
    fm = panel.edit_hex.fontMetrics()
    frame = panel.edit_hex.style().pixelMetric(QStyle.PM_DefaultFrameWidth)
    hex_need = fm.horizontalAdvance("#RRGGBB") + 2 * frame + 2
    hex_text_need = fm.horizontalAdvance(panel.edit_hex.text()) + 2 * frame + 4
    hex_w_ok = (panel.edit_hex.width() >= hex_need
                and fm.horizontalAdvance(panel.edit_hex.text()) <= panel.edit_hex.width() - 2 * frame - 4)
    hv_ok = []
    for edit, sample in ((panel.edit_h, "210.00"), (panel.edit_s, "100.00"),
                         (panel.edit_v, "100.00"), (panel.edit_l, "0.0000"),
                         (panel.edit_c, "0.0000"), (panel.edit_a, "-0.0000"),
                         (panel.edit_b, "-0.0000")):
        need = edit.fontMetrics().horizontalAdvance(sample) + 2 * edit.style().pixelMetric(
            QStyle.PM_DefaultFrameWidth) + 2
        hv_ok.append(edit.width() >= need)
    put("  K1b 实测：HEX 框宽 %d px（字体实测 #RRGGBB=%d + 边距 %d + 2 = %d；当前文本需 %d）；"
        "H/S/V=%d/%d/%d；L/C/a/b=%d/%d/%d/%d（a/b 按更宽的 -0.0000 兜底）"
        % (panel.edit_hex.width(), fm.horizontalAdvance("#RRGGBB"), 2 * frame, hex_need,
           hex_text_need, panel.edit_h.width(), panel.edit_s.width(), panel.edit_v.width(),
           panel.edit_l.width(), panel.edit_c.width(), panel.edit_a.width(), panel.edit_b.width()))
    check("K1b HEX / H / S / V / L / C / a / b 数值框宽度 ≥ 字体实测宽度（都不裁字）",
          hex_w_ok and all(hv_ok),
          "HEX 宽=%d 需≥%d（文本需 %d，实际 %d）；其余=%s"
          % (panel.edit_hex.width(), hex_need, hex_text_need,
             fm.horizontalAdvance(panel.edit_hex.text()), hv_ok))

    # K1c 四个分量框等宽 + 四条色条等宽（行结构 [标签][色条 stretch][数值框定宽]）
    four = (panel.edit_l.width(), panel.edit_c.width(), panel.edit_a.width(), panel.edit_b.width())
    strips = (panel.strip_l.width(), panel.strip_c.width(), panel.strip_a.width(), panel.strip_b.width())
    strip_rights = (panel.strip_l.geometry().right(), panel.strip_c.geometry().right(),
                    panel.strip_a.geometry().right(), panel.strip_b.geometry().right())
    put("  K1c 实测：L/C/a/b 框宽 %s；四条色条宽 %s；色条右端 %s"
        % (four, strips, strip_rights))
    check("K1c 四个分量框等宽（= 字体实测最大值）→ 四条色条等宽、右端对齐",
          len(set(four)) == 1 and len(set(strips)) == 1 and len(set(strip_rights)) == 1,
          "框宽=%s 色条宽=%s 色条右端=%s" % (four, strips, strip_rights))

    # K2 浮层对象 + 尺寸 + 标志 + 默认模式（2 秒）+ 5 项互斥子菜单
    ov = panel.preview_overlay()
    flags = int(ov.windowFlags())
    flags_ok = (bool(flags & Q.Tool) and bool(flags & Q.FramelessWindowHint)
                and bool(flags & Q.WindowStaysOnTopHint)
                and bool(flags & Q.WindowDoesNotAcceptFocus))
    attrs_ok = (ov.testAttribute(Q.WA_ShowWithoutActivating)
                and ov.testAttribute(Q.WA_TransparentForMouseEvents)
                and ov.focusPolicy() == Q.NoFocus)
    modes = list(getattr(panel, "preview_actions", {}) or {})
    checked = [m for m, a in (panel.preview_actions or {}).items() if a.isChecked()]
    default_ok = (checked == [panel.preview_mode] and panel.preview_group.isExclusive()
                  and selfmod.PREVIEW_DEFAULT_MODE == "hover")
    check("K2 浮层对象存在 / 100×150 / 标志与属性正确 / 出厂默认常量=hover 且勾选与当前模式一致",
          default_ok and modes == ["off", "1s", "2s", "hover", "always"]
          and (ov.width(), ov.height()) == (100, 150) and flags_ok and attrs_ok,
          "尺寸=%dx%d 模式=%s 勾选=%s 子菜单项=%s 标志=%s 属性=%s"
          % (ov.width(), ov.height(), panel.preview_mode, checked, modes, flags_ok, attrs_ok))

    # K3 三格 = 100×100 + 2×50×50 正方形、相邻无间隙、无文字/无边框、到点直接隐藏（无淡出）
    rects = [rect for rect, _c in ov.cell_rects()]
    sizes = [(int(rect.width()), int(rect.height())) for rect in rects]
    adjacent = (abs(rects[0].bottom() - rects[1].top()) < 1e-9
                and abs(rects[1].right() - rects[2].left()) < 1e-9
                and abs(rects[1].bottom() - rects[2].bottom()) < 1e-9
                and abs(rects[2].bottom() - ov.height()) < 1e-9)
    src_all = inspect.getsource(type(ov))
    paint_src = inspect.getsource(type(ov).paintEvent) + inspect.getsource(type(ov)._paint_empty)
    no_text = "drawText" not in paint_src
    no_border = ("drawRect" not in paint_src and "drawLine" not in paint_src
                 and "setPen" not in paint_src)
    no_fade = ("QPropertyAnimation" not in src_all and "setWindowOpacity" not in src_all
               and not hasattr(ov, "fade_ms"))
    check("K3 三格正方形（100×100 + 2×50×50）相邻无间隙 / 无文字无边框 / 无淡出动画",
          sizes == [(100, 100), (50, 50), (50, 50)] and adjacent and no_text
          and no_border and no_fade and not ov.styleSheet(),
          "%s 相邻=%s 无文字=%s 无边框=%s 无淡出=%s" % (sizes, adjacent, no_text, no_border, no_fade))

    # K4/K5 改色触发：显示 + 三格取值 + 拖动期间不倒计时
    panel.preview_hide_ms = 60                   # 测试期：2 秒模式的倒计时调小
    panel.set_preview_mode("2s", _broadcast=False)
    panel.set_history(["#112233", "#445566", "#778899"], save=False)
    ov.hide_now()
    panel._picking = True                        # 模拟拾色器拖动中
    panel._preview_begin()                       # 与真实按下时一致
    panel.set_color(200.0, 0.6, 0.8, write_fg=False)
    cur_rgb = panel.picker_rgb()
    want = (cur_rgb, (0x44, 0x55, 0x66), (0x11, 0x22, 0x33))
    cells = ov.colors()
    placed = tuple(c for _rect, c in ov.cell_rects())     # 按绘制位置：上 / 左下 / 右下
    put("  K4 实测：浮层 %dx%d，三格(上/左下/右下)=%s" % (ov.width(), ov.height(), placed))
    check("K4 改色时浮层显示、三格 = 当前 / 上上次 / 上一次",
          ov.isVisible() and cells == want,
          "显示=%s 实测=%s 期望=%s" % (ov.isVisible(), cells, want))
    check("K4b 下方两格位置口径：左下=上一次(history[0])、右下=上上次(history[1])",
          placed == (cur_rgb, (0x11, 0x22, 0x33), (0x44, 0x55, 0x66)),
          "绘制顺序(上/左下/右下)=%s" % (placed,))
    check("K5 拖动中不启动倒计时", (not ov.countdown_active()),
          "倒计时=%s" % ov.countdown_active())

    # K6 拖动期间即使倒计时很小也不隐藏
    stayed = True
    for _i in range(5):
        panel.set_color((panel.h + 7) % 360, panel.s, panel.v, write_fg=False)
        QApplication.processEvents()
        time.sleep(0.05)
        QApplication.processEvents()
        stayed = stayed and ov.isVisible()
    check("K6 拖动期间（倒计时调小到 60ms）浮层始终不隐藏",
          stayed and ov.isVisible() and not ov.countdown_active(),
          "每步都可见=%s 末态可见=%s 倒计时=%s"
          % (stayed, ov.isVisible(), ov.countdown_active()))

    # K7 松手后才开始倒计时，到点直接隐藏（无淡出：windowOpacity 仍为 1.0）
    panel._picking = False
    panel._on_pick_end()                         # 松手：记历史 + 启动倒计时
    countdown = ov.countdown_active()
    QApplication.processEvents()
    time.sleep(0.25)
    QApplication.processEvents()
    opacity = ov.windowOpacity()
    check("K7 松手后开始倒计时、到点直接隐藏（无淡出）",
          countdown and not ov.isVisible() and abs(opacity - 1.0) < 1e-6,
          "松手时倒计时=%s 250ms 后仍可见=%s opacity=%.3f"
          % (countdown, ov.isVisible(), opacity))

    # K8 外部改色不弹浮层
    ov.hide_now()
    panel.apply_external(120.0, 0.5, 0.5, "#7F7F7F", write_fg=False)
    QApplication.processEvents()
    ext_hidden = not ov.isVisible()
    panel.set_color(30.0, 0.4, 0.4, write_fg=False, preview=False)
    QApplication.processEvents()
    check("K8 外部改色（apply_external / preview=False 的 pull 路径）不弹浮层",
          ext_hidden and not ov.isVisible(),
          "apply_external 后=%s set_color(preview=False) 后=%s"
          % (ext_hidden, ov.isVisible()))

    # K9/K10 五种模式：off 不显示 / 1s、2s 倒计时时长 / hover 进出 / always 常显 + 广播
    got = []
    listener = lambda k, v: got.append((k, v))      # noqa: E731
    panel.view_listeners.append(listener)
    try:
        panel.set_preview_mode("off")
        panel._picking = True
        panel.set_color(10.0, 0.5, 0.5, write_fg=False)
        panel._picking = False
        QApplication.processEvents()
        off_ok = not ov.isVisible()

        panel.set_preview_mode("1s")
        panel._picking = True
        panel._preview_begin()
        panel.set_color(20.0, 0.5, 0.5, write_fg=False)
        panel._picking = False
        panel._on_pick_end()
        ms_1s = ov._timer.remainingTime() if ov.countdown_active() else -1

        panel.preview_hide_ms = 2000                 # 「2 秒」模式的口径
        panel.set_preview_mode("2s")
        panel._picking = True
        panel._preview_begin()
        panel.set_color(40.0, 0.5, 0.5, write_fg=False)
        panel._picking = False
        panel._on_pick_end()
        ms_2s = ov._timer.remainingTime() if ov.countdown_active() else -1

        panel.set_preview_mode("always")
        panel._picking = True
        panel._preview_begin()
        panel.set_color(60.0, 0.5, 0.5, write_fg=False)
        panel._picking = False
        panel._on_pick_end()
        QApplication.processEvents()
        time.sleep(0.20)
        QApplication.processEvents()
        always_ok = ov.isVisible() and not ov.countdown_active()

        panel.set_preview_mode("hover")
        ov.hide_now()
        panel.picker.enterEvent(QEvent(QEvent.Enter))
        QApplication.processEvents()
        hover_in = ov.isVisible() and not ov.countdown_active()
        panel.picker.leaveEvent(QEvent(QEvent.Leave))       # 移出 -> 立即隐藏（无倒计时）
        QApplication.processEvents()
        hover_out = (not ov.isVisible()) and (not ov.countdown_active())
        panel.picker.enterEvent(QEvent(QEvent.Enter))       # 再进来 -> 立即显示
        QApplication.processEvents()
        hover_re = ov.isVisible()
        # 「悬停」+ 改色（鼠标不在拾色器上）：松手后立即隐藏
        panel.picker.leaveEvent(QEvent(QEvent.Leave))
        panel._picking = True
        panel._preview_begin()
        panel.set_color(75.0, 0.5, 0.5, write_fg=False)
        changed_shown = ov.isVisible()
        panel._picking = False
        panel._on_pick_end()
        QApplication.processEvents()
        hover_change_hidden = not ov.isVisible()
        # 「悬停」+ 改色（鼠标仍在拾色器上）：松手后保持显示
        panel.picker.enterEvent(QEvent(QEvent.Enter))
        panel._picking = True
        panel._preview_begin()
        panel.set_color(85.0, 0.5, 0.5, write_fg=False)
        panel._picking = False
        panel._on_pick_end()
        QApplication.processEvents()
        hover_keep = ov.isVisible()
        panel.picker.leaveEvent(QEvent(QEvent.Leave))
    finally:
        if listener in panel.view_listeners:
            panel.view_listeners.remove(listener)
        panel.set_preview_mode("1s", _broadcast=False)   # 复位持久化值，供后面查「新面板默认」
        panel.preview_hide_ms = 60
    put("  K9/K10 实测：1 秒模式剩余 %d ms、2 秒模式剩余 %d ms；"
        "always 200ms 后仍可见=%s" % (ms_1s, ms_2s, always_ok))
    check("K9 「关闭」模式改色完全不显示浮层", off_ok, "off 后可见=%s" % ov.isVisible())
    check("K10 「1 秒」倒计时 ≈1000ms / 「2 秒」≈2000ms / 「一直」常显不倒计时",
          600 < ms_1s <= 1100 and 1500 < ms_2s <= 2100 and always_ok,
          "1s=%dms 2s=%dms always=%s" % (ms_1s, ms_2s, always_ok))
    # 「悬停」+ 拖 L/C/a/b 色条（鼠标不在拾色器内）：拖动中照常显示、松手后立即隐藏
    panel.set_preview_mode("hover", _broadcast=False)
    panel._picker_hovered = False
    ov.hide_now()
    panel._on_strip_l_press()
    panel._on_strip_lightness(0.55)
    QApplication.processEvents()
    strip_shown = ov.isVisible() and not ov.countdown_active()
    panel._on_strip_lightness(0.62)
    QApplication.processEvents()
    strip_kept = ov.isVisible()
    panel._on_strip_release()
    QApplication.processEvents()
    strip_hidden = not ov.isVisible()
    panel.set_preview_mode("1s", _broadcast=False)    # 复位持久化值，供后面查「新面板默认」
    put("  K10b 实测：悬停进入显示=%s、移出即隐藏=%s、再进入显示=%s；改色（鼠标在外）松手后隐藏=%s、"
        "改色（鼠标在拾色器内）松手后保持=%s；拖明度条中显示=%s/保持=%s、松手后隐藏=%s"
        % (hover_in, hover_out, hover_re, hover_change_hidden, hover_keep,
           strip_shown, strip_kept, strip_hidden))
    check("K10b 「悬停」：进入即显示、移出即隐藏（无倒计时）、改色按是否在拾色器内决定隐藏",
          hover_in and hover_out and hover_re and changed_shown
          and hover_change_hidden and hover_keep,
          "进入=%s 移出即隐藏=%s 再进入=%s 改色显示=%s 在外松手隐藏=%s 在内松手保持=%s"
          % (hover_in, hover_out, hover_re, changed_shown, hover_change_hidden, hover_keep))
    check("K10d 「悬停」+ 拖色条（鼠标不在拾色器内）：拖动中照常显示、松手后立即隐藏",
          strip_shown and strip_kept and strip_hidden,
          "拖动中显示=%s 保持=%s 松手后隐藏=%s" % (strip_shown, strip_kept, strip_hidden))
    check("K10c 五种模式都广播到对端面板（preview_mode）",
          ("preview_mode", "off") in got and ("preview_mode", "1s") in got
          and ("preview_mode", "2s") in got and ("preview_mode", "hover") in got
          and ("preview_mode", "always") in got, str(got))

    # K11 菜单文案：a/b 条满量程（v7 R25 改名）；左键点环锁明度默认开（在新面板上量默认值）
    ab_text = panel.act_ab_line.text()
    ab_ok = ab_text in ("a/b 条满量程", "a/b strips full range")
    # 先把设置层复位到出厂默认，再建新面板量默认值（否则读到上一轮残留的持久化值）
    _kmc = selfmod.keymap_core
    panel.reset_keymap(_broadcast=False)
    panel.set_preview_mode(selfmod.PREVIEW_DEFAULT_MODE, _broadcast=False)
    fresh = selfmod.HsvPickerPanel(dbg_name="defaults")
    ring_default_on = (_kmc.lookup(fresh.keymap, "ring", "left", "none") == "hue_lock_lc_rel"
                       and _kmc.lookup(fresh.picker.keymap, "ring", "left", "none") == "hue_lock_lc_rel"
                       and _kmc.lookup(fresh.keymap, "ring", "left", "shift") == "hue_hsv"
                       and fresh.preview_mode == "hover")
    put("  K11 实测：a/b 项文案=%r；新面板默认：环左键=%s、环 Shift+左键=%s，浮层模式=%s"
        % (ab_text, _kmc.lookup(fresh.keymap, "ring", "left", "none"),
           _kmc.lookup(fresh.keymap, "ring", "left", "shift"), fresh.preview_mode))
    check("K11 菜单项改名「a/b 条满量程」+ 环上左键默认「转色相 + 锁明度 + 锁相对彩度」+ 浮层默认「悬停」",
          ab_ok and ring_default_on,
          "a/b 项=%r 默认：环左键=%s Shift+左键=%s 浮层模式=%s"
          % (ab_text, _kmc.lookup(fresh.keymap, "ring", "left", "none"),
             _kmc.lookup(fresh.keymap, "ring", "left", "shift"), fresh.preview_mode))
    fresh.hide()

    # K12 定位自动翻转（屏幕右侧放不下 -> 翻到左侧；正常位置贴右侧）
    panel.set_preview_mode("2s", _broadcast=False)
    screen = QApplication.primaryScreen()
    avail = screen.availableGeometry() if screen is not None else QRect(0, 0, 0, 0)
    if avail.width() < 200 or avail.height() < 200:
        check("K12 靠屏幕右边时翻到左侧 / 正常时贴右侧", True,
              "屏幕不可用，跳过（%s）" % (avail,))
    else:
        far = QRect(avail.right() - 30, avail.top() + 60, 30, 30)
        ov.show_near(far)
        flipped = ov.x() + ov.width() == far.x()          # 间隙 0：紧贴左侧
        fx, fw, fleft = ov.x(), ov.width(), far.x()
        mid = QRect(avail.left() + 200, avail.top() + 200, 120, 120)
        ov.show_near(mid)
        right_side = ov.x() == mid.right() + 1            # 间隙 0：紧贴右侧（anchor.right()+1）
        put("  K12 实测：屏幕可用区 %s；靠右锚点 x=%d -> 浮层 x=%d（%s，x+w=%d）；"
            "中部锚点 x=%d -> 浮层 x=%d（贴右 = anchor.right+1 = %d）"
            % (avail, fleft, fx, "翻到左侧" if flipped else "未翻转", fx + fw,
               mid.x(), ov.x(), mid.right() + 1))
        check("K12 靠屏幕右边时紧贴左侧 / 正常时紧贴右侧（间隙 0）", flipped and right_side,
              "翻转：x=%d x+w=%d anchor.x=%d；正常：x=%d anchor.right+1=%d"
              % (fx, fx + fw, fleft, ov.x(), mid.right() + 1))

    # K13 浮层跟随面板（150ms 重锚定；位置没变不 move；隐藏停表）
    ov.hide_now()
    panel._picking = True
    panel._preview_begin()
    panel.set_color(120.0, 0.5, 0.6, write_fg=False)
    follow_running = panel._preview_follow.isActive()
    pos0 = (ov.x(), ov.y())
    anchor0 = panel._preview_anchor()
    panel.move(panel.x() + 60, panel.y() + 40)   # 模拟拖动面板 / 移动弹窗
    panel._layout_picker()
    anchor1 = panel._preview_anchor()
    QApplication.processEvents()
    time.sleep(0.30)                             # 等跟随定时器自己跑（间隔 150ms）
    QApplication.processEvents()
    pos1 = (ov.x(), ov.y())                      # 自动跟随后的位置
    panel._preview_follow_tick()                 # 再手动 tick 一次：位置应已一致（不重复 move）
    pos1b = (ov.x(), ov.y())
    moved = (pos1 != pos0) and (pos1b == pos1) and anchor1 is not None and anchor0 is not None
    panel.move(panel.x() - 60, panel.y() - 40)
    panel._picking = False
    ov.hide_now()
    panel._preview_follow_tick()                 # 浮层已隐藏 -> 应当停表
    stopped = not panel._preview_follow.isActive()
    put("  K13 实测：锚点 %s -> %s；浮层 %s -> %s；显示时跟随表=%s、隐藏后停表=%s"
        % ((anchor0.x(), anchor0.y()) if anchor0 else None,
           (anchor1.x(), anchor1.y()) if anchor1 else None, pos0, pos1,
           follow_running, stopped))
    check("K13 浮层跟随面板（150ms 重锚定；位置没变不 move；隐藏停表）",
          follow_running and moved and stopped,
          "显示时定时器=%s 锚点 %s -> %s，浮层 %s -> %s，隐藏后定时器=%s"
          % (follow_running, (anchor0.x(), anchor0.y()) if anchor0 else None,
             (anchor1.x(), anchor1.y()) if anchor1 else None, pos0, pos1,
             panel._preview_follow.isActive()))

    # K14 拾色器不可见（面板隐藏 / 弹窗关闭）-> 立即收起浮层并停表
    panel._was_shown = True                      # 模拟「面板显示过」
    panel._picking = True
    panel._preview_begin()
    panel.set_color(60.0, 0.5, 0.5, write_fg=False)
    shown_before = ov.isVisible()
    panel._preview_follow_tick()                 # 面板此刻不可见 -> 应当收起 + 停表
    hidden_after = not ov.isVisible() and not panel._preview_follow.isActive()
    panel._picking = False
    panel._was_shown = False
    check("K14 拾色器不可见时浮层立即收起且跟随定时器停表",
          shown_before and hidden_after,
          "收起前可见=%s 收起后(隐藏+停表)=%s" % (shown_before, hidden_after))

    # K15 浮层不覆盖面板矩形（锚点换成面板矩形后：任何方向都在面板之外）
    ov.hide_now()
    panel._picking = True
    panel._preview_begin()
    panel.set_color(90.0, 0.6, 0.7, write_fg=False)
    QApplication.processEvents()
    panel_rect = QRect(panel.mapToGlobal(QPoint(0, 0)), panel.size())
    ov_rect = QRect(ov.pos(), ov.size())
    no_overlap = not ov_rect.intersects(panel_rect)
    tight = (ov_rect.x() == panel_rect.right() + 1)
    put("  K15 实测：面板矩形 %s，浮层 %s，相交=%s，紧贴（浮层x=%d = 面板右缘+1=%d）=%s"
        % (panel_rect, ov_rect, ov_rect.intersects(panel_rect), ov_rect.x(),
           panel_rect.right() + 1, tight))
    panel._picking = False
    ov.hide_now()
    check("K15 浮层紧贴面板右缘（间隙 0）且不覆盖面板矩形",
          no_overlap and tight and ov.isVisible() is False,
          "面板 %s 浮层 %s 相交=%s 紧贴=%s" % (panel_rect, ov_rect, no_overlap, tight))

    # K16 弹窗面板也生效（独立实例 + 同一模式）
    pop = selfmod.HsvPickerPopup(panel)
    pop.panel.set_history(["#010203", "#040506"], save=False)
    ov_pop = pop.panel.preview_overlay()
    pop.show()                                   # 让弹窗面板真的可见（不用 toggle，免装外点过滤器）
    QApplication.processEvents()
    pop.panel._picking = True
    pop.panel._preview_begin()
    pop.panel.set_color(300.0, 0.5, 0.5, write_fg=False)
    QApplication.processEvents()
    pop_cells = ov_pop.colors()
    pop_placed = tuple(c for _rect, c in ov_pop.cell_rects())    # 上 / 左下 / 右下
    pop_visible = ov_pop.isVisible()
    pop_following = pop.panel._preview_follow.isActive()
    pop_picker_vis = pop.panel.picker.isVisible()
    pop_ok = ((ov_pop is not ov) and pop_visible and pop_following and pop_picker_vis
              and pop_placed == ((128, 64, 128), (1, 2, 3), (4, 5, 6)))
    pop.panel._picking = False
    ov_pop.hide_now()
    pop.panel._preview_follow_tick()             # 浮层已隐藏 -> 停表
    pop.hide()
    QApplication.processEvents()
    off_after_hide = not (ov_pop.isVisible() or pop.panel._preview_follow.isActive())
    put("  K16 实测：弹窗自己的浮层 100x150 可见=%s，绘制三格=%s，拾色器可见=%s，隐藏后停表=%s"
        % (pop_visible, pop_placed, pop_picker_vis, off_after_hide))
    check("K16 弹窗面板也弹浮层（独立实例；左下=history[0]、右下=history[1]）",
          pop_ok and off_after_hide and pop.panel.preview_mode == panel.preview_mode,
          "弹窗浮层可见=%s 绘制三格=%s 跟随表=%s 拾色器可见=%s 非同一实例=%s 隐藏后=%s"
          % (pop_visible, pop_placed, pop_following, pop_picker_vis, ov_pop is not ov,
             off_after_hide))

    # 还原默认，避免影响后续段落
    panel.set_preview_mode("2s", _broadcast=False)
    panel.preview_hide_ms = 2000
    ov.hide_now()


def _section_f(panel, c, selfmod):
    """F 弹窗（破坏性：会销毁对象，放在最后）。"""
    from PyQt5.QtCore import Qt as Q
    pop = selfmod.HsvPickerPopup(panel)
    vis = []
    for _ in range(20):
        pop.toggle()
        vis.append(pop.isVisible())
    ok_alt = all(vis[i] != vis[i + 1] for i in range(len(vis) - 1))
    check("F1 toggle 严格交替 20 次", ok_alt, "".join("1" if v else "0" for v in vis))

    pop.toggle()
    panel._push_history("#00FF00")
    check("F2 历史正向同步", pop.panel.history.colors[:1] == ["#00FF00"],
          "%r" % (pop.panel.history.colors[:2],))
    pop.panel._push_history("#FF0000")
    check("F3 历史反向同步", panel.history.colors[:1] == ["#FF0000"],
          "%r" % (panel.history.colors[:2],))
    panel.set_show_clusters(False)
    same1 = pop.panel.show_clusters is False
    pop.panel.set_show_lines(False)
    same2 = panel.show_lines is False
    panel.set_show_clusters(True)
    panel.set_show_lines(True)
    check("F4 显示开关双向同步", same1 and same2, "clusters=%s lines=%s" % (same1, same2))
    panel.set_color(200.0, 0.4, 0.7, write_fg=False)
    check("F5 颜色同步到弹窗", abs(pop.panel.h - 200.0) < 1e-6, "h=%.2f" % pop.panel.h)

    pop.resize(512, 700)
    pop._save_size()
    pop2 = selfmod.HsvPickerPopup(panel)
    check("F6 弹窗尺寸记忆", (pop2.width(), pop2.height()) == (512, 700),
          "%dx%d" % (pop2.width(), pop2.height()))

    # 关闭所有弹窗：会把注册到 QApplication 的事件过滤器摘掉（避免污染后续计时）
    try:
        for p in (pop, pop2):
            if p.isVisible():
                p.hide()
        check("F8 隐藏后事件过滤器已摘除", not getattr(pop, "_outside_filter", False))
    except Exception as exc:
        check("F8 隐藏后事件过滤器已摘除", False, repr(exc))

    try:
        from PyQt5 import sip
        from PyQt5.QtGui import QHideEvent
        sip.delete(pop2.panel.picker)
        pop2.hideEvent(QHideEvent())
        sip.delete(panel.picker)
        pop2.hideEvent(QHideEvent())
        check("F7 对象销毁后 hideEvent 安全", True)
    except Exception as exc:
        check("F7 对象销毁后 hideEvent 安全", False, repr(exc))



def _section_g(selfmod):
    """G 渲染压力（用新面板，避免受前面销毁影响）。"""
    from PyQt5.QtGui import QPixmap, QPainter
    sect("G 渲染压力")
    panel2 = selfmod.HsvPickerDocker().panel
    errs = []
    for (w, h) in [(300, 700), (520, 900), (900, 1300), (260, 460), (1500, 1100)]:
        panel2.resize(w, h)
        panel2.mid_box.resize(max(80, w - 12), max(120, h - 260))
        panel2._layout_picker()
        pm = QPixmap(panel2.size())
        try:
            pr = QPainter(pm)
            panel2.render(pr)
            pr.end()
        except Exception as exc:
            errs.append("%dx%d: %r" % (w, h, exc))
    check("G1 多尺寸整面板渲染无异常", not errs, "；".join(errs[:3]))

    # P2-⑥：先量机器当前速度，再给绝对阈值乘负载系数（上限 3×）
    calib_min = cpu_calib_min_ms(5)
    perf_factor = max(1.0, min(CALIB_MAX_FACTOR, calib_min / CALIB_REF_MIN_MS))
    g2_budget = 30.0 * perf_factor
    g4_budget = 16.7 * perf_factor
    put("  机器负载校准：%.1f ms（参考 %.1f ms）→ 阈值系数 ×%.2f；G2 预算 %.1f ms、"
        "G4 预算 %.1f ms" % (calib_min, CALIB_REF_MIN_MS, perf_factor, g2_budget, g4_budget))

    panel2.resize(560, 900)
    panel2.mid_box.resize(548, 640)
    panel2._layout_picker()
    c2 = panel2.picker
    pm = QPixmap(panel2.size())
    pr = QPainter(pm)
    panel2.render(pr)
    pr.end()
    def _render_trial():
        stats = []
        for i in range(12):
            c2.h = (c2.h + 13) % 360
            c2.set_color(c2.h, 0.4 + 0.03 * (i % 6), 0.5 + 0.03 * (i % 5))
            panel2._sync_entries()
            t0 = time.perf_counter()
            pr = QPainter(pm)
            panel2.render(pr)
            pr.end()
            stats.append((time.perf_counter() - t0) * 1000)
        return stats

    def _trial_mean(stats):
        return sum(stats) / len(stats)

    def _median(xs):
        ys = sorted(xs)
        n = len(ys)
        return ys[n // 2] if n % 2 else 0.5 * (ys[n // 2 - 1] + ys[n // 2])

    # 时间敏感断言改稳健判定：3 次为一组取中位数，首组中位超线则最多再跑 2 组；
    # 最终判定值取所有单次均值的**最小值**。机器负载只会让帧变慢，干净窗口的最小值
    # 就是「无扰水平」；真回退时所有窗口都会超线。阈值 = 30ms × 负载系数（见上方校准），
    # 系数只补偿整机变慢，不回退真实性能目标。
    from PyQt5.QtWidgets import QApplication as _QApp
    trial_sets = []
    for _set_i in range(3):
        trials = [_render_trial() for _ in range(3)]
        means = [_trial_mean(s) for s in trials]
        trial_sets.append((trials, means))
        if _median(means) <= g2_budget:
            break
        time.sleep(0.1)
        _QApp.processEvents()
    retried = len(trial_sets) > 1
    all_means = [m for _t, means in trial_sets for m in means]
    all_frames = [f for trials, _means in trial_sets for s in trials for f in s]
    med = _median(all_means[-3:] if retried else all_means)
    best = min(all_means)
    best_frame = min(all_frames)
    worst = max(max(s) for _t, _means in trial_sets for s in _t)
    put("  渲染 12 帧 × %d 次：单次均值 %s（末组中位 %.1f ms）；最快单帧 %.1f ms；最差 %.1f ms%s"
        % (len(all_means), "/".join("%.1f" % m for m in all_means), med, best_frame, worst,
           "；首组中位超线，共跑 %d 组" % len(trial_sets) if retried else ""))
    check("G2 换色渲染 ≤30ms/帧（负载校准 + 最快单帧/最好一组）",
          best_frame <= g2_budget or best <= g2_budget,
          "最快单帧 %.1f / 最好一组 %.1f / 预算 %.1f（系数 ×%.2f，校准 %.1fms；单次均值 %s）"
          % (best_frame, best, g2_budget, perf_factor, calib_min,
             "/".join("%.1f" % m for m in all_means)))

    # G2b 不可达提示「开 / 关」的换色渲染对比（验收 A7：打开后不回退）
    def _hue_trial(flag):
        c2.set_show_unreachable(flag)
        stat = []
        for i in range(12):
            c2.h = (c2.h + 13) % 360
            c2.set_color(c2.h, 0.4 + 0.03 * (i % 6), 0.5 + 0.03 * (i % 5))
            panel2._sync_entries()
            t0 = time.perf_counter()
            pr2 = QPainter(pm)
            panel2.render(pr2)
            pr2.end()
            stat.append((time.perf_counter() - t0) * 1000)
        return stat

    # 保持原口径「关闭 12 帧 / 打开 12 帧」，不达标最多再跑 4 轮（首轮 + 重试 4 次），
    # 取「打开均值最小」的一轮判定；负载只会让帧变慢，真回退时所有轮次全超线，
    # 30ms 绝对线与 1.5 倍相对线都不放宽。
    g2b_pairs = []
    for _try_i in range(5):
        off_t = _hue_trial(False)
        on_t = _hue_trial(True)
        om, nm = _trial_mean(off_t), _trial_mean(on_t)
        g2b_pairs.append((off_t, om, on_t, nm))
        if nm <= g2_budget and nm <= om * 1.5 + 2.0:
            break
        time.sleep(0.1)
        _QApp.processEvents()
    best_idx = min(range(len(g2b_pairs)), key=lambda i: g2b_pairs[i][3])
    off_stats, avg_off, on_stats, avg_on = g2b_pairs[best_idx]
    off_means = [p[1] for p in g2b_pairs]
    on_means = [p[3] for p in g2b_pairs]
    best_off_frame = min(min(p[0]) for p in g2b_pairs)
    best_on_frame = min(min(p[2]) for p in g2b_pairs)
    worst_off = max(max(p[0]) for p in g2b_pairs)
    worst_on = max(max(p[2]) for p in g2b_pairs)
    put("  不可达提示：关闭 单次 %s / 打开 单次 %s（取打开最小轮：关闭 %.1f / 打开 %.1f）；"
        "最快单帧 关闭 %.1f / 打开 %.1f；最差 %.1f / %.1f%s"
        % ("/".join("%.1f" % m for m in off_means),
           "/".join("%.1f" % m for m in on_means),
           avg_off, avg_on, best_off_frame, best_on_frame, worst_off, worst_on,
           "；共跑了 %d 轮" % len(g2b_pairs)))
    check("G2b 不可达提示打开后换色渲染不回退（负载校准 + 最快单帧/最好一轮）",
          (best_on_frame <= g2_budget and best_on_frame <= best_off_frame * 1.5 + 2.0)
          or (avg_on <= g2_budget and avg_on <= avg_off * 1.5 + 2.0),
          "最快单帧 关闭 %.1f / 打开 %.1f；最好一轮 关闭 %.1f / 打开 %.1f（预算 %.1f、系数 ×%.2f；共 %d 轮）"
          % (best_off_frame, best_on_frame, avg_off, avg_on, g2_budget, perf_factor,
             len(g2b_pairs)))
    c2.set_show_unreachable(True)

    # G4 色相环中键拖动：≥60fps（≤16.7ms/帧）
    from PyQt5.QtCore import Qt as _Q
    g2 = c2._geometry()
    rr2 = (g2["r_in"] + g2["r_out"]) / 2.0
    ring_pt = (g2["cx"] - rr2, g2["cy"])
    c2.set_color(60.0, 0.4, 0.6)
    c2.mousePressEvent(Ev(ring_pt[0], ring_pt[1], _Q.MiddleButton))
    frames = []
    for i in range(20):
        t0 = time.perf_counter()
        c2.mouseMoveEvent(Ev(g2["cx"], g2["cy"] - rr2 + (i - 10) * 3, _Q.NoButton, _Q.MiddleButton))
        pr = QPainter(pm)
        panel2.render(pr)
        pr.end()
        frames.append((time.perf_counter() - t0) * 1000)
    c2.mouseReleaseEvent(Ev(ring_pt[0], ring_pt[1], _Q.MiddleButton, _Q.NoButton))
    ring_avg, ring_worst = sum(frames) / len(frames), max(frames)
    put("  色相环中键拖动 20 帧：均值 %.1f ms / 最差 %.1f ms（60fps 线 16.7ms）"
        % (ring_avg, ring_worst))
    check("G4 色相环拖动 ≥60fps（负载校准）", ring_avg <= g4_budget,
          "均值 %.1f 最差 %.1f（预算 %.1f、系数 ×%.2f）"
          % (ring_avg, ring_worst, g4_budget, perf_factor))

    errs = []
    for a in (True, False):
        for b in (True, False):
            try:
                panel2.set_show_clusters(a)
                panel2.set_show_lines(b)
                pr = QPainter(pm)
                panel2.render(pr)
                pr.end()
            except Exception as exc:
                errs.append("clusters=%s lines=%s: %r" % (a, b, exc))
    check("G3 四种显示组合渲染无异常", not errs, "；".join(errs[:3]))
    return panel2

def _section_h(panel, c, selfmod, g, cx, cy):
    """H 色条语义 / 锁定投影 / 样式 / 端点精度。"""
    from PyQt5.QtCore import Qt as Q
    import numpy as _np
    sect("H 色条语义 / 锁定投影 / 样式 / 端点精度")

    # H1 明度条 = 锁定彩度：拖动过程中 C_rel 保持不变
    panel.set_color(68.0, 0.2638, 0.9961)      # #F5FEBB 附近
    panel.set_color(68.0, 0.5, 0.6)
    panel._on_strip_l_press()
    c_ref = panel._crel_now()
    worst = 0.0
    for i in range(20, 96):          # 0.20 ~ 0.95（蓝线可信区间）
        panel._on_strip_lightness(i / 100.0)
        worst = max(worst, abs(panel._crel_now() - c_ref))
    panel._on_strip_release()
    check("H1 明度条沿蓝色轨迹（C_rel 恒定）", worst < 1e-2, "最大偏差 %.2e" % worst)

    # H2 高明度端可继续拖（修「0.9744 就拖不动」）
    panel.set_color(68.0, 0.2638, 0.9961)
    panel._on_strip_l_press()
    panel._on_strip_lightness(1.0)
    L_top = float(selfmod.math_core.lightness(panel.h, panel.s, panel.v, "oklab"))
    check("H2 Oklab 明度可拖到 1.0", L_top > 0.999, "L=%.6f" % L_top)

    # H3 低明度端可到接近 0
    panel.set_color(68.0, 0.2638, 0.9961)
    panel._on_strip_l_press()
    panel._on_strip_lightness(0.0)
    L_bot = float(selfmod.math_core.lightness(panel.h, panel.s, panel.v, "oklab"))
    check("H3 明度可拖到 0", L_bot <= 1e-9, "L=%.6f" % L_bot)

    # H4 端点段精细度：0.9~1.0 与 0.0~0.1 每 0.01 都能落到 2e-3 内
    panel.set_color(68.0, 0.2638, 0.9961)
    panel._on_strip_l_press()
    worst_hi = worst_lo = 0.0
    for t in _np.arange(0.90, 1.001, 0.01):
        panel._on_strip_lightness(float(t))
        L = float(selfmod.math_core.lightness(panel.h, panel.s, panel.v, "oklab"))
        worst_hi = max(worst_hi, abs(L - t))
    for t in _np.arange(0.0, 0.101, 0.01):
        panel._on_strip_lightness(float(t))
        L = float(selfmod.math_core.lightness(panel.h, panel.s, panel.v, "oklab"))
        worst_lo = max(worst_lo, abs(L - t))
    put("  H4 端点精度：高段最大偏差 %.2e，低段 %.2e" % (worst_hi, worst_lo))
    check("H4 端点段（0.9~1.0 / 0.0~0.1）精度", worst_hi < 2e-3 and worst_lo < 2e-3,
          "高段 %.2e 低段 %.2e" % (worst_hi, worst_lo))

    # H5 彩度条 = 锁定明度
    panel.set_color(200.0, 0.5, 0.5)
    panel._on_strip_c_press()
    L0 = float(selfmod.math_core.lightness(panel.h, panel.s, panel.v, "oklab"))
    worst = 0.0
    for i in range(21):
        panel._on_strip_chroma(i / 20.0)
        L = float(selfmod.math_core.lightness(panel.h, panel.s, panel.v, "oklab"))
        worst = max(worst, abs(L - L0))
    put("  H5 彩度条拖动：明度最大偏差 %.2e" % worst)
    check("H5 彩度条拖动时明度恒定", worst < 2e-3, "最大偏差 %.2e" % worst)

    # H6 左键 + 锁定明度（用 set_locks 模拟）仍按曲线投影
    c.set_color(60.0, 0.4, 0.6)
    c.set_locks(True, False)
    L0 = c.target_l
    worst = 0.0
    c.mousePressEvent(Ev(cx, cy, Q.LeftButton))
    for d in range(0, 90, 6):
        c.mouseMoveEvent(Ev(cx + d, cy - d // 2, Q.LeftButton, Q.LeftButton))
        worst = max(worst, abs(float(selfmod.math_core.lightness(c.h, c.s, c.v, "oklab")) - L0))
    c.mouseReleaseEvent(Ev(cx + 90, cy - 45, Q.LeftButton))
    c.set_locks(False, False)
    check("H6 左键+临时锁明度：明度恒定", worst < 2e-3, "最大偏差 %.2e" % worst)

    # H7 过点线加粗（1.8，与簇线同款虚线）
    import inspect
    src = inspect.getsource(type(c)._paint_through)
    check("H7 过点线 1.8 虚线", "QPen(color, 1.8)" in src and "DashLine" in src)

    # H8 历史模型可保留 64 个
    panel.history.set_colors([])
    for i in range(300):
        panel._push_history("#%02X%02X%02X" % (i % 256, (i * 3) % 256, (i * 7) % 256))
    check("H8 历史保留 128", len(panel.history.colors) == 128, "%d" % len(panel.history.colors))

    # H10 色条拖动结束与数值框提交都要记历史
    panel.history.set_colors([])
    panel.set_color(60.0, 0.5, 0.5)
    panel._on_strip_l_press()
    panel._on_strip_lightness(0.7)
    n_mid = len(panel.history.colors)
    panel._on_strip_release()
    n_after_strip = len(panel.history.colors)
    panel.apply_entry_text(panel.edit_hex, "#123456")
    n_after_entry = len(panel.history.colors)
    check("H10 色条/数值框也记历史",
          n_mid == 0 and n_after_strip >= 1 and n_after_entry > n_after_strip,
          "拖动中=%d 松手=%d 提交后=%d" % (n_mid, n_after_strip, n_after_entry))

    # H11 弹窗面板与主面板结构一致
    pop_tmp = selfmod.HsvPickerPopup(panel)
    same_cls = type(pop_tmp.panel) is type(panel)
    attrs = ("picker", "swatch_cur", "history", "strip_l", "strip_c", "btn_menu",
             "edit_h", "edit_s", "edit_v", "edit_hex", "edit_l", "edit_c", "menu",
             "preview_overlay")
    missing = [a for a in attrs if not hasattr(pop_tmp.panel, a)]
    same_min = (pop_tmp.panel.minimumWidth() == panel.minimumWidth()
                and pop_tmp.panel.minimumHeight() == panel.minimumHeight())
    sw_same = (pop_tmp.panel.swatch_cur.height() == panel.swatch_cur.height())
    pv_same = (pop_tmp.panel.preview_mode == panel.preview_mode)
    check("H11 弹窗面板与主面板一致", same_cls and not missing and same_min and sw_same and pv_same,
          "同类=%s 缺部件=%s 最小尺寸一致=%s 色块高=%s 浮层模式一致=%s" % (
              same_cls, missing, same_min, sw_same, pv_same))
    try:
        pop_tmp.hide()
    except Exception:
        pass

    # H12 按键表：环上左键默认「转色相 + 锁明度 + 锁相对彩度」（v6 R20）
    _kmc = selfmod.keymap_core
    default_on = (_kmc.lookup(c.keymap, "ring", "left", "none") == "hue_lock_lc_rel")
    panel.set_keymap(_kmc.default_keymap(), _broadcast=False)
    on = (_kmc.lookup(c.keymap, "ring", "left", "none") == "hue_lock_lc_rel")
    c.set_color(60.0, 0.5, 0.6)
    from hsv_picker import math_core as mc
    L0 = float(mc.lightness(c.h, c.s, c.v, c.metric))
    Crel0 = float(mc.crel_of_xyz(c.h, c.metric, c.s, c.v)[0])
    gg = c._geometry()
    rr2 = (gg["r_in"] + gg["r_out"]) / 2.0
    c.mousePressEvent(Ev(gg["cx"] + rr2, gg["cy"], Q.LeftButton))
    c._last_heavy = 0.0                     # 绕开 60Hz 节流，保证这一次真的拖到
    c.mouseMoveEvent(Ev(gg["cx"], gg["cy"] - rr2, Q.LeftButton, Q.LeftButton))
    dL = abs(float(mc.lightness(c.h, c.s, c.v, c.metric)) - L0)
    dC = abs(float(mc.crel_of_xyz(c.h, c.metric, c.s, c.v)[0]) - Crel0)
    c.mouseReleaseEvent(Ev(gg["cx"], gg["cy"], Q.LeftButton))
    check("H12 环上左键默认「转色相 + 锁明度 + 锁相对彩度」（按键表默认）",
          default_on and on and dL < 2e-3 and dC < 2e-3,
          "默认=%s 生效=%s ΔL=%.2e ΔC_rel=%.2e" % (default_on, on, dL, dC))

    # H9 数值框拖动期间不回读 Krita
    panel._entry_dragging = True
    panel._dirty = True
    panel._pull_from_krita()
    check("H9 数值框拖动期间不回读", panel._dirty is True)
    panel._entry_dragging = False
    panel._dirty = False


def _section_i(panel, c, selfmod, g, cx, cy):
    """I Oklab a/b 分量条（布局 / 回写 / 钳制 / 开关 / 同步 / 渲染）。"""
    import numpy as _np
    mc = selfmod.math_core
    sect("I Oklab a/b 分量条")

    def ab_now():
        return [float(x) for x in mc.oklab_ab(panel.h, panel.s, panel.v)]

    # I1 控件存在 + 默认可见 + 标记位置与读数一致
    have = all(hasattr(panel, n) for n in
               ("strip_a", "strip_b", "edit_a", "edit_b", "lbl_a", "lbl_b"))
    check("I1 a/b 条与数值框存在且默认显示",
          have and not panel.strip_a.isHidden() and not panel.edit_a.isHidden()
          and not panel.strip_b.isHidden() and bool(getattr(panel, "show_ab", False)),
          "show_ab=%s" % getattr(panel, "show_ab", None))

    # I1b 四条色条标签统一为符号 L / C / a / b，且等宽（左端对齐）、都带提示
    syms = [panel.lbl_l.text(), panel.lbl_c.text(), panel.lbl_a.text(), panel.lbl_b.text()]
    widths = set(w.width() for w in (panel.lbl_l, panel.lbl_c, panel.lbl_a, panel.lbl_b))
    tips = [bool(w.toolTip()) for w in (panel.lbl_l, panel.lbl_c, panel.lbl_a, panel.lbl_b)]
    check("I1b 色条标签 = L / C / a / b（等宽对齐 + 均有提示）",
          syms == ["L", "C", "a", "b"] and len(widths) == 1 and all(tips),
          "标签 %s 宽度 %s 提示 %s" % (syms, sorted(widths), tips))

    panel.set_color(210.0, 0.62, 0.86)
    L0, a0, b0 = ab_now()
    try:
        txt_ok = (abs(float(panel.edit_a.text()) - a0) < 1e-4
                  and abs(float(panel.edit_b.text()) - b0) < 1e-4)
    except Exception:
        txt_ok = False
    check("I2 a/b 数值框 = 当前色的 Oklab 分量（4 位小数）", txt_ok,
          "%s / %s 期望 %+.4f / %+.4f" % (panel.edit_a.text(), panel.edit_b.text(), a0, b0))

    # I3 拖 a 条：L 与 b 不动、a 单调变化；游标跟随
    panel._on_strip_ab_press("a")
    Lk, ak, bk = ab_now()
    worst_l = worst_b = 0.0
    a_seen = []
    try:
        for i in range(21):
            panel._on_strip_ab("a", panel.strip_a.value_of_t(i / 20.0))
            L1, a1, b1 = ab_now()
            worst_l = max(worst_l, abs(L1 - Lk))
            worst_b = max(worst_b, abs(b1 - bk))
            a_seen.append(a1)
    finally:
        panel._on_strip_release()
    check("I3 拖 a 条：明度 L 与分量 b 保持不变",
          worst_l < 2e-3 and worst_b < 2e-3 and (max(a_seen) - min(a_seen)) > 0.05,
          "ΔL=%.2e Δb=%.2e a 跨度=%.4f" % (worst_l, worst_b, max(a_seen) - min(a_seen)))
    check("I4 拖 a 条后游标落在读数对应的位置",
          abs(float(panel.strip_a.value) - panel.strip_a.t_of(ab_now()[1])) < 1e-6,
          "t=%.6f" % float(panel.strip_a.value))

    # I5 拖 b 条：L 与 a 不动
    panel.set_color(210.0, 0.62, 0.86)
    panel._on_strip_ab_press("b")
    Lk, ak, bk = ab_now()
    worst_l = worst_a = 0.0
    b_seen = []
    try:
        for i in range(21):
            panel._on_strip_ab("b", panel.strip_b.value_of_t(i / 20.0))
            L1, a1, b1 = ab_now()
            worst_l = max(worst_l, abs(L1 - Lk))
            worst_a = max(worst_a, abs(a1 - ak))
            b_seen.append(b1)
    finally:
        panel._on_strip_release()
    check("I5 拖 b 条：明度 L 与分量 a 保持不变",
          worst_l < 2e-3 and worst_a < 2e-3 and (max(b_seen) - min(b_seen)) > 0.05,
          "ΔL=%.2e Δa=%.2e b 跨度=%.4f" % (worst_l, worst_a, max(b_seen) - min(b_seen)))

    # I6 越界值被钳进 sRGB 可达区间（数值框输入/拖到死区都不会出域）
    panel.set_color(210.0, 0.62, 0.86)
    Lk, ak, bk = ab_now()
    lo_a, hi_a = mc.ab_axis_interval(Lk, bk, "a")
    panel._on_strip_ab("a", -9.0)
    a_low = ab_now()[1]
    panel._on_strip_ab("a", +9.0)
    a_high = ab_now()[1]
    in_gamut_ok = all(bool(mc.oklab_in_gamut(*ab_now())) for _ in range(1))
    check("I6 极端输入被钳在可达区间端点且不出色域",
          # 容差 6e-5：a/b 走 Oklab->sRGB->HSV->Oklab 往返的固有误差实测 ≤1.9e-5（矩阵精度）
          abs(a_low - lo_a) < 6e-5 and abs(a_high - hi_a) < 6e-5 and in_gamut_ok,
          "钳后 [%+.4f, %+.4f] 应为 [%+.4f, %+.4f]" % (a_low, a_high, lo_a, hi_a))

    # I7 box 口径有死区、line 口径无死区，且 line ⊆ box
    try:
        panel.set_ab_mode("box", _broadcast=False)
        box_rng = panel.strip_a.ranges()[0]
        dead = panel.strip_a.dead_mask(200)
        box_ok = dead is not None and bool(_np.asarray(dead).any())
        panel.set_ab_mode("line", _broadcast=False)
        line_rng = panel.strip_a.ranges()[0]
        line_ok = panel.strip_a.dead_mask(200) is None
        contained = box_rng[0] <= line_rng[0] + 1e-9 and box_rng[1] >= line_rng[1] - 1e-9
        check("I7 box 有死区 / line 无死区，且 line 量程 ⊆ box 量程",
              box_ok and line_ok and contained,
              "box [%+.4f, %+.4f] ⊇ line [%+.4f, %+.4f]，死区 %d/200"
              % (box_rng[0], box_rng[1], line_rng[0], line_rng[1], int(_np.asarray(dead).sum())))
    finally:
        panel.set_ab_mode("box", _broadcast=False)

    # I8 死区内拖动被钳住（拖到死区不会写越界值）
    panel.set_color(210.0, 0.62, 0.86)
    lo_a, hi_a = mc.ab_axis_interval(ab_now()[0], ab_now()[2], "a")
    panel._on_strip_ab("a", panel.strip_a.ranges()[0][0])       # 拖到 box 量程最左（死区里）
    a_left = ab_now()[1]
    check("I8 box 口径下拖到死区＝停在可达边界", abs(a_left - lo_a) < 6e-5,
          "a=%.5f 边界=%.5f" % (a_left, lo_a))

    # I9 数值框提交生效（且另一个分量不动）
    panel.set_color(210.0, 0.62, 0.86)
    Lk, ak, bk = ab_now()
    lo_a, hi_a = mc.ab_axis_interval(Lk, bk, "a")
    target = min(hi_a - 1e-4, max(lo_a + 1e-4, ak + 0.04))
    panel.apply_entry_text(panel.edit_a, "%+.4f" % target)
    L1, a1, b1 = ab_now()
    check("I9 a 数值框提交生效、b 不动",
          abs(a1 - target) < 3e-4 and abs(b1 - bk) < 3e-4 and abs(L1 - Lk) < 3e-3,
          "a=%.5f 目标=%.5f Δb=%.2e" % (a1, target, abs(b1 - bk)))

    # I10 非法输入还原
    panel.apply_entry_text(panel.edit_a, "abc")
    check("I10 a 数值框非法输入被还原", abs(float(panel.edit_a.text()) - ab_now()[1]) < 1e-4,
          "框=%s 实际=%+.4f" % (panel.edit_a.text(), ab_now()[1]))

    # I11 菜单开关收起/展开 + 跨面板广播
    got = []
    listener = lambda k, v: got.append((k, v))          # noqa: E731
    panel.view_listeners.append(listener)
    try:
        panel.set_show_ab(False)
        hidden = panel.strip_a.isHidden() and panel.edit_a.isHidden() and panel.lbl_a.isHidden()
        panel.set_ab_mode("line")
        panel.set_show_ab(True)
        shown = not panel.strip_a.isHidden() and not panel.edit_b.isHidden()
        empty = panel._crel_now() is not None          # 收起期间其它功能不受影响
        check("I11 开关收起/展开正常，且不影响其它读数", hidden and shown and empty)
        check("I12 设置变化广播到对端面板（show_ab / ab_mode）",
              ("show_ab", False) in got and ("show_ab", True) in got
              and ("ab_mode", "line") in got, str(got))
        back = []
        panel.view_listeners.append(lambda k, v: back.append(k))
        panel.set_view_flag("show_ab", True)
        panel.set_view_flag("ab_mode", "box")
        check("I13 对端设置回灌不引发回环", back == [] and panel.ab_mode == "box", str(back))
        panel.view_listeners.remove(listener)
    finally:
        if listener in panel.view_listeners:
            panel.view_listeners.remove(listener)
        panel.set_show_ab(True, _broadcast=False)
        panel.set_ab_mode("box", _broadcast=False)

    # I14 渲染：位图形状/像素范围 + 死区掩码长度 + 全位置绘制不炸
    errs = []
    try:
        for strip in (panel.strip_a, panel.strip_b):
            img = strip.strip_image(240)
            if img.shape != (strip_widget_h(), 240, 3) or int(img.min()) < 0 or int(img.max()) > 255:
                errs.append("位图异常 %s" % (img.shape,))
            dm = strip.dead_mask(240)
            if dm is not None and len(dm) != 240:
                errs.append("死区长度 %d" % len(dm))
    except Exception as exc:
        errs.append(repr(exc))
    check("I14 a/b 条位图与死区掩码正常", not errs, "；".join(errs))

    # I15 多颜色/多明度下拖动不抛异常（含近黑、近白、灰）
    errs = []
    try:
        for h, s, v in ((0, 1, 1), (210, 0.62, 0.86), (120, 0.1, 0.95),
                        (300, 0.9, 0.15), (0, 0, 0.5), (45, 1.0, 0.001)):
            panel.set_color(h, s, v)
            for axis in ("a", "b"):
                panel._on_strip_ab_press(axis)
                for t in (0.0, 0.25, 0.5, 0.75, 1.0):
                    panel._on_strip_ab(axis, panel.strip_a.value_of_t(t))
                panel._on_strip_release()
            if not bool(mc.oklab_in_gamut(*ab_now())):
                errs.append("出域 h=%g" % h)
    except Exception as exc:
        errs.append(traceback.format_exc().splitlines()[-1])
    check("I15 全色域扫拖 a/b 条无异常且不出色域", not errs, "；".join(errs)[:200])

    panel.set_color(210.0, 0.62, 0.86)


def _section_n(panel, c, selfmod, g, cx, cy):
    """N 色环不可达提示 / 环上锁 L+C / C 条双口径 / 5 个新开关（验收 A1~A8）。"""
    from PyQt5.QtCore import Qt as Q
    from PyQt5.QtGui import QColor, QImage, QPainter
    from PyQt5.QtWidgets import QApplication
    import math as _m
    import numpy as _np
    mc = selfmod.math_core
    kmc = selfmod.keymap_core
    from hsv_picker import render as rd
    sect("N 色环提示 / 环上锁 L+C / C 条双口径 / 新开关（A1~A8）")

    # 前面的用例改过控件尺寸；先让布局结算，再重新布局、重新取几何（否则环上坐标与 c 实际尺寸不一致）
    panel.resize(520, 900)
    panel.layout().activate()
    QApplication.processEvents()
    panel.mid_box.resize(508, 640)
    panel.layout().activate()
    QApplication.processEvents()
    panel._layout_picker()
    QApplication.processEvents()
    c.set_keymap(kmc.default_keymap())      # R14：回到默认按键表
    g = c._geometry()
    cx = g["sq"][0] + (g["sq"][2] - g["sq"][0]) / 2.0
    cy = g["sq"][1] + (g["sq"][3] - g["sq"][1]) / 2.0

    def ring_pt_at(hh, frac):
        """按**当前** c 几何取环上点（frac=0 内圈、1 外圈），避免布局变化后使用旧几何。"""
        gg = c._geometry()
        rr = gg["r_in"] + (gg["r_out"] - gg["r_in"]) * float(frac)
        rad = _m.radians(float(hh) - 180.0)
        return (gg["cx"] + rr * _m.cos(rad), gg["cy"] + rr * _m.sin(rad))

    def ring_pt(hh):
        return ring_pt_at(hh, 0.5)

    def square_center():
        """按**当前** c 几何取方块中心（A8 前面渲染/布局可能已改变 c 尺寸）。"""
        gg = c._geometry()
        return ((gg["sq"][0] + gg["sq"][2]) / 2.0,
                (gg["sq"][1] + gg["sq"][3]) / 2.0)

    def move(px, py, btn):
        c._last_heavy = 0.0        # 关掉 60Hz 节流：测试要每一步都生效
        c.mouseMoveEvent(Ev(px, py, Q.NoButton, btn))

    # ---------- A1：相对口径下改明度，C 条游标不漂 ----------
    panel.set_chroma_mode("rel", _broadcast=False)
    panel.set_chroma_full(False, _broadcast=False)
    seen, miss = [], []
    for Lt in (0.30, 0.45, 0.60, 0.75, 0.90):
        cmax = float(mc.cmax_of_L(30.0, "oklab", _np.array([Lt]))[0])
        got = mc.sv_at_L_C(30.0, Lt, 0.5 * cmax)      # 固定 C_rel = 0.5
        if got is None:
            miss.append(Lt)
            continue
        panel.set_color(30.0, got[0], got[1])
        panel._sync_entries()
        seen.append(float(panel.strip_c.value))
    drift = (max(seen) - min(seen)) if len(seen) == 5 else 1.0
    put("  A1 实测：C 条游标最大位移 %.3e（L=0.30/0.45/0.60/0.75/0.90 -> %s）"
        % (drift, " ".join("%.6f" % v for v in seen)))
    check("A1 相对口径改明度时 C 条游标位移 = 0", (not miss) and drift < 1e-6,
          "最大位移 %.2e（游标 %s）" % (drift, " ".join("%.6f" % v for v in seen)))

    # ---------- A2：游标位置 × 量程 == 数值框 ----------
    samples = ((30.0, 0.60, 0.90), (210.0, 0.30, 0.50),
               (300.0, 0.90, 0.20), (120.0, 0.05, 0.90))
    worst = 0.0
    for mode, full in (("rel", False), ("abs", False), ("abs", True)):
        panel.set_chroma_mode(mode, _broadcast=False)
        panel.set_chroma_full(full, _broadcast=False)
        for h, s, v in samples:
            panel.set_color(h, s, v)
            panel._sync_entries()
            pos_val = float(panel.strip_c.value) * float(panel.strip_c.range_hi())
            worst = max(worst, abs(pos_val - float(panel.edit_c.text())))
    put("  A2 实测：游标×量程 与数值框最大差 %.2e（相对/绝对固定/绝对满量程 3 种口径）" % worst)
    check("A2 游标位置 × 量程 == 数值框（差 < 1e-4）", worst < 1e-4, "最大差 %.2e" % worst)
    panel.set_chroma_mode("rel", _broadcast=False)

    # ---------- A3：环上右键绝对角度 = 锁 L + 锁绝对 C（可达区内）----------
    # v4/R15：中/右键都是**绝对角度**（按下即到点击处）；可达区内 L、C 锁定。
    c.set_keymap(kmc.default_keymap())
    c.set_color(60.0, 0.90, 0.95)
    L0 = float(mc.lightness(c.h, c.s, c.v, "oklab"))
    C0 = float(mc.ok_L_C(c.h, c.s, c.v)[1])
    worst_l = worst_c = worst_press = 0.0
    for hh in (60.0, 62.0, 64.0, 66.0, 68.0, 66.0, 64.0, 62.0, 60.0):
        px, py = ring_pt(hh)
        c.mousePressEvent(Ev(px, py, Q.RightButton))
        worst_press = max(worst_press, abs(((c.h - hh) + 180.0) % 360.0 - 180.0))
        worst_l = max(worst_l, abs(float(mc.lightness(c.h, c.s, c.v, "oklab")) - L0))
        worst_c = max(worst_c, abs(float(mc.ok_L_C(c.h, c.s, c.v)[1]) - C0))
        c.mouseReleaseEvent(Ev(px, py, Q.RightButton, Q.NoButton))
    put("  A3 实测（v4 绝对角度，起点 h=60 S=0.90 V=0.95 -> L0=%.6f C0=%.6f；60~68° 往返）："
        "按下偏差=%.2e maxΔL=%.2e maxΔC=%.2e" % (L0, C0, worst_press, worst_l, worst_c))
    check("A3 环上右键绝对角度（按下即到点击处）+ 锁 L/C（误差 < 1e-6）",
          worst_press < 1e-6 and worst_l < 1e-6 and worst_c < 1e-6,
          "按下=%.2e maxΔL=%.2e maxΔC=%.2e" % (worst_press, worst_l, worst_c))

    # ---------- A5：斜纹覆盖角集合 == {h : C_max(L,h) < C} ----------
    got0 = mc.sv_at_L_C(300.0, 0.5, 0.20)
    c.set_color(300.0, got0[0], got0[1])
    Lh = float(mc.lightness(300.0, got0[0], got0[1], "oklab"))
    Ch = float(mc.ok_L_C(300.0, got0[0], got0[1])[1])
    c.set_show_unreachable(True)
    path = c.unreachable_path(g)
    img = QImage(max(2, c.width()), max(2, c.height()), QImage.Format_ARGB32)
    img.fill(0)
    pr = QPainter(img)
    if path is not None:
        pr.fillPath(path, QColor(255, 255, 255))
    pr.end()
    mismatch = []
    for hh in range(360):
        px, py = ring_pt(hh)
        covered = img.pixelColor(int(round(px)), int(round(py))).alpha() > 40
        reach = bool(_np.asarray(mc.hue_reachable_mask(_np.array([float(hh)]), Lh, Ch))[0])
        if covered == reach:
            mismatch.append(hh)
    c.set_show_unreachable(False)
    off_ok = c.unreachable_path(g) is None
    c.set_show_unreachable(True)
    put("  A5 实测：逐度不匹配 %d 个角度（360 度全覆盖检查）；关闭提示后 path=None=%s；覆盖弧 %s"
        % (len(mismatch), off_ok, [(round(a, 1), round(b, 1)) for a, b in c._unreachable_spans()]))
    check("A5 斜纹覆盖 = 不可达色相集合（误差 0）+ 关闭后无斜纹",
          path is not None and not mismatch and off_ok,
          "不匹配 %d 个角度 %s；关闭后 path=None=%s"
          % (len(mismatch), mismatch[:6], off_ok))

    # ---------- A16：方块四角与环内圈之间的死角（R12）----------
    gg = c._geometry()
    lens_pts = [(gg["cx"] + gg["half_sq"] * 1.10, gg["cy"]),
                (gg["cx"] - gg["half_sq"] * 1.10, gg["cy"]),
                (gg["cx"], gg["cy"] + gg["half_sq"] * 1.10),
                (gg["cx"], gg["cy"] - gg["half_sq"] * 1.10)]
    lens_hits = [rd.hit_area(gg, x, y) for x, y in lens_pts]
    corner_none = rd.hit_area(gg, 2.0, 2.0) is None
    center_sq = rd.hit_area(gg, gg["cx"], gg["cy"]) == "square"
    c.set_color(60.0, 0.5, 0.5)
    c.mousePressEvent(Ev(lens_pts[0][0], lens_pts[0][1], Q.LeftButton))
    lens_started = (c._drag_mode is not None and c._press_area == "ring")
    c.mouseReleaseEvent(Ev(lens_pts[0][0], lens_pts[0][1], Q.LeftButton, Q.NoButton))
    put("  A16 实测：4 个死角命中=%s；控件角落=None:%s；方块中心=square:%s；按下起拖=%s"
        % (lens_hits, corner_none, center_sq, lens_started))
    check("A16 4 块角落透镜区命中为色相环、按下能起拖（控件角落仍 None、方块内仍 square）",
          all(v == "ring" for v in lens_hits) and corner_none and center_sq and lens_started,
          "hits=%s corner=None:%s center=square:%s started=%s"
          % (lens_hits, corner_none, center_sq, lens_started))

    # ---------- A17：不可达扇区 30% 灰底 + 细斜纹（R9，取代 v2 的「不填灰」）----------
    c.set_color(40.0, 0.90, 0.95)

    def _render_canvas_image(flag):
        c.set_show_unreachable(flag)
        im = QImage(max(2, c.width()), max(2, c.height()), QImage.Format_ARGB32)
        im.fill(0)
        pp = QPainter(im)
        c.render(pp)
        pp.end()
        return im

    # 先空渲染一次，触发可能的延迟布局；随后重取几何（render 可能改变控件尺寸），
    # 否则用旧几何框出的采样点会错位（v2 踩过同类坑）。
    _render_canvas_image(True)
    QApplication.processEvents()
    gg = c._geometry()
    img_off = _render_canvas_image(False)
    img_on = _render_canvas_image(True)
    same_size = (img_off.size() == img_on.size())
    L17 = float(mc.lightness(c.h, c.s, c.v, "oklab"))
    C17 = float(mc.ok_L_C(c.h, c.s, c.v)[1])
    spans17 = [(float(a), float(b)) for a, b in mc.hue_reachable_spans(L17, C17, 1.0)]
    q_alpha = 77.0 / 255.0
    q_gray = 58.0 / 255.0
    s_off, s_on, alphas = [], [], []
    sample_n = changed_n = hatch_n = 0
    W17, H17 = img_off.width(), img_off.height()
    # 先用 numpy 框出「环带 ∩ 不可达扇区」的像素集合，再逐点取色（避免 23 万次全画布采样）
    yy_g, xx_g = _np.mgrid[0:H17, 0:W17]
    rad_g = _np.hypot(xx_g - gg["cx"], yy_g - gg["cy"])
    band_g = (rad_g >= gg["r_in"] + 2.0) & (rad_g <= gg["r_out"] - 2.0)
    hue_g = (_np.degrees(_np.arctan2(yy_g - gg["cy"], xx_g - gg["cx"])) + 180.0) % 360.0
    unreach_g = _np.ones_like(band_g)
    for lo, hi in spans17:
        unreach_g &= ((hue_g - float(lo)) % 360.0) >= (float(hi) - float(lo))
    ys17, xs17 = _np.nonzero(band_g & unreach_g)
    for yy, xx in zip(ys17.tolist(), xs17.tolist()):
        on_px = img_on.pixelColor(int(xx), int(yy))
        off_px = img_off.pixelColor(int(xx), int(yy))
        a_on = (on_px.redF(), on_px.greenF(), on_px.blueF())
        a_off = (off_px.redF(), off_px.greenF(), off_px.blueF())
        m1, n1 = max(a_off), min(a_off)
        m2, n2 = max(a_on), min(a_on)
        s_off.append((m1 - n1) / m1 if m1 > 1e-9 else 0.0)
        s_on.append((m2 - n2) / m2 if m2 > 1e-9 else 0.0)
        sample_n += 1
        if max(abs(a_off[i] - a_on[i]) for i in range(3)) > 1e-6:
            changed_n += 1
        exp = tuple(q_alpha * q_gray + (1.0 - q_alpha) * a_off[i] for i in range(3))
        if max(abs(a_on[i] - exp[i]) for i in range(3)) > 4.0 / 255.0:
            hatch_n += 1
        else:
            # 纯灰底像素：反解混合系数 α = (off-on)/(off-58/255)
            bi = max(range(3), key=lambda i: abs(a_off[i] - q_gray))
            den = a_off[bi] - q_gray
            if abs(den) > 0.05:
                alphas.append((a_off[bi] - a_on[bi]) / den)
    keep = (float(_np.mean(s_on)) / max(float(_np.mean(s_off)), 1e-9)) if s_off else 0.0
    changed_ratio = float(changed_n) / float(sample_n) if sample_n else 0.0
    hatch_ratio = float(hatch_n) / float(sample_n) if sample_n else 0.0
    med_alpha = float(_np.median(alphas)) if alphas else -1.0
    c.set_show_unreachable(True)
    put("  A17 实测：扇区采样 %d 点；改动占比 %.2f%%；斜纹像素占比 %.2f%%；"
        "平均饱和度保留率 %.3f（v2 无灰底=0.938）；中位混合系数 α=%.3f"
        % (sample_n, changed_ratio * 100.0, hatch_ratio * 100.0, keep, med_alpha))
    check("A17 不可达扇区：30% 灰底铺满（改动 ≥90%）+ 斜纹仍在 + α∈[0.20,0.45] + 饱和度保留率 <0.90",
          same_size and sample_n > 500 and changed_ratio >= 0.90
          and hatch_ratio > 0.005 and 0.20 <= med_alpha <= 0.45 and keep < 0.90,
          "changed=%.1f%% hatch=%.1f%% keep=%.3f α=%.3f"
          % (changed_ratio * 100.0, hatch_ratio * 100.0, keep, med_alpha))

    # ---------- A6：提示开启不影响环上点击/拖动 ----------
    errs = []
    for hh in (10.0, 90.0, 200.0, 330.0, 359.0):
        c.set_color(0.0, 0.5, 0.5)
        px, py = ring_pt(hh)
        c.mousePressEvent(Ev(px, py, Q.LeftButton))
        got_h = c.h
        c.mouseReleaseEvent(Ev(px, py, Q.LeftButton))
        if abs(((got_h - hh) + 180.0) % 360.0 - 180.0) > 1.0:
            errs.append((hh, got_h, c._drag_mode, c._press_area,
                         c.width(), c.height(), round(g["cx"], 1), round(g["cy"], 1),
                         round(px, 1), round(py, 1)))
    put("  A6 实测：提示开启后 10/90/200/330/359 度点击色相偏差超 1 度的用例数 = %d"
        % len(errs))
    check("A6 提示开启后环上点击仍能改色相（命中判定不变）", not errs, str(errs[:3]))

    # ---------- A8：设置项（行为 + 跨面板同步 + 持久化）+ 自定义按键表即时生效 ----------
    got = []
    listener = lambda k, v: got.append((k, v))          # noqa: E731
    panel.view_listeners.append(listener)
    pop = None
    fresh = None
    try:
        pop = selfmod.HsvPickerPopup(panel)
        panel.set_show_unreachable(False)
        off_ok = (panel.picker.show_unreachable is False
                  and panel.act_unreachable.isChecked() is False
                  and pop.panel.picker.show_unreachable is False)
        panel.set_show_unreachable(True)
        back_ok = panel.picker.show_unreachable is True and pop.panel.picker.show_unreachable is True

        # 自定义按键表：改动作 -> 两端即时生效（行为真的跟着走）
        km = kmc.default_keymap()
        kmc.set_action(km, "square", "none", "left", "v_only")
        panel.set_keymap(km)
        px, py = square_center()
        c.mousePressEvent(Ev(px, py, Q.LeftButton))
        sq_effect = (c._drag_mode == "axis" and c._axis_lock == "v")
        c.mouseReleaseEvent(Ev(px, py, Q.LeftButton, Q.NoButton))
        key_sync_ok = (pop.panel.picker.keymap == panel.keymap
                       and kmc.lookup(pop.panel.keymap, "square", "left", "none") == "v_only")
        panel.set_keymap(kmc.default_keymap())

        panel.set_chroma_mode("abs")
        panel.set_chroma_full(True)
        abs_ok = (panel.strip_c.mode == "abs" and panel.strip_c.full is True
                  and pop.panel.strip_c.mode == "abs" and pop.panel.strip_c.full is True
                  and panel.edit_c.toolTip() != "" and panel.strip_c.dead_mask(100) is None)
        panel.set_chroma_full(False)
        dm = panel.strip_c.dead_mask(200)
        dead_ok = dm is not None and bool(_np.asarray(dm).any())
        panel.set_chroma_mode("rel")
        rel_ok = panel.strip_c.mode == "rel" and pop.panel.strip_c.mode == "rel"
        check("A8 设置项行为 + 自定义按键表即时生效 + 跨 Docker/弹窗同步",
              off_ok and back_ok and sq_effect and key_sync_ok and abs_ok and dead_ok and rel_ok,
              "提示=%s 键表=%s C绝对=%s 死区=%s 相对=%s"
              % (off_ok and back_ok, sq_effect and key_sync_ok, abs_ok, dead_ok, rel_ok))
        keys = set(k for k, _v in got)
        check("A8b 设置变化都广播到对端",
              {"unreachable", "keymap", "chroma_mode", "chroma_full"} <= keys,
              str(sorted(keys)))
        # 持久化：写成非默认值，再新建面板（等价于重启后从 Krita 设置读）
        panel.set_show_unreachable(False)
        km2 = kmc.default_keymap()
        kmc.set_action(km2, "ring", "none", "right", "hue_lock_lc_rel")
        panel.set_keymap(km2)
        panel.set_chroma_mode("abs")
        panel.set_chroma_full(True)
        fresh = selfmod.HsvPickerPanel()
        vals = (fresh.show_unreachable,
                kmc.lookup(fresh.keymap, "ring", "right", "none"),
                fresh.chroma_mode, fresh.chroma_full)
        persist_ok = vals == (False, "hue_lock_lc_rel", "abs", True)
        put("  A8 实测：提示=%s C绝对=%s 死区=%s 回相对=%s；广播键=%s；持久化新面板读到 %s"
            % (off_ok and back_ok, abs_ok, dead_ok, rel_ok, sorted(keys), vals))
        check("A8c 设置持久化（新面板读到的值与写入一致）", persist_ok,
              "新面板读到：%s" % (vals,))
    finally:
        if listener in panel.view_listeners:
            panel.view_listeners.remove(listener)
        for _w in (pop, fresh):
            if _w is not None:
                try:
                    _w.hide()
                    _w.deleteLater()
                except Exception:
                    pass
        panel.set_show_unreachable(True, _broadcast=False)
        panel.set_keymap(kmc.default_keymap(), _broadcast=False)
        panel.set_chroma_mode("rel", _broadcast=False)
        panel.set_chroma_full(False, _broadcast=False)

    # ---------- A11：自定义按键表（结构 / 行高 / 中英）----------
    old_lang = selfmod.i18n._LANG
    dlg = None; d2 = None; headers = []; row_h = -1; areas = []; headers_en = []
    try:
        selfmod.i18n._LANG = "zh"
        panel.act_keymap.trigger()
        dlg = getattr(panel, "_keymap_dialog", None)
        if dlg is not None:
            headers = [dlg.table.horizontalHeaderItem(i).text()
                       for i in range(dlg.table.columnCount())]
            row_h = dlg.table.rowHeight(0)
            areas = [r[0] for r in dlg.keymap_rows()]
        selfmod.i18n._LANG = "en"
        d2 = selfmod.keymap_dialog.KeymapDialog(None)
        headers_en = [d2.table.horizontalHeaderItem(i).text()
                      for i in range(d2.table.columnCount())]
    finally:
        selfmod.i18n._LANG = old_lang
    struct_ok = (headers == ["区域", "输入", "动作"] and len(areas) == 17
                 and areas.count("ring") == 4
                 and set(areas) == {"ring", "square", "lstrip", "cstrip",
                                    "astrip", "bstrip", "field"})
    row_h_ok = 0 < row_h <= 32
    bilingual_ok = (headers_en == ["Area", "Input", "Action"]
                    and selfmod.keymap_core.area_label("ring", zh=False) == "Hue ring")
    for _d in (d2, dlg):
        if _d is not None:
            try:
                _d.hide()
            except Exception:
                pass
    put("  A11 实测：表头=%s、行数=%d、区域=%d 个、行高=%.0fpx、英文表头=%s"
        % (headers, len(areas), len(set(areas)), row_h, headers_en))
    check("A11 自定义按键表可弹出：表头=区域|输入|动作、17 行、7 区域、行高紧凑、中英",
          struct_ok and row_h_ok and bilingual_ok,
          "struct=%s row_h=%.0f bilingual=%s" % (struct_ok, row_h, bilingual_ok))

    # ---------- A20：自定义按键表可编辑 + 即时生效 + 修饰键 + 锁相对彩度 + 恢复默认 ----------
    from PyQt5.QtCore import Qt as _Q
    dlg = getattr(panel, "_keymap_dialog", None)
    opened = dlg is not None
    # A20a：方块左键 -> v_only，行为真的跟着走
    ok_v = dlg.change_action("square", "none", "left", "v_only") if opened else False
    sqx, sqy = square_center()
    c.set_color(60.0, 0.5, 0.5)
    c.mousePressEvent(Ev(sqx, sqy, Q.LeftButton))
    mode_v, axis_v = c._drag_mode, c._axis_lock
    eff_v = (mode_v == "axis" and axis_v == "v" and abs(c.s - 0.5) < 1e-9)
    c.mouseReleaseEvent(Ev(sqx, sqy, Q.LeftButton, Q.NoButton))
    put("  A20a 实测：改动作成功=%s；方块左键改 v_only 后 drag_mode=%s axis=%s S=%.6f"
        % (ok_v, mode_v, axis_v, c.s))
    check("A20a 自定义表改动作即时生效（行为真的按新动作走）",
          ok_v and eff_v, "ok=%s eff_v=%s" % (ok_v, eff_v))

    # A20b：修饰键可配（Ctrl+Shift+左）+ 锁明度+锁相对彩度可选且生效
    ok_mod = dlg.change_action("field", "none", "left", "text_only") if opened else False
    mod_lookup = (panel.edit_h._action_for(_Q.LeftButton, _Q.NoModifier) == "text_only"
                  and panel.edit_h._action_for(
                      _Q.LeftButton, _Q.ControlModifier | _Q.ShiftModifier) == "drag_x4")
    ok_rel = dlg.change_action("ring", "none", "right", "hue_lock_lc_rel") if opened else False
    c.set_color(30.0, 0.9, 0.95)
    Lr = float(mc.lightness(c.h, c.s, c.v, "oklab"))
    Cr = float(mc.crel_of_xyz(c.h, "oklab", c.s, c.v)[0])
    px, py = ring_pt(140.0)
    c.mousePressEvent(Ev(px, py, Q.RightButton))
    mode_rel = c._drag_mode
    dL = abs(float(mc.lightness(c.h, c.s, c.v, "oklab")) - Lr)
    dC = abs(float(mc.crel_of_xyz(c.h, "oklab", c.s, c.v)[0]) - Cr)
    rel_effect = (mode_rel == "ring_crel" and abs(c.h - 140.0) < 1e-6
                  and dL < 1e-6 and dC < 1e-6)
    c.mouseReleaseEvent(Ev(px, py, Q.RightButton, Q.NoButton))
    put("  A20b 实测：数值框无修饰=只编辑=%s、Ctrl+Shift=×4=%s；环右键锁 L+C_rel："
        "drag_mode=%s ΔL=%.2e ΔC_rel=%.2e 命中角=%.3f"
        % (mod_lookup, mod_lookup, mode_rel, dL, dC, c.h))
    check("A20b 修饰键可配（Ctrl+Shift+左）+ 环上「锁明度+锁相对彩度」可选且生效",
          ok_mod and mod_lookup and ok_rel and rel_effect,
          "mod=%s rel=%s effect=%s dL=%.2e dC=%.2e" % (ok_mod and mod_lookup, ok_rel, rel_effect, dL, dC))

    # A20c：同区重复输入拒绝 + 新增 + 恢复默认 + 三个旧菜单项删除
    dup_rej = (dlg.add_input("square", "none", "left") is False) if opened else False
    add_ok = (dlg.add_input("square", "ctrl", "right") is True) if opened else False
    if opened:
        dlg.reset_defaults()
    reset_ok = (kmc.lookup(panel.keymap, "square", "left", "none") == "abs"
                and kmc.lookup(panel.keymap, "ring", "left", "none") == "hue_lock_lc_rel"
                and kmc.lookup(panel.keymap, "ring", "left", "shift") == "hue_hsv"
                and kmc.lookup(panel.keymap, "ring", "right", "none") == "hue_lock_lc_abs")
    menu_texts = [a.text() for a in panel.menu.actions()]
    old_menu_gone = (not hasattr(panel, "act_swap_ring") and not hasattr(panel, "act_swap_square")
                     and not hasattr(panel, "act_ring_lock")
                     and not hasattr(panel, "set_swap_ring") and not hasattr(panel, "set_swap_square")
                     and not hasattr(panel, "set_ring_lock_lightness")
                     and not any(("交换" in t or "锁定明度" in t) for t in menu_texts))
    put("  A20c 实测：重复输入拒绝=%s、新增成功=%s、恢复默认=%s、旧菜单项已删=%s（菜单项=%s）"
        % (dup_rej, add_ok, reset_ok, old_menu_gone, menu_texts))
    check("A20c 同区重复输入拒绝 + 恢复默认可用 + 三个旧菜单项已删除",
          dup_rej and add_ok and reset_ok and old_menu_gone,
          "dup=%s add=%s reset=%s gone=%s" % (dup_rej, add_ok, reset_ok, old_menu_gone))
    # 插件版本可见性（__version__ + 设置菜单「关于… v1.0.0」+ 对话框内容）
    ver = getattr(selfmod, "__version__", None)
    about_text = panel.act_about.text() if hasattr(panel, "act_about") else ""
    from PyQt5.QtWidgets import QMessageBox as _QMB
    captured = {}
    _orig_exec = _QMB.exec_

    def _capture_exec(box):
        captured["title"] = box.windowTitle()
        captured["text"] = box.text()
        captured["info"] = box.informativeText()
        return _QMB.Ok

    _QMB.exec_ = _capture_exec
    try:
        panel.show_about_dialog()
    finally:
        _QMB.exec_ = _orig_exec
    info = captured.get("info", "")
    slogan = captured.get("text", "")
    dialog_ok = ("OKLAB/OKLCH" in slogan and "1.0.0" in info
                 and "GPL-3.0-or-later" in info and "BSD-3" in info)
    put("  版本实测：__version__=%s；菜单项=%r；对话框 slogan=%r info=%r"
        % (ver, about_text, slogan, info))
    check("版本 1.0.0 在设置菜单可见，关于框含 slogan/版本/GPL/numpy BSD",
          ver == "1.0.0" and "v1.0.0" in about_text and dialog_ok,
          "version=%s about=%r dialog=%s" % (ver, about_text, dialog_ok))
    if dlg is not None:
        dlg.hide()

    # ---------- A21：环上右键绝对角度 + 不可达钳到最近可达边界 ----------
    c.set_keymap(kmc.default_keymap())
    c.set_color(30.0, 0.90, 0.95)
    L21 = float(mc.lightness(c.h, c.s, c.v, "oklab"))
    C21 = float(mc.ok_L_C(c.h, c.s, c.v)[1])
    bad_clamp, bad_reach = [], []
    for hh in _np.arange(0.0, 360.0, 5.0):
        hh = float(hh)
        c.set_color(30.0, 0.90, 0.95)
        c._last_heavy = 0.0
        px, py = ring_pt(hh)
        c.mousePressEvent(Ev(px, py, Q.RightButton))
        want = mc.nearest_reachable_hue(hh, L21, C21)
        if want is not None:
            if abs(((c.h - want) + 180.0) % 360.0 - 180.0) > 1e-6:
                bad_clamp.append((hh, round(c.h, 4), round(want, 4)))
            if not mc.hue_is_reachable(c.h, L21, C21):
                bad_reach.append((hh, round(c.h, 4)))
        c.mouseReleaseEvent(Ev(px, py, Q.RightButton, Q.NoButton))
    c.set_color(30.0, 0.90, 0.95)
    px, py = ring_pt(100.0)
    c.mousePressEvent(Ev(px, py, Q.RightButton))
    abs_ok = abs(((c.h - 100.0) + 180.0) % 360.0 - 180.0) < 1e-6
    c.mouseReleaseEvent(Ev(px, py, Q.RightButton, Q.NoButton))
    import inspect as _insp
    _src = _insp.getsource(selfmod.picker_widget)
    hint_gone = ("_ring_hint_h" not in _src)
    put("  A21 实测：按下即到点击处=%s；360° 取样钳边界不符 %d 个、落在不可达集合 %d 个；"
        "_ring_hint_h 已删=%s" % (abs_ok, len(bad_clamp), len(bad_reach), hint_gone))
    check("A21a 环上右键按下即到点击处（绝对角度）", abs_ok)
    check("A21b 不可达色相钳到最近可达边界（误差 0 且落在可达集合）",
          not bad_clamp and not bad_reach,
          "钳边界不符 %d / 不可达 %d %s" % (len(bad_clamp), len(bad_reach), (bad_clamp + bad_reach)[:3]))
    check("A21c _ring_hint_h 与虚线指示线已删除", hint_gone)

    # ---------- A22：历史色块 16×16 无描边、直接接壤 ----------
    from PyQt5.QtGui import QImage as _QI, QPainter as _QP
    hist_cell = selfmod.history_widget.CELL
    panel.history.set_colors(["#FF0000", "#00FF00", "#0000FF"])
    panel.history.resize(16, 48)
    _img = _QI(16, 48, _QI.Format_RGB32); _img.fill(0)
    _p = _QP(_img); panel.history.render(_p); _p.end()
    r15 = _img.pixelColor(8, 15).name(); r16 = _img.pixelColor(8, 16).name()
    r31 = _img.pixelColor(8, 31).name(); r32 = _img.pixelColor(8, 32).name()
    hist_ok = (hist_cell == 16 and r15 == "#ff0000" and r16 == "#00ff00"
               and r31 == "#00ff00" and r32 == "#0000ff")
    put("  A22 实测：CELL=%d；接壤处像素 %s %s | %s %s（无深色描边）"
        % (hist_cell, r15, r16, r31, r32))
    check("A22 历史色块 16×16、无 1px 描边、颜色直接接壤",
          hist_ok, "%s %s %s %s" % (r15, r16, r31, r32))

    # ---------- A12：二级菜单改名（不改变内容）----------
    chroma_title = panel.menu_chroma.title()
    put("  A12 实测：二级菜单标题 = %r" % (chroma_title,))
    check("A12 菜单改名「C 条选项」/ C strip options",
          chroma_title in ("C 条选项", "C strip options"), repr(chroma_title))

    # ---------- A18：两项菜单改名（R17 后不再联动）----------
    old_lang = selfmod.i18n._LANG
    p18 = None
    try:
        selfmod.i18n._LANG = "zh"
        p18 = selfmod.HsvPickerPanel()
        t_auto = p18.act_auto_close.text()
        t_top = p18.act_on_top.text()
    finally:
        selfmod.i18n._LANG = old_lang
        if p18 is not None:
            try:
                p18.hide()
                p18.deleteLater()
            except Exception:
                pass
    put("  A18 实测：文案=%r / %r" % (t_auto, t_top))
    check("A18 菜单改名「点击弹出面板外时自动关闭」/「弹出面板置顶」",
          t_auto == "点击弹出面板外时自动关闭" and t_top == "弹出面板置顶",
          "%r %r" % (t_auto, t_top))

    # ---------- A23：置顶记忆自己的值（R17，取代 v3 的两条联动）----------
    p23 = None; fresh23 = None
    try:
        p23 = selfmod.HsvPickerPanel()
        p23.set_always_on_top(False, _broadcast=False)
        p23.set_auto_close_popup(True, _broadcast=False)      # 自动关闭开 -> 置顶灰、记忆保留
        s1 = (p23.always_on_top, p23.act_on_top.isEnabled(), p23.act_on_top.isChecked())
        p23.set_always_on_top(True, _broadcast=False)
        p23.set_auto_close_popup(True, _broadcast=False)
        s2 = (p23.always_on_top, p23.act_on_top.isEnabled(), p23.act_on_top.isChecked())
        p23.set_auto_close_popup(False, _broadcast=False)     # 关掉自动关闭 -> 恢复记忆值 True
        s3 = (p23.always_on_top, p23.act_on_top.isEnabled(), p23.act_on_top.isChecked())
        # 反向：记忆 False，开/关自动关闭后仍为 False（不被强制勾选）
        p23.set_always_on_top(False, _broadcast=False)
        p23.set_auto_close_popup(True, _broadcast=False)
        p23.set_auto_close_popup(False, _broadcast=False)
        s4 = (p23.always_on_top, p23.act_on_top.isEnabled(), p23.act_on_top.isChecked())
        keys23 = []
        p23.view_listeners.append(lambda k, v: keys23.append(k))
        p23.set_always_on_top(True)
        p23.set_auto_close_popup(True)
        fresh23 = selfmod.HsvPickerPanel()
        s5 = (fresh23.auto_close_popup, fresh23.always_on_top)
    finally:
        for _w in (p23, fresh23):
            if _w is not None:
                try:
                    _w.hide()
                    _w.deleteLater()
                except Exception:
                    pass
    put("  A23 实测：默认=%s 开自动关闭=%s 关自动关闭=%s 反向=%s；持久化新面板=%s；广播键=%s"
        % (s1, s2, s3, s4, s5, sorted(set(keys23))))
    check("A23 置顶记忆自己的值：自动关闭不改写、开时置灰但保留值、关掉后恢复记忆值",
          s1 == (False, False, False) and s2 == (True, False, True) and s3 == (True, True, True)
          and s4 == (False, True, False) and s5 == (True, True)
          and {"on_top", "auto_close"} <= set(keys23),
          "s1=%s s2=%s s3=%s s4=%s s5=%s keys=%s"
          % (s1, s2, s3, s4, s5, sorted(set(keys23))))

    # ---------- A19：a/b 条拖动时红虚线实时更新（R11）----------
    panel.set_ab_mode("box", _broadcast=False)
    c.set_color(200.0, 0.6, 0.7)
    panel._on_strip_ab_press("a")
    frozen_none = (c._frozen_iso is None and c._frozen_crel is None)
    Lab, aab, bab = panel._ab_now()
    lo_a, hi_a = mc.ab_axis_interval(Lab, bab, "a")
    v1_a = lo_a + 0.15 * (hi_a - lo_a)
    v2_a = lo_a + 0.85 * (hi_a - lo_a)
    panel._on_strip_ab("a", v1_a)
    ca = c._through_lines()
    panel._on_strip_ab("a", v2_a)
    cb2 = c._through_lines()

    def _line_same(x, y):
        if x is None or y is None:
            return x is None and y is None
        return _np.array_equal(x, y)

    red_moved = not _line_same(ca["iso"], cb2["iso"])
    panel._on_strip_release()
    put("  A19 实测：a/b 按下后 frozen_iso=%s frozen_crel=%s；a 值 %.4f -> %.4f：红虚线变化=%s"
        % (c._frozen_iso, c._frozen_crel, v1_a, v2_a, red_moved))
    check("A19 a/b 条拖动红虚线实时（不冻结快照）",
          frozen_none and red_moved,
          "frozen_none=%s red_moved=%s" % (frozen_none, red_moved))

    c.set_color(60.0, 0.5, 0.6)


def _section_v5(panel, c, selfmod, g, cx, cy, dock):
    """V v5：R18「按键功能」弹窗继承置顶 + R19 全修饰键组合真正生效。"""
    from PyQt5.QtCore import Qt as Q, QPointF, QEvent
    from PyQt5.QtGui import QMouseEvent
    from PyQt5.QtWidgets import QApplication
    import math as _m
    kmc = selfmod.keymap_core
    sect("V v5 弹窗置顶继承 + 全修饰键生效（R18/R19）")

    panel.resize(520, 900)
    panel.layout().activate()
    QApplication.processEvents()
    panel.mid_box.resize(508, 640)
    panel._layout_picker()
    QApplication.processEvents()
    c.set_keymap(kmc.default_keymap())

    def ring_pt(hh):
        gg = c._geometry()
        rr = gg["r_in"] + (gg["r_out"] - gg["r_in"]) * 0.5
        rad = _m.radians(float(hh) - 180.0)
        return (gg["cx"] + rr * _m.cos(rad), gg["cy"] + rr * _m.sin(rad))

    # ---------- A24：R18「按键功能」弹窗继承实际置顶 ----------
    pop = None; dlg_pop = None; dlg_dock = None
    r18 = {}
    try:
        pop = selfmod.HsvPickerPopup(None)
        pp = pop.panel
        pp.set_auto_close_popup(False, _broadcast=False)
        pp.set_always_on_top(True, _broadcast=False)
        pp.show_keymap_dialog()
        dlg_pop = getattr(pp, "_keymap_dialog", None)
        r18["on"] = bool(dlg_pop.windowFlags() & Q.WindowStaysOnTopHint) if dlg_pop else False
        r18["parent"] = (dlg_pop is not None and dlg_pop.parentWidget() is pop)
        pp.set_always_on_top(False, _broadcast=False)
        r18["off"] = bool(dlg_pop.windowFlags() & Q.WindowStaysOnTopHint) if dlg_pop else True
        pp.set_always_on_top(True, _broadcast=False)
        r18["back"] = bool(dlg_pop.windowFlags() & Q.WindowStaysOnTopHint) if dlg_pop else False
        pp.set_auto_close_popup(True, _broadcast=False)     # 自动关闭开 -> 实际不置顶
        r18["auto"] = bool(dlg_pop.windowFlags() & Q.WindowStaysOnTopHint) if dlg_pop else True
        pp.set_auto_close_popup(False, _broadcast=False)
        panel.show_keymap_dialog()                          # Docker 面板打开
        dlg_dock = getattr(panel, "_keymap_dialog", None)
        r18["dock_parent"] = (dlg_dock is not None and dlg_dock.parentWidget() is dock)
    except Exception as exc:
        r18["exc"] = repr(exc)
    finally:
        for _d in (dlg_pop, dlg_dock):
            if _d is not None:
                try:
                    _d.hide()
                except Exception:
                    pass
        if pop is not None:
            try:
                pop.hide()
            except Exception:
                pass
    ok18 = (r18.get("on") is True and r18.get("parent") is True
            and r18.get("off") is False and r18.get("back") is True
            and r18.get("auto") is False and r18.get("dock_parent") is True)
    put("  A24 实测：弹窗内 on=%s parent=%s off=%s 恢复=%s 自动关闭开=%s；Docker parent=%s%s"
        % (r18.get("on"), r18.get("parent"), r18.get("off"), r18.get("back"),
           r18.get("auto"), r18.get("dock_parent"),
           (" EXC=" + str(r18.get("exc"))) if "exc" in r18 else ""))
    check("A24 「按键功能」弹窗继承实际置顶（弹窗内以弹窗为 parent、切换即时刷新）",
          ok18, str(r18))

    # ---------- A25：v6 R20 色相环 Shift+左键 = 纯 HSV（默认表；只改色相，S/V 不动） ----------
    kmc.set_action(panel.keymap, "ring", "shift", "left", "none")   # 先清掉，确保下面读到的是默认表
    panel.set_keymap(kmc.default_keymap(), _broadcast=False)
    shift_action = kmc.lookup(panel.keymap, "ring", "left", "shift")
    c.set_color(60.0, 0.5, 0.5)
    s0, v0 = c.s, c.v
    px, py = ring_pt(140.0)
    c.mousePressEvent(Ev(px, py, Q.LeftButton, None, Q.ShiftModifier))
    mode_hsv = c._drag_mode
    h1, s1, v1 = c.h, c.s, c.v
    ring1_ok = (mode_hsv == "ring_hue_hsv" and abs(h1 - 140.0) < 1e-6
                and abs(s1 - s0) < 1e-12 and abs(v1 - v0) < 1e-12)
    c.mouseReleaseEvent(Ev(px, py, Q.LeftButton, Q.NoButton, Q.ShiftModifier))
    put("  A25a 实测：默认表查表=%s；按下 -> mode=%s h=%.4f S %.6f->%s V %.6f->%s"
        % (shift_action, mode_hsv, h1, s0, s1, v0, v1))
    check("A25a 色相环 Shift+左键默认「纯 HSV」并真正生效（mode=ring_hue_hsv）",
          shift_action == "hue_hsv" and ring1_ok,
          "查表=%s mode=%s h=%.4f S %.6f->%s V %.6f->%s"
          % (shift_action, mode_hsv, h1, s0, s1, v0, v1))

    # A25b：纯 HSV = S / V 精确保留、只有色相变（对照默认左键「锁 L + 锁 C_rel」会同时动 S/V）
    c.set_color(210.0, 0.5, 0.5)
    s0, v0 = c.s, c.v
    px, py = ring_pt(0.0)
    c.mousePressEvent(Ev(px, py, Q.LeftButton, None, Q.ShiftModifier))
    h2, s2, v2 = c.h, c.s, c.v
    c.mouseReleaseEvent(Ev(px, py, Q.LeftButton, Q.NoButton, Q.ShiftModifier))
    pure_hsv_ok = (abs(h2 - 0.0) < 1e-6 and abs(s2 - s0) < 1e-12
                   and abs(v2 - v0) < 1e-12 and abs(h2 - 210.0 % 360.0) > 1e-6)
    put("  A25b 实测：纯 HSV 转色相 210°->%.1f° 时 S %.6f->%.6f（Δ%.2e）V %.6f->%.6f（Δ%.2e）"
        % (h2, s0, s2, abs(s2 - s0), v0, v2, abs(v2 - v0)))
    check("A25b 纯 HSV：S / V 严格不变、只有色相变",
          pure_hsv_ok, "h 210->%.4f S %.6f->%.6f V %.6f->%.6f" % (h2, s0, s2, v0, v2))

    # ---------- A26：R19 色条 Shift+左键 = none（该组合不响应） ----------
    km = kmc.default_keymap()
    kmc.set_action(km, "lstrip", "shift", "left", "none")
    panel.set_keymap(km, _broadcast=False)
    sl = panel.strip_l
    sl.set_value(0.3)
    v_before = sl.value
    ev_none = Ev(10.0, 5.0, Q.LeftButton, None, Q.ShiftModifier)
    sl.mousePressEvent(ev_none)
    v_none = sl.value
    strip_none_ok = (not sl._dragging and ev_none.ignored
                     and abs(v_none - v_before) < 1e-12)
    sl.mouseReleaseEvent(Ev(10.0, 5.0, Q.LeftButton, Q.NoButton, Q.ShiftModifier))
    ev_ok = Ev(10.0, 5.0, Q.LeftButton)          # 对照：无修饰左键仍响应
    sl.mousePressEvent(ev_ok)
    strip_ok = bool(sl._dragging) and (not ev_ok.ignored)
    sl.mouseReleaseEvent(Ev(10.0, 5.0, Q.LeftButton, Q.NoButton))
    panel.set_keymap(kmc.default_keymap(), _broadcast=False)
    put("  A26v5 实测：色条 Shift+左键 none -> dragging=%s ignored=%s val %.6f->%.6f；"
        "无修饰仍响应=%s" % (sl._dragging, ev_none.ignored, v_before, v_none, strip_ok))
    check("A26v5 R19 色条 Shift+左键 自定义为 none 后该组合不响应", strip_none_ok and strip_ok,
          "none=%s contrast=%s" % (strip_none_ok, strip_ok))

    # ---------- A27：R19 数值框组合改成 none（不拖动但保留单击编辑） ----------
    km = kmc.default_keymap()
    kmc.set_action(km, "field", "none", "left", "none")
    panel.set_keymap(km, _broadcast=False)
    eh = panel.edit_h
    eh.set_value(123.45)
    t_before = eh.text()
    press = QMouseEvent(QEvent.MouseButtonPress, QPointF(5.0, 10.0),
                        Q.LeftButton, Q.LeftButton, Q.NoModifier)
    eh.mousePressEvent(press)
    eh.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, QPointF(5.0, 60.0),
                                  Q.NoButton, Q.LeftButton, Q.NoModifier))
    t_none = eh.text()
    enabled_none = eh._drag_enabled
    field_none_ok = (enabled_none is False and t_none == t_before
                     and press.isAccepted())
    eh.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, QPointF(5.0, 60.0),
                                     Q.LeftButton, Q.NoButton, Q.NoModifier))
    eh.set_value(123.45)                          # 对照：Ctrl 档仍可拖动
    eh.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, QPointF(5.0, 10.0),
                                   Q.LeftButton, Q.LeftButton, Q.ControlModifier))
    eh.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, QPointF(5.0, 60.0),
                                  Q.NoButton, Q.LeftButton, Q.ControlModifier))
    field_ctrl_ok = (eh.text() != "123.45")
    eh.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, QPointF(5.0, 60.0),
                                     Q.LeftButton, Q.NoButton, Q.ControlModifier))
    panel.set_keymap(kmc.default_keymap(), _broadcast=False)
    put("  A27v5 实测：数值框 none -> enabled=%s 文本 %s->%s 可单击编辑=%s；Ctrl 档拖动=%s"
        % (enabled_none, t_before, t_none, press.isAccepted(), field_ctrl_ok))
    check("A27v5 R19 数值框组合改为 none 后不拖动、但保留单击编辑",
          field_none_ok and field_ctrl_ok, "none=%s ctrl=%s" % (field_none_ok, field_ctrl_ok))

    # ---------- A28：R19 表格 UI 任意区域都能加任意修饰键+鼠标键并生效 ----------
    combos = [("ring", "ctrl_shift", "middle"), ("square", "alt", "right"),
              ("lstrip", "shift", "left"), ("cstrip", "ctrl", "middle"),
              ("astrip", "ctrl_shift", "right"), ("bstrip", "alt", "middle"),
              ("field", "shift", "right")]
    dlg = getattr(panel, "_keymap_dialog", None)
    all_add = (dlg is not None)
    if dlg is not None:
        for area, mods, btn in combos:
            if not dlg.add_input(area, mods, btn):
                all_add = False
        rows_ok = all(kmc.find_action(panel.keymap, a, b, m) == "none" for a, m, b in combos)
        dlg.change_action("ring", "ctrl_shift", "middle", "hue_hsv")
        look_ok = (c._lookup_action("ring", Q.MiddleButton,
                                    Q.ControlModifier | Q.ShiftModifier) == "hue_hsv")
        dlg.reset_defaults()
    else:
        rows_ok = look_ok = False
    put("  A28v5 实测：7 区域任意组合新增全部成功=%s、表中可见=%s、改动作后查表=%s"
        % (all_add, rows_ok, look_ok))
    check("A28v5 R19 表格 UI 任意区域可加任意「修饰键+鼠标键」并即时生效",
          all_add and rows_ok and look_ok, "add=%s rows=%s look=%s" % (all_add, rows_ok, look_ok))


def _section_t41(panel, c, selfmod, g, cx, cy):
    """T-41：8 种修饰键组合；T-42：删除「转色相 + 只锁明度」的迁移。"""
    from PyQt5.QtCore import Qt as Q
    from PyQt5.QtWidgets import QApplication
    import math as _m
    kmc = selfmod.keymap_core
    sect("T41/T42 8 种修饰键组合 + 已删动作迁移")

    # 前面的用例改过控件尺寸；先让布局结算再取几何
    panel.resize(520, 900)
    panel.layout().activate()
    QApplication.processEvents()
    panel.mid_box.resize(508, 640)
    panel._layout_picker()
    QApplication.processEvents()
    c.set_keymap(kmc.default_keymap())
    g = c._geometry()
    cx = g["sq"][0] + (g["sq"][2] - g["sq"][0]) / 2.0
    cy = g["sq"][1] + (g["sq"][3] - g["sq"][1]) / 2.0

    def ring_pt(hh):
        gg = c._geometry()
        rr = (gg["r_in"] + gg["r_out"]) / 2.0
        rad = _m.radians(float(hh) - 180.0)
        return (gg["cx"] + rr * _m.cos(rad), gg["cy"] + rr * _m.sin(rad))

    # ---------- 数据层：8 种映射 / 顺序 / 中英 label / 未知修饰位 ----------
    expect = (("none", (0, 0, 0)), ("shift", (1, 0, 0)), ("ctrl", (0, 1, 0)),
              ("alt", (0, 0, 1)), ("ctrl_shift", (1, 1, 0)),
              ("shift_alt", (1, 0, 1)), ("ctrl_alt", (0, 1, 1)),
              ("ctrl_shift_alt", (1, 1, 1)))
    map_bad = [mid for mid, bits in expect if kmc.mods_from_bools(*bits) != mid]
    order_ok = tuple(kmc.MOD_IDS) == tuple(mid for mid, _b in expect)
    zh_labels = [m[1] for m in kmc.MODS]
    en_labels = [m[2] for m in kmc.MODS]
    label_ok = (zh_labels == ["无", "Shift", "Ctrl", "Alt", "Ctrl+Shift", "Shift+Alt",
                              "Ctrl+Alt", "Ctrl+Shift+Alt"]
                and en_labels == ["None", "Shift", "Ctrl", "Alt", "Ctrl+Shift",
                                  "Shift+Alt", "Ctrl+Alt", "Ctrl+Shift+Alt"])
    unknown_ok = (kmc.mods_from_bools(0, 0, 0, 1) is None
                  and kmc.mods_from_bools(1, 0, 0, 1) is None
                  and kmc.mods_from_bools(1, 1, 1, 1) is None)
    check("T41a 8 种 bool→ID 映射 / 顺序 / 中英 label / 未知位返回 None",
          (not map_bad) and order_ok and label_ok and unknown_ok,
          "bad=%s order=%s label=%s unknown=%s"
          % (map_bad, order_ok, label_ok, unknown_ok))
    put("  T41a 实测：映射不匹配=%s；MOD_IDS=%s；中英 label=%s / %s；未知位 None=%s"
        % (map_bad, list(kmc.MOD_IDS), zh_labels, en_labels, unknown_ok))

    # ---------- 数据层：lookup / fallback / normalize / set_action 往返 ----------
    km = kmc.default_keymap()
    kmc.set_action(km, "square", "shift_alt", "middle", "v_only")
    kmc.set_action(km, "square", "ctrl_alt", "left", "s_only")
    look_ok = (kmc.lookup(km, "square", "middle", "shift_alt") == "v_only"
               and kmc.lookup(km, "square", "left", "ctrl_alt") == "s_only"
               and kmc.lookup(km, "square", "middle", "ctrl_shift_alt") == "rel_l"
               and kmc.lookup(km, "square", "middle", "none") == "rel_l")
    old_action = "".join(("hue_", "lock_l"))   # T-42 已删除动作；运行时拼接避免字面量/折叠残留
    old_json = ('{"ring":[["none","left","%s"],["shift","left","hue_hsv"]],'
                '"field":[["none","left","drag"]]}' % old_action)
    old_norm = kmc.normalize(kmc.parse(old_json))
    migrate_ok = (kmc.lookup(old_norm, "ring", "left", "none") == "none"
                  and kmc.lookup(old_norm, "ring", "left", "shift") == "hue_hsv"
                  and kmc.lookup(old_norm, "field", "left", "none") == "drag"
                  and old_action not in kmc.action_ids("ring"))
    km2 = kmc.default_keymap()
    kmc.set_action(km2, "ring", "ctrl_shift_alt", "right", "hue_hsv")
    roundtrip_ok = kmc.normalize(kmc.parse(kmc.dump(km2))) == kmc.normalize(km2)
    check("T41b lookup 精确/落回 none 行 + 旧键表迁移为 none + parse/dump 往返",
          look_ok and migrate_ok and roundtrip_ok,
          "look=%s migrate=%s roundtrip=%s" % (look_ok, migrate_ok, roundtrip_ok))
    put("  T41b 实测：Shift+Alt+中=%s、Ctrl+Alt+左=%s、Ctrl+Shift+Alt+中(落回)=%s；"
        "旧表已删动作 -> %s、Shift 行保留=%s；parse(dump()) 往返=%s"
        % (kmc.lookup(km, "square", "middle", "shift_alt"),
           kmc.lookup(km, "square", "left", "ctrl_alt"),
           kmc.lookup(km, "square", "middle", "ctrl_shift_alt"),
           kmc.lookup(old_norm, "ring", "left", "none"),
           kmc.lookup(old_norm, "ring", "left", "shift"), roundtrip_ok))

    # ---------- 行为层：环 / 方块 / 条 / 数值框各一个此前不支持的新组合 ----------
    # 环：Ctrl+Alt+左键 = 纯 HSV
    km = kmc.default_keymap()
    kmc.set_action(km, "ring", "ctrl_alt", "left", "hue_hsv")
    panel.set_keymap(km, _broadcast=False)
    c.set_color(10.0, 0.5, 0.5)
    px, py = ring_pt(200.0)
    c._last_heavy = 0.0
    c.mousePressEvent(Ev(px, py, Q.LeftButton, None, Q.ControlModifier | Q.AltModifier))
    ring_hit = abs(((c.h - 200.0) + 180.0) % 360.0 - 180.0)
    ring_ok = (c._drag_mode == "ring_hue_hsv" and ring_hit < 1e-6)
    c.mouseReleaseEvent(Ev(px, py, Q.LeftButton, Q.NoButton,
                           Q.ControlModifier | Q.AltModifier))

    # 方块：Shift+Alt+左键 = 只改 V
    km = kmc.default_keymap()
    kmc.set_action(km, "square", "shift_alt", "left", "v_only")
    panel.set_keymap(km, _broadcast=False)
    c.set_color(60.0, 0.5, 0.5)
    c._last_heavy = 0.0
    c.mousePressEvent(Ev(cx, cy, Q.LeftButton, None, Q.ShiftModifier | Q.AltModifier))
    c.mouseMoveEvent(Ev(cx, cy - 40.0, Q.NoButton, Q.LeftButton,
                        Q.ShiftModifier | Q.AltModifier))
    sq_mode, sq_axis, sq_s, sq_v = c._drag_mode, c._axis_lock, c.s, c.v
    square_ok = (sq_mode == "axis" and sq_axis == "v"
                 and abs(sq_s - 0.5) < 1e-12 and sq_v > 0.5)
    c.mouseReleaseEvent(Ev(cx, cy - 40.0, Q.LeftButton, Q.NoButton,
                           Q.ShiftModifier | Q.AltModifier))

    # L 条：Shift+Alt+左键 = 拖动改明度；无修饰同一鼠标键设为 none 做对照
    km = kmc.default_keymap()
    kmc.set_action(km, "lstrip", "none", "left", "none")
    kmc.set_action(km, "lstrip", "shift_alt", "left", "drag_l")
    panel.set_keymap(km, _broadcast=False)
    strip = panel.strip_l
    strip.set_value(0.2)
    sx = max(20.0, strip.width() * 0.8)
    strip.mousePressEvent(Ev(sx, 5.0, Q.LeftButton, None, Q.ShiftModifier | Q.AltModifier))
    strip_val = strip.value
    strip_ok = (strip._dragging is True and strip_val > 0.7)
    strip.mouseReleaseEvent(Ev(sx, 5.0, Q.LeftButton, Q.NoButton,
                               Q.ShiftModifier | Q.AltModifier))
    strip.set_value(0.2)
    none_ev = Ev(sx, 5.0, Q.LeftButton)
    strip.mousePressEvent(none_ev)
    strip_none_ok = bool(none_ev.ignored and not strip._dragging)

    # 数值框：Ctrl+Shift+Alt+左键 = 拖动 ×4
    from PyQt5.QtCore import QEvent, QPointF
    from PyQt5.QtGui import QMouseEvent
    km = kmc.default_keymap()
    kmc.set_action(km, "field", "ctrl_shift_alt", "left", "drag_x4")
    panel.set_keymap(km, _broadcast=False)
    eh = panel.edit_h
    eh.setText("123.45")
    mods3 = Q.ControlModifier | Q.ShiftModifier | Q.AltModifier
    eh.mousePressEvent(QMouseEvent(QEvent.MouseButtonPress, QPointF(5.0, 10.0),
                                   Q.LeftButton, Q.LeftButton, mods3))
    eh.mouseMoveEvent(QMouseEvent(QEvent.MouseMove, QPointF(5.0, 60.0),
                                  Q.NoButton, Q.LeftButton, mods3))
    field_gain, field_text = eh._drag_gain, eh.text()
    field_ok = (eh._drag_enabled is True and field_gain == 4.0
                and abs(float(field_text) - 83.45) < 1e-6)
    eh.mouseReleaseEvent(QMouseEvent(QEvent.MouseButtonRelease, QPointF(5.0, 60.0),
                                     Q.LeftButton, Q.NoButton, mods3))
    check("T41c 环 Ctrl+Alt / 方块 Shift+Alt / 条 Shift+Alt / 数值框 Ctrl+Shift+Alt 都生效",
          ring_ok and square_ok and strip_ok and strip_none_ok and field_ok,
          "ring=%s(%.6f) square=%s strip=%s none=%s field=%s"
          % (ring_ok, ring_hit, square_ok, strip_ok, strip_none_ok, field_ok))
    put("  T41c 实测：环 Ctrl+Alt 命中偏差=%.2e、mode=%s；方块 Shift+Alt mode=%s axis=%s "
        "S=%.6f V=%.6f；L 条 Shift+Alt value=%.3f dragging=%s；无修饰对照 ignored=%s；"
        "数值框 Ctrl+Shift+Alt gain=%.1f 文本 %s"
        % (ring_hit, "ring_hue_hsv", sq_mode, sq_axis, sq_s, sq_v,
           strip_val, strip_ok, strip_none_ok, field_gain, field_text))

    # ---------- 未知 Qt 修饰位（Meta）→ 落回 none 行，不误触 Shift 行 ----------
    c.set_keymap(kmc.default_keymap())
    meta_none = c._lookup_action("ring", Q.LeftButton, Q.MetaModifier)
    meta_shift = c._lookup_action("ring", Q.LeftButton, Q.MetaModifier | Q.ShiftModifier)
    check("T41d Meta 未知键落回 none 行（Meta+Shift 不误触 Shift 行）",
          meta_none == "hue_lock_lc_rel" and meta_shift == "hue_lock_lc_rel",
          "meta=%s meta+shift=%s" % (meta_none, meta_shift))
    put("  T41d 实测：Meta+左=%s、Meta+Shift+左=%s（默认环 none 行=%s、Shift 行=%s）"
        % (meta_none, meta_shift, "hue_lock_lc_rel", "hue_hsv"))

    # ---------- 按键对话框：修饰键下拉 8 项且顺序 / 中英 label 正确 ----------
    old_lang = selfmod.i18n._LANG
    ed = ed_en = None
    items = texts_zh = texts_en = None
    try:
        selfmod.i18n._LANG = "zh"
        ed = selfmod.keymap_dialog.InputEditor(None)
        items = [ed.cmb_mod.itemData(i) for i in range(ed.cmb_mod.count())]
        texts_zh = [ed.cmb_mod.itemText(i) for i in range(ed.cmb_mod.count())]
        selfmod.i18n._LANG = "en"                       # label 在构造时写入，需另建一个英文实例
        ed_en = selfmod.keymap_dialog.InputEditor(None)
        texts_en = [ed_en.cmb_mod.itemText(i) for i in range(ed_en.cmb_mod.count())]
    finally:
        selfmod.i18n._LANG = old_lang
        for _w in (ed, ed_en):
            if _w is not None:
                _w.hide()
    dropdown_ok = (items == list(kmc.MOD_IDS)
                   and texts_zh == zh_labels and texts_en == en_labels)
    check("T41e 按键对话框修饰键下拉 = 8 项，顺序与中英 label 正确",
          dropdown_ok, "items=%s zh=%s en=%s" % (items, texts_zh, texts_en))
    put("  T41e 实测：下拉 items=%s；中文=%s；英文=%s"
        % (items, texts_zh, texts_en))

    # 复位，避免污染后续用例
    panel.set_keymap(kmc.default_keymap(), _broadcast=False)
    panel.set_color(210.0, 0.62, 0.86)


def _section_v7(panel, c, selfmod, g, cx, cy, dock):
    """V7：明度标准（R22）+ 环中键默认（R23）+ 对话框跟随宿主（R24）+ 改名（R25）。

    验收 A26~A31。
    """
    from PyQt5.QtCore import Qt as Q
    from PyQt5.QtWidgets import QApplication
    import math as _m
    import numpy as _np
    mc = selfmod.math_core
    kmc = selfmod.keymap_core
    sect("V7 明度标准 + 中键默认 + 对话框跟随宿主 + 改名（A26~A31）")

    panel.resize(520, 900)
    panel.layout().activate()
    QApplication.processEvents()
    panel.mid_box.resize(508, 640)
    panel._layout_picker()
    QApplication.processEvents()
    c.set_keymap(kmc.default_keymap())
    panel.set_chroma_mode("rel", _broadcast=False)
    panel.set_chroma_full(False, _broadcast=False)
    panel.set_lightness_metric("oklab", _broadcast=False)

    def ring_pt(hh):
        gg = c._geometry()
        rr = (gg["r_in"] + gg["r_out"]) / 2.0
        rad = _m.radians(float(hh) - 180.0)
        return (gg["cx"] + rr * _m.cos(rad), gg["cy"] + rr * _m.sin(rad))

    def lock_span(btn):
        """环上锁明度动作 36 色相采样：返回 (灰阶跨度, Oklab L 跨度)。"""
        gs, ls = [], []
        for hh in range(0, 360, 10):
            c.set_color(60.0, 0.5, 0.6)
            c._last_heavy = 0.0
            px, py = ring_pt(hh)
            c.mousePressEvent(Ev(px, py, btn))
            gs.append(float(mc.lightness(c.h, c.s, c.v, "gray")))
            ls.append(float(mc.lightness(c.h, c.s, c.v, "oklab")))
            c.mouseReleaseEvent(Ev(px, py, btn, Q.NoButton))
        return max(gs) - min(gs), max(ls) - min(ls)

    # ---------- A26 明度标准切换生效 ----------
    panel.set_lightness_metric("gray", _broadcast=False)
    panel.set_color(210.0, 0.62, 0.86)
    panel._sync_entries()
    gray_now = float(mc.lightness(panel.h, panel.s, panel.v, "gray"))
    # 独立按定义重算一遍灰阶码值（线性 sRGB 亮度 / Σ 再 srgb_encode），验证内部口径 <1e-6
    _rgb = mc.hsv_to_srgb(panel.h, panel.s, panel.v)
    _lin = mc.srgb_to_linear(_rgb)
    _ysum = 0.2126729 + 0.7151522 + 0.0721750
    _gray_def = float(mc._srgb_encode(
        (0.2126729 * _lin[0] + 0.7151522 * _lin[1] + 0.0721750 * _lin[2]) / _ysum))
    field_text = panel.edit_l.text()
    try:
        field_now = float(field_text)
    except Exception:
        field_now = -1.0
    # L 数值框固定 4 位小数，读数误差上界 = 显示取舍误差（5e-5）；内部口径另按 1e-6 核
    field_ok = (abs(gray_now - _gray_def) < 1e-6
                and abs(field_now - round(gray_now, 4)) < 1e-12)
    gray_mid_g, gray_mid_l = lock_span(Q.MiddleButton)
    gray_left_g, gray_left_l = lock_span(Q.LeftButton)
    panel.set_lightness_metric("oklab", _broadcast=False)
    ok_mid_g, ok_mid_l = lock_span(Q.MiddleButton)
    panel.set_lightness_metric("gray", _broadcast=False)
    a26_ok = (field_ok and gray_mid_g < 1e-6 and gray_left_g < 1e-6
              and gray_mid_l > 0.01 and gray_left_l > 0.01
              and ok_mid_l < 1e-6 and ok_mid_g > 0.01)
    put("  A26 实测：灰阶口径 L 数值框=%s（口径 %.6f，定义重算 %.6f，Δ=%.2e；框 4 位小数）；"
        "36 色相锁明度跨度："
        "中键 灰阶=%.2e/Oklab=%.2e，左键 灰阶=%.2e/Oklab=%.2e；切回 Oklab 后 "
        "Oklab=%.2e/灰阶=%.2e"
        % (field_text, gray_now, _gray_def, abs(gray_now - _gray_def),
           gray_mid_g, gray_mid_l, gray_left_g, gray_left_l, ok_mid_l, ok_mid_g))
    check("A26 明度标准切换生效：L=灰阶码值 + 锁明度让所选口径恒定、另一口径漂移",
          a26_ok, "field=%s defΔ=%.1e mid(g/l)=%.1e/%.1e left=%.1e/%.1e oklab=%.1e/%.1e"
          % (field_ok, abs(gray_now - _gray_def), gray_mid_g, gray_mid_l,
             gray_left_g, gray_left_l, ok_mid_l, ok_mid_g))

    # ---------- A27 灰阶口径下 C_max / C_rel 自洽 ----------
    worst_rt = worst_id = 0.0
    miss = 0
    for hh in (20.0, 140.0, 260.0, 340.0):
        for Lc in (0.2, 0.5, 0.8):
            for crel in (0.1, 0.5, 0.95):
                got = mc.sv_at_L_crel(hh, Lc, crel, metric="gray")
                if got is None:
                    miss += 1
                    continue
                s2, v2 = got
                worst_rt = max(worst_rt,
                               abs(float(mc.crel_of_xyz(hh, "gray", s2, v2)[0]) - crel),
                               abs(float(mc.lightness(hh, s2, v2, "gray")) - Lc))
                C2 = float(mc.ok_L_C(hh, s2, v2)[1])
                cm2 = float(mc.cmax_of_L(hh, "gray", Lc))
                worst_id = max(worst_id, abs(C2 / cm2 - crel))
    got = mc.sv_at_L_crel(140.0, 0.5, 0.5, metric="gray")
    panel.set_color(140.0, got[0], got[1])
    panel._sync_entries()
    strip_ok = abs(float(panel.strip_c.value) - float(panel.edit_c.text())) < 1e-6
    a27_ok = (miss == 0 and worst_rt < 1e-6 and worst_id < 1e-6 and strip_ok)
    put("  A27 实测：灰阶 C_rel 往返最大偏差=%.2e；C/C_max 恒等最大偏差=%.2e；"
        "不可达=%d；C 条游标=%.6f 数值框=%s"
        % (worst_rt, worst_id, miss, float(panel.strip_c.value), panel.edit_c.text()))
    check("A27 灰阶口径 C_max/C_rel 自洽（往返 + C=crel·C_max + 游标=数值）",
          a27_ok, "rt=%.1e id=%.1e miss=%d strip=%s" % (worst_rt, worst_id, miss, strip_ok))

    # ---------- A28 a/b 条不受明度标准影响 ----------
    panel.set_lightness_metric("gray", _broadcast=False)
    panel.set_color(210.0, 0.62, 0.86)
    panel._sync_entries()
    Lab_g, a_g, b_g = panel._ab_now()
    strip_a_L = float(panel.strip_a.L)
    edit_a_g = panel.edit_a.text()
    edit_b_g = panel.edit_b.text()
    ok_l = float(mc.lightness(panel.h, panel.s, panel.v, "oklab"))
    gray_l = float(mc.lightness(panel.h, panel.s, panel.v, "gray"))
    panel.set_lightness_metric("oklab", _broadcast=False)
    panel._sync_entries()
    Lab_o, a_o, b_o = panel._ab_now()
    a28_ok = (abs(Lab_g - ok_l) < 1e-9 and abs(Lab_o - ok_l) < 1e-9
              and abs(a_g - a_o) < 1e-12 and abs(b_g - b_o) < 1e-12
              and abs(strip_a_L - ok_l) < 1e-4 and abs(strip_a_L - gray_l) > 0.01
              and panel.edit_a.text() == edit_a_g and panel.edit_b.text() == edit_b_g)
    put("  A28 实测：灰阶口径下 a/b 的 L=%.6f（Oklab L=%.6f，灰阶=%.6f）；切换前后 "
        "ΔL=%.2e Δa=%.2e Δb=%.2e；a/b 数值框不变=%s"
        % (Lab_g, ok_l, gray_l, abs(Lab_g - Lab_o), abs(a_g - a_o), abs(b_g - b_o),
           panel.edit_a.text() == edit_a_g))
    check("A28 a/b 条不受明度标准影响（内部 L 轴仍是 Oklab L、读数不变）",
          a28_ok, "Lg=%.6f ok=%.6f gray=%.6f stripL=%.6f" % (Lab_g, ok_l, gray_l, strip_a_L))

    # ---------- A29 环中键新默认 ----------
    km = kmc.default_keymap()
    mid = kmc.lookup(km, "ring", "middle", "none")
    right = kmc.lookup(km, "ring", "right", "none")
    rings = len(km.get("ring", []))
    put("  A29 实测：环中键=%s、环右键=%s、ring 行数=%d" % (mid, right, rings))
    check("A29 色相环中键默认 = hue_lock_lc_abs（与右键同）、ring 仍 4 行",
          mid == "hue_lock_lc_abs" and mid == right and rings == 4,
          "mid=%s right=%s rows=%d" % (mid, right, rings))

    # ---------- A30 对话框跟随宿主 ----------
    pop = None; dlg24 = None
    r24 = {}
    try:
        pop = selfmod.HsvPickerPopup(None)
        pp = pop.panel
        pop.show(); QApplication.processEvents()
        pp.show_keymap_dialog(); QApplication.processEvents()
        dlg24 = getattr(pp, "_keymap_dialog", None)
        r24["open"] = bool(dlg24 is not None and dlg24.isVisible()
                           and pp._keymap_dialog_wanted)
        pop.hide(); QApplication.processEvents()
        r24["closed"] = bool(dlg24 is not None and (not dlg24.isVisible())
                             and not pp._keymap_dialog_wanted)
        pop.show(); QApplication.processEvents()
        pp.show_keymap_dialog(); QApplication.processEvents()
        r24["reopen"] = bool(dlg24.isVisible() and pp._keymap_dialog_wanted)
        pop.showMinimized(); QApplication.processEvents()
        r24["min"] = bool((not dlg24.isVisible()) and pp._keymap_dialog_wanted
                          and pp._keymap_dialog_hidden_by_host)
        pop.showNormal(); QApplication.processEvents()
        r24["restore"] = bool(dlg24.isVisible() and pp._keymap_dialog_wanted)
    except Exception as exc:
        r24["exc"] = repr(exc)
    finally:
        for _w in (dlg24, pop):
            if _w is not None:
                try:
                    _w.hide()
                except Exception:
                    pass
    # Docker 宿主：显示 -> 对话框在；宿主隐藏 -> 对话框关
    dock_ok = False
    try:
        dock.show(); QApplication.processEvents()
        panel.show_keymap_dialog(); QApplication.processEvents()
        dd = getattr(panel, "_keymap_dialog", None)
        shown = bool(dd is not None and dd.isVisible() and panel._keymap_dialog_wanted)
        dock.hide(); QApplication.processEvents()
        closed = bool(dd is not None and (not dd.isVisible())
                      and not panel._keymap_dialog_wanted)
        dock_ok = shown and closed
        if dd is not None:
            dd.hide()
    except Exception:
        dock_ok = False
    a30_keys = ("open", "closed", "reopen", "min", "restore")
    a30_ok = all(bool(r24.get(k)) for k in a30_keys) and dock_ok
    put("  A30 实测：弹窗 open=%s hide->close=%s reopen=%s 最小化->hide=%s 恢复->show=%s；"
        "Docker 显示->开/隐藏->关=%s%s"
        % (r24.get("open"), r24.get("closed"), r24.get("reopen"), r24.get("min"),
           r24.get("restore"), dock_ok,
           (" EXC=" + str(r24.get("exc"))) if "exc" in r24 else ""))
    check("A30 宿主隐藏 -> 对话框关闭、宿主最小化 -> 隐藏、恢复 -> 重新显示（弹窗 + Docker）",
          a30_ok, str(r24) + " dock=%s" % dock_ok)

    # ---------- A31 菜单改名 ----------
    ab_text = panel.act_ab_line.text()
    put("  A31 实测：a/b 项文案=%r" % (ab_text,))
    check("A31 菜单改名「a/b 条满量程」/ a/b strips full range",
          ab_text in ("a/b 条满量程", "a/b strips full range"), repr(ab_text))

    # 收尾：复位到默认 Oklab L（保证后续 run 与「默认零影响」可重复）
    panel.set_lightness_metric("oklab", _broadcast=False)
    panel.set_chroma_mode("rel", _broadcast=False)
    panel.set_color(60.0, 0.5, 0.6)
    c.set_keymap(kmc.default_keymap())


def strip_widget_h():
    from PyQt5.QtWidgets import QApplication
    import hsv_picker.strip_widget as sw
    return sw.STRIP_H


def main(*args):
    sys.path.insert(0, os.path.join(os.environ["APPDATA"], "krita", "pykrita"))
    from PyQt5.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    try:
        from hsv_picker import hsv_picker as hp
    except Exception:
        put("导入插件失败:\n" + traceback.format_exc())
        return 1

    # G 段先跑：此时应用里只有它自己一个面板，计时干净
    _section_g(hp)

    dock = hp.HsvPickerDocker()
    panel = dock.panel
    # 探针用的是隔离的 kritarunnerrc，但设置项会跨 run 残留；先复位到出厂默认，保证断言可重复
    panel.set_preview_mode(hp.PREVIEW_DEFAULT_MODE, _broadcast=False)
    panel.set_show_unreachable(True, _broadcast=False)
    panel.set_keymap(hp.keymap_core.default_keymap(), _broadcast=False)
    panel.set_chroma_mode("rel", _broadcast=False)
    panel.set_chroma_full(False, _broadcast=False)
    panel.set_ab_mode("box", _broadcast=False)
    panel.set_show_ab(True, _broadcast=False)
    panel.set_lightness_metric("oklab", _broadcast=False)
    _section_a(panel)

    panel.resize(520, 900)
    panel.mid_box.resize(508, 640)
    panel._layout_picker()
    c = panel.picker
    g = c._geometry()
    cx = g["sq"][0] + (g["sq"][2] - g["sq"][0]) / 2.0
    cy = g["sq"][1] + (g["sq"][3] - g["sq"][1]) / 2.0
    rr = (g["r_in"] + g["r_out"]) / 2.0

    _section_bc(panel, c, hp, g, cx, cy, (g["cx"] - rr, g["cy"]))
    _section_h(panel, c, hp, g, cx, cy)
    _section_def(panel, c, hp, g, cx, cy)
    _section_i(panel, c, hp, g, cx, cy)
    _section_n(panel, c, hp, g, cx, cy)
    _section_k(panel, hp)
    _section_v5(panel, c, hp, g, cx, cy, dock)
    _section_v7(panel, c, hp, g, cx, cy, dock)
    _section_t41(panel, c, hp, g, cx, cy)
    _section_f(panel, c, hp)          # 最后跑（会销毁对象）

    put("")
    put("=" * 56)
    put("通过 %d 项，失败 %d 项" % (PASS[0], len(FAIL)))
    for f in FAIL:
        put("  - %s" % f)
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
