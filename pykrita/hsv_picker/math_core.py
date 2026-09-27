# -*- coding: utf-8 -*-
"""HSV / Oklab / 相对彩度 数学内核（纯 numpy，不依赖 Krita 与 Qt）。

从 Tkinter 版 hsv_lightness_picker.py 的数学层整体搬移，并删去：
  · 已废弃的 ∇L 正交族：ortho_family / ortho_through / point_where_L
  · 绝对彩度专用：iso_cabs_curve / solve_s_cabs_scalar
  · Tk 渲染层：curve_px / render_ring / render_square / _png_b64 / to_photoimage / ring_array
绘图与控件相关的几何、颜色常量也一律不带（改由 Qt 侧的自绘控件负责）。
本模块可用系统 Python + numpy 直接单测，见 tools/math_selftest.py。

坐标约定：
    h ∈ [0, 360)  色相（度）
    s, v ∈ [0, 1] HSV 的饱和度 / 明度
    metric = "oklab" 时 L ∈ [0, 1]；"lab"（CIE L*）时 L ∈ [0, 100]
    C = √(a²+b²)（Oklab 绝对彩度）；C_rel = C / C_max(色相, 明度) ∈ [0, 1]
"""

from __future__ import annotations

import math
import re

import numpy as np


def v_from_lightness(metric, L):
    """指标明度 L -> 对应灰阶的 HSV V（向量化；与 lightness(h,0,V,metric) 严格互逆）。

    · oklab: L = cbrt(Y)，Y = V^2.4 附近的编码关系 -> V = cbrt(L)^2.4 的精确反解
    · lab  : 标准 CIE L* -> Y 分段函数，再取 sRGB 编码
    注意：不要用 _v_gray()，它内部还套了一次 _srgb_encode，只适合明度尺图像取样。
    """
    L = np.asarray(L, dtype=np.float64)
    if metric == "gray":
        # 灰阶口径：L 本身就是 srgb_encode(Y) 的码值，中性色 R=G=B=V ⇒ L == V
        return np.clip(L, 0.0, 1.0)
    if metric == "oklab":
        # Oklab 灰阶: L = cbrt(Y) -> Y = L^3；V 是 Y 的 sRGB 编码值
        Y = np.clip(L, 0.0, 1.0) ** 3
    else:
        f = (np.clip(L, 0.0, 100.0) + 16.0) / 116.0
        Y = np.where(f > 6.0 / 29.0, f ** 3, (f - 4.0 / 29.0) * 3.0 * (6.0 / 29.0) ** 2)
    Y = np.clip(Y, 0.0, 1.0)
    V = np.where(Y <= 0.0031308, 12.92 * Y, 1.055 * np.power(Y, 1.0 / 2.4) - 0.055)
    return np.clip(V, 0.0, 1.0)


def filter_crel_line(h, metric, ss, vv, c_min=0.0025):
    """过滤等 C_rel 线上「数值不可信」的**近黑端**（供等彩度线/明度条共用）。

    · 近黑处绝对彩度 C 太小、C_rel 比值病态 -> 只保留 C ≥ c_min 的段；
      阈值是 Oklab 尺度：C ∈ [0, 0.33]，0.0025 ≈ 旧版 CIE Lab 尺度下的 1.0；
    · 亮端不用过滤：实测 V→1 时 S 平滑收敛到 0（纯白），是正确极限。
    """
    ss = np.asarray(ss, dtype=np.float64)
    vv = np.asarray(vv, dtype=np.float64)
    keep = np.zeros(len(ss), dtype=bool)
    for i in range(len(ss)):
        vi, si = float(vv[i]), float(ss[i])
        if vi < 0.002:
            continue
        try:
            if float(crel_of_xyz(h, metric, si, vi)[1]) >= c_min:
                keep[i] = True
        except Exception:
            pass
    if int(keep.sum()) < 2:
        return ss, vv
    return ss[keep], vv[keep]


def clamp(x, lo, hi):
    return lo if x < lo else (hi if x > hi else x)


# ================================================================ 颜色数学
def hsv_to_srgb(h, s, v):
    """HSV -> gamma 编码 sRGB（0~1）。h 可为标量或数组（度），s/v 形状与之匹配。

    用标准六扇区公式（每个扇区 (R,G,B) 是 (c,x,0) 的轮换），保证
    0°红、60°黄、120°绿、180°青、240°蓝、300°品红。
    标量入参走**纯 Python 快路径**：内部被调用的次数极多（等明度曲线二分里每帧上千次），
    numpy 的标量调度开销比算本身还大。
    """
    if not (isinstance(h, np.ndarray) or isinstance(s, np.ndarray) or isinstance(v, np.ndarray)):
        hh = float(h) % 360.0
        ss = float(s)
        vv = float(v)
        hp = hh / 60.0
        k = int(hp) % 6
        f = hp - int(hp)
        p = vv * (1.0 - ss)
        q = vv * (1.0 - ss * f)
        t = vv * (1.0 - ss * (1.0 - f))
        r, g, b = ((vv, t, p), (q, vv, p), (p, vv, t),
                   (p, q, vv), (t, p, vv), (vv, p, q))[k]
        return np.array([r, g, b], dtype=np.float64)

    h = np.asarray(h, dtype=np.float64) % 360.0
    s = np.asarray(s, dtype=np.float64)
    v = np.asarray(v, dtype=np.float64)
    hp = h / 60.0
    k = np.floor(hp).astype(np.intp) % 6
    f = hp - np.floor(hp)
    p = v * (1.0 - s)
    q = v * (1.0 - s * f)
    t = v * (1.0 - s * (1.0 - f))
    r = np.choose(k, [v, q, p, p, t, v])          # np.choose 比 3 次 np.select 快 ~1.5 倍
    g = np.choose(k, [t, v, v, q, p, p])
    b = np.choose(k, [p, p, t, v, v, q])
    out = np.stack([r, g, b], axis=-1)
    if h.ndim == 0 and s.ndim == 0 and v.ndim == 0:   # 全标量 -> 返回 (3,)
        return out.reshape(3)
    return out


def srgb_to_linear(c):
    c = np.clip(np.asarray(c, dtype=np.float64), 0.0, 1.0)
    return np.where(c <= 0.04045, c / 12.92, ((c + 0.055) / 1.055) ** 2.4)


def srgb_to_hsv(r, g, b):
    """(r,g,b) ∈ 0~1 -> (h 度, s, v)。"""
    mx = max(r, g, b)
    mn = min(r, g, b)
    d = mx - mn
    if d <= 1e-12:
        h = 0.0
    elif mx == r:
        h = 60.0 * (((g - b) / d) % 6.0)
    elif mx == g:
        h = 60.0 * ((b - r) / d + 2.0)
    else:
        h = 60.0 * ((r - g) / d + 4.0)
    s = 0.0 if mx <= 1e-12 else d / mx
    return h % 360.0, s, mx


_Y_SUM = 0.2126729 + 0.7151522 + 0.0721750          # sRGB D65 Y 系数之和（≈1.0000001，归一化用）
_EPS_Y = 216.0 / 24389.0        # (6/29)^3
_KAPPA_Y = 24389.0 / 27.0


def _lab_l_from_Y(Y):
    """CIE Lab 明度 L*（D65 白点，Y 为相对亮度 0~1）。"""
    f = np.where(Y > _EPS_Y, np.cbrt(Y), (_KAPPA_Y * Y + 16.0) / 116.0)
    return 116.0 * f - 16.0


def lightness(h, s, v, metric="lab"):
    """视觉明度。

    metric='lab'   -> CIE Lab L*，0~100
    metric='oklab' -> Oklab L，0~1
    metric='gray'  -> 灰阶码值 srgb_encode(Y)，0~1（Y = 线性 sRGB 亮度 / Σ，纯白 = 1）
    """
    lin = srgb_to_linear(hsv_to_srgb(h, s, v))
    R, G, B = lin[..., 0], lin[..., 1], lin[..., 2]
    if metric == "oklab":
        l_ = 0.4122214708 * R + 0.5363325363 * G + 0.0514459929 * B
        m_ = 0.2119034982 * R + 0.6806995451 * G + 0.1073969566 * B
        s_ = 0.0883024619 * R + 0.2817188376 * G + 0.6299787005 * B
        return (0.2104542553 * np.cbrt(l_) + 0.7936177850 * np.cbrt(m_)
                - 0.0040720468 * np.cbrt(s_))
    # sRGB (IEC 61966-2-1) D65 亮度系数，除以系数之和让纯白正好 = 1
    Y = (0.2126729 * R + 0.7151522 * G + 0.0721750 * B) / _Y_SUM
    if metric == "gray":
        return _srgb_encode(Y)
    return _lab_l_from_Y(Y)


# ================================================================ Oklab a/b 分量与 sRGB 色域工具

_OK_GAMUT_TOL = 3e-5        # 色域判定的线性空间容差（≈0.06/255，肉眼不可辨）
_AB_LIM = 0.45              # a/b 的搜索半径（sRGB 色域内 |a|≤0.277、|b|≤0.312，留足余量）
_AB_SLICE_CACHE = {}        # {(round(L,4)): (a_lo, a_hi, b_lo, b_hi)}
_AB_IVAL_CACHE = {}         # {(round(L,4), round(other,4), axis): (lo, hi)}
_AB_EXACT_CACHE = {}        # {(round(L,9), round(other,9), axis, seed)}: 区间或 False=空


def oklab_ab(h, s, v):
    """HSV -> Oklab (L, a, b)，支持标量/数组（与 lightness(..., "oklab") 同一矩阵）。"""
    lin = srgb_to_linear(hsv_to_srgb(h, s, v))
    R, G, B = lin[..., 0], lin[..., 1], lin[..., 2]
    l_ = np.cbrt(0.4122214708 * R + 0.5363325363 * G + 0.0514459929 * B)
    m_ = np.cbrt(0.2119034982 * R + 0.6806995451 * G + 0.1073969566 * B)
    s_ = np.cbrt(0.0883024619 * R + 0.2817188376 * G + 0.6299787005 * B)
    return (0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_,
            1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_,
            0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_)


def ok_L_C(h, s, v):
    """Oklab 口径的 (L, C)：L 为 Oklab 明度、C = √(a²+b²) 为绝对彩度。

    **全插件的彩度只有这一个来源**（彩度条 / 等彩度线 / 数值框 / 锁定约束）。
    """
    L, a, b = oklab_ab(h, s, v)
    return L, np.hypot(a, b)


def oklab_to_srgb(L, a, b, clip=True):
    """Oklab -> sRGB。clip=True 返回伽马编码 0~1；clip=False 返回**线性**值（判色域用，可越界）。"""
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l, m, s = l_ ** 3, m_ ** 3, s_ ** 3
    lin = np.stack([
        4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s,
        -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s,
        -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s], axis=-1)
    if not clip:
        return lin
    return np.clip(_srgb_encode(lin), 0.0, 1.0)


def oklab_in_gamut(L, a, b, tol=_OK_GAMUT_TOL):
    """(L,a,b) 是否落在 sRGB 色域内；支持标量/数组（数组返回布尔数组）。

    标量走**纯 Python 快路径**：可行区间二分里每帧要调上百次，
    numpy 标量调度的 6.4us/次 会变成 0.65ms/次（实测），纯 float 只要 ~1us。
    """
    if not (isinstance(a, np.ndarray) or isinstance(b, np.ndarray)
            or isinstance(L, np.ndarray)):
        Lf, af, bf = float(L), float(a), float(b)
        l_ = Lf + 0.3963377774 * af + 0.2158037573 * bf
        m_ = Lf - 0.1055613458 * af - 0.0638541728 * bf
        s_ = Lf - 0.0894841775 * af - 1.2914855480 * bf
        l, m, s = l_ * l_ * l_, m_ * m_ * m_, s_ * s_ * s_
        r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
        if r < -tol or r > 1.0 + tol:
            return False
        g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
        if g < -tol or g > 1.0 + tol:
            return False
        bl = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
        return -tol <= bl <= 1.0 + tol
    lin = oklab_to_srgb(L, a, b, clip=False)
    return np.all(lin >= -tol, axis=-1) & np.all(lin <= 1.0 + tol, axis=-1)


def _ab_inside(L, other, axis, x):
    if axis == "a":
        return bool(oklab_in_gamut(L, x, other))
    return bool(oklab_in_gamut(L, other, x))


def _ab_bisect_edge(x_in, x_out, L, other, axis, iters=16):
    """x_in 在色域内、x_out 在外 -> 二分夹出边界，返回色域内那一侧。"""
    for _ in range(iters):
        mid = 0.5 * (x_in + x_out)
        if _ab_inside(L, other, axis, mid):
            x_in = mid
        else:
            x_out = mid
    return float(x_in)


