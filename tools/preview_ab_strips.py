# -*- coding: utf-8 -*-
"""Oklab a/b 分量色条 —— 效果预览（离线渲染 PNG，不进插件）。

目的：真正改插件之前，先出一张「看起来就是面板本身」的位图，用来判断
「在明度条 / 彩度条下面再加 a 条 + b 条」的观感与量程口径。

渲染口径尽量照抄插件现有实现（都是纯 numpy 函数，可离线复用）：
  · 色相环 / 方块 = render.render_ring_array / render.render_square_array
  · 明度条 = 左黑右白灰阶（strip_widget.LightnessStrip 同口径）
  · 彩度条 = 线性 Oklab C_rel（strip_widget.ChromaStrip 同口径：t = C / C_max）
  · a / b 条 = 本脚本新增，三种量程口径见 AB_VARIANTS

用法：
    python tools/preview_ab_strips.py            # 渲染预览图
    python tools/preview_ab_strips.py --check    # 只跑数学自检（不画图）
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_ROOT / "pykrita" / "hsv_picker"))

import math_core as mc          # noqa: E402
import render as rd             # noqa: E402  （Qt 是延迟 import，可离线用）

# ================================================================ 颜色数学（Oklab）

def srgb_to_oklab(rgb):
    """gamma sRGB (…,3) ∈0~1 -> (L, a, b)。"""
    rgb = np.asarray(rgb, dtype=np.float64)
    r, g, b = (mc.srgb_to_linear(rgb[..., i]) for i in range(3))
    l_ = 0.4122214708 * r + 0.5363325363 * g + 0.0514459929 * b
    m_ = 0.2119034982 * r + 0.6806995451 * g + 0.1073969566 * b
    s_ = 0.0883024619 * r + 0.2817188376 * g + 0.6299787005 * b
    l_, m_, s_ = np.cbrt(l_), np.cbrt(m_), np.cbrt(s_)
    return (0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
            1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
            0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_)


def _srgb_encode(y):
    y = np.clip(np.asarray(y, dtype=np.float64), 0.0, 1.0)
    return np.where(y <= 0.0031308, 12.92 * y, 1.055 * np.power(y, 1.0 / 2.4) - 0.055)


def oklab_to_srgb(L, a, b, clip=True):
    """Oklab -> gamma sRGB (…,3)；clip=False 时返回未截断的线性值（判色域用）。"""
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    lin = np.stack([
        4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
        -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
        -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s], axis=-1)
    if not clip:
        return np.asarray(lin, dtype=np.float64)
    return np.clip(_srgb_encode(lin), 0.0, 1.0)


def in_gamut(L, a, b, tol=3e-5):
    """(L,a,b) 是否落在 sRGB 色域内（线性空间容差 tol）。支持标量/数组。"""
    lin = oklab_to_srgb(L, a, b, clip=False)
    return np.all(lin >= -tol, axis=-1) & np.all(lin <= 1.0 + tol, axis=-1)


def _inside(L, other, axis, x):
    """固定另一分量时，x 是否在色域内（标量）。"""
    if axis == "a":
        return bool(in_gamut(L, x, other))
    return bool(in_gamut(L, other, x))


def _bisect_edge(x_in, x_out, L, other, axis, iters=40):
    """x_in 在色域内、x_out 在外 -> 二分夹边界，返回色域内的那一侧。"""
    for _ in range(iters):
        mid = 0.5 * (x_in + x_out)
        if _inside(L, other, axis, mid):
            x_in = mid
        else:
            x_out = mid
    return x_in


_INTERVAL_CACHE: dict = {}


def axis_interval(L, other, axis, lim=0.45, n=241):
    """固定另一分量，求该分量在 sRGB 色域内的**可行区间** [lo, hi]。

    注意：不能假设灰轴（该分量为 0）一定可行 —— 色域边界可能整段落在同侧，
    所以先扫一遍找可行样本，再向两侧二分。区间为空时返回 (0.0, 0.0)。
    """
    key = (round(float(L), 4), round(float(other), 4), axis)
    hit = _INTERVAL_CACHE.get(key)
    if hit is not None:
        return hit
    xs = np.linspace(-lim, lim, int(n))
    if axis == "a":
        ok = in_gamut(float(L), xs, np.full_like(xs, float(other)))
    else:
        ok = in_gamut(float(L), np.full_like(xs, float(other)), xs)
    idx = np.flatnonzero(ok)
    if idx.size == 0:
        out = (0.0, 0.0)
    else:
        i0, i1 = int(idx[0]), int(idx[-1])
        lo = _bisect_edge(xs[i0], xs[i0 - 1] if i0 > 0 else xs[i0], L, other, axis)
        hi = _bisect_edge(xs[i1], xs[i1 + 1] if i1 < n - 1 else xs[i1], L, other, axis)
        out = (float(lo), float(hi))
    if len(_INTERVAL_CACHE) > 256:
        _INTERVAL_CACHE.clear()
    _INTERVAL_CACHE[key] = out
    return out


_SLICE_CACHE: dict = {}


def ab_slice_at_L(L, n=601, lim=0.36):
    """固定明度 L 时 sRGB 色域在 (a,b) 平面上的切片包围盒。

    返回 (a_lo, a_hi, b_lo, b_hi) = 切片在 a / b 轴上的**投影**（不限定 a=0 或 b=0），
    栅格扫描 + 缓存；量程只随 L 变化，拖动时不会抖。
    """
    key = round(float(L), 4)
    hit = _SLICE_CACHE.get(key)
    if hit is not None:
        return hit
    ax = np.linspace(-lim, lim, int(n))
    A, B = np.meshgrid(ax, ax, indexing="ij")
    mask = in_gamut(float(L), A, B)
    if not mask.any():
        out = (0.0, 0.0, 0.0, 0.0)
    else:
        out = (float(A[mask].min()), float(A[mask].max()),
               float(B[mask].min()), float(B[mask].max()))
    if len(_SLICE_CACHE) > 64:
        _SLICE_CACHE.clear()
    _SLICE_CACHE[key] = out
    return out


# 三种「a/b 条量程」口径
AB_VARIANTS = {
    "A": dict(name="A 固定量程 ±0.40",
              note="A 固定 ±0.40：全局统一刻度，但两端大段超出 sRGB（灰色斜纹=再拖也不变色）"),
    "B": dict(name="B 当前明度切片（包围盒）",
              note="B 当前明度切片的包围盒：量程只随 L 变；另一端越界处仍会压平"),
    "C": dict(name="C 当前 (L, 另一分量) 单线切片",
              note="C 单线切片（推荐）：满量程永远是可达色，与现有彩度条同一哲学"),
}

_A_MIN, _A_MAX = -0.2339, 0.2762      # sRGB 色域内 a 的极值（实测，见 --check）
_B_MIN, _B_MAX = -0.3115, 0.1986      # sRGB 色域内 b 的极值
_FIX_SPAN = 0.40                      # 方案 A 的固定半量程


def ab_range(kind, variant, L, a_now, b_now):
    """返回该条的 (值下限, 值上限)。kind ∈ {"a","b"}。"""
    if variant == "A":
        return (-_FIX_SPAN, _FIX_SPAN)
    if variant == "B":
        a_lo, a_hi, b_lo, b_hi = ab_slice_at_L(L)
        return (a_lo, a_hi) if kind == "a" else (b_lo, b_hi)
    # C：固定另一分量后的可行区间（拖 a 时 b 不动，所以拖动过程中 a 条自身量程不变）
    if kind == "a":
        return axis_interval(L, b_now, "a")
    return axis_interval(L, a_now, "b")


def strip_image_ab(width, kind, variant, L, a_now, b_now, height=22):
    """渲染 a / b 条的位图（uint8 RGB (height,width,3)）。"""
    lo, hi = ab_range(kind, variant, L, a_now, b_now)
    t = np.linspace(0.0, 1.0, int(width))
    vals = lo + t * (hi - lo)
    if kind == "a":
        a, b = vals, np.full_like(vals, b_now)
    else:
        a, b = np.full_like(vals, a_now), vals
    rgb = oklab_to_srgb(L, a, b, clip=True)
    arr = (np.clip(rgb, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    return np.repeat(arr[None, :, :], height, axis=0), (lo, hi)


def strip_out_of_gamut(width, kind, variant, L, a_now, b_now):
    """该条上每个采样点是否在 sRGB 色域内（方案 A 用来画「死区」）。"""
    lo, hi = ab_range(kind, variant, L, a_now, b_now)
    t = np.linspace(0.0, 1.0, int(width))
    vals = lo + t * (hi - lo)
    if kind == "a":
        a, b = vals, np.full_like(vals, b_now)
    else:
        a, b = np.full_like(vals, a_now), vals
    return ~in_gamut(L, a, b)


# ================================================================ 面板现有部件（同插件口径）

def strip_image_L(width, height=22):
    """明度条：左黑右白灰阶（strip_widget.LightnessStrip.strip_image）。"""
    t = np.linspace(0.0, 1.0, int(width))
    v = mc.v_from_lightness("oklab", t * 1.0)
    rgb = np.repeat(np.asarray(v)[:, None], 3, axis=1)
    arr = (np.clip(rgb, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8)
    return np.repeat(arr[None, :, :], height, axis=0)


def strip_image_C(width, hue, L, height=22):
    """彩度条：线性 Oklab C_rel（与 strip_widget.ChromaStrip 同口径）。

    位置 t 对应的绝对彩度 = t * C_max(Oklab L, h)，再沿等明度曲线取 (S,V)。
    不再使用「等明度线弧长等分」；t 即 C_rel，游标与数值框一致。
    """
    arr = np.zeros((height, int(width), 3), dtype=np.uint8)
    try:
        ss, vv = mc.iso_lightness_curve(hue, L, "oklab", n_v=129, iters=30)
        cc = np.asarray(mc.ok_L_C(hue, ss, vv)[1], dtype=np.float64)
        cc = np.maximum.accumulate(np.clip(cc, 0.0, None))
        cmax = float(np.asarray(mc.cmax_of_L(hue, "oklab",
                                             np.array([float(L)]))).reshape(-1)[0])
        t = np.linspace(0.0, 1.0, int(width))
        vals = t * cmax
        s_x = np.interp(vals, cc, ss)
        v_x = np.interp(vals, cc, vv)
        rgb = mc.hsv_to_srgb(np.full_like(t, hue), s_x, v_x)
        arr = np.repeat(((np.clip(rgb, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8))[None, :, :],
                        height, axis=0)
    except Exception:
        pass
    return arr


def crel_linear_t(hue, L, s, v):
    """当前色点在彩度条上的归一化位置：线性口径 t = C_rel = C / C_max(L,h)。"""
    try:
        return float(mc.crel_of_xyz(hue, "oklab", s, v)[0])
    except Exception:
        return 0.0


# ================================================================ 画布小工具

SC = 2                                   # 超采样：位图按 2 倍画、观看更清晰
BG = (28, 28, 30)
PANEL_BG = (58, 58, 60)
BOX_BG = (40, 40, 42)
BORDER = (105, 105, 110)
TEXT = (228, 228, 232)
TEXT_DIM = (150, 150, 156)
ACCENT = (255, 190, 80)

_FONTS: dict = {}


def font(size, bold=False):
    key = (size, bold)
    if key not in _FONTS:
        name = "msyhbd.ttc" if bold else "msyh.ttc"
        _FONTS[key] = ImageFont.truetype(str(Path("C:/Windows/Fonts") / name), int(size * SC))
    return _FONTS[key]


class Canvas:
    def __init__(self, w, h):
        self.w, self.h = int(w), int(h)
        self.img = Image.new("RGB", (self.w * SC, self.h * SC), BG)
        self.d = ImageDraw.Draw(self.img)

    def rect(self, x, y, w, h, fill=None, outline=None, lw=1):
        self.d.rectangle([x * SC, y * SC, (x + w) * SC - 1, (y + h) * SC - 1],
                         fill=fill, outline=outline, width=int(lw * SC))

    def line(self, x0, y0, x1, y1, fill, lw=1):
        self.d.line([x0 * SC, y0 * SC, x1 * SC, y1 * SC], fill=fill, width=max(1, int(lw * SC)))

    def text(self, x, y, s, fill=TEXT, size=11, bold=False, anchor="la"):
        self.d.text((x * SC, y * SC), s, font=font(size, bold), fill=fill, anchor=anchor)

    def circle(self, x, y, r, fill=None, outline=None, lw=1):
        self.d.ellipse([(x - r) * SC, (y - r) * SC, (x + r) * SC, (y + r) * SC],
                       fill=fill, outline=outline, width=max(1, int(lw * SC)))

    def paste_rgb(self, arr, x, y):
        im = Image.fromarray(np.ascontiguousarray(arr, dtype=np.uint8), "RGB")
        self.img.paste(im, (int(x * SC), int(y * SC)))

    def crop_to(self, h_px):
        """按实际内容高度裁掉多余空白（避免底部被切或留大片黑边）。"""
        self.img = self.img.crop((0, 0, self.w * SC, int(h_px * SC)))
        self.h = int(h_px)

    def save(self, path):
        self.img.save(str(path))


def rgb255(v):
    return tuple(int(round(c)) for c in v)


def hex_of(rgb01):
    return "#%02X%02X%02X" % rgb255(rgb01 * 255.0)


# ================================================================ 面板

PANEL_W = 480
M = 6
MID_H = 320
SW_TOP, SW_BOT = 24, 24
ROW_H = 26
STRIP_H = 22
GAP = 3
HIST_W = 16
LABEL_W = 46
BOX_W = 64


def panel_height(n_strip):
    return M + MID_H + GAP + (SW_TOP + SW_BOT) + GAP + ROW_H + GAP + \
        n_strip * STRIP_H + (n_strip - 1) * GAP + M


def _draw_picker(c, x, y, side, h, s, v):
    g = rd.picker_geometry(side, side)
    ring = rd.render_ring_array(side, 0.809, 0.989, ss=2)
    ring_img = Image.fromarray(ring, "RGBA")
    c.img.paste(ring_img, (int(x * SC), int(y * SC)), ring_img)
    sq = rd.render_square_array(h, int(g["sq"][2] - g["sq"][0]))
    c.paste_rgb(sq, x + g["sq"][0], y + g["sq"][1])
    c.rect(x + g["sq"][0], y + g["sq"][1], sq.shape[1], sq.shape[0], outline=(20, 20, 20, 160))
    # 环上色相游标
    import math as _m
    rad = _m.radians(h - 180.0)
    x0 = x + g["cx"] + g["r_in"] * _m.cos(rad)
    y0 = y + g["cy"] + g["r_in"] * _m.sin(rad)
    x1 = x + g["cx"] + g["r_out"] * _m.cos(rad)
    y1 = y + g["cy"] + g["r_out"] * _m.sin(rad)
    c.line(x0, y0, x1, y1, (0, 0, 0), 3)
    c.line(x0, y0, x1, y1, (255, 255, 255), 1.5)
    # 方块上色点
    px = x + g["sq"][0] + s * (g["sq"][2] - g["sq"][0])
    py = y + g["sq"][1] + (1.0 - v) * (g["sq"][3] - g["sq"][1])
    c.circle(px, py, 6 / SC, outline=(0, 0, 0), lw=2)
    c.circle(px, py, 6 / SC, outline=(255, 255, 255), lw=1.5)


def _draw_strip(c, x, y, w, arr, t, *, dead=None):
    arr = np.array(arr, dtype=np.float64)
    if dead is not None and dead.any():
        # 超色域区段：与中灰混合 + 斜纹，直观表示「这一段的颜色已经到头了」
        arr[:, dead] = arr[:, dead] * 0.45 + np.array([70.0, 70.0, 70.0]) * 0.55
        for i in np.flatnonzero(dead):
            if int(i) % 3 == 0:
                arr[:, i] = arr[:, i] * 0.6 + 40.0
    c.paste_rgb(np.clip(arr, 0, 255).astype(np.uint8), x, y)
    c.rect(x - 0.5, y - 0.5, w + 1, STRIP_H + 1, outline=(20, 20, 20))
    mx = x + t * (w - 1)
    c.line(mx, y + 1, mx, y + STRIP_H - 1, (0, 0, 0), 3)
    c.line(mx, y + 1, mx, y + STRIP_H - 1, (255, 255, 255), 1.6)


def draw_panel(c, x, y, *, h, s, v, show_ab, variant, title, subtitle=""):
    n = 4 if show_ab else 2
    H = panel_height(n)
    c.rect(x, y, PANEL_W, H, PANEL_BG, outline=BORDER)
    c.text(x, y - 30, title, size=13, bold=True)
    if subtitle:
        c.text(x, y - 15, subtitle, size=10, fill=TEXT_DIM)

    rgb01 = mc.hsv_to_srgb(h, s, v)
    L, a_now, b_now = (float(t) for t in srgb_to_oklab(rgb01))
    C_ok = float(np.hypot(a_now, b_now))

    # --- 拾色器 + 历史列
    cy = y + M
    avail_w = PANEL_W - 2 * M - HIST_W - 6
    side = min(avail_w, MID_H)
    _draw_picker(c, x + M + (avail_w - side) / 2.0, cy + (MID_H - side) / 2.0, side, h, s, v)
    hx = x + M + avail_w + 6
    hist = ["#8E7CC3", "#E06666", "#F6B26B", "#93C47D", "#6FA8DC", "#5798D9",
            "#C27BA0", "#444444", "#FFFFFF", "#000000"]
    c.rect(hx, cy, HIST_W, side, fill=BOX_BG, outline=BORDER)
    for i, hx_col in enumerate(hist):
        col = tuple(int(hx_col[1 + 2 * k:3 + 2 * k], 16) for k in range(3))
        c.rect(hx + 1, cy + i * 16 + 1, HIST_W - 2, 14, fill=col)

    # --- 三色块
    sy = cy + MID_H + GAP
    c.rect(x + M, sy, PANEL_W - 2 * M, SW_TOP, fill=rgb255(rgb01 * 255.0))
    c.rect(x + M, sy + SW_TOP, (PANEL_W - 2 * M) / 2.0, SW_BOT, fill=rgb255(rgb01 * 255.0))
    c.rect(x + M + (PANEL_W - 2 * M) / 2.0, sy + SW_TOP, (PANEL_W - 2 * M) / 2.0, SW_BOT, fill=(20, 20, 20))

    # --- 数值行（设置 + H/S/V/HEX）
    ry = sy + SW_TOP + SW_BOT + GAP
    bx = x + M
    c.rect(bx, ry, 44, ROW_H, fill=BOX_BG, outline=BORDER)
    c.text(bx + 22, ry + ROW_H / 2.0, "设置", size=10, anchor="mm")
    bx += 50
    hsv_txt = [("H", "%.2f" % h, 58), ("S", "%.2f" % (s * 100), 60),
               ("V", "%.2f" % (v * 100), 60), ("HEX", hex_of(rgb01), 88)]
    for label, txt, w in hsv_txt:
        c.text(bx + 8, ry + ROW_H / 2.0, label, size=10, anchor="lm", fill=TEXT_DIM)
        bx += 20
        c.rect(bx, ry, w, ROW_H, fill=BOX_BG, outline=BORDER)
        c.text(bx + w - 4, ry + ROW_H / 2.0, txt, size=10, anchor="rm")
        bx += w + 10

    # --- 色条
    ty = ry + ROW_H + GAP
    sx = x + M + LABEL_W
    sw = PANEL_W - 2 * M - LABEL_W - BOX_W - 4
    rows = [("L", strip_image_L(sw, STRIP_H), L, "%.4f" % L, None),
            ("C", strip_image_C(sw, h, L, STRIP_H), crel_linear_t(h, L, s, v), "%.4f" % 0.0, None)]
    if show_ab:
        arr_a, (alo, ahi) = strip_image_ab(sw, "a", variant, L, a_now, b_now)
        arr_b, (blo, bhi) = strip_image_ab(sw, "b", variant, L, a_now, b_now)
        ta = (a_now - alo) / max(1e-9, ahi - alo)
        tb = (b_now - blo) / max(1e-9, bhi - blo)
        rows.append(("a", arr_a, ta, "%+.4f" % a_now,
                     strip_out_of_gamut(sw, "a", variant, L, a_now, b_now) if variant == "A" else None))
        rows.append(("b", arr_b, tb, "%+.4f" % b_now,
                     strip_out_of_gamut(sw, "b", variant, L, a_now, b_now) if variant == "A" else None))
    for i, (label, arr, t, txt, dead) in enumerate(rows):
        yy = ty + i * (STRIP_H + GAP)
        c.text(x + M, yy + STRIP_H / 2.0, label, size=10, anchor="lm")
        _draw_strip(c, sx, yy, sw, arr, float(np.clip(t, 0.0, 1.0)), dead=dead)
        c.rect(sx + sw + 4, yy, BOX_W, STRIP_H, fill=BOX_BG, outline=BORDER)
        c.text(sx + sw + 4 + BOX_W - 4, yy + STRIP_H / 2.0, txt, size=10, anchor="rm")

    # 彩度条读数改用真实 C_rel（画完再补，避免行结构变复杂）
    if True:
        try:
            crel = float(mc.crel_of_xyz(h, "oklab", s, v)[0])
        except Exception:
            crel = 0.0
        yy = ty + (STRIP_H + GAP)
        c.rect(sx + sw + 4, yy, BOX_W, STRIP_H, fill=BOX_BG, outline=BORDER)
        c.text(sx + sw + 4 + BOX_W - 4, yy + STRIP_H / 2.0, "%.4f" % crel, size=10, anchor="rm")
    return H


# ================================================================ 量程口径对比带

def draw_variant_band(c, x, y, w, *, h, s, v):
    rgb01 = mc.hsv_to_srgb(h, s, v)
    L, a_now, b_now = (float(t) for t in srgb_to_oklab(rgb01))
    c.text(x, y, "① a 条 / b 条的三种量程口径（示意：灰色斜纹 = 超出 sRGB，再拖也不变色）",
           size=12, bold=True)
    yy = y + 22
    bw = w - 236
    for kind in ("a", "b"):
        for variant in ("A", "B", "C"):
            arr, (lo, hi) = strip_image_ab(bw, kind, variant, L, a_now, b_now)
            dead = strip_out_of_gamut(bw, kind, variant, L, a_now, b_now)
            c.text(x, yy + STRIP_H / 2.0, "%s 条 · %s" % (kind, variant), size=10, anchor="lm")
            t = (a_now - lo) / max(1e-9, hi - lo) if kind == "a" else (b_now - lo) / max(1e-9, hi - lo)
            _draw_strip(c, x + 108, yy, bw, arr, float(np.clip(t, 0, 1)), dead=dead)
            c.text(x + 108 + bw + 8, yy + STRIP_H / 2.0,
                   "[%+.3f, %+.3f]" % (lo, hi), size=9, anchor="lm", fill=TEXT_DIM)
            yy += STRIP_H + 4
        yy += 6
    for k, variant in enumerate(("A", "B", "C")):
        c.text(x + 108, yy + 12 * k, AB_VARIANTS[variant]["note"], size=9, fill=TEXT_DIM)
    return yy + 12 * 3


# ================================================================ 主流程

def check():
    ok = True

    def rep(name, cond, extra=""):
        nonlocal ok
        ok = ok and bool(cond)
        print("%s %s %s" % ("PASS" if cond else "FAIL", name, extra))

    # 1) 往返精度
    err = 0.0
    for h, s, v in [(0, 1, 1), (30, 1, 1), (120, 1, 1), (240, 1, 1),
                    (210, 0.62, 0.86), (0, 0, 0.5), (300, 0.3, 0.2)]:
        rgb = mc.hsv_to_srgb(h, s, v)
        err = max(err, float(np.max(np.abs(oklab_to_srgb(*srgb_to_oklab(rgb)) - rgb))))
    rep("sRGB->Oklab->sRGB 往返 < 1e-5", err < 1e-5, "err=%.2e" % err)

    # 2) Oklab L 与插件 math_core.lightness 一致
    e2 = 0.0
    for h, s, v in [(0, 1, 1), (210, 0.62, 0.86), (120, 0.4, 0.3)]:
        e2 = max(e2, abs(float(srgb_to_oklab(mc.hsv_to_srgb(h, s, v))[0])
                         - float(mc.lightness(h, s, v, "oklab"))))
    rep("Oklab L == math_core.lightness(oklab)", e2 < 1e-9, "err=%.2e" % e2)

    # 3) 纯红 Oklab 标准值
    L, a, b = (float(t) for t in srgb_to_oklab(mc.hsv_to_srgb(0, 1, 1)))
    rep("Oklab(纯红)=(0.62796, 0.22486, 0.12585)",
        abs(L - 0.6279554) < 1e-6 and abs(a - 0.2248631) < 1e-6 and abs(b - 0.1258463) < 1e-6,
        "(%.5f, %.5f, %.5f)" % (L, a, b))

    # 4) 灰轴 a=b=0
    e4 = max(max(abs(float(t)) for t in srgb_to_oklab(mc.hsv_to_srgb(0, 0, v))[1:])
             for v in (0.2, 0.5, 0.8))
    rep("灰轴 a=b=0", e4 < 1e-7, "max=%.2e" % e4)

    # 5) 色域切片：包围盒端点必须正好贴着色域边界（扫另一分量验证）
    L = 0.65
    a_lo, a_hi, b_lo, b_hi = ab_slice_at_L(L, n=1201)
    bs = np.linspace(b_lo - 0.03, b_hi + 0.03, 601)
    as_ = np.linspace(a_lo - 0.03, a_hi + 0.03, 601)
    rep("a 上界贴边", bool(in_gamut(L, a_hi - 5e-4, bs).any())
        and not bool(in_gamut(L, a_hi + 8e-3, bs).any()), "a ∈ [%+.4f, %+.4f]" % (a_lo, a_hi))
    rep("a 下界贴边", bool(in_gamut(L, a_lo + 5e-4, bs).any())
        and not bool(in_gamut(L, a_lo - 8e-3, bs).any()))
    rep("b 上界贴边", bool(in_gamut(L, as_, b_hi - 5e-4).any())
        and not bool(in_gamut(L, as_, b_hi + 8e-3).any()), "b ∈ [%+.4f, %+.4f]" % (b_lo, b_hi))
    rep("b 下界贴边", bool(in_gamut(L, as_, b_lo + 5e-4).any())
        and not bool(in_gamut(L, as_, b_lo - 8e-3).any()))

    # 5b) 单线可行区间（回归：可行区间可能整段不含灰轴 b=0）
    L0, b_ref = 0.662366, -0.115906
    lo, hi = axis_interval(L0, b_ref, "a")
    rep("a 单线区间两端可行", in_gamut(L0, lo, b_ref) and in_gamut(L0, hi, b_ref),
        "[%+.4f, %+.4f]" % (lo, hi))
    rep("a 单线区间之外不可行", (not in_gamut(L0, lo - 6e-3, b_ref))
        and not in_gamut(L0, hi + 6e-3, b_ref))
    a_far = hi * 0.985
    b_lo, b_hi = axis_interval(L0, a_far, "b")
    rep("极端 a 处的 b 区间不塌成一点", b_hi - b_lo > 1e-3, "宽 %.4f" % (b_hi - b_lo))
    rep("极端 a 处灰轴 b=0 在域外、b 区间仍算对",
        (not in_gamut(L0, a_far, 0.0)) and in_gamut(L0, a_far, b_hi))

    # 6) 固定量程方案确实存在死区
    dead = strip_out_of_gamut(64, "a", "A", 0.65, 0.0, 0.0)
    rep("方案 A 有超色域区段", bool(dead.any()), "dead=%d/64" % int(dead.sum()))

    # 6b) 彩度条线性口径：t = C_rel，不再用弧长等分
    hC, sC, vC = 210.0, 0.62, 0.86
    rgbC = mc.hsv_to_srgb(hC, sC, vC)
    LC, aC, bC = (float(x) for x in srgb_to_oklab(rgbC))
    crelC = float(mc.crel_of_xyz(hC, "oklab", sC, vC)[0])
    rep("C 条游标位置 = C_rel（线性）",
        abs(crel_linear_t(hC, LC, sC, vC) - crelC) < 1e-12, "t=%.6f" % crelC)
    arrC = strip_image_C(129, hC, LC, height=1)
    Lm, am, bm = (float(x) for x in srgb_to_oklab(arrC[0, 64].astype(np.float64) / 255.0))
    Cm = float(np.hypot(am, bm))
    cmaxC = float(np.asarray(mc.cmax_of_L(hC, "oklab", np.array([LC]))).reshape(-1)[0])
    rep("C 条中点像素 C ≈ 0.5·C_max（线性）",
        abs(Cm - 0.5 * cmaxC) < 3e-3,
        "C=%.6f 期望=%.6f 差=%.2e" % (Cm, 0.5 * cmaxC, abs(Cm - 0.5 * cmaxC)))
    Cs = []
    for x in (8, 64, 120):
        _Lx, _ax, _bx = (float(y) for y in srgb_to_oklab(arrC[0, x].astype(np.float64) / 255.0))
        Cs.append(float(np.hypot(_ax, _bx)))
    rep("C 条像素 C 随位置单调增", Cs[0] < Cs[1] < Cs[2],
        "C=%s" % ", ".join("%.5f" % c for c in Cs))

    # 7) 当前色数值（写进文档用）
    rgb01 = mc.hsv_to_srgb(210, 0.62, 0.86)
    L, a, b = (float(t) for t in srgb_to_oklab(rgb01))
    print("     预览色 %s  L=%.6f  a=%+.6f  b=%+.6f  C_oklab=%.6f  C_CIE=%s"
          % (hex_of(rgb01), L, a, b, float(np.hypot(a, b)),
             round(float(mc.lab_L_C(210, 0.62, 0.86)[1]), 3)))
    a_lo, a_hi, b_lo, b_hi = ab_slice_at_L(L)
    print("     L=%.4f 处切片：a ∈ [%+.4f, %+.4f]  b ∈ [%+.4f, %+.4f]"
          % (L, a_lo, a_hi, b_lo, b_hi))
    return ok


def out_dir_now():
    """按当天日期生成输出目录（docs/yyyy年MM月/yyyy年MM月dd日/images）。"""
    import datetime
    now = datetime.datetime.now()
    d = _ROOT / "docs" / now.strftime("%Y年%m月") / now.strftime("%Y年%m月%d日") / "images"
    d.mkdir(parents=True, exist_ok=True)
    return d


def main():
    out_dir = out_dir_now()
    out_dir.mkdir(parents=True, exist_ok=True)
    h, s, v = 210.0, 0.62, 0.86

    H2, H4 = panel_height(2), panel_height(4)
    W = 24 + PANEL_W * 2 + 40
    top = 92
    c = Canvas(W, top + H4 + 320 + 40)
    c.text(24, 14, "馍馍拾色器 · Oklab a/b 分量条 · 效果预览", size=15, bold=True)
    rgb01 = mc.hsv_to_srgb(h, s, v)
    L, a_now, b_now = (float(t) for t in srgb_to_oklab(rgb01))
    C_ok = float(np.hypot(a_now, b_now))
    C_cie = float(mc.lab_L_C(h, s, v)[1])
    c.text(24, 40, "示例颜色 %s ｜ 真 Oklab：L=%.4f  a=%+.4f  b=%+.4f  C=%+.4f"
           % (hex_of(rgb01), L, a_now, b_now, C_ok), size=10)

    draw_panel(c, 24, top, h=h, s=s, v=v, show_ab=False, variant="C",
               title="① 现状：明度 + 彩度 两条", subtitle="当前插件（相对彩度 C_rel，量程 0~1）")
    draw_panel(c, 24 + PANEL_W + 40, top, h=h, s=s, v=v, show_ab=True, variant="B",
               title="② 加 a 条 + b 条后的样子（已实现，默认方案 B）",
               subtitle="量程 = 当前明度的色域切片包围盒（刻度只随 L 变，灰色斜纹=此刻拖不到）")

    y_band = top + max(H2, H4) + 46
    y_end = draw_variant_band(c, 24, y_band, W - 48, h=h, s=s, v=v)
    c.text(24, y_end + 14, "⚠ 现有插件的「彩度」C 用的是 CIE Lab 的 C*ab（本例 %.1f，量程 0~150）再按同明度最大值归一化，"
                           "并非 Oklab 彩度 —— 所以现在还不是严格意义的 OKLCH。" % C_cie, size=10, fill=ACCENT)
    c.text(24, y_end + 30, "拖动 a / b 条时：明度 L 与另一分量不动，色相环游标与方块色点会跟着移动"
                           "（(L,a,b) 与 (L,C,h) 是同一个三维空间的两组坐标）。", size=9, fill=TEXT_DIM)
    c.text(24, y_end + 44, "本图为离线渲染示意，非插件截图；线簇与过点线未画。", size=9, fill=TEXT_DIM)
    c.crop_to(y_end + 62)

    out = out_dir / "preview-oklab-ab-strips.png"
    c.save(out)
    print("已输出：%s  (%d×%d)" % (out, c.w, c.h))
    main_frames(out_dir, h, s, v)
    return out




# ================================================================ 图 2：拖动 a 条的三个瞬间

def frame_of(L, a, b):
    """(L,a,b) -> 该色的 HSV（拖动 a 条后的真实结果）。"""
    rgb = oklab_to_srgb(L, a, b)
    h, s, v = mc.srgb_to_hsv(*(float(c) for c in rgb))
    return rgb, float(h), float(s), float(v)


def draw_frame(c, x, y, *, L, a, b, title, highlight=None):
    FW, SIDE, SH, LAB = 300, 208, 18, 34
    c.text(x, y, title, size=12, bold=True)
    rgb, h, s, v = frame_of(L, a, b)
    _draw_picker(c, x + (FW - SIDE) / 2.0, y + 22, SIDE, h, s, v)

    yy = y + 22 + SIDE + 10
    sw = FW - LAB - 60
    rows = [("L", strip_image_L(sw, SH), L, "%.4f" % L),
            ("C", strip_image_C(sw, h, L, SH), crel_linear_t(h, L, s, v), "%.4f" % (s * v)),
            ("a", None, 0.0, "%+.4f" % a),
            ("b", None, 0.0, "%+.4f" % b)]
    data = []
    arr_a, (alo, ahi) = strip_image_ab(sw, "a", "C", L, a, b)
    arr_b, (blo, bhi) = strip_image_ab(sw, "b", "C", L, a, b)
    rows[2] = ("a", arr_a, (a - alo) / max(1e-9, ahi - alo), "%+.4f" % a)
    rows[3] = ("b", arr_b, (b - blo) / max(1e-9, bhi - blo), "%+.4f" % b)
    for label, arr, t, txt in rows:
        c.text(x, yy + SH / 2.0, label, size=9, anchor="lm",
               fill=ACCENT if label == highlight else TEXT)
        _draw_strip(c, x + LAB, yy, sw, arr, float(np.clip(t, 0, 1)))
        c.text(x + LAB + sw + 6, yy + SH / 2.0, txt, size=9, anchor="lm", fill=TEXT_DIM)
        if label == highlight:
            c.rect(x + LAB - 2, yy - 2, sw + 4, SH + 4, outline=ACCENT, lw=1)
        yy += SH + 3
    c.text(x, yy + 6, "色相 %.1f°　彩度 C=%.4f　HEX %s" % (h, float(np.hypot(a, b)), hex_of(rgb)),
           size=9, fill=TEXT_DIM)
    c.text(x, yy + 20, "a 条量程 [%+.3f, %+.3f]　b 条量程 [%+.3f, %+.3f]"
           % (alo, ahi, blo, bhi), size=9, fill=TEXT_DIM)
    return yy + 34


def main_frames(out_dir, h0, s0, v0):
    rgb01 = mc.hsv_to_srgb(h0, s0, v0)
    L, a0, b0 = (float(t) for t in srgb_to_oklab(rgb01))
    arr, (alo, ahi) = strip_image_ab(400, "a", "C", L, a0, b0)
    picks = [a0, alo + 0.62 * (ahi - alo), alo + 0.985 * (ahi - alo)]
    titles = ["① 起始", "② 把 a 条拖到 62%", "③ 把 a 条拖到最右"]
    W = 24 + 3 * 300 + 2 * 30
    H = 24 + 40 + 22 + 208 + 10 + 4 * 21 + 60 + 20
    c = Canvas(W, H)
    c.text(24, 14, "拖动 a 条时面板怎么变（b 与 L 不动，色点沿等明度线滑走）", size=15, bold=True)
    c.text(24, 38, "同一 a 条、同一 b 与 L；只改 a —— 看色相游标 / 方块色点 / 彩度读数如何跟着走。"
                   "注意：方案 C 下 b 条的刻度会随 a 变化（可达范围变了）。", size=10, fill=TEXT_DIM)
    for i, (a_val, title) in enumerate(zip(picks, titles)):
        draw_frame(c, 24 + i * 330, 72, L=L, a=a_val, b=b0, title=title, highlight="a")
    c.text(24, H - 26, "结论：加 a/b 条 = 给同一个三维颜色多一组坐标入口；"
                       "色相环与方块仍然是「当前色」的显示，不会被取代。", size=10, fill=ACCENT)
    c.crop_to(H)
    out = out_dir / "preview-oklab-ab-drag.png"
    c.save(out)
    print("已输出：%s  (%d×%d)" % (out, c.w, c.h))
    return out


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if "--check" in sys.argv:
        sys.exit(0 if check() else 1)
    check()
    main()
