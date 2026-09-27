# -*- coding: utf-8 -*-
"""拖动性能探针（kritarunner，跑已安装的插件）。

量：Shift/Alt+左键轴拖动、数值框拖动、_sync_entries、过点线重建的单帧成本。
用法：kritarunner.com -s perfprobe -f main
"""

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


LOG = os.path.join(_momo_repo_root(), "tmp", "perf_probe.log")
_OUT = None


def put(msg=""):
    global _OUT
    if _OUT is None:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        _OUT = open(LOG, "w", encoding="utf-8", newline="\n")
    _OUT.write(str(msg) + "\n")
    _OUT.flush()


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


def _prep(panel, w=560, h=900):
    panel.resize(w, h)
    panel.mid_box.resize(max(80, w - 12), max(120, h - 260))
    panel._layout_picker()
    from PyQt5.QtGui import QPixmap
    return QPixmap(panel.size())


def _frame(panel, pm):
    from PyQt5.QtGui import QPainter
    pr = QPainter(pm)
    panel.render(pr)
    pr.end()


def _axis_frames(panel, pm, mods, n=24):
    from PyQt5.QtCore import Qt
    c = panel.picker
    g = c._geometry()
    cx = g["sq"][0] + (g["sq"][2] - g["sq"][0]) / 2.0
    cy = g["sq"][1] + (g["sq"][3] - g["sq"][1]) / 2.0
    c.set_color(60.0, 0.5, 0.5)
    c.mousePressEvent(Ev(cx, cy, Qt.LeftButton, Qt.LeftButton, mods))
    stats = []
    for i in range(n):
        x = cx + (i % 8) * 4.0
        y = cy + (i % 5) * 3.0
        t0 = time.perf_counter()
        c.mouseMoveEvent(Ev(x, y, Qt.NoButton, Qt.LeftButton, mods))
        _frame(panel, pm)
        stats.append((time.perf_counter() - t0) * 1000.0)
    c.mouseReleaseEvent(Ev(cx, cy, Qt.LeftButton, Qt.NoButton, mods))
    return stats


def _entry_frames(panel, pm, n=24):
    stats = []
    for i in range(n):
        t0 = time.perf_counter()
        panel._on_drag_value("h", 60.0 + i)
        _frame(panel, pm)
        stats.append((time.perf_counter() - t0) * 1000.0)
    panel._entry_dragging = False
    return stats


def _report(name, stats):
    avg = sum(stats) / len(stats)
    worst = max(stats)
    put("  %-34s 均值 %6.2f ms / 最差 %6.2f ms" % (name, avg, worst))
    return avg


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

    put("== 拖动性能探针（无真实 View：不含 Krita 写色/信号成本）==")

    # 1) 独立面板（无对端）
    solo = hp.HsvPickerPanel()
    pm = _prep(solo)
    _axis_frames(solo, pm, Qt.ShiftModifier, n=6)          # 预热
    _report("独立面板 Shift+左键轴拖动", _axis_frames(solo, pm, Qt.ShiftModifier))
    _report("独立面板 Alt+左键轴拖动", _axis_frames(solo, pm, Qt.AltModifier))
    _report("独立面板 H 数值框拖动", _entry_frames(solo, pm))

    # 2) 主面板 + 弹窗（对端打开）
    dock = hp.HsvPickerDocker()
    pop = hp.HsvPickerPopup(dock.panel)
    pm2 = _prep(pop.panel)
    _axis_frames(pop.panel, pm2, Qt.ShiftModifier, n=6)     # 预热
    _report("弹窗拖动（主面板开）Shift+左键", _axis_frames(pop.panel, pm2, Qt.ShiftModifier))
    _report("弹窗 H 数值框拖动（主面板开）", _entry_frames(pop.panel, pm2))

    # 3) 单点成本
    p = pop.panel
    N = 30
    t0 = time.perf_counter()
    for i in range(N):
        p.set_color(60.0, 0.4 + 0.001 * i, 0.5)
        p._sync_entries()
    put("  %-34s 均值 %6.2f ms" % ("_sync_entries（颜色变化）",
                                   (time.perf_counter() - t0) * 1000.0 / N))
    c = p.picker
    t0 = time.perf_counter()
    for i in range(10):
        c._through_cache = None
        c._through_key = None
        c._through_lines()
    put("  %-34s 均值 %6.2f ms" % ("_through_lines 强制重建",
                                   (time.perf_counter() - t0) * 1000.0 / 10))

    put("完成")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except SystemExit:
        raise
    except Exception:
        put("顶层异常:\n" + traceback.format_exc())
        sys.exit(1)