def ab_axis_interval(L, other, axis="a", lim=_AB_LIM, n=161):
    """固定另一分量，求该分量在 sRGB 色域内的**可行区间** [lo, hi]。

    注意：**不能假设 0（灰轴）一定可行** —— 色域边界可能整段落在同一侧，
    所以先栅格扫一遍找可行样本，再向两侧二分；区间为空时返回 (0.0, 0.0)。
    量程随 (L, 另一分量) 变化 —— 这就是「满量程永远可达」口径。
    """
    # 键粗到 3 位小数：拖动时明度/另一分量每帧都在动，4 位会让缓存几乎每帧失效
    key = (round(float(L), 3), round(float(other), 3), axis)
    hit = _AB_IVAL_CACHE.get(key)
    if hit is not None:
        return hit
    xs = np.linspace(-lim, lim, int(n))
    if axis == "a":
        ok = oklab_in_gamut(float(L), xs, np.full_like(xs, float(other)))
    else:
        ok = oklab_in_gamut(float(L), np.full_like(xs, float(other)), xs)
    idx = np.flatnonzero(ok)
    if idx.size == 0:
        out = (0.0, 0.0)
    else:
        i0, i1 = int(idx[0]), int(idx[-1])
        out = (_ab_bisect_edge(xs[i0], xs[i0 - 1] if i0 > 0 else xs[i0], L, other, axis),
               _ab_bisect_edge(xs[i1], xs[i1 + 1] if i1 < n - 1 else xs[i1], L, other, axis))
    if len(_AB_IVAL_CACHE) > 512:
        _AB_IVAL_CACHE.clear()
    _AB_IVAL_CACHE[key] = out
    return out


def ab_axis_interval_exact(L, other, axis="a", lim=_AB_LIM, seed=None, iters=40, n=8193):
    """固定另一分量，求该分量在 sRGB 色域内的**精确可行区间** [lo, hi]；空区间返回 None。

    与 ``ab_axis_interval`` 的区别只在「栅格扫不到窄切片」这一退化情形：
    固定 L 与另一分量后，可行集合在 x 轴上是一个区间；某些切片是切点/宽度小于栅格
    步长（如 h=60°, v=1 的纯黄切片只有一个点），161 点栅格会一个样本都扫不到，
    旧实现就返回了 (0.0, 0.0)。本函数优先用调用方给出的 seed（按下时刻的当前分量，
    必然在可行区间内）向两侧扩张 + 二分，因此退化切片也能返回真实区间（切点 -> [x0,x0]）。
    没有可用 seed 时退到高密度栅格（8193 点）；确实一个可行点都没有 -> None（明确空区间）。
    """
    Lf, otherf = float(L), float(other)
    seedf = None if seed is None else float(seed)
    key = (round(Lf, 9), round(otherf, 9), axis,
           None if seedf is None else round(seedf, 9), round(float(lim), 9))
    hit = _AB_EXACT_CACHE.get(key, "MISS")
    if hit != "MISS":
        return None if hit is False else hit

    def inside(x):
        return _ab_inside(Lf, otherf, axis, x)

    def expand(direction):
        step = 0.02
        x_in = seedf
        x = seedf
        while True:
            xn = x + direction * step
            xn = max(-lim, xn) if direction < 0 else min(lim, xn)
            if inside(xn):
                x_in = xn
                if xn <= -lim or xn >= lim:
                    return xn
                x = xn
                step *= 1.5
            else:
                x_out = xn
                for _ in range(int(iters)):
                    mid = 0.5 * (x_in + x_out)
                    if inside(mid):
                        x_in = mid
                    else:
                        x_out = mid
                return x_in

    if seedf is not None and inside(seedf):
        out = (expand(-1.0), expand(1.0))
    else:
        xs = np.linspace(-float(lim), float(lim), int(n))
        if axis == "a":
            ok = oklab_in_gamut(Lf, xs, np.full_like(xs, otherf))
        else:
            ok = oklab_in_gamut(Lf, np.full_like(xs, otherf), xs)
        idx = np.flatnonzero(ok)
        if idx.size == 0:
            out = None
        else:
            i0, i1 = int(idx[0]), int(idx[-1])
            out = (_ab_bisect_edge(xs[i0], xs[i0 - 1] if i0 > 0 else xs[i0],
                                   Lf, otherf, axis, iters=iters),
                   _ab_bisect_edge(xs[i1], xs[i1 + 1] if i1 < n - 1 else xs[i1],
                                   Lf, otherf, axis, iters=iters))
    if len(_AB_EXACT_CACHE) > 512:
        _AB_EXACT_CACHE.clear()
    _AB_EXACT_CACHE[key] = False if out is None else out
    return out


def ab_axis_interval_seeded(L, other, axis="a", seed=None, lim=_AB_LIM, n=161):
    """gray 路径专用：旧栅格区间仍可用时保持旧行为，否则用 seed 精确区间。

    本函数只修「旧 161 点栅格扫不到切片」的退化情形（典型 h=60°,v=1：
    旧实现返回 (0,0)，把当前分量误钳到 0）。判定「旧区间可用」= 旧区间包含
    当前分量 seed（当前色一定在真实切片内）：
      · 包含 -> 返回旧区间（绝大多数颜色，行为/数字保持不变）；
      · 不包含 -> 用 ``ab_axis_interval_exact(seed=...)`` 返回包含 seed 的真实
        连通区间；真找不到 -> None（明确空区间）。
    oklab 路径不经过本函数，仍直接调用 ``ab_axis_interval``，逐位不变。
    """
    old = ab_axis_interval(L, other, axis, lim=lim, n=n)
    if seed is not None:
        s = float(seed)
        if old[0] - 1e-9 <= s <= old[1] + 1e-9:
            return old
    return ab_axis_interval_exact(L, other, axis, lim=lim, seed=seed, n=8193)


# ---- gray 口径：a/b 条的「目标灰阶可达」区间（多采样 + 向量化）----

_GRAY_AB_L_BASE = {}        # {n_L: L 采样点数组（含 0 / 1）}


def _gray_l_samples(n_L, l_hint=None):
    """L 轴采样点：均匀 n_L 个（含端点）；l_hint（按下时刻当前色的 Oklab L）额外并入。"""
    n_L = int(n_L)
    if n_L < 2:
        n_L = 2
    base = _GRAY_AB_L_BASE.get(n_L)
    if base is None:
        base = np.linspace(0.0, 1.0, n_L)
        if len(_GRAY_AB_L_BASE) > 8:
            _GRAY_AB_L_BASE.clear()
        _GRAY_AB_L_BASE[n_L] = base
    if l_hint is None:
        return base
    hint = float(l_hint)
    if hint < 0.0 or hint > 1.0:
        return base
    if float(np.min(np.abs(base - hint))) <= 1e-12:
        return base
    return np.sort(np.concatenate([base, np.array([hint], dtype=np.float64)]))


def gray_from_oklab(L, a, b):
    """(Oklab L, a, b) -> 灰阶码值 srgb_encode(Y)（线性 sRGB 先钳到 [0,1]），支持广播。

    与 ``lightness(srgb_to_hsv(oklab_to_srgb(...)), "gray")`` 的差别只有 sRGB 往返
    的 ~1e-16 数值噪声；供 gray 口径的可达区间向量化求值。
    """
    L = np.asarray(L, dtype=np.float64)
    a = np.asarray(a, dtype=np.float64)
    b = np.asarray(b, dtype=np.float64)
    l_ = L + 0.3963377774 * a + 0.2158037573 * b
    m_ = L - 0.1055613458 * a - 0.0638541728 * b
    s_ = L - 0.0894841775 * a - 1.2914855480 * b
    l = l_ * l_ * l_
    m = m_ * m_ * m_
    s = s_ * s_ * s_
    r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    bl = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
    r = np.clip(r, 0.0, 1.0)
    g = np.clip(g, 0.0, 1.0)
    bl = np.clip(bl, 0.0, 1.0)
    Y = (0.2126729 * r + 0.7151522 * g + 0.0721750 * bl) / _Y_SUM
    return _srgb_encode(Y)


def gray_from_oklab_py(L, a, b):
    """标量快路径：与 gray_from_oklab 同式（numpy 标量调度 ~10us -> 纯 float ~1us）。"""
    Lf, af, bf = float(L), float(a), float(b)
    l_ = Lf + 0.3963377774 * af + 0.2158037573 * bf
    m_ = Lf - 0.1055613458 * af - 0.0638541728 * bf
    s_ = Lf - 0.0894841775 * af - 1.2914855480 * bf
    l = l_ * l_ * l_
    m = m_ * m_ * m_
    s = s_ * s_ * s_
    r = 4.0767416621 * l - 3.3077115913 * m + 0.2309699292 * s
    if r < 0.0:
        r = 0.0
    elif r > 1.0:
        r = 1.0
    g = -1.2684380046 * l + 2.6097574011 * m - 0.3413193965 * s
    if g < 0.0:
        g = 0.0
    elif g > 1.0:
        g = 1.0
    bl = -0.0041960863 * l - 0.7034186147 * m + 1.7076147010 * s
    if bl < 0.0:
        bl = 0.0
    elif bl > 1.0:
        bl = 1.0
    Y = (0.2126729 * r + 0.7151522 * g + 0.0721750 * bl) / _Y_SUM
    if Y <= 0.0031308:
        return 12.92 * Y
    return 1.055 * (Y ** (1.0 / 2.4)) - 0.055


_GRAY_GS_ITERS = 10         # 采样极值邻域的黄金分割细化次数（真实求值，不是插值）
_GRAY_GS_PHI = (math.sqrt(5.0) - 1.0) / 2.0


def gray_l_range(axis, other, x, n_L=17, l_hint=None, gs_iters=_GRAY_GS_ITERS,
                 l_samples=None):
    """固定 x，求灰阶码值在 L∈[0,1] 上的 (min, max)。

    先均匀采 n_L 个 L（默认 17，另含 l_hint），再对采样 argmin/argmax 的
    左右邻域做黄金分割细化。所有求值点都是真实的 L，得到的范围一定是真实范围的
    子集 ⇒ 判定**永不把不可达判成可达（假可达恒为 0）**；细化只减少「窄极值被
    均匀采样漏掉」造成的假不可达。返回 (float, float)。
    l_samples：可选的预排序采样数组（同一次区间求解内复用，省重复构造）。
    """
    Ls = _gray_l_samples(n_L, l_hint) if l_samples is None else np.asarray(l_samples)
    if axis == "a":
        vals = [gray_from_oklab_py(float(lv), float(x), float(other)) for lv in Ls]
    else:
        vals = [gray_from_oklab_py(float(lv), float(other), float(x)) for lv in Ls]
    i_min = min(range(len(vals)), key=vals.__getitem__)
    i_max = max(range(len(vals)), key=vals.__getitem__)

    def refine(idx, want_min):
        lo_l = float(Ls[max(0, idx - 1)])
        hi_l = float(Ls[min(len(Ls) - 1, idx + 1)])
        if hi_l - lo_l <= 1e-15:
            return float(vals[idx])
        gr = _GRAY_GS_PHI
        a_l, b_l = lo_l, hi_l
        c_l = b_l - gr * (b_l - a_l)
        d_l = a_l + gr * (b_l - a_l)

        def f(lv):
            if axis == "a":
                return gray_from_oklab_py(lv, x, other)
            return gray_from_oklab_py(lv, other, x)

        fc, fd = f(c_l), f(d_l)
        for _ in range(int(gs_iters)):
            if (fc < fd) == bool(want_min):
                b_l, d_l, fd = d_l, c_l, fc
                c_l = b_l - gr * (b_l - a_l)
                fc = f(c_l)
            else:
                a_l, c_l, fc = c_l, d_l, fd
                d_l = a_l + gr * (b_l - a_l)
                fd = f(d_l)
        return min(fc, fd) if want_min else max(fc, fd)

    lo = min(vals[i_min], refine(i_min, True), vals[0], vals[-1])
    hi = max(vals[i_max], refine(i_max, False), vals[0], vals[-1])
    return float(lo), float(hi)


