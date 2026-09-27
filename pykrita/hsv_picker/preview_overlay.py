# -*- coding: utf-8 -*-
"""预览浮层：100×150 的独立小窗，显示三个**纯色方块**（没有任何文字）。

对齐 Krita 自带拾色器右上角那份预览：

  +-----------+-----------+   上格 100×100 = 当前选色（实时）
  |   当前选色（100×100） |   三格**直接接壤**：无间隙、无分隔线、**无任何边框**
  +-----+-----+-----+-----+   （窗口本身也是无边框窗口）
  | 上一次选色 | 上上次选色 |   下排两格各 50×50：左 = 上一次（history[0]）
  +-----+-----+-----+-----+                    右 = 上上次（history[1]）
                               浮层总尺寸 100×150（历史不足时该格画中灰）

为什么不用 Krita 的 ``LastColorHistory``（画布历史）：实测它**只在退出 Krita 时落盘**
（会话中途画几笔不写盘，退出后才更新），会话中拿不到，所以下排两格一律取自本插件
自己的历史列表（实时、无外部依赖）。

窗口特性（Qt5）：
  · Qt.Tool | FramelessWindowHint | WindowStaysOnTopHint | WindowDoesNotAcceptFocus；
    WA_ShowWithoutActivating + WA_TransparentForMouseEvents + NoFocus —— 不抢焦点、不吃鼠标、不进任务栏；
  · show_near(anchor)：默认**紧贴**锚点**右侧**（间隙 0）、顶部对齐，放不下依次翻到 左 -> 下 -> 上，最后夹回屏幕内；
    位置没变就不 move()（面板侧每 150ms 重锚定一次，见 HsvPickerPanel._preview_follow_tick）；
  · hide_after(ms)：单次倒计时（可重置），到点**直接隐藏**（不做淡出动画）；拖动期间应调用 cancel_hide()。
"""

from PyQt5.QtCore import QPoint, QRect, QRectF, Qt, QTimer
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtWidgets import QApplication, QWidget

try:                        # 插件内：包内相对导入
    from . import i18n
except ImportError:         # 离线单测：直接把本目录加进 sys.path
    import i18n

W = 100             # 浮层宽
H = 150             # 浮层总高（对齐 Krita 自带预览的 100×150）
TOP_H = 100         # 上格：100×100 正方形（当前选色）
BOT_H = 50          # 下排：两个 50×50 正方形（100 + 50 = 150）
GAP = 0             # 与锚点的间隙（px）：0 = 紧贴面板边缘（贴右/左/上/下都在面板之外）

EMPTY = QColor(105, 105, 110)      # 没有数据的那一格：中灰


def _rgb(value):
    """任意 3 元序列 -> (r, g, b) 0~255 整数；None / 坏数据返回 None。"""
    if value is None:
        return None
    try:
        r, g, b = (int(round(float(v))) for v in tuple(value)[:3])
    except Exception:
        return None
    return (max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)))


