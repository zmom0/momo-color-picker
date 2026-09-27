# -*- coding: utf-8 -*-
"""自绘 HSV 拾色器控件：色相环（外圈）+ S/V 方块 + 两族轨迹线。

方位：0° 红在 9 点钟，色相顺时针递增（不要改）。
几何：方块半边长 = 短边 × 0.286，环内半径 = 方块半边长 × √2（方块四角顶内圈）。
Qt5：鼠标坐标用 event.localPos()。

交互（v4：动作由**自定义按键表** keymap_core 决定，见「按键功能」对话框；默认值 v7 R23）：
  · 环上：默认左键 = 绝对角度转色相 + 锁明度 + 锁**相对彩度 C_rel**；中键 / 右键 =
    绝对角度 + 锁明度 + 锁绝对彩度 C，目标色相够不到 C 时把色相
    **钳到最近的可达边界**；Shift+左键 = 纯 HSV（只改色相，S / V 原样不动）
  · 方块内：左键绝对定位；中键默认改明度（相对）、右键默认改彩度（相对）；
    Shift+左键 = 只改 S、Alt+左键 = 只改 V（都是键表里的默认输入行）
  · 键表把「修饰键 + 鼠标键」映射到动作；没配的修饰键组合落回该键的「无修饰」行
"""

import math

import numpy as np
from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QFont, QImage, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PyQt5.QtWidgets import QWidget

try:                        # 插件内：包内相对导入
    from . import debug_log as dlog
    from . import keymap_core as kmc
    from . import math_core as mc
    from . import render as rd
except ImportError:         # 离线单测：直接把本目录加进 sys.path
    import debug_log as dlog
    import keymap_core as kmc
    import math_core as mc
    import render as rd

HUE_BUCKET = 2.0           # 方块位图的色相分桶（度）
CLUSTER_HUE_BUCKET = 15.0  # 线簇缓存的色相分桶（度）
CLUSTER_STEP = 0.1         # 两族簇的步进

# 键表不支持的 Qt 修饰位（Meta / Keypad / GroupSwitch 等）：出现即落回「无修饰」行
_UNKNOWN_QT_MODS = (Qt.MetaModifier | Qt.KeypadModifier
                    | getattr(Qt, "GroupSwitchModifier", 0))


def cluster_pen_width(target):
    """线簇线宽：50% 的簇线略粗（1.5），其余 1.0。"""
    return 1.5 if abs(float(target) - 0.5) < 1e-6 else 1.0


def cluster_line_styles(base_rgba, target):
    """某条簇线的绘制样式列表 [(rgba, width), ...]。

    50% 簇线两族共用同一**轻微**高亮色（中性浅灰、单笔 1.5px），只比普通簇线略明显；
    其余簇线保持各族原色 1.0px。
    """
    if abs(float(target) - 0.5) < 1e-6:
        return [((205, 205, 205, 190), 1.5)]
    return [(base_rgba, cluster_pen_width(target))]