def gray_reachable_mask(axis, other, target, x, n_L=17, l_hint=None, tol=1e-12,
                        refine=True, l_samples=None, gs_iters=_GRAY_GS_ITERS):
    """gray 口径下固定另一分量 other 时，本分量 x 是否「存在 Oklab L 使灰阶 == target」。

    refine=True（默认）：每个 x 用 ``gray_l_range``（17 点 + 黄金分割细化）求
    min/max；target 落在其中即判可达。范围始终是真实值的子集 ⇒ 假可达恒为 0。
    refine=False：只做 n_L 点均匀 min/max（更快，用于批量对照/扫描）；同样保守。
    支持 x 数组；axis ∈ {"a","b"}；l_samples 可复用预排序采样数组。
    """
    xs = np.atleast_1d(np.asarray(x, dtype=np.float64))
    targetf = float(target)
    if not refine:
        sample_arr = _gray_l_samples(n_L, l_hint) if l_samples is None else np.asarray(l_samples)
        if axis == "a":
            g = gray_from_oklab(sample_arr[:, None], xs[None, :], float(other))
        else:
            g = gray_from_oklab(sample_arr[:, None], float(other), xs[None, :])
        lo = g.min(axis=0)
        hi = g.max(axis=0)
        return (lo - float(tol) <= targetf) & (targetf <= hi + float(tol))
    sample_arr = _gray_l_samples(n_L, l_hint) if l_samples is None else np.asarray(l_samples)
    out = np.zeros(xs.shape, dtype=bool)
    for i, xv in enumerate(xs.ravel()):
        lo, hi = gray_l_range(axis, other, float(xv), n_L=n_L, l_hint=l_hint,
                              gs_iters=gs_iters, l_samples=sample_arr)
        out.ravel()[i] = (lo - float(tol)) <= targetf <= (hi + float(tol))
    return out


def gray_component_interval(axis, other, target, x0, lim=_AB_LIM, n_L=17,
                            l_hint=None, iters=16, tol=1e-12,
                            gs_iters=_GRAY_GS_ITERS):
    """gray 口径下本分量「目标灰阶可达」区间 [lo, hi]（x0 不可达 -> None=明确空区间）。

    以按下时刻的 x0（当前色分量，必然可达）为锚点，向两侧扩张 + 二分；两侧每轮
    批量求值以摊薄 numpy 调用开销。多采样口径见 ``gray_reachable_mask``。
    """
    x0f = float(x0)
    limf = float(lim)
    samples = _gray_l_samples(n_L, l_hint)   # 一次构造，整个区间求解复用

    def reach(xs):
        return gray_reachable_mask(axis, other, target, xs, n_L=n_L,
                                   l_hint=l_hint, tol=tol, l_samples=samples,
                                   gs_iters=gs_iters)

    if not bool(reach(np.array([x0f], dtype=np.float64))[0]):
        return None
    inside = np.array([x0f, x0f], dtype=np.float64)      # [左边界内点, 右边界内点]
    outside = np.array([np.nan, np.nan], dtype=np.float64)
    walk = np.array([x0f, x0f], dtype=np.float64)
    step = np.array([0.03, 0.03], dtype=np.float64)
    found = np.array([False, False])
    for _ in range(64):
        if bool(found.all()):
            break
        cand = walk + np.array([-step[0], step[1]])
        cand = np.clip(cand, -limf, limf)
        ok = np.asarray(reach(cand), dtype=bool)
        for k in (0, 1):
            if found[k]:
                continue
            if ok[k]:
                inside[k] = cand[k]
                if cand[k] <= -limf or cand[k] >= limf:
                    found[k] = True
                else:
                    walk[k] = cand[k]
                    step[k] *= 2.0
            else:
                outside[k] = cand[k]
                found[k] = True
    for k in (0, 1):
        if not found[k]:
            outside[k] = -limf if k == 0 else limf
    for _ in range(int(iters)):
        mid = 0.5 * (inside + outside)
        ok = np.asarray(reach(mid), dtype=bool)
        inside = np.where(ok, mid, inside)
        outside = np.where(ok, outside, mid)
    return float(inside[0]), float(inside[1])


def solve_ab_L_for_gray(target, a, b, iters=40):
    """固定 (a, b)，二分 Oklab L 使灰阶码值 == target（端点钳制）。

    与 hsv_picker._solve_ab_L_metric 同一算法，只把每次求值换成纯 Python 快路径；
    metric="oklab" 的路径不经过这里。
    """
    targetf = float(target)
    lo, hi = 0.0, 1.0
    f_lo = gray_from_oklab_py(lo, a, b)
    f_hi = gray_from_oklab_py(hi, a, b)
    if targetf <= f_lo:
        return lo
    if targetf >= f_hi:
        return hi
    for _ in range(int(iters)):
        mid = 0.5 * (lo + hi)
        if gray_from_oklab_py(mid, a, b) < targetf:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


# ---- 切片包围盒查表（由 tools/make_ab_box_table.py 生成）----
_AB_BOX_L = (
        0.00200, 0.00215, 0.00260, 0.00335, 0.00440, 0.00575, 0.00739, 0.00933,
        0.01157, 0.01410, 0.01692, 0.02004, 0.02344, 0.02713, 0.03111, 0.03537,
        0.03991, 0.04472, 0.04981, 0.05517, 0.06080, 0.06670, 0.07285, 0.07926,
        0.08593, 0.09284, 0.10000, 0.10740, 0.11504, 0.12291, 0.13101, 0.13932,
        0.14786, 0.15661, 0.16556, 0.17472, 0.18407, 0.19361, 0.20334, 0.21325,
        0.22333, 0.23357, 0.24398, 0.25454, 0.26524, 0.27609, 0.28708, 0.29819,
        0.30942, 0.32077, 0.33223, 0.34379, 0.35544, 0.36718, 0.37900, 0.39089,
        0.40285, 0.41486, 0.42693, 0.43904, 0.45119, 0.46336, 0.47556, 0.48778,
        0.50000, 0.51222, 0.52444, 0.53664, 0.54881, 0.56096, 0.57307, 0.58514,
        0.59715, 0.60911, 0.62100, 0.63282, 0.64456, 0.65621, 0.66777, 0.67923,
        0.69058, 0.70181, 0.71292, 0.72391, 0.73476, 0.74546, 0.75602, 0.76643,
        0.77667, 0.78675, 0.79666, 0.80639, 0.81593, 0.82528, 0.83444, 0.84339,
        0.85214, 0.86068, 0.86899, 0.87709, 0.88496, 0.89260, 0.90000, 0.90716,
        0.91407, 0.92074, 0.92715, 0.93330, 0.93920, 0.94483, 0.95019, 0.95528,
        0.96009, 0.96463, 0.96889, 0.97287, 0.97656, 0.97996, 0.98308, 0.98590,
        0.98843, 0.99067, 0.99261, 0.99425, 0.99560, 0.99665, 0.99740, 0.99785,
        0.99800,
    )
_AB_BOX_A_LO = (
        -0.06680, -0.06680, -0.06680, -0.07040, -0.07220, -0.07580, -0.07760, -0.07940,
        -0.07940, -0.07400, -0.07400, -0.07040, -0.05780, -0.03440, -0.03260, -0.02000,
        -0.01820, -0.01820, -0.01820, -0.01820, -0.02000, -0.02000, -0.02180, -0.02360,
        -0.02540, -0.02720, -0.02900, -0.03080, -0.03260, -0.03440, -0.03620, -0.03980,
        -0.04160, -0.04340, -0.04520, -0.04880, -0.05060, -0.05240, -0.05600, -0.05780,
        -0.06140, -0.06320, -0.06680, -0.07040, -0.07220, -0.07580, -0.07940, -0.08120,
        -0.08480, -0.08660, -0.09020, -0.09380, -0.09560, -0.09920, -0.10280, -0.10640,
        -0.11000, -0.11180, -0.11540, -0.11900, -0.12260, -0.12620, -0.12800, -0.13340,
        -0.13520, -0.13880, -0.14240, -0.14600, -0.14960, -0.15140, -0.15500, -0.15860,
        -0.16220, -0.16580, -0.16760, -0.17120, -0.17480, -0.17840, -0.18020, -0.18380,
        -0.18740, -0.18920, -0.19280, -0.19640, -0.19820, -0.20180, -0.20540, -0.20720,
        -0.21080, -0.21260, -0.21620, -0.21800, -0.21980, -0.22340, -0.22700, -0.22880,
        -0.23060, -0.23420, -0.23060, -0.21440, -0.20000, -0.18740, -0.17480, -0.16220,
        -0.15140, -0.14060, -0.13160, -0.12080, -0.11360, -0.10460, -0.09740, -0.09020,
        -0.08300, -0.07580, -0.06860, -0.05600, -0.04520, -0.03620, -0.02900, -0.02360,
        -0.01820, -0.01460, -0.01280, -0.00920, -0.00740, -0.00560, -0.00380, -0.00380,
        -0.00380,
    )
_AB_BOX_A_HI = (
        0.07580, 0.07580, 0.07400, 0.07220, 0.06860, 0.06500, 0.05960, 0.05420,
        0.04880, 0.04160, 0.03620, 0.03260, 0.02900, 0.02540, 0.02540, 0.02360,
        0.02360, 0.02540, 0.02540, 0.02720, 0.02900, 0.03080, 0.03260, 0.03620,
        0.03800, 0.03980, 0.04340, 0.04700, 0.04880, 0.05240, 0.05600, 0.05960,
        0.06320, 0.06680, 0.07040, 0.07400, 0.07760, 0.08120, 0.08480, 0.08840,
        0.09380, 0.09740, 0.10100, 0.10640, 0.11000, 0.11540, 0.11900, 0.12440,
        0.12800, 0.13340, 0.13700, 0.14240, 0.14780, 0.15140, 0.15680, 0.16220,
        0.16760, 0.17120, 0.17660, 0.18200, 0.18740, 0.19100, 0.19640, 0.20180,
        0.20720, 0.21260, 0.21620, 0.22160, 0.22700, 0.23240, 0.23600, 0.24140,
        0.24680, 0.25220, 0.25580, 0.26120, 0.26660, 0.27020, 0.27560, 0.27740,
        0.27740, 0.27560, 0.26120, 0.24860, 0.23780, 0.22520, 0.21440, 0.20360,
        0.19100, 0.18200, 0.17120, 0.16220, 0.15320, 0.14420, 0.13520, 0.12620,
        0.11900, 0.11180, 0.10460, 0.09740, 0.09020, 0.08300, 0.07760, 0.07220,
        0.06680, 0.06140, 0.05600, 0.05060, 0.04520, 0.04160, 0.03800, 0.03440,
        0.03080, 0.02720, 0.02360, 0.02000, 0.01820, 0.01460, 0.01280, 0.01100,
        0.00920, 0.00740, 0.00560, 0.00560, 0.00380, 0.00200, 0.00200, 0.00200,
        0.00200,
    )
_AB_BOX_B_LO = (
        -0.03800, -0.03620, -0.03620, -0.03620, -0.03440, -0.03440, -0.03440, -0.03260,
        -0.03260, -0.03260, -0.03260, -0.03260, -0.03260, -0.03260, -0.03260, -0.03440,
        -0.03440, -0.03620, -0.03980, -0.04160, -0.04520, -0.04880, -0.05240, -0.05600,
        -0.06140, -0.06680, -0.07040, -0.07580, -0.08120, -0.08660, -0.09200, -0.09740,
        -0.10280, -0.11000, -0.11540, -0.12260, -0.12800, -0.13340, -0.14060, -0.14780,
        -0.15500, -0.16220, -0.16940, -0.17660, -0.18380, -0.19100, -0.19820, -0.20540,
        -0.21440, -0.22160, -0.23060, -0.23780, -0.24680, -0.25400, -0.26300, -0.27020,
        -0.27920, -0.28640, -0.29540, -0.30260, -0.31160, -0.30620, -0.30080, -0.29360,
        -0.28640, -0.27920, -0.27200, -0.26480, -0.25760, -0.25040, -0.24500, -0.23780,
        -0.23060, -0.22340, -0.21620, -0.20900, -0.20360, -0.19640, -0.18920, -0.18380,
        -0.17660, -0.16940, -0.16220, -0.15500, -0.14960, -0.14240, -0.13520, -0.12980,
        -0.12260, -0.11720, -0.11000, -0.10460, -0.09920, -0.09380, -0.08840, -0.08300,
        -0.07940, -0.07400, -0.06860, -0.06500, -0.05960, -0.05600, -0.05240, -0.04880,
        -0.04520, -0.04160, -0.03800, -0.03440, -0.03080, -0.02900, -0.02540, -0.02360,
        -0.02180, -0.01820, -0.01640, -0.01460, -0.01280, -0.01100, -0.00920, -0.00740,
        -0.00740, -0.00560, -0.00380, -0.00380, -0.00380, -0.00200, -0.00200, -0.00200,
        -0.00200,
    )
