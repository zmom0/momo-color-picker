# -*- coding: utf-8 -*-
"""色块控件。

- ``CurrentColorSwatch``：面板常驻的**当前色小色块**（24×24、1px 边框），放在数值行 HEX 框右边；
- ``ColorSwatchWidget``：旧的三色块（当前/前景/背景），面板已不再使用，保留备用。

色块颜色均为实时值（不是点击前快照）。
"""

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QPainter
from PyQt5.QtWidgets import QApplication, QSizePolicy, QWidget

try:                        # 插件内：包内相对导入
    from . import i18n
except ImportError:         # 离线单测：直接把本目录加进 sys.path
    import i18n

TOP_H = 24.0        # 当前拾色器色块高度
BOTTOM_H = 24.0     # 前景/背景色块高度


class ColorSwatchWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(int(TOP_H + BOTTOM_H))
        self.picker_color = QColor(255, 0, 0)
        self.fg_color = None      # None = 无活动文档
        self.bg_color = None
        self.setToolTip(i18n.t(
            "上：当前拾色器颜色　左下：Krita 前景色　右下：Krita 背景色",
            "Top: current picker color  ·  Bottom-left: Krita foreground  ·  Bottom-right: Krita background"))

    def set_picker_color(self, qcolor):
        self.picker_color = QColor(qcolor)
        self.update()

    def set_fg_color(self, qcolor):
        self.fg_color = QColor(qcolor) if qcolor is not None else None
        self.update()

    def set_bg_color(self, qcolor):
        self.bg_color = QColor(qcolor) if qcolor is not None else None
        self.update()

    def _cells(self):
        """三块直接接壤：上整行，下左 / 下右各半。"""
        w = float(max(1, self.width()))
        top = QRectF(0.0, 0.0, w, TOP_H)
        half = w / 2.0
        bl = QRectF(0.0, TOP_H, half, BOTTOM_H)
        br = QRectF(half, TOP_H, w - half, BOTTOM_H)
        return [(top, self.picker_color), (bl, self.fg_color), (br, self.bg_color)]

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        font = QFont(self.font())
        font.setPointSizeF(6.5)
        p.setFont(font)
        for rect, color in self._cells():
            if color is None:
                p.fillRect(rect, QColor(64, 64, 68))
                continue
            p.fillRect(rect, color)
            fg = QColor(0, 0, 0, 210) if color.lightness() > 128 else QColor(255, 255, 255, 215)
            p.setPen(fg)
            p.drawText(rect.adjusted(4.0, 0.0, -3.0, -1.0),
                       Qt.AlignLeft | Qt.AlignVCenter, color.name().upper())


    def _copy(self, color):
        if color is None:
            return
        try:
            QApplication.clipboard().setText(color.name().upper())
        except Exception:
            pass

    def mousePressEvent(self, event):
        """点色块 = 复制其 HEX。"""
        if event.button() != Qt.LeftButton:
            event.ignore()
            return
        for rect, color in self._cells():
            if rect.contains(event.localPos()):
                self._copy(color)
                event.accept()
                return
        event.ignore()


CUR_MIN_W = 24      # 当前色小色块最小宽度（宽度自适应、吃满数值行右侧余量）
CUR_H = 24          # 当前色小色块初始高度（面板随后按 HEX 框高度校正）


class CurrentColorSwatch(QWidget):
    """当前选色小色块：**宽度自适应**（吃满数值行右侧余量）、高度与 HEX 数值框一致。

    面板把它放在数值行 HEX 数值框右边（那一行右侧的留白），替代旧的三色块控件；
    点一下复制其 HEX。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumWidth(CUR_MIN_W)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(CUR_H)
        self.setContextMenuPolicy(Qt.NoContextMenu)
        self.color = QColor(255, 0, 0)
        self._sync_tip()

    def set_color(self, qcolor):
        """设置当前色（None = 未知，画灰色）。"""
        if qcolor is None:
            self.color = None
        else:
            self.color = QColor(qcolor)
        self._sync_tip()
        self.update()

    def hex_text(self):
        return "--" if self.color is None else self.color.name().upper()

    def sync_height(self, height):
        """按 HEX 数值框的实际高度校正自身高度（布局完成后由面板调用）。"""
        height = int(height)
        if height > 0 and height != self.height():
            self.setFixedHeight(height)

    def _sync_tip(self):
        self.setToolTip(i18n.t("当前选色 %s（点击复制 HEX）",
                               "Current color %s (click to copy HEX)") % self.hex_text())

    def _border_color(self):
        try:
            color = QApplication.palette().mid().color()
            if color.isValid():
                return color
        except Exception:
            pass
        return QColor(115, 115, 120)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        if self.color is None:
            p.fillRect(self.rect(), QColor(64, 64, 68))
        else:
            p.fillRect(self.rect(), self.color)
        p.setPen(self._border_color())
        p.drawRect(0, 0, self.width() - 1, self.height() - 1)

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton or self.color is None:
            event.ignore()
            return
        try:
            QApplication.clipboard().setText(self.color.name().upper())
        except Exception:
            pass
        event.accept()