class PreviewOverlay(QWidget):
    """三个纯色方块的预览小窗（无文字；常驻对象，反复 show/hide）。"""

    def __init__(self, parent=None):
        flags = (Qt.Tool | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint
                 | Qt.WindowDoesNotAcceptFocus)
        super().__init__(parent, flags)
        self.setAttribute(Qt.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(W, H)
        self.setWindowTitle(i18n.t("馍馍拾色器预览", "Momo picker preview"))
        self.current_rgb = None      # 上格：当前选色
        self.older_rgb = None        # 右下：上上次选色（历史 colors[1]）
        self.last_rgb = None         # 左下：上一次选色（历史 colors[0]）
        self.hide_ms = 2000          # 默认倒计时（松手后计时；面板按模式传 1000/2000/0）
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)     # 到点直接隐藏，不做淡出

    # ------------------------------------------------------------ 内容
    def colors(self):
        """当前三格取值 (current, older, last)，均为 (r,g,b) 或 None。"""
        return (self.current_rgb, self.older_rgb, self.last_rgb)

    def show_colors(self, current_rgb, older_rgb, last_picked_rgb):
        """更新三格并显示（不抢焦点、不启动倒计时）。"""
        self.current_rgb = _rgb(current_rgb)
        self.older_rgb = _rgb(older_rgb)
        self.last_rgb = _rgb(last_picked_rgb)
        self.update()
        self._show_passive()
        return self.colors()

    def flash(self, ms=None):
        """按当前三格显示 + 重置倒计时（用于「不改色也弹出」的场合）。"""
        self.update()
        self._show_passive()
        self.hide_after(ms)

    def _show_passive(self):
        """显示且不激活、不改变焦点。

        首次 show 已经因 WindowStaysOnTopHint 位于顶层，无需再 raise_（省一次
        ~1ms 平台调用）；后续刷新仍 raise_，保持浮层在其它窗口之上。
        """
        if not self.isVisible():
            self.show()
            return
        try:
            self.raise_()
        except Exception:
            pass

    # ------------------------------------------------------------ 倒计时（到点直接隐藏，无淡出）
    def hide_after(self, ms=None):
        """重置（单次）倒计时；到点**直接隐藏**。拖动期间不要调用本方法。"""
        delay = int(self.hide_ms if ms is None else ms)
        if delay <= 0:
            self.hide_now()
            return
        self._timer.start(delay)

    def cancel_hide(self):
        """取消倒计时（拖动中 / 「一直显示」模式调用：不隐藏）。"""
        self._timer.stop()

    def hide_now(self):
        """立刻隐藏（取消失效倒计时）。"""
        self._timer.stop()
        self.hide()

    def countdown_active(self):
        return bool(self._timer.isActive())

    # ------------------------------------------------------------ 定位
    def screen_geometry(self, point):
        """包含 point 的屏幕可用区；取不到时退回 QApplication.desktop()（Qt5）。"""
        screen = None
        try:
            screen = QApplication.screenAt(point)
        except Exception:
            screen = None
        if screen is not None:
            try:
                return screen.availableGeometry()
            except Exception:
                pass
        try:
            return QApplication.desktop().availableGeometry()
        except Exception:
            return QRect(0, 0, 1920, 1080)

    def show_near(self, anchor_global_rect, gap=GAP):
        """贴锚点放置：右 -> 左 -> 下 -> 上，最后夹进屏幕可用区；返回落点 (x, y)。"""
        anchor = QRect(anchor_global_rect)
        avail = self.screen_geometry(anchor.center())
        gap = int(gap)
        w, h = self.width(), self.height()
        if anchor.right() + 1 + gap + w <= avail.right() + 1:
            x, y = anchor.right() + 1 + gap, anchor.top()
        elif anchor.left() - gap - w >= avail.left():
            x, y = anchor.left() - gap - w, anchor.top()
        elif anchor.bottom() + 1 + gap + h <= avail.bottom() + 1:
            x, y = anchor.left(), anchor.bottom() + 1 + gap
        else:
            x, y = anchor.left(), anchor.top() - gap - h
        x = max(avail.left(), min(int(x), avail.right() - w + 1))
        y = max(avail.top(), min(int(y), avail.bottom() - h + 1))
        if self.pos() != QPoint(x, y):
            self.move(x, y)
        return (x, y)

    # ------------------------------------------------------------ 绘制
    def cell_rects(self):
        """三格矩形 + 对应颜色（相邻无间隙：上整行、下排左右各半）。"""
        w = float(self.width())
        half = w / 2.0
        return [(QRectF(0.0, 0.0, w, TOP_H), self.current_rgb),
                (QRectF(0.0, TOP_H, half, BOT_H), self.last_rgb),        # 左下 = 上一次
                (QRectF(half, TOP_H, w - half, BOT_H), self.older_rgb)]  # 右下 = 上上次

    def paintEvent(self, event):
        """只填三个色块：无文字、无边框、无分隔线（三格直接接壤）。"""
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        for rect, rgb in self.cell_rects():
            if rgb is None:
                self._paint_empty(p, rect)
            else:
                p.fillRect(rect, QColor(rgb[0], rgb[1], rgb[2]))

    def _paint_empty(self, p, rect):
        """没有数据的那一格：中灰（不画任何文字）。"""
        p.fillRect(rect, EMPTY)