_AB_BOX_B_HI = (
        0.02720, 0.02720, 0.02720, 0.02900, 0.02900, 0.03080, 0.03260, 0.03260,
        0.03440, 0.03620, 0.03620, 0.03800, 0.03980, 0.03980, 0.03980, 0.03980,
        0.01820, 0.01640, 0.01640, 0.01640, 0.01640, 0.01640, 0.01820, 0.01820,
        0.02000, 0.02180, 0.02180, 0.02360, 0.02540, 0.02720, 0.02900, 0.03080,
        0.03260, 0.03440, 0.03620, 0.03800, 0.03980, 0.04160, 0.04340, 0.04520,
        0.04700, 0.04880, 0.05240, 0.05420, 0.05600, 0.05780, 0.06140, 0.06320,
        0.06500, 0.06680, 0.07040, 0.07220, 0.07400, 0.07760, 0.07940, 0.08300,
        0.08480, 0.08660, 0.09020, 0.09200, 0.09380, 0.09740, 0.09920, 0.10280,
        0.10460, 0.10640, 0.11000, 0.11180, 0.11540, 0.11720, 0.11900, 0.12260,
        0.12440, 0.12800, 0.12980, 0.13160, 0.13520, 0.13700, 0.13880, 0.14240,
        0.14420, 0.14600, 0.14960, 0.15140, 0.15320, 0.15500, 0.15860, 0.16040,
        0.16220, 0.16400, 0.16580, 0.16760, 0.16940, 0.17120, 0.17480, 0.17660,
        0.17840, 0.18020, 0.18020, 0.18200, 0.18380, 0.18560, 0.18740, 0.18740,
        0.18920, 0.19100, 0.19280, 0.19280, 0.19460, 0.19460, 0.19640, 0.19640,
        0.19820, 0.19820, 0.18920, 0.15680, 0.12980, 0.10460, 0.08480, 0.07040,
        0.05420, 0.04340, 0.03620, 0.02540, 0.02000, 0.01460, 0.00920, 0.00740,
        0.00740,
    )
# ---- 切片包围盒查表结束 ----

# 转成 numpy 数组一次（np.interp 每次从 tuple 转换要 0.03ms，转完 0.003ms）
_AB_BOX_L_ARR = np.asarray(_AB_BOX_L, dtype=np.float64)
_AB_BOX_A_LO_ARR = np.asarray(_AB_BOX_A_LO, dtype=np.float64)
_AB_BOX_A_HI_ARR = np.asarray(_AB_BOX_A_HI, dtype=np.float64)
_AB_BOX_B_LO_ARR = np.asarray(_AB_BOX_B_LO, dtype=np.float64)
_AB_BOX_B_HI_ARR = np.asarray(_AB_BOX_B_HI, dtype=np.float64)


def ab_slice_box(L):
    """固定 L 时 sRGB 色域切片在 a / b 轴上的**投影包围盒**（查表 + 线性插值）。

    为什么要内嵌表：二维栅格扫 7.99ms/次，而拖动时明度每帧都在变（每次都会缓存失效），
    直接把整帧预算吃光；内嵌表零冷启动、0.003ms/次。表与色相无关，只随 L 变。
    精度：a/b 栅格步长 0.0018 + 明度方向插值，实测与直接栅格扫偏差 ≤0.003。
    """
    if not _AB_BOX_L:
        return 0.0, 0.0, 0.0, 0.0
    L = float(L)
    if L <= float(_AB_BOX_L[0]) or L >= float(_AB_BOX_L[-1]):
        return 0.0, 0.0, 0.0, 0.0
    return (float(np.interp(L, _AB_BOX_L_ARR, _AB_BOX_A_LO_ARR)),
            float(np.interp(L, _AB_BOX_L_ARR, _AB_BOX_A_HI_ARR)),
            float(np.interp(L, _AB_BOX_L_ARR, _AB_BOX_B_LO_ARR)),
            float(np.interp(L, _AB_BOX_L_ARR, _AB_BOX_B_HI_ARR)))


def ab_strip_range(L, a, b, axis="a", mode="box"):
    """a/b 条的横向量程 (lo, hi)。

    mode="box"  : 当前明度的切片包围盒 —— 刻度只随 L 变（拖动时两把刻度都不抖），
                  但另一分量越界的那一段会「拖了不变色」（画成灰色斜纹）；
    mode="line" : 固定另一分量后的可行区间 —— 满量程永远可达，代价是刻度会随另一分量变。

    box 口径额外做一步**并集兜底**：量程至少覆盖「精确算出的可达区间」。
    因为查表在明度方向的跳变处会有 ~0.01 的误差，兜底后能保证可达点永远不会被切在条外。
    """
    other = b if axis == "a" else a
    live = ab_axis_interval(L, other, axis)
    if mode == "box":
        a_lo, a_hi, b_lo, b_hi = ab_slice_box(L)
        box = (a_lo, a_hi) if axis == "a" else (b_lo, b_hi)
        out = (min(box[0], live[0]), max(box[1], live[1]))
    else:
        out = live
    if out[1] - out[0] < 1e-6:                 # 退化（近黑/白）：给个最小宽度，别让拖动除零
        c = 0.5 * (out[0] + out[1])
        return c - 5e-4, c + 5e-4
    return out


def _solve_v(h, s_fixed, target, metric, iters=40):
    """固定 S、固定色相，二分求让视觉明度 = target 的 V；够不到返回 None。

    固定 S 时明度随 V 严格单调上升，所以解唯一。
    """
    if float(lightness(h, s_fixed, 1.0, metric)) < target:
        return None
    lo, hi = 0.0, 1.0
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if float(lightness(h, s_fixed, mid, metric)) < target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _srgb_encode(Y):
    Y = np.clip(np.asarray(Y, dtype=np.float64), 0.0, 1.0)
    return np.where(Y <= 0.0031308, 12.92 * Y, 1.055 * np.power(Y, 1.0 / 2.4) - 0.055)




def _v_from_gray_oklab(L):
    """灰度端（Oklab）：L ≈ cbrt(Y) → Y = L^3 → V。"""
    return float(_srgb_encode(clamp(float(L), 0.0, 1.0) ** 3))


def _v_from_sat(h, target, metric):
    """纯色端 S=1：Y = Y_hue * lin(V)，反解 V；够不到返回 None。"""
    y1 = float(_lab_l_from_Y(1.0)) if False else None
    Y_full = float(srgb_to_linear(hsv_to_srgb(float(h), 1.0, 1.0)).dot(
        np.array([0.2126729, 0.7151522, 0.0721750])))
    if metric == "lab":
        f = (clamp(float(target), 0.0, 100.0) + 16.0) / 116.0
        Y_t = f ** 3 if f > 6.0 / 29.0 else (f - 4.0 / 29.0) * 3.0 * (6.0 / 29.0) ** 2
    else:
        Y_t = clamp(float(target), 0.0, 1.0) ** 3
    if Y_full <= 1e-12 or Y_t > Y_full:
        return None
    return float(_srgb_encode(Y_t / Y_full))


_LBAR_YMIN = 1e-3            # 对数明度尺的底端亮度（3 个数量级：1 -> 1e-3）


_LBAR_LMAX = {"lab": 100.0, "oklab": 1.0, "gray": 1.0}   # 各指标的明度上限


def _lbar_Y_from_L(L, metric="lab"):
    """指标明度 L -> 等效灰阶相对亮度 Y。

    oklab：L∈0~1，Y = L³（与 _v_gray 的灰阶口径一致）；
    gray ：L∈0~1 是 srgb_encode(Y)，反解 Y = srgb_to_linear(L)；
    lab  ：L*∈0~100，沿用现有 CIE Lab 分段函数。
    """
    L = np.asarray(L, dtype=np.float64)
    if metric == "gray":
        return srgb_to_linear(np.clip(L, 0.0, 1.0))
    if metric == "oklab":
        return np.clip(L, 0.0, 1.0) ** 3
    f = (np.clip(L, 0.0, 100.0) + 16.0) / 116.0
    return np.where(f > 6.0 / 29.0, f ** 3,
                    (f - 4.0 / 29.0) * 3.0 * (6.0 / 29.0) ** 2)


def _lbar_L_from_Y(Y, metric="lab"):
    """等效灰阶相对亮度 Y -> 指标明度 L（_lbar_Y_from_L 的逆）。"""
    Y = np.clip(np.asarray(Y, dtype=np.float64), 0.0, 1.0)
    if metric == "gray":
        return np.clip(_srgb_encode(Y), 0.0, 1.0)
    if metric == "oklab":
        return np.cbrt(Y)
    return _lab_l_from_Y(Y)


def _lbar_Y(f, log_mode, metric="lab"):
    """明度尺位置 f（0=顶 1=底）-> 等效灰阶相对亮度 Y。

    线性档：位置等分指标明度（oklab/gray L∈0~1 → 走 _lbar_Y_from_L；lab L*∈0~100 → CIE 分段函数）；
    对数档：位置等分 log10(Y)。metric='lab' 时与旧实现逐位一致。
    """
    f = np.asarray(f, dtype=np.float64)
    if log_mode:
        return 10.0 ** (math.log10(_LBAR_YMIN) * f)
    if metric in ("oklab", "gray"):
        return _lbar_Y_from_L(1.0 - f, metric)
    L = np.clip(100.0 * (1.0 - f), 0.0, 100.0)
    f_ = (L + 16.0) / 116.0
    return np.where(f_ > 6.0 / 29.0, f_ ** 3,
                    (f_ - 4.0 / 29.0) * 3.0 * (6.0 / 29.0) ** 2)


def _lbar_f(Y, log_mode, metric="lab"):
    """相对亮度 Y -> 明度尺位置（_lbar_Y 的逆；口径随 metric）。"""
    Y = np.clip(np.asarray(Y, dtype=np.float64), 1e-9, 1.0)
    if log_mode:
        return np.clip(np.log10(Y) / math.log10(_LBAR_YMIN), 0.0, 1.0)
    if metric == "gray":
        return np.clip(1.0 - _srgb_encode(Y), 0.0, 1.0)
    if metric == "oklab":
        return np.clip(1.0 - np.cbrt(Y), 0.0, 1.0)
    return np.clip(1.0 - _lab_l_from_Y(Y) / 100.0, 0.0, 1.0)


def _lbar_f_from_L(L, log_mode, metric="lab"):
    """指标明度 L -> 尺位置 f（0=顶 1=底）。

    线性档：f = 1 - L/Lmax（与 _lbar_L_from_f 严格互逆）；
    对数分布档：L 先转等效灰 Y，再按 log10 映射。
    metric='lab' 的对数档复用旧实现完全相同的运算次序；线性档旧代码多绕了一步
    Lab→Y→L* 的往返，在纯黑处会因 Y 下限 1e-9 把游标留在离底 9e-9 处，这里修正为
    严格的反函数（差值 9e-9 个位置 ≈ 3e-6 px，肉眼与像素均不可见）。
    """
    if metric in ("oklab", "gray"):
        L = np.asarray(L, dtype=np.float64)
        if log_mode:
            return _lbar_f(_lbar_Y_from_L(L, metric), True, metric)
        return np.clip(1.0 - np.clip(L, 0.0, 1.0), 0.0, 1.0)
    L = np.asarray(L, dtype=np.float64)
    if not log_mode:
        return np.clip(1.0 - np.clip(L, 0.0, 100.0) / 100.0, 0.0, 1.0)
    f_lin = 1.0 - np.clip(L, 0.0, 100.0) / 100.0
    return _lbar_f(_lbar_Y(f_lin, False, "lab"), True, "lab")


def _lbar_L_from_f(f, log_mode, metric="lab"):
    """尺位置 f -> 指标明度 L（_lbar_f_from_L 的逆）。

    线性档：L = Lmax*(1-f)；对数分布档：Y = 10^(log10(YMIN)*f)，再转回指标 L。
    """
    f = float(np.clip(float(f), 0.0, 1.0))
    if log_mode:
        Y = 10.0 ** (math.log10(_LBAR_YMIN) * f)
        return float(_lbar_L_from_Y(Y, metric))
    return _LBAR_LMAX.get(metric, 100.0) * (1.0 - f)


def lbar_tick_text(L, metric, log_mode):
    """明度尺刻度标签：lab 保持 %g / %.0f 风格，oklab 固定 0~1 两位小数。"""
    L = float(L)
    if metric == "lab":
        return ("%.0f" % L) if log_mode else ("%g" % L)
    return "%.2f" % clamp(L, 0.0, 1.0)


def lbar_readout_text(L, metric):
    """明度尺条底读数：lab 保持 L*%.0f，oklab 固定 0~1 两位小数。"""
    L = float(L)
    if metric == "lab":
        return "L*%.0f" % clamp(L, 0.0, 100.0)
    return "%.2f" % clamp(L, 0.0, 1.0)


def lbar_status_text(L, metric):
    """状态栏里的明度写法（比刻度多给一位精度）。"""
    L = float(L)
    if metric == "lab":
        return "L* = %.1f" % clamp(L, 0.0, 100.0)
    return "%.2f" % clamp(L, 0.0, 1.0)


