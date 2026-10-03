# -*- coding: utf-8 -*-
"""弹窗行为探针（kritarunner）：外点自动关闭设置 + 菜单点击算内部。

用法：kritarunner.com -s popupprobe -f main
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


LOG = os.path.join(_momo_repo_root(), "tmp", "popup_probe.log")
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


class FakePress(object):
    """真 QMouseEvent 构造器（eventFilter 的 super() 需要真事件）。"""

    @staticmethod
    def make(gpos):
        from PyQt5.QtCore import QEvent, QPointF, Qt
        from PyQt5.QtGui import QMouseEvent
        return QMouseEvent(QEvent.MouseButtonPress, QPointF(5, 5), QPointF(5, 5),
                           QPointF(gpos), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)


def main(*args):
    sys.path.insert(0, os.path.join(os.environ["APPDATA"], "krita", "pykrita"))
    from PyQt5.QtCore import QPoint, Qt
    from PyQt5.QtWidgets import QApplication, QLineEdit
    app = QApplication.instance() or QApplication([])
    try:
        from hsv_picker import hsv_picker as hp
    except Exception:
        put("导入插件失败:\n" + traceback.format_exc())
        return 1

    dock = hp.HsvPickerDocker()
    # 探针使用隔离的设置；先把两项置于确定初始值，保证可重复
    dock.panel.set_always_on_top(True, _broadcast=False)
    dock.panel.set_auto_close_popup(True, _broadcast=False)
    pop = hp.HsvPickerPopup(dock.panel)
    pop.show()
    app.processEvents()
    pop.activateWindow()
    app.processEvents()

    check("「自动关闭」开：置顶实际不生效、菜单项置灰，但记忆值保留（R17）",
          pop.panel.auto_close_popup is True and pop.panel.act_auto_close.isChecked() is True
          and pop.panel.act_auto_close.text() == "点击弹出面板外时自动关闭"
          and pop.panel.act_on_top.text() == "弹出面板置顶"
          and pop.panel.always_on_top is True and pop.panel.act_on_top.isEnabled() is False
          and pop.panel.act_on_top.isChecked() is True,
          "auto=%s checked=%s on_top=%s enabled=%s top_checked=%s"
          % (pop.panel.auto_close_popup, pop.panel.act_auto_close.isChecked(),
             pop.panel.always_on_top, pop.panel.act_on_top.isEnabled(),
             pop.panel.act_on_top.isChecked()))

    # 1) 菜单上的按下：算内部，不隐藏
    r_menu = pop.eventFilter(pop.panel.menu, FakePress.make(QPoint(20000, 20000)))
    check("菜单点击不隐藏弹窗", pop.isVisible() and r_menu is not True,
          "visible=%s ret=%r" % (pop.isVisible(), r_menu))

    # 1b) 菜单后代控件（QAction 走 menu 事件）已覆盖；再测设置按钮本身
    btn_g = pop.panel.btn_menu.mapToGlobal(pop.panel.btn_menu.rect().center())
    r_btn = pop.eventFilter(pop.panel.btn_menu, FakePress.make(btn_g))
    check("设置按钮点击不隐藏", pop.isVisible() and r_btn is not True)

    # 2) 真正的外部点击：默认隐藏并消费
    out_g = pop.mapToGlobal(pop.rect().center()) + QPoint(4000, 3000)
    r_out = pop.eventFilter(None, FakePress.make(out_g))
    check("外部点击默认隐藏并消费", (not pop.isVisible()) and r_out is True,
          "visible=%s ret=%r" % (pop.isVisible(), r_out))

    # 3) 关掉设置后：外部点击不隐藏、不消费
    pop.panel.set_auto_close_popup(False)
    pop.show()
    app.processEvents()
    r_out2 = pop.eventFilter(None, FakePress.make(out_g))
    check("关闭设置后外部点击不隐藏不消费",
          pop.isVisible() and r_out2 is not True,
          "visible=%s ret=%r" % (pop.isVisible(), r_out2))

    # 4) 设置持久化 + 双面板同步
    panel2 = hp.HsvPickerPanel()
    check("新面板继承设置（持久化）", panel2.auto_close_popup is False,
          "panel2=%s" % panel2.auto_close_popup)
    dock.panel.set_auto_close_popup(True)
    check("双面板设置同步", pop.panel.auto_close_popup is True,
          "pop=%s" % pop.panel.auto_close_popup)
    check("菜单文字与状态一致", pop.panel.act_auto_close.isChecked() is True)

    # 5) 跨面板同步：完全同步 + 拖动隔离 + 量化容差回声判定
    pop.panel.set_color(60.0, 0.5, 0.5, write_fg=False)
    check("弹窗→主面板 颜色同步", abs(dock.panel.h - 60.0) < 1e-6,
          "dock=%.1f" % dock.panel.h)
    dock.panel.set_color(200.0, 0.4, 0.7, write_fg=False)
    check("主面板→弹窗 颜色同步（含读数）",
          abs(pop.panel.h - 200.0) < 1e-6 and pop.panel.edit_h.text() == "200.00",
          "pop=%.1f edit=%s" % (pop.panel.h, pop.panel.edit_h.text()))

    pop.panel.set_color(60.0, 0.5, 0.5, write_fg=False)
    pop.panel._picking = True                       # 模拟正在拖动
    dock.panel.apply_external(123.0, 0.9, 0.9, "#FF0000")
    check("拖动中忽略对端覆盖（不跳变）", abs(pop.panel.h - 60.0) < 1e-6,
          "h=%.1f" % pop.panel.h)
    pop.panel._picking = False

    # 量化容差：与当前色相差 ≤1 视为自己/对端的回声，相差大视为外部改色
    pop.panel.set_color(30.0, 0.6, 0.6, write_fg=False)
    r0, g0, b0 = pop.panel.picker_rgb()
    hex_self = "#%02X%02X%02X" % (r0, g0, b0)
    hex_near = "#%02X%02X%02X" % (min(255, r0 + 1), max(0, g0 - 1), b0)
    hex_far = "#%02X%02X%02X" % ((r0 + 40) % 256, (g0 + 40) % 256, (b0 + 40) % 256)
    check("量化容差判定（±1 回声 / 大差外部）",
          pop.panel._canvas_close_to_picker(hex_self)
          and pop.panel._canvas_close_to_picker(hex_near)
          and not pop.panel._canvas_close_to_picker(hex_far),
          "self=%s near=%s far=%s" % (hex_self, hex_near, hex_far))

    # 6) 应用级 Shift+B：弹窗可见→关闭，隐藏→弹出；文本输入框内不抢
    from PyQt5.QtCore import QEvent
    from PyQt5.QtGui import QKeyEvent
    import time as _t6
    ext = hp._EXTENSION
    ext._popup = pop          # 让扩展快捷键操作探针里的这个弹窗
    ext._docker = dock

    def _press():
        # text="B" 让真实派发到 QLineEdit 时能插入大写 B；过滤器只看 key+modifiers
        return QKeyEvent(QEvent.KeyPress, Qt.Key_B, Qt.ShiftModifier, "B")

    check("应用级快捷键过滤器已安装",
          getattr(ext, "_app_filter_installed", False) is True)
    pop.show()
    QApplication.processEvents()
    pop.panel.picker.setFocus(Qt.OtherFocusReason)
    QApplication.processEvents()
    r1 = ext.eventFilter(None, _press())
    check("焦点在拾色器上：Shift+B 关闭弹窗",
          (not pop.isVisible()) and r1 is True,
          "visible=%s ret=%r focus=%r" % (pop.isVisible(), r1, QApplication.focusWidget()))
    r2 = ext.eventFilter(None, _press())
    check("再按 Shift+B 重新弹出", pop.isVisible() and r2 is True)
    r2b = ext.eventFilter(None, _press())
    check("连按不等消抖（立即再关闭）", (not pop.isVisible()) and r2b is True,
          "visible=%s ret=%r" % (pop.isVisible(), r2b))
    pop.show()
    QApplication.processEvents()
    pop.activateWindow()
    QApplication.processEvents()
    pop.panel.edit_hex.setText("#FF0000")
    pop.panel.edit_hex.setCursorPosition(len(pop.panel.edit_hex.text()))
    pop.panel.edit_hex.setFocus(Qt.OtherFocusReason)
    QApplication.processEvents()
    fw = QApplication.focusWidget()
    if fw is pop.panel.edit_hex:
        # 真实派发：应用级过滤器放行 -> QLineEdit 收到大写 B，弹窗不关
        QApplication.sendEvent(pop.panel.edit_hex, _press())
        QApplication.processEvents()
        got_b = ("B" in pop.panel.edit_hex.text()) and pop.panel.edit_hex.text().endswith("B")
        r3 = ext.eventFilter(None, _press())
        check("弹窗 HEX 焦点：Shift+B 不关窗、输入框收到大写 B",
              pop.isVisible() and got_b and r3 is not True,
              "visible=%s text=%r ret=%r" % (pop.isVisible(), pop.panel.edit_hex.text(), r3))
        from PyQt5.QtGui import QShortcutEvent
        _seq = ext._shortcut_sequence()
        _short_ev = QShortcutEvent(_seq, 0)
        _short_match = _short_ev.key() == _seq[0]
        r3s = ext.eventFilter(pop.panel.edit_hex, _short_ev)
        check("弹窗 HEX 焦点：QEvent.Shortcut 分支同样不关窗",
              pop.isVisible() and _short_match and r3s is not True,
              "visible=%s ret=%r key_match=%s" % (pop.isVisible(), r3s, _short_match))
        pop.panel.picker.setFocus(Qt.OtherFocusReason)
        QApplication.processEvents()
        r3b = ext.eventFilter(None, _press())
        check("焦点回画布/拾色器后 Shift+B 恢复切换",
              (not pop.isVisible()) and r3b is True,
              "visible=%s ret=%r" % (pop.isVisible(), r3b))
    else:
        put("  [SKIP] 无法把焦点交给弹窗 HEX 输入框（focus=%r）" % (fw,))
    if pop.isVisible():
        pop.hide()
    outside = QLineEdit()
    outside.show()
    outside.activateWindow()
    QApplication.processEvents()
    outside.setFocus(Qt.OtherFocusReason)
    QApplication.processEvents()
    fw2 = QApplication.focusWidget()
    if fw2 is outside:
        r4 = ext.eventFilter(None, _press())
        check("Krita 文本框内不抢 Shift+B",
              r4 is not True and not pop.isVisible(),
              "visible=%s ret=%r" % (pop.isVisible(), r4))
    else:
        put("  [SKIP] 独立文本框无法获得焦点（focus=%r）" % (fw2,))
    outside.hide()
    pop.hide()

    # 7) 主面板取消勾选 → 弹窗也不自动关闭
    pop.show()
    QApplication.processEvents()
    dock.panel.set_auto_close_popup(False)
    r_partner_off = pop.eventFilter(None, FakePress.make(out_g))
    check("主面板取消勾选后外点不关",
          pop.isVisible() and r_partner_off is not True,
          "visible=%s ret=%r" % (pop.isVisible(), r_partner_off))
    dock.panel.set_auto_close_popup(True)

    # 8) 窗口置顶记忆（R17，不再联动）+ 独立顶层窗口（Windows 任务栏可见）
    type_mask = getattr(Qt, "WindowType_Mask", 0xFF)
    dock.panel.set_always_on_top(True)
    dock.panel.set_auto_close_popup(True)
    QApplication.processEvents()
    check("「自动关闭」开：实际不置顶、菜单置灰、记忆值保留 + 独立顶层窗口（任务栏可见）",
          (not bool(pop.windowFlags() & Qt.WindowStaysOnTopHint))
          and pop.panel.act_on_top.isEnabled() is False
          and pop.panel.always_on_top is True and pop.panel.act_on_top.isChecked() is True
          and (pop.windowFlags() & type_mask) == Qt.Window,
          "flags=%d type=%d enabled=%s on_top=%s"
          % (int(pop.windowFlags()), int(pop.windowFlags() & type_mask),
             pop.panel.act_on_top.isEnabled(), pop.panel.always_on_top))
    dock.panel.set_auto_close_popup(False)       # R17：不改写记忆值，只恢复生效
    QApplication.processEvents()
    check("关掉「自动关闭」后恢复记忆值（不强制勾选/取消）",
          bool(pop.windowFlags() & Qt.WindowStaysOnTopHint)
          and pop.panel.act_on_top.isEnabled() is True
          and pop.panel.always_on_top is True)
    dock.panel.set_always_on_top(False)
    QApplication.processEvents()
    check("取消置顶后窗口标志更新",
          not bool(pop.windowFlags() & Qt.WindowStaysOnTopHint))
    dock.panel.set_always_on_top(True)
    QApplication.processEvents()
    panel3 = hp.HsvPickerPanel()
    check("恢复置顶 + 新面板继承置顶设置（持久化）",
          bool(pop.windowFlags() & Qt.WindowStaysOnTopHint)
          and panel3.always_on_top is True)

    # 8c) R18「按键功能」弹窗继承实际置顶 + 宿主 parent + 切换即时刷新
    dock.panel.set_always_on_top(True)
    QApplication.processEvents()
    pop.panel.show_keymap_dialog()
    kdlg = getattr(pop.panel, "_keymap_dialog", None)
    kdlg_on = (kdlg is not None and kdlg.parentWidget() is pop
               and bool(kdlg.windowFlags() & Qt.WindowStaysOnTopHint))
    dock.panel.set_always_on_top(False)
    QApplication.processEvents()
    kdlg_off = bool(kdlg.windowFlags() & Qt.WindowStaysOnTopHint)
    dock.panel.set_always_on_top(True)
    QApplication.processEvents()
    kdlg_back = bool(kdlg.windowFlags() & Qt.WindowStaysOnTopHint)
    check("R18「按键功能」弹窗继承弹窗实际置顶（parent=弹窗、切换即时刷新）",
          kdlg_on and not kdlg_off and kdlg_back,
          "on=%s off=%s back=%s parent=%s"
          % (kdlg_on, kdlg_off, kdlg_back,
             None if kdlg is None else (kdlg.parentWidget() is pop)))
    if kdlg is not None:
        kdlg.hide()
    dock.panel.show_keymap_dialog()
    kdlg2 = getattr(dock.panel, "_keymap_dialog", None)
    check("R18 从 Docker 面板打开「按键功能」时以 Docker 为 parent",
          kdlg2 is not None and kdlg2.parentWidget() is dock,
          "parent=%r" % (None if kdlg2 is None else kdlg2.parentWidget(),))
    if kdlg2 is not None:
        kdlg2.hide()

    # 8b) 弹出位置跟随鼠标（默认开、可持久化、以鼠标为中心 + 窗口内贴边）
    from hsv_picker.hsv_picker import popup_position
    check("默认开启「弹出位置跟随鼠标」",
          pop.panel.popup_at_mouse is True and pop.panel.act_mouse_pos.isChecked() is True)
    screen = (0, 0, 1919, 1079)
    win = (100, 50, 1500, 900)
    check("以鼠标为中心弹出（窗口内）",
          popup_position((800, 475), (400, 600), screen, win) == (600, 175),
          "%r" % (popup_position((800, 475), (400, 600), screen, win),))
    check("超出窗口左上时贴边到窗口内",
          popup_position((100, 100), (400, 600), screen, win) == (100, 50))
    check("超出窗口右下时贴边到窗口内",
          popup_position((1490, 890), (400, 600), screen, win) == (1101, 301))
    check("多屏：鼠标在副屏也贴回 Krita 窗口内",
          popup_position((2000, 100), (400, 600), (1920, 0, 3839, 1079), win) == (1101, 50))
    check("弹窗比窗口还大时贴窗口左上",
          popup_position((800, 475), (400, 600), screen, (100, 50, 300, 200)) == (100, 50))
    check("无窗口信息时按屏幕可用区贴边",
          popup_position((100, 100), (400, 600), screen, None) == (0, 0))
    dock.panel.set_popup_at_mouse(False)
    check("关闭后同步到弹窗面板", pop.panel.popup_at_mouse is False)
    dock.panel.set_popup_at_mouse(True)
    panel4 = hp.HsvPickerPanel()
    check("新面板继承弹出位置设置（持久化）", panel4.popup_at_mouse is True)
    pop.show()
    QApplication.processEvents()
    pop._place_popup()
    check("实际放置调用成功且窗口可见", pop.isVisible())

    # 9) 中英双语：强制语言后新建面板，检查菜单文字
    hp.i18n._LANG = "en"
    panel_en = hp.HsvPickerPanel()
    check("英文界面（非中文环境）",
          panel_en.btn_menu.text() == "Settings"
          and panel_en.act_debug.text() == "Diagnostic log"
          and panel_en.act_on_top.text() == "Keep popup always on top",
          "btn=%r debug=%r" % (panel_en.btn_menu.text(), panel_en.act_debug.text()))
    hp.i18n._LANG = "zh_CN"
    panel_zh = hp.HsvPickerPanel()
    check("中文界面",
          panel_zh.btn_menu.text() == "设置"
          and panel_zh.act_debug.text() == "诊断日志"
          and panel_zh.act_on_top.text() == "弹出面板置顶",
          "btn=%r debug=%r" % (panel_zh.btn_menu.text(), panel_zh.act_debug.text()))
    hp.i18n._LANG = None

    # 10) 桌面元数据（插件管理器名称/说明）与插件内说明书
    import os as _os
    installed_root = _os.path.join(_os.environ["APPDATA"], "krita", "pykrita")
    desktop_path = _os.path.join(installed_root, "hsv_picker.desktop")
    desktop = open(desktop_path, encoding="utf-8").read()
    check("插件管理器名称：英文默认 + 中文 zh_CN",
          "Name=Momo Color Picker" in desktop and "Name[zh_CN]=馍馍拾色器" in desktop)
    check("插件说明（Comment）已缩写并保留 slogan",
          "Comment[zh_CN]=" in desktop
          and "更适合HSV宝宝的Oklab/Oklch拾色器" in desktop
          and len(desktop) < 1200,
          "len=%d" % len(desktop))
    check("X-Krita-Manual 指向 Manual.html", "X-Krita-Manual=Manual.html" in desktop)
    manual_path = _os.path.join(installed_root, "hsv_picker", "Manual.html")
    manual = open(manual_path, encoding="utf-8").read() if _os.path.isfile(manual_path) else ""
    check("插件内说明书已安装且含中英两版",
          len(manual) > 2000 and "Momo Color Picker" in manual and "馍馍拾色器" in manual)
    check("说明书含彩度概念解释（绝对/相对）",
          "绝对彩度" in manual and "相对彩度" in manual
          and "Absolute chroma" in manual and "relative chroma" in manual)
    check("说明书无技术细节章节",
          "技术信息" not in manual and "Technical notes" not in manual)
    check("说明书适配深色/默认主题",
          "prefers-color-scheme" in manual and "background" in manual)
    check("说明书无评审批注与 logo",
          "【" not in manual and "】" not in manual and "logo-" not in manual)
    check("说明书中文在前且英文锚点存在",
          "English ↓" in manual and 'id="english"' in manual
          and manual.index("功能与操作") < manual.index('id="english"'))
    _ci = manual.lower().find("controls</h")
    _di = manual.lower().find("concepts</h")
    check("功能在概念之前",
          manual.index("功能与操作") < manual.index("概念</h2>")
          and _ci >= 0 and _di >= 0 and _ci < _di,
          "controls=%d concepts=%d" % (_ci, _di))
    check("说明书引用图文资产", manual.count("manual/images/") >= 15,
          "refs=%d" % manual.count("manual/images/"))
    check("说明书字号已加大",
          "font-size: 16px" in manual and "font-size: 14.5px" in manual)

    # 收尾：恢复默认，避免影响用户会话
    dock.panel.set_always_on_top(True)
    # 11) 视图跟随：弹窗始终使用活动视图；Docker canvasChanged 广播给弹窗
    class _Sig(object):
        def connect(self, fn):
            pass

        def disconnect(self, fn):
            pass

    class _View(object):
        def __init__(self):
            self.foregroundColorChanged = _Sig()
            self.backgroundColorChanged = _Sig()

        def foregroundColor(self):
            return None

        def backgroundColor(self):
            return None

        def canvas(self):
            return None

    class _Canvas(object):
        def __init__(self, view):
            self._view = view

        def view(self):
            return self._view

    view_a, view_b = _View(), _View()
    check("弹窗面板跟随活动视图、Docker 不跟随",
          pop.panel.follow_active_view is True and dock.panel.follow_active_view is False)
    dock.canvasChanged(_Canvas(view_a))
    check("Docker 视图变化广播给弹窗（sink）", pop.panel._view is view_a)
    old_active_view = hp.active_view
    hp.active_view = lambda: view_b
    try:
        check("弹窗动态跟随活动视图（解析不重绑）",
              pop.panel._resolve_view() is view_b,
              "resolved=%r bound=%r" % (pop.panel._resolve_view(), pop.panel._view))
        hp.active_view = lambda: _View()
        try:
            pop.panel._resolve_view()
            churn_ok = True
        except RecursionError:
            churn_ok = False
        check("activeView 每次返回新 wrapper 也不递归", churn_ok)
        try:
            pop5 = hp.HsvPickerPopup(dock.panel)
            make_ok = pop5 is not None
        except Exception as exc:
            make_ok = False
            put("  创建弹窗异常：%r" % (exc,))
        check("activeView 抖动时仍能创建弹窗（快捷键不再失效）", make_ok)
    finally:
        hp.active_view = old_active_view

    # 12) T-40 弹窗尺寸：默认贴合内容、只记用户 resize、旧键不生效
    from PyQt5.QtGui import QCursor, QGuiApplication
    _k = hp.Krita.instance()
    _legacy_key = hp.POPUP_SIZE_LEGACY_KEY
    _user_key = hp.POPUP_SIZE_USER_KEY
    _old_legacy = _k.readSetting("", _legacy_key, "") or ""
    _old_user = _k.readSetting("", _user_key, "") or ""
    _pops = []
    try:
        _k.writeSetting("", _legacy_key, "333x444")      # 旧键存在，但必须不生效
        _k.writeSetting("", _user_key, "")
        _pd = hp.HsvPickerPopup(None)
        _pops.append(_pd)
        _hint = _pd.panel.sizeHint()
        _min_hint = _pd.panel.minimumSizeHint()
        _exp_w = max(_hint.width(), _min_hint.width(), _pd.panel.minimumWidth())
        _exp_h = max(_hint.height(), _min_hint.height(), _pd.panel.minimumHeight())
        _exp_h = max(_exp_h, int(round(_exp_w * hp.POPUP_FILL_ASPECT)))
        _pd.show()
        QApplication.processEvents()
        _pd.panel._layout_picker()
        QApplication.processEvents()
        _pk, _mb = _pd.panel.picker, _pd.panel.mid_box
        check("T-40 新用户默认尺寸让拾色器填满宽度（旧键 %s 不生效）" % _legacy_key,
              abs(_pd.width() - _exp_w) <= 2 and abs(_pd.height() - _exp_h) <= 2
              and (_pd.width(), _pd.height()) != (333, 444)
              and (_mb.width() - _pk.width()) <= 32
              and abs(_mb.height() - _pk.height()) <= 2,
              "sizeHint=%dx%d minHint=%dx%d expect=%dx%d pop=%dx%d picker=%d mid=%dx%d"
              % (_hint.width(), _hint.height(), _min_hint.width(), _min_hint.height(),
                 _exp_w, _exp_h, _pd.width(), _pd.height(), _pk.width(),
                 _mb.width(), _mb.height()))
        _m = _pd.layout().contentsMargins()
        check("T-40 默认弹窗无空白（布局边距 0、面板铺满内容区）",
              (_m.left() + _m.right() + _m.top() + _m.bottom()) == 0
              and _pd.panel.size() == _pd.contentsRect().size(),
              "margins=%d,%d,%d,%d pop=%dx%d panel=%dx%d"
              % (_m.left(), _m.top(), _m.right(), _m.bottom(),
                 _pd.width(), _pd.height(), _pd.panel.width(), _pd.panel.height()))
        _mem_after_show = _k.readSetting("", _user_key, "") or ""
        check("T-40 默认尺寸/首次显示不写用户记忆", _mem_after_show == "",
              "user=%r" % _mem_after_show)
        _pd.resize(520, 640)                 # 模拟用户拖边框
        QApplication.processEvents()
        _mem_user = _k.readSetting("", _user_key, "") or ""
        check("T-40 用户 resize 后写入新键", _mem_user == "520x640",
              "user=%r" % _mem_user)
        _pd.hide()
        _pr = hp.HsvPickerPopup(None)
        _pops.append(_pr)
        check("T-40 重开恢复用户尺寸",
              abs(_pr.width() - 520) <= 2 and abs(_pr.height() - 640) <= 2,
              "restored=%dx%d" % (_pr.width(), _pr.height()))
        _k.writeSetting("", _user_key, "4000x4000")     # 超出屏幕：应 clamp
        _pc = hp.HsvPickerPopup(None)
        _pops.append(_pc)
        _scr = QGuiApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
        _ag = _scr.availableGeometry()
        check("T-40 用户尺寸超出屏幕时 clamp 到可用区",
              _pc.width() <= _ag.width() and _pc.height() <= _ag.height()
              and (_pc.width(), _pc.height()) != (4000, 4000),
              "pop=%dx%d screen=%dx%d" % (_pc.width(), _pc.height(),
                                          _ag.width(), _ag.height()))
    finally:
        for _p in _pops:
            try:
                _p.hide()
            except Exception:
                pass
        _k.writeSetting("", _legacy_key, _old_legacy)
        _k.writeSetting("", _user_key, _old_user)

    # 13) T-53 临时切换键：Docker ↔ 弹窗同步 + 弹窗真实 widgetAt 命中 + 悬停即时切换
    from PyQt5.QtGui import QCursor
    dock.panel.set_temp_chroma_key("shift")
    key_sync = pop.panel.temp_chroma_key == "shift"
    dock.panel.set_temp_chroma_key("alt")
    QApplication.processEvents()
    key_sync = key_sync and pop.panel.temp_chroma_key == "alt"
    dock.panel.set_temp_chroma_key("shift")
    QApplication.processEvents()
    check("T53p1 临时切换键 Docker ↔ 弹窗双向同步（默认 shift、改 alt 后弹窗跟随）",
          key_sync, "dock=%s pop=%s" % (dock.panel.temp_chroma_key,
                                        pop.panel.temp_chroma_key))

    pop.show()
    QApplication.processEvents()
    pop.activateWindow()
    QApplication.processEvents()
    orig_pop_focus = pop.panel._text_input_has_focus
    pop.panel._text_input_has_focus = lambda: False
    pop.panel._kb_clear()
    pop.panel._panel_hovered = False
    cursor_probe = None
    try:
        center_g = pop.mapToGlobal(QPoint(pop.width() // 2, pop.height() // 2))
        QCursor.setPos(center_g)
        QApplication.processEvents()
        if QCursor.pos() == center_g:
            cursor_probe = pop.panel._cursor_inside_panel()
    except Exception:
        cursor_probe = None
    if cursor_probe is True:
        pop.panel._refresh_panel_hover()
        hit_in = pop.panel._panel_hovered
        pop.panel._kb_shift = True
        pop.panel._update_hover_temp()
        hover_on = (pop.panel.picker.temp_chroma_mode in ("rel", "abs")
                    and pop.panel.strip_c.mode == pop.panel.picker.temp_chroma_mode)
        dock_untouched = dock.panel.picker.temp_chroma_mode is None
        scr = QApplication.primaryScreen().availableGeometry()
        cands = [QPoint(scr.left() + 2, scr.top() + 2),
                 QPoint(scr.right() - 2, scr.bottom() - 2),
                 QPoint(scr.left() + 2, scr.bottom() - 2),
                 QPoint(scr.right() - 2, scr.top() + 2)]
        out_g = None
        for q in cands:
            if not pop.frameGeometry().contains(q):
                out_g = q
                break
        out_miss = out_after = None
        if out_g is not None:
            QCursor.setPos(out_g)
            QApplication.processEvents()
            out_miss = (not pop.panel._cursor_inside_panel())
            pop.panel._refresh_panel_hover()
            out_after = (not pop.panel._panel_hovered
                         and pop.panel.picker.temp_chroma_mode is None)
        pop.panel._kb_shift = False
        pop.panel._update_hover_temp()
        ok = bool(hit_in and hover_on and dock_untouched and out_miss and out_after)
        put("  T53p2 实测：真实光标在弹窗内命中=%s、悬停预览=%s、主面板未受影响=%s；"
            "移出后不命中=%s、恢复=%s" % (hit_in, hover_on, dock_untouched, out_miss, out_after))
    else:
        ok = True
        put("  [SKIP] T53p2 鼠标注入不可用（QCursor.pos 不跟随）；真实 widgetAt 留待手工验收")
    check("T53p2 弹窗真实 widgetAt 父链命中/移出：命中即预览、移出立即恢复、不泄漏到主面板",
          ok, "cursor_probe=%s" % (cursor_probe,))

    # 显式状态循环：弹窗 10 次按下/松开不锁存；主面板独立
    latch_ok = True
    for _i in range(10):
        pop.panel._panel_hovered = True
        pop.panel._kb_shift = True
        pop.panel._update_hover_temp()
        on = pop.panel.picker.temp_chroma_mode in ("rel", "abs")
        pop.panel._kb_shift = False
        pop.panel._update_hover_temp()
        off = pop.panel.picker.temp_chroma_mode is None
        latch_ok = latch_ok and on and off
    orig_dock_focus = dock.panel._text_input_has_focus
    dock.panel._text_input_has_focus = lambda: False
    dock.panel._panel_hovered = True
    dock.panel._kb_shift = True
    dock.panel._update_hover_temp()
    dock_on = dock.panel.picker.temp_chroma_mode in ("rel", "abs")
    pop_off = pop.panel.picker.temp_chroma_mode is None
    dock.panel._kb_shift = False
    dock.panel._update_hover_temp()
    dock_off = dock.panel.picker.temp_chroma_mode is None
    dock.panel._text_input_has_focus = orig_dock_focus
    dock.panel._panel_hovered = False
    pop.panel._text_input_has_focus = orig_pop_focus
    pop.panel._kb_clear()
    pop.panel._panel_hovered = False
    pop.panel._update_hover_temp()
    check("T53p3 弹出面板悬停 10 次不锁存；释放/移出后立即恢复，主面板独立",
          latch_ok and dock_on and dock_off and pop_off,
          "latch=%s dock_on=%s dock_off=%s pop_off=%s"
          % (latch_ok, dock_on, dock_off, pop_off))
    put("  T53p3 实测：弹窗 10 次循环无锁存=%s；主面板独立预览=%s、松开恢复=%s；"
        "弹窗保持第二口径未泄漏=%s" % (latch_ok, dock_on, dock_off, pop_off))

    # 收尾：恢复默认，避免影响用户会话
    dock.panel.set_auto_close_popup(True)
    pop.hide()

    # 14) T-54 关闭 Krita 时收掉弹窗（退出收尾三条钩子 + 最后一个主窗口 Close）
    from PyQt5.QtGui import QCloseEvent
    from PyQt5.QtWidgets import QMainWindow
    _t54_pops = []
    _t54_wins = []
    ext._remove_quit_hooks()        # 干净起点（真实 createActions 可能已装过一次）
    _attr_ok = pop.testAttribute(Qt.WA_QuitOnClose) is False
    check("T54a 弹窗 WA_QuitOnClose=False（不参与 Qt「最后一个窗口」判定）",
          _attr_ok, "attr=%s" % (pop.testAttribute(Qt.WA_QuitOnClose),))

    ext._install_quit_hooks()
    _t54_filter1 = getattr(ext, "_quit_filter", None)
    ext._install_quit_hooks()       # 重复调用必须被标志挡住
    _t54_filter2 = getattr(ext, "_quit_filter", None)
    _t54_once = (getattr(ext, "_quit_hook_installed", False) is True
                 and _t54_filter1 is not None and _t54_filter2 is _t54_filter1
                 and getattr(ext, "_quit_notifier", None) is not None
                 and getattr(ext, "_quit_app", None) is QApplication.instance())
    check("T54b 退出收尾三条钩子只挂一次（对象不变、引用齐备）",
          _t54_once,
          "installed=%s filter_same=%s notifier=%s app=%s"
          % (getattr(ext, "_quit_hook_installed", False), _t54_filter2 is _t54_filter1,
             getattr(ext, "_quit_notifier", None) is not None,
             getattr(ext, "_quit_app", None) is QApplication.instance()))

    # 信号已连接/可断开：已连接时 disconnect 不抛，未连接时 PyQt 抛 TypeError
    _sig_linked = {"app": False, "krita": False}
    try:
        QApplication.instance().aboutToQuit.disconnect(ext._close_popup_for_quit)
        _sig_linked["app"] = True
        QApplication.instance().aboutToQuit.connect(ext._close_popup_for_quit)
    except Exception:
        _sig_linked["app"] = False
    try:
        ext._quit_notifier.applicationClosing.disconnect(ext._close_popup_for_quit)
        _sig_linked["krita"] = True
        ext._quit_notifier.applicationClosing.connect(ext._close_popup_for_quit)
    except Exception:
        _sig_linked["krita"] = False
    check("T54c applicationClosing 与 aboutToQuit 两条信号均已连接",
          _sig_linked["app"] and _sig_linked["krita"], "%r" % (_sig_linked,))

    def _hide_t54_wins():
        for _w in _t54_wins:
            try:
                _w.hide()
            except RuntimeError:
                pass
        QApplication.processEvents()

    def _mk_pop54():
        _p = hp.HsvPickerPopup(dock.panel)
        _t54_pops.append(_p)
        ext._popup = _p
        _p.show()
        QApplication.processEvents()
        return _p

    # 正例：唯一可见主窗口收到 Close -> 弹窗立即隐藏、扩展引用置空
    _hide_t54_wins()
    _p1 = _mk_pop54()
    _w1 = QMainWindow()
    _t54_wins.append(_w1)
    _w1.show()
    QApplication.processEvents()
    QApplication.sendEvent(_w1, QCloseEvent())
    _p1_vis, _p1_ref = _p1.isVisible(), ext._popup
    check("T54d 最后一个可见主窗口收到 Close：弹窗立即收掉且引用置空",
          (not _p1_vis) and _p1_ref is None,
          "visible=%s ref=%r" % (_p1_vis, _p1_ref))

    # 钩子可整体移除：移除后同样的 Close 不再收弹窗，两条信号也确实断开
    _hide_t54_wins()
    ext._remove_quit_hooks()
    _p2 = _mk_pop54()
    _w2 = QMainWindow()
    _t54_wins.append(_w2)
    _w2.show()
    QApplication.processEvents()
    QApplication.sendEvent(_w2, QCloseEvent())
    _p2_vis, _p2_ref = _p2.isVisible(), ext._popup
    _removed_ok = _p2_vis and _p2_ref is _p2
    _sig_gone = {"app": False, "krita": False}
    try:
        QApplication.instance().aboutToQuit.disconnect(ext._close_popup_for_quit)
    except TypeError:
        _sig_gone["app"] = True
    except Exception:
        pass
    try:
        hp.Krita.instance().notifier().applicationClosing.disconnect(
            ext._close_popup_for_quit)
    except TypeError:
        _sig_gone["krita"] = True
    except Exception:
        pass
    try:
        hp.Krita.instance().notifier().applicationClosing.emit()   # 移除期间也不该收
    except Exception:
        pass
    _p2_vis2, _p2_ref2 = _p2.isVisible(), ext._popup
    check("T54e 退出过滤器/信号可整体移除：移除后 Close 与 applicationClosing 均不收弹窗",
          _removed_ok and _p2_vis2 and _p2_ref2 is _p2
          and _sig_gone["app"] and _sig_gone["krita"],
          "close_removed=%s visible=%s ref_is=%s disc=%r"
          % (_removed_ok, _p2_vis2, _p2_ref2 is _p2, _sig_gone))

    # 反例：两个可见主窗口关其一 -> 弹窗不受影响
    ext._install_quit_hooks()       # 重新装回（与真实运行一致）
    _hide_t54_wins()
    _p3 = _mk_pop54()
    _wa = QMainWindow()
    _wb = QMainWindow()
    _t54_wins.extend([_wa, _wb])
    _wa.show()
    _wb.show()
    QApplication.processEvents()
    QApplication.sendEvent(_wa, QCloseEvent())
    _p3_vis, _p3_ref = _p3.isVisible(), ext._popup
    check("T54f 两个可见主窗口关其一：弹窗不受影响",
          _p3_vis and _p3_ref is _p3,
          "visible=%s ref_is=%s wa_visible=%s wb_visible=%s"
          % (_p3_vis, _p3_ref is _p3, _wa.isVisible(), _wb.isVisible()))

    # applicationClosing 正例：信号触发同样收弹窗（钩子真实生效）
    _hide_t54_wins()
    _p4 = _mk_pop54()
    try:
        hp.Krita.instance().notifier().applicationClosing.emit()
    except Exception:
        pass
    _p4_vis, _p4_ref = _p4.isVisible(), ext._popup
    check("T54g applicationClosing 信号触发：弹窗收掉",
          (not _p4_vis) and _p4_ref is None,
          "visible=%s ref=%r" % (_p4_vis, _p4_ref))

    # 回归：退出钩子在装状态下不影响弹窗 toggle 既有语义
    _hide_t54_wins()
    _p5 = _mk_pop54()
    _p5.toggle()
    _p5_off = not _p5.isVisible()
    _p5.toggle()
    _p5_on = _p5.isVisible() and ext._popup is _p5
    _p5_attr = _p5.testAttribute(Qt.WA_QuitOnClose) is False   # setWindowFlags 后属性仍在
    check("T54h 退出钩子不影响弹窗 toggle 既有语义（置顶/重设窗口标志后属性保持）",
          _p5_off and _p5_on and _p5_attr,
          "off=%s on=%s attr_false=%s" % (_p5_off, _p5_on, _p5_attr))

    # T-54 收尾：移除退出过滤器、隐藏临时窗口与弹窗，避免污染后续用例
    ext._remove_quit_hooks()
    ext._popup = None
    for _w in _t54_wins:
        try:
            _w.hide()
        except Exception:
            pass
    for _p in _t54_pops:
        try:
            _p.hide()
        except Exception:
            pass
    QApplication.processEvents()
    for _p in _t54_pops:
        try:
            _p.deleteLater()
        except Exception:
            pass
    QApplication.processEvents()
    put("  T54 实测：WA_QuitOnClose=False 断言=%s；三钩子只挂一次=%s；唯一主窗口 Close 收弹窗=%s；"
        "移除后 Close 不收=%s、applicationClosing 不收=%s；双主窗口不误收=%s；"
        "applicationClosing 正例收弹窗=%s；toggle 回归=%s"
        % (_attr_ok, _t54_once, (not _p1_vis), _removed_ok,
           _p2_vis2, _p3_vis, (not _p4_vis), (_p5_off and _p5_on)))

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
