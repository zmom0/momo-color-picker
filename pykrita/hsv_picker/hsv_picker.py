# -*- coding: utf-8 -*-
"""HSV 拾色器（Oklab 明度）— Krita 5.3.3 Docker 插件。

结构：
  HsvPickerDocker      —— 面板形态的拾色器（T-3 先做空面板 + 前景/背景色信号验证）
  HsvPickerExtension   —— 注册可自定义快捷键的动作，用于临时弹出拾色器

目标环境：Krita 5.3.3 / Qt5 / PyQt5 5.15.x / Python 3.13（不要写 Qt6 API）。
"""

import os
import tempfile
import time
import traceback

from PyQt5.QtCore import QEvent, QObject, QTimer, Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (QAction, QActionGroup, QCheckBox, QHBoxLayout, QLabel,
                             QLineEdit, QMenu, QMessageBox, QStyle, QToolButton,
                             QVBoxLayout, QWidget)
from krita import (DockWidget, DockWidgetFactory, DockWidgetFactoryBase,
                   Extension, Krita, ManagedColor)

import numpy as np


def mc_clamp(x):
    return max(0.0, min(1.0, float(x)))


try:                        # 插件内：包内相对导入
    from . import __version__
    from . import debug_log as dlog
    from . import i18n
    from . import math_core
    from . import picker_widget
    from . import history_widget
    from . import keymap_core
    from . import strip_widget
    from . import swatch_widget
    from . import preview_overlay
    from . import keymap_dialog
    from .drag_edit import DragValueEdit
except ImportError:         # 离线单测：直接把本目录加进 sys.path
    __version__ = "1.1.0"
    import debug_log as dlog
    import i18n
    import math_core
    import picker_widget
    import history_widget
    import keymap_core
    import strip_widget
    import swatch_widget
    import preview_overlay
    import keymap_dialog
    from drag_edit import DragValueEdit

PLUGIN_ID = "hsv_picker"          # 必须等于 .desktop 的 X-KDE-Library 与文件夹名
ACTION_POPUP_ID = "hsv_picker_popup"
ACTION_CLUSTERS_ID = "hsv_picker_show_clusters"
ACTION_LINES_ID = "hsv_picker_show_lines"
DEFAULT_POPUP_SHORTCUT = "Shift+B"
HISTORY_KEY = "HsvPickerHistory"
AUTO_CLOSE_KEY = "HsvPickerAutoClosePopup"   # 弹出面板外自动关闭（默认开）
ON_TOP_KEY = "HsvPickerAlwaysOnTop"          # 弹出窗口置顶（默认开）
POPUP_AT_MOUSE_KEY = "HsvPickerPopupAtMouse"  # 弹出位置跟随鼠标（默认开）
SHOW_AB_KEY = "HsvPickerShowAbStrips"        # 显示 Oklab a/b 分量条（默认开）
STRIP_LABEL_W = 14                           # 色条符号标签宽度（L / C / a / b 左端对齐用）
AB_MODE_KEY = "HsvPickerAbRangeMode"         # a/b 条量程口径：box（默认）/ line
PREVIEW_MODE_KEY = "HsvPickerPreviewMode"    # 浮层选项：off / 1s / 2s / hover / always（默认 hover）
SHOW_UNREACHABLE_KEY = "HsvPickerShowUnreachable"    # 色环「不可达色相」提示（默认开）
KEYMAP_KEY = "HsvPickerKeymap"               # 自定义按键表（JSON；空 = 默认表）
CHROMA_MODE_KEY = "HsvPickerChromaMode"              # C 条口径：rel（默认）/ abs
CHROMA_FULL_KEY = "HsvPickerChromaFullRange"         # 绝对口径下 C 条满量程（默认不勾）
CHROMA_ABS_CLUSTER_KEY = "HsvPickerChromaAbsCluster"  # 绝对 C 线簇密度：fixed（默认）/ even
TEMP_CHROMA_KEY_KEY = "HsvPickerTempChromaKey"       # 临时切换键（MOD_ID；默认 shift）
LIGHTNESS_METRIC_KEY = "HsvPickerLightnessMetric"    # 明度标准：oklab（默认）/ gray
POPUP_SIZE_USER_KEY = "HsvPickerPopupSizeUser"       # 用户手动调整过的弹窗尺寸
POPUP_SIZE_LEGACY_KEY = "HsvPickerPopupSize"         # T-40 前的旧尺寸键（程序化尺寸也会写入，已废弃不读）
POPUP_FILL_ASPECT = 1.278     # 默认高 = 宽 × 该比例：拾色器方块填满宽度且无纵向空白（实测 493→630）
PREVIEW_MODES = ("off", "1s", "2s", "hover", "always")
LIGHTNESS_METRICS = ("oklab", "gray")                 # 明度标准可选值
PREVIEW_DEFAULT_MODE = "hover"
PREVIEW_SHORT_MS = 1000                      # 「1 秒」模式的倒计时（ms）
PREVIEW_HIDE_MS = 2000                       # 「2 秒」模式的倒计时（ms）
PREVIEW_FOLLOW_MS = 150                      # 浮层显示期间重锚定的间隔（跟随拾色器；隐藏就停表）
_UNSET = object()                            # 「尚未捕获」哨兵（沿用 object() 而不是 None：None 是合法取值）

# 调试日志（排查加载/事件问题时把 _DEBUG 打开）
_DEBUG = False


def _default_debug_log():
    try:
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        if os.path.isfile(os.path.join(base, "tools", "math_selftest.py")):
            return os.path.join(base, "tmp", "hsv_picker_debug.log")
    except NameError:
        pass
    return os.path.join(tempfile.gettempdir(), "hsv_picker_debug.log")


_DEBUG_LOG = _default_debug_log()


def _alive(obj):
    """Qt 包装对象是否仍然存活（Krita 退出时会先销毁 C++ 对象）。"""
    if obj is None:
        return False
    try:
        from PyQt5 import sip
        return not sip.isdeleted(obj)
    except Exception:
        return True


def _log(text):
    if not _DEBUG:
        return
    try:
        os.makedirs(os.path.dirname(_DEBUG_LOG), exist_ok=True)
        with open(_DEBUG_LOG, "a", encoding="utf-8", newline="\n") as fh:
            fh.write("%s\n" % (text,))
    except Exception:
        pass


def active_view():
    """当前活动 View；无窗口/无文档时返回 None。"""
    win = Krita.instance().activeWindow()
    return win.activeView() if win is not None else None


def read_fg_qcolor(view=None):
    """读 Krita 前景色 -> QColor（Krita 负责色彩管理转换）。"""
    view = view if view is not None else active_view()
    if view is None:
        return None
    mc = view.foregroundColor()
    if mc is None:
        return None
    try:
        return mc.colorForCanvas(view.canvas())
    except Exception:
        _log("read_fg_qcolor 失败:\n%s" % traceback.format_exc())
        return None


def write_fg_qcolor(qcolor, view=None):
    """把 QColor 写回 Krita 前景色；写入会同步触发 foregroundColorChanged。"""
    view = view if view is not None else active_view()
    if view is None:
        return False
    try:
        mc = ManagedColor.fromQColor(qcolor, view.canvas())
        if mc is None:
            return False
        view.setForeGroundColor(mc)
        return True
    except Exception:
        _log("write_fg_qcolor 失败:\n%s" % traceback.format_exc())
        return False


def popup_position(cursor, popup_size, screen_rect, window_rect=None):
    """计算弹窗左上角（屏幕像素坐标）。

    - 弹窗**以鼠标为中心**；
    - 超出 Krita 主窗口时自动**贴边**（夹回窗口内）；
    - 同时不超出屏幕可用区（可放置区域 = Krita 窗口 ∩ 屏幕；两者不相交时优先 Krita 窗口）。
    所有 rect 均为闭区间 (left, top, right, bottom)。
    """
    cx, cy = int(cursor[0]), int(cursor[1])
    width, height = int(popup_size[0]), int(popup_size[1])
    sl, st, sr, sb = [int(v) for v in screen_rect]
    domain = (sl, st, sr, sb)
    if window_rect is not None:
        wl, wt, wr, wb = [int(v) for v in window_rect]
        left, top = max(sl, wl), max(st, wt)
        right, bottom = min(sr, wr), min(sb, wb)
        if left <= right and top <= bottom:
            domain = (left, top, right, bottom)
        else:
            domain = (wl, wt, wr, wb)      # 窗口与屏幕完全不相交：优先留在 Krita 窗口内
    left, top, right, bottom = domain
    x = cx - width // 2
    y = cy - height // 2
    x = max(left, min(x, right - width + 1))
    y = max(top, min(y, bottom - height + 1))
    return (x, y)


