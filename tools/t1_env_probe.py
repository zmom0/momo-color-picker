# -*- coding: utf-8 -*-
"""T-1 环境验证脚本（Krita 5.3.3 Scripter 版）。

用法：Krita -> 工具 -> 脚本 -> Scripter，整段粘贴本文件内容后点运行（播放键）。
输出同时写入 tmp/t1/scripter_result.txt，并在 Scripter 输出框逐行打印。

验证目标（资料包 §8-1）：
  1) foregroundColorChanged / backgroundColorChanged 信号是否真实存在、何时触发；
  2) ManagedColor.colorForCanvas / ManagedColor.fromQColor 在真实 canvas 上的行为；
  3) components() 与 componentsOrdered() 的真实通道顺序；
  4) Krita 内嵌 Python 的版本与 numpy 是否缺失。
"""
import sys
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


LOG_PATH = os.path.join(_momo_repo_root(), "tmp", "t1", "scripter_result.txt")

LOG_LINES = []


def put(msg=""):
    text = str(msg)
    LOG_LINES.append(text)
    try:
        print(text)
    except Exception:
        pass


def flush_log():
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(LOG_LINES) + "\n")
    except Exception:
        put("!! 写入日志失败: %r" % (traceback.format_exc(),))


def qname(qc):
    return "%s r=%d g=%d b=%d a=%d" % (qc.name().upper(), qc.red(), qc.green(),
                                       qc.blue(), qc.alpha())


def arrays(mc):
    try:
        comp = [round(float(x), 6) for x in mc.components()]
    except Exception as exc:
        comp = "FAIL(%r)" % (exc,)
    try:
        ordered = [round(float(x), 6) for x in mc.componentsOrdered()]
    except Exception as exc:
        ordered = "FAIL(%r)" % (exc,)
    return "components=%r componentsOrdered=%r" % (comp, ordered)


def step_env():
    put("=== [1] 解释器 / 绑定版本 ===")
    put("python      = %s" % sys.version.replace("\n", " "))
    put("executable  = %s" % sys.executable)
    put("sys.path[0:6] = %r" % (sys.path[:6],))
    try:
        from PyQt5.QtCore import QT_VERSION_STR, PYQT_VERSION_STR
        put("Qt          = %s" % QT_VERSION_STR)
        put("PyQt5       = %s" % PYQT_VERSION_STR)
    except Exception:
        put("PyQt5 探测失败: %r" % (traceback.format_exc(),))
    try:
        import numpy
        put("numpy       = OK %s" % numpy.__version__)
    except Exception as exc:
        put("numpy       = FAIL %s: %s" % (type(exc).__name__, exc))
    from krita import Krita
    inst = Krita.instance()
    put("Krita.version() = %s" % inst.version())
    put("windows()       = %r" % (inst.windows(),))
    put("activeWindow()  = %r" % (inst.activeWindow(),))
    put("colorModels()   = %r" % (inst.colorModels(),))
    put("colorDepths(RGBA) = %r" % (inst.colorDepths("RGBA"),))


def get_view():
    from krita import Krita
    win = Krita.instance().activeWindow()
    if win is None:
        return None
    return win.activeView()


def step_document():
    put("")
    put("=== [2] 活动文档 / 视图 ===")
    from krita import Krita
    inst = Krita.instance()
    view = get_view()
    if view is None:
        win = inst.activeWindow()
        if win is None:
            put("!! 没有活动窗口：请先在 Krita 里打开或新建一个文档，再重跑本脚本")
            return None
        try:
            doc = inst.createDocument(320, 200, "T1ProbeDoc", "RGBA", "U8",
                                      "sRGB-elle-V2-srgbtrc.icc", 72.0)
            view = win.addView(doc) if doc is not None else None
            put("已临时新建文档 320x200 RGBA/U8 -> view=%r" % (view,))
        except Exception:
            put("!! 新建文档失败:\n%s" % traceback.format_exc())
            return None
    put("view        = %r" % (view,))
    put("view.canvas() = %r" % (view.canvas(),))
    doc = view.document()
    if doc is not None:
        put("document    = %s  %dx%d  model=%s depth=%s profile=%s" % (
            doc.name(), doc.width(), doc.height(), doc.colorModel(),
            doc.colorDepth(), doc.colorProfile()))
    return view


def step_fgbg(view):
    put("")
    put("=== [3] 前景色 / 背景色读取 ===")
    fg = view.foregroundColor()
    bg = view.backgroundColor()
    put("fg          = %r" % (fg,))
    if fg is not None:
        put("fg 空间     = model=%s depth=%s profile=%s" % (
            fg.colorModel(), fg.colorDepth(), fg.colorProfile()))
        put("fg %s" % arrays(fg))
        put("fg.colorForCanvas(view.canvas()) = %s" % qname(fg.colorForCanvas(view.canvas())))
    put("bg          = %r" % (bg,))
    if bg is not None:
        put("bg 空间     = model=%s depth=%s profile=%s" % (
            bg.colorModel(), bg.colorDepth(), bg.colorProfile()))
        put("bg %s" % arrays(bg))
        put("bg.colorForCanvas(view.canvas()) = %s" % qname(bg.colorForCanvas(view.canvas())))


