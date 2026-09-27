# -*- coding: utf-8 -*-
"""诊断日志模式 UI 探针（kritarunner，跑已安装的插件）。

验证：开关默认关 / 开启后落盘 / 输入事件与明度条映射链 / JUMP 标记 / 关闭后不再增长 /
     「每次按下重锁当前 C_rel」修复。
用法：kritarunner.com -s logprobe -f main
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


LOG = os.path.join(_momo_repo_root(), "tmp", "log_probe.log")
DBG = os.path.join(_momo_repo_root(), "tmp", "log_probe_debug.log")
os.environ["HSV_PICKER_DEBUG_LOG"] = DBG

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


def main(*args):
    sys.path.insert(0, os.path.join(os.environ["APPDATA"], "krita", "pykrita"))
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication
    QApplication.instance() or QApplication([])
    try:
        from hsv_picker import hsv_picker as hp
        hp.i18n._LANG = "zh"      # 探针固定中文，断言与语言环境无关
    except Exception:
        put("导入插件失败:\n" + traceback.format_exc())
        return 1

    for path in (DBG, DBG + ".1"):
        try:
            if os.path.exists(path):
                os.remove(path)
        except OSError:
            pass

    panel = hp.HsvPickerPanel()
    panel.resize(520, 900)
    panel.mid_box.resize(508, 640)
    panel._layout_picker()

    check("默认关闭", hp.dlog.is_enabled() is False and panel.debug_log is False,
          "enabled=%s flag=%s" % (hp.dlog.is_enabled(), panel.debug_log))

    # ---- 每次按下重锁当前 C_rel（T-17 候选修复）----
    panel.set_color(0.0, 0.5, 0.7)
    panel._on_strip_l_press()
    panel._on_strip_lightness(0.4)
    crel1 = panel._strip_crel
    panel._on_strip_release()
    check("松手清 C_rel 锁", panel._strip_crel is None)
    panel.set_color(210.0, 0.9, 0.8)
    cur = panel._crel_now()
    panel._on_strip_l_press()
    panel._on_strip_lightness(0.4)
    crel2 = panel._strip_crel
    panel._on_strip_release()
    check("每次按下重锁当前 C_rel",
          abs(crel2 - cur) < 1e-9 and abs(crel2 - crel1) > 1e-3,
          "crel1=%.4f crel2=%.4f cur=%.4f" % (crel1, crel2, cur))

    # ---- 开启日志：明度条拖动 + 方块右键拖动 ----
    import time as _time

    def _strip_loop(panel, n=30, pace=0.016):
        """模拟 60Hz 平滑拖动：每步 16ms、ΔL=0.005；只统计单次处理耗时（不含 sleep）。"""
        panel.set_color(210.0, 0.8, 0.6)
        panel._on_strip_l_press()
        work = 0.0
        for i in range(n):
            t0 = _time.monotonic()
            panel._on_strip_lightness(0.05 + 0.005 * i)
            work += _time.monotonic() - t0
            _time.sleep(pace)
        panel._on_strip_release()
        return work * 1000.0 / float(n)

    dt_off = _strip_loop(panel)
    panel.set_debug_log(True)
    dt_on = _strip_loop(panel)
    put("  明度条单次处理（60Hz 平滑拖动）：关=%.3f ms 开=%.3f ms（绝对开销 %+.3f ms，比值 %.2f）"
        % (dt_off, dt_on, dt_on - dt_off, dt_on / max(dt_off, 1e-9)))
    check("日志开启单次处理 ≤ 16.7ms（60fps 预算）", dt_on <= 16.7, "%.3f ms" % dt_on)
    check("日志开启绝对开销 ≤ 2ms/次", (dt_on - dt_off) <= 2.0,
          "%+.3f ms" % (dt_on - dt_off))
    check("开启生效", hp.dlog.is_enabled() is True and panel.debug_log is True)
    check("菜单文字变为开启中", "开启" in panel.act_debug.text(), panel.act_debug.text())

    panel.set_color(210.0, 0.8, 0.6)
    panel._on_strip_l_press()
    for t in (0.6, 0.4, 0.2, 0.08, 0.03):
        panel._on_strip_lightness(t)
    panel._on_strip_release()

    panel.set_color(60.0, 0.5, 0.5)
    panel.set_color(60.0, 0.0, 0.0)          # 人为制造 >0.02 的明度跳变
    c = panel.picker
    g = c._geometry()
    cx = g["sq"][0] + (g["sq"][2] - g["sq"][0]) / 2.0
    cy = g["sq"][1] + (g["sq"][3] - g["sq"][1]) / 2.0
    c.mousePressEvent(Ev(cx, cy, Qt.RightButton))
    c.mouseMoveEvent(Ev(cx, cy + 24, Qt.RightButton, Qt.RightButton))
    c.mouseReleaseEvent(Ev(cx, cy + 24, Qt.RightButton))

    hp.dlog.flush(force=True)
    text = open(DBG, encoding="utf-8").read()
    check("日志有会话头 SES", "SES" in text)
    check("日志有明度条按下", "STRIP_L_DOWN" in text)
    check("日志有明度条拖动链", ("STRIP_L_HIT" in text) or ("STRIP_L_CLAMP" in text), "")
    check("日志有状态行", "SET" in text and "L=" in text)
    check("日志有 JUMP 标记", "JUMP" in text)
    check("日志有拾色器按下/移动/松开",
          "PICK_DOWN" in text and "PICK_MOVE" in text and "PICK_UP" in text)
    check("日志有明度条松开", "STRIP_UP" in text)

    # ---- 持久化：新面板继承开关 ----
    panel2 = hp.HsvPickerPanel()
    check("新面板继承开关（持久化）", panel2.debug_log is True, "panel2=%s" % panel2.debug_log)

    # ---- 关闭后不再增长 ----
    panel.set_debug_log(False)
    panel2.set_debug_log(False)
    check("关闭生效", hp.dlog.is_enabled() is False)
    size = os.path.getsize(DBG)
    panel.set_color(10.0, 0.5, 0.5)
    hp.dlog.flush(force=True)
    check("关闭后文件不再增长", os.path.getsize(DBG) == size,
          "%d -> %d" % (size, os.path.getsize(DBG)))

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