def _v_gray(metric, Ls):
    """灰阶端：明度 L -> V（向量化；与 lightness() 的口径严格互逆）。"""
    Ls = np.asarray(Ls, dtype=np.float64)
    if metric == "gray":
        return np.clip(Ls, 0.0, 1.0)          # 灰阶码值本身就是中性色的 V
    if metric == "oklab":
        return _srgb_encode(np.clip(Ls, 0.0, 1.0) ** 3)
    f = (np.clip(Ls, 0.0, 100.0) + 16.0) / 116.0
    Y = np.where(f > 6.0 / 29.0, f ** 3, (f - 4.0 / 29.0) * 3.0 * (6.0 / 29.0) ** 2)
    return _srgb_encode(Y)


def _iso_curve_parts(h, targets, metric, n_v, iters, Lp, top):
    """多条等明度曲线一起二分（同色相）：返回 (S 矩阵, V 矩阵, ok 掩码, v_left, v_top)。"""
    targets = np.asarray(targets, dtype=np.float64)
    ok = (targets > 1e-9) & (targets < top - 1e-12)
    if not ok.any():
        return None, None, ok, None, None
    v_left = _v_gray(metric, targets)                     # 左端点（灰轴 S=0）可解析
    reach = targets <= Lp - 1e-12
    v_right = _solve_v_vec(h, 1.0, targets, metric, iters=30)   # 右端点（纯色相 S=1）
    v_top = np.where(reach, v_right, 1.0)
    u = np.linspace(0.0, 1.0, n_v)
    V = v_left[:, None] + (v_top - v_left)[:, None] * u[None, :]
    lo = np.zeros_like(V)
    hi = np.ones_like(V)
    tt = targets[:, None]
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        darker = lightness(h, mid, V, metric) < tt            # 太暗 -> 需要更小的 S
        hi = np.where(darker, mid, hi)
        lo = np.where(darker, lo, mid)
    return 0.5 * (lo + hi), V, ok, v_left, np.where(reach, v_top, np.nan)


def _iso_curve_finish(ss, vv):
    """按 V 升序排序 + 去掉重复 V 的点。"""
    order = np.argsort(vv, kind="stable")
    ss, vv = ss[order], vv[order]
    keep = np.ones(len(vv), dtype=bool)
    keep[1:] = np.abs(np.diff(vv)) > 1e-9
    return ss[keep], vv[keep]


def iso_lightness_curves(h, targets, metric="lab", n_v=129, iters=34):
    """一次求**多条**等明度曲线（同色相、不同目标明度）。返回 [(L, ss, vv), ...]。

    等明度簇一次要 9 条，逐条算会花掉 20ms+；批成一个矩阵二分后 numpy 调度开销被摊薄。
    """
    targets = np.asarray(targets, dtype=np.float64)
    if len(targets) == 0:
        return []
    top = float(lightness(h, 0.0, 1.0, metric))          # 白点明度（100 / 1.0）
    Lp = float(lightness(h, 1.0, 1.0, metric))           # 纯色端明度
    S, V, ok, v_left, v_top = _iso_curve_parts(h, targets, metric, n_v, iters, Lp, top)
    if S is None:
        return []
    out = []
    for i, t in enumerate(targets):
        if not ok[i]:
            continue
        ss = np.concatenate([[0.0], S[i]])
        vv = np.concatenate([[v_left[i]], V[i]])
        if np.isfinite(v_top[i]):                        # 精确右端点：S=1
            ss = np.concatenate([ss, [1.0]])
            vv = np.concatenate([vv, [v_top[i]]])
        ss, vv = _iso_curve_finish(ss, vv)
        if len(ss) >= 2:
            out.append((float(t), ss, vv))
    return out


def _solve_v_vec(h, s_fixed, targets, metric, iters=40):
    """向量化 _solve_v：固定 S、对一批 target 求 V（够不到的会退化成 V=1）。"""
    targets = np.asarray(targets, dtype=np.float64)
    lo = np.zeros_like(targets)
    hi = np.ones_like(targets)
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        low = lightness(h, s_fixed, mid, metric) < targets
        lo = np.where(low, mid, lo)
        hi = np.where(low, hi, mid)
    return 0.5 * (lo + hi)


def iso_lightness_curve(h, target, metric="lab", n_v=257, iters=34):
    """求「固定色相 h + 固定视觉明度 target」在 HSV 方块内的全部 (S,V)。

    做法：沿 V 均匀采样，对每个 V 用二分法求满足明度的 S。
      固定 V 时明度随 S 严格单调下降（加饱和变暗）；
      固定 S 时明度随 V 严格单调上升（整体提亮）。
    所以解唯一、曲线单调：S 随 V 一起变大，整体从左边缘走向右上。
    首尾再补两个精确端点（左边缘 S=0 / 右边缘 S=1），让曲线真正贴到边界。
    返回按 V 升序的 (S 数组, V 数组)；无解时返回空数组。
    """
    top = float(lightness(h, 0.0, 1.0, metric))          # 白点明度（100 / 1.0）
    if target <= 1e-9:
        return np.array([0.0]), np.array([0.0])          # 纯黑
    if target >= top - 1e-12:
        return np.array([0.0]), np.array([1.0])          # 纯白
    got = iso_lightness_curves(h, [float(target)], metric, n_v=n_v, iters=iters)
    if not got:
        return np.array([]), np.array([])
    _t, ss, vv = got[0]
    return ss, vv


def curve_arclen(ss, vv):
    """归一化累积弧长 t ∈ [0,1]，用来“沿曲线滑动”时保持相对位置。"""
    n = len(ss)
    if n < 2:
        return np.zeros(n)
    d = np.hypot(np.diff(ss), np.diff(vv))
    cum = np.concatenate([[0.0], np.cumsum(d)])
    total = float(cum[-1])
    return cum / total if total > 1e-12 else np.linspace(0.0, 1.0, n)


def point_at_t(ss, vv, tt, t):
    """取曲线上弧长比例 = t 的点。"""
    if len(ss) == 0:
        return 0.0, 0.0
    if len(ss) == 1:
        return float(ss[0]), float(vv[0])
    t = clamp(float(t), 0.0, 1.0)
    return float(np.interp(t, tt, ss)), float(np.interp(t, tt, vv))


def nearest_t(ss, vv, tt, s, v):
    """点 (s,v) 在折线 (ss,vv) 上最近点的弧长比例 t ∈ [0,1]。"""
    n = len(ss)
    if n < 2:
        return 0.0
    ax, ay = ss[:-1], vv[:-1]
    dx, dy = ss[1:] - ax, vv[1:] - ay
    l2 = dx * dx + dy * dy
    l2 = np.where(l2 < 1e-18, 1e-18, l2)
    u = np.clip(((s - ax) * dx + (v - ay) * dy) / l2, 0.0, 1.0)
    px, py = ax + u * dx, ay + u * dy
    i = int(np.argmin((px - s) ** 2 + (py - v) ** 2))
    return float(tt[i] + u[i] * (tt[i + 1] - tt[i]))


def _grad_grid(h, metric, n=65):
    """在 (S,V) 网格上算 L 及其梯度（供正交族积分用）。"""
    ax = np.linspace(0.0, 1.0, n)
    sg, vg = np.meshgrid(ax, ax)                 # sg[i,j]=S(j)、vg[i,j]=V(i)
    lg = lightness(h, sg, vg, metric)
    dldv, dlds = np.gradient(lg, ax, ax)
    return dlds, dldv, n


def _field_fn(dlds, dldv, n):
    """双线性插值 + 单位化的梯度场（∇L 方向）。"""
    def sample(f, s, v):
        x = np.clip(s, 0.0, 1.0) * (n - 1)
        y = np.clip(v, 0.0, 1.0) * (n - 1)
        x0 = np.floor(x).astype(int)
        y0 = np.floor(y).astype(int)
        x1 = np.minimum(x0 + 1, n - 1)
        y1 = np.minimum(y0 + 1, n - 1)
        fx, fy = x - x0, y - y0
        return (f[y0, x0] * (1 - fx) * (1 - fy) + f[y0, x1] * fx * (1 - fy)
                + f[y1, x0] * (1 - fx) * fy + f[y1, x1] * fx * fy)

    def field(q):
        fs = sample(dlds, q[:, 0], q[:, 1])
        fv = sample(dldv, q[:, 0], q[:, 1])
        m = np.hypot(fs, fv)
        m = np.where(m < 1e-9, 1e-9, m)
        return np.stack([fs / m, fv / m], axis=1)

    return field


def _integrate(field, start, n_steps, step, sign=1.0, seed_pts=None):
    """从 start 沿 ±∇L 用 RK4 积分，出方块即停；返回点列。"""
    st = np.array([start], dtype=np.float64)
    alive = np.ones(1, dtype=bool)
    pts = [tuple(st[0])]
    for _ in range(n_steps):
        if not alive.any():
            break
        k1 = field(st) * sign
        k2 = field(st + 0.5 * step * k1) * sign
        k3 = field(st + 0.5 * step * k2) * sign
        k4 = field(st + step * k3) * sign
        nxt = st + step * (k1 + 2.0 * k2 + 2.0 * k3 + k4) / 6.0
        out = ((nxt[:, 0] < 0) | (nxt[:, 0] > 1) | (nxt[:, 1] < 0) | (nxt[:, 1] > 1))
        nxt[:, 0] = np.clip(nxt[:, 0], 0.0, 1.0)
        nxt[:, 1] = np.clip(nxt[:, 1], 0.0, 1.0)
        st = nxt
        pts.append((float(st[0, 0]), float(st[0, 1])))
        alive &= ~out
    return pts








def refine_on_curve(h, target, metric, v, iters=26):
    """固定 V 二分求使 L = target 的 S —— 让滑动得到的色点**精确**落在等明度曲线上。

    折线插值出来的点会差 ~1e-4 明度，肉眼看不见，但复制出去的 L 值就不是锁定值了，
    所以这里再精修一下（26 次二分 ≈ 1ms）。
    """
    lo, hi = 0.0, 1.0                       # 固定 V 时 L 随 S 单调下降
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        if float(lightness(h, mid, v, metric)) > target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi), v


def _sort_by(arr_key, *arrays):
    """按 arr_key 升序重排，方便 np.interp 使用（正交线的 S 是递减的）。"""
    idx = np.argsort(np.asarray(arr_key, dtype=np.float64))
    return [np.asarray(a, dtype=np.float64)[idx] for a in arrays]


def curve_at_f(cs, cv, strip_mode, f):
    """色条位置 f(0=顶 1=底) -> 曲线上对应的点；越出曲线范围自动夹到端点。

    等明度线与正交线都适用：前者 S 随 V 递增，后者 S 随 V 递减，所以按方向重排后再插值。
    """
    cs = np.asarray(cs, dtype=np.float64)
    cv = np.asarray(cv, dtype=np.float64)
    if len(cs) < 1:
        return None
    cvs, css = _sort_by(cv, cv, cs)                 # 按 V 升序
    if strip_mode == "v":
        vv = 1.0 - f
        return float(np.interp(vv, cvs, css)), vv
    if strip_mode == "s":
        ss = 1.0 - f
        css2, cvs2 = _sort_by(cs, cs, cv)           # 按 S 升序
        return ss, float(np.interp(ss, css2, cvs2))
    tt = curve_arclen(cvs, css)
    # 注意：point_at_t(ss, vv, ...) 的返回值是 (ss, vv)；这里传进去的是 (V,S) 排好序的曲线，
    # 所以必须先接成 (V,S) 再翻回 (S,V) 返回 —— 以前直接 return，把 V 当成 S 用了（拖动被夹到端点）
    v_arc, s_arc = point_at_t(cvs, css, tt, 1.0 - f)
    return s_arc, v_arc


def strip_image(h, cs, cv, strip_mode, bw, bh):
    """把一条曲线上的颜色排成竖色条（返回 bh×bw 的 RGB 数组，上=色条顶部）。

    strip_mode:
      "v"   —— 竖直位置就是 V，与方块 V 轴完全对齐；曲线 V 范围外留空
      "s"   —— 竖直位置就是 S
      "arc" —— 按曲线弧长等分，铺满整条
    """
    img = np.empty((bh, bw, 3), dtype=np.uint8)
    img[:] = (38, 38, 42)
    cs = np.asarray(cs, dtype=np.float64)
    cv = np.asarray(cv, dtype=np.float64)
    if len(cs) < 1:
        return img
    f = 1.0 - (np.arange(bh) + 0.5) / bh            # 每行位置：0=顶 1=底
    if strip_mode == "v":
        cvs, css = _sort_by(cv, cv, cs)
        ss, vv = np.interp(f, cvs, css), f
        inside = (f >= cvs[0] - 1e-9) & (f <= cvs[-1] + 1e-9)
    elif strip_mode == "s":
        css2, cvs2 = _sort_by(cs, cs, cv)
        ss, vv = f, np.interp(f, css2, cvs2)
        inside = (f >= css2[0] - 1e-9) & (f <= css2[-1] + 1e-9)
    else:
        cvs, css = _sort_by(cv, cv, cs)
        tt = curve_arclen(cvs, css)
        ss, vv = np.interp(f, tt, css), np.interp(f, tt, cvs)
        inside = np.ones(bh, dtype=bool)
    cols = hsv_to_srgb(float(h), ss[inside], vv[inside])
    img[inside] = np.clip(cols * 255.0 + 0.5, 0, 255).astype(np.uint8)[:, None, :]
    return img


