# -*- coding: utf-8 -*-
"""T-1 补充验证：setForeGroundColor 是否 / 何时触发 foregroundColorChanged。

背景：主探针测得"立即 0 次、150ms 后仍 0 次"，需要区分三种可能：
  ① 信号是异步排队，150ms 不够；
  ② 信号根本没被程序化 setForeGroundColor 触发；
  ③ 信号只在 Krita 自身 UI 改色时触发。
本脚本用 100ms x 8 次的定时采样测出触发时刻，并覆盖定时器是否被弹出对话框阻塞。
"""
import os
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


LOG_PATH = os.path.join(_momo_repo_root(), "tmp", "t1", "signal_probe.txt")
COUNTS = [0]
MARKS = []


def put(msg=""):
    text = str(msg)
    try:
        print(text)
    except Exception:
        pass
    with open(LOG_PATH, "a", encoding="utf-8", newline="\n") as fh:
        fh.write(text + "\n")


def run_signal_probe():
    try:
        os.remove(LOG_PATH)
    except OSError:
        pass
    put("=== T-1 补充：信号触发时机 ===")
    from PyQt5.QtCore import QTimer
    from PyQt5.QtGui import QColor
    from krita import Krita, ManagedColor

    win = Krita.instance().activeWindow()
    view = win.activeView() if win is not None else None
    if view is None:
        put("!! 没有活动视图，请在 Krita 打开文档后重跑")
        return
    canvas = view.canvas()
    old_qc = view.foregroundColor().colorForCanvas(canvas)
    put("测试前 fg = %s" % old_qc.name().upper())
    old_mc = ManagedColor.fromQColor(QColor(old_qc.red(), old_qc.green(), old_qc.blue()), canvas)

    def on_fg():
        COUNTS[0] += 1
        MARKS.append("emit#%d" % COUNTS[0])

    def on_timer(tick):
        if tick == 0:
            put("  timer tick 0（定时器未被弹窗阻塞）")
        put("  [%d00ms] 信号计数=%d %s" % (tick, COUNTS[0], " ".join(MARKS)))

    def restore():
        put("恢复原前景色 %s" % old_qc.name().upper())
        if old_mc is not None:
            view.setForeGroundColor(old_mc)
        put("恢复后 fg = %s" % view.foregroundColor().colorForCanvas(canvas).name().upper())
        put("=== 结束 ===")

    view.foregroundColorChanged.connect(on_fg)
    put("信号已连接，准备写入 #3366CC")
    view.setForeGroundColor(ManagedColor.fromQColor(QColor(51, 102, 204), canvas))
    put("写入完成（同步）计数=%d" % COUNTS[0])
    for tick in range(1, 8):
        QTimer.singleShot(tick * 100, lambda t=tick: on_timer(t))
    QTimer.singleShot(900, restore)


run_signal_probe()