class HsvPickerPanel(QWidget):
    """拾色器主控件（Docker 面板与快捷键弹出窗口共用同一套实现）。

    color_synced：其它面板改了颜色时广播，用于面板之间同步（Docker <-> 弹出窗口）。
    """

    color_synced = pyqtSignal(float, float, float, str)

    def __init__(self, parent=None, dbg_name="panel", follow_active_view=False):
        super().__init__(parent)
        self.follow_active_view = bool(follow_active_view)   # 弹窗为 True：始终跟随当前活动视图
        self.view_sinks = []                                 # 本面板视图变化时要同步的其它面板
        self.setMinimumWidth(300)
        self.setMinimumHeight(430)
        self._view = None
        self._syncing = False           # 写前景色期间：忽略 Krita 的回冲信号
        self._picking = False           # 拾色器交互中：浮层不启动倒计时（松手后才计时）
        self._internal = False          # 本次前景色变化是不是拾色器自己写的
        self._dirty = False             # Krita 前景色被外部改动，需要回读进拾色器
        self.show_clusters = True       # ① 显示明度/彩度线簇（含对应标签）
        self.show_lines = True          # ② 显示明度/彩度线
        # 诊断日志模式（T-16）：每次启动 Krita 自动关闭（不跨会话持久化）
        self.debug_log = bool(dlog.is_enabled())
        self._dbg_ctx = "-"             # 当前颜色变更来源（写日志用）
        self._dbg_last_l = None         # 上一条颜色记录的明度（按当前口径；跳变检测用）
        self._dbg_name = dbg_name        # docker / popup（写日志用）
        # 弹出面板外自动关闭（默认开；设置持久化）
        self.auto_close_popup = True
        try:
            self.auto_close_popup = (Krita.instance().readSetting("", AUTO_CLOSE_KEY, "") or "1") != "0"
        except Exception:
            self.auto_close_popup = True
        # 弹出面板置顶（默认值照旧；设置持久化）
        self.always_on_top = True
        try:
            self.always_on_top = (Krita.instance().readSetting("", ON_TOP_KEY, "") or "1") != "0"
        except Exception:
            self.always_on_top = True
        # 弹出位置跟随鼠标（默认开；设置持久化）
        self.popup_at_mouse = True
        try:
            self.popup_at_mouse = (Krita.instance().readSetting("", POPUP_AT_MOUSE_KEY, "") or "1") != "0"
        except Exception:
            self.popup_at_mouse = True
        # 显示 Oklab a/b 分量条（默认开；设置持久化）
        self.show_ab = True
        try:
            self.show_ab = (Krita.instance().readSetting("", SHOW_AB_KEY, "") or "1") != "0"
        except Exception:
            self.show_ab = True
        # a/b 条量程口径：box=当前明度切片包围盒（刻度不抖，可能有死区）/
        #                 line=单线可行区间（满量程可达）
        self.ab_mode = "box"
        try:
            self.ab_mode = Krita.instance().readSetting("", AB_MODE_KEY, "") or "box"
        except Exception:
            self.ab_mode = "box"
        if self.ab_mode not in ("box", "line"):
            self.ab_mode = "box"
        # 色环「不可达色相」提示（默认开；设置持久化）
        self.show_unreachable = True
        try:
            self.show_unreachable = (Krita.instance().readSetting(
                "", SHOW_UNREACHABLE_KEY, "") or "1") != "0"
        except Exception:
            self.show_unreachable = True
        # 自定义按键表（R14：JSON 持久化；空/坏值 = 默认表）
        self.keymap = keymap_core.default_keymap()
        try:
            self.keymap = keymap_core.parse(
                Krita.instance().readSetting("", KEYMAP_KEY, "") or "")
        except Exception:
            self.keymap = keymap_core.default_keymap()
        # 全局「临时切换键」（T-53）：按住它 + 键表基础行 = 临时翻转彩度口径；none = 不自动翻转
        self.temp_chroma_key = "shift"
        try:
            _tk = str(Krita.instance().readSetting("", TEMP_CHROMA_KEY_KEY, "") or "").strip()
            if _tk in keymap_core.MOD_IDS:
                self.temp_chroma_key = _tk
        except Exception:
            self.temp_chroma_key = "shift"
        # C 条口径：rel = 相对彩度 C_rel（默认）/ abs = 绝对彩度 C
        self.chroma_mode = "rel"
        try:
            _cm = str(Krita.instance().readSetting("", CHROMA_MODE_KEY, "") or "").strip()
            if _cm in ("rel", "abs"):
                self.chroma_mode = _cm
        except Exception:
            self.chroma_mode = "rel"
        # 绝对口径下的量程：不勾（默认）= 固定 [0, C_ABS_LIM] 有死区；勾 = 满量程 [0, C_max]
        self.chroma_full = False
        try:
            self.chroma_full = (Krita.instance().readSetting(
                "", CHROMA_FULL_KEY, "") or "0") != "0"
        except Exception:
            self.chroma_full = False
        # 绝对 C 线簇密度：fixed（默认，0.02~0.36 共 18 档）/ even（按色相纯色 C_max 等分 9 档）
        self.abs_cluster_mode = "fixed"
        try:
            _acm = str(Krita.instance().readSetting(
                "", CHROMA_ABS_CLUSTER_KEY, "") or "").strip()
            if _acm in ("even", "fixed"):
                self.abs_cluster_mode = _acm
        except Exception:
            self.abs_cluster_mode = "fixed"
        # 明度标准：oklab = Oklab 感知明度 L（默认，零影响）/ gray = 灰阶码值（色彩校样口径）
        # 只影响 L 条 / L 数值框 / 锁明度动作 / 等明度线与簇 / C_max·C_rel 的 L 轴；
        # a/b 分量条的内部 L 轴永远是 Oklab L。
        self.lightness_metric = "oklab"
        try:
            _lm = str(Krita.instance().readSetting("", LIGHTNESS_METRIC_KEY, "") or "").strip()
            if _lm in LIGHTNESS_METRICS:
                self.lightness_metric = _lm
        except Exception:
            self.lightness_metric = "oklab"
        # 浮层选项：off（关闭）/ 1s / 2s / hover（默认，鼠标悬停拾色器即显示）/ always；持久化
        self.preview_mode = PREVIEW_DEFAULT_MODE
        try:
            raw_mode = str(Krita.instance().readSetting("", PREVIEW_MODE_KEY, "") or "").strip()
            if raw_mode in PREVIEW_MODES:
                self.preview_mode = raw_mode
        except Exception:
            self.preview_mode = PREVIEW_DEFAULT_MODE
        self.preview_hide_ms = PREVIEW_HIDE_MS   # 「2 秒」模式的倒计时（测试会临时调小）
        self._overlay = None                     # 预览浮层（惰性创建的独立小窗）
        self._keymap_dialog = None               # 「按键功能…」操作矩阵（惰性创建、已开复用）
        self._keymap_dialog_wanted = False       # R24：对话框是否应为「打开」状态
        self._keymap_dialog_hidden_by_host = False   # R24：因宿主最小化而临时隐藏
        self._was_shown = False                  # 面板是否显示过（离屏初始化时不据此收起浮层）
        # 浮层下排两格：本轮操作开始时的「上上次 / 上一次选色」（整轮不变，松手后也保持）
        self._preview_last_rgb = _UNSET
        self._preview_older_rgb = _UNSET
        self._picker_hovered = False             # 「悬停」模式：鼠标是否在拾色器内
        # T-53 切换键悬停预览：鼠标在面板内 + 按住全局临时切换键 -> 临时预览另一口径
        self._panel_hovered = False              # 由 widgetAt(鼠标位置) 父链判定，主/弹窗各自维护
        self._hover_suspended = False            # 应用失活时暂停悬停预览
        self._hover_filter_installed = False
        self._kb_shift = False                   # 显式维护的修饰键状态（KeyPress/KeyRelease，修正松开不回）
        self._kb_ctrl = False
        self._kb_alt = False
        self._strip_ab_ctx = None       # a/b 条拖动期间锁定的 (M0, a, b)
        self._strip_ab_Lok = None       # a/b 条按下时刻的 Oklab L（可达区间冻结用）
        self._strip_ab_metric = None    # a/b 条按下时刻的「明度标准」
        self._strip_ab_gray_iv = None   # gray 口径：本分量「目标灰阶可达」区间缓存
        self._strip_active = False      # 色条拖动中（跨面板同步隔离用）
        self._suppress_until = 0.0      # 写入/同步后短窗口内，画布上与当前色差 ≤1 的变化视为回声
        # T-49/T-51 数值行自适应：固定宽度开销、布局递归 guard（文本始终完整，无动态小数）
        self._entry_row_fixed = None
        self._layout_entry_guard = False
        self.h = 0.0
        self.s = 1.0
        self.v = 1.0
        self._status = QLabel(self)     # 仅用于内部错误提示；必须隐藏，否则会飘在面板左上角
        self._status.hide()
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(3)
        self._build_ui(root)
        self._sync_entries()
        self.history_listeners = []     # 跨面板同步：历史变化时回调
        self.view_listeners = []        # 跨面板同步：显示开关变化时回调
        self._load_history()
        self.destroyed.connect(self._on_panel_destroyed)
        # 预览浮层跟随拾色器：只在浮层显示期间跑（每 150ms 重锚定一次），隐藏即停表
        self._preview_follow = QTimer(self)
        self._preview_follow.setInterval(PREVIEW_FOLLOW_MS)
        self._preview_follow.timeout.connect(self._preview_follow_tick)
        # 外部改色兜底：有些路径不一定给 View 信号（系统拾色器等），轻量轮询比对
        self._poll = QTimer(self)
        self._poll.setInterval(120)
        self._poll.timeout.connect(self._poll_external)
        self._poll.start()
        try:
            self._install_hover_filter()     # T-53：应用级事件过滤，供切换键悬停预览
        except Exception:
            pass
        if self.debug_log:
            self._dbg_session()
        self.refresh_status()

    # ---------------------------------------------------------------- UI

    def _build_ui(self, root):
        # 2) 中部：拾色器（居中）+ 历史颜色（右侧）——手工摆放，避免布局反馈把拾色器越挤越小
        self.mid_box = QWidget(self)
        self.mid_box.setMinimumHeight(200)
        self.picker = picker_widget.HsvPickerCanvas(self.mid_box)
        self.picker.set_color(self.h, self.s, self.v)
        self.picker.color_changed = self._on_picker_color
        self.picker.interaction_started.connect(self._on_pick_start)
        self.picker.interaction_finished.connect(self._on_pick_end)
        self.picker.set_keymap(self.keymap)
        self.picker.set_chroma_mode(self.chroma_mode)   # T-48：拾色器跟随 C 条口径
        self.picker.set_temp_chroma_key(self.temp_chroma_key)   # T-53：按下动作/悬停共用的临时切换键
        self.picker.set_show_unreachable(bool(self.show_unreachable))
        # 「悬停」模式用：鼠标进出拾色器
        self.picker.hover_enter = self._on_picker_hover_enter
        self.picker.hover_leave = self._on_picker_hover_leave
        self.history = history_widget.HistoryWidget(self.mid_box, on_pick=self._on_history_pick)
        root.addWidget(self.mid_box, 1)

        # 3) 设置按钮（二级菜单；与数值行同一排、位于最左侧）
        self.btn_menu = QToolButton(self)
        self.btn_menu.setText(i18n.t("设置", "Settings"))
        self.btn_menu.setPopupMode(QToolButton.InstantPopup)
        self.btn_menu.setToolTip(i18n.t("显示选项：明度/彩度线簇与过点线",
                                        "Display options: clusters and through-lines"))
        self.menu = QMenu(self.btn_menu)
        self.act_clusters = QAction(i18n.t("显示明度/彩度线簇", "Show lightness/chroma cluster lines"), self.menu)
        self.act_clusters.setCheckable(True)
        self.act_clusters.setChecked(self.show_clusters)
        self.act_clusters.toggled.connect(self.set_show_clusters)
        self.act_lines = QAction(i18n.t("显示明度/彩度线", "Show lightness/chroma through-lines"), self.menu)
        self.act_lines.setCheckable(True)
        self.act_lines.setChecked(self.show_lines)
        self.act_lines.toggled.connect(self.set_show_lines)
        self.menu.addAction(self.act_clusters)
        self.menu.addAction(self.act_lines)
        # 色环「不可达色相」提示（默认开）：只叠细斜纹、不填灰底，不影响点击/拖动
        self.act_unreachable = QAction(i18n.t("显示不可达色相提示",
                                              "Show unreachable hue hint"), self.menu)
        self.act_unreachable.setCheckable(True)
        self.act_unreachable.setToolTip(i18n.t(
            "在色环上把「当前明度 + 当前绝对彩度 C 够不到」的色相段叠一层细斜纹；"
            "只画斜线、不填灰底，斜线之间保留原色相；只影响观感，斜纹区照样可点可拖",
            "Draw a thin hatch overlay over the hue spans that cannot reach the current "
            "lightness + absolute chroma C; lines only, no gray fill, original hue remains "
            "between lines; visual only, hatching stays clickable and draggable"))
        self.act_unreachable.blockSignals(True)
        self.act_unreachable.setChecked(self.show_unreachable)
        self.act_unreachable.blockSignals(False)
        self.act_unreachable.toggled.connect(self.set_show_unreachable)
        self.menu.addAction(self.act_unreachable)
        self.act_show_ab = QAction(i18n.t("显示 Oklab a/b 分量条",
                                          "Show Oklab a/b strips"), self.menu)
        self.act_show_ab.setCheckable(True)
        self.act_show_ab.setToolTip(i18n.t(
            "在明度/彩度条下方再加 a 条与 b 条（Oklab 的另外两个分量），可拖动改色",
            "Add Oklab a and b strips below lightness/chroma; drag to change the color"))
        self.act_show_ab.blockSignals(True)
        self.act_show_ab.setChecked(self.show_ab)
        self.act_show_ab.blockSignals(False)
        self.act_show_ab.toggled.connect(self.set_show_ab)
        self.menu.addAction(self.act_show_ab)
        self.act_ab_line = QAction(i18n.t("a/b 条满量程",
                                          "a/b strips full range"), self.menu)
        self.act_ab_line.setCheckable(True)
        self.act_ab_line.setToolTip(i18n.t(
            "勾选：量程随「另一分量」变，但每一段都拖得到；不勾（默认）：量程只随明度变、"
            "刻度更稳，够不到的段画成灰色斜纹",
            "On: range follows the other component (every span is reachable); "
            "Off (default): range follows lightness only, unreachable spans are hatched"))
        self.act_ab_line.blockSignals(True)
        self.act_ab_line.setChecked(self.ab_mode == "line")
        self.act_ab_line.blockSignals(False)
        self.act_ab_line.toggled.connect(self.set_ab_mode_line)
        self.menu.addAction(self.act_ab_line)
        # C 条选项（二选一，默认相对彩度 C_rel）+ 绝对口径满量程
        self.menu_chroma = QMenu(i18n.t("C 条选项", "C strip options"), self.menu)
        self.menu_chroma.setToolTip(i18n.t(
            "相对彩度 C_rel = C / C_max(L,h) ∈ [0,1]，永远满量程；"
            "绝对彩度 C = √(a²+b²)（Oklab 口径），量程固定 0~0.4 时够不到的段画灰斜纹",
            "Relative chroma C_rel = C / C_max(L,h) in [0,1], always full range; "
            "absolute chroma C = sqrt(a^2+b^2) (Oklab), fixed 0-0.4 range hatches unreachable spans"))
        self.chroma_group = QActionGroup(self.menu)
        self.chroma_group.setExclusive(True)
        self.chroma_actions = {}
        for _mode, _zh, _en in (("rel", "相对彩度 C_rel", "Relative chroma C_rel"),
                                ("abs", "绝对彩度 C", "Absolute chroma C")):
            act = QAction(i18n.t(_zh, _en), self.menu_chroma)
            act.setCheckable(True)
            act.setChecked(_mode == self.chroma_mode)
            act.triggered.connect(lambda _checked=False, m=_mode: self.set_chroma_mode(m))
            self.chroma_group.addAction(act)
            self.menu_chroma.addAction(act)
            self.chroma_actions[_mode] = act
        self.act_c_cluster_even = QAction(i18n.t(
            "绝对 C 线簇按色相等分", "Even absolute C clusters by hue"), self.menu_chroma)
        self.act_c_cluster_even.setCheckable(True)
        self.act_c_cluster_even.setToolTip(i18n.t(
            "绝对彩度口径的线簇档位：不勾（默认）= 固定 0.02~0.36 步长 0.02 共 18 档"
            "（够不到的明度段不画）；勾选 = 当前色相纯色 C_max(h) 的 10%~90% 共 9 档",
            "Absolute chroma cluster levels: off (default) = fixed 0.02-0.36 in 0.02 steps "
            "(18 levels); on = 9 levels at 10%-90% of the pure-color C_max(h)"))
        self.act_c_cluster_even.blockSignals(True)
        self.act_c_cluster_even.setChecked(self.abs_cluster_mode != "fixed")
        self.act_c_cluster_even.blockSignals(False)
        self.act_c_cluster_even.toggled.connect(self.set_abs_cluster_even)
        self.menu_chroma.addAction(self.act_c_cluster_even)
        # 临时切换键（8 项互斥）：按住它 + 基础行动作 = 临时锁另一彩度口径
        self.menu_temp_key = QMenu(i18n.t("临时切换键", "Temporary switch key"),
                                   self.menu_chroma)
        self.menu_temp_key.setToolTip(i18n.t(
            "按住该键时：悬停面板即时预览另一彩度口径；按方块中/右键、环左/中/右键时"
            "临时锁另一口径，松开恢复。none = 不自动翻转（*_other 动作仍可手动绑定）",
            "Hold this key while hovering the panel to preview the other chroma scale; "
            "pressing the square middle/right or ring left/middle/right buttons locks "
            "the other scale until release. none = no auto flip (*_other actions remain "
            "selectable in the key table)"))
        self.temp_key_group = QActionGroup(self.menu)
        self.temp_key_group.setExclusive(True)
        self.temp_key_actions = {}
        for _mid, _zh, _en in keymap_core.MODS:
            act = QAction(i18n.t(_zh, _en), self.menu_temp_key)
            act.setCheckable(True)
            act.setChecked(_mid == self.temp_chroma_key)
            act.triggered.connect(
                lambda _checked=False, m=_mid: self.set_temp_chroma_key(m))
            self.temp_key_group.addAction(act)
            self.menu_temp_key.addAction(act)
            self.temp_key_actions[_mid] = act
        self.menu_chroma.addMenu(self.menu_temp_key)
        self.menu.addMenu(self.menu_chroma)
        self.act_c_full = QAction(i18n.t("C 条满量程", "C strip full range"), self.menu)
        self.act_c_full.setCheckable(True)
        self.act_c_full.setToolTip(i18n.t(
            "仅绝对口径生效。勾选：量程 = C_max(L,h)，永远满量程可达、无死区（刻度随颜色变）；"
            "不勾（默认）：量程固定 0~0.4，够不到的段画灰斜纹、拖到底即停",
            "Absolute scale only. On: range = C_max(L,h), always reachable (ticks follow the color); "
            "Off (default): fixed 0-0.4 range, unreachable spans are hatched and dragging stops there"))
        self.act_c_full.blockSignals(True)
        self.act_c_full.setChecked(self.chroma_full)
        self.act_c_full.blockSignals(False)
        self.act_c_full.toggled.connect(self.set_chroma_full)
        self.menu.addAction(self.act_c_full)
        # 明度标准（二选一，默认 Oklab L）：只换 L 轴口径，a/b 条的内部 L 轴永远是 Oklab L
        self.menu_metric = QMenu(i18n.t("明度标准", "Lightness standard"), self.menu)
        self.menu_metric.setToolTip(i18n.t(
            "Oklab L = 感知明度（默认）；灰阶 = Krita 软打样那张灰块的码值 srgb_encode(Y)。"
            "切换只改 L 条 / L 数值框 / 锁明度动作 / 等明度线 / C_max·C_rel 的 L 轴，"
            "a/b 分量条的内部 L 轴永远是 Oklab L",
            "Oklab L = perceptual lightness (default); Grayscale = the code value of Krita's "
            "soft-proof gray patch, srgb_encode(Y). Switching only changes the L axis used by "
            "the L strip / L field / lock-lightness actions / iso-lightness lines / C_max and "
            "C_rel; the a/b strips always use Oklab L internally"))
        self.metric_group = QActionGroup(self.menu)
        self.metric_group.setExclusive(True)
        self.metric_actions = {}
        for _mode, _zh, _en in (("oklab", "Oklab L（感知明度）", "Oklab L (perceptual)"),
                                ("gray", "灰阶（色彩校样）", "Grayscale (soft proof)")):
            act = QAction(i18n.t(_zh, _en), self.menu_metric)
            act.setCheckable(True)
            act.setChecked(_mode == self.lightness_metric)
            act.triggered.connect(
                lambda _checked=False, m=_mode: self.set_lightness_metric(m))
            self.metric_group.addAction(act)
            self.menu_metric.addAction(act)
            self.metric_actions[_mode] = act
        self.menu.addMenu(self.menu_metric)
        self.menu.addSeparator()
        # 浮层选项（子菜单，五项互斥）：改色时在面板外侧弹出三格预览
        self.menu_preview = QMenu(i18n.t("浮层选项", "Overlay options"), self.menu)
        self.menu_preview.setToolTip(i18n.t(
            "浮层 = 改色时在面板外侧弹出的 100×150 三格预览"
            "（当前选色 / 上一次选色 / 上上次选色）；靠屏幕边缘时自动翻到另一侧",
            "Overlay = the 100x150 three-cell preview (current / last picked / the one before last) "
            "popped up next to the panel while you change the color; it flips sides near the screen edge"))
        self.preview_group = QActionGroup(self.menu)
        self.preview_group.setExclusive(True)
        self.preview_actions = {}
        for mode, label_zh, label_en in (("off", "关闭", "Off"),
                                         ("1s", "1 秒", "1 second"),
                                         ("2s", "2 秒", "2 seconds"),
                                         ("hover", "悬停", "Hover"),
                                         ("always", "一直", "Always")):
            act = QAction(i18n.t(label_zh, label_en), self.menu_preview)
            act.setCheckable(True)
            act.setChecked(mode == self.preview_mode)
            act.triggered.connect(lambda _checked=False, m=mode: self.set_preview_mode(m))
            self.preview_group.addAction(act)
            self.menu_preview.addAction(act)
            self.preview_actions[mode] = act
        self.menu.addMenu(self.menu_preview)
        self.menu.addSeparator()
        self.act_keymap = QAction(i18n.t("按键功能…", "Key functions..."), self.menu)
        self.act_keymap.setToolTip(i18n.t(
            "打开自定义按键表：选区域×输入（鼠标键+修饰键）×动作；"
            "改完立即生效并保存，底部可恢复默认",
            "Open the custom key table: area x input (mouse button + modifier) x action; "
            "changes take effect and are stored immediately, with a Restore defaults button"))
        self.act_keymap.triggered.connect(self.show_keymap_dialog)
        self.menu.addAction(self.act_keymap)
        self.act_auto_close = QAction(i18n.t("点击弹出面板外时自动关闭",
                                             "Auto-close popup when clicking outside"), self.menu)
        self.act_auto_close.setCheckable(True)
        self.act_auto_close.blockSignals(True)
        self.act_auto_close.setChecked(self.auto_close_popup)
        self.act_auto_close.blockSignals(False)
        self.act_auto_close.toggled.connect(self.set_auto_close_popup)
        self.menu.addAction(self.act_auto_close)
        self.act_on_top = QAction(i18n.t("弹出面板置顶", "Keep popup always on top"), self.menu)
        self.act_on_top.setCheckable(True)
        self.act_on_top.setToolTip(i18n.t(
            "弹出面板保持在其他窗口之上；「点击弹出面板外时自动关闭」打开时本项无效（置灰）",
            "Keep the popup above other windows; disabled while "
            "\"Auto-close popup when clicking outside\" is on"))
        self.act_on_top.blockSignals(True)
        self.act_on_top.setChecked(self.always_on_top)
        self.act_on_top.blockSignals(False)
        self.act_on_top.setEnabled(not self.auto_close_popup)     # R17：自动关闭开 → 置顶项置灰（记忆值保留）
        self.act_on_top.toggled.connect(self.set_always_on_top)
        self.menu.addAction(self.act_on_top)
        self.act_mouse_pos = QAction(i18n.t("弹出位置跟随鼠标", "Popup at mouse position"), self.menu)
        self.act_mouse_pos.setCheckable(True)
        self.act_mouse_pos.blockSignals(True)
        self.act_mouse_pos.setChecked(self.popup_at_mouse)
        self.act_mouse_pos.blockSignals(False)
        self.act_mouse_pos.toggled.connect(self.set_popup_at_mouse)
        self.menu.addAction(self.act_mouse_pos)
        self.menu.addSeparator()
        self.act_debug = QAction(i18n.t("诊断日志", "Diagnostic log"), self.menu)
        self.act_debug.setCheckable(True)
        self.act_debug.setToolTip(i18n.t(
            "开启后把交互与内部状态写入 %APPDATA%\\krita\\hsv_picker_debug.log"
            "（每次启动 Krita 自动关闭；开启时覆盖上次日志）",
            "Write interaction and internal state to %APPDATA%\\krita\\hsv_picker_debug.log"
            " (off on every Krita start; enabling overwrites the previous log)"))
        self.act_debug.blockSignals(True)
        self.act_debug.setChecked(self.debug_log)
        self.act_debug.blockSignals(False)
        self.act_debug.toggled.connect(self.set_debug_log)
        self.menu.addAction(self.act_debug)
        if self.debug_log:
            self.act_debug.setText(i18n.t("诊断日志（开启中）", "Diagnostic log (on)"))
        self.menu.addSeparator()
        self.act_about = QAction(
            i18n.t("关于馍馍拾色器 v" + str(__version__),
                   "About Momo Color Picker v" + str(__version__)), self.menu)
        self.act_about.setToolTip(i18n.t(
            "显示 slogan、版本、许可与第三方依赖信息",
            "Show the slogan, version, license and third-party notices"))
        self.act_about.triggered.connect(self.show_about_dialog)
        self.menu.addAction(self.act_about)
        self.btn_menu.setMenu(self.menu)

        # 4) 数值行：设置按钮 + H / S / V（可拖动调值）+ HEX + 当前色小色块，同一排
        # T-49：四框宽度按面板宽度自适应（H/S/V 等宽、2→1→0 位小数；HEX 优先完整）。
        data_row = QHBoxLayout()
        data_row.setSpacing(4)
        data_row.addWidget(self.btn_menu)
        data_row.addSpacing(6)
        self.edit_h = self._make_entry(DragValueEdit, "0.00", 58, (0.0, 360.0), 0.2, True, "h")
        self.edit_s = self._make_entry(DragValueEdit, "100.00", 60, (0.0, 100.0), 0.2, False, "s")
        self.edit_v = self._make_entry(DragValueEdit, "100.00", 60, (0.0, 100.0), 0.2, False, "v")
        # 构造时先按字体实测兜底（padding=8，不裁字）：H 最宽 "359.99"、S/V 最宽 "100.00"。
        self.edit_h.setFixedWidth(self._entry_width(self.edit_h, "359.99", 58, 8))
        self.edit_s.setFixedWidth(self._entry_width(self.edit_s, "100.00", 60, 8))
        self.edit_v.setFixedWidth(self._entry_width(self.edit_v, "100.00", 60, 8))
        self.edit_hex = self._make_entry(QLineEdit, "#FF0000", self._entry_width(
            self.edit_v, "#RRGGBB", 88, 26))
        self._entry_labels = {}
        for label, edit in (("H", self.edit_h), ("S", self.edit_s),
                            ("V", self.edit_v), ("HEX", self.edit_hex)):
            lbl = QLabel(label, self)
            data_row.addWidget(lbl)
            self._entry_labels[label] = lbl
            data_row.addWidget(edit)
            data_row.addSpacing(6)
        self._data_row = data_row
        # 当前色小色块：放在 HEX 数值框右边、**吃满该行右侧余量**（旧的 48px 三色块已移除）
        self.swatch_cur = swatch_widget.CurrentColorSwatch(self)
        self.swatch_cur.sync_height(self.edit_hex.sizeHint().height())
        data_row.addWidget(self.swatch_cur, 1)
        root.addLayout(data_row)
        # T-49 字体实测上限（+8 余量）与行内固定开销在构造时量一次；resize 时按可用宽分配。
        self._w_hsv_full = max(self._entry_width(self.edit_h, "359.99", 0, 8),
                               self._entry_width(self.edit_h, "100.00", 0, 8))
        self._w_hsv_1 = max(self._entry_width(self.edit_h, "359.9", 0, 8),
                            self._entry_width(self.edit_h, "100.0", 0, 8))
        self._w_hsv_0 = max(self._entry_width(self.edit_h, "360", 0, 8),
                            self._entry_width(self.edit_h, "100", 0, 8))
        self._w_hex_full = self._entry_width(self.edit_hex, "#RRGGBB", 0, 8)
        self._w_hex_min = self._entry_width(self.edit_hex, "#RRR", 0, 8)

        # 5) 两条横向色条（左 0）：明度条 + 彩度条，各带数值框
        self.strip_l_row = QHBoxLayout()
        self.strip_l_row.setSpacing(4)
        self.strip_l = strip_widget.LightnessStrip(
            self, on_changed=self._on_strip_lightness, metric=self.lightness_metric,
            on_press=self._on_strip_l_press, on_release=self._on_strip_release)
        # 四个分量数值框（L / C / a / b）**等宽** = 字体实测最大值：
        # 四条色条行都是 [标签][色条(stretch)][数值框(定宽)]，框宽不同会让四条色条的右端错开。
        # 样例取最坏情况："0.0000"（L/C）与 "-0.0000"（a/b 带符号，比 "+" 宽）。
        _uni_w = max(self._entry_width(self.edit_h, "0.0000", 64, 8),
                     self._entry_width(self.edit_h, "-0.0000", 64, 8))
        self.edit_l = QLineEdit("0.5000", self)
        self.edit_l.setFixedWidth(_uni_w)
        self.edit_l.setAlignment(Qt.AlignRight)
        self.edit_l.editingFinished.connect(self._on_entry_commit)
        self.lbl_l = self._strip_label(
            "L", i18n.t("Oklab 明度 L（0~1）", "Oklab lightness L (0-1)"))
        self.strip_l_row.addWidget(self.lbl_l)
        self.strip_l_row.addWidget(self.strip_l, 1)
        self.strip_l_row.addWidget(self.edit_l)
        root.addLayout(self.strip_l_row)

        self.strip_c_row = QHBoxLayout()
        self.strip_c_row.setSpacing(4)
        self.strip_c = strip_widget.ChromaStrip(
            self, on_changed=self._on_strip_chroma,
            on_press=self._on_strip_c_press, on_release=self._on_strip_release)
        self.edit_c = QLineEdit("1.0000", self)
        self.edit_c.setFixedWidth(_uni_w)
        self.edit_c.setAlignment(Qt.AlignRight)
        self.edit_c.editingFinished.connect(self._on_entry_commit)
        self.lbl_c = self._strip_label(
            "C", i18n.t("相对彩度 C（0~1；1 = 该明度/色相下最饱和）",
                        "Relative chroma C (0-1; 1 = most saturated at this lightness/hue)"))
        self.strip_c_row.addWidget(self.lbl_c)
        self.strip_c_row.addWidget(self.strip_c, 1)
        self.strip_c_row.addWidget(self.edit_c)
        root.addLayout(self.strip_c_row)

        # 6) Oklab a / b 分量条（默认显示；设置菜单可收起）
        self.strip_a_row = QHBoxLayout()
        self.strip_a_row.setSpacing(4)
        self.strip_a = strip_widget.AbStrip(
            self, axis="a", mode=self.ab_mode,
            on_changed=lambda v: self._on_strip_ab("a", v),
            on_press=lambda: self._on_strip_ab_press("a"),
            on_release=self._on_strip_release)
        self.edit_a = QLineEdit("+0.0000", self)
        self.edit_a.setFixedWidth(_uni_w)
        self.edit_a.setAlignment(Qt.AlignRight)
        self.edit_a.editingFinished.connect(self._on_entry_commit)
        self.lbl_a = self._strip_label(
            "a", i18n.t("Oklab a 分量（绿 ↔ 红方向）", "Oklab a component (green to red)"))
        self.strip_a_row.addWidget(self.lbl_a)
        self.strip_a_row.addWidget(self.strip_a, 1)
        self.strip_a_row.addWidget(self.edit_a)
        root.addLayout(self.strip_a_row)

        self.strip_b_row = QHBoxLayout()
        self.strip_b_row.setSpacing(4)
        self.strip_b = strip_widget.AbStrip(
            self, axis="b", mode=self.ab_mode,
            on_changed=lambda v: self._on_strip_ab("b", v),
            on_press=lambda: self._on_strip_ab_press("b"),
            on_release=self._on_strip_release)
        self.edit_b = QLineEdit("+0.0000", self)
        self.edit_b.setFixedWidth(_uni_w)
        self.edit_b.setAlignment(Qt.AlignRight)
        self.edit_b.editingFinished.connect(self._on_entry_commit)
        self.lbl_b = self._strip_label(
            "b", i18n.t("Oklab b 分量（蓝 ↔ 黄方向）", "Oklab b component (blue to yellow)"))
        self.strip_b_row.addWidget(self.lbl_b)
        self.strip_b_row.addWidget(self.strip_b, 1)
        self.strip_b_row.addWidget(self.edit_b)
        root.addLayout(self.strip_b_row)
        self._measure_entry_row()       # T-49：行内固定开销只量一次
        self._layout_entry_widths()
        self._apply_ab_visible()
        self._apply_chroma_label()
        self._apply_lightness_metric()
        self._apply_keymap()          # 把自定义按键表灌进四条色条与三个可拖动数值框
        # 首帧预算：预览浮层首次 show 要付 Qt 建原生窗口的一次性成本（本机 ~4ms）。
        # 它不属于 gray 可达区间，却会落进「首次拖动帧」；这里在面板构造时把原生
        # 窗口预创建掉（winId 不显示窗口、不抢焦点、观感与行为不变），首帧只付刷新。
        try:
            if getattr(self, "preview_mode", PREVIEW_DEFAULT_MODE) != "off":
                self.preview_overlay().winId()
        except Exception:
            pass

    def _strip_label(self, symbol, tip):
        """色条之前的符号标签（L / C / a / b）：固定宽度，保证 4 条左端对齐。"""
        lbl = QLabel(symbol, self)
        lbl.setToolTip(tip)
        lbl.setFixedWidth(STRIP_LABEL_W)
        return lbl

    def resizeEvent(self, event):
        self._layout_entry_widths()
        self._layout_picker()
        self._sync_swatch_height()
        super().resizeEvent(event)

    def _sync_swatch_height(self):
        """当前色块高度与 HEX 数值框一致（布局完成后按实测高度校正）。"""
        swatch = getattr(self, "swatch_cur", None)
        edit = getattr(self, "edit_hex", None)
        if swatch is None or edit is None or not _alive(swatch) or not _alive(edit):
            return
        height = edit.height() if edit.height() > 0 else edit.sizeHint().height()
        swatch.sync_height(height)

    def showEvent(self, event):
        self._was_shown = True
        self._layout_entry_widths()
        self._layout_picker()
        self._sync_swatch_height()
        super().showEvent(event)
        self._hover_suspended = False
        self._sync_kb_from_app()      # 显示时校准一次，避免隐藏期间漏掉 KeyRelease
        self._refresh_panel_hover()   # T-53：重新显示时按鼠标位置 + 按键状态刷新预览
        if getattr(self, "preview_mode", PREVIEW_DEFAULT_MODE) == "always":
            self._preview_update(start_countdown=False)   # 「一直」模式：打开面板即显示

    def event(self, ev):
        # 布局在每次尺寸变化后都要重算中间区（拾色器居中 + 历史列等高）
        from PyQt5.QtCore import QEvent
        if ev.type() in (QEvent.LayoutRequest, QEvent.Resize):
            self._layout_picker()
        return super().event(ev)

    def _layout_picker(self):
        """中间区手工布局：拾色器正方形居中、历史列贴右侧且与拾色器等高。

        不用 QHBoxLayout：历史列高度依赖拾色器边长，用布局会产生
        「设固定高 -> 挤压行 -> 拾色器更小 -> 历史更矮」的收缩反馈。
        """
        box = getattr(self, "mid_box", None)
        picker = getattr(self, "picker", None)
        if box is None or picker is None or not _alive(picker):
            return
        bw, bh = max(1, box.width()), max(1, box.height())
        hist = getattr(self, "history", None)
        hist_w = hist.width() if hist is not None else 0
        avail_w = max(80, bw - hist_w - 6)
        side = max(120, min(avail_w, bh))
        px = int((avail_w - side) / 2.0)
        picker.setGeometry(px, int((bh - side) / 2.0), side, side)
        if hist is not None and _alive(hist):
            hist_h = max(history_widget.CELL, side)
            hist.move(avail_w + 6, int((bh - hist_h) / 2.0))
            hist.resize(history_widget.CELL, hist_h)
            if len(hist.colors) != hist.capacity():
                self._save_history_capacity()

    def _entry_width(self, widget, sample, minimum, padding):
        """数值框宽度：按字体实测宽度 + 余量，取 max(最小宽, 实测宽+padding)。

        大字体 / 高 DPI 下写死宽度会裁掉开头字符（例如 HEX 的 "#"），所以一律现算；
        取不到字体度量时退回 minimum。
        """
        try:
            advance = int(widget.fontMetrics().horizontalAdvance(sample))
        except Exception:
            return int(minimum)
        return max(int(minimum), advance + int(padding))

    def _entry_widgets(self):
        """数值行四个框（H/S/V/HEX）：布局与焦点处理共用。"""
        return (self.edit_h, self.edit_s, self.edit_v, self.edit_hex)

    def _entry_panel_width(self):
        """面板分给数值行的可用内容宽（扣掉根布局左右边距）。"""
        w = max(1, int(self.width()))
        lay = self.layout()
        if lay is not None:
            m = lay.contentsMargins()
            w -= m.left() + m.right()
        return max(1, w)

    def _measure_entry_row(self):
        """行内固定开销 = data_row.sizeHint() − 四个数值框当前宽度和（构造时量一次）。"""
        row = getattr(self, "_data_row", None)
        if row is None:
            return
        try:
            cur = sum(int(w.width()) for w in self._entry_widgets())
            self._entry_row_fixed = max(0, int(row.sizeHint().width()) - cur)
        except Exception:
            self._entry_row_fixed = 0

    def _layout_entry_widths(self):
        """T-49/T-51：按可用宽分配 H/S/V/HEX 宽度；H/S/V 等宽、文本始终完整。

        宽度规则沿用 T-49 骨架（够宽取上限不再变宽；不够先保 HEX 完整、H/S/V 等分；
        再不够 H/S/V 保整数宽、HEX 收缩）。文本不再动态降小数，宽度不足时由
        `_update_entry_alignments()` 改成左对齐并停在开头。
        """
        if getattr(self, "_layout_entry_guard", False):
            return
        edits = self._entry_widgets()
        if any(not _alive(w) for w in edits):
            return
        if self._entry_row_fixed is None:
            self._measure_entry_row()
        avail = self._entry_panel_width() - int(self._entry_row_fixed or 0)
        wf, w1, w0 = self._w_hsv_full, self._w_hsv_1, self._w_hsv_0
        xh, xm = self._w_hex_full, self._w_hex_min
        if avail >= 3 * wf + xh:
            w_hsv, w_hex = wf, xh               # 够宽：四框都取上限，余量全部给色块
        else:
            w_hex = xh                          # 先保 HEX 完整
            share = (avail - xh) / 3.0
            if share >= w0:
                w_hsv = int(min(wf, max(w0, share)))
            else:
                w_hsv = w0                      # 再不够：H/S/V 保整数宽，HEX 收缩
                w_hex = int(max(xm, min(xh, avail - 3 * w_hsv)))
        changed = (int(self.edit_hex.width()) != int(w_hex)
                   or any(int(w.width()) != int(w_hsv)
                          for w in (self.edit_h, self.edit_s, self.edit_v)))
        self._layout_entry_guard = True
        try:
            for w in (self.edit_h, self.edit_s, self.edit_v):
                if int(w.width()) != int(w_hsv):
                    w.setFixedWidth(int(w_hsv))
            if int(self.edit_hex.width()) != int(w_hex):
                self.edit_hex.setFixedWidth(int(w_hex))
            if changed:
                self._sync_entries()
            self._update_entry_alignments()
        finally:
            self._layout_entry_guard = False

    def _update_entry_alignments(self):
        """T-51：文本始终完整；框宽不足时左对齐并停在开头（优先整数），够宽恢复右对齐。"""
        for edit in self._entry_widgets():
            if not _alive(edit):
                continue
            try:
                fm = edit.fontMetrics()
                frame = edit.style().pixelMetric(QStyle.PM_DefaultFrameWidth)
                need = fm.horizontalAdvance(edit.text()) + 2 * frame + 4
                want = Qt.AlignLeft if int(edit.width()) < int(need) else Qt.AlignRight
                if (edit.alignment() & Qt.AlignHorizontal_Mask) != want:
                    edit.setAlignment(want)
                if want == Qt.AlignLeft and not edit.hasFocus():
                    edit.setCursorPosition(0)   # 不聚焦时把显示停在文本开头
            except Exception:
                pass

    def _make_entry(self, cls, text, width, value_range=(0.0, 1.0), sensitivity=0.6,
                    wrap=False, kind=None):
        if cls is DragValueEdit:
            edit = cls(self, value_range=value_range, sensitivity=sensitivity,
                       decimals=2, wrap=wrap,
                       # 用默认参数捕获 kind，避免依赖 self.sender()
                       on_drag=lambda val, k=kind: self._on_drag_value(k, val))
            edit.kind = kind
        else:
            edit = cls(text, self)
        edit.setFixedWidth(width)
        edit.setAlignment(Qt.AlignRight)
        edit.editingFinished.connect(self._on_entry_commit)
        return edit

    def _on_drag_value(self, kind, value):
        """拖动 H/S/V 数值框时实时应用（与拾色器拖动一致，实时写前景色）。"""
        self._editing_field = kind
        if not getattr(self, "_entry_dragging", False):
            self._preview_begin()   # 数值框拖动开始：记下「上一次选色」
        self._entry_dragging = True
        self._dbg_ctx = "entry_drag_" + str(kind)
        if kind == "h":
            self.set_color(value, self.s, self.v)
        elif kind == "s":
            self.set_color(self.h, value / 100.0, self.v)
        elif kind == "v":
            self.set_color(self.h, self.s, value / 100.0)


    # ------------------------------------------------- Krita 视图绑定
    # ---- 历史颜色（16 色 LRU，持久化在 Krita 设置里）----
    def set_history(self, colors, save=True):
        """由外部（另一个面板）同步历史列表。"""
        self.history.set_colors(list(colors)[:128])
        if save:
            self._save_history()

    def _load_history(self):
        raw = ""
        try:
            raw = Krita.instance().readSetting("", HISTORY_KEY, "") or ""
        except Exception:
            raw = ""
        items = [x.strip().upper() for x in raw.split(",") if x.strip()]
        items = [x for x in items if len(x) == 7 and x.startswith("#")][:128]
        self.history.set_colors(items)

    def _save_history_capacity(self):
        """高度变化：只更新显示（模型仍保留最多 64 个），并持久化。"""
        self.history.set_colors(list(self.history.colors)[:128])
        self._save_history()

    def _save_history(self):
        try:
            Krita.instance().writeSetting("", HISTORY_KEY, ",".join(self.history.colors))
        except Exception:
            pass

    def _push_history(self, hex_text=None):
        hex_text = (hex_text or ("#%02X%02X%02X" % self.picker_rgb())).upper()
        items = [c for c in self.history.colors if c != hex_text]
        items.insert(0, hex_text)
        self.history.set_colors(items[:128])
        self._save_history()
        for cb in getattr(self, "history_listeners", []) or []:
            try:
                cb(self.history.colors)
            except Exception:
                pass

    def _on_history_pick(self, hex_text):
        try:
            r, g, b = math_core.parse_hex(hex_text)
        except Exception:
            return
        h, s, v = math_core.srgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
        if s <= 1e-6:
            h = self.h
        self._dbg_ctx = "history"
        self._preview_begin()       # 点击历史前：先把「上一次选色」记下来
        self.set_color(h, s, v, write_fg=True)
        self._push_history(hex_text)

    def _resolve_view(self):
        """当前应当读写的视图。

        弹窗（follow_active_view=True）优先使用 Krita 当前活动视图；没有活动视图时退回绑定视图。
        这里**不做信号重绑**（Krita 的 activeView() 可能每次返回新的 wrapper，重绑会递归/抖动）；
        视图切换时的信号重绑由 Docker canvasChanged → view_sinks 转发完成。
        """
        if self.follow_active_view:
            active = active_view()
            if active is not None:
                return active
        if self._view is not None:
            return self._view
        return active_view()

    def _poll_external(self):
        """轮询 Krita 前景色：与面板显示不一致且不是自己在写 -> 视为外部改色。"""
        if not _alive(self):
            return
        if self._interacting() or self._syncing:
            return
        if not self.isVisible():
            return
        view = self._resolve_view()
        qc = read_fg_qcolor(view)
        if qc is None:
            return
        my_rgb = self.picker_rgb()
        my_hex = "#%02X%02X%02X" % my_rgb
        canvas_hex = qc.name().upper()
        if not self._canvas_close_to_picker(canvas_hex):
            if dlog.is_enabled():
                dlog.log("POLL_MISMATCH", canvas=canvas_hex, picker=my_hex,
                         dr=qc.red() - my_rgb[0], dg=qc.green() - my_rgb[1],
                         db=qc.blue() - my_rgb[2], picking=int(self._picking))
            self._dirty = True
            self.refresh_status()

    def _pull_from_krita(self, reason="-"):
        """把 Krita 当前前景色读回拾色器（外部改色 / 系统拾色器也会同步）。"""
        if getattr(self, "_entry_dragging", False):
            return
        self._dirty = False
        view = self._resolve_view()
        qc = read_fg_qcolor(view)
        if qc is None:
            return
        try:
            h, s, v = math_core.srgb_to_hsv(qc.redF(), qc.greenF(), qc.blueF())
        except Exception:
            return
        if s <= 1e-6:
            h = self.h            # 灰轴：保留原色相
        if dlog.is_enabled():
            dlog.log("PULL", src=qc.name().upper(), reason=reason, h=round(h, 3),
                     s=round(s, 5), v=round(v, 6))
        self._dbg_ctx = "pull"
        self.set_color(h, s, v, write_fg=False, preview=False)   # 外部改色不弹浮层
        self._suppress_until = time.monotonic() + 0.5

    def set_view(self, view):
        if self._view is not None:
            for signal, slot in ((self._view.foregroundColorChanged, self._on_fg_changed),
                                 (self._view.backgroundColorChanged, self._on_bg_changed)):
                try:
                    signal.disconnect(slot)
                except (TypeError, RuntimeError):
                    pass
        self._view = view
        if view is not None:
            view.foregroundColorChanged.connect(self._on_fg_changed)
            view.backgroundColorChanged.connect(self._on_bg_changed)
        self.refresh_status()

    def _canvas_close_to_picker(self, hex_now):
        """画布颜色与当前颜色是否在 U8/画布量化容差（±1/255）内。"""
        try:
            r, g, b = self.picker_rgb()
            if hex_now == "#%02X%02X%02X" % (r, g, b):
                return True
            hr = int(hex_now[1:3], 16)
            hg = int(hex_now[3:5], 16)
            hb = int(hex_now[5:7], 16)
            return abs(hr - r) <= 1 and abs(hg - g) <= 1 and abs(hb - b) <= 1
        except Exception:
            return False

    def _on_fg_changed(self):
        if self._syncing:
            if dlog.is_enabled():
                dlog.log_throttled("SIG_FG", 10, sync=1, internal=int(bool(self._internal)),
                                   hex="-")
            return
        qc = read_fg_qcolor(self._view if self._view is not None else active_view())
        hex_now = qc.name().upper() if qc is not None else None
        # 写入/同步后的短窗口内，画布上与当前色相差 ≤1 的变化都是回声，不回读（避免量化值拉回抖动）
        if hex_now is not None and time.monotonic() < self._suppress_until \
                and self._canvas_close_to_picker(hex_now):
            if dlog.is_enabled():
                dlog.log_throttled("SIG_FG", 10, sync=0, echo=1, hex=hex_now)
            return
        if dlog.is_enabled():
            dlog.log_throttled("SIG_FG", 10, sync=0, internal=int(bool(self._internal)),
                               hex=(hex_now or "-"))
        if self._interacting():
            return
        if not self._internal:
            self._dirty = True          # 外部（含系统拾色器）改色：需要回读进拾色器
        self.refresh_status()

    def _on_pick_start(self):
        """开始拾色：记下浮层下排两格（上上次/上一次选色），本轮内保持不变。"""
        self._picking = True
        self._dbg_ctx = "picker"
        self._preview_begin()       # 记下本轮操作前的「上一次选色」
        self._sync_entries()        # T-51：临时口径开始时立即切 C 条/数值框显示
        dlog.log("PICK_START", h=round(self.h, 3), s=round(self.s, 5), v=round(self.v, 6))

    def _on_pick_end(self):
        """拾色结束：恢复实时跟随 Krita 前景色，并把当前色计入历史。"""
        self._picking = False
        # T-53：松手后若切换键仍按住且鼠标仍在面板内，继续悬停预览另一口径
        self._update_hover_temp()
        self._sync_entries()        # T-51：临时口径已在 picker 松手时清掉，这里恢复持久口径显示
        dlog.log("PICK_END", h=round(self.h, 3), s=round(self.s, 5), v=round(self.v, 6),
                 hex="#%02X%02X%02X" % self.picker_rgb())
        self._push_history()
        self.refresh_status()
        self._preview_start_countdown()      # 松手后才开始 2 秒倒计时

    def _on_bg_changed(self):
        if not self._syncing:
            self.refresh_status()

    # ------------------------------------------------- 颜色流转
    def picker_rgb(self):
        """当前拾色器颜色的 8bit RGB。"""
        rgb = math_core.hsv_to_srgb(self.h, self.s, self.v)
        return tuple(int(round(float(c) * 255.0)) for c in rgb)

    def apply_external(self, h, s, v, hex_text, write_fg=False):
        """由另一个面板同步过来的颜色：完全同步（颜色/读数/色条/色块一起更新）。"""
        if not _alive(self) or not _alive(getattr(self, "picker", None)):
            return
        if self._interacting():
            return                      # 本面板正在拖动：不让对端覆盖，松手后会自然对齐
        self._external_update = True
        self._dbg_ctx = "external"
        self._dirty = False
        try:
            # 同步过来的颜色不记历史（历史只在拾色交互松手时记一次）
            self.set_color(h, s, v, write_fg=write_fg)
        finally:
            self._external_update = False
            self._dbg_ctx = "-"
        self._suppress_until = time.monotonic() + 0.5

    def set_color(self, h, s, v, write_fg=False, preview=True):
        """设定当前颜色；write_fg=True 时同时写回 Krita 前景色。

        preview=False 或 _external_update=True（外部改色同步）时不弹预览浮层。
        """
        if not _alive(getattr(self, "picker", None)):
            return
        self.h = float(h) % 360.0
        self.s = max(0.0, min(1.0, float(s)))
        self.v = max(0.0, min(1.0, float(v)))
        self.picker.set_color(self.h, self.s, self.v)
        self._sync_entries()
        if not getattr(self, "_external_update", False):
            # 先广播给对端再写 Krita：对端据此打上"回声"标记，避免把量化回读再推回来
            self.color_synced.emit(self.h, self.s, self.v, "#%02X%02X%02X" % self.picker_rgb())
        if write_fg:
            self._write_fg()
        self.refresh_status()
        self._dbg_color(write_fg)
        if preview and not getattr(self, "_external_update", False):
            self._preview_update()

    def _write_fg(self):
        view = self._resolve_view()
        if view is None:
            if dlog.is_enabled():
                dlog.log("WRITE_FG_SKIP", reason="no_view")
            return
        hex_now = "#%02X%02X%02X" % self.picker_rgb()
        self._suppress_until = time.monotonic() + 0.5
        if dlog.is_enabled():
            dlog.log("WRITE_FG", hex=hex_now,
                     h=round(self.h, 3), s=round(self.s, 5), v=round(self.v, 6))
        self._syncing = True
        self._internal = True
        try:
            ok = write_fg_qcolor(QColor(*self.picker_rgb()), view)
            if not ok and dlog.is_enabled():
                dlog.log("WRITE_FG_FAIL", hex=hex_now)
        finally:
            self._syncing = False
            self._internal = False

    def _on_picker_color(self):
        self._dbg_ctx = "picker"
        self.h = self.picker.h
        self.s = self.picker.s
        self.v = self.picker.v
        self._sync_entries()
        if not getattr(self, "_external_update", False):
            self.color_synced.emit(self.h, self.s, self.v, "#%02X%02X%02X" % self.picker_rgb())
        self._write_fg()
        self.refresh_status()
        self._dbg_color(True)
        self._preview_update()      # 拾色器拖动：实时更新浮层（拖动中不倒计时）

    def _sync_entries(self):
        """把当前颜色同步到所有读数与色条（色条位置按"左 0"口径）。

        正在被拖动/编辑的那个框不回写，否则会和用户输入打架（表现为数值抽风跳动）。
        """
        skip = getattr(self, "_editing_field", None)
        if skip != "h":
            self.edit_h.setText("%.2f" % self.h)
        if skip != "s":
            self.edit_s.setText("%.2f" % (self.s * 100.0))
        if skip != "v":
            self.edit_v.setText("%.2f" % (self.v * 100.0))
        if skip != "hex":
            self.edit_hex.setText("#%02X%02X%02X" % self.picker_rgb())
        # T-48/T-51：持久口径 + 线簇密度灌进拾色器；临时口径（Shift+中/右）只影响显示
        eff_mode = self.chroma_mode
        if _alive(getattr(self, "picker", None)):
            self.picker.set_chroma_mode(self.chroma_mode)
            self.picker.set_abs_cluster_mode(self.abs_cluster_mode)
            eff_mode = self.picker.effective_chroma_mode()
        self._apply_chroma_label(eff_mode)
        L = float(math_core.lightness(self.h, self.s, self.v, self.lightness_metric))
        self.edit_l.setText("%.4f" % L)
        self.strip_l.set_hue(self.h)
        self.strip_l.set_value(L)                # 左 0（黑）
        self.strip_c.set_context(self.h, L)
        # C 条与 C 数值框按**生效口径**显示：Shift 临时切换期间跟另一口径，松手恢复
        self.strip_c.set_mode(eff_mode, self.chroma_full)
        c_disp = self._crel_now() if eff_mode == "rel" else self._cabs_now()
        if skip != "c":
            self.edit_c.setText("%.4f" % c_disp)
        self.strip_c.set_value(self.strip_c.t_of(c_disp))
        # Oklab a / b 分量（同一个颜色的另一组坐标）
        if getattr(self, "show_ab", True):
            L_ab, a_now, b_now = self._ab_now()
            skip_ab = getattr(self, "_editing_field", None)
            if _alive(getattr(self, "strip_a", None)):
                self.strip_a.set_context(L_ab, a_now, b_now)
            if _alive(getattr(self, "strip_b", None)):
                self.strip_b.set_context(L_ab, a_now, b_now)
            if skip_ab != "a" and _alive(getattr(self, "edit_a", None)):
                self.edit_a.setText("%+.4f" % a_now)
            if skip_ab != "b" and _alive(getattr(self, "edit_b", None)):
                self.edit_b.setText("%+.4f" % b_now)
        self._update_entry_alignments()

    def _ab_now(self):
        """当前色的 Oklab (L, a, b)；异常时退回「明度 + a=b=0」。

        正常路径恒为 Oklab L（a/b 条内部 L 轴固定 Oklab，见 AGENTS 固定语义）；
        异常兜底按当前「明度标准」取明度（R27 审计项），正常路径不受影响。
        """
        try:
            return tuple(float(x) for x in math_core.oklab_ab(self.h, self.s, self.v))
        except Exception:
            try:
                return float(math_core.lightness(self.h, self.s, self.v,
                                                self.lightness_metric)), 0.0, 0.0
            except Exception:
                return 0.0, 0.0, 0.0

    def _ab_ctx_now(self):
        """a/b 条拖动上下文：返回 (M0, a0, b0, L_ok, metric)。

        · M0  = 当前「明度标准」口径的明度值（a/b 条拖动要守住的量）；
        · L_ok = Oklab L（ab 可达区间仍按它冻结，与其它色条一致）；
        · metric = 按下时刻的明度标准（保存下来，拖动中途切菜单也不换口径）。
        """
        try:
            L_ok, a0, b0 = (float(x) for x in math_core.oklab_ab(self.h, self.s, self.v))
        except Exception:
            L_ok, a0, b0 = self._ab_now()
        metric = self.lightness_metric
        try:
            M0 = float(math_core.lightness(self.h, self.s, self.v, metric))
        except Exception:
            M0 = L_ok if metric == "oklab" else 0.0
        return M0, a0, b0, L_ok, metric

    def _solve_ab_L_metric(self, target, metric, a, b, iters=40):
        """固定 (a, b)，二分求 Oklab L 使 metric(oklab_to_srgb(L, a, b)) == target。

        灰阶口径下拖 a/b 条时用它保持「灰阶」不变。调用方会先用
        `_ab_gray_component_interval` 把本分量钳进目标灰阶可达区间，
        所以正常不会走到端点钳制；下面的端点分支只作防御性兜底。
        iters=40 是为了让灰阶残差稳定低于 1e-9。
        """
        if str(metric) == "gray":
            # 纯 Python 标量快路径（同式、同二分；numpy 标量调度太贵）
            return float(math_core.solve_ab_L_for_gray(float(target), float(a), float(b),
                                                       iters=iters))
        def f(Lv):
            rgb = math_core.oklab_to_srgb(Lv, a, b)
            hh, ss, vv = math_core.srgb_to_hsv(
                float(rgb[0]), float(rgb[1]), float(rgb[2]))
            return float(math_core.lightness(hh, ss, vv, metric))

        lo, hi = 0.0, 1.0
        flo, fhi = f(lo), f(hi)
        if target <= flo:
            return lo
        if target >= fhi:
            return hi
        for _ in range(int(iters)):
            mid = 0.5 * (lo + hi)
            if f(mid) < target:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    def _gray_at_ab_L(self, L_ok, a, b):
        """(Oklab L, a, b) -> sRGB 钳位后颜色的**灰阶码值**。"""
        rgb = math_core.oklab_to_srgb(float(L_ok), float(a), float(b))
        hh, ss, vv = math_core.srgb_to_hsv(
            float(rgb[0]), float(rgb[1]), float(rgb[2]))
        return float(math_core.lightness(hh, ss, vv, "gray"))

    def _ab_gray_component_interval(self, axis, other, target, x0, l_hint=None):
        """gray 口径下本分量 x 的「目标灰阶仍可达」区间 [lo, hi]。

        固定另一个分量 other 扫本分量 x；只要存在某个 Oklab L∈[0,1] 使
        灰阶 == target，就认为该 x 可达。区间以按下时刻的本分量 x0 为锚点
        向两侧扩张 + 二分（x0 就是当前颜色的分量，按下时必然可达）。

        可达判定原来是「L 两端点灰阶夹住 target」，属保守近似；现改为对
        L 均匀 17 点（另并入按下时刻的 Oklab L）求 min/max，再在 math_core 内
        向量化求值。多采样只会让可行区间比旧法更宽、更接近真实可达集合，
        且采样范围是真实 L∈[0,1] 的子集 => 永不把不可达判成可达。

        用途：把拖动/提交的本分量值先钳进这个区间端点，再二分解 L，
        这样灰阶严格不变（与其它色条「拖到底即停」一致）。
        结果按 (axis, other, target, x0, l_hint) 缓存，拖动期间每帧不重算。
        """
        key = (axis, round(float(other), 6), round(float(target), 6),
               round(float(x0), 6), None if l_hint is None else round(float(l_hint), 6))
        cached = getattr(self, "_strip_ab_gray_iv", None)
        if cached is not None and cached[0] == key:
            return float(cached[1]), float(cached[2])

        try:
            iv = math_core.gray_component_interval(axis, other, target, x0, l_hint=l_hint)
        except Exception:
            dlog.log("ERR", where="gray_component_interval", tb=traceback.format_exc())
            iv = None
        if iv is None:
            lim = float(math_core._AB_LIM)
            return -lim, lim               # 异常兜底：不钳（维持旧行为）
        self._strip_ab_gray_iv = (key, float(iv[0]), float(iv[1]))
        return float(iv[0]), float(iv[1])

    def _clear_strip_ab_ctx(self):
        """一次性清掉 a/b 条上下文（松手 / 数值框提交后调用）。

        R29：数值框提交必须等价于「按下 → 提交 → 松手」，否则下一次提交会
        沿用旧颜色算出的 (L / 另一分量 / 灰阶)，跳到旧颜色那条线上。
        """
        self._strip_ab_ctx = None
        self._strip_ab_Lok = None
        self._strip_ab_metric = None
        self._strip_ab_gray_iv = None

    def _crel_now(self):
        try:
            return float(math_core.crel_of_xyz(self.h, self.lightness_metric, self.s, self.v)[0])
        except Exception:
            return 0.0

    def _cabs_now(self):
        """当前颜色的**绝对彩度** C = √(a²+b²)（Oklab 口径）。"""
        try:
            return float(math_core.ok_L_C(self.h, self.s, self.v)[1])
        except Exception:
            return 0.0

    def _crel_arclen_t(self):
        """【已废弃】当前色点在「等明度线按弧长等分」上的归一化位置。

        C 条坐标改成线性（C_rel / C）后不再使用，保留仅为兼容旧探针脚本。
        """
        key = (round(self.h, 2), round(self.s, 5), round(self.v, 5), self.lightness_metric)
        if getattr(self, "_arclen_key", None) == key:
            return self._arclen_val
        val = self._crel_arclen_t_impl()
        self._arclen_key = key
        self._arclen_val = val
        return val

    def _crel_arclen_t_impl(self):
        try:
            ss, vv = math_core.iso_lightness_curve(
                self.h, float(math_core.lightness(self.h, self.s, self.v, self.lightness_metric)),
                self.lightness_metric, n_v=33, iters=12)
            if len(ss) < 2:
                return 0.0
            tt = math_core.curve_arclen(ss, vv)
            i = int((np.abs(ss - self.s) + np.abs(vv - self.v)).argmin())
            return float(tt[i])
        except Exception:
            return 0.0

    # ---- 色条回调 ----
    def _solve_v_for_lightness(self, h, s_fixed, l_target, iters=26):
        """固定色相/S，二分求使明度等于 l_target 的 V。"""
        lo, hi = 0.0, 1.0
        for _ in range(iters):
            mid = 0.5 * (lo + hi)
            if float(math_core.lightness(h, s_fixed, mid, self.lightness_metric)) < l_target:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    def _solve_s_for_lightness(self, h, l_target, iters=26):
        """固定 V=1，二分求使明度等于 l_target 的 S（用于目标明度在当前饱和度下达不到时）。"""
        lo, hi = 0.0, 1.0
        for _ in range(iters):
            mid = 0.5 * (lo + hi)
            if float(math_core.lightness(h, mid, 1.0, self.lightness_metric)) > l_target:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    def _on_strip_l_press(self):
        """明度条按下：重新锁定「C 条当前口径对应的保持量」；冻结红蓝过点线。

        相对口径保持 C_rel（与旧版一致）；绝对口径保持绝对 C —— 由 R6 规定。
        """
        self._strip_s0 = float(self.s)
        self._strip_crel = None       # 关键：每次按下重新锁定（此前会残留上次的 C_rel）
        self._strip_cabs = None
        self._strip_active = True
        self._preview_begin()
        self._dbg_strip_tag = "L"
        self._freeze_picker_lines("crel")     # 锁 C_rel → 蓝线冻结、红线实时
        if dlog.is_enabled():
            dlog.log("STRIP_L_DOWN", h=round(self.h, 3), s=round(self.s, 5),
                     v=round(self.v, 6), crel=round(self._crel_now(), 4),
                     cabs=round(self._cabs_now(), 4),
                     l=round(float(math_core.lightness(
                         self.h, self.s, self.v, self.lightness_metric)), 5))

    def _on_strip_c_press(self):
        """彩度条按下：锁定此刻的明度，并冻结红蓝过点线。"""
        self._strip_L = float(math_core.lightness(self.h, self.s, self.v, self.lightness_metric))
        self._strip_active = True
        self._preview_begin()
        self._dbg_strip_tag = "C"
        self._freeze_picker_lines("iso")      # 锁明度 → 红线冻结、蓝线实时
        if dlog.is_enabled():
            dlog.log("STRIP_C_DOWN", h=round(self.h, 3), s=round(self.s, 5),
                     v=round(self.v, 6), l=round(self._strip_L, 5))

    def _on_strip_release(self):
        self._strip_s0 = None
        self._strip_L = None
        self._strip_crel = None       # 松手解绑，避免下次拖动沿用旧 C_rel
        self._strip_cabs = None       # 绝对口径的锁定值同理
        self._clear_strip_ab_ctx()    # a/b 条同理（含 gray 可达区间缓存）
        self._strip_active = False    # 先解锁：松手后的刷新允许回读对齐
        self._update_hover_temp()     # 松手：按键仍按住且鼠标在面板内则恢复悬停预览
        if dlog.is_enabled():
            dlog.log("STRIP_UP", tag=getattr(self, "_dbg_strip_tag", "-"),
                     h=round(self.h, 3), s=round(self.s, 5), v=round(self.v, 6),
                     l=round(float(math_core.lightness(
                         self.h, self.s, self.v, self.lightness_metric)), 5),
                     crel=round(self._crel_now(), 4))
        self._freeze_picker_lines(None)
        self.refresh_status()
        self._push_history()          # 色条拖动结束也计入历史
        self._preview_start_countdown()      # 松手后才开始 2 秒倒计时

    def _freeze_picker_lines(self, mode):
        """按锁定线冻结过点线：mode = "iso"（锁明度）/ "crel"（锁彩度）/ None（全实时）。"""
        picker = getattr(self, "picker", None)
        if not _alive(picker):
            return
        picker.freeze_lines(mode)

    def _solve_v_at_s(self, h, s_fixed, l_target, iters=30):
        """固定色相/饱和度，二分求使明度等于目标的 V。"""
        lo, hi = 0.0, 1.0
        for _ in range(iters):
            mid = 0.5 * (lo + hi)
            if float(math_core.lightness(h, s_fixed, mid, self.lightness_metric)) < l_target:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    def _solve_s_at_white(self, h, l_target, s_max, iters=20):
        """V=1 时二分求使明度等于目标的 S（用于亮端退饱和），范围 [0, s_max]。"""
        lo, hi = 0.0, float(s_max)
        for _ in range(iters):
            mid = 0.5 * (lo + hi)
            if float(math_core.lightness(h, mid, 1.0, self.lightness_metric)) > l_target:
                lo = mid
            else:
                hi = mid
        return 0.5 * (lo + hi)

    def _lv_curve(self, hue, crel):
        """等 C_rel 曲线上「明度 -> (S,V)」采样表（顶部加密），按色相桶+C_rel 缓存。"""
        key = (round(hue / 2.0) * 2.0, round(float(crel), 4), self.lightness_metric)
        cache = getattr(self, "_lv_cache", None)
        if cache is None:
            cache = self._lv_cache = {}
        hit = cache.get(key)
        if hit is not None:
            dlog.log_throttled("LV_HIT", 120, key=key)
            return hit
        v = np.concatenate([
            np.geomspace(1e-3, 0.02, 21),
            np.linspace(0.02, 0.95, 74),
            np.linspace(0.95, 1.0, 51)[1:],     # 顶部加密（蓝线在此平滑收敛到纯白）
        ])
        s_arr = math_core.solve_s_at_crel(hue, self.lightness_metric, v, float(crel))
        ok = np.isfinite(s_arr)
        if int(ok.sum()) < 8:
            dlog.log("LV_FAIL", key=key, reason="finite", n=int(ok.sum()))
            return None
        s_arr, v = np.clip(s_arr[ok], 0.0, 1.0), v[ok]
        s_arr, v = math_core.filter_crel_line(hue, self.lightness_metric, s_arr, v)
        if len(s_arr) < 8:
            dlog.log("LV_FAIL", key=key, reason="filter", n=len(s_arr))
            return None
        # 近黑端：蓝线不可信段用「固定该线底端 S、把 V 从底端向 0 铺开」合成点，
        # 这样明度在 0 ~ 底端之间也是连续可插值的（否则会出现 0.0582 -> 0 的跳变）。
        s_bot, v_bot = float(s_arr[0]), float(v[0])
        if v_bot > 1e-6:
            v_dark = np.geomspace(1e-6, v_bot, 41)[:-1]
            s_dark = np.full_like(v_dark, s_bot)
            s_arr = np.concatenate([s_dark, s_arr])
            v = np.concatenate([v_dark, v])
        L = math_core.lightness(hue, s_arr, v, self.lightness_metric)
        order = np.argsort(L)
        L, v, s_arr = L[order], v[order], s_arr[order]
        L = np.maximum.accumulate(L)      # 保证插值用的 L 单调（消除数值抖动）
        out = (L, v, s_arr)
        if len(cache) > 48:
            cache.clear()
        cache[key] = out
        if dlog.is_enabled():
            dlog.log("LV_BUILD", key=key, n=len(L), L0=round(float(L[0]), 5),
                     L1=round(float(L[-1]), 5), s0=round(float(s_arr[0]), 5),
                     v0=round(float(v[0]), 6), v1=round(float(v[-1]), 6))
        return out

    def _eff_chroma_mode(self):
        """生效口径：优先拾色器临时口径（悬停预览 / 自动翻转），取不到时回落持久口径。"""
        picker = getattr(self, "picker", None)
        if _alive(picker):
            try:
                return picker.effective_chroma_mode()
            except Exception:
                pass
        return self.chroma_mode

    def _on_strip_lightness(self, t):
        """明度条：拖动时**保持生效口径对应的量**，只改明度。

        · 相对口径：沿蓝色轨迹线（等 C_rel 线）走 —— 按下时锁定当前 C_rel，
          在该线上建立「Oklab 明度 -> (S,V)」采样表，拖动时按目标明度查表取点；
        · 绝对口径：保持绝对彩度 C，直接解 (L_target, C) 的 (S,V)；
          目标明度够不到该 C 时钳到该明度上限（此时游标允许随之移动，属被钳不是漂移）。
        """
        self._dbg_ctx = "stripL"
        L_target = float(t) * 1.0
        if self._eff_chroma_mode() == "abs":
            self._on_strip_lightness_abs(L_target)
            return
        crel = self._strip_crel if getattr(self, "_strip_active", False) else None
        if crel is None:
            crel = self._crel_now()
            if getattr(self, "_strip_active", False):
                self._strip_crel = crel      # 拖动期间才锁定（数值框提交不写回这一个槽）
        dlog.log_throttled("STRIP_L", 8, t=round(float(t), 4), L_t=round(L_target, 5),
                           crel=round(float(crel), 4))
        if L_target <= 1e-9:
            dlog.log_throttled("STRIP_L_EDGE", 200, edge="black", t=round(float(t), 4))
            self.set_color(self.h, self.s, 0.0, write_fg=True)   # 纯黑
            return
        if L_target >= 1.0 - 1e-9:
            dlog.log_throttled("STRIP_L_EDGE", 200, edge="white", t=round(float(t), 4))
            self.set_color(self.h, 0.0, 1.0, write_fg=True)      # 纯白（蓝线的极限端点）
            return
        try:
            curve = self._lv_curve(self.h, crel)
            if curve is None:
                dlog.log_throttled("STRIP_L_SKIP", 200, reason="curve_none",
                                   t=round(float(t), 4), crel=round(float(crel), 4))
                return
            L_tab, v_tab, s_tab = curve
            if L_target > float(L_tab[-1]) + 1e-12:
                idx = len(L_tab) - 1
                dlog.log_throttled("STRIP_L_CLAMP", 200, side="high",
                                   t=round(float(t), 4), L_t=round(L_target, 5),
                                   L1=round(float(L_tab[-1]), 5))
                self.set_color(self.h, float(s_tab[idx]), float(v_tab[idx]), write_fg=True)
                return
            if L_target < float(L_tab[0]) - 1e-12:
                dlog.log_throttled("STRIP_L_CLAMP", 200, side="low",
                                   t=round(float(t), 4), L_t=round(L_target, 5),
                                   L0=round(float(L_tab[0]), 5))
            v_new = float(np.interp(L_target, L_tab, v_tab))
            s_new = float(np.interp(L_target, L_tab, s_tab))
            dlog.log_throttled("STRIP_L_HIT", 8, L_t=round(L_target, 5),
                               L0=round(float(L_tab[0]), 5), L1=round(float(L_tab[-1]), 5),
                               s=round(s_new, 5), v=round(v_new, 6))
            self.set_color(self.h, s_new, v_new, write_fg=True)
        except Exception:
            dlog.log("ERR", where="strip_lightness", tb=traceback.format_exc())
            return

    def _on_strip_lightness_abs(self, L_target):
        """绝对口径的明度条：保持绝对彩度 C，解 (L_target, C) 的 (S, V)。

        目标明度够不到该 C 时钳到该明度上限（C = C_max），此时 C 条游标允许移动。
        """
        cabs = self._strip_cabs if getattr(self, "_strip_active", False) else None
        if cabs is None:
            cabs = self._cabs_now()
            if getattr(self, "_strip_active", False):
                self._strip_cabs = cabs       # 拖动期间才锁定
        dlog.log_throttled("STRIP_L_ABS", 8, t=round(float(L_target), 4),
                           cabs=round(float(cabs), 4))
        try:
            s_new, v_new = math_core.sv_at_L_C(
                self.h, L_target, cabs, self.lightness_metric, clamp=True)
            self.set_color(self.h, s_new, v_new, write_fg=True)
        except Exception:
            dlog.log("ERR", where="strip_lightness_abs", tb=traceback.format_exc())

    def _on_strip_chroma_value(self, value):
        """彩度条 / 彩度数值框：按当前口径沿等明度线取点。

        统一走 sv_at_L_C：相对口径先换算成绝对 C 目标 = C_rel × C_max(L,h)，
        所以两种口径共用同一套解，不会出现两套插值口径对不上。
        """
        self._dbg_ctx = "stripC"
        try:
            # 明度锁定只在「C 条拖动」期间有效；数值框提交用当前色的明度
            L = self._strip_L if getattr(self, "_strip_active", False) else None
            if L is None:
                L = float(math_core.lightness(self.h, self.s, self.v, self.lightness_metric))
            eff = self._eff_chroma_mode()
            if eff == "rel":
                cmax = float(np.asarray(math_core.cmax_of_L(
                    self.h, self.lightness_metric, np.array([L])), dtype=np.float64)[0])
                c_abs = mc_clamp(float(value)) * cmax
            else:
                c_abs = float(value)
            s_x, v_x = math_core.sv_at_L_C(
                self.h, L, c_abs, self.lightness_metric, clamp=True)
            dlog.log_throttled("STRIP_C", 8, mode=eff,
                               val=round(float(value), 4), L=round(L, 5),
                               s=round(s_x, 5), v=round(v_x, 6))
            self.set_color(self.h, s_x, v_x, write_fg=True)
        except Exception:
            dlog.log("ERR", where="strip_chroma", tb=traceback.format_exc())

    def _on_strip_chroma(self, value):
        """彩度条回调：value 是**当前口径**的值（相对口径 = C_rel；绝对口径 = C）。"""
        self._on_strip_chroma_value(value)

    # ---- Oklab a/b 分量条（拖动只改本分量，明度与另一分量锁定）----
    def _apply_ab_visible(self):
        """按 show_ab 显示/收起 a/b 两行（标签 + 色条 + 数值框）。"""
        for w in (getattr(self, "lbl_a", None), getattr(self, "strip_a", None),
                  getattr(self, "edit_a", None), getattr(self, "lbl_b", None),
                  getattr(self, "strip_b", None), getattr(self, "edit_b", None)):
            if w is not None and _alive(w):
                w.setVisible(bool(self.show_ab))
        if _alive(getattr(self, "picker", None)):
            self._layout_picker()

    def _on_strip_ab_press(self, axis):
        """a/b 条按下：锁定当前口径 (M0, a, b) 与 Oklab L；拖动期间只改本分量。"""
        M0, a0, b0, L_ok, metric = self._ab_ctx_now()
        self._strip_ab_ctx = (M0, a0, b0)
        self._strip_ab_Lok = L_ok
        self._strip_ab_metric = metric
        self._strip_active = True
        # 按下时预计算并缓存 gray 切片区间与「目标灰阶可达」区间；
        # 拖动首帧只读缓存（interval 的计算从首帧挪到按下事件，语义不变）。
        if metric != "oklab":
            try:
                x0 = a0 if axis == "a" else b0
                other = b0 if axis == "a" else a0
                math_core.ab_axis_interval_seeded(L_ok, other, axis, seed=x0)
                self._ab_gray_component_interval(axis, other, M0, x0, l_hint=L_ok)
            except Exception:
                dlog.log("ERR", where="strip_ab_press_precompute",
                         tb=traceback.format_exc())
        self._preview_begin()
        self._dbg_strip_tag = "ok" + axis
        # R11：拖 a/b 时明度锁住但色相在变，等明度线形状本来就会变；冻结只会给出过期信息，
        # 所以两条过点线都实时（不再与方块内中/右键、L/C 条的「锁定线冻结」一致）。
        self._freeze_picker_lines(None)
        if dlog.is_enabled():
            dlog.log("STRIP_AB_DOWN", axis=axis, metric=metric, l=round(M0, 5),
                     lok=round(L_ok, 5), a=round(a0, 5), b=round(b0, 5))

    def _on_strip_ab(self, axis, value):
        """a/b 条拖动（或数值框提交）：固定「明度标准」的明度与另一分量，只改本分量。

        · oklab 口径：上下文就是 Oklab L，行为与旧版一字不变；
        · gray 口径：把本分量先钳进「目标灰阶仍可达」的区间（R30），
          再解 Oklab L 使灰阶 == 按下时刻的灰阶（一维二分），灰阶严格不变。

        本分量先按旧逻辑钳进「按下时刻 Oklab L 下 (另一分量) 的可达区间」，
        gray 口径再把值钳进目标灰阶可达区间（可能比前者窄，也可能在切片退化
        时给出切片外的最近端点）——这样 box 口径的死区拖不出 sRGB，
        目标灰阶在所有输入下都严格不变（与其它色条「拖到底即停」一致）。
        """
        self._dbg_ctx = "strip" + axis.upper()
        ctx = getattr(self, "_strip_ab_ctx", None)
        if ctx is None:
            M0, a0, b0, L_ok, metric = self._ab_ctx_now()
            ctx = self._strip_ab_ctx = (M0, a0, b0)
            self._strip_ab_Lok = L_ok
            self._strip_ab_metric = metric
        else:
            M0, a0, b0 = ctx
            L_ok = getattr(self, "_strip_ab_Lok", None)
            if L_ok is None:                 # 兼容外部直接塞入旧式 (L, a, b) 上下文
                L_ok = M0
            metric = getattr(self, "_strip_ab_metric", None) or "oklab"
        other = b0 if axis == "a" else a0
        x0 = a0 if axis == "a" else b0
        try:
            if metric == "oklab":
                # oklab 路径：与旧版一字不动（原 ab_axis_interval）
                lo, hi = math_core.ab_axis_interval(L_ok, other, axis)
            else:
                # gray 路径：旧栅格区间包含当前分量时保持旧行为；
                # 退化切片（如 h=60°,v=1 旧返回 (0,0) 不含 x0）改用 seed 精确区间。
                iv_seeded = math_core.ab_axis_interval_seeded(L_ok, other, axis, seed=x0)
                if iv_seeded is None:
                    lo, hi = math_core.ab_axis_interval(L_ok, other, axis)   # 明确空区间兜底
                else:
                    lo, hi = iv_seeded
            val = max(lo, min(hi, float(value)))
        except Exception:
            dlog.log("ERR", where="strip_ab_range", tb=traceback.format_exc())
            return
        if metric != "oklab":
            # R30：gray 口径下把本分量钳到「仍能解出目标灰阶」的区间端点。
            # 只动 gray 路径；oklab 路径的 val / L_use 一字不动。
            try:
                gl, gh = self._ab_gray_component_interval(axis, other, M0, x0, l_hint=L_ok)
                val = max(gl, min(gh, val))
            except Exception:
                dlog.log("ERR", where="strip_ab_gray_iv", tb=traceback.format_exc())
        a, b = (val, b0) if axis == "a" else (a0, val)
        try:
            if metric == "oklab":
                L_use = L_ok                     # 旧口径：按下时刻的 Oklab L 原样用
            else:
                L_use = self._solve_ab_L_metric(M0, metric, a, b)
            rgb = math_core.oklab_to_srgb(L_use, a, b)
            h, s, v = math_core.srgb_to_hsv(float(rgb[0]), float(rgb[1]), float(rgb[2]))
        except Exception:
            dlog.log("ERR", where="strip_ab", tb=traceback.format_exc())
            return
        dlog.log_throttled("STRIP_AB", 8, axis=axis, metric=metric, l=round(L_use, 5),
                           a=round(a, 5), b=round(b, 5), lo=round(lo, 5), hi=round(hi, 5))
        self.set_color(h, s, v, write_fg=True)

    def _sync_old_entries(self):
        """（保留旧接口名，避免外部误用）"""
        self._sync_entries()
        self.edit_s.setText("%.2f" % (self.s * 100.0))
        self.edit_v.setText("%.2f" % (self.v * 100.0))
        self.edit_hex.setText("#%02X%02X%02X" % self.picker_rgb())

    # ------------------------------------------------- 数值框回写
    # ------------------------------------------------- 数值框回写
    def _on_entry_commit(self):
        self._editing_field = None
        self._entry_dragging = False
        self._dbg_ctx = "-"
        self._update_hover_temp()    # 拖动结束：按当前悬停 + 按键 + 文本框焦点状态恢复预览
        sender = self.sender()
        if sender is None:
            self._preview_start_countdown()
            return
        self.apply_entry_text(sender, sender.text())
        self._preview_start_countdown()      # 提交结束才开始 2 秒倒计时

    def apply_entry_text(self, sender, text):
        """把某个数值框的文本应用到当前颜色（可脱离 Qt 信号单独测试）。"""
        field = "?"
        for name, widget in (("h", self.edit_h), ("s", self.edit_s), ("v", self.edit_v),
                             ("hex", self.edit_hex), ("l", self.edit_l), ("c", self.edit_c),
                             ("a", getattr(self, "edit_a", None)),
                             ("b", getattr(self, "edit_b", None))):
            if sender is widget:
                field = name
                break
        self._dbg_ctx = "entry_" + field
        self._preview_begin()       # 本轮操作开始前的「上一次选色」
        dlog.log("ENTRY", field=field, text=text.strip())
        try:
            if sender is self.edit_h:
                self.set_color(math_core.parse_hue(text), self.s, self.v, write_fg=True)
            elif sender is self.edit_s:
                self.set_color(self.h, math_core.parse_ratio(text), self.v, write_fg=True)
            elif sender is self.edit_v:
                self.set_color(self.h, self.s, math_core.parse_ratio(text), write_fg=True)
            elif sender is self.edit_hex:
                r, g, b = math_core.parse_hex(text)
                h, s, v = math_core.srgb_to_hsv(r / 255.0, g / 255.0, b / 255.0)
                self.set_color(h, s, v, write_fg=True)
            elif sender is self.edit_l:
                self._on_strip_lightness(float(text))
            elif sender is self.edit_c:
                self._on_strip_chroma(float(text))
            elif sender is getattr(self, "edit_a", None):
                # R29：数值框提交 = 以当前颜色为上下文；提交完即清，
                # 避免换色后再提交沿用旧 (L / 另一分量 / 灰阶)。
                self._clear_strip_ab_ctx()
                try:
                    self._on_strip_ab("a", math_core.parse_number(text))
                finally:
                    self._clear_strip_ab_ctx()
            elif sender is getattr(self, "edit_b", None):
                self._clear_strip_ab_ctx()
                try:
                    self._on_strip_ab("b", math_core.parse_number(text))
                finally:
                    self._clear_strip_ab_ctx()
        except (ValueError, TypeError, IndexError):
            dlog.log("ENTRY_BAD", field=field, text=text.strip())
            self._sync_entries()
            self._status.setText(i18n.t("输入无法识别，已还原：%s",
                                        "Unrecognized input, restored: %s") % text.strip())
            return
        self._push_history()          # 数值框提交成功也计入历史

    # ------------------------------------------------- 状态与当前色小色块
    def refresh_status(self):
        if self._dirty and not self._interacting():
            self._pull_from_krita("dirty")
        if _alive(getattr(self, "swatch_cur", None)):
            self.swatch_cur.set_color(QColor(*self.picker_rgb()))
        self._status.setText("")

    # ------------------------------------------------- 预览浮层（独立小窗）
    def preview_overlay(self):
        """预览浮层对象（惰性创建；独立小窗，不抢焦点、不吃鼠标）。"""
        ov = getattr(self, "_overlay", None)
        if ov is None or not _alive(ov):
            ov = preview_overlay.PreviewOverlay()
            self._overlay = ov
        return ov

    def _preview_begin(self):
        """新一轮操作开始：记下下排两格（history[0]=上一次、history[1]=上上次），本轮内保持不变。"""
        self._preview_last_rgb = self._history_rgb(0)
        self._preview_older_rgb = self._history_rgb(1)

    def _history_rgb(self, index):
        """我们自己的颜色历史里第 index 条（0=最新）；不足或坏数据返回 None。"""
        colors = getattr(getattr(self, "history", None), "colors", None) or []
        if index < 0 or index >= len(colors):
            return None
        try:
            return tuple(int(v) for v in math_core.parse_hex(colors[index]))
        except Exception:
            return None

    def _preview_anchor(self):
        """浮层锚点（全局矩形），每次调用都重算。

        口径 = **面板的水平范围 + 拾色器的上沿 + 面板的下沿**：
        这样浮层贴右/左/下/上都落在面板之外，**不会压住面板自身（含右侧历史列）**；
        同时仍然跟着面板 / 拾色器一起动（150ms 重锚定）。

        拾色器不可见（面板隐藏 / 弹窗关闭）、已销毁、宽高为 0 时返回 None（调用方会收起浮层）。
        面板从未显示过（离屏初始化 / 离屏测试）时不做可见性判定。
        """
        picker = getattr(self, "picker", None)
        if picker is None or not _alive(picker) or picker.width() <= 0 or self.width() <= 0:
            return None
        try:
            from PyQt5.QtCore import QPoint, QRect
            if not picker.isVisible() and getattr(self, "_was_shown", False):
                return None
            picker_tl = picker.mapToGlobal(QPoint(0, 0))
            panel_tl = self.mapToGlobal(QPoint(0, 0))
            top = int(picker_tl.y())
            bottom = int(panel_tl.y()) + int(self.height())
            if bottom - top < 1:
                bottom = top + 1
            return QRect(int(panel_tl.x()), top, int(self.width()), bottom - top)
        except Exception:
            return None

    # ------------------------------------------------- 浮层跟随拾色器（150ms 重锚定）
    def _preview_follow_start(self):
        """浮层显示期间启动跟随定时器（隐藏/销毁时务必停表，不常驻轮询）。"""
        timer = getattr(self, "_preview_follow", None)
        if timer is None:
            return
        try:
            if not timer.isActive():
                timer.start()
        except Exception:
            pass

    def _preview_follow_stop(self):
        timer = getattr(self, "_preview_follow", None)
        if timer is not None:
            try:
                timer.stop()
            except Exception:
                pass

    def _preview_follow_tick(self):
        """一次重锚定：拾色器没了/不可见就收起浮层；否则按新几何重走「右→左→下→上」。"""
        ov = getattr(self, "_overlay", None)
        if ov is None or not _alive(ov) or not ov.isVisible():
            self._preview_follow_stop()
            return
        anchor = self._preview_anchor()
        if anchor is None:
            self._preview_hide_now()
            self._preview_follow_stop()
            return
        try:
            ov.show_near(anchor)
        except Exception:
            pass

    def _preview_enabled(self):
        """当前模式是否要显示浮层（off = 完全不显示）。"""
        return getattr(self, "preview_mode", PREVIEW_DEFAULT_MODE) != "off"

    def _preview_delay_ms(self):
        """「1 秒」（1000ms）/「2 秒」（2000ms）模式的倒计时时长；hover/always/off 用不到。"""
        mode = getattr(self, "preview_mode", PREVIEW_DEFAULT_MODE)
        if mode == "1s":
            return PREVIEW_SHORT_MS
        if mode == "2s":
            return int(getattr(self, "preview_hide_ms", PREVIEW_HIDE_MS))
        return 0

    def _preview_update(self, start_countdown=None):
        """改色时刷新浮层：显示 + 三格取值。

        start_countdown=None：按当前交互状态判断（拖动中不倒计时、松手后才计时）。
        """
        if not self._preview_enabled():
            self._preview_hide_now()
            return None
        if self._preview_last_rgb is _UNSET or self._preview_older_rgb is _UNSET:
            self._preview_begin()      # 兜底：没走过 _preview_begin 的调用
        if start_countdown is None:
            start_countdown = not self._interacting()
        try:
            ov = self.preview_overlay()
            was_visible = ov.isVisible()
            ov.show_colors(self.picker_rgb(), self._preview_older_rgb,
                           self._preview_last_rgb)
            if not was_visible:
                anchor = self._preview_anchor()
                if anchor is not None:
                    ov.show_near(anchor)
            if self.preview_mode == "always":
                ov.cancel_hide()
            elif start_countdown:
                ov.hide_after(self._preview_delay_ms())
            else:
                ov.cancel_hide()
            self._preview_follow_start()
            return ov
        except Exception:
            return None

    def _preview_start_countdown(self):
        """松手 / 提交结束：浮层若在显示就按当前模式启动（或重置）倒计时。"""
        if not self._preview_enabled():
            return
        ov = getattr(self, "_overlay", None)
        if ov is None or not _alive(ov) or not ov.isVisible():
            return
        try:
            if self.preview_mode == "always":
                ov.cancel_hide()                 # 一直：不隐藏
                return
            if self.preview_mode == "hover":
                if getattr(self, "_picker_hovered", False):
                    ov.cancel_hide()             # 鼠标仍在拾色器上：保持显示
                else:
                    self._preview_hide_now()     # 鼠标不在拾色器上：立即隐藏
                return
            ov.hide_after(self._preview_delay_ms())   # 1 秒 / 2 秒
        except Exception:
            pass

    def _on_picker_hover_enter(self):
        """鼠标移进拾色器：仅在「悬停」模式显示（不改色也显示），并在拾色器内一直保持。"""
        self._picker_hovered = True
        if getattr(self, "preview_mode", PREVIEW_DEFAULT_MODE) != "hover":
            return
        self._preview_begin()
        self._preview_update(start_countdown=False)

    def _on_picker_hover_leave(self):
        """鼠标移出拾色器（仅「悬停」模式）：**立即隐藏**（无延迟、无淡出）。

        拖动中不处理：松手时由 `_preview_start_countdown()` 统一判定（鼠标不在拾色器内就立即隐藏）。
        """
        self._picker_hovered = False
        if getattr(self, "preview_mode", PREVIEW_DEFAULT_MODE) != "hover":
            return
        if self._interacting():
            return
        self._preview_hide_now()

    def _preview_hide_now(self):
        """立刻收起浮层并停掉跟随定时器（关掉设置项 / 面板隐藏 / 拾色器消失时用）。"""
        self._preview_follow_stop()
        ov = getattr(self, "_overlay", None)
        if ov is not None and _alive(ov):
            try:
                ov.hide_now()
            except Exception:
                pass

    # ------------------------------------------------- T-53 全局临时切换键 + 悬停预览
    def set_temp_chroma_key(self, key, _broadcast=True):
        """临时切换键：8 种 MOD_ID（none = 不自动翻转）；持久化 + 双面板同步 + 即时刷新。"""
        key = str(key)
        if key not in keymap_core.MOD_IDS:
            key = "shift"
        self.temp_chroma_key = key
        try:
            Krita.instance().writeSetting("", TEMP_CHROMA_KEY_KEY, key)
        except Exception:
            pass
        act = (getattr(self, "temp_key_actions", None) or {}).get(key)
        if _alive(act) and not act.isChecked():
            act.setChecked(True)          # 互斥组：其余项自动取消勾选
        if _alive(getattr(self, "picker", None)):
            self.picker.set_temp_chroma_key(key)
        self._update_hover_temp()
        if _broadcast:
            for cb in getattr(self, "view_listeners", []) or []:
                try:
                    cb("temp_chroma_key", key)
                except Exception:
                    pass

    def _kb_mod_id(self):
        """显式维护的 Shift/Ctrl/Alt 状态 -> MOD_ID。"""
        return keymap_core.mods_from_bools(self._kb_shift, self._kb_ctrl, self._kb_alt)

    def _kb_clear(self):
        self._kb_shift = False
        self._kb_ctrl = False
        self._kb_alt = False

    def _hover_key_active(self):
        """当前修饰键是否包含全局临时切换键的全部位；none 恒为 False。"""
        return keymap_core.mod_contains(self._kb_mod_id(),
                                        getattr(self, "temp_chroma_key", "shift"))

    def _current_hover_mod_id(self):
        """当前显式修饰键状态 ID（与键表 MOD_IDS 同口径）。"""
        return self._kb_mod_id()

    def _text_input_has_focus(self):
        """文本输入框有焦点时暂停悬停预览（Shift 打大写不闪烁）。"""
        try:
            from PyQt5.QtWidgets import QAbstractSpinBox, QApplication, QLineEdit
            w = QApplication.focusWidget()
            return isinstance(w, (QLineEdit, QAbstractSpinBox))
        except Exception:
            return False

    def _cursor_inside_panel(self):
        """鼠标命中的控件是否属于本面板：widgetAt + parentWidget 父链；主面板与弹窗各自判定。"""
        try:
            from PyQt5.QtGui import QCursor
            from PyQt5.QtWidgets import QApplication
            w = QApplication.widgetAt(QCursor.pos())
            while w is not None:
                if w is self:
                    return True
                w = w.parentWidget()
        except Exception:
            pass
        return False

    def _update_hover_temp(self):
        """按住切换键且鼠标在面板内时临时预览另一口径；幂等、不写设置不广播。"""
        if not _alive(getattr(self, "picker", None)):
            return
        if self._interacting():
            return                  # 拖动中口径按下定死，悬停刷新不得改（松手后由调用方重算）
        target = None
        if self._panel_hovered and not self._hover_suspended:
            try:
                if not self._text_input_has_focus() and self._hover_key_active():
                    target = ("abs" if self.chroma_mode == "rel" else "rel")
            except Exception:
                target = None
        if self.picker.temp_chroma_mode != target:
            self.picker.set_temp_chroma_mode(target)
            self._sync_entries()

    def _refresh_panel_hover(self):
        """用 widgetAt(鼠标位置) 重算悬停状态并刷新预览（修正时好时坏）。"""
        inside = self._cursor_inside_panel()
        self._panel_hovered = inside
        self._update_hover_temp()

    def _on_app_key_event(self, event):
        """KeyPress/KeyRelease -> 显式维护 Shift/Ctrl/Alt 状态，松开立刻清位。"""
        try:
            down = (event.type() == QEvent.KeyPress)
            key = event.key()
            if key == Qt.Key_Shift:
                self._kb_shift = down
            elif key == Qt.Key_Control:
                self._kb_ctrl = down
            elif key == Qt.Key_Alt:
                self._kb_alt = down
        except Exception:
            pass

    def _sync_kb_from_mouse(self, event):
        """鼠标事件自带 modifiers：补齐「进入应用前就已按住」的键，避免漏按。"""
        try:
            mods = event.modifiers()
        except Exception:
            return
        self._kb_shift = bool(mods & Qt.ShiftModifier)
        self._kb_ctrl = bool(mods & Qt.ControlModifier)
        self._kb_alt = bool(mods & Qt.AltModifier)

    def _sync_kb_from_app(self):
        """窗口重新激活 / 重新显示时按 Qt 当前修饰键状态校准一次（不在 KeyPress 过滤器里用）。"""
        try:
            from PyQt5.QtWidgets import QApplication
            app = QApplication.instance()
            if app is None:
                return
            mods = app.keyboardModifiers()
        except Exception:
            return
        self._kb_shift = bool(mods & Qt.ShiftModifier)
        self._kb_ctrl = bool(mods & Qt.ControlModifier)
        self._kb_alt = bool(mods & Qt.AltModifier)

    def _install_hover_filter(self):
        """安装应用级事件过滤器（按键 / 鼠标 / 焦点 / 应用激活 -> 刷新悬停预览）。"""
        if getattr(self, "_hover_filter_installed", False):
            return
        from PyQt5.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            return
        app.installEventFilter(self)
        self._hover_filter_installed = True

    def _remove_hover_filter(self):
        """移除应用级事件过滤器（面板销毁时调用，避免残留钩子）。"""
        if not getattr(self, "_hover_filter_installed", False):
            return
        try:
            from PyQt5.QtWidgets import QApplication
            app = QApplication.instance()
            if app is not None:
                app.removeEventFilter(self)
        except Exception:
            pass
        self._hover_filter_installed = False

    def eventFilter(self, obj, event):
        """应用级过滤器：刷新切换键悬停预览，不消费事件。"""
        try:
            et = event.type()
            if et in (QEvent.KeyPress, QEvent.KeyRelease):
                self._on_app_key_event(event)
                self._refresh_panel_hover()
            elif et in (QEvent.MouseMove, QEvent.MouseButtonPress,
                        QEvent.MouseButtonRelease, QEvent.Wheel):
                self._sync_kb_from_mouse(event)
                self._refresh_panel_hover()
            elif et in (QEvent.FocusIn, QEvent.FocusOut, QEvent.Enter, QEvent.Leave):
                self._refresh_panel_hover()
            elif et in (QEvent.ApplicationDeactivate,
                        getattr(QEvent, "WindowDeactivate", None)):
                self._kb_clear()
                if et == QEvent.ApplicationDeactivate:
                    self._hover_suspended = True
                self._update_hover_temp()
            elif et in (QEvent.ApplicationActivate,
                        getattr(QEvent, "WindowActivate", None)):
                self._hover_suspended = False
                self._sync_kb_from_app()   # 激活时校准一次；随后按键/鼠标事件继续维护
                self._refresh_panel_hover()
        except Exception:
            pass
        return super().eventFilter(obj, event)

    def enterEvent(self, event):
        self._refresh_panel_hover()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._refresh_panel_hover()
        super().leaveEvent(event)

    def _on_panel_destroyed(self, *args):
        """面板销毁：清悬停预览 + 移除过滤器 + 收掉浮层，避免留下独立小窗/残留钩子。"""
        self._panel_hovered = False
        self._kb_clear()
        try:
            if _alive(getattr(self, "picker", None)):
                self.picker.set_temp_chroma_mode(None)
        except Exception:
            pass
        self._remove_hover_filter()
        self._preview_follow_stop()
        ov = getattr(self, "_overlay", None)
        if ov is not None:
            try:
                ov.hide()
                ov.deleteLater()
            except Exception:
                pass
        self._overlay = None

    def hideEvent(self, event):
        self._panel_hovered = False
        self._hover_suspended = False
        self._update_hover_temp()     # T-53：面板隐藏立即清悬停预览
        self._preview_hide_now()      # 面板隐藏（弹窗关闭等）：浮层不单独飘着
        super().hideEvent(event)

    # ------------------------------------------------- 二级菜单配置
    # ------------------------------------------------- Oklab a/b 条设置
    def set_show_ab(self, checked, _broadcast=True):
        """显示/收起 Oklab a/b 分量条（默认开；设置持久化）。"""
        self.show_ab = bool(checked)
        try:
            Krita.instance().writeSetting("", SHOW_AB_KEY, "1" if self.show_ab else "0")
        except Exception:
            pass
        if _alive(getattr(self, "act_show_ab", None)) and \
                self.act_show_ab.isChecked() != self.show_ab:
            self.act_show_ab.blockSignals(True)
            self.act_show_ab.setChecked(self.show_ab)
            self.act_show_ab.blockSignals(False)
        self._apply_ab_visible()
        self._sync_entries()
        if _broadcast:
            for cb in getattr(self, "view_listeners", []) or []:
                try:
                    cb("show_ab", self.show_ab)
                except Exception:
                    pass

    def set_ab_mode(self, mode, _broadcast=True):
        """a/b 条量程口径：box=当前明度切片包围盒（默认，刻度稳）/ line=单线可行区间。"""
        self.ab_mode = mode if mode in ("box", "line") else "box"
        try:
            Krita.instance().writeSetting("", AB_MODE_KEY, self.ab_mode)
        except Exception:
            pass
        for strip in (getattr(self, "strip_a", None), getattr(self, "strip_b", None)):
            if _alive(strip):
                strip.set_mode(self.ab_mode)
        want_line = (self.ab_mode == "line")
        if _alive(getattr(self, "act_ab_line", None)) and \
                self.act_ab_line.isChecked() != want_line:
            self.act_ab_line.blockSignals(True)
            self.act_ab_line.setChecked(want_line)
            self.act_ab_line.blockSignals(False)
        self._sync_entries()
        if _broadcast:
            for cb in getattr(self, "view_listeners", []) or []:
                try:
                    cb("ab_mode", self.ab_mode)
                except Exception:
                    pass

    def set_ab_mode_line(self, checked, _broadcast=True):
        """菜单勾选：勾=满量程可达（line）；不勾=切片包围盒（box，默认）。"""
        self.set_ab_mode("line" if checked else "box", _broadcast)

    # ------------------------------------------------- C 条口径（相对 / 绝对）+ 色环提示 + 两个交换开关
    def _apply_chroma_label(self, mode=None):
        """C 条标签与工具提示跟随口径（相对彩度 C_rel / 绝对彩度 C）。

        mode 缺省 = 持久口径；面板临时口径显示期间由 `_sync_entries` 传入生效口径。
        """
        mode = self.chroma_mode if mode is None else \
            ("abs" if str(mode) == "abs" else "rel")
        if mode == "rel":
            tip = i18n.t("相对彩度 C_rel = C / C_max(L,h)（0~1；1 = 该明度/色相下最饱和）",
                         "Relative chroma C_rel = C / C_max(L,h) (0-1; 1 = most saturated)")
        else:
            rng = i18n.t("满量程 0~C_max(L,h)", "full range 0 to C_max(L,h)") \
                if self.chroma_full else i18n.t("固定量程 0~0.4", "fixed range 0-0.4")
            tip = i18n.t("绝对彩度 C = √(a²+b²)（Oklab 口径；%s）",
                         "Absolute chroma C = sqrt(a^2+b^2) (Oklab; %s)") % rng
        for w in (getattr(self, "lbl_c", None), getattr(self, "edit_c", None),
                  getattr(self, "strip_c", None)):
            if w is not None and _alive(w):
                w.setToolTip(tip)

    def set_chroma_mode(self, mode, _broadcast=True):
        """C 条口径：rel = 相对彩度 C_rel（默认）/ abs = 绝对彩度 C；设置持久化。"""
        mode = "abs" if str(mode) == "abs" else "rel"
        self.chroma_mode = mode
        try:
            Krita.instance().writeSetting("", CHROMA_MODE_KEY, mode)
        except Exception:
            pass
        act = (getattr(self, "chroma_actions", None) or {}).get(mode)
        if _alive(act) and not act.isChecked():
            act.setChecked(True)          # 互斥组：其余项自动取消勾选
        if _alive(getattr(self, "strip_c", None)):
            self.strip_c.set_mode(self.chroma_mode, self.chroma_full)
        self._apply_chroma_label()
        self._sync_entries()
        self._update_hover_temp()      # T-53：持久口径变化时，若正在悬停预览按新口径重算另一口径
        if _broadcast:
            for cb in getattr(self, "view_listeners", []) or []:
                try:
                    cb("chroma_mode", self.chroma_mode)
                except Exception:
                    pass

    def set_chroma_full(self, checked, _broadcast=True):
        """绝对口径的 C 条量程：勾 = 满量程 [0, C_max]（无死区）；不勾（默认）= 固定 [0, 0.4]。"""
        self.chroma_full = bool(checked)
        try:
            Krita.instance().writeSetting("", CHROMA_FULL_KEY, "1" if self.chroma_full else "0")
        except Exception:
            pass
        if _alive(getattr(self, "act_c_full", None)) and \
                self.act_c_full.isChecked() != self.chroma_full:
            self.act_c_full.blockSignals(True)
            self.act_c_full.setChecked(self.chroma_full)
            self.act_c_full.blockSignals(False)
        if _alive(getattr(self, "strip_c", None)):
            self.strip_c.set_mode(self.chroma_mode, self.chroma_full)
        self._apply_chroma_label()
        self._sync_entries()
        if _broadcast:
            for cb in getattr(self, "view_listeners", []) or []:
                try:
                    cb("chroma_full", self.chroma_full)
                except Exception:
                    pass

    def set_abs_cluster_mode(self, mode, _broadcast=True):
        """绝对 C 线簇密度：fixed（默认，0.02~0.36 共 18 档）/ even（按色相纯色 C_max 等分 9 档）。

        持久化 + Docker ↔ 弹窗双向同步；线簇缓存 key 带该模式。
        """
        mode = "even" if str(mode) == "even" else "fixed"
        self.abs_cluster_mode = mode
        try:
            Krita.instance().writeSetting("", CHROMA_ABS_CLUSTER_KEY, mode)
        except Exception:
            pass
        act = getattr(self, "act_c_cluster_even", None)
        want_even = (mode != "fixed")
        if _alive(act) and act.isChecked() != want_even:
            act.blockSignals(True)
            act.setChecked(want_even)
            act.blockSignals(False)
        if _alive(getattr(self, "picker", None)):
            self.picker.set_abs_cluster_mode(mode)
        self._sync_entries()
        if _broadcast:
            for cb in getattr(self, "view_listeners", []) or []:
                try:
                    cb("chroma_abs_cluster", self.abs_cluster_mode)
                except Exception:
                    pass

    def set_abs_cluster_even(self, checked, _broadcast=True):
        """菜单勾选：勾 = even（等分 9 档）/ 不勾 = fixed（默认，18 档）。"""
        self.set_abs_cluster_mode("even" if checked else "fixed", _broadcast)

    # ------------------------------------------------- 明度标准（Oklab L / 灰阶）
    def _apply_lightness_metric(self):
        """把当前明度标准灌进拾色器 / L 条 / C 条，并刷新 L 标签与色条提示。"""
        m = self.lightness_metric
        if _alive(getattr(self, "picker", None)):
            self.picker.set_metric(m)
        if _alive(getattr(self, "strip_l", None)):
            self.strip_l.metric = m
            self.strip_l._cache_key = None
            self.strip_l.update()
            self.strip_l.setToolTip(i18n.t(
                "明度条（灰阶口径）：左黑右白，读数 = srgb_encode(Y)" if m == "gray"
                else "明度条：左黑右白，读数 = Oklab L",
                "Lightness strip (grayscale): dark to light, readout = srgb_encode(Y)"
                if m == "gray" else "Lightness strip: dark to light, readout = Oklab L"))
        if _alive(getattr(self, "strip_c", None)):
            self.strip_c.set_metric(m)
        if _alive(getattr(self, "lbl_l", None)):
            self.lbl_l.setToolTip(i18n.t(
                "灰阶码值 srgb_encode(Y)（0~1；Krita 软打样灰块口径）" if m == "gray"
                else "Oklab 明度 L（0~1）",
                "Grayscale code value srgb_encode(Y) (0-1; Krita soft-proof gray)"
                if m == "gray" else "Oklab lightness L (0-1)"))

    def set_lightness_metric(self, mode, _broadcast=True):
        """明度标准：oklab = Oklab L（默认，零影响）/ gray = 灰阶码值（色彩校样口径）。

        持久化 + 广播；Docker ↔ 弹窗双向同步。只换 L 轴，彩度仍是 Oklab C。
        """
        mode = "gray" if str(mode) == "gray" else "oklab"
        self.lightness_metric = mode
        try:
            Krita.instance().writeSetting("", LIGHTNESS_METRIC_KEY, mode)
        except Exception:
            pass
        act = (getattr(self, "metric_actions", None) or {}).get(mode)
        if _alive(act) and not act.isChecked():
            act.setChecked(True)          # 互斥组：其余项自动取消勾选
        self._apply_lightness_metric()
        self._sync_entries()
        if _broadcast:
            for cb in getattr(self, "view_listeners", []) or []:
                try:
                    cb("lightness_metric", mode)
                except Exception:
                    pass

    def set_show_unreachable(self, checked, _broadcast=True):
        """色环「不可达色相」提示（默认开）：只叠细斜纹、不填灰底，不影响点击/拖动。"""
        self.show_unreachable = bool(checked)
        try:
            Krita.instance().writeSetting("", SHOW_UNREACHABLE_KEY,
                                          "1" if self.show_unreachable else "0")
        except Exception:
            pass
        if _alive(getattr(self, "act_unreachable", None)) and \
                self.act_unreachable.isChecked() != self.show_unreachable:
            self.act_unreachable.blockSignals(True)
            self.act_unreachable.setChecked(self.show_unreachable)
            self.act_unreachable.blockSignals(False)
        if _alive(getattr(self, "picker", None)):
            self.picker.set_show_unreachable(self.show_unreachable)
        if _broadcast:
            for cb in getattr(self, "view_listeners", []) or []:
                try:
                    cb("unreachable", self.show_unreachable)
                except Exception:
                    pass

    # ------------------------------------------------- 自定义按键表（R14）
    def set_keymap(self, keymap, _broadcast=True):
        """写入自定义按键表：即时生效 + 持久化 + 广播到对端面板。"""
        self.keymap = keymap_core.normalize(keymap)
        try:
            Krita.instance().writeSetting("", KEYMAP_KEY, keymap_core.dump(self.keymap))
        except Exception:
            pass
        self._apply_keymap()
        self._update_hover_temp()      # T-53：键表精确行可能变化，立即重算悬停预览
        dlg = getattr(self, "_keymap_dialog", None)
        if _alive(dlg) and dlg.keymap != self.keymap:
            dlg.set_keymap(self.keymap)
        if _broadcast:
            for cb in getattr(self, "view_listeners", []) or []:
                try:
                    cb("keymap", self.keymap)
                except Exception:
                    pass

    def reset_keymap(self, _broadcast=True):
        """恢复默认按键表并即时生效。"""
        self.set_keymap(keymap_core.default_keymap(), _broadcast=_broadcast)

    def _apply_keymap(self):
        """把当前按键表灌进拾色器 / 四条色条 / 可拖动数值框。"""
        if _alive(getattr(self, "picker", None)):
            self.picker.set_keymap(self.keymap)
        for name in ("strip_l", "strip_c", "strip_a", "strip_b",
                     "edit_h", "edit_s", "edit_v"):
            widget = getattr(self, name, None)
            if widget is not None and hasattr(widget, "set_keymap"):
                widget.set_keymap(self.keymap)

    # ------------------------------------------------- 置顶 / 「按键功能…」对话框（R18）
    def effective_top(self):
        """当前**实际生效**的置顶状态：记忆值 AND not「点击面板外自动关闭」。

        与弹窗窗口标志同口径；「按键功能…」对话框打开时按此继承置顶。
        """
        return bool(getattr(self, "always_on_top", True)
                    and not getattr(self, "auto_close_popup", True))

    def _keymap_parent(self):
        """「按键功能…」对话框的宿主：弹窗内打开用弹窗，Docker 内打开用 Docker 面板。"""
        host = getattr(self, "dialog_host", None)
        if host is not None:
            return host
        w = self.parentWidget()
        while w is not None:
            if isinstance(w, (HsvPickerPopup, HsvPickerDocker)):
                return w
            w = w.parentWidget()
        return self.window() or self

    def show_keymap_dialog(self):
        """打开/复用「按键功能…」对话框（R18：继承实际置顶 + 宿主作 parent）。"""
        dlg = getattr(self, "_keymap_dialog", None)
        if not _alive(dlg):
            dlg = keymap_dialog.KeymapDialog(self._keymap_parent(),
                                             on_change=self.set_keymap)
            self._keymap_dialog = dlg
            try:
                dlg.finished.connect(self._on_keymap_dialog_finished)
            except Exception:
                pass
        self._keymap_dialog_wanted = True
        self._keymap_dialog_hidden_by_host = False
        dlg.apply_effective_top(self.effective_top())
        dlg.set_keymap(self.keymap)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()
        self._sync_keymap_dialog_visibility()

    def _on_keymap_dialog_finished(self, *_args):
        """用户手动关闭对话框：清掉「应为打开」意图，避免宿主恢复时又自动弹出。"""
        self._keymap_dialog_wanted = False
        self._keymap_dialog_hidden_by_host = False

    def _sync_keymap_dialog_visibility(self):
        """R24：宿主隐藏/关闭 -> 关闭对话框；宿主最小化 -> 隐藏、恢复 -> 重新显示。

        宿主侧在 hideEvent / changeEvent(WindowStateChange) 里调用本方法，不轮询。
        只处理「用户打开过、且尚未手动关闭」的对话框。
        """
        dlg = getattr(self, "_keymap_dialog", None)
        if not _alive(dlg) or not getattr(self, "_keymap_dialog_wanted", False):
            return
        host = getattr(self, "dialog_host", None)
        visible, minimized = True, False
        if host is not None and _alive(host):
            try:
                visible = bool(host.isVisible())
                minimized = bool(host.isMinimized()) or bool(
                    int(host.windowState()) & int(Qt.WindowMinimized))
            except Exception:
                visible, minimized = True, False
        if minimized:
            if dlg.isVisible():
                self._keymap_dialog_hidden_by_host = True
                try:
                    dlg.hide()
                except Exception:
                    pass
            return
        if not visible:
            # 宿主隐藏/关闭：对话框一并关闭（之后宿主再显示也不再自动弹出）
            self._keymap_dialog_wanted = False
            self._keymap_dialog_hidden_by_host = False
            try:
                dlg.close()
            except Exception:
                pass
            return
        if getattr(self, "_keymap_dialog_hidden_by_host", False):
            self._keymap_dialog_hidden_by_host = False
            if not dlg.isVisible():
                try:
                    dlg.show()
                    dlg.raise_()
                except Exception:
                    pass

    def _refresh_keymap_dialog(self):
        """按键表变化时，若对话框已打开则实时刷新。"""
        dlg = getattr(self, "_keymap_dialog", None)
        if _alive(dlg):
            dlg.set_keymap(self.keymap)

    def _refresh_keymap_dialog_top(self):
        """置顶设置变化时，若「按键功能…」对话框已打开则实时刷新窗口标志（R18）。"""
        dlg = getattr(self, "_keymap_dialog", None)
        if _alive(dlg):
            try:
                dlg.apply_effective_top(self.effective_top())
            except Exception:
                pass

    # ------------------------------------------------- 浮层选项（持久化 + 广播）
    def set_preview_mode(self, mode, _broadcast=True):
        """浮层选项：off（关闭）/ 1s / 2s / hover（默认）/ always（一直显示）；设置持久化。"""
        mode = str(mode or "").strip()
        if mode not in PREVIEW_MODES:
            mode = PREVIEW_DEFAULT_MODE
        self.preview_mode = mode
        try:
            Krita.instance().writeSetting("", PREVIEW_MODE_KEY, mode)
        except Exception:
            pass
        act = (getattr(self, "preview_actions", None) or {}).get(mode)
        if _alive(act) and not act.isChecked():
            act.setChecked(True)          # 互斥组：其余项自动取消勾选
        if mode == "off":
            self._preview_hide_now()
        elif mode == "always":
            self._preview_update(start_countdown=False)      # 立刻显示并保持
        elif getattr(self, "_overlay", None) is not None and                 _alive(self._overlay) and self._overlay.isVisible():
            self._preview_start_countdown()                  # 显示中切 1s/2s：按新时长立即计时
        if _broadcast:
            for cb in getattr(self, "view_listeners", []) or []:
                try:
                    cb("preview_mode", mode)
                except Exception:
                    pass

    def set_view_flag(self, which, value):
        """跨面板同步设置项（不回传，避免回环）。"""
        if which == "clusters":
            self.set_show_clusters(value, _broadcast=False)
        elif which == "lines":
            self.set_show_lines(value, _broadcast=False)
        elif which == "keymap":
            self.set_keymap(value, _broadcast=False)
        elif which == "auto_close":
            self.set_auto_close_popup(value, _broadcast=False)
        elif which == "on_top":
            self.set_always_on_top(value, _broadcast=False)
        elif which == "popup_at_mouse":
            self.set_popup_at_mouse(value, _broadcast=False)
        elif which == "show_ab":
            self.set_show_ab(value, _broadcast=False)
        elif which == "ab_mode":
            self.set_ab_mode(value, _broadcast=False)
        elif which == "preview_mode":
            self.set_preview_mode(value, _broadcast=False)
        elif which == "unreachable":
            self.set_show_unreachable(value, _broadcast=False)
        elif which == "chroma_mode":
            self.set_chroma_mode(value, _broadcast=False)
        elif which == "chroma_full":
            self.set_chroma_full(value, _broadcast=False)
        elif which == "chroma_abs_cluster":
            self.set_abs_cluster_mode(value, _broadcast=False)
        elif which == "temp_chroma_key":
            self.set_temp_chroma_key(value, _broadcast=False)
        elif which == "lightness_metric":
            self.set_lightness_metric(value, _broadcast=False)
        elif which == "debug_log":
            self.set_debug_log(value, _broadcast=False)

    # ------------------------------------------------- 诊断日志（T-16）
    def set_debug_log(self, checked, _broadcast=True):
        """诊断日志模式：记录交互与内部状态（每次启动 Krita 自动关闭，不跨会话持久化）。"""
        self.debug_log = bool(checked)
        if _alive(getattr(self, "act_debug", None)):
            if self.act_debug.isChecked() != self.debug_log:
                self.act_debug.blockSignals(True)
                self.act_debug.setChecked(self.debug_log)
                self.act_debug.blockSignals(False)
            self.act_debug.setText(i18n.t("诊断日志（开启中）", "Diagnostic log (on)")
                                   if self.debug_log else i18n.t("诊断日志", "Diagnostic log"))
        if self.debug_log:
            dlog.enable(True)
            self._dbg_session()
        else:
            dlog.log("OFF", panel=self._dbg_name)
            dlog.enable(False)
        if _broadcast:
            for cb in getattr(self, "view_listeners", []) or []:
                try:
                    cb("debug_log", self.debug_log)
                except Exception:
                    pass

    def show_about_dialog(self):
        """设置菜单「关于馍馍拾色器」：slogan / 版本 / 许可 / 第三方依赖。"""
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle(i18n.t("关于馍馍拾色器", "About Momo Color Picker"))
        box.setText(i18n.t(
            "馍馍拾色器：更适合HSV宝宝的OKLAB/OKLCH拾色器",
            "Momo Color Picker: a more HSV-friendly OKLAB/OKLCH picker"))
        box.setInformativeText(i18n.t(
            "版本：%s\n许可：GPL-3.0-or-later\n第三方：numpy（BSD-3-Clause）",
            "Version: %s\nLicense: GPL-3.0-or-later\nThird-party: numpy (BSD-3-Clause)")
            % __version__)
        box.setStandardButtons(QMessageBox.Ok)
        box.exec_()

    def _dbg_session(self):
        """写一条诊断日志会话头（版本 / 面板 / 当前颜色）。"""
        if not dlog.is_enabled():
            return
        try:
            ver = str(Krita.instance().version())
        except Exception:
            ver = "-"
        dlog.log("SES", panel=self._dbg_name, krita=ver, w=self.width(), h=self.height(),
                 hue=round(self.h, 3), sat=round(self.s, 5), val=round(self.v, 6))

    def _dbg_color(self, write_fg, ctx=None):
        """set_color 末尾采样：记录状态并标出 >0.02 的明度跳变（仅日志开启时有开销）。

        明度口径跟随「明度标准」（R27）：诊断日志里的 L / dL / JUMP 与当前口径同量。
        """
        if not dlog.is_enabled():
            return
        ctx = ctx or self._dbg_ctx
        try:
            L = float(math_core.lightness(self.h, self.s, self.v, self.lightness_metric))
        except Exception:
            return
        prev = self._dbg_last_l
        delta = None if prev is None else (L - prev)
        hex_text = "#%02X%02X%02X" % self.picker_rgb()
        dlog.log_throttled("SET", 8, ctx=ctx, h=round(self.h, 3), s=round(self.s, 5),
                           v=round(self.v, 6), L=round(L, 5),
                           dL=(None if delta is None else round(delta, 5)),
                           hex=hex_text, wfg=int(bool(write_fg)))
        if delta is not None and abs(delta) > 0.02:
            dlog.log("JUMP", ctx=ctx, L=round(L, 5), L_prev=round(prev, 5),
                     dL=round(delta, 5), h=round(self.h, 3), s=round(self.s, 5),
                     v=round(self.v, 6), hex=hex_text)
        self._dbg_last_l = L

    def set_auto_close_popup(self, checked, _broadcast=True):
        """点击弹出面板外时是否自动关闭（默认开；持久化 + 广播）。

        R17：与「弹出面板置顶」**不再联动**。置顶自己记忆自己的值；
        本项开着时置顶项只是**置灰**（此状态下无意义），但记忆值保留。
        """
        self.auto_close_popup = bool(checked)
        try:
            Krita.instance().writeSetting("", AUTO_CLOSE_KEY, "1" if self.auto_close_popup else "0")
        except Exception:
            pass
        if _alive(getattr(self, "act_auto_close", None)):
            if self.act_auto_close.isChecked() != self.auto_close_popup:
                self.act_auto_close.blockSignals(True)
                self.act_auto_close.setChecked(self.auto_close_popup)
                self.act_auto_close.blockSignals(False)
        if _alive(getattr(self, "act_on_top", None)):
            self.act_on_top.setEnabled(not self.auto_close_popup)
        hook = getattr(self, "on_top_hook", None)
        if hook is not None:
            try:
                hook()          # 实际窗口标志 = 记忆值 AND not 自动关闭
            except Exception:
                pass
        self._refresh_keymap_dialog_top()          # R18：已打开的「按键功能」同步置顶
        if _broadcast:
            for cb in getattr(self, "view_listeners", []) or []:
                try:
                    cb("auto_close", self.auto_close_popup)
                except Exception:
                    pass

    def set_always_on_top(self, checked, _broadcast=True):
        """弹出面板是否置顶（弹窗会立即应用窗口标志）。

        R17：独立记忆自己的值，不因「自动关闭」而被改写；
        自动关闭开着时只是菜单项置灰，真实值仍保留。
        """
        self.always_on_top = bool(checked)
        try:
            Krita.instance().writeSetting("", ON_TOP_KEY, "1" if self.always_on_top else "0")
        except Exception:
            pass
        if _alive(getattr(self, "act_on_top", None)):
            if self.act_on_top.isChecked() != self.always_on_top:
                self.act_on_top.blockSignals(True)
                self.act_on_top.setChecked(self.always_on_top)
                self.act_on_top.blockSignals(False)
            self.act_on_top.setEnabled(not self.auto_close_popup)
        hook = getattr(self, "on_top_hook", None)
        if hook is not None:
            try:
                hook()
            except Exception:
                pass
        self._refresh_keymap_dialog_top()          # R18：已打开的「按键功能」同步置顶
        if _broadcast:
            for cb in getattr(self, "view_listeners", []) or []:
                try:
                    cb("on_top", self.always_on_top)
                except Exception:
                    pass

    def set_popup_at_mouse(self, checked, _broadcast=True):
        """弹出位置是否跟随鼠标（默认开；放不下时回退 Krita 窗口中心）。"""
        self.popup_at_mouse = bool(checked)
        try:
            Krita.instance().writeSetting("", POPUP_AT_MOUSE_KEY,
                                          "1" if self.popup_at_mouse else "0")
        except Exception:
            pass
        if _alive(getattr(self, "act_mouse_pos", None)):
            if self.act_mouse_pos.isChecked() != self.popup_at_mouse:
                self.act_mouse_pos.blockSignals(True)
                self.act_mouse_pos.setChecked(self.popup_at_mouse)
                self.act_mouse_pos.blockSignals(False)
        if _broadcast:
            for cb in getattr(self, "view_listeners", []) or []:
                try:
                    cb("popup_at_mouse", self.popup_at_mouse)
                except Exception:
                    pass

    def _interacting(self):
        """本面板是否正在拖动（用于隔离对端同步与回读，避免拖动中被覆盖）。"""
        return bool(self._picking or getattr(self, "_strip_active", False)
                    or getattr(self, "_entry_dragging", False))

    def set_show_clusters(self, checked, _broadcast=True):
        self.show_clusters = bool(checked)
        if self.act_clusters.isChecked() != self.show_clusters:
            self.act_clusters.setChecked(self.show_clusters)
        self.picker.set_show_clusters(self.show_clusters)
        if _broadcast:
            for cb in getattr(self, "view_listeners", []) or []:
                try:
                    cb("clusters", self.show_clusters)
                except Exception:
                    pass

    def set_show_lines(self, checked, _broadcast=True):
        self.show_lines = bool(checked)
        if self.act_lines.isChecked() != self.show_lines:
            self.act_lines.setChecked(self.show_lines)
        self.picker.set_show_lines(self.show_lines)
        if _broadcast:
            for cb in getattr(self, "view_listeners", []) or []:
                try:
                    cb("lines", self.show_lines)
                except Exception:
                    pass