def iso_cluster(h, metric, step_pct=10.0):
    """等明度曲线簇：返回 [(L, ss, vv), ...]，默认 L* = 10,20,...,90。

    step_pct 用「百分比」表示，两种指标通用（Oklab L 的 10% = 0.1）。
    """
    top = 100.0 if metric == "lab" else 1.0
    step = step_pct / 100.0 * top
    if step <= 0:
        return []
    targets = []
    k = 1
    while k * step < top - 1e-9:
        targets.append(k * step)
        k += 1
    return iso_lightness_curves(h, targets, metric, n_v=129)




def thin_labels(pos, min_gap):
    """pos 已升序：贪心挑出互相不挤的标签下标（保证刻度线仍在，只是不写数字）。"""
    keep, last = [], -1e18
    for i, p in enumerate(pos):
        if p - last >= min_gap:
            keep.append(i)
            last = p
    return keep


_XN, _YN, _ZN = 0.95047, 1.0, 1.08883


def _f_lab(t):
    t = np.asarray(t, dtype=np.float64)
    return np.where(t > _EPS_Y, np.cbrt(t), (_KAPPA_Y * t + 16.0) / 116.0)


def lab_L_C(h, s, v):
    """CIELAB (D65) 的 (L*, C*ab)，支持标量/数组。"""
    lin = srgb_to_linear(hsv_to_srgb(h, s, v))
    R, G, B = lin[..., 0], lin[..., 1], lin[..., 2]
    X = 0.4124564 * R + 0.3575761 * G + 0.1804375 * B
    Y = 0.2126729 * R + 0.7151522 * G + 0.0721750 * B
    Z = 0.0193339 * R + 0.1191920 * G + 0.9503041 * B
    fx, fy, fz = _f_lab(X / _XN), _f_lab(Y / _YN), _f_lab(Z / _ZN)
    a_, b_ = 500.0 * (fx - fy), 200.0 * (fy - fz)
    return 116.0 * fy - 16.0, np.hypot(a_, b_)


def curve_crel(h, cs, cv, metric="lab"):
    """等明度曲线上各点的相对彩度（0=灰端 1=最饱和端）、最大绝对彩度、各点绝对彩度 C。

    C_max 走 cmax_of_L()，与 crel_of_xyz()/crel_field() **同一口径**（否则拖明度尺会漂）。
    """
    cs = np.asarray(cs, dtype=np.float64)
    cv = np.asarray(cv, dtype=np.float64)
    if len(cs) == 0:
        return np.zeros(0), 0.0, np.zeros(0)
    _, C = ok_L_C(h, cs, cv)
    Lc = float(np.median(lightness(h, cs, cv, metric)))    # 曲线上明度恒定，取中位数抗噪
    cmax = float(cmax_of_L(h, metric, Lc))
    if cmax <= 1e-9:
        return np.zeros_like(C), 0.0, C
    return C / cmax, cmax, C


def _poly_at(cs, cv, x):
    """折线上「索引 = x」处的 (S,V)（线性插值）。"""
    lo = int(np.floor(clamp(float(x), 0.0, len(cs) - 1.0)))
    hi = min(lo + 1, len(cs) - 1)
    f = clamp(float(x) - lo, 0.0, 1.0)
    return (float(cs[lo] * (1 - f) + cs[hi] * f),
            float(cv[lo] * (1 - f) + cv[hi] * f))


def _crel_at(h, metric, s, v):
    """(s,v) 的相对彩度（与 crel_of_xyz 同口径，标量）。"""
    cm = float(cmax_of_L(h, metric, float(lightness(h, s, v, metric))))
    if cm <= 1e-9:
        return 0.0
    return float(ok_L_C(h, s, v)[1]) / cm


def point_at_crel(h, cs, cv, crel, metric="lab"):
    """取等明度曲线上「相对彩度 = crel」的点（0=灰，1=该明度下最饱和）。

    折线插值之后再做 12 次二分精修，**并保留更准的那个**：C/C_max 沿折线不是线性的，
    小 C_rel 处光靠插值会偏 0.3~1%，拖明度尺时会一步步累积成漂移（用户报的
    "S 小时明度 0~100 线不准"）。
    """
    cs = np.asarray(cs, dtype=np.float64)
    cv = np.asarray(cv, dtype=np.float64)
    if len(cs) < 2:
        return (float(cs[0]), float(cv[0])) if len(cs) else (0.0, 0.0)
    rel, cmax, C = curve_crel(h, cs, cv, metric)
    if cmax <= 1e-9:
        return float(cs[-1]), float(cv[-1])
    target = clamp(float(crel), 0.0, 1.0)
    i = float(np.interp(target, rel, np.arange(len(cs), dtype=float)))
    s0, v0 = _poly_at(cs, cv, i)
    e0 = abs(_crel_at(h, metric, s0, v0) - target)
    if e0 > 1e-7:                             # 值得精修才精修（绝大多数点一次就过）
        a = float(max(0, int(np.floor(i))))
        b = float(min(len(cs) - 1, int(np.floor(i)) + 1))
        for _ in range(12):                   # C_rel 沿曲线单调增 -> 二分
            mid = 0.5 * (a + b)
            s_m, v_m = _poly_at(cs, cv, mid)
            if _crel_at(h, metric, s_m, v_m) < target:
                a = mid
            else:
                b = mid
        s1, v1 = _poly_at(cs, cv, 0.5 * (a + b))
        if abs(_crel_at(h, metric, s1, v1) - target) < e0:
            return s1, v1
    return s0, v0


def crel_of_point(h, cs, cv, s, v, metric="lab"):
    """点 (s,v) 在等明度曲线上对应的相对彩度。"""
    cs = np.asarray(cs, dtype=np.float64)
    cv = np.asarray(cv, dtype=np.float64)
    if len(cs) < 2:
        return 0.0
    rel, cmax, C = curve_crel(h, cs, cv, metric)
    if cmax <= 1e-9:
        return 0.0
    tt = curve_arclen(cs, cv)
    t = nearest_t(cs, cv, tt, s, v)
    return float(np.interp(t, tt, rel))




_CMAX_EDGE = {}
_CMAX_N = 385               # 边界曲线采样点数（按边参数插值，误差 ≤0.1%）
_CMAX_ITERS = 44            # cmax_exact 的二分次数（≈1e-13 精度）


def cmax_exact(h, metric, L):
    """精确 C_max(色相, 明度)：同明度下最饱和的颜色必在方块边界上。

    L ≤ L*(S=1,V=1)  -> 在 **S=1 边**上二分 V（固定 S 时明度随 V 单调增）；
    否则              -> 在 **V=1 边**上二分 S（固定 V 时明度随 S 单调减）。
    支持标量/数组；metric='lab' 时 L∈[0,100]、'oklab' 时 L∈[0,1]。
    注意：这是**参考实现**（慢，1681 点约 18ms），运行时请用 cmax_of_L()。
    """
    L = np.asarray(L, dtype=np.float64)
    Lp = float(lightness(h, 1.0, 1.0, metric))          # 纯色端（S=1,V=1）的明度
    sat = L <= Lp
    lo = np.zeros_like(L)
    hi = np.ones_like(L)
    for _ in range(_CMAX_ITERS):                        # 分支 A：S=1 边上解 V
        mid = 0.5 * (lo + hi)
        dark = lightness(h, 1.0, mid, metric) < L
        lo = np.where(sat & dark, mid, lo)
        hi = np.where(sat & ~dark, mid, hi)
    v_a = 0.5 * (lo + hi)
    lo = np.zeros_like(L)
    hi = np.ones_like(L)
    for _ in range(_CMAX_ITERS):                        # 分支 B：V=1 边上解 S
        mid = 0.5 * (lo + hi)
        bright = lightness(h, mid, 1.0, metric) > L
        lo = np.where(~sat & bright, mid, lo)
        hi = np.where(~sat & ~bright, mid, hi)
    s_b = 0.5 * (lo + hi)
    cm = np.where(sat, ok_L_C(h, 1.0, v_a)[1], ok_L_C(h, s_b, 1.0)[1])
    return np.where(L > 0.0, cm, 0.0)


def _cmax_edge_table(h, metric, n=_CMAX_N):
    """C_max(明度) 的两条边界曲线（按**边参数**采样，逐色相精确，缓存）。

    为什么按参数(t=V/S)而不是按 L 插值：C_max 在纯色端对 L 是**尖点**（L=97 处 0.2 个
    L 单位内掉 13 个彩度单位），按 L 线性插值会把尖点抹掉；而 S=1 / V=1 两条边上的
    (L(t), C(t)) 都是 t 的光滑单调函数，先反解 t 再取 C 就没有这个问题。
    """
    key = (round(float(h) % 360.0, 3), metric, n)
    tab = _CMAX_EDGE.get(key)
    if tab is None:
        t = 0.5 - 0.5 * np.cos(np.pi * np.arange(n) / (n - 1.0))   # 两端更密
        La = np.maximum.accumulate(lightness(h, 1.0, t, metric))   # S=1 边：L 随 V 单调增
        Ca = ok_L_C(h, 1.0, t)[1]
        Lb = np.minimum.accumulate(lightness(h, t, 1.0, metric))   # V=1 边：L 随 S 单调减
        Cb = ok_L_C(h, t, 1.0)[1]
        tab = (t, La, Ca, Lb, Cb)
        if len(_CMAX_EDGE) > 96:
            _CMAX_EDGE.clear()
        _CMAX_EDGE[key] = tab
    return tab


def cmax_of_L(h, metric, L):
    """C_max(色相, 明度) —— 数值框 / 等彩度场 / 拖明度尺**共用同一口径**（向量化）。"""
    t, La, Ca, Lb, Cb = _cmax_edge_table(h, metric)
    L = np.asarray(L, dtype=np.float64)
    c_a = np.interp(np.interp(L, La, t), t, Ca)                 # 分支 A：S=1 边
    c_b = np.interp(np.interp(L, Lb[::-1], t[::-1]), t, Cb)     # 分支 B：V=1 边
    out = np.where(L <= float(La[-1]), c_a, c_b)
    return np.where(L > 0.0, out, 0.0)


def crel_of_xyz(h, metric, s, v):
    """(s,v) 的相对彩度与绝对彩度 C —— 与 crel_field / curve_crel 同口径，保证等值线过点。"""
    L = float(lightness(h, s, v, metric))
    C = float(ok_L_C(h, s, v)[1])
    cmax = float(cmax_of_L(h, metric, L))
    return (C / cmax if cmax > 1e-9 else 0.0), C


def crel_field(h, metric, n=41):
    """在 (S,V) 网格上算相对彩度场 C_rel(s,v)（0=灰，1=该明度下最饱和）。

    返回 (ax, rel)：ax 为 S/V 轴刻度，rel[i, j] 对应 V=ax[i]、S=ax[j]。
    """
    ax = np.linspace(0.0, 1.0, n)
    S, V = np.meshgrid(ax, ax)                 # S[i,j]=ax[j]、V[i,j]=ax[i]
    Lg = lightness(h, S, V, metric)
    Cg = ok_L_C(h, S, V)[1]
    cmax_g = np.maximum(cmax_of_L(h, metric, Lg), 1e-9)
    rel = np.clip(Cg / cmax_g, 0.0, 1.0)
    # 灰轴附近 C→0 且数值噪声大，强制归零，避免低 S 处等值线乱跑
    rel[:, 0] = 0.0
    rel[S <= 1e-6] = 0.0
    return ax, rel


def crel_isoline(ax, rel, target):
    """取相对彩度 = target 的等值线（按 V 逐行反解 S，向量化）。返回 (S 数组, V 数组)。"""
    ax = np.asarray(ax, dtype=np.float64)
    rel = np.asarray(rel, dtype=np.float64)
    inside = (rel[:, 0] <= target + 1e-12) & (target - 1e-12 <= rel[:, -1])
    rows = np.nonzero(inside)[0]
    if len(rows) < 2:
        return np.array([]), np.array([])
    r = rel[rows, :]
    k = np.clip(np.sum(r < target, axis=1), 1, r.shape[1] - 1)
    i = np.arange(len(rows))
    r0, r1 = r[i, k - 1], r[i, k]
    d = r1 - r0
    t = np.clip((target - r0) / np.where(np.abs(d) < 1e-15, 1e-15, d), 0.0, 1.0)
    return ax[k - 1] + (ax[k] - ax[k - 1]) * t, ax[rows]


