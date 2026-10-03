# -*- coding: utf-8 -*-
"""T-51 布局取直探针（kritarunner）：文本完整 + 窄时左对齐 / 宽时右对齐 + 尺寸矩阵。

覆盖：
  A8 文本始终完整：H/S/V 始终两位小数、HEX 始终完整 #RRGGBB，不出现省略号/动态小数；
     宽度足够（600/800）右对齐；宽度不足（455/420/400/350）左对齐并把显示停在开头。
  A9 宽度自适应骨架保留：够宽取上限后不再变宽、余量给色块；窄时 H/S/V 等宽、HEX 收缩、不溢出。
产物截图：tmp/t48-t49/layout-<宽>.png（600/455/400/350）。
用法：kritarunner.com -s layoutprobe -f main
"""

import json
import os
import re
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


SHOTS = os.path.join(_momo_repo_root(), "tmp", "t48-t49")
LOG = os.path.join(SHOTS, "layout_probe.log")
PASS = [0]
FAIL = []
_OUT = None


def put(msg=""):
    global _OUT
    if _OUT is None:
        os.makedirs(SHOTS, exist_ok=True)
        _OUT = open(LOG, "w", encoding="utf-8", newline="\n")
    _OUT.write(str(msg) + "\n")
    _OUT.flush()


def check(name, ok, detail=""):
    if ok:
        PASS[0] += 1
    else:
        FAIL.append("%s %s" % (name, detail))
    put("[%s] %s  %s" % ("OK  " if ok else "FAIL", name, detail))


def main(*args):
    sys.path.insert(0, os.path.join(os.environ["APPDATA"], "krita", "pykrita"))
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication, QStyle
    app = QApplication.instance() or QApplication([])

    def flush():
        app.processEvents()
        app.processEvents()

    try:
        from hsv_picker import hsv_picker as hp
    except Exception:
        put("导入插件失败:\n" + traceback.format_exc())
        return 1

    os.makedirs(SHOTS, exist_ok=True)
    panel = hp.HsvPickerPanel()
    panel.setAttribute(Qt.WA_DontShowOnScreen, True)
    panel.resize(600, 900)
    panel.show()
    flush()
    panel.set_chroma_mode("rel", _broadcast=False)
    panel.set_lightness_metric("oklab", _broadcast=False)
    panel.set_color(123.0, 0.5, 0.6)
    panel._sync_entries()
    flush()

    edits = (panel.edit_h, panel.edit_s, panel.edit_v, panel.edit_hex)

    def align_of(edit):
        a = edit.alignment() & Qt.AlignHorizontal_Mask
        if a == Qt.AlignLeft:
            return "left"
        if a == Qt.AlignRight:
            return "right"
        return "other(%d)" % int(a)

    def need_of(edit):
        fm = edit.fontMetrics()
        frame = edit.style().pixelMetric(QStyle.PM_DefaultFrameWidth)
        return fm.horizontalAdvance(edit.text()) + 2 * frame + 4

    rows = {}
    for w in (800, 600, 455, 420, 400, 350, 300):
        panel.resize(w, 900)
        panel.layout().activate()
        panel._data_row.activate()
        flush()
        for e in edits:
            e.clearFocus()
        panel._layout_entry_widths()
        flush()
        rows[w] = {
            "panel_w": panel.width(),
            "widths": [e.width() for e in edits],
            "texts": [e.text() for e in edits],
            "align": [align_of(e) for e in edits],
            "cursor": [e.cursorPosition() for e in edits],
            "need": [need_of(e) for e in edits],
            "swatch_w": panel.swatch_cur.width(),
            "row_w": panel._data_row.geometry().width(),
            "limits": [panel._w_hsv_full, panel._w_hsv_1, panel._w_hsv_0,
                       panel._w_hex_full, panel._w_hex_min],
            "fixed": panel._entry_row_fixed,
        }
        if w in (600, 455, 400, 350):
            pm = panel.grab()
            path = os.path.join(SHOTS, "layout-%d.png" % w)
            if not pm.save(path, "PNG"):
                put("截图保存失败：%s" % path)
    put(json.dumps(dict((str(k), v) for k, v in rows.items()),
                   ensure_ascii=False, indent=1))

    def hsv_full(text):
        return re.match(r"^\d+\.\d{2}$", text) is not None

    def fits(w):
        r = rows[w]
        return (r["widths"][0] == r["widths"][1] == r["widths"][2]
                and r["row_w"] <= r["panel_w"] - 12 + 1
                and r["swatch_w"] >= 24 and all(x > 0 for x in r["widths"]))

    # A8a 文本始终完整、无省略号、无动态小数
    texts_ok = True
    for w in rows:
        r = rows[w]
        if not (all(hsv_full(t) for t in r["texts"][:3])
                and re.match(r"^#[0-9A-F]{6}$", r["texts"][3]) is not None
                and all("…" not in t for t in r["texts"])):
            texts_ok = False
    check("A8a 全尺寸文本始终完整：H/S/V 两位小数、HEX #RRGGBB、无省略号", texts_ok)

    # A8b 宽面板右对齐；窄面板按各自文本宽度决定：不足以完整显示则左对齐+光标 0
    wide_ok = all(rows[w]["align"] == ["right"] * 4 for w in (600, 800))
    narrow_ok = True
    for w in (455, 420, 400, 350):
        r = rows[w]
        for i in range(4):
            expect_left = r["widths"][i] < r["need"][i]
            want = "left" if expect_left else "right"
            if r["align"][i] != want:
                narrow_ok = False
            if expect_left and r["cursor"][i] != 0:
                narrow_ok = False
    check("A8b 600/800 全右对齐；窄面板按文本宽度：放不下则左对齐且光标停在开头",
          wide_ok and narrow_ok,
          "wide=%s narrow=%s" % (wide_ok, narrow_ok))

    # A9 宽度自适应骨架：600/800 到上限；455 等宽；350 HEX 收缩；全程不溢出
    lim = rows[600]["limits"]
    a9 = (rows[600]["widths"] == [lim[0], lim[0], lim[0], lim[3]]
          and rows[800]["widths"] == rows[600]["widths"]
          and rows[455]["widths"][0] == rows[455]["widths"][1] == rows[455]["widths"][2]
          and rows[350]["widths"][0] == lim[2]
          and rows[350]["widths"][3] == lim[4]
          and all(fits(w) for w in (600, 800, 455, 420, 400, 350)))
    check("A9 宽度自适应骨架：够宽取上限不变宽、455 等宽、350 HEX 收缩、全程不溢出",
          a9, "600=%s 455=%s 350=%s" % (rows[600]["widths"], rows[455]["widths"],
                                         rows[350]["widths"]))

    # 截图留档
    shots = [os.path.join(SHOTS, "layout-%d.png" % w) for w in (600, 455, 400, 350)]
    check("A9b 截图留档 600/455/400/350", all(os.path.isfile(p) for p in shots),
          str(shots))

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
