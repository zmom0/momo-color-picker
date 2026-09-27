# -*- coding: utf-8 -*-
"""两条横向色条：明度条（左=0）与彩度条（左=0，线性坐标）。

· 明度条：横向渐变 = 当前色相下沿「等明度线」变化的灰阶/彩色过渡，
  左端为 L 最小、右端为 L 最大；拖动设定目标明度（内部用 _lbar_* 映射）。
· 彩度条：坐标**线性**（相对模式 = C_rel，绝对模式 = C / 量程上界），
  左端 0、右端满量程；拖动设定当前口径对应的彩度值。
"""

import numpy as np
from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QImage, QPainter, QPen
from PyQt5.QtWidgets import QWidget

try:
    from . import i18n
    from . import keymap_core as kmc
    from . import math_core as mc
except ImportError:
    import i18n
    import keymap_core as kmc
    import math_core as mc

STRIP_H = 22

# 键表不支持的 Qt 修饰位（Meta / Keypad / GroupSwitch 等）：出现即落回「无修饰」行
_UNKNOWN_QT_MODS = (Qt.MetaModifier | Qt.KeypadModifier
                    | getattr(Qt, "GroupSwitchModifier", 0))


class StripBase(QWidget):
    """横向色条基类：**左 0 右满量程**，拖动/点击用绝对位置。

    哪个鼠标键 / 修饰键能拖动由自定义按键表决定（区域 = AREA）。
    """

    AREA = None

    def __init__(self, parent=None, on_changed=None, on_press=None, on_release=None):
        super().__init__(parent)
        self._on_press = on_press
        self._on_release = on_release
        self.setFixedHeight(STRIP_H)
        self.setMinimumWidth(120)
        self.setCursor(Qt.SizeHorCursor)
        self.value = 0.0            # 归一化位置（0=最左，1=最右）
        self._on_changed = on_changed
        self._dragging = False
        self._press_button = Qt.LeftButton
        self.keymap = kmc.default_keymap()      # 自定义按键表
        self.setContextMenuPolicy(Qt.NoContextMenu)

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
        return kmc.lookup(self.keymap, self.AREA, self._btn_id(btn), mod)

    # ---- 子类实现 ----
    def strip_image(self, width):
        """返回 uint8 RGB (STRIP_H, width, 3)。"""
        raise NotImplementedError

    def text_for(self, t):
        """归一化位置 -> 显示文本。"""
        return "%.4f" % t

    # ---- 通用绘制 ----
    def dead_mask(self, width):
        """返回布尔数组：True 处表示「该位置当前拖不到」；默认无死区（返回 None）。"""
        return None

    def _paint_dead(self, p, w):
        """把不可达区段画成「半透明灰底 + 斜纹」（a/b 条与绝对彩度条的死区共用）。"""
        dead = self.dead_mask(w)
        if dead is None:
            return
        idx = np.flatnonzero(np.asarray(dead, dtype=bool))
        if idx.size == 0:
            return
        spans = []
        start = prev = int(idx[0])
        for raw in idx[1:]:
            i = int(raw)
            if i != prev + 1:
                spans.append((start, prev))
                start = i
            prev = i
        spans.append((start, prev))
        p.setRenderHint(QPainter.Antialiasing, False)
        for a0, b0 in spans:
            x0, x1 = float(a0), float(b0) + 1.0
            p.fillRect(QRectF(x0, 0.0, x1 - x0, float(STRIP_H)), QColor(58, 58, 58, 165))
            p.setPen(QPen(QColor(150, 150, 150, 120), 1.0))
            x = x0 - STRIP_H
            while x < x1:
                p.drawLine(QPointF(max(x, x0), float(STRIP_H) - 1.0),
                           QPointF(min(x + STRIP_H, x1), 0.0))
                x += 6.0

    def paintEvent(self, event):
        w = max(2, self.width())
        arr = self.strip_image(w)
        from PyQt5.QtGui import QImage
        arr = np.ascontiguousarray(arr, dtype=np.uint8)
        img = QImage(arr.data, w, STRIP_H, w * 3, QImage.Format_RGB888)
        p = QPainter(self)
        p.drawImage(0, 0, img)
        self._paint_dead(p, w)
        p.setPen(QPen(QColor(20, 20, 20, 160), 1))
        p.drawRect(0, 0, w - 1, STRIP_H - 1)
        # 游标
        x = self.value * (w - 1)
        for pen, dy in ((QPen(QColor(0, 0, 0, 200), 3), 0), (QPen(QColor(255, 255, 255, 235), 1.6), 0)):
            p.setPen(pen)
            p.drawLine(QPointF(x, 1.0), QPointF(x, STRIP_H - 1.0))
        return

    # ---- 交互 ----
    def _apply(self, pos):
        w = max(1, self.width())
        self.value = mc.clamp(pos.x() / float(w), 0.0, 1.0)
        self.update()
        if self._on_changed is not None:
            self._on_changed(self.value)

    def mousePressEvent(self, event):
        if event.button() not in (Qt.LeftButton, Qt.MiddleButton, Qt.RightButton):
            event.ignore()
            return
        if self._action_for(event.button(), event.modifiers()) == "none":
            event.ignore()
            return
        self._dragging = True
        self._press_button = event.button()
        if self._on_press is not None:
            self._on_press()
        self._apply(event.localPos())
        event.accept()

    def mouseMoveEvent(self, event):
        if self._dragging and (event.buttons() & self._press_button):
            self._apply(event.localPos())
            event.accept()

    def mouseReleaseEvent(self, event):
        self._dragging = False
        if self._on_release is not None:
            self._on_release()
        event.accept()

    def set_value(self, t):
        self.value = mc.clamp(float(t), 0.0, 1.0)
        self.update()


