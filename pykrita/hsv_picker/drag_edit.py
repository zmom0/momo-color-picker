# -*- coding: utf-8 -*-
"""可在输入框上纵向拖动调值的 QLineEdit。

交互约定（横向留给文本选择，所以用纵向）：
  · 按下不纵移（< 3px）后松手 -> 当普通点击处理，正常编辑 / 选文字 / 全选；
  · 纵向拖过 3px            -> 进入拖动模式，按 -dy * sensitivity 改值（上拖变大）；
  · 拖动模式下实时回调 on_drag(value)，并同步显示（不触发 editingFinished）；
  · 拖动倍率由**自定义按键表**（field 区域）决定：默认无修饰=×1、Ctrl=×2、
    Ctrl+Shift=×4、Alt=×0.5；按下那一刻选定动作。
  · 表中为 `none` -> 该组合**不拖动**，但仍保留普通单击编辑（R19）。
"""

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import QLineEdit

try:                        # 插件内：包内相对导入
    from . import i18n
    from . import keymap_core as kmc
except ImportError:         # 离线单测：直接把本目录加进 sys.path
    import i18n
    import keymap_core as kmc

DRAG_THRESHOLD = 3

# 键表不支持的 Qt 修饰位（Meta / Keypad / GroupSwitch 等）：出现即落回「无修饰」行
_UNKNOWN_QT_MODS = (Qt.MetaModifier | Qt.KeypadModifier
                    | getattr(Qt, "GroupSwitchModifier", 0))


class DragValueEdit(QLineEdit):
    def __init__(self, parent=None, value_range=(0.0, 360.0), sensitivity=0.5,
                 decimals=2, wrap=False, on_drag=None):
        super().__init__(parent)
        self._min, self._max = float(value_range[0]), float(value_range[1])
        self._sensitivity = float(sensitivity)
        self._decimals = int(decimals)
        self._wrap = bool(wrap)
        self._on_drag = on_drag
        self._dragging = False
        self._press_y = 0
        self._start_value = 0.0
        self._drag_gain = 1.0
        self._drag_enabled = False
        self._drag_button = Qt.LeftButton
        self.keymap = kmc.default_keymap()      # 自定义按键表（field 区域）
        self.setCursor(Qt.SizeVerCursor)
        self.setToolTip(i18n.t(
            "可直接输入；也可按住纵向拖动调值（不按=标准速，Ctrl=×2，Ctrl+Shift=×4 更快，Alt=×0.5 精调）",
            "Type a value, or drag vertically to adjust (plain=normal, Ctrl=×2, Ctrl+Shift=×4 faster, Alt=×0.5 fine)"))

    def set_keymap(self, keymap):
        """灌入用户自定义按键表（面板持久化后调用）。"""
        self.keymap = kmc.normalize(keymap)

    @staticmethod
    def _btn_id(btn):
        if btn == Qt.MiddleButton:
            return "middle"
        if btn == Qt.RightButton:
            return "right"
        return "left"

    def _action_for(self, btn, mods):
        mod = kmc.mods_from_bools(bool(mods & Qt.ShiftModifier),
                                  bool(mods & Qt.ControlModifier),
                                  bool(mods & Qt.AltModifier),
                                  bool(mods & _UNKNOWN_QT_MODS))
        return kmc.lookup(self.keymap, "field", self._btn_id(btn), mod)

    def set_value(self, value):
        """只更新显示，不触发 editingFinished。"""
        text = ("%." + str(self._decimals) + "f") % float(value)
        if text != self.text():
            self.setText(text)

    def _clamp(self, value):
        if self._wrap:
            span = self._max - self._min
            if span <= 0:
                return self._min
            return (value - self._min) % span + self._min
        return max(self._min, min(self._max, value))

    def mousePressEvent(self, event):
        if event.button() in (Qt.LeftButton, Qt.MiddleButton, Qt.RightButton):
            action = self._action_for(event.button(), event.modifiers())
            # R19：表中 none / text_only -> 不拖动，但仍把事件交给基类做单击编辑
            self._drag_enabled = action in kmc.FIELD_DRAG_GAIN
            self._drag_gain = kmc.FIELD_DRAG_GAIN.get(action, 1.0)
            self._drag_button = event.button()
            self._press_y = event.y()
            self._dragging = False
            self.setFocus(Qt.MouseFocusReason)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_enabled and (event.buttons() & self._drag_button):
            dy = event.y() - self._press_y
            if not self._dragging and abs(dy) >= DRAG_THRESHOLD:
                self._dragging = True
                try:
                    self._start_value = float(self.text())
                except ValueError:
                    self._start_value = self._min
                    self.selectAll()
            if self._dragging:
                value = self._clamp(self._start_value -
                                    dy * self._sensitivity * self._drag_gain)
                self.set_value(value)
                if self._on_drag is not None:
                    self._on_drag(value)
                event.accept()
                return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        was_dragging = self._dragging
        self._dragging = False
        if was_dragging:
            # 拖动结束：把最终值按正常提交路径生效（走宿主校验，避免非法文本）
            self.editingFinished.emit()
        super().mouseReleaseEvent(event)
