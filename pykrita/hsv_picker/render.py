# -*- coding: utf-8 -*-
"""拾色器的位图渲染（numpy -> QImage）与几何换算。

与 math_core 的分工：math_core 只算颜色数学，本模块把颜色数学的结果变成位图。
三个 render_*_array 是纯 numpy、可在系统 Python 下单测；只有 qimage_from_* 需要 PyQt5，
所以 Qt 是延迟 import 的（便于数学/渲染逻辑离线回归）。
Krita 5.3.3 = Qt5：QImage 用 Format_RGB888，取鼠标坐标用 event.localPos()。
"""

import numpy as np

try:                        # 插件内：包内相对导入
    from . import math_core as mc
except ImportError:         # 离线单测：直接把本目录加进 sys.path
    import math_core as mc


def render_square_array(h, size):
    """固定色相的 HSV 方块 -> uint8 RGB (size, size, 3)。

    s 向右 0->1，v 向下 1->0（与 Tkinter 版同口径）。
    """
    size = int(size)
    if size < 2:
        size = 2
    ss = np.linspace(0.0, 1.0, size)
    vv = np.linspace(1.0, 0.0, size)
    s_grid, v_grid = np.meshgrid(ss, vv)
    hs = np.full_like(s_grid, float(h))
    rgb = mc.hsv_to_srgb(hs, s_grid, v_grid)
    return (np.clip(rgb, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)


def render_ring_array(size, r_in_ratio, r_out_ratio, ss=2):
    """色相环 -> RGBA uint8 (size*ss, size*ss, 4)。

    方位：0° 在 9 点钟，色相顺时针递增（与 Tkinter 版一致）。
    环内/外半径按控件尺寸等比给出（r_in_ratio / r_out_ratio 相对画布边长）。
    返回图里环外区域 alpha=0，画的时候直接叠在背景上。
    """
    size = int(size)
    px = max(4, size * int(ss))
    c = (px - 1) / 2.0
    yy, xx = np.mgrid[0:px, 0:px]
    dx = xx - c
    dy = yy - c
    rad = np.hypot(dx, dy)
    r_out = r_out_ratio * (px - 1) / 2.0
    r_in = r_in_ratio * (px - 1) / 2.0
    alpha = np.clip((r_out - rad) * 255.0 / max(1.0, r_out * 0.004), 0.0, 255.0)
    alpha *= np.clip((rad - r_in) * 255.0 / max(1.0, r_in * 0.004), 0.0, 1.0)
    ang = np.degrees(np.arctan2(dy, dx))              # 屏幕角度：0°=3 点，顺时针为正
    hue = (ang + 180.0) % 360.0                       # 0° 红在 9 点钟，色相顺时针递增
    rgb = mc.hsv_to_srgb(hue, np.ones_like(hue), np.ones_like(hue))
    out = np.zeros((px, px, 4), dtype=np.uint8)
    out[..., :3] = (np.clip(rgb, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    out[..., 3] = alpha.astype(np.uint8)
    return out


def qimage_from_rgb(arr):
    """uint8 RGB (h,w,3) -> QImage（复制数据，避免 numpy 缓冲被回收）。"""
    from PyQt5.QtGui import QImage
    arr = np.ascontiguousarray(arr, dtype=np.uint8)
    h, w, _ = arr.shape
    return QImage(arr.data, w, h, w * 3, QImage.Format_RGB888).copy()


def qimage_from_rgba(arr):
    """uint8 RGBA (h,w,4) -> QImage（复制数据）。"""
    from PyQt5.QtGui import QImage
    arr = np.ascontiguousarray(arr, dtype=np.uint8)
    h, w, _ = arr.shape
    return QImage(arr.data, w, h, w * 4, QImage.Format_RGBA8888).copy()


# ------------------------------------------------------------------ 纯几何（无 Qt，可离线单测）
SQ_HALF_RATIO = 0.286     # 方块半边长占「控件短边」的比例（留 0.4% 安全边）
RING_RATIO = 0.09          # 色相环厚度占「控件短边」的比例


def picker_geometry(width, height):
    """控件像素尺寸 -> 拾色器几何字典。

    约束：环外圈必须落在控件内 -> half_sq*√2 + side*RING_RATIO <= side/2
    -> half_sq <= side*(0.5-0.09)/√2 ≈ side*0.2899，故取 SQ_HALF_RATIO = 0.286。
    该比例与 Tkinter 版一致（方块边长 350 / 画布 600 = 58.3%，环厚 44 / 600 = 7.3%）。
    """
    side = float(min(max(1.0, width), max(1.0, height)))
    half_sq = side * SQ_HALF_RATIO
    r_in = half_sq * 1.4142135623730951
    r_out = r_in + side * RING_RATIO
    cx, cy = float(width) / 2.0, float(height) / 2.0
    return {"cx": cx, "cy": cy, "half_sq": half_sq, "r_in": r_in, "r_out": r_out,
            "sq": (cx - half_sq, cy - half_sq, cx + half_sq, cy + half_sq)}


def hit_area(geom, x, y):
    """鼠标 (x, y) 落在方块 / 色相环 / 空白：返回 "square"/"ring"/None。

    R12：方块四角恰好顶到环内圈，四角与内圈之间的 4 块角落透镜区曾返回 None
    （按下完全无反应）；现兜底按「环」处理，让那里也能起拖转色相。
    方块的外接矩形判定优先级更高（在方块内仍返回 "square"），控件边缘仍返回 None。
    """
    d = ((x - geom["cx"]) ** 2 + (y - geom["cy"]) ** 2) ** 0.5
    if d >= geom["r_in"]:
        return "ring" if d <= geom["r_out"] else None
    sq = geom["sq"]
    if sq[0] <= x <= sq[2] and sq[1] <= y <= sq[3]:
        return "square"
    return "ring"


def sv_from_pos(geom, x, y):
    """控件像素 -> 归一化 (s, v)，超出方块范围时钳到 0~1。"""
    s = (x - geom["cx"]) / (2.0 * geom["half_sq"]) + 0.5
    v = 0.5 - (y - geom["cy"]) / (2.0 * geom["half_sq"])
    return (0.0 if s < 0.0 else (1.0 if s > 1.0 else s),
            0.0 if v < 0.0 else (1.0 if v > 1.0 else v))


def hue_from_pos(geom, x, y):
    """控件像素 -> 色相角（0° 在 9 点钟，顺时针递增），与 render_ring_array 同口径。"""
    import math
    ang = math.degrees(math.atan2(y - geom["cy"], x - geom["cx"]))
    return (ang + 180.0) % 360.0


def pos_from_hue(geom, hue, radius):
    """色相角 -> 环上某半径处的画布坐标（画游标用）。"""
    import math
    rad = math.radians(hue - 180.0)
    return geom["cx"] + radius * math.cos(rad), geom["cy"] + radius * math.sin(rad)