class HsvPickerDocker(DockWidget):
    """Krita 面板形态的拾色器。"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle(i18n.t("馍馍拾色器", "Momo Color Picker"))
        self.panel = HsvPickerPanel(self, dbg_name="docker")
        self.panel.dialog_host = self        # R18：从 Docker 打开「按键功能」时以 Docker 为 parent
        self.setWidget(self.panel)
        global _EXTENSION
        if _EXTENSION is not None:
            _EXTENSION.attach_docker(self)
        _log("HsvPickerDocker.__init__")

    # Krita 每次切换画布/视图都会回调；签名必须带 canvas
    def canvasChanged(self, canvas):
        view = canvas.view() if canvas is not None else None
        _log("canvasChanged view=%r" % (view,))
        self.panel.set_view(view)
        for sink in list(getattr(self.panel, "view_sinks", []) or []):
            try:
                sink.set_view(view)
            except Exception:
                pass

    # R24：Docker 隐藏/关闭 -> 「按键功能」对话框一并关闭；最小化 -> 隐藏、恢复 -> 显示
    def hideEvent(self, event):
        super().hideEvent(event)
        try:
            self.panel._sync_keymap_dialog_visibility()
        except Exception:
            pass

    def changeEvent(self, event):
        super().changeEvent(event)
        try:
            if event.type() == QEvent.WindowStateChange:
                self.panel._sync_keymap_dialog_visibility()
        except Exception:
            pass


class _QuitCloseFilter(QObject):
    """T-54：应用级事件过滤器，最后一个可见主窗口收到 Close 时立即收掉弹窗。

    只观察、不消费：主窗口该关还关，弹窗由 extension 收掉。
    不复用 Extension.eventFilter，独立对象便于测试与销毁时整体移除。
    """

    def __init__(self, extension):
        super().__init__()
        self._ext = extension

    def eventFilter(self, obj, event):
        try:
            if event.type() != QEvent.Close:
                return False
            from PyQt5.QtWidgets import QMainWindow
            if not isinstance(obj, QMainWindow):
                return False
            if not obj.isVisible():
                return False                     # 隐藏窗口被关掉不算「最后一个窗口」
            if self._ext._is_last_visible_main_window(obj):
                self._ext._close_popup_for_quit()
        except Exception:
            pass
        return False                             # 不消费，主窗口照常关闭


class HsvPickerExtension(Extension):
    """注册 Krita 动作：临时弹出拾色器 + 两个显示开关。"""

    def __init__(self, parent):
        super().__init__(parent)
        self._popup = None
        self._docker = None

    def setup(self):
        pass

    def createActions(self, window):
        action = window.createAction(ACTION_POPUP_ID,
                                     i18n.t("弹出馍馍拾色器", "Show Momo Color Picker"))
        action.setToolTip(i18n.t("临时弹出拾色器；再次按下快捷键或点击面板外隐藏",
                                 "Temporarily show the picker; press the shortcut again or click outside to hide"))
        if not action.shortcut():
            action.setShortcut(DEFAULT_POPUP_SHORTCUT)
        action.triggered.connect(self.toggle_popup)
        self._toggle_sequence = action.shortcut().toString() or DEFAULT_POPUP_SHORTCUT
        self._install_app_shortcut_filter()
        self._install_quit_hooks()          # T-54：每个主窗口都会调一次，内部只挂一次
        _log("createActions 完成 shortcut=%r" % (action.shortcut(),))

    # ---- 应用级快捷键：无论焦点在主窗口、画布还是弹窗，Shift+B 都切换弹窗 ----
    def _install_app_shortcut_filter(self):
        if getattr(self, "_app_filter_installed", False):
            return
        try:
            from PyQt5.QtWidgets import QApplication
            app = QApplication.instance()
            if app is None:
                return
            app.installEventFilter(self)
            self._app_filter_installed = True
        except Exception:
            pass

    def _shortcut_sequence(self):
        from PyQt5.QtGui import QKeySequence
        return QKeySequence(getattr(self, "_toggle_sequence", None) or DEFAULT_POPUP_SHORTCUT)

    def eventFilter(self, obj, event):
        """接管 Shift+B：弹窗可见→关闭，不可见→弹出。

        任何文本输入框（QLineEdit / QAbstractSpinBox）获得焦点时，快捷键一律不抢：
        弹窗自身的 HEX / 数值框内输入大写 B（Shift+B）不会被误当成弹窗开关。
        """
        try:
            from PyQt5.QtCore import QEvent
            from PyQt5.QtGui import QKeySequence
            from PyQt5.QtWidgets import QAbstractSpinBox, QApplication, QLineEdit
            et = event.type()
            if et == QEvent.KeyPress:
                if event.isAutoRepeat():
                    return False
                combo = QKeySequence(event.key() | int(event.modifiers()))
                if not self._shortcut_sequence().matches(combo):
                    return False
            elif et == QEvent.Shortcut:
                if event.key() != self._shortcut_sequence()[0]:
                    return False
            else:
                return False
            focused = QApplication.focusWidget()
            text_input = focused if isinstance(focused, (QLineEdit, QAbstractSpinBox)) else None
            if text_input is None and isinstance(obj, (QLineEdit, QAbstractSpinBox)):
                text_input = obj      # 焦点信息缺失时以事件目标兜底（直接派发也按文本输入处理）
            if text_input is not None:
                if dlog.is_enabled():
                    dlog.log_throttled("HOTKEY_SKIP", 200, reason="text",
                                       cls=type(text_input).__name__)
                return False
            if dlog.is_enabled():
                dlog.log("HOTKEY", visible=int(bool(self._popup and self._popup.isVisible())))
            self.toggle_popup()
            return True
        except Exception:
            return False


    # ---- T-54：应用退出 / 最后一个主窗口关闭 => 收掉弹窗 ----
    def _install_quit_hooks(self):
        """只挂一次：Krita applicationClosing + Qt aboutToQuit + 应用级 Close 过滤器。"""
        if getattr(self, "_quit_hook_installed", False):
            return
        self._quit_hook_installed = True      # 先置标志：createActions 每个主窗口都会调用
        self._quit_notifier = None
        self._quit_app = None
        self._quit_filter = None
        try:
            notifier = Krita.instance().notifier()
            notifier.applicationClosing.connect(self._close_popup_for_quit)
            self._quit_notifier = notifier     # 持引用，防止被 GC 后信号失联
        except Exception:
            pass
        try:
            from PyQt5.QtWidgets import QApplication
            app = QApplication.instance()
            if app is not None:
                app.aboutToQuit.connect(self._close_popup_for_quit)
                self._quit_app = app
        except Exception:
            pass
        try:
            from PyQt5.QtWidgets import QApplication
            app = QApplication.instance()
            if app is not None:
                self._quit_filter = _QuitCloseFilter(self)
                app.installEventFilter(self._quit_filter)
        except Exception:
            self._quit_filter = None

    def _remove_quit_hooks(self):
        """移除三条退出收尾（幂等；测试与销毁用）。"""
        self._quit_hook_installed = False
        notifier = getattr(self, "_quit_notifier", None)
        if notifier is not None:
            try:
                notifier.applicationClosing.disconnect(self._close_popup_for_quit)
            except Exception:
                pass
        self._quit_notifier = None
        app = getattr(self, "_quit_app", None)
        if app is not None:
            try:
                app.aboutToQuit.disconnect(self._close_popup_for_quit)
            except Exception:
                pass
        self._quit_app = None
        flt = getattr(self, "_quit_filter", None)
        if flt is not None:
            try:
                from PyQt5.QtWidgets import QApplication
                app = QApplication.instance()
                if app is not None:
                    app.removeEventFilter(flt)
            except Exception:
                pass
        self._quit_filter = None

    def _is_last_visible_main_window(self, window):
        """除 window 外没有其它可见 QMainWindow => 它是最后一个主窗口。"""
        try:
            from PyQt5.QtWidgets import QApplication, QMainWindow
            for w in QApplication.topLevelWidgets():
                if w is window:
                    continue
                if isinstance(w, QMainWindow) and w.isVisible():
                    return False
            return True
        except Exception:
            return False        # 判定失败时保守：不误收弹窗

    def _close_popup_for_quit(self, *args):
        """幂等收掉弹窗：hide + deleteLater + 清引用；退出路径上异常一律吞掉。"""
        try:
            popup = getattr(self, "_popup", None)
            self._popup = None
        except Exception:
            return
        if popup is None:
            return
        try:
            popup.hide()
        except Exception:
            pass
        try:
            popup.deleteLater()
        except Exception:
            pass


    def attach_docker(self, docker):
        """Docker 创建后登记，供弹出窗口共享颜色/历史状态。"""
        self._docker = docker

    def toggle_popup(self, *args):
        """快捷键触发：显示/隐藏临时弹出的拾色器窗口（不消抖，每次按键都切换）。"""
        self._install_app_shortcut_filter()      # 兜底：确保应用级快捷键接管已安装
        try:
            if self._popup is None:
                partner = getattr(self, "_docker", None)
                self._popup = HsvPickerPopup(partner.panel if partner is not None else None)
            self._popup.toggle()
        except Exception:
            _log("toggle_popup 失败:\n%s" % traceback.format_exc())




class HsvPickerPopup(QWidget):
    """快捷键临时弹出的拾色器窗口（与 Docker 面板共享颜色/历史/显示开关）。"""

    def __init__(self, partner=None):
        super().__init__(None, Qt.Window)
        # T-54：独立顶层弹窗不参与 Qt「最后一个窗口关闭 => 退出」判定，
        # 否则关掉 Krita 主窗口后 krita.exe 会因弹窗仍在而残留。
        self.setAttribute(Qt.WA_QuitOnClose, False)
        self.setWindowTitle(i18n.t("馍馍拾色器", "Momo Color Picker"))
        self._partner = partner
        self._changing_flags = False
        self._programmatic_resize = False      # 程序化 resize（构造/默认应用）期间不写尺寸记忆
        self._programmatic_size = (0, 0)       # 最近一次程序化 resize 的目标尺寸
        self._size_user_resizable = False      # 首次 show 之前不接受「用户 resize」落盘
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.panel = HsvPickerPanel(self, dbg_name="popup", follow_active_view=True)
        self.panel.dialog_host = self        # R18：从弹窗打开「按键功能」时以弹窗为 parent
        layout.addWidget(self.panel)
        if partner is not None:
            # 颜色双向同步
            self.panel.color_synced.connect(partner.apply_external)
            partner.color_synced.connect(self.panel.apply_external)
            self.panel.set_color_from_partner = partner.apply_external
            # 视图同步：Docker 的 canvasChanged 会更新所有 sink（弹窗跟随活动视图，双保险）
            partner.view_sinks.append(self.panel)
            # 历史双向同步
            self.panel.history_listeners.append(partner.set_history)
            partner.history_listeners.append(self.panel.set_history)
            self.panel.set_history(partner.history.colors, save=False)
            # 显示开关双向同步（各改各的对端，避免自我回环）
            self.panel.view_listeners.append(lambda which, value: partner.set_view_flag(which, value))
            partner.view_listeners.append(lambda which, value: self.panel.set_view_flag(which, value))
            # 视图绑定也共享：两边读写同一份 Krita 前景色
            self.panel.set_view(partner._view if partner._view is not None else active_view())
            self.panel.set_show_clusters(partner.show_clusters, _broadcast=False)
            self.panel.set_show_lines(partner.show_lines, _broadcast=False)
            # 浮层选项也照抄一份（两边各自读设置，这里保证构造时一致）
            self.panel.set_preview_mode(partner.preview_mode, _broadcast=False)
            # 不可达提示 / 自定义按键表 / C 条口径与满量程：也照抄一份
            self.panel.set_show_unreachable(partner.show_unreachable, _broadcast=False)
            self.panel.set_keymap(partner.keymap, _broadcast=False)
            self.panel.set_temp_chroma_key(partner.temp_chroma_key, _broadcast=False)
            self.panel.set_chroma_mode(partner.chroma_mode, _broadcast=False)
            self.panel.set_chroma_full(partner.chroma_full, _broadcast=False)
            self.panel.set_lightness_metric(partner.lightness_metric, _broadcast=False)
        # 尺寸：用户记忆优先，否则按面板内容计算（程序化 resize 不写记忆）
        self._apply_initial_size()
        # 置顶设置变化时立即应用到窗口；默认按当前设置
        self.panel.on_top_hook = self._apply_window_flags
        self._apply_window_flags()

    def _apply_window_flags(self):
        """按「弹出面板置顶」设置应用窗口标志：独立顶层窗口（Windows 任务栏可见）+ 可选置顶。

        R17：置顶记忆自己的值；但「点击弹出面板外时自动关闭」开着时本项无意义（置灰），
        故实际标志 = 记忆值 AND not 自动关闭。
        """
        try:
            was_visible = self.isVisible()
            self._changing_flags = True
            flags = Qt.Window
            effective_top = self.panel.effective_top()
            if effective_top:
                flags |= Qt.WindowStaysOnTopHint
            self.setWindowFlags(flags)
            if was_visible:
                self.show()
                self.raise_()
        except Exception:
            pass
        finally:
            self._changing_flags = False

    def _screen_available_size(self):
        """当前屏幕可用区（光标所在屏优先，取不到用主屏）；无屏幕信息返回 None。"""
        try:
            from PyQt5.QtGui import QCursor, QGuiApplication
            from PyQt5.QtWidgets import QApplication
            screen = QGuiApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()
            if screen is None:
                return None
            geo = screen.availableGeometry()
            if geo.width() > 0 and geo.height() > 0:
                return (geo.width(), geo.height())
        except Exception:
            pass
        return None

    def _clamp_size_to_screen(self, w, h):
        """把尺寸 clamp 到当前屏幕可用区，避免弹窗超出屏幕。"""
        w, h = max(1, int(w)), max(1, int(h))
        avail = self._screen_available_size()
        if avail is None:
            return w, h
        return min(w, avail[0]), min(h, avail[1])

    def _default_size(self):
        """首次打开且无用户记忆时的尺寸 = 面板 sizeHint；不足时补到硬最小尺寸，再 clamp 到屏幕。

        高度按 POPUP_FILL_ASPECT 放大，让拾色器方块填满面板宽度：否则方块只占中间一小块，
        左右会留下大片空白。
        """
        hint = self.panel.sizeHint()
        min_hint = self.panel.minimumSizeHint()
        w = max(int(hint.width()), int(min_hint.width()), int(self.panel.minimumWidth()))
        h = max(int(hint.height()), int(min_hint.height()), int(self.panel.minimumHeight()))
        if w <= 0 or h <= 0:
            w, h = 300, 430      # 极端兜底：面板 hint 完全无效时给一个可用尺寸
        h = max(h, int(round(w * POPUP_FILL_ASPECT)))
        return self._clamp_size_to_screen(w, h)

    def _read_user_size(self):
        """读用户手动 resize 的记忆（只认新键；旧键 HsvPickerPopupSize 不再生效）。"""
        try:
            raw = Krita.instance().readSetting("", POPUP_SIZE_USER_KEY, "") or ""
            if "x" in raw:
                w, h = (int(x) for x in raw.split("x", 1))
                if 280 <= w <= 4000 and 280 <= h <= 4000:
                    return w, h
        except Exception:
            pass
        return None

    def _apply_initial_size(self):
        """构造时应用尺寸：用户记忆优先，否则按内容计算；全程标记为程序化 resize。"""
        try:
            size = self._read_user_size()
            size = self._clamp_size_to_screen(*size) if size is not None else self._default_size()
        except Exception:
            size = (300, 430)      # 兜底：面板 hint 计算异常时也不让构造失败
        self._programmatic_resize = True
        try:
            self.resize(size[0], size[1])
            # 以实际生效尺寸为准：首次 show 触发的 resize 事件不再被误认为用户改动
            self._programmatic_size = (self.width(), self.height())
        finally:
            self._programmatic_resize = False

    def _save_size(self, size=None):
        """把用户手动调整后的尺寸写入新键（旧键不再写）。"""
        try:
            w, h = size if size is not None else (self.width(), self.height())
            Krita.instance().writeSetting("", POPUP_SIZE_USER_KEY, "%dx%d" % (int(w), int(h)))
        except Exception:
            pass

    def resizeEvent(self, event):
        # 程序化 resize / 首次显示前不写记忆；只有用户手动改变尺寸才落盘。
        if (not getattr(self, "_programmatic_resize", False)
                and getattr(self, "_size_user_resizable", False)):
            size = (event.size().width(), event.size().height())
            if size != getattr(self, "_programmatic_size", None):
                self._programmatic_size = size      # 之后同尺寸事件（换窗口标志等）不重复写
                self._save_size(size)
        super().resizeEvent(event)

    def toggle(self):
        """显示 <-> 隐藏。"""
        if self.isVisible():
            self._hide_reason = "toggle"
            self.hide()
        else:
            self._apply_window_flags()
            if getattr(self.panel, "popup_at_mouse", True):
                self._place_popup()
            self._install_outside_filter()
            self.show()
            self.raise_()
            self.activateWindow()      # 聚焦到弹窗：再次按快捷键时由弹窗侧快捷键隐藏
            self.setFocus(Qt.OtherFocusReason)

    def _place_popup(self):
        """按「弹出位置跟随鼠标」放置：以鼠标为中心；超出 Krita 主窗口时贴边夹回窗口内。"""
        try:
            from PyQt5.QtGui import QCursor, QGuiApplication
            from PyQt5.QtWidgets import QApplication
            cursor = QCursor.pos()
            screen = QGuiApplication.screenAt(cursor) or QApplication.primaryScreen()
            if screen is None:
                return
            sg = screen.availableGeometry()
            screen_rect = (sg.left(), sg.top(), sg.right(), sg.bottom())
            window_rect = None
            try:
                win = Krita.instance().activeWindow()
                qw = win.qwindow() if win is not None else None
                if qw is not None and not qw.isMinimized():
                    fg = qw.frameGeometry()
                    if fg.width() > 0 and fg.height() > 0:
                        window_rect = (fg.left(), fg.top(), fg.right(), fg.bottom())
            except Exception:
                window_rect = None
            x, y = popup_position((cursor.x(), cursor.y()), (self.width(), self.height()),
                                  screen_rect, window_rect)
            self.move(x, y)
        except Exception:
            pass

    def _auto_close_enabled(self):
        """主面板与弹窗任一取消勾选，都视为关闭「外点自动关闭」。"""
        vals = [getattr(self.panel, "auto_close_popup", True)]
        if _alive(self._partner):
            vals.append(getattr(self._partner, "auto_close_popup", True))
        return all(vals)

    # ---- 点窗口外隐藏（可缩放的 Tool 窗口不能靠 Qt.Popup 语义）----
    def _install_outside_filter(self):
        if getattr(self, "_outside_filter", False):
            return
        try:
            from PyQt5.QtWidgets import QApplication
            QApplication.instance().installEventFilter(self)
            self._outside_filter = True
        except Exception:
            pass

    def _remove_outside_filter(self):
        if not getattr(self, "_outside_filter", False):
            return
        try:
            from PyQt5.QtWidgets import QApplication
            QApplication.instance().removeEventFilter(self)
        except Exception:
            pass
        self._outside_filter = False

    def _obj_is_ours(self, obj):
        """obj 是否为本弹窗或其子控件（QMenu 等顶层子窗口按 parentWidget 链判断）。"""
        try:
            w = obj
            while w is not None:
                if w is self:
                    return True
                w = w.parentWidget()
        except Exception:
            pass
        return False

    def _is_inside_popup(self, gpos):
        """gpos 命中的控件是否属于本弹窗（含「设置」菜单等子窗口）。"""
        try:
            from PyQt5.QtWidgets import QApplication
            return self._obj_is_ours(QApplication.widgetAt(gpos))
        except Exception:
            pass
        return False

    def eventFilter(self, obj, event):
        """点窗口外：按设置决定是否隐藏；隐藏时**吃掉这次点击**（画布不受影响）。"""
        try:
            from PyQt5.QtCore import QEvent
            if event.type() == QEvent.MouseButtonPress and self.isVisible():
                # 事件目标是本弹窗或其后代（含设置菜单）：算作内部点击
                if obj is self or self._obj_is_ours(obj):
                    return super().eventFilter(obj, event)
                gpos = event.globalPos() if hasattr(event, "globalPos") else None
                if gpos is not None and not self.frameGeometry().contains(gpos) \
                        and not self._is_inside_popup(gpos):
                    if not self._auto_close_enabled():
                        return super().eventFilter(obj, event)    # 设置项关闭：不隐藏、不消费
                    self._hide_reason = "auto_close"
                    self.hide()
                    return True          # 消费掉，避免画布同时收到这一下
        except Exception:
            pass
        return super().eventFilter(obj, event)

    def showEvent(self, event):
        if not getattr(self, "_changing_flags", False) and dlog.is_enabled():
            dlog.log("POPUP_SHOW", auto_close=int(self._auto_close_enabled()),
                     on_top=int(bool(getattr(self.panel, "always_on_top", True))))
        super().showEvent(event)
        self._size_user_resizable = True      # 首次显示完成，之后才接受「用户 resize」落盘
        try:
            self.panel._sync_keymap_dialog_visibility()      # 最小化恢复后重新显示对话框
        except Exception:
            pass

    # R24：弹出面板最小化/恢复 -> 「按键功能」对话框隐藏/重新显示
    def changeEvent(self, event):
        super().changeEvent(event)
        if getattr(self, "_changing_flags", False):
            return
        try:
            if event.type() == QEvent.WindowStateChange:
                self.panel._sync_keymap_dialog_visibility()
        except Exception:
            pass

    def hideEvent(self, event):
        if getattr(self, "_changing_flags", False):
            super().hideEvent(event)
            return
        try:
            self._remove_outside_filter()
            if dlog.is_enabled():
                dlog.log("POPUP_HIDE", reason=getattr(self, "_hide_reason", "-"),
                         auto_close=int(self._auto_close_enabled()))
            self._hide_reason = "-"
            if _alive(self._partner) and _alive(self.panel) and _alive(self.panel.picker):
                self._partner.apply_external(
                    self.panel.h, self.panel.s, self.panel.v,
                    "#%02X%02X%02X" % self.panel.picker_rgb())
        except (RuntimeError, AttributeError):
            pass
        super().hideEvent(event)
        try:
            self.panel._sync_keymap_dialog_visibility()      # R24：宿主隐藏 -> 关闭对话框
        except Exception:
            pass


# ---- 注册（必须在模块 import 时执行，__init__.py 会 import 本模块）----
_EXTENSION = HsvPickerExtension(Krita.instance())
Krita.instance().addDockWidgetFactory(
    DockWidgetFactory(PLUGIN_ID,
                      DockWidgetFactoryBase.DockPosition.DockRight,
                      HsvPickerDocker))
Krita.instance().addExtension(_EXTENSION)
try:
    _EXTENSION._install_app_shortcut_filter()
except Exception:
    pass
_log("模块注册完成")