def crel_of_sv(h, metric, s, v):
    """向量化的 C_rel(s,v)（与 crel_of_xyz 同口径，支持数组）。"""
    L = lightness(h, s, v, metric)
    C = ok_L_C(h, s, v)[1]
    return C / np.maximum(cmax_of_L(h, metric, L), 1e-9)


def solve_s_at_crel(h, metric, V, target, iters=26):
    """给定 V（数组）、求使 C_rel = target 的 S（向量化二分；无解的行返回 NaN）。

    用途：过点等彩度线**必须在行上精确满足** C_rel = target（折线插值会差 0.002 上下）。
    """
    V = np.asarray(V, dtype=np.float64)
    hi_val = crel_of_sv(h, metric, np.ones_like(V), V)      # S=1 处的 C_rel（该行最大值）
    ok = hi_val >= target - 1e-12
    lo = np.zeros_like(V)
    hi = np.ones_like(V)
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        low = crel_of_sv(h, metric, mid, V) < target
        lo = np.where(low, mid, lo)
        hi = np.where(~low, mid, hi)
    s = 0.5 * (lo + hi)
    return np.where(ok, s, np.nan)


def solve_s_crel_scalar(h, metric, v, target, iters=30):
    """标量版：给定 V，二分求使 C_rel = target 的 S（过点线专用，避免 numpy 调度开销）。"""
    lo, hi = 0.0, 1.0
    for _ in range(iters):
        mid = 0.5 * (lo + hi)
        c, _ = crel_of_xyz(h, metric, mid, v)
        if c < target:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)




def crel_isoline_through(h, metric, ax, rel, target, v_point):
    """等彩度线（网格等值线 + 按**色点所在那一行的精确解**插入点）。

    曲线本来由 41x41 网格插值给出，网格本身误差 ~0.002；但"线要过色点"这件事
    必须严格，所以专门给色点所在 V 再做一次精确二分，保证线上严格穿过色点。
    补点前校验：a) 解必须落在 (0,1) 的明显内部（S≤1e-6 视为无解：V→1 时
                     绝对彩度与 C_max 同时趋 0，二分会被浮点分辨率顶到 0）；
                  b) 用绝对彩度对 S 的数值敏感度做病态判据，敏感度远超目标 C_rel 时
                     放弃补点。旧版不做校验，会在每条线顶端留下一个
                     (V=1.0, S≈1e-6) 的假点，把线尾拽到完全错误的位置。
    """
    s_iso, v_iso = crel_isoline(ax, rel, target)
    if len(s_iso) < 2:
        return s_iso, v_iso
    v0, v1 = float(v_iso[0]), float(v_iso[-1])
    vp = float(v_point)
    if not (v0 - 1e-9 <= vp <= v1 + 1e-9):
        return s_iso, v_iso
    s_p = float(solve_s_crel_scalar(h, metric, vp, target))
    if not (1e-6 < s_p < 1.0 - 1e-12):        # a) 退化端/边界无解，不补点
        return s_iso, v_iso
    sigma = 1e-9 / s_p                        # b) C_rel 数值敏感度判据
    c_lo = float(crel_of_xyz(h, metric, max(0.0, s_p - sigma), vp)[0])
    c_hi = float(crel_of_xyz(h, metric, min(1.0, s_p + sigma), vp)[0])
    if abs(c_hi - c_lo) > 0.5 * float(target):   # 比值病态：解不可信
        return s_iso, v_iso
    ss = np.concatenate([np.asarray(s_iso, dtype=np.float64), np.array([s_p])])
    vv = np.concatenate([np.asarray(v_iso, dtype=np.float64), np.array([vp])])
    order = np.argsort(vv, kind="stable")
    return ss[order], vv[order]




# ================================================================ 图像渲染
def _bg_rgb01():
    return np.array([int(BG[1:3], 16), int(BG[3:5], 16), int(BG[5:7], 16)], dtype=np.float64) / 255.0










_RING_CACHE = {}




# ================================================================ 文本解析








_HEX_RE = re.compile(r"^#?([0-9a-fA-F]{6}|[0-9a-fA-F]{3})$")


# ================================================================ 数值解析（数值框校验用）

def parse_number(txt):
    t = txt.strip().replace("，", "").replace(",", "")
    t = re.sub(r"[^0-9eE+\-.]", "", t)
    if not t:
        raise ValueError("空值")
    return float(t)
def parse_hue(txt):
    return parse_number(txt) % 360.0
def parse_ratio(txt):
    """'50' / '50%' -> 0.5；'0.5' / '.5' -> 0.5；'0.5%' -> 0.005"""
    t = txt.strip().replace("％", "%")
    if t.endswith("%"):
        return clamp(float(re.sub(r"[^0-9eE+\-.]", "", t[:-1])) / 100.0, 0.0, 1.0)
    x = parse_number(t)
    if 0.0 <= x <= 1.0 and "." in t:
        return x
    return clamp(x / 100.0, 0.0, 1.0)
def parse_rgb(txt):
    """0~255；带 % 按 0~100% 折算；带小数点且 ≤1 按 0~1 折算。"""
    t = txt.strip().replace("％", "%")
    if t.endswith("%"):
        return int(round(clamp(float(re.sub(r"[^0-9eE+\-.]", "", t[:-1])), 0.0, 100.0) * 2.55))
    x = parse_number(t)
    if 0.0 <= x <= 1.0 and "." in t:
        x *= 255.0
    return int(round(clamp(x, 0.0, 255.0)))
def parse_hex(txt):
    t = txt.strip()
    m = _HEX_RE.match(t)
    if m:
        s = m.group(1)
        if len(s) == 3:
            s = "".join(ch * 2 for ch in s)
        return tuple(int(s[i:i + 2], 16) for i in (0, 2, 4))
    nums = re.findall(r"\d+(?:\.\d+)?", t)
    if len(nums) == 3:
        return tuple(parse_rgb(n) for n in nums)
    raise ValueError("无法识别的颜色：" + txt)


# ================================================================ 批量等彩度线（明度轨迹线簇）
def crel_isoline_many(ax, rel, targets):
    """从 C_rel 场里一次性抽取多条等值线（明度轨迹线簇用）。

    与 crel_isoline 同口径（按 V 行对 S 线性插值），但把 levels 放到第三条轴广播，
    一次算完所有目标；返回 [(S 数组, V 数组), ...]，无解的条目返回空数组。
    """
    ax = np.asarray(ax, dtype=np.float64)
    rel = np.asarray(rel, dtype=np.float64)
    tg = np.asarray(targets, dtype=np.float64).reshape(1, 1, -1)     # (1, 1, L)
    inside = (rel[:, 0][:, None] <= tg[0] + 1e-12) &              (tg[0] - 1e-12 <= rel[:, -1][:, None])                  # (rows, L)
    k = np.clip(np.sum(rel[:, :, None] < tg, axis=1), 1, rel.shape[1] - 1)   # (rows, L)
    idx = np.arange(rel.shape[0])[:, None]                           # (rows, 1)
    r0 = rel[idx, k - 1]
    r1 = rel[idx, k]
    d = r1 - r0
    t = np.clip((tg[0] - r0) / np.where(np.abs(d) < 1e-15, 1e-15, d), 0.0, 1.0)
    s_line = ax[k - 1] + (ax[k] - ax[k - 1]) * t
    v_line = np.broadcast_to(ax[:, None], s_line.shape)
    out = []
    for j in range(tg.shape[2]):
        mask = inside[:, j]
        if int(mask.sum()) >= 2:
            out.append((s_line[mask, j], v_line[mask, j]))
        else:
            out.append((np.array([]), np.array([])))
    return out


# ================================================================ 绝对彩度：固定 (L, C) 求 (S, V) 与可达色相
# 色环「不可达色相」提示、环上右键「锁 L + 锁绝对 C」、C 条双口径共用。
C_ABS_LIM = 0.4             # 绝对彩度条的固定量程上界（sRGB 全色域最大 Oklab C ≈ 0.3217，取整留余量）
_CMAX_HUE_GRID = np.arange(0.0, 361.0, 1.0)   # 闭区间：360 与 0 重合，np.interp 按环绕工作
_CMAX_CURVE_CACHE = {}      # {round(L,6): 全色相 C_max 曲线}
_CMAX_CURVE_MAX = 32        # 曲线缓存条数上限（拖动时 L 每帧变，限制内存）

_cbrt_py = getattr(math, "cbrt", None)
if _cbrt_py is None:        # Python < 3.11 兜底（本机 3.12 / Krita 内嵌 3.13 走 math.cbrt）
    def _cbrt_py(x):
        return math.copysign(abs(x) ** (1.0 / 3.0), x)


def _hsv_linear_py(h, s, v):
    """标量 HSV -> **线性** sRGB（纯 Python 快路径，_oklab_lc_py / _gray_lc_py 共用）。"""
    hh = float(h) % 360.0
    ss = 0.0 if s < 0.0 else (1.0 if s > 1.0 else float(s))
    vv = 0.0 if v < 0.0 else (1.0 if v > 1.0 else float(v))
    hp = hh / 60.0
    k = int(hp) % 6
    f = hp - int(hp)
    p = vv * (1.0 - ss)
    q = vv * (1.0 - ss * f)
    t = vv * (1.0 - ss * (1.0 - f))
    r, g, b = ((vv, t, p), (q, vv, p), (p, vv, t),
               (p, q, vv), (t, p, vv), (vv, p, q))[k]
    R = r / 12.92 if r <= 0.04045 else ((r + 0.055) / 1.055) ** 2.4
    G = g / 12.92 if g <= 0.04045 else ((g + 0.055) / 1.055) ** 2.4
    B = b / 12.92 if b <= 0.04045 else ((b + 0.055) / 1.055) ** 2.4
    return R, G, B


def _oklab_lc_py(h, s, v):
    """标量 (L, C)：HSV -> Oklab 明度与绝对彩度（纯 Python 快路径）。

    与 lightness(..., "oklab") / ok_L_C() 同一矩阵（实测差 ≤6e-17），
    单次 ~0.7us（numpy 标量路径 ~10us）：固定 (L,C) 求解每帧要调上千次。
    """
    R, G, B = _hsv_linear_py(h, s, v)
    l_ = _cbrt_py(0.4122214708 * R + 0.5363325363 * G + 0.0514459929 * B)
    m_ = _cbrt_py(0.2119034982 * R + 0.6806995451 * G + 0.1073969566 * B)
    s_ = _cbrt_py(0.0883024619 * R + 0.2817188376 * G + 0.6299787005 * B)
    L = 0.2104542553 * l_ + 0.7936177850 * m_ - 0.0040720468 * s_
    a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    bb = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    return L, math.hypot(a, bb)


def _gray_lc_py(h, s, v):
    """标量 (gray, C)：HSV -> 灰阶码值 srgb_encode(Y) 与 Oklab 绝对彩度（纯 Python）。

    灰阶口径 = Krita 软打样那张灰块的码值：Y = (0.2126729R + 0.7151522G + 0.0721750B)/Σ，
    纯白 = 1；C 仍是 Oklab 绝对彩度（切灰阶只换明度轴，不换彩度轴）。
    """
    R, G, B = _hsv_linear_py(h, s, v)
    Y = (0.2126729 * R + 0.7151522 * G + 0.0721750 * B) / _Y_SUM
    gray = 12.92 * Y if Y <= 0.0031308 else 1.055 * (Y ** (1.0 / 2.4)) - 0.055
    l_ = _cbrt_py(0.4122214708 * R + 0.5363325363 * G + 0.0514459929 * B)
    m_ = _cbrt_py(0.2119034982 * R + 0.6806995451 * G + 0.1073969566 * B)
    s_ = _cbrt_py(0.0883024619 * R + 0.2817188376 * G + 0.6299787005 * B)
    a = 1.9779984951 * l_ - 2.4285922050 * m_ + 0.4505937099 * s_
    bb = 0.0259040371 * l_ + 0.7827717662 * m_ - 0.8086757660 * s_
    return gray, math.hypot(a, bb)


def _metric_lc_py(h, s, v, metric="oklab"):
    """标量 (指标明度 L, Oklab 绝对彩度 C)：metric="gray" 换灰阶轴，其余同 Oklab。"""
    if metric == "gray":
        return _gray_lc_py(h, s, v)
    return _oklab_lc_py(h, s, v)


def _lightness_py(h, s, v):
    """标量 Oklab 明度（纯 Python）。"""
    return _oklab_lc_py(h, s, v)[0]


