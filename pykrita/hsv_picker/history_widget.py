# -*- coding: utf-8 -*-
"""历史颜色网格：单列、格子 16×16、行数自适应高度（与拾色器等高）。

数据是纯 Python 列表（`["#RRGGBB", ...]`），由面板负责持久化与增删，
控件只负责画格子 + 点击回调。
"""

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtWidgets import QWidget

try:                        # 插件内：包内相对导入
    from . import i18n
except ImportError:         # 离线单测：直接把本目录加进 sys.path
    import i18n

CELL = 16          # 格子边长（px）
WIDTH = 16         # 单列


class HistoryWidget(QWidget):
    def __init__(self, parent=None, on_pick=None):
        super().__init__(parent)
        self.setFixedWidth(WIDTH)
        self.setMinimumHeight(CELL)
        self.colors = []                 # ["#RRGGBB", ...]，按可见行数截断
        self._on_pick = on_pick
        self.setToolTip(i18n.t("历史颜色：单击取用", "History colors: click to use"))
        self.setContextMenuPolicy(Qt.NoContextMenu)

    # ---- 行数随高度自适应 ----
    def rows(self):
        return max(1, int(self.height() // CELL))

    def capacity(self):
        return self.rows()

    MAX_KEEP = 128     # 模型里最多保留 128 个（显示几个由高度决定）

    def set_colors(self, colors):
        self.colors = list(colors)[:self.MAX_KEEP]
        self.update()

    def _cells(self):
        out = []
        for i, hex_text in enumerate(self.colors):
            out.append((QRectF(0.0, i * CELL, CELL, CELL), hex_text))
        return out

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        for i in range(self.rows()):
            rect = QRectF(0.0, i * CELL, CELL, CELL)
            if i >= len(self.colors):
                p.fillRect(rect, QColor(52, 52, 56))
                continue
            # R16：16×16 纯色直接接壤，不画 1px 描边
            p.fillRect(rect, QColor(self.colors[i]))

    def mousePressEvent(self, event):
        if event.button() != Qt.LeftButton:
            event.ignore()
            return
        idx = int(event.localPos().y() // CELL)
        if 0 <= idx < len(self.colors) and self._on_pick is not None:
            self._on_pick(self.colors[idx])
        event.accept()