class LightnessStrip(StripBase):
    """明度条：横向 = 当前色相在 L 轴上的取样（左暗右亮）。"""

    AREA = "lstrip"

    def __init__(self, parent=None, on_changed=None, metric="oklab",
                 on_press=None, on_release=None):
        super().__init__(parent, on_changed, on_press, on_release)
        self.metric = metric
        self.hue = 0.0
        self._cache_key = None
        self._cache = None

    def set_hue(self, hue):
        if abs(hue - self.hue) > 0.5:
            self.hue = float(hue)
            self._cache_key = None
            self.update()

    def strip_image(self, width):
        key = (width, round(self.hue / 4.0), self.metric)
        if self._cache is not None and self._cache_key == key:
            return self._cache
        t = np.linspace(0.0, 1.0, width)
        # 线性档：位置 f 与指标明度线性对应（_lbar_* 是标量接口，这里向量化实现同口径）
        # oklab / gray 都是 0~1；只有旧 CIE Lab（lab）是 0~100
        lmax = 1.0 if self.metric in ("oklab", "gray") else 100.0
        # 需求：明度条必须是左侧黑 -> 右侧白的灰阶，不带任何色相
        L = t * lmax
        v = mc.v_from_lightness(self.metric, L)
        rgb = np.repeat(v[:, None], 3, axis=1)
        self._cache = (np.clip(rgb, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
        self._cache = np.repeat(self._cache[None, :, :], STRIP_H, axis=0)
        self._cache_key = key
        return self._cache

    def text_for(self, t):
        L = float(t) * (1.0 if self.metric in ("oklab", "gray") else 100.0)
        return "%.4f" % L if self.metric in ("oklab", "gray") else "%.2f" % L


class ChromaStrip(StripBase):

    AREA = "cstrip"
    """彩度条：**线性坐标**（相对模式 = C_rel，绝对模式 = C / 量程上界）。

    · mode="rel"：横向量程固定 [0, 1]，值 = 相对彩度 C_rel = C / C_max(L, h)。
    · mode="abs"：值 = 绝对彩度 C（= √(a²+b²)，Oklab 口径）。
        full=False（默认）：量程固定 [0, C_ABS_LIM]，超出 C_max(L, h) 的段画**死区斜纹**，
                            拖到底即停（值钳在可达区间）；
        full=True        ：量程动态 [0, C_max(L, h)]，满量程永远可达、无死区，
                            代价是刻度随颜色变。
    坐标一律线性（t = 值 / 量程上界）——旧版把位置放在「等明度线弧长」上，
    拖动明度时游标会漂 3.6%~12.7%；线性后位置只跟显示值走。
    """

    def __init__(self, parent=None, on_changed=None, on_press=None, on_release=None):
        super().__init__(parent, on_changed, on_press, on_release)
        self.hue = 0.0
        self.target_l = 0.5
        self.metric = "oklab"       # L 轴口径（oklab / gray），由面板灌入
        self.mode = "rel"
        self.full = False
        self._cache_key = None
        self._cache = None
        self._ctx_key = None
        self._curve_cache = None
        self.setToolTip(i18n.t(
            "彩度条：拖动改彩度（明度不动）。默认相对彩度 C_rel（0~1）；可切成绝对彩度 C",
            "Chroma strip: drag to change chroma (lightness stays). Default is relative chroma "
            "C_rel (0-1); can switch to absolute chroma C"))

    # ---- 上下文与口径 ----
    def set_context(self, hue, target_l):
        # R27：key 带 metric —— 否则同 (hue, L) 在不同口径下会命中旧曲线缓存
        key = (round(hue / 2.0), round(float(target_l), 3), self.metric)
        if key != self._ctx_key:
            self.hue = float(hue)
            self.target_l = float(target_l)
            self._ctx_key = key
            self._cache_key = None
            self._curve_cache = None
            self.update()

    def set_mode(self, mode, full=False):
        """口径：mode = "rel" / "abs"；full 仅绝对口径有用（满量程 = C_max(L,h)）。"""
        mode = "abs" if str(mode) == "abs" else "rel"
        full = bool(full)
        if mode != self.mode or full != self.full:
            self.mode = mode
            self.full = full
            self._cache_key = None
            self.update()

    def set_metric(self, metric):
        """设置 L 轴口径（oklab / gray）：清缓存并重算（C 仍是 Oklab 绝对彩度）。"""
        metric = "gray" if str(metric) == "gray" else "oklab"
        if metric != self.metric:
            self.metric = metric
            self._cache_key = None
            self._curve_cache = None
            self.update()

    def _cmax_now(self):
        """当前 (hue, target_l) 下的 C_max（绝对彩度上界），异常时退回 0。"""
        try:
            arr = mc.cmax_of_L(self.hue, self.metric, np.array([float(self.target_l)]))
            return float(np.asarray(arr, dtype=np.float64).reshape(-1)[0])
        except Exception:
            return 0.0

    def range_hi(self):
        """显示量程上界（相对模式恒 1.0）。"""
        if self.mode == "rel":
            return 1.0
        if self.full:
            return self._cmax_now()
        return float(mc.C_ABS_LIM)

    def value_of_t(self, t):
        """归一化位置 -> 显示值（相对模式 = C_rel；绝对模式 = C，已钳进可达区间）。"""
        t = mc.clamp(float(t), 0.0, 1.0)
        if self.mode == "rel":
            return t
        v = t * self.range_hi()
        if not self.full:
            v = min(v, self._cmax_now())      # 固定量程：死区里拖不动
        return v

    def t_of(self, value):
        """显示值 -> 归一化位置（与 value_of_t 互逆，供面板摆游标）。"""
        hi = self.range_hi()
        if hi < 1e-12:
            return 0.0
        return mc.clamp(float(value) / hi, 0.0, 1.0)

    # ---- 绘制 ----
    def _curve_data(self):
        """当前 (hue, target_l) 的等明度曲线采样：(S, V, 绝对 C)，按 C 单调递增。"""
        if self._curve_cache is None:
            try:
                ss, vv = mc.iso_lightness_curve(self.hue, self.target_l, self.metric,
                                                       n_v=129, iters=30)
            except Exception:
                ss, vv = np.array([]), np.array([])
            if len(ss) >= 2:
                cc = np.asarray(mc.ok_L_C(self.hue, ss, vv)[1], dtype=np.float64)
                cc = np.maximum.accumulate(np.clip(cc, 0.0, None))
                self._curve_cache = (np.asarray(ss, dtype=np.float64),
                                     np.asarray(vv, dtype=np.float64), cc)
            else:
                self._curve_cache = False
        return self._curve_cache if self._curve_cache else None

    def strip_image(self, width):
        width = int(max(2, width))
        key = (width, round(self.hue, 3), round(self.target_l, 4), self.mode,
               self.full, self.metric)
        if self._cache is not None and self._cache_key == key:
            return self._cache
        t = np.linspace(0.0, 1.0, width)
        rgb = np.zeros((width, 3), dtype=np.float64)
        data = self._curve_data()
        if data is not None:
            ss, vv, cc = data
            if self.mode == "rel":
                vals = t * self._cmax_now()          # t = C_rel -> 绝对 C
            else:
                vals = t * self.range_hi()           # 绝对模式：固定量程 / 满量程
            s_x = np.interp(vals, cc, ss)
            v_x = np.interp(vals, cc, vv)
            rgb = mc.hsv_to_srgb(np.full_like(t, self.hue), s_x, v_x)
        arr = (np.clip(rgb, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
        self._cache = np.repeat(arr[None, :, :], STRIP_H, axis=0)
        self._cache_key = key
        return self._cache

    def dead_mask(self, width):
        """绝对 + 固定量程：位置值 > C_max(L,h) 的段是死区（拖动会被钳住）。"""
        if self.mode != "abs" or self.full:
            return None
        width = int(max(2, width))
        vals = np.linspace(0.0, 1.0, width) * float(mc.C_ABS_LIM)
        return vals > (self._cmax_now() + 1e-9)

    def text_for(self, t):
        return "%.4f" % self.value_of_t(t)

    # ---- 交互：值与位置不是同一个数，覆写 _apply ----
    def _apply(self, pos):
        w = max(1, self.width())
        t = mc.clamp(pos.x() / float(w), 0.0, 1.0)
        value = self.value_of_t(t)
        self.value = self.t_of(value)        # 游标画在「钳后」的位置
        self.update()
        if self._on_changed is not None:
            self._on_changed(value)


class AbStrip(StripBase):
    """Oklab a / b 分量条（横向 = 固定 L 与另一个分量，扫本分量）。

    · mode="box"  ：量程 = 当前明度的切片包围盒。刻度只随 L 变（拖动时两把刻度都不抖），
                    代价是「另一个分量越界」的那一段拖了不变色 —— 画成灰色斜纹，
                    并且拖到底就停（值被钳在可达区间里）。
    · mode="line" ：量程 = 固定另一个分量后的可行区间。满量程永远可达，刻度随另一分量变。

    一条的「游标位置」= 本分量在**显示量程**里的归一化位置；可达区间由 ranges()[1] 给出。
    """

    def __init__(self, parent=None, axis="a", mode="box",
                 on_changed=None, on_press=None, on_release=None):
        super().__init__(parent, on_changed, on_press, on_release)
        self.axis = "a" if axis == "a" else "b"
        self.AREA = "astrip" if self.axis == "a" else "bstrip"
        self.mode = mode if mode in ("box", "line") else "box"
        self.L = 0.5
        self.a = 0.0
        self.b = 0.0
        self._ctx_key = None
        self._cache = None
        self._cache_key = None
        self.setToolTip(i18n.t(
            "Oklab %s 分量：拖动改本分量（明度与另一个分量不动）；灰色斜纹段当前不可达",
            "Oklab %s component: drag to change it (L and the other component stay);"
            " hatched spans are unreachable at this color") % self.axis)

    # ---- 上下文 ----
    def set_context(self, L, a, b):
        """由面板在颜色变化时调用：更新 L / a / b 并刷新游标位置。"""
        key = (round(float(L), 4), round(float(a), 4), round(float(b), 4), self.mode)
        if key != self._ctx_key:
            self._ctx_key = key
            self.L, self.a, self.b = float(L), float(a), float(b)
            self._cache = None
            self.update()
        self.value = self.t_of(self.component())

    def set_mode(self, mode):
        if mode in ("box", "line") and mode != self.mode:
            self.mode = mode
            self._ctx_key = None
            self._cache = None
            self.update()

    def component(self):
        return self.a if self.axis == "a" else self.b

    def ranges(self):
        """(显示量程, 可达区间)。可达区间 ⊆ 显示量程；两者相等即无死区。"""
        disp = mc.ab_strip_range(self.L, self.a, self.b, self.axis, self.mode)
        live = mc.ab_strip_range(self.L, self.a, self.b, self.axis, "line")
        return disp, live

    def t_of(self, value):
        lo, hi = self.ranges()[0]
        if hi - lo < 1e-12:
            return 0.0
        return mc.clamp((float(value) - lo) / (hi - lo), 0.0, 1.0)

    def value_of_t(self, t):
        """归一化位置 -> 分量值（已钳进可达区间，保证不出 sRGB 色域）。"""
        disp, live = self.ranges()
        v = disp[0] + mc.clamp(float(t), 0.0, 1.0) * (disp[1] - disp[0])
        return mc.clamp(v, live[0], live[1])

    # ---- 绘制 ----
    def strip_image(self, width):
        width = int(max(2, width))
        key = (width, round(self.L, 4), round(self.a, 4), round(self.b, 4), self.mode)
        if self._cache is not None and self._cache_key == key:
            return self._cache
        lo, hi = self.ranges()[0]
        vals = lo + np.linspace(0.0, 1.0, width) * (hi - lo)
        if self.axis == "a":
            a, b = vals, np.full_like(vals, self.b)
        else:
            a, b = np.full_like(vals, self.a), vals
        rgb = mc.oklab_to_srgb(self.L, a, b)
        arr = (np.clip(rgb, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
        self._cache = np.repeat(arr[None, :, :], STRIP_H, axis=0)
        self._cache_key = key
        return self._cache

    def dead_mask(self, width):
        if self.mode == "line":
            return None                      # 满量程恒可达
        disp, live = self.ranges()
        vals = disp[0] + np.linspace(0.0, 1.0, int(max(2, width))) * (disp[1] - disp[0])
        return (vals < live[0] - 1e-9) | (vals > live[1] + 1e-9)

    def text_for(self, t):
        return "%+.4f" % self.value_of_t(t)

    # ---- 交互：值域不是 0~1，覆写 _apply ----
    def _apply(self, pos):
        w = max(1, self.width())
        t = mc.clamp(pos.x() / float(w), 0.0, 1.0)
        value = self.value_of_t(t)
        self.value = self.t_of(value)        # 游标画在「钳后」的位置
        self.update()
        if self._on_changed is not None:
            self._on_changed(value)