class HsvPickerCanvas(QWidget):
    """颜色改变时发出 color_changed()，由面板负责联动前景色。

interaction_started / interaction_finished：面板用来标记一次拾色操作的起止
（预览浮层据此判断「拖动中不倒计时、松手后才开始倒计时」）。"""

    interaction_started = pyqtSignal()
    interaction_finished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(180, 180)
        self.setMouseTracking(False)
        self.setContextMenuPolicy(Qt.NoContextMenu)
        self._last_heavy = 0.0          # 60Hz 节流用
        self._through_cache = None      # 过点线缓存（同一颜色重复绘制不重算）
        self._through_key = None

        self.h = 0.0
        self.s = 1.0
        self.v = 1.0
        self.metric = "oklab"
        self.show_clusters = True
        self.show_lines = True
        self.show_unreachable = True       # 色环「不可达色相」细斜纹（只画线、不填灰底；默认开）
        self.keymap = kmc.default_keymap()  # 自定义按键表（面板会灌入用户表）

        self.chk_l = False          # 复选框来的常驻锁
        self.chk_c = False
        self.btn_l = False          # 中/右键按压带来的临时锁
        self.btn_c = False
        self.lock_l = False         # 生效锁 = chk OR btn
        self.lock_c = False
        self.target_l = None
        self.target_crel = None
        self.target_cabs = None     # 环上右键「锁 L + 锁绝对 C」的 C 目标

        self._press_pos = None
        self._press_area = None
        self._press_sv = None
        self._press_h = None
        self._drag_mode = None          # absolute / axis / ring_hue_hsv / ring_crel /
                                        # ring_lc / rel_mid / rel_right
        self._axis_lock = None          # "s" / "v"
        self._square_cache = None
        self._square_cache_key = None
        self._ring_cache = None
        self._ring_cache_size = None
        self._cluster_cache = None
        self._cluster_cache_key = None
        self._unreachable_cache = None      # 不可达色相弧缓存（按当前 L/C）
        self._unreachable_key = None

    def set_show_unreachable(self, flag):
        """显示/隐藏色环「不可达色相」提示（30% 灰底 + 细斜纹；只影响观感，不改命中判定）。"""
        self.show_unreachable = bool(flag)
        self._unreachable_cache = None
        self._unreachable_key = None
        self.update()

    def set_metric(self, metric):
        """设置「明度标准」（oklab / gray）：只换 L 轴口径，C 仍是 Oklab 绝对彩度。

        与 L 有关的三类缓存必须清掉（过点线 / 线簇 / 不可达弧）；另外若拖动中冻结了
        过点线快照，切口径后旧快照就过期了，一并解冻（下帧按新口径实时重算）。
        方块位图只依赖色相，不动。
        """
        metric = "gray" if str(metric) == "gray" else "oklab"
        if metric != self.metric:
            self.metric = metric
            self._through_cache = None
            self._through_key = None
            self._cluster_cache = None
            self._cluster_cache_key = None
            self._unreachable_cache = None
            self._unreachable_key = None
            self._clear_frozen_lines()      # R27：不留旧口径的冻结过点线
            self.update()

    def set_color(self, h, s, v):
        """设定颜色。s≈0（灰轴）时保留上一次的色相，避免"拖到 S=0 色相归零"。"""
        s = mc.clamp(float(s), 0.0, 1.0)
        if s > 1e-6:
            self.h = float(h) % 360.0
        elif abs(float(h) % 360.0) > 1e-9:
            self.h = float(h) % 360.0
        self.s = s
        self.v = mc.clamp(float(v), 0.0, 1.0)
        self.update()

    def color_changed(self):
        """宿主（面板）覆盖：把颜色同步到 Krita 前景色。"""
        pass

    def set_locks(self, lock_l, lock_c):
        """由面板复选框设置**常驻锁**（左键拖动时会沿被锁定的曲线走）。"""
        self.chk_l = bool(lock_l)
        self.chk_c = bool(lock_c)
        self._refresh_locks()

    def _refresh_locks(self):
        """生效锁 = 复选框锁 OR 中/右键临时锁；并刷新锁定目标值。"""
        new_l = bool(self.chk_l or self.btn_l)
        new_c = bool(self.chk_c or self.btn_c)
        if new_l and not self.lock_l:
            self.target_l = self.locked_lightness()
        if not new_l:
            self.target_l = None
        if new_c and not self.lock_c:
            self.target_crel = self.locked_crel()
        if not new_c:
            self.target_crel = None
        self.lock_l, self.lock_c = new_l, new_c
        self.update()

    def _apply_absolute_locked(self, pos, area):
        """左键绝对定位；若有一把锁，则把落点投影到对应约束曲线上（两把锁则钉住）。"""
        if area == "ring":
            self.h = rd.hue_from_pos(self._geometry(), pos.x(), pos.y())
            return
        ss, vv = rd.sv_from_pos(self._geometry(), pos.x(), pos.y())
        if self.lock_l and self.lock_c:
            return                      # 0 自由度：钉住
        if not self.lock_l and not self.lock_c:
            self.s, self.v = ss, vv
            return
        curve = self.constraint_curve()
        if curve is None or len(curve) < 2:
            self.s, self.v = ss, vv
            return
        # 投影到曲线（按弧长找最近点）
        g = self._geometry()
        w = max(1.0, g["sq"][2] - g["sq"][0])
        pts = np.column_stack([g["sq"][0] + curve[:, 0] * w,
                               g["sq"][1] + (1.0 - curve[:, 1]) * w])
        px = g["sq"][0] + ss * w
        py = g["sq"][1] + (1.0 - vv) * w
        i = int(np.argmin((pts[:, 0] - px) ** 2 + (pts[:, 1] - py) ** 2))
        self.s = mc.clamp(float(curve[i, 0]), 0.0, 1.0)
        self.v = mc.clamp(float(curve[i, 1]), 0.0, 1.0)
        # 精修：锁彩度时固定 V 二分求精确 S（与 Tkinter 版同口径）
        if self.lock_c and not self.lock_l and self.target_crel is not None:
            try:
                self.s = mc.clamp(float(mc.solve_s_crel_scalar(
                    self.h, self.metric, self.v, self.target_crel)), 0.0, 1.0)
            except Exception:
                pass

    def set_show_clusters(self, checked):
        self.show_clusters = bool(checked)
        self.update()

    def set_show_lines(self, checked):
        self.show_lines = bool(checked)
        self.update()

    def _geometry(self):
        return rd.picker_geometry(self.width(), self.height())

    def _hit(self, pos):
        return rd.hit_area(self._geometry(), pos.x(), pos.y())

    def _sv_to_px(self, s, v):
        g = self._geometry()
        w = max(1.0, g["sq"][2] - g["sq"][0])
        return (g["sq"][0] + s * w, g["sq"][1] + (1.0 - v) * w)

    def _px_to_sv(self, x, y):
        g = self._geometry()
        w = max(1.0, g["sq"][2] - g["sq"][0])
        return (mc.clamp((x - g["sq"][0]) / w, 0.0, 1.0),
                mc.clamp(1.0 - (y - g["sq"][1]) / w, 0.0, 1.0))

    def _square_pixmap(self):
        g = self._geometry()
        size = max(2, int(round(g["half_sq"] * 2.0)))
        bucket = round(self.h / HUE_BUCKET) * HUE_BUCKET % 360.0
        if self._square_cache is not None and self._square_cache_key == (size, bucket):
            return self._square_cache
        self._square_cache = QPixmap.fromImage(
            rd.qimage_from_rgb(rd.render_square_array(bucket, size)))
        self._square_cache_key = (size, bucket)
        return self._square_cache

    def _ring_pixmap(self):
        """色相环位图：优先用预生成资源 assets/ring.png，缺失时回退实时渲染。"""
        side = min(max(1, self.width()), max(1, self.height()))
        if self._ring_cache is not None and self._ring_cache_size == side:
            return self._ring_cache
        g = self._geometry()
        img = None
        try:
            import os
            path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "ring.png")
            if os.path.isfile(path):
                from PyQt5.QtGui import QImage
                img = QImage(path)
        except Exception:
            img = None
        if img is None or img.isNull():
            img = rd.qimage_from_rgba(rd.render_ring_array(
                720, g["r_in"] / (side / 2.0), g["r_out"] / (side / 2.0), ss=1))
        self._ring_cache = QPixmap.fromImage(img).scaled(
            side, side, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self._ring_cache_size = side
        return self._ring_cache

    def _invalidate_clusters(self):
        self._cluster_cache = None
        self._cluster_cache_key = None

    def resizeEvent(self, event):
        self._square_cache = None
        self._square_cache_key = None
        self._ring_cache = None
        self._ring_cache_size = None
        self._invalidate_clusters()
        super().resizeEvent(event)

    def _clusters(self):
        """两族线簇；按色相 10° 桶 + 边长 + 指标缓存。返回 dict。"""
        g = self._geometry()
        key = (round(self.h / CLUSTER_HUE_BUCKET) * CLUSTER_HUE_BUCKET,
               int(round(g["half_sq"] * 2.0)), self.metric)
        if self._cluster_cache is not None and self._cluster_cache_key == key:
            return self._cluster_cache
        hue = float(self.h)
        n = int(round(1.0 / CLUSTER_STEP))
        targets = [CLUSTER_STEP * i for i in range(1, n)]
        data = {"iso": [], "crel": []}
        try:
            for tgt, ss, vv in mc.iso_lightness_curves(hue, targets, self.metric,
                                                       n_v=49, iters=20):
                if len(ss) >= 2:
                    data["iso"].append((float(tgt), ss, vv))
        except Exception:
            pass
        try:
            ax, rel = mc.crel_field(hue, self.metric, n=41)
            for i, (ss, vv) in enumerate(mc.crel_isoline_many(ax, rel, targets)):
                if len(ss) >= 2:
                    data["crel"].append((float(targets[i]), ss, vv))
        except Exception:
            pass
        self._cluster_cache = data
        self._cluster_cache_key = key
        return data

    def constraint_curve(self):
        """当前锁定的可滑动曲线：[(S,V), ...]；两把锁同时锁 -> None。"""
        if self.lock_l and self.lock_c:
            return None
        try:
            if self.lock_l:
                tgt = self.target_l if self.target_l is not None else self.locked_lightness()
                ss, vv = mc.iso_lightness_curve(self.h, tgt, self.metric, n_v=121, iters=28)
                # 等明度线在该色相下可能够不到更高 V（S=1 封顶），这里按 V 单调裁剪
                if len(vv) >= 2:
                    order = np.argsort(vv)
                    vv = vv[order]
                    ss = ss[order]
            else:
                tgt = self.target_crel if self.target_crel is not None else self.locked_crel()
                v = np.linspace(0.005, 0.995, 121)
                s = mc.solve_s_at_crel(self.h, self.metric, v, tgt)
                ok = np.isfinite(s)
                if not np.any(ok):
                    return None
                ss, vv = np.clip(s[ok], 0.0, 1.0), v[ok]
            if len(ss) < 2:
                return None
            return np.column_stack([ss, vv])
        except Exception:
            return None

    def locked_lightness(self):
        return float(mc.lightness(self.h, self.s, self.v, self.metric))

    def locked_crel(self):
        try:
            return float(mc.crel_of_xyz(self.h, self.metric, self.s, self.v)[0])
        except Exception:
            return 0.5

    def locked_cabs(self):
        """当前颜色的**绝对彩度** C = √(a²+b²)（环上右键锁定用）。"""
        try:
            return float(mc.ok_L_C(self.h, self.s, self.v)[1])
        except Exception:
            return 0.0

    # ---- 色环「不可达色相」提示（不改环位图，只叠一层矢量斜纹）----
    def _unreachable_spans(self):
        """当前色点 (L, C) 下**不可达**的色相弧 [(起点, 宽度), ...]（度，可能跨 0°）。

        不可达 = {h : C_max(L,h) < C}，按 1° 采样；没开提示 / 全可达时返回 []。
        结果按 (L, C, metric) 缓存：拖动中同色重复绘制不重算。
        """
        if not self.show_unreachable:
            return []
        try:
            L = float(mc.lightness(self.h, self.s, self.v, self.metric))
            C = float(mc.ok_L_C(self.h, self.s, self.v)[1])
        except Exception:
            return []
        key = (round(L, 5), round(C, 5), self.metric)
        if self._unreachable_key == key and self._unreachable_cache is not None:
            return self._unreachable_cache
        spans = mc.hue_reachable_spans(L, C, 1.0, self.metric)
        out = []
        if not spans:
            out = [(0.0, 360.0)]                     # 整圈都不可达
        elif not (len(spans) == 1 and (spans[0][1] - spans[0][0]) >= 360.0 - 1e-9):
            # 可达段已规范成 (lo, lo+width)（lo ∈ [0,360)、width ≤ 360）；
            # 把跨 0° 的段展开到 [0,720) 后按起点排序，段间空隙就是不可达弧。
            norm = [(float(lo) % 360.0, float(lo) % 360.0 + (float(hi) - float(lo)))
                    for lo, hi in spans]
            norm.sort()
            first = norm[0]
            cur = first[1]
            for lo, hi in norm[1:]:
                if lo > cur + 1e-9:
                    out.append((cur % 360.0, lo - cur))
                cur = max(cur, hi)
            wrap_len = (first[0] + 360.0) - cur
            if wrap_len > 1e-9:
                out.append((cur % 360.0, wrap_len))
        self._unreachable_key = key
        self._unreachable_cache = out
        return out

    def unreachable_path(self, geom=None):
        """不可达扇区的 QPainterPath（环形扇区）；无不可达时返回 None。

        方位换算：色相 h 的屏幕极角 = 180 - h（Qt 角度逆时针为正），
        色相顺时针增 -> 扫掠为负；跨 0° 的弧拆成两段。
        """
        spans = self._unreachable_spans()
        if not spans:
            return None
        g = geom if geom is not None else self._geometry()
        cx, cy, r_in, r_out = g["cx"], g["cy"], g["r_in"], g["r_out"]
        rect_o = QRectF(cx - r_out, cy - r_out, 2.0 * r_out, 2.0 * r_out)
        rect_i = QRectF(cx - r_in, cy - r_in, 2.0 * r_in, 2.0 * r_in)
        path = QPainterPath()
        for lo, width in spans:
            pieces = [(lo, width)] if lo + width <= 360.0 else \
                [(lo, 360.0 - lo), (0.0, lo + width - 360.0)]
            for a_deg, w in pieces:
                if w <= 1e-6:
                    continue
                a0 = 180.0 - a_deg
                path.arcMoveTo(rect_o, a0)
                path.arcTo(rect_o, a0, -w)
                path.arcTo(rect_i, a0 - w, w)
                path.closeSubpath()
        return path

    def freeze_lines(self, mode):
        """按被锁定的线冻结：mode = "iso"（锁明度→冻结红线）/ "crel"（锁彩度→冻结蓝线）/ "both" / None。"""
        mode = str(mode or "none")
        self._frozen_iso = self._iso_line_now() if mode in ("iso", "both") else None
        self._frozen_crel = self._crel_line_now() if mode in ("crel", "both") else None
        self.update()

    def _clear_frozen_lines(self):
        self._frozen_iso = None
        self._frozen_crel = None

    def _through_lines(self):
        """两条过点线：被锁定的那条用按下时的冻结快照，另一条实时更新。"""
        frozen_iso = getattr(self, "_frozen_iso", None)
        frozen_crel = getattr(self, "_frozen_crel", None)
        if frozen_iso is not None or frozen_crel is not None:
            return {"iso": frozen_iso if frozen_iso is not None else self._iso_line_now(),
                    "crel": frozen_crel if frozen_crel is not None else self._crel_line_now()}
        key = (round(self.h, 2), round(self.s, 5), round(self.v, 5), self.metric)
        if self._through_cache is not None and self._through_key == key:
            return self._through_cache
        out = {"iso": self._iso_line_now(), "crel": self._crel_line_now()}
        self._through_cache = out
        self._through_key = key
        return out

    def _iso_line_now(self):
        """红线 = 等明度线（彩度轨迹线）；显示用采样（精度足够、成本低）。"""
        try:
            work_l = float(mc.lightness(self.h, self.s, self.v, self.metric))
            ss, vv = mc.iso_lightness_curve(self.h, work_l, self.metric, n_v=33, iters=10)
            if len(ss) >= 2:
                return (ss, vv)
        except Exception:
            pass
        return None

    def _crel_line_now(self):
        """蓝线 = 等 C_rel 线（明度 0~100 轨迹线）；显示用采样。"""
        try:
            crel = float(mc.crel_of_xyz(self.h, self.metric, self.s, self.v)[0])
            v = np.linspace(0.005, 0.995, 33)
            s = mc.solve_s_at_crel(self.h, self.metric, v, crel, iters=10)
            ok = np.isfinite(s)
            if int(ok.sum()) >= 2:
                ss, vv = mc.filter_crel_line(self.h, self.metric,
                                             np.clip(s[ok], 0.0, 1.0), v[ok])
                if len(ss) >= 2:
                    return (ss, vv)
        except Exception:
            pass
        return None

    def _curve_v_to_s(self, curve, v_query):
        """在约束曲线上按 V 插值出 S（曲线按 V 单调，天然单调可插值）。"""
        order = np.argsort(curve[:, 1])
        vv = curve[order, 1]
        ss = curve[order, 0]
        return float(np.interp(v_query, vv, ss))

    def _curve_s_to_v(self, curve, s_query):
        """在约束曲线上按 S 插值出 V（曲线按 S 单调）。"""
        order = np.argsort(curve[:, 0])
        ss = curve[order, 0]
        vv = curve[order, 1]
        return float(np.interp(s_query, ss, vv))

    # ---- 键表：输入 -> 动作（R14）----
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

    def _lookup_action(self, area, btn, mods):
        """(区域, 鼠标键, Qt 修饰键位) -> 动作 id（未知组合落回无修饰行）。"""
        mod = kmc.mods_from_bools(bool(mods & Qt.ShiftModifier),
                                  bool(mods & Qt.ControlModifier),
                                  bool(mods & Qt.AltModifier),
                                  bool(mods & _UNKNOWN_QT_MODS))
        return kmc.lookup(self.keymap, area, self._btn_id(btn), mod)

    # ---- 环上动作（R15：除「无」外都是绝对角度，点击即到位）----
    def _begin_ring_action(self, action, pos):
        if action == "none":
            return False
        hue = rd.hue_from_pos(self._geometry(), pos.x(), pos.y()) % 360.0
        if action == "hue_hsv":
            self._drag_mode = "ring_hue_hsv"
            self.h = hue
        elif action == "hue_lock_lc_rel":
            self._drag_mode = "ring_crel"
            self.target_l = self.locked_lightness()
            self.target_crel = self.locked_crel()
            self.h = hue
            self._apply_ring_lc_rel(hue)
        else:                                   # hue_lock_lc_abs（未知动作也兜底到它）
            self._drag_mode = "ring_lc"
            self.target_l = self.locked_lightness()
            self.target_cabs = self.locked_cabs()
            self._apply_ring_lc(hue)
        return True

    # ---- 方块内动作 ----
    def _begin_square_action(self, action, pos):
        if action == "none":
            return False
        if action == "abs":
            self._drag_mode = "absolute"
            self._apply_absolute_locked(pos, "square")
            self._reanchor()
        elif action == "abs_lock_l":
            self._drag_mode = "absolute"
            self.btn_l = True
            self._refresh_locks()
            self._apply_absolute_locked(pos, "square")
            self._reanchor()
        elif action == "abs_lock_c":
            self._drag_mode = "absolute"
            self.btn_c = True
            self._refresh_locks()
            self._apply_absolute_locked(pos, "square")
            self._reanchor()
        elif action == "rel_l":                 # 改明度（相对，锁 C_rel，沿明度轨迹线）
            self._drag_mode = "rel_right"
            self.btn_c = True
            self._refresh_locks()
        elif action == "rel_c":                 # 改彩度（相对，锁明度，沿彩度轨迹线）
            self._drag_mode = "rel_mid"
            self.btn_l = True
            self._refresh_locks()
        elif action == "s_only":
            self._drag_mode = "axis"
            self._axis_lock = "s"
        elif action == "v_only":
            self._drag_mode = "axis"
            self._axis_lock = "v"
        else:                                   # 未知动作：退化为绝对定位
            self._drag_mode = "absolute"
            self._apply_absolute_locked(pos, "square")
            self._reanchor()
        return True

    def _apply_ring_lc_rel(self, hue):
        """环上「锁 L + 锁相对彩度 C_rel」：C_rel 换算成该 (L, h) 下的绝对 C 再解 (S, V)。"""
        if self.target_l is None or self.target_crel is None:
            return
        h = float(hue) % 360.0
        cmax = float(mc.cmax_of_L(h, self.metric, self.target_l))
        got = mc.sv_at_L_C(h, self.target_l, self.target_crel * cmax,
                            self.metric, clamp=True)
        if got is None:
            return
        self.h = h
        self.s = mc.clamp(float(got[0]), 0.0, 1.0)
        self.v = mc.clamp(float(got[1]), 0.0, 1.0)

    def _reanchor(self):
        """松手重锚定：锁明度 -> 目标改当前明度；锁彩度 -> 目标改当前 C_rel。"""
        if self.lock_l:
            self.target_l = self.locked_lightness()
        if self.lock_c:
            self.target_crel = self.locked_crel()

    def _to_px(self, ss, vv, g):
        x0, y0 = g["sq"][0], g["sq"][1]
        w = max(1.0, g["sq"][2] - g["sq"][0])
        return (x0 + np.asarray(ss, dtype=np.float64) * w,
                y0 + (1.0 - np.asarray(vv, dtype=np.float64)) * w)

    @staticmethod
    def _polyline(p, xs, ys):
        pts = [QPointF(float(x), float(y)) for x, y in zip(xs, ys)]
        if len(pts) >= 2:
            p.drawPolyline(QPolygonF(pts))

    def _paint_clusters(self, p, g):
        data = self._clusters()
        p.setBrush(Qt.NoBrush)
        for family, base in (("iso", (150, 190, 225, 160)), ("crel", (195, 170, 120, 160))):
            for _tgt, ss, vv in data[family]:
                for rgba, width in cluster_line_styles(base, _tgt):
                    pen = QPen(QColor(*rgba), width)
                    pen.setStyle(Qt.DashLine)
                    p.setPen(pen)
                    self._polyline(p, *self._to_px(ss, vv, g))

    def _paint_through(self, p, g):
        lines = self._through_lines()
        # 过点线：红 = 等明度线（彩度轨迹线），蓝 = 明度轨迹线
        # 样式与簇线一致（细虚线），只是加粗到 2.0
        for line, color in ((lines["iso"], QColor(230, 60, 60, 235)),
                            (lines["crel"], QColor(70, 130, 255, 235))):
            if line is None:
                continue
            xs, ys = self._to_px(line[0], line[1], g)
            pen = QPen(color, 1.8)
            pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            self._polyline(p, xs, ys)

    def paintEvent(self, event):
        g = self._geometry()
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)
        side = min(self.width(), self.height())
        p.drawPixmap(int(round(g["cx"] - side / 2.0)),
                     int(round(g["cy"] - side / 2.0)), self._ring_pixmap())
        # 不可达色相提示（R9）：先铺 30% 灰底（58,58,58,77），再叠中灰细斜纹。
        # v2 的「只画线不填灰底」已作废；命中判定不受影响，环位图不重算。
        if self.show_unreachable:
            up = self.unreachable_path(g)
            if up is not None:
                p.setPen(Qt.NoPen)
                p.setBrush(QBrush(QColor(58, 58, 58, 77)))       # 30% 灰底
                p.drawPath(up)
                p.setBrush(QBrush(QColor(128, 128, 128, 170), Qt.BDiagPattern))
                p.drawPath(up)
                p.setBrush(Qt.NoBrush)
        sq = self._square_pixmap()
        x0, y0 = int(round(g["sq"][0])), int(round(g["sq"][1]))
        p.drawPixmap(x0, y0, sq)
        p.setPen(QPen(QColor(20, 20, 20, 160), 1))
        p.drawRect(x0, y0, sq.width() - 1, sq.height() - 1)
        if self.show_clusters:
            self._paint_clusters(p, g)
        if self.show_lines:
            self._paint_through(p, g)
        px, py = self._sv_to_px(self.s, self.v)
        for pen in (QPen(QColor(0, 0, 0, 200), 2), QPen(QColor(255, 255, 255, 235), 1.5)):
            p.setPen(pen)
            p.drawEllipse(QPointF(px, py), 6.0, 6.0)
        p0 = rd.pos_from_hue(g, self.h, g["r_in"])
        p1 = rd.pos_from_hue(g, self.h, g["r_out"])
        for pen in (QPen(QColor(0, 0, 0, 200), 3), QPen(QColor(255, 255, 255, 235), 1.5)):
            p.setPen(pen)
            p.drawLine(QPointF(p0[0], p0[1]), QPointF(p1[0], p1[1]))
        mid = rd.pos_from_hue(g, self.h, (g["r_in"] + g["r_out"]) / 2.0)
        p.setPen(QPen(QColor(255, 255, 255, 235), 1.5))
        p.drawEllipse(QPointF(mid[0], mid[1]), 2.0, 2.0)

    # ---- 悬停钩子（面板用于「鼠标移到拾色器上就显示预览」设置项）----
    def enterEvent(self, event):
        hook = getattr(self, "hover_enter", None)
        if hook is not None:
            try:
                hook()
            except Exception:
                pass
        super().enterEvent(event)

    def leaveEvent(self, event):
        hook = getattr(self, "hover_leave", None)
        if hook is not None:
            try:
                hook()
            except Exception:
                pass
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        pos = event.localPos()
        area = self._hit(pos)
        if area is None:
            event.ignore()
            return
        btn = event.button()
        if btn not in (Qt.LeftButton, Qt.MiddleButton, Qt.RightButton):
            event.ignore()
            return
        self.setFocus(Qt.MouseFocusReason)
        self._press_pos = pos
        self._press_area = area
        self._press_sv = (self.s, self.v)
        self._press_h = self.h
        self._axis_lock = None
        mods = event.modifiers()
        if dlog.is_enabled():
            dlog.log("PICK_DOWN", area=area, btn=int(btn), x=round(pos.x(), 1),
                     y=round(pos.y(), 1), h=round(self.h, 3), s=round(self.s, 5),
                     v=round(self.v, 6), lock_l=int(self.lock_l), lock_c=int(self.lock_c),
                     mods=int(mods))

        # R14：动作由自定义按键表决定；左键先清掉中/右键留下的临时锁
        if btn == Qt.LeftButton:
            self.btn_l = False
            self.btn_c = False
            self.target_cabs = None
            self._refresh_locks()
        action = self._lookup_action(area, btn, mods)
        if area == "ring":
            started = self._begin_ring_action(action, pos)
        else:
            started = self._begin_square_action(action, pos)
        if not started:
            self._drag_mode = None
            self._clear_frozen_lines()
            self.update()
            event.accept()
            return
        # 色相环上中/右键拖动：红蓝线都实时；方块内相对拖动：锁定的线冻结、另一条实时
        if self._drag_mode == "rel_mid":
            self.freeze_lines("iso")      # 方块内锁明度 → 红线不动，蓝线实时
        elif self._drag_mode == "rel_right":
            self.freeze_lines("crel")     # 方块内锁彩度 → 蓝线不动，红线实时
        else:
            self.freeze_lines(None)       # 环上动作与左键绝对定位：两条线都实时
        self._snap_anchor = (self.s, self.v)
        self._invalidate_clusters()
        self.update()
        self.interaction_started.emit()
        self.color_changed()
        event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_mode is None:
            return
        pos = event.localPos()
        # 60Hz 节流：环/轴拖动等重活最多每 14ms 做一次，保证 ≥60fps 手感
        import time as _time
        now = _time.monotonic()
        if self._drag_mode in ("ring_hue_hsv", "ring_crel", "ring_lc",
                               "axis") and (now - self._last_heavy) < 0.014:
            return
        self._last_heavy = now
        if self._drag_mode == "absolute":
            self._apply_absolute_locked(pos, self._press_area)
        elif self._drag_mode == "ring_hue_hsv":
            self.h = rd.hue_from_pos(self._geometry(), pos.x(), pos.y()) % 360.0
        elif self._drag_mode in ("ring_crel", "ring_lc"):
            hue = rd.hue_from_pos(self._geometry(), pos.x(), pos.y())
            if self._drag_mode == "ring_lc":
                self._apply_ring_lc(hue)
            else:
                self._apply_ring_lc_rel(hue)
        elif self._drag_mode == "axis":
            g = self._geometry()
            half = max(1.0, g["half_sq"])
            the_s, the_v = self._press_sv
            if self._axis_lock == "s":
                self.s = mc.clamp(the_s + (pos.x() - self._press_pos.x()) / (2.0 * half), 0.0, 1.0)
            else:
                self.v = mc.clamp(the_v - (pos.y() - self._press_pos.y()) / (2.0 * half), 0.0, 1.0)
        elif self._drag_mode == "rel_mid":
            self._drag_mid(pos)
        elif self._drag_mode == "rel_right":
            self._drag_right(pos)
        if dlog.is_enabled():
            dlog.log_throttled("PICK_MOVE", 8, mode=self._drag_mode, x=round(pos.x(), 1),
                               y=round(pos.y(), 1), h=round(self.h, 3), s=round(self.s, 5),
                               v=round(self.v, 6))
            if self._drag_mode in ("rel_mid", "rel_right", "ring_hue_hsv",
                                   "ring_crel", "ring_lc"):
                try:
                    L = float(mc.lightness(self.h, self.s, self.v, self.metric))
                    C = float(mc.crel_of_xyz(self.h, self.metric, self.s, self.v)[0])
                    dlog.log_throttled("PICK_SNAP", 16, mode=self._drag_mode, L=round(L, 5),
                                       L_t=(None if self.target_l is None else round(self.target_l, 5)),
                                       C=round(C, 5),
                                       C_t=(None if self.target_crel is None else round(self.target_crel, 5)))
                except Exception:
                    pass
        self.update()
        self.color_changed()
        event.accept()

    def _apply_ring_lc(self, hue):
        """环上「锁 L + 锁绝对彩度 C」（R15：绝对角度 + 超限钳到最近可达边界）。

        目标色相 (h, L0, C0) 可达时直接切过去；不可达（C0 > C_max(L0, h)）时，
        把色相**钳到角度距离最近的可达边界**，颜色取该边界处的色
        （L、C 仍锁定）。不再保留 v3 的跟手指示线。
        """
        if self.target_l is None or self.target_cabs is None:
            return
        h = float(hue) % 360.0
        got = mc.sv_at_L_C(h, self.target_l, self.target_cabs, self.metric)
        if got is None:
            h2 = mc.nearest_reachable_hue(h, self.target_l, self.target_cabs,
                                         metric=self.metric)
            if h2 is None:
                return
            got = mc.sv_at_L_C(h2, self.target_l, self.target_cabs,
                                self.metric, clamp=True)
            if got is None:
                return
            h = h2
        self.h = h
        self.s = mc.clamp(float(got[0]), 0.0, 1.0)
        self.v = mc.clamp(float(got[1]), 0.0, 1.0)

    def _drag_mid(self, pos):
        """中键（方块内）：左右拖动，沿彩度轨迹线按**弧长比例**移动。"""
        self._drag_along_arc(pos, vertical=False)

    def _drag_right(self, pos):
        """右键（方块内）：上下拖动，沿明度轨迹线按**弧长比例**移动。"""
        self._drag_along_arc(pos, vertical=True)

    def _drag_along_arc(self, pos, vertical):
        """把鼠标位移换算成「沿约束曲线弧长的相对推进量」，再取新点。

        用弧长而不是坐标分量，避免曲线平缓段「动一点跳很远」。
        """
        curve = self.constraint_curve()
        if curve is None or len(curve) < 2:
            return
        g = self._geometry()
        w = max(1.0, g["sq"][2] - g["sq"][0])
        pts = np.column_stack([g["sq"][0] + curve[:, 0] * w,
                               g["sq"][1] + (1.0 - curve[:, 1]) * w])
        seg = np.hypot(np.diff(pts[:, 0]), np.diff(pts[:, 1]))
        cum = np.concatenate([[0.0], np.cumsum(seg)])
        total = float(cum[-1])
        if total <= 1e-9:
            return
        # 按下时色点在曲线上的弧长
        anchor = self._snap_anchor if getattr(self, "_snap_anchor", None) else self._press_sv
        d0 = np.hypot(pts[:, 0] - (g["sq"][0] + anchor[0] * w),
                      pts[:, 1] - (g["sq"][1] + (1.0 - anchor[1]) * w))
        t0 = float(cum[int(np.argmin(d0))])
        # 位移：宁可多给一点，让手感接近「拖多远走多远」
        delta_px = ((pos.x() - self._press_pos.x()) if not vertical
                    else -(pos.y() - self._press_pos.y()))
        t_new = float(np.clip(t0 + delta_px * (total / max(1.0, w)), 0.0, total))
        px = float(np.interp(t_new, cum, pts[:, 0]))
        py = float(np.interp(t_new, cum, pts[:, 1]))
        self.s = mc.clamp((px - g["sq"][0]) / w, 0.0, 1.0)
        self.v = mc.clamp(1.0 - (py - g["sq"][1]) / w, 0.0, 1.0)

    def mouseReleaseEvent(self, event):
        if self._drag_mode is None:
            return
        mode = self._drag_mode
        if self._drag_mode in ("rel_mid", "rel_right", "absolute",
                               "ring_hue_hsv", "ring_crel", "ring_lc"):
            self._reanchor()
        # 临时锁只服务于本次拖动：松手后一律清掉
        self.btn_l = False
        self.btn_c = False
        self.target_cabs = None
        self._refresh_locks()
        self._drag_mode = None
        self._axis_lock = None
        self._clear_frozen_lines()
        self._snap_anchor = None
        self._invalidate_clusters()
        self.update()
        self.interaction_finished.emit()
        self.color_changed()
        if dlog.is_enabled():
            dlog.log("PICK_UP", mode=mode, h=round(self.h, 3), s=round(self.s, 5),
                     v=round(self.v, 6), lock_l=int(self.lock_l), lock_c=int(self.lock_c))
        event.accept()