def _solve_v_py(h, s, L0, iters=26):
    """固定色相/S，二分求使 Oklab 明度 = L0 的 V（L 随 V 严格单调增）。"""
    lo, hi = 0.0, 1.0
    for _ in range(int(iters)):
        mid = 0.5 * (lo + hi)
        if _lightness_py(h, s, mid) < L0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _cmax_point_py(h, L0, inner=26):
    """(h, L0) 下绝对彩度最大的点 -> (S, V, C_max)：S=1 边解 V 或 V=1 边解 S。"""
    Lp = _lightness_py(h, 1.0, 1.0)
    if L0 <= Lp:                     # S=1 边：L 随 V 单调增
        lo, hi = 0.0, 1.0
        for _ in range(int(inner)):
            mid = 0.5 * (lo + hi)
            if _lightness_py(h, 1.0, mid) < L0:
                lo = mid
            else:
                hi = mid
        s, v = 1.0, 0.5 * (lo + hi)
    else:                            # V=1 边：L 随 S 单调减
        lo, hi = 0.0, 1.0
        for _ in range(int(inner)):
            mid = 0.5 * (lo + hi)
            if _lightness_py(h, mid, 1.0) > L0:
                lo = mid
            else:
                hi = mid
        s, v = 0.5 * (lo + hi), 1.0
    return s, v, _oklab_lc_py(h, s, v)[1]


def _solve_v_metric_py(h, s, L0, metric="oklab", iters=26):
    """按 metric 的「明度 -> V」二分（metric="oklab" 时与 _solve_v_py 完全一致）。"""
    if metric == "oklab":
        return _solve_v_py(h, s, L0, iters)
    lo, hi = 0.0, 1.0
    for _ in range(int(iters)):
        mid = 0.5 * (lo + hi)
        if _gray_lc_py(h, s, mid)[0] < L0:
            lo = mid
        else:
            hi = mid
    return 0.5 * (lo + hi)


def _cmax_point_metric_py(h, L0, metric="oklab", inner=26):
    """按 metric 的明度轴，在 sRGB 边界上找 C 最大的点 -> (S, V, C_max)。

    metric="oklab" 时直接走原 _cmax_point_py（保证默认口径逐位不变）。
    """
    if metric == "oklab":
        return _cmax_point_py(h, L0, inner)
    Lp = _gray_lc_py(h, 1.0, 1.0)[0]     # 纯色端（S=1,V=1）的灰阶码值
    if L0 <= Lp:                         # S=1 边：gray 随 V 单调增
        lo, hi = 0.0, 1.0
        for _ in range(int(inner)):
            mid = 0.5 * (lo + hi)
            if _gray_lc_py(h, 1.0, mid)[0] < L0:
                lo = mid
            else:
                hi = mid
        s, v = 1.0, 0.5 * (lo + hi)
    else:                                # V=1 边：gray 随 S 单调减
        lo, hi = 0.0, 1.0
        for _ in range(int(inner)):
            mid = 0.5 * (lo + hi)
            if _gray_lc_py(h, mid, 1.0)[0] > L0:
                lo = mid
            else:
                hi = mid
        s, v = 0.5 * (lo + hi), 1.0
    return s, v, _gray_lc_py(h, s, v)[1]


def cmax_hue_curve(L, iters=20, metric="oklab"):
    """固定指标明度 L，一次求出 0~360° 全部色相的 C_max（1° 步长，361 点）。

    为什么不用 cmax_of_L 逐色相算：那要为每个色相建 385 点边界表（0.25ms/色相，
    360 个色相 ~97ms），而色环「不可达提示」每次颜色变化都要重算。
    这里把两个分支（S=1 边解 V / V=1 边解 S）合并成一条 numpy 二分：
    361 个色相一次 ~1.3ms（iters=20，与精确解偏差 ≤2e-7）。按 (L, metric) 缓存。
    """
    key = (round(float(L), 6), metric)
    got = _CMAX_CURVE_CACHE.get(key)
    if got is not None:
        return got
    L = float(L)
    hues = _CMAX_HUE_GRID
    sat = L <= lightness(hues, 1.0, 1.0, metric)       # True 走 S=1 边，否则走 V=1 边
    lo = np.zeros_like(hues)
    hi = np.ones_like(hues)
    for _ in range(int(iters)):
        mid = 0.5 * (lo + hi)
        Lmid = lightness(hues, np.where(sat, 1.0, mid), np.where(sat, mid, 1.0), metric)
        behind = np.where(sat, Lmid < L, Lmid > L)     # 「还没到目标明度」的两种方向
        lo = np.where(behind, mid, lo)
        hi = np.where(behind, hi, mid)
    x = 0.5 * (lo + hi)
    out = ok_L_C(hues, np.where(sat, 1.0, x), np.where(sat, x, 1.0))[1]
    out = np.where(L > 0.0, out, 0.0)
    if len(_CMAX_CURVE_CACHE) >= _CMAX_CURVE_MAX:
        _CMAX_CURVE_CACHE.clear()
    _CMAX_CURVE_CACHE[key] = out
    return out


def hue_reachable_mask(hs, L, C, metric="oklab"):
    """色相数组 hs（度）在固定 (指标明度 L, 绝对彩度 C) 下是否可达。

    可达定义：C_max(L, h) >= C。返回同形状 bool 数组（标量入参返回 0 维数组）。
    彩度 C 永远是 Oklab 绝对彩度；metric="gray" 只换明度轴。
    """
    hs = np.asarray(hs, dtype=np.float64) % 360.0
    if float(C) <= 1e-12:
        return np.ones(hs.shape, dtype=bool)
    cm = np.interp(hs, _CMAX_HUE_GRID, cmax_hue_curve(L, metric=metric))
    return cm >= float(C) - 1e-12


def hue_reachable_spans(L, C, step=1.0, metric="oklab"):
    """可达色相区间列表 [(lo, hi), ...]（度）：弧从 lo 起、宽 hi-lo，可能跨 0°。

    用 step（默认 1°）均匀采样 + hue_reachable_mask 同口径判定；支持「2 段可达」
    （中间被不可达段隔开）。全可达 -> [(0.0, 360.0)]；全不可达 -> []。
    每个采样格的覆盖范围取「格中心 ±step/2」，据此画的斜纹与同分辨率采样一一对应。
    """
    step = float(step)
    if step <= 0.0 or step > 360.0:
        step = 1.0
    n = max(1, int(round(360.0 / step)))
    hs = np.arange(n, dtype=np.float64) * step
    mask = np.asarray(hue_reachable_mask(hs, L, C, metric), dtype=bool)
    if bool(mask.all()):
        return [(0.0, 360.0)]
    if not bool(mask.any()):
        return []
    start = int(np.argmin(mask))        # 从某个不可达点出发，天然不会把跨 0° 的弧切断
    spans = []
    k = 0
    while k < n:
        if not mask[(start + k) % n]:
            k += 1
            continue
        j = k
        while j < n and mask[(start + j) % n]:
            j += 1
        a = ((start + k) % n) * step
        width = (j - k) * step
        lo = (a - 0.5 * step) % 360.0
        spans.append((lo, lo + width))
        k = j
    return spans


def sv_at_L_C(h, L0, C0, metric="oklab", iters=30, inner=26, clamp=False):
    """固定 HSV 色相 h、指标明度 L0、绝对彩度 C0，解 (S, V)；不可达返回 None。

    依据：沿等明度曲线绝对彩度 C 随 S 严格单调（60/60 组实测），故解唯一、不分叉。
    外层二分 S、内层二分 V（纯 Python 快路径，一次 ~40us）。
    clamp=True 时不可达就直接返回「该 (h, L0) 下 C 最大的点」（C=C_max）——
    供 C 条 / 明度条拖到色域边界时停住用；默认 None 供环上右键 sticky 判定用。
    metric="oklab"（默认）时 L0 是 Oklab L∈[0,1]；metric="gray" 时 L0 是灰阶码值∈[0,1]，
    彩度 C 仍是 Oklab 绝对彩度（切灰阶只换明度轴）。
    """
    h = float(h) % 360.0
    L0 = float(L0)
    C0 = float(C0)
    if L0 <= 1e-12:                 # 纯黑：C_max = 0（二分到不了精确端点，这里直接给）
        return (0.0, 0.0) if (C0 <= 1e-9 or clamp) else None
    if L0 >= 1.0 - 1e-12:           # 纯白：C_max = 0
        return (0.0, 1.0) if (C0 <= 1e-9 or clamp) else None
    s_pk, v_pk, c_pk = _cmax_point_metric_py(h, L0, metric, inner)
    # C_max 有两套口径：cmax_of_L（查表；色相可达性、C 条量程、等彩度场都用它）与
    # _cmax_point_py（直接二分）。两者有 ~1e-6 量级的数值差，若只按 c_pk 判边界，
    # 会把「恰好取满 C_max」的颜色误判成不可达（实测 C_rel=1 时有 12~27/36 个色相中招）。
    # 这里统一以 cmax_of_L 为准，并把 C0 钳到本曲线的峰，保证「取满」永远有解。
    if C0 > float(cmax_of_L(h, metric, L0)) + 1e-9:
        return (s_pk, v_pk) if clamp else None
    if C0 > c_pk:
        C0 = c_pk
    if C0 <= 1e-12:
        return 0.0, _solve_v_metric_py(h, 0.0, L0, metric, inner)   # 灰轴（C=0）
    lo, hi = 0.0, s_pk
    for _ in range(int(iters)):
        mid = 0.5 * (lo + hi)
        if _metric_lc_py(h, mid, _solve_v_metric_py(h, mid, L0, metric, inner),
                         metric)[1] < C0:
            lo = mid
        else:
            hi = mid
    s = 0.5 * (lo + hi)
    return s, _solve_v_metric_py(h, s, L0, metric, inner)


def sv_at_L_C_many(hs, L0, C0, metric="oklab", iters=30, inner=26):
    """sv_at_L_C 的批量版（色相数组）：返回 (S 数组, V 数组)，不可达处为 NaN。"""
    hs = np.atleast_1d(np.asarray(hs, dtype=np.float64))
    ss = np.full(hs.shape, np.nan, dtype=np.float64)
    vv = np.full(hs.shape, np.nan, dtype=np.float64)
    for i, h in enumerate(hs.ravel()):
        got = sv_at_L_C(float(h), L0, C0, metric, iters=iters, inner=inner)
        if got is not None:
            ss.ravel()[i], vv.ravel()[i] = got
    return ss, vv


def sv_at_L_crel(h, L0, crel, metric="oklab", iters=30, inner=26):
    """固定 (h, Oklab 明度 L0, 相对彩度 C_rel) 解 (S, V)。

    C_rel = C / C_max(L0, h) ∈ [0,1]，等价于绝对口径 C0 = C_rel × C_max(L0, h)；
    C_rel ≤ 1 时理论上永远可达（边界处可能被数值判成不可达，返回 None）。
    """
    hh = float(h) % 360.0
    cmax = float(cmax_of_L(hh, metric, float(L0)))
    return sv_at_L_C(hh, float(L0), float(crel) * cmax, metric, iters=iters, inner=inner)


def hue_is_reachable(h, L, C, metric="oklab"):
    """单个色相 h 在固定 (指标明度 L, 绝对彩度 C) 下是否可达（标量布尔）。"""
    return bool(hue_reachable_mask(np.array([float(h)]), L, C, metric)[0])


def nearest_reachable_hue(h, L, C, step=1.0, iters=24, metric="oklab"):
    """固定 (L, 绝对彩度 C) 下距离色相 h **角度最近**的可达色相。

    可达 = C_max(L, h) >= C。全可达 -> h；全不可达 -> None。
    先用 step 网格取最近的可达采样点，再从它朝 h 二分到精确边界，
    返回的点保证 ``hue_is_reachable`` 为真（可直接用 sv_at_L_C 求色）。
    """
    h = float(h) % 360.0
    span = 360.0 / max(1.0, float(step))
    hs = np.arange(int(round(span)), dtype=np.float64) * (360.0 / int(round(span)))
    mask = np.asarray(hue_reachable_mask(hs, L, C, metric), dtype=bool)
    if not bool(mask.any()):
        return None
    if hue_is_reachable(h, L, C, metric):
        return h
    dist = np.abs(((hs - h) + 180.0) % 360.0 - 180.0)
    dist = np.where(mask, dist, np.inf)
    i = int(np.argmin(dist))
    best = float(hs[i]) % 360.0
    delta = ((h - best) + 180.0) % 360.0 - 180.0
    if abs(delta) < 1e-12:
        return best
    lo_f, hi_f, res = 0.0, 1.0, best
    for _ in range(int(iters)):
        mid = 0.5 * (lo_f + hi_f)
        cand = (best + mid * delta) % 360.0
        if hue_is_reachable(cand, L, C, metric):
            lo_f, res = mid, cand
        else:
            hi_f = mid
    return res % 360.0