def step_roundtrip(view):
    put("")
    put("=== [4] QColor <-> ManagedColor 往返（sRGB #3366CC）===")
    from PyQt5.QtGui import QColor
    from krita import ManagedColor
    canvas = view.canvas()
    mc = ManagedColor.fromQColor(QColor(51, 102, 204), canvas)
    put("fromQColor(#3366CC, canvas) = %r" % (mc,))
    if mc is None:
        put("!! fromQColor 返回 None")
        return
    put("  %s" % arrays(mc))
    qc = mc.colorForCanvas(canvas)
    put("  -> colorForCanvas = %s" % qname(qc))
    ok = (qc.red(), qc.green(), qc.blue()) == (51, 102, 204)
    put("  往返一致 = %s" % ("OK" if ok else "DIFF"))
    put("")
    put("--- components() 输入顺序测试：setComponents([0.8, 0.4, 0.2, 1.0]) ---")
    probe = ManagedColor("RGBA", "U8", "sRGB-elle-V2-srgbtrc.icc")
    probe.setComponents([0.8, 0.4, 0.2, 1.0])
    put("  %s" % arrays(probe))
    put("  -> colorForCanvas = %s" % qname(probe.colorForCanvas(canvas)))
    put("  判读：若 colorForCanvas 为 #CC6633 则 components() 是 RGB 序；#3366CC 则是 BGR 序")

    put("")
    put("--- 写入前景色再读回（真实 canvas 色彩管理）---")
    try:
        view.setForeGroundColor(mc)
        back = view.foregroundColor()
        put("setForeGroundColor(#3366CC) 后 fg = %r" % (back,))
        put("  读回 %s" % arrays(back))
        put("  读回 QColor = %s" % qname(back.colorForCanvas(canvas)))
    except Exception:
        put("!! 写前景色失败:\n%s" % traceback.format_exc())


COUNT = {"fg": 0, "bg": 0}


def step_signals(view):
    put("")
    put("=== [5] 颜色变化信号 ===")
    from krita import Krita
    from PyQt5.QtCore import QTimer
    fg_attr = hasattr(type(view), "foregroundColorChanged")
    bg_attr = hasattr(type(view), "backgroundColorChanged")
    put("View 类有 foregroundColorChanged = %s" % fg_attr)
    put("View 类有 backgroundColorChanged = %s" % bg_attr)
    put("类属性对象 = fg:%r  bg:%r" % (
        getattr(type(view), "foregroundColorChanged", None),
        getattr(type(view), "backgroundColorChanged", None)))
    try:
        view.foregroundColorChanged.connect(lambda: COUNT.__setitem__("fg", COUNT["fg"] + 1))
        view.backgroundColorChanged.connect(lambda: COUNT.__setitem__("bg", COUNT["bg"] + 1))
        put("信号连接 = OK")
    except Exception:
        put("!! 信号连接失败:\n%s" % traceback.format_exc())
        return

    def after():
        put("  [150ms 后] 计数 = %r" % (COUNT,))
        put("  判读：若 fg 计数 > 0，说明 setForeGroundColor 会触发 foregroundColorChanged（进度 100%）")
        put("")
        put("=== T-1 探针结束 ===")
        flush_log()

    QTimer.singleShot(150, after)
    put("  [立即] 计数 = %r（信号可能是同步或异步触发）" % (COUNT,))


def run_t1_probe():
    put("=== T-1 环境验证开始 ===")
    put("时间戳 = %s" % __import__("time").strftime("%Y-%m-%d %H:%M:%S"))
    flush_log()
    try:
        step_env()
    except Exception:
        put("!! step_env 失败:\n%s" % traceback.format_exc())
    flush_log()
    view = None
    try:
        view = step_document()
    except Exception:
        put("!! step_document 失败:\n%s" % traceback.format_exc())
    flush_log()
    if view is not None:
        for fn in (step_fgbg, step_roundtrip):
            try:
                fn(view)
            except Exception:
                put("!! %s 失败:\n%s" % (fn.__name__, traceback.format_exc()))
            flush_log()
        try:
            step_signals(view)
        except Exception:
            put("!! step_signals 失败:\n%s" % traceback.format_exc())
            flush_log()
    else:
        put("!! 没有可用视图，跳过 [3][4][5]")
        put("=== T-1 探针结束（不完整）===")
        flush_log()


run_t1_probe()
