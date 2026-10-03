# -*- coding: utf-8 -*-
"""math_core.py 数学层回归自检（系统 Python + numpy，不需要 Krita / Qt / Tk）。

用法：python tools/math_selftest.py
基准：Tkinter 版 `python hsv_lightness_picker.py --selftest` 的数学断言，
      以及从旧版实跑取到的黄金锚点（GOLDEN，容差 1e-9）。
"""
import os
import sys
import time
import traceback

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pykrita", "hsv_picker"))

import numpy as np          # noqa: E402
import math_core as mc      # noqa: E402

PASS = []
FAIL = []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("[%s] %-56s %s" % ("OK  " if ok else "FAIL", name, detail))


def close(name, got, want, tol=1e-9):
    ok = abs(float(got) - float(want)) <= tol
    check(name, ok, "实测 %.12g 期望 %.12g (Δ=%.2g)" % (got, want, abs(float(got) - float(want))))


# ---------------------------------------------------------------- 黄金锚点
GOLDEN = {
    "lightness_lab_red": 53.2407918333,
    "lightness_oklab_red": 0.6279553606,
    "lightness_oklab_gray50": 0.5981807266,
    # CIE Lab 参考实现（仅自检用，插件彩度已不从这里取）
    "lab_L_C_red": (53.2407941413, 104.5517656769),
    "lab_L_C_120_060_090": (81.4818000045, 84.0385331094),
    # Oklab 口径（现行）：C = √(a²+b²)
    "cmax_of_L_red_oklab_050": 0.2051764535,
    "cmax_of_L_30_oklab_080": 0.1455143670,
    "crel_of_xyz_120_060_090": (0.7732775111, 0.2155334892),
    "crel_of_xyz_200_030_050": (0.2847169486, 0.0358891338),
    "lbar_f_oklab_L050": 0.1003433319,
    "lbar_L_from_f_oklab_030": 0.5011872336,
    "solve_s_crel_scalar_45_080": 0.3875330533,
    "crel_of_sv_45_08": 0.9200532766,
}


def test_color_math():
    print("\n== 1. 明度与 CIE Lab ==")
    close("Oklab L(白)=1", mc.lightness(0, 0, 1, "oklab"), 1.0, 1e-6)
    close("Oklab L(黑)=0", mc.lightness(0, 0, 0, "oklab"), 0.0, 1e-9)
    close("L*(白)=100", mc.lightness(0, 0, 1, "lab"), 100.0, 1e-4)
    close("L*(黑)=0", mc.lightness(0, 0, 0, "lab"), 0.0, 1e-9)
    close("L*(纯红)=53.2408", mc.lightness(0, 1, 1, "lab"), GOLDEN["lightness_lab_red"])
    close("Oklab L(纯红)=0.6280", mc.lightness(0, 1, 1, "oklab"), GOLDEN["lightness_oklab_red"])
    close("Oklab L(灰50%)=0.5982", mc.lightness(0, 0, 0.5, "oklab"), GOLDEN["lightness_oklab_gray50"])
    L, C = mc.lab_L_C(0, 1, 1)
    close("lab_L_C(纯红).L", L, GOLDEN["lab_L_C_red"][0])
    close("lab_L_C(纯红).C", C, GOLDEN["lab_L_C_red"][1])
    L, C = mc.lab_L_C(120, 0.6, 0.9)
    close("lab_L_C(120,.6,.9).L", L, GOLDEN["lab_L_C_120_060_090"][0])
    close("lab_L_C(120,.6,.9).C", C, GOLDEN["lab_L_C_120_060_090"][1])


def test_hsv_roundtrip():
    print("\n== 2. HSV <-> sRGB 往返 ==")
    rng = np.random.default_rng(20260913)
    h = rng.uniform(0.0, 360.0, 500)
    s = rng.uniform(0.05, 1.0, 500)
    v = rng.uniform(0.05, 1.0, 500)
    worst_hs = 0.0
    for i in range(len(h)):
        r = float(mc.hsv_to_srgb(float(h[i]), float(s[i]), float(v[i]))[0])
        g = float(mc.hsv_to_srgb(float(h[i]), float(s[i]), float(v[i]))[1])
        b = float(mc.hsv_to_srgb(float(h[i]), float(s[i]), float(v[i]))[2])
        h2, s2, v2 = mc.srgb_to_hsv(r, g, b)
        dh = min(abs(h2 - h[i]), 360.0 - abs(h2 - h[i]))
        worst_hs = max(worst_hs, dh, abs(s2 - s[i]), abs(v2 - v[i]))
    check("500 随机色 HSV->RGB->HSV 往返（标量口径）", worst_hs < 1e-9, "最大偏差 %.2e" % worst_hs)


def test_iso_curve():
    print("\n== 3. 等明度曲线（彩度轨迹线）==")
    n_checked = 0
    worst_L = 0.0
    mono_ok = True
    for hue in (0, 45, 120, 200, 300):
        for target in (0.2, 0.5, 0.8):
            ss, vv = mc.iso_lightness_curve(hue, target, "oklab")
            if len(ss) < 3:
                continue
            Ls = mc.lightness(hue, ss, vv, "oklab")
            worst_L = max(worst_L, float(np.max(np.abs(Ls - target))))
            if float(np.max(np.diff(ss))) <= 0:
                mono_ok = False
            n_checked += 1
    check("等明度曲线：明度恒定（%d 条）" % n_checked, worst_L < 1e-6, "最大 |ΔL| = %.2e" % worst_L)
    check("等明度曲线：S 单调递增", mono_ok)
    ss, vv = mc.iso_lightness_curve(0, 0.5, "oklab")
    close("曲线起点在左边缘 S=0", ss[0], 0.0, 1e-9)
    close("曲线起点 V=_v_gray(target)", vv[0], float(mc._v_gray("oklab", 0.5)), 1e-12)
    check("曲线点数 257", len(ss) == 257, "实测 %d" % len(ss))
    close("曲线终点 S", ss[-1], 0.9999999976, 1e-8)
    close("曲线终点 V", vv[-1], 0.7385129151, 1e-8)
    rows = mc.iso_lightness_curves(30, [0.3, 0.6, 0.9], "oklab")
    ok_rows = all(len(r) == 3 and len(r[1]) == len(r[2]) and len(r[1]) >= 2 for r in rows)
    check("iso_lightness_curves 返回 [(L, ss, vv), ...]", ok_rows and len(rows) >= 1,
          "返回 %d 条，形状合法=%s" % (len(rows), ok_rows))
    if rows:
        L0, ss0, vv0 = rows[0]
        close("簇首条明度恒定", float(np.max(np.abs(mc.lightness(30, ss0, vv0, "oklab") - L0))), 0.0, 1e-6)


def test_curves_utils():
    print("\n== 4. 曲线工具（弧长 / 投影 / 精修）==")
    ss, vv = mc.iso_lightness_curve(0, 0.5, "oklab")
    tt = mc.curve_arclen(ss, vv)
    check("curve_arclen 单调递增", bool(np.all(np.diff(tt) >= -1e-15)))
    close("curve_arclen 起点 0", tt[0], 0.0)
    close("curve_arclen 终点 1", tt[-1], 1.0)
    s_mid, v_mid = mc.point_at_t(ss, vv, tt, 0.5)
    t_back = mc.nearest_t(ss, vv, tt, s_mid, v_mid)
    close("nearest_t 与 point_at_t 互逆 t=0.5", t_back, 0.5, 1e-9)
    for t in (0.1, 0.3, 0.7, 0.95):
        s0, v0 = mc.point_at_t(ss, vv, tt, t)
        close("互逆 t=%.2f" % t, mc.nearest_t(ss, vv, tt, s0, v0), t, 1e-9)
    s_ref, v_ref = mc.refine_on_curve(30, 0.6, "oklab", 0.7)
    close("refine_on_curve 后明度=target", mc.lightness(30, s_ref, v_ref, "oklab"), 0.6, 1e-9)
    check("refine_on_curve 返回同一 V", abs(v_ref - 0.7) < 1e-15, "v=%.2f" % v_ref)
    # 该 V 下 S=1 也够不到目标明度时，只能返回边界解（旧版同行为）
    s_lim, v_lim = mc.refine_on_curve(30, 0.6, "oklab", 0.9)
    check("够不到目标时返回边界 S≈1", abs(s_lim - 1.0) < 1e-6 and abs(v_lim - 0.9) < 1e-15,
          "S=%.6f" % s_lim)


def test_crel():
    print("\n== 5. 相对彩度与 C_max（Oklab 口径）==")
    close("cmax_of_L(红,oklab,0.5)", mc.cmax_of_L(0, "oklab", 0.5), GOLDEN["cmax_of_L_red_oklab_050"])
    close("cmax_of_L(30,oklab,0.8)", mc.cmax_of_L(30, "oklab", 0.8), GOLDEN["cmax_of_L_30_oklab_080"])
    close("cmax_of_L(L=0)=0", mc.cmax_of_L(0, "oklab", 0.0), 0.0)
    crel, cabs = mc.crel_of_xyz(120, "oklab", 0.6, 0.9)
    close("crel_of_xyz(120,.6,.9).C_rel", crel, GOLDEN["crel_of_xyz_120_060_090"][0])
    close("crel_of_xyz(120,.6,.9).C", cabs, GOLDEN["crel_of_xyz_120_060_090"][1])
    crel2, cabs2 = mc.crel_of_xyz(200, "oklab", 0.3, 0.5)
    close("crel_of_xyz(200,.3,.5).C_rel", crel2, GOLDEN["crel_of_xyz_200_030_050"][0])
    close("crel_of_xyz(200,.3,.5).C", cabs2, GOLDEN["crel_of_xyz_200_030_050"][1])
    v = np.array([0.8])
    close("crel_of_sv(45,oklab,.8,.8)", mc.crel_of_sv(45, "oklab", v, v)[0], GOLDEN["crel_of_sv_45_08"])
    s_sol = mc.solve_s_crel_scalar(45, "oklab", 0.8, 0.5)
    close("solve_s_crel_scalar(45,.8,0.5)", s_sol, GOLDEN["solve_s_crel_scalar_45_080"])
    crel_check = mc.crel_of_xyz(45, "oklab", s_sol, 0.8)[0]
    close("解出来的 S 满足 C_rel=0.5", crel_check, 0.5, 1e-6)
    ax, rel = mc.crel_field(45, "oklab", n=41)
    check("crel_field 形状 (41,41)", ax.shape == (41,) and rel.shape == (41, 41))
    ss, vv = mc.crel_isoline_through(45, "oklab", ax, rel, 0.7, 0.8)
    check("crel_isoline_through 有解", len(ss) > 10, "点数 %d" % len(ss))
    if len(ss) > 10:
        crel_line = mc.crel_of_sv(45, "oklab", ss, vv)
        cabs_line = np.array([mc.crel_of_xyz(45, "oklab", float(a), float(b))[1]
                              for a, b in zip(ss, vv)])
        # 只在绝对彩度有意义处校验（近黑端 C_rel 比值病态）
        keep = cabs_line > 0.006
        worst = float(np.max(np.abs(crel_line[keep] - 0.7))) if np.any(keep) else 9.9
        check("轨迹线各点 C_rel≈0.7（C>0.006）", worst < 0.01,
              "最大偏差 %.4f（%d/%d 点参与）" % (worst, int(keep.sum()), len(ss)))
    # 精确性：过点线必须真正穿过当前色点
    s_pt, v_pt = 0.4, 0.7
    crel_pt = mc.crel_of_xyz(45, "oklab", s_pt, v_pt)[0]
    ss2, vv2 = mc.crel_isoline_through(45, "oklab", ax, rel, crel_pt, v_pt)
    idx = int(np.argmin(np.abs(ss2 - s_pt) + np.abs(vv2 - v_pt)))
    gap = abs(float(ss2[idx]) - s_pt) + abs(float(vv2[idx]) - v_pt)
    check("轨迹线穿过当前点（端点或中间）", gap < 0.03, "最近点间隙 %.4f" % gap)


def test_lbar():
    print("\n== 6. 明度尺映射（横置明度条用）==")
    for metric in ("oklab", "lab"):
        worst = 0.0
        for f in (0.0, 0.05, 0.25, 0.5, 0.75, 0.95, 1.0):
            for log_mode in (False, True):
                L = mc._lbar_L_from_f(f, log_mode, metric)
                back = mc._lbar_f_from_L(L, log_mode, metric)
                worst = max(worst, abs(float(back) - f))
        check("位置<->明度互逆 [%s]" % metric, worst < 1e-9, "最大误差 %.2e" % worst)
    close("_lbar_f(oklab,0.5,对数)",
          mc._lbar_f(0.5, True, "oklab"), GOLDEN["lbar_f_oklab_L050"])
    close("_lbar_L_from_f(0.3,对数,oklab)",
          mc._lbar_L_from_f(0.3, True, "oklab"), GOLDEN["lbar_L_from_f_oklab_030"])
    v_gray = float(mc._v_gray("oklab", np.array([0.5]))[0])
    want_v = 1.055 * (0.5 ** 3) ** (1.0 / 2.4) - 0.055     # = _srgb_encode(0.5^3)
    close("oklab 线性档灰度 V = _srgb_encode(L^3)", v_gray, want_v, 1e-12)
    close("灰度 V 与 lightness 互逆", mc.lightness(0, 0, v_gray, "oklab"), 0.5, 1e-8)
    check("读数文本 oklab 两位小数", mc.lbar_readout_text(0.6279, "oklab") == "0.63",
          mc.lbar_readout_text(0.6279, "oklab"))
    check("读数文本 lab L*", "53" in mc.lbar_readout_text(53.24, "lab"),
          mc.lbar_readout_text(53.24, "lab"))


def test_parse():
    print("\n== 7. 数值解析（数值框校验）==")
    close("parse_ratio('50')", mc.parse_ratio("50"), 0.5)
    close("parse_ratio('0.5')", mc.parse_ratio("0.5"), 0.5)
    close("parse_ratio('0.5%')", mc.parse_ratio("0.5%"), 0.005)
    close("parse_hue('370')", mc.parse_hue("370"), 10.0)
    check("parse_hex('#f00')", mc.parse_hex("#f00") == (255, 0, 0), "%r" % (mc.parse_hex("#f00"),))
    check("parse_hex('rgb(1,2,3)')", mc.parse_hex("rgb(1,2,3)") == (1, 2, 3))
    check("parse_hex('#888050')", mc.parse_hex("#888050") == (136, 128, 80))
    try:
        mc.parse_hex("")
        check("parse_hex(空串) 抛 ValueError（旧版同口径）", False, "未抛异常")
    except ValueError:
        check("parse_hex(空串) 抛 ValueError（旧版同口径）", True, "旧版同口径")
    try:
        mc.parse_ratio("abc")
        check("parse_ratio(非数字) 抛 ValueError", False, "未抛异常")
    except ValueError:
        check("parse_ratio(非数字) 抛 ValueError", True)


def test_strip():
    print("\n== 8. 色条图像 ==")
    ss, vv = mc.iso_lightness_curve(0, 0.5, "oklab")
    for mode in ("v", "arc", "s"):
        img = mc.strip_image(0, ss, vv, mode, 8, 64)
        check("strip_image[%s] 形状 (64,8,3)" % mode,
              img.shape == (64, 8, 3) and img.dtype == np.uint8, "%r" % (img.shape,))
    img = mc.strip_image(0, ss, vv, "arc", 8, 64)
    check("strip_image 像素在 0~255", int(img.min()) >= 0 and int(img.max()) <= 255)
    f_pt = mc.curve_at_f(ss, vv, "arc", 0.5)
    check("curve_at_f[arc] 返回 (S,V)", f_pt is not None and 0.0 <= f_pt[0] <= 1.0 and 0.0 <= f_pt[1] <= 1.0,
          "%.4f %.4f" % f_pt if f_pt else "None")


def test_isoline_append_guard():
    print("\n== 8.5 过点补点守卫（旧版顶端假点缺陷的回归）==")
    ax, rel = mc.crel_field(45, "oklab", n=41)
    # A. 正常行仍要精确补点：线上必须严格穿过色点
    s_pt, v_pt = 0.40, 0.62
    crel_pt = mc.crel_of_xyz(45, "oklab", s_pt, v_pt)[0]
    ss, vv = mc.crel_isoline_through(45, "oklab", ax, rel, crel_pt, v_pt)
    i = int(np.argmin(np.abs(vv - v_pt)))
    gap = abs(float(ss[i]) - s_pt) + abs(float(vv[i]) - v_pt)
    check("补点：线严格穿过色点", gap < 1e-9, "间隙 %.2e" % gap)
    close("补点后该行 C_rel 回到目标",
          float(mc.crel_of_sv(45, "oklab", ss[i], vv[i])), crel_pt, 1e-6)
    # B. 退化端（v_point=1.0）不得补点
    ss2, vv2 = mc.crel_isoline_through(45, "oklab", ax, rel, 0.7, 1.0)
    n_grid = len(mc.crel_isoline(ax, rel, 0.7)[0])
    check("退化端不补点（点数=网格点数）", len(ss2) == n_grid,
          "线条数 %d，网格 %d" % (len(ss2), n_grid))
    # C. 顶部以下的线各点 C_rel 恒定（排除 V>0.95 的浮点退化区）
    worst = 0.0
    for hue in (0, 45, 120, 200, 300):
        axh, relh = mc.crel_field(hue, "oklab", n=41)
        for target in (0.3, 0.5, 0.7, 0.9):
            for vp in (0.15, 0.3, 0.5, 0.7, 0.9, 0.999):
                s_l, v_l = mc.crel_isoline_through(hue, "oklab", axh, relh, target, vp)
                mask = v_l < 0.95
                if not np.any(mask):
                    continue
                c_l = mc.crel_of_sv(hue, "oklab", s_l[mask], v_l[mask])
                worst = max(worst, float(np.max(np.abs(c_l - target))))
    check("120 例：V<0.95 段 C_rel 恒定", worst < 0.02, "最大偏差 %.4f" % worst)


def test_v_from_lightness():
    print("\n== 8.6 明度 -> 灰阶 V 反解（明度条用）==")
    worst = 0.0
    for L in (0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0):
        v = float(mc.v_from_lightness("oklab", L))
        worst = max(worst, abs(float(mc.lightness(0.0, 0.0, v, "oklab")) - L))
    check("oklab：L -> V -> 回读 L 互逆", worst < 1e-6, "最大误差 %.2e" % worst)
    worst = 0.0
    for L in (0.0, 25.0, 50.0, 75.0, 100.0):
        v = float(mc.v_from_lightness("lab", L))
        worst = max(worst, abs(float(mc.lightness(0.0, 0.0, v, "lab")) - L))
    check("lab：L* -> V -> 回读 L* 互逆", worst < 1e-4, "最大误差 %.2e" % worst)
    check("V(0)=0、V(满量程)=1",
          abs(float(mc.v_from_lightness("oklab", 0.0))) < 1e-12 and
          abs(float(mc.v_from_lightness("oklab", 1.0)) - 1.0) < 1e-6)


def test_oklab_ab():
    print("\n== 5b. Oklab a/b 分量与 sRGB 色域工具 ==")
    worst = 0.0
    for h, s, v in ((0, 1, 1), (30, 0.6, 0.9), (120, 0.4, 0.7), (240, 0.9, 0.3), (300, 0.05, 0.4)):
        L = float(mc.oklab_ab(h, s, v)[0])
        worst = max(worst, abs(L - float(mc.lightness(h, s, v, "oklab"))))
    check("oklab_ab().L 与 lightness(oklab) 同源", worst < 1e-12, "最大偏差 %.2e" % worst)

    L, a, b = (float(x) for x in mc.oklab_ab(0, 1, 1))
    check("Oklab(纯红)=(0.62796, 0.22486, 0.12585)",
          abs(L - 0.6279553606) < 1e-9 and abs(a - 0.2248630611) < 1e-9
          and abs(b - 0.1258462985) < 1e-9, "(%.7f, %.7f, %.7f)" % (L, a, b))

    worst = max(max(abs(float(x)) for x in mc.oklab_ab(0, 0, v)[1:]) for v in (0.2, 0.5, 0.8))
    check("灰轴 a=b=0", worst < 1e-7, "最大 %.2e" % worst)

    _, C = mc.ok_L_C(0, 1, 1)
    check("ok_L_C().C == √(a²+b²)", abs(float(C) - float(np.hypot(a, b))) < 1e-15)

    worst = 0.0
    for h, s, v in ((0, 1, 1), (210, 0.62, 0.86), (120, 0.4, 0.3), (300, 0.3, 0.2)):
        rgb = mc.hsv_to_srgb(h, s, v)
        back = mc.oklab_to_srgb(*[float(x) for x in mc.oklab_ab(h, s, v)])
        worst = max(worst, float(np.max(np.abs(np.asarray(back) - np.asarray(rgb)))))
    check("sRGB->Oklab->sRGB 往返", worst < 2e-6, "最大误差 %.2e" % worst)

    check("oklab_in_gamut(纯色边界)", bool(mc.oklab_in_gamut(*[float(x) for x in mc.oklab_ab(0, 1, 1)]))
          and not bool(mc.oklab_in_gamut(0.5, 0.4, 0.4)))

    # 切片包围盒：内嵌查表 vs 直接二维栅格扫（表在跳变处残差 ~0.01，见 tools/make_ab_box_table.py）
    L0 = 0.65
    a_lo, a_hi, b_lo, b_hi = mc.ab_slice_box(L0)
    _ax = np.linspace(-0.36, 0.36, 401)
    _A, _B = np.meshgrid(_ax, _ax, indexing="ij")
    _m = mc.oklab_in_gamut(L0, _A, _B)
    ref = (float(_A[_m].min()), float(_A[_m].max()), float(_B[_m].min()), float(_B[_m].max()))
    d = max(abs(x - y) for x, y in zip((a_lo, a_hi, b_lo, b_hi), ref))
    check("ab_slice_box 与直接栅格扫一致（≤1e-2）", d < 1e-2,
          "偏差 %.5f；表 a∈[%+.4f, %+.4f] b∈[%+.4f, %+.4f]" % (d, a_lo, a_hi, b_lo, b_hi))

    # 端点近似「贴边」：往里 2e-2 必可达、往外 2e-2 必不可达（表残差 1e-2 + padding 2e-3）
    _bs = np.linspace(b_lo - 0.05, b_hi + 0.05, 401)
    _as = np.linspace(a_lo - 0.05, a_hi + 0.05, 401)
    check("ab_slice_box：边界内 2e-2 可达、外 2e-2 不可达",
          bool(mc.oklab_in_gamut(L0, a_hi - 2e-2, _bs).any())
          and not bool(mc.oklab_in_gamut(L0, a_hi + 2e-2, _bs).any())
          and bool(mc.oklab_in_gamut(L0, a_lo + 2e-2, _bs).any())
          and not bool(mc.oklab_in_gamut(L0, a_lo - 2e-2, _bs).any())
          and bool(mc.oklab_in_gamut(L0, _as, b_hi - 2e-2).any())
          and not bool(mc.oklab_in_gamut(L0, _as, b_hi + 2e-2).any()))

    # 单线可行区间：端点可行、区间外不可行
    l1, h1 = mc.ab_axis_interval(L0, -0.115906, "a")
    check("ab_axis_interval：端点可行、区间外不可行",
          bool(mc.oklab_in_gamut(L0, l1, -0.115906)) and bool(mc.oklab_in_gamut(L0, h1, -0.115906))
          and not bool(mc.oklab_in_gamut(L0, l1 - 6e-3, -0.115906))
          and not bool(mc.oklab_in_gamut(L0, h1 + 6e-3, -0.115906)),
          "[%+.4f, %+.4f]" % (l1, h1))

    # 回归：可行区间可能整段不含灰轴（早期按「从 0 向外二分」的写法会退化成空区间）
    L1 = 0.662366                      # 该明度下 (a=0.264, b=0) 恰好在色域外
    l1b, h1b = mc.ab_axis_interval(L1, -0.115906, "a")
    a_far = 0.985 * h1b
    l2, h2 = mc.ab_axis_interval(L1, a_far, "b")
    check("回归：灰轴不在区间内时仍算得对",
          (not bool(mc.oklab_in_gamut(L1, a_far, 0.0)))
          and bool(mc.oklab_in_gamut(L1, a_far, h2)) and (h2 - l2) > 1e-3,
          "b ∈ [%+.4f, %+.4f]（宽 %.4f）" % (l2, h2, h2 - l2))

    # 两种条口径
    for mode in ("box", "line"):
        lo, hi = mc.ab_strip_range(L0, 0.0, -0.115906, "a", mode)
        cur_ok = bool(mc.oklab_in_gamut(L0, 0.0, -0.115906))
        check("ab_strip_range(mode=%s) 次序与当前值可达" % mode, lo < hi and cur_ok,
              "[%+.4f, %+.4f]" % (lo, hi))
    box_lo, box_hi = mc.ab_strip_range(L0, 0.0, -0.115906, "a", "box")
    line_lo, line_hi = mc.ab_strip_range(L0, 0.0, -0.115906, "a", "line")
    check("box 口径包含 line 口径（死区=包含关系）",
          box_lo <= line_lo + 1e-9 and box_hi >= line_hi - 1e-9,
          "box [%+.4f, %+.4f] ⊇ line [%+.4f, %+.4f]" % (box_lo, box_hi, line_lo, line_hi))

    # 退化保护：近黑处不能返回零宽度
    lo, hi = mc.ab_strip_range(0.001, 0.0, 0.0, "a", "box")
    check("近黑退化仍给出最小宽度", hi - lo > 1e-4, "宽 %.6f" % (hi - lo))


def test_abs_chroma():
    print("")
    print("== 10. 绝对彩度：固定 (L, C) 求 (S, V) 与可达色相 ==")
    # 常量与依据：sRGB 全色域最大 Oklab C 实测 0.3217 @ h=300 L=0.70
    cmax_max = float(mc.cmax_of_L(300.0, "oklab", np.array([0.70]))[0])
    check("C_ABS_LIM=0.4 且 ≥ 全色域最大 C（实测 %.4f）" % cmax_max,
          abs(mc.C_ABS_LIM - 0.4) < 1e-12 and mc.C_ABS_LIM > cmax_max,
          "C_ABS_LIM=%.4f maxC=%.4f" % (mc.C_ABS_LIM, cmax_max))

    # 纯 Python 标量快路径与 numpy 口径一致
    worst_l = worst_c = 0.0
    for h in (0.0, 30.0, 123.4, 200.0, 359.9):
        for s in (0.0, 0.25, 0.6, 1.0):
            for v in (0.0, 0.1, 0.5, 0.9, 1.0):
                L1, C1 = mc._oklab_lc_py(h, s, v)
                worst_l = max(worst_l, abs(L1 - float(mc.lightness(h, s, v, "oklab"))))
                worst_c = max(worst_c, abs(C1 - float(mc.ok_L_C(h, s, v)[1])))
    check("纯 Python (L,C) 快路径与 numpy 口径一致", worst_l < 1e-12 and worst_c < 1e-12,
          "maxΔL=%.2e maxΔC=%.2e" % (worst_l, worst_c))

    # 验收 A3 起点：h=30 S=0.60 V=0.90 -> L=0.760956 C=0.118427
    L0, C0 = (float(x) for x in mc.ok_L_C(30.0, 0.60, 0.90))
    check("A3 起点 L/C 与规格一致", abs(L0 - 0.760956) < 1e-5 and abs(C0 - 0.118427) < 1e-5,
          "L=%.6f C=%.6f" % (L0, C0))
    worst_l = worst_c = 0.0
    hues = (30.0, 60.0, 120.0, 180.0, 240.0, 300.0, 350.0)
    for hh in hues:
        s, v = mc.sv_at_L_C(hh, L0, C0)
        worst_l = max(worst_l, abs(float(mc.lightness(hh, s, v, "oklab")) - L0))
        worst_c = max(worst_c, abs(float(mc.ok_L_C(hh, s, v)[1]) - C0))
    check("sv_at_L_C 往返：L / C 误差 < 1e-6", worst_l < 1e-6 and worst_c < 1e-6,
          "maxΔL=%.2e maxΔC=%.2e" % (worst_l, worst_c))

    # 不可达 -> None；clamp -> C_max 点
    got_none = mc.sv_at_L_C(210.0, L0, 0.30)
    s_c, v_c = mc.sv_at_L_C(210.0, L0, 0.30, clamp=True)
    C_pk = float(mc.cmax_of_L(210.0, "oklab", np.array([L0]))[0])
    C_got = float(mc.ok_L_C(210.0, s_c, v_c)[1])
    check("超限返回 None / clamp 返回 C_max 点",
          got_none is None and abs(C_got - C_pk) < 2e-6
          and abs(float(mc.lightness(210.0, s_c, v_c, "oklab")) - L0) < 1e-6,
          "None=%s clamp C=%.6f C_max=%.6f" % (got_none is None, C_got, C_pk))

    # 端点：纯黑 / 纯白 / 灰轴
    black = mc.sv_at_L_C(200.0, 0.0, 0.0)
    white = mc.sv_at_L_C(200.0, 1.0, 0.0)
    gray = mc.sv_at_L_C(200.0, 0.5, 0.0)
    check("端点与灰轴（黑/白/灰）",
          black == (0.0, 0.0) and white == (0.0, 1.0) and gray[0] == 0.0
          and abs(float(mc.lightness(200.0, gray[0], gray[1], "oklab")) - 0.5) < 1e-6,
          "黑=%s 白=%s 灰=%s" % (black, white, tuple(round(x, 5) for x in gray)))

    # 批量版与逐个一致，不可达处 NaN
    hs_arr = np.array([30.0, 60.0, 210.0, 350.0])
    ss, vv = mc.sv_at_L_C_many(hs_arr, L0, 0.30)
    one_by_one = [mc.sv_at_L_C(float(h), L0, 0.30) for h in hs_arr]
    same = True
    for i, got in enumerate(one_by_one):
        if got is None:
            same = same and bool(np.isnan(ss[i]) and np.isnan(vv[i]))
        else:
            same = same and abs(ss[i] - got[0]) < 1e-12 and abs(vv[i] - got[1]) < 1e-12
    check("sv_at_L_C_many 与逐个一致（未可达处 NaN）", same and int(np.isnan(ss).sum()) >= 1,
          "NaN 个数 %d" % int(np.isnan(ss).sum()))

    # C_max 全色相曲线 vs 精确解（cmax_exact）
    worst = 0.0
    for L in (0.2, 0.35, 0.5, 0.65, 0.8, 0.9):
        cm = mc.cmax_hue_curve(L)
        for i in range(0, 361, 17):
            worst = max(worst, abs(float(cm[i]) - float(mc.cmax_exact(
                float(i % 360), "oklab", np.array([L]))[0])))
    check("cmax_hue_curve 与 cmax_exact 偏差 < 1e-6", worst < 1e-6, "maxΔ=%.2e" % worst)

    # 可达段 ↔ 掩码逐度一致（含「2 段」用例）
    worst_bad = 0
    two_seg = mc.hue_reachable_spans(0.5, 0.20, 1.0)
    for L, C in ((0.5, 0.20), (0.6, 0.12), (0.3, 0.05), (0.4, 0.08),
                 (0.9, 0.16), (0.2, 0.02), (0.7, 0.30)):
        grid = np.arange(0.0, 360.0, 1.0)
        spans = mc.hue_reachable_spans(L, C, 1.0)
        m = np.zeros(grid.shape, dtype=bool)
        for lo, hi in spans:
            m |= ((grid - lo) % 360.0) < (hi - lo)
        worst_bad += int(np.sum(m != np.asarray(mc.hue_reachable_mask(grid, L, C))))
    check("hue_reachable_spans 与 hue_reachable_mask 逐度一致（0 差异）",
          worst_bad == 0 and len(two_seg) == 2,
          "差异 %d；L=0.5/C=0.20 段=%s" % (worst_bad,
                                       [(round(a, 1), round(b, 1)) for a, b in two_seg]))

    # 可达弧度对照盘问实测表：L=0.5 / C=0.20 -> 最长段 121°、两段共 144°
    longest = max((hi - lo) for lo, hi in two_seg)
    total = sum((hi - lo) for lo, hi in two_seg)
    check("可达弧度对照实测表（L=0.5 C=0.20：最长 121°、合计 144°）",
          abs(longest - 121.0) <= 1.0 and abs(total - 144.0) <= 1.0,
          "最长 %.1f° 合计 %.1f°" % (longest, total))

    # 数学前提：沿等明度曲线绝对彩度严格单调（抽样 12 组）
    bad_mono = 0
    for hh in (30.0, 90.0, 150.0, 210.0, 270.0, 330.0):
        for L in (0.3, 0.6):
            ss2, vv2 = mc.iso_lightness_curve(hh, L, "oklab", n_v=21, iters=20)
            carr = [float(mc.ok_L_C(hh, float(a), float(b))[1]) for a, b in zip(ss2, vv2)]
            if any(carr[i + 1] <= carr[i] for i in range(len(carr) - 1)):
                bad_mono += 1
    check("沿等明度曲线绝对 C 严格单调（12 组抽样）", bad_mono == 0, "非单调组数 %d" % bad_mono)



def test_t48_cabs():
    """T-48：绝对彩度场 / 等值线 / 固定 V 反解 S（C_abs 口径）。"""
    print("")
    print("== 10.5 绝对彩度反解与等值线（T-48）==")
    hues = (0.0, 30.0, 117.3, 200.0, 300.0)
    targets = tuple(0.04 * i for i in range(1, 10))     # 固定档位 0.04~0.36

    # 1) 固定 V 反解往返：可解行逐行 |C-target| < 1e-6
    worst = 0.0
    n_rows = 0
    for h in hues:
        v_rows = np.linspace(0.05, 0.95, 19)
        for tgt in (0.04, 0.10, 0.18, 0.30):
            s = mc.solve_s_at_cabs(h, v_rows, tgt)
            ok = np.isfinite(s)
            n_rows += int(ok.sum())
            if np.any(ok):
                c_got = np.asarray(mc.ok_L_C(h, s[ok], v_rows[ok])[1], dtype=float)
                worst = max(worst, float(np.max(np.abs(c_got - tgt))))
    check("solve_s_at_cabs 往返：C 误差 < 1e-6", n_rows > 100 and worst < 1e-6,
          "可解行 %d，maxΔC=%.2e" % (n_rows, worst))

    # 2) 不可达 -> NaN；恰好够到的行不得误判
    v_probe = np.array([0.05, 0.5, 0.95])
    hi = np.asarray(mc.ok_L_C(30.0, np.ones_like(v_probe), v_probe)[1], dtype=float)
    unreach = mc.solve_s_at_cabs(30.0, v_probe, float(np.max(hi)) + 0.02)
    edge = mc.solve_s_at_cabs(30.0, v_probe, hi * 0.999999)
    bad_unreach = [i for i in range(len(v_probe)) if not np.isnan(unreach[i])]
    check("solve_s_at_cabs 不可达返回 NaN、边界可达不误判",
          not bad_unreach and bool(np.all(np.isfinite(edge))),
          "不可达误判=%s 边界有限=%s" % (bad_unreach, np.all(np.isfinite(edge))))
    # 3) 网格布局与方向：cabs[i,j] 对应 V=ax[i]、S=ax[j]；与 ok_L_C 逐点一致
    hh = 117.3
    ax, C = mc.cabs_field(hh, n=17)
    S, V = np.meshgrid(ax, ax)
    ref = np.asarray(mc.ok_L_C(hh, S, V)[1], dtype=float)
    ref[:, 0] = 0.0
    check("cabs_field 形状 (n,n)、方向与 crel_field 一致、逐点等于 ok_L_C",
          ax.shape == (17,) and C.shape == (17, 17)
          and bool(np.array_equal(ax, np.linspace(0.0, 1.0, 17)))
          and bool(np.array_equal(C, ref)),
          "ax=%s shape=%s 一致=%s" % (ax[0], C.shape, bool(np.array_equal(C, ref))))
    mono_bad = 0
    for i in range(C.shape[0]):
        if C[i, -1] > 0.01 and np.any(np.diff(C[i, :]) < -1e-12):
            mono_bad += 1
    check("cabs_field 每行 C 随 S 单调不减（够到有意义彩度的行）", mono_bad == 0,
          "非单调行 %d" % mono_bad)

    # 4) 线簇 9 条档位值正确、每条 C 误差 < 1e-4
    worst_line = 0.0
    n_lines = n_pts = 0
    for h in hues:
        axh, Ch = mc.cabs_field(h, n=41)
        lines = mc.cabs_isoline_many(axh, Ch, targets)
        for i, (ss, vv) in enumerate(lines):
            if len(ss) < 2:
                continue
            n_lines += 1
            n_pts += len(ss)
            cc = np.asarray(mc.ok_L_C(h, ss, vv)[1], dtype=float)
            worst_line = max(worst_line, float(np.max(np.abs(cc - targets[i]))))
    check("cabs_isoline_many：每条线 C 误差 < 1e-4（5 色相 × 9 档）",
          n_lines >= 20 and worst_line < 1e-4,
          "%d 条 / %d 点，maxΔC=%.2e" % (n_lines, n_pts, worst_line))

    # 5) 过点线按 V 反解严格穿过当前色点；并由该点组成可绘折线
    s_pt, v_pt = 0.42, 0.63
    c_pt = float(mc.ok_L_C(hh, s_pt, v_pt)[1])
    s_exact = float(mc.solve_s_at_cabs(hh, np.array([v_pt]), c_pt)[0])
    check("过点线在 V=当前值 处严格穿过色点（|ΔS| < 1e-6）",
          abs(s_exact - s_pt) < 1e-6,
          "s=%.9f -> %.9f Δ=%.2e" % (s_pt, s_exact, abs(s_exact - s_pt)))

    # 6) 标量版与向量版一致（含不可达一致返回 NaN）
    worst_sc = 0.0
    sc_ok = True
    for h in hues:
        for tgt in (0.05, 0.15, 0.25):
            vv = np.array([0.15, 0.35, 0.55, 0.75, 0.9])
            sv = mc.solve_s_at_cabs(h, vv, tgt)
            for i in range(len(vv)):
                s_sc = mc.solve_s_cabs_scalar(h, float(vv[i]), tgt)
                if np.isfinite(sv[i]):
                    if not np.isfinite(s_sc):
                        sc_ok = False
                    else:
                        worst_sc = max(worst_sc, abs(float(sv[i]) - s_sc))
                elif np.isfinite(s_sc):
                    sc_ok = False
    check("solve_s_cabs_scalar 与向量版一致（不可达都返回 NaN）",
          sc_ok and worst_sc < 1e-7, "maxΔS=%.2e 一致=%s" % (worst_sc, sc_ok))

    # 7) C=0 退化：反解落在灰轴、场第 0 列严格为 0
    s_zero = mc.solve_s_at_cabs(45.0, np.array([0.2, 0.5, 0.8]), 0.0)
    s_zero_sc = mc.solve_s_cabs_scalar(45.0, 0.5, 0.0)
    check("C=0 退化：反解 S≈0（向量 + 标量；26/30 次二分的分辨率 ~1e-8）",
          float(np.max(np.abs(s_zero))) < 1e-7 and abs(s_zero_sc) < 1e-7,
          "vec max=%.2e scalar=%.2e" % (float(np.max(np.abs(s_zero))), s_zero_sc))
    check("cabs_field 灰轴（S=0 列）严格为 0",
          float(np.max(np.abs(C[:, 0]))) == 0.0,
          "max|C[:,0]|=%.2e" % float(np.max(np.abs(C[:, 0]))))

    # 7b) 完整等绝对 C 线：折线过当前色点、起点在 S=1 边、端点 C=target
    worst_pt = 0.0
    n_curve = 0
    start_s_bad = 0
    for h, s0, v0 in ((184.0, 1.0, 0.6), (120.0, 0.99, 0.4), (0.0, 1.0, 0.5),
                      (300.0, 0.5, 0.3), (45.0, 0.05, 0.9), (210.0, 0.999, 0.2)):
        c0 = float(mc.ok_L_C(h, s0, v0)[1])
        got = mc.cabs_iso_curve(h, c0, n_v=33, iters=26, v_extra=v0)
        if got is None:
            continue
        ss, vv = got
        n_curve += 1
        worst_pt = max(worst_pt, float(np.hypot(np.asarray(ss) - s0,
                                                np.asarray(vv) - v0).min()))
        if abs(float(ss[0]) - 1.0) > 1e-6:
            start_s_bad += 1
    check("cabs_iso_curve 折线严格过当前色点（含 S=1 边端点）且起点在 S=1 边",
          n_curve >= 5 and worst_pt < 1e-6 and start_s_bad == 0,
          "曲线 %d 条，过点 maxΔ=%.2e，起点异常 %d" % (n_curve, worst_pt, start_s_bad))
    ax_hi, C_hi = mc.cabs_field(117.3, n=41)
    top_hi = float(np.nanmax(C_hi))
    check("cabs_iso_curve 目标高于纯色彩度时返回 None",
          mc.cabs_iso_curve(117.3, top_hi + 0.01) is None,
          "top=%.6f" % top_hi)

    # 8) T-51：线簇档位由 cabs_cluster_targets 生成（even 9 档 / fixed 18 档）
    even_t = mc.cabs_cluster_targets(117.3, "even")
    fixed_t = mc.cabs_cluster_targets(117.3, "fixed")
    check("cabs_cluster_targets fixed = 0.02~0.36 步长 0.02（18 档）",
          len(fixed_t) == 18 and abs(fixed_t[0] - 0.02) < 1e-12
          and abs(fixed_t[-1] - 0.36) < 1e-12
          and bool(np.allclose(np.diff(fixed_t), 0.02, atol=1e-12)),
          str(fixed_t))
    top_t = float(mc.ok_L_C(117.3, 1.0, 1.0)[1])
    check("cabs_cluster_targets even = 纯色 C_max(h) 的 10%~90%（9 档）",
          len(even_t) == 9 and abs(even_t[0] - 0.1 * top_t) < 1e-12
          and abs(even_t[-1] - 0.9 * top_t) < 1e-12
          and bool(np.all(np.diff(even_t) > 0)),
          str(even_t))


def test_t51_cabs_clusters():
    """T-51：绝对 C 线簇两档密度（even 任意色相 9 条 / fixed 18 档更密）。"""
    print("")
    print("== 10.6 绝对 C 线簇密度（T-51）==")
    hues = (0.0, 26.0, 60.0, 120.0, 180.0, 240.0, 300.0, 359.0)
    worst_even = 0.0
    min_even = 99
    visible_fixed = []
    visible_old = []
    f_ok = e_ok = True
    for h in hues:
        t_even = np.asarray(mc.cabs_cluster_targets(h, "even"), dtype=float)
        top = float(mc.ok_L_C(h, 1.0, 1.0)[1])
        if not (len(t_even) == 9 and abs(t_even[-1] - 0.9 * top) < 1e-12):
            e_ok = False
        ax, cg = mc.cabs_field(h, n=41)
        lines = mc.cabs_isoline_many(ax, cg, t_even)
        n_vis = sum(1 for ss, _vv in lines if len(ss) >= 2)
        min_even = min(min_even, n_vis)
        for i, (ss, vv) in enumerate(lines):
            if len(ss) < 2:
                continue
            cc = np.asarray(mc.ok_L_C(h, ss, vv)[1], dtype=float)
            worst_even = max(worst_even, float(np.max(np.abs(cc - t_even[i]))))
            if mc.cabs_iso_curve(h, float(t_even[i]), n_v=33, iters=26) is None:
                e_ok = False
        t_fixed = np.asarray(mc.cabs_cluster_targets(h, "fixed"), dtype=float)
        if not (len(t_fixed) == 18 and bool(np.allclose(np.diff(t_fixed), 0.02))):
            f_ok = False
        lines_f = mc.cabs_isoline_many(ax, cg, t_fixed)
        visible_fixed.append(sum(1 for ss, _vv in lines_f if len(ss) >= 2))
        t_old = np.asarray([0.04 * i for i in range(1, 10)], dtype=float)
        lines_o = mc.cabs_isoline_many(ax, cg, t_old)
        visible_old.append(sum(1 for ss, _vv in lines_o if len(ss) >= 2))
    check("even：8 色相 × 9 档全部存在、可见 9 条、每条 C 误差 < 1e-4",
          e_ok and min_even == 9 and worst_even < 1e-4,
          "最少可见 %d 条，maxΔC=%.2e" % (min_even, worst_even))
    check("fixed：8 色相档位都是 0.02~0.36 共 18 档", f_ok, str(visible_fixed))
    check("fixed(0.02) 可见条数 ≥ 旧 0.04 档，且最密时明显更多",
          all(a >= b for a, b in zip(visible_fixed, visible_old))
          and max(visible_fixed) >= 10 and max(visible_fixed) > max(visible_old),
          "fixed=%s old04=%s" % (visible_fixed, visible_old))


def test_reachable_hue():
    print("")
    print("== 11. 最近可达边界与锁相对彩度求色 ==")
    def ang(a, b):
        return abs(((float(a) - float(b)) + 180.0) % 360.0 - 180.0)
    L0, C0 = (float(x) for x in mc.ok_L_C(30.0, 0.90, 0.95))
    hs = [0.0, 30.0, 90.0, 157.0, 160.0, 262.0, 270.0]
    same = all(mc.hue_is_reachable(h, L0, C0)
               == bool(mc.hue_reachable_mask(np.array([h]), L0, C0)[0]) for h in hs)
    check("hue_is_reachable 与 hue_reachable_mask 口径一致", same)

    grid = np.arange(0.0, 360.0, 0.1)
    mask = np.asarray(mc.hue_reachable_mask(grid, L0, C0), dtype=bool)
    worst = 0.0
    for tgt in (0.0, 20.0, 40.0, 160.0, 200.0, 260.0, 300.0, 355.0):
        got = mc.nearest_reachable_hue(tgt, L0, C0)
        if got is None or not mc.hue_is_reachable(got, L0, C0):
            worst = 9.0
            break
        dist = np.abs(((grid - tgt) + 180.0) % 360.0 - 180.0)
        brute = float(np.min(dist[mask]))
        worst = max(worst, abs(ang(got, tgt) - brute))
    check("nearest_reachable_hue 返回可达点且到边界距离最小（≤ 0.1°）",
          worst <= 0.1, "最大偏离 %.4f°" % worst)

    check("nearest_reachable_hue 全可达返回原值",
          mc.nearest_reachable_hue(123.4, L0, 1e-9) == 123.4)
    check("nearest_reachable_hue 全不可达返回 None",
          mc.nearest_reachable_hue(10.0, 1.0, 0.5) is None)

    worst_l = worst_c = 0.0
    for h in (20.0, 90.0, 200.0, 300.0):
        for crel in (0.1, 0.5, 0.95):
            got = mc.sv_at_L_crel(h, L0, crel)
            if got is None:
                worst_l = 9.0
                break
            worst_l = max(worst_l, abs(float(mc.lightness(h, got[0], got[1], "oklab")) - L0))
            worst_c = max(worst_c, abs(float(mc.crel_of_xyz(h, "oklab", got[0], got[1])[0]) - crel))
    check("sv_at_L_crel 回读：L 与 C_rel 误差 < 1e-6", worst_l < 1e-6 and worst_c < 1e-6,
          "maxΔL=%.2e maxΔC_rel=%.2e" % (worst_l, worst_c))


def test_gray_metric():
    """R22 灰阶口径（metric="gray"）：定义互逆、往返、C_rel 自洽、边界可达。"""
    print("\n== 13. 灰阶口径（明度标准 = gray）==")
    rng = np.random.default_rng(20260926)
    cases = [(0.0, 1.0, 1.0), (180.0, 0.5, 0.5), (210.0, 0.62, 0.86), (30.0, 0.0, 0.4)]
    cases += [(float(rng.random() * 360.0), float(rng.random()), float(rng.random()))
              for _ in range(200)]
    worst_def = worst_axis = worst_scalar = worst_okc = 0.0
    ysum = 0.2126729 + 0.7151522 + 0.0721750
    for h, s, v in cases:
        lin = mc.srgb_to_linear(mc.hsv_to_srgb(h, s, v))
        y = (0.2126729 * lin[0] + 0.7151522 * lin[1] + 0.0721750 * lin[2]) / ysum
        worst_def = max(worst_def, abs(float(mc.lightness(h, s, v, "gray"))
                                       - float(mc._srgb_encode(y))))
        g_sc, c_sc = mc._gray_lc_py(h, s, v)
        worst_scalar = max(worst_scalar,
                           abs(g_sc - float(mc.lightness(h, s, v, "gray"))),
                           abs(c_sc - float(mc.ok_L_C(h, s, v)[1])))
        # 彩度仍是 Oklab C，与明度标准无关：ok_L_C 的 L/C 不应变
        worst_okc = max(worst_okc, abs(float(mc.ok_L_C(h, s, v)[1]) - c_sc))
    for v in np.linspace(0.0, 1.0, 501):
        worst_axis = max(worst_axis, abs(float(mc.lightness(0.0, 0.0, float(v), "gray")) - v))
    check("gray 灰阶码值 = srgb_encode(Y)（独立重算）", worst_def < 1e-12,
          "maxΔ=%.2e" % worst_def)
    check("gray 灰轴 L == V（0~1 全量程）", worst_axis < 1e-12, "maxΔ=%.2e" % worst_axis)
    inv = max(abs(float(mc.v_from_lightness("gray", np.array([t]))[0]) - t)
              for t in np.linspace(0.0, 1.0, 101))
    check("v_from_lightness(gray) 与 lightness(gray) 互逆", inv < 1e-12, "maxΔ=%.2e" % inv)
    check("_gray_lc_py 与 lightness(gray)/ok_L_C 同口径（C 仍是 Oklab C）",
          worst_scalar < 1e-12, "maxΔ=%.2e" % worst_scalar)

    worst_rt = worst_rel = 0.0
    for h in (20.0, 140.0, 260.0, 340.0):
        for L0 in (0.2, 0.5, 0.8):
            cmax = float(np.asarray(mc.cmax_of_L(h, "gray", np.array([L0])))[0])
            for frac in (0.0, 0.25, 0.5, 0.85, 1.0):
                got = mc.sv_at_L_C(h, L0, frac * cmax, metric="gray")
                if got is None:
                    worst_rt = 9.0
                    continue
                s2, v2 = got
                worst_rt = max(worst_rt,
                               abs(float(mc.lightness(h, s2, v2, "gray")) - L0),
                               abs(float(mc.ok_L_C(h, s2, v2)[1]) - frac * cmax))
            for crel in (0.1, 0.5, 0.95):
                got = mc.sv_at_L_crel(h, L0, crel, metric="gray")
                if got is None:
                    worst_rel = 9.0
                    continue
                s2, v2 = got
                worst_rel = max(worst_rel,
                                abs(float(mc.lightness(h, s2, v2, "gray")) - L0),
                                abs(float(mc.crel_of_xyz(h, "gray", s2, v2)[0]) - crel))
    check("sv_at_L_C(gray) 往返 L / C（含取满 C_max）", worst_rt < 1e-6,
          "maxΔ=%.2e" % worst_rt)
    check("sv_at_L_crel(gray) 往返 L / C_rel", worst_rel < 1e-6, "maxΔ=%.2e" % worst_rel)

    worst_curve = 0.0
    for L0 in (0.2, 0.5, 0.8):
        curve = mc.cmax_hue_curve(L0, metric="gray")
        for i, h in enumerate(np.arange(0.0, 361.0, 1.0)):
            worst_curve = max(worst_curve,
                              abs(float(curve[i]) - float(np.asarray(
                                  mc.cmax_exact(float(h), "gray", L0)))))
    check("gray cmax_hue_curve 与 cmax_exact 偏差 < 1e-6", worst_curve < 1e-6,
          "maxΔ=%.2e" % worst_curve)

    miss = []
    for L0 in (0.2, 0.4, 0.6, 0.8):
        for h in np.arange(0.0, 360.0, 10.0):
            cmax = float(np.asarray(mc.cmax_of_L(float(h), "gray", np.array([L0])))[0])
            if mc.sv_at_L_C(float(h), L0, cmax, metric="gray") is None:
                miss.append((L0, float(h)))
    check("gray C_rel=1 取满 C_max 时 36 色相全可达（边界 bug 修复保留）", not miss,
          "不可达 %d 个 %s" % (len(miss), miss[:4]))

    diff = 0
    for L0, C0 in ((0.5, 0.08), (0.3, 0.12), (0.7, 0.05)):
        spans = mc.hue_reachable_spans(L0, C0, 1.0, metric="gray")
        grid = np.arange(0.0, 360.0, 1.0)
        m = np.asarray(mc.hue_reachable_mask(grid, L0, C0, metric="gray"), dtype=bool)
        cov = np.zeros(len(grid), dtype=bool)
        for lo, hi in spans:
            for i, hh in enumerate(grid):
                if (hh - lo) % 360.0 <= (hi - lo) + 1e-9:
                    cov[i] = True
        diff += int(np.sum(m != cov))
    check("gray hue_reachable_spans 与 hue_reachable_mask 逐度一致", diff == 0,
          "差异 %d/1080" % diff)


def test_gray_ab_slice_fixes():
    """gray a/b 退化切片、可达判定多采样细化、单次调用耗时。"""
    print("\n== 14. gray a/b 切片与可达区间 ==")

    # ---- oklab 旧路径原样不动；gray 路径用 seed 精确版 -----------------------
    hues = np.arange(0.0, 360.0, 10.0)
    vs = np.linspace(0.1, 1.0, 10)
    n_pairs = fixed = ex_none = seed_out = 0
    for h in hues:
        for v in vs:
            L, a, b = (float(x) for x in mc.oklab_ab(h, 1.0, v))
            for axis, other, x0 in (("a", b, a), ("b", a, b)):
                old = mc.ab_axis_interval(L, other, axis)         # oklab 旧路径
                ex = mc.ab_axis_interval_exact(L, other, axis, seed=x0)
                n_pairs += 1
                if ex is None:
                    ex_none += 1
                    continue
                if not (ex[0] - 1e-9 <= x0 <= ex[1] + 1e-9):
                    seed_out += 1
                if old == (0.0, 0.0) and not (abs(ex[0]) < 1e-12 and abs(ex[1]) < 1e-12):
                    fixed += 1
    check("h×v 网格（36×10）精确切片无空、种子必在区间内",
          n_pairs == 720 and ex_none == 0 and seed_out == 0,
          "pairs=%d empty=%d seed外=%d" % (n_pairs, ex_none, seed_out))
    check("旧 [0,0] 哨兵退化切片被真实区间修复（含 h=60°,v=1）",
          fixed > 0, "修复 %d/%d 个输出" % (fixed, n_pairs))
    L60, a60, b60 = (float(x) for x in mc.oklab_ab(60.0, 1.0, 1.0))
    old60 = mc.ab_axis_interval(L60, b60, "a")
    ex60 = mc.ab_axis_interval_exact(L60, b60, "a", seed=a60)
    check("退化切片返回真实切点区间（不再把值钳到 0）",
          old60 == (0.0, 0.0) and ex60 is not None
          and ex60[0] - 1e-12 <= a60 <= ex60[1] + 1e-12
          and (ex60[1] - ex60[0]) < 1e-3,
          "old=%s exact=[%+.9f,%+.9f] a0=%+.9f 宽=%.2e"
          % (old60, ex60[0], ex60[1], a60, ex60[1] - ex60[0]))
    check("真空切片显式返回 None",
          mc.ab_axis_interval_exact(1.2, 0.0, "a", seed=0.0) is None)

    # seeded 口径 = gray 路径实际用的：旧区间含 x0 原样保留，否则 seed 精确区间
    Ln, an, bn = (float(x) for x in mc.oklab_ab(210.0, 0.62, 0.86))
    old_n = mc.ab_axis_interval(Ln, bn, "a")
    seeded_n = mc.ab_axis_interval_seeded(Ln, bn, "a", seed=an)
    check("seeded：旧区间含当前分量时逐位保持旧行为", seeded_n == old_n,
          "old=%s seeded=%s" % (old_n, seeded_n))
    seeded_60 = mc.ab_axis_interval_seeded(L60, b60, "a", seed=a60)
    check("seeded：h=60°,v=1 不再返回 [0,0]，且区间含当前分量",
          seeded_60 is not None and seeded_60 != (0.0, 0.0)
          and seeded_60[0] - 1e-9 <= a60 <= seeded_60[1] + 1e-9,
          "[%+.9f,%+.9f]" % seeded_60)
    L240, a240, b240 = (float(x) for x in mc.oklab_ab(240.0, 1.0, 1.0))
    old240 = mc.ab_axis_interval(L240, a240, "b")
    seeded_240 = mc.ab_axis_interval_seeded(L240, a240, "b", seed=b240)
    check("seeded：旧区间不含当前分量（双岛切片）时返回含 seed 的连通区间",
          not (old240[0] - 1e-9 <= b240 <= old240[1] + 1e-9)
          and seeded_240 is not None
          and seeded_240[0] - 1e-9 <= b240 <= seeded_240[1] + 1e-9,
          "old=%s seeded=[%+.6f,%+.6f] b0=%+.6f"
          % (old240, seeded_240[0], seeded_240[1], b240))

    # ---- 多采样 min/max + 极值细化；32769 点密集采样复核 ---------------------
    tol = 1e-3                         # 假不可达容差（分量单位；全量程 0.9 的 0.11%）
    dense = np.linspace(0.0, 1.0, 32769)

    def dense_ok(axis, other, target, x):
        if axis == "a":
            g = mc.gray_from_oklab(dense, np.full_like(dense, x), np.full_like(dense, other))
        else:
            g = mc.gray_from_oklab(dense, np.full_like(dense, other), np.full_like(dense, x))
        return bool(g.min() - 1e-11 <= target <= g.max() + 1e-11)

    worst_py = worst_rt = 0.0
    rng = np.random.default_rng(20260926)
    for _ in range(200):
        h = float(rng.random() * 360.0)
        s = float(rng.random())
        v = float(rng.random())
        L, a, b = (float(x) for x in mc.oklab_ab(h, s, v))
        worst_py = max(worst_py, abs(mc.gray_from_oklab_py(L, a, b)
                                     - float(mc.gray_from_oklab(L, a, b))))
        rgb = mc.oklab_to_srgb(L, a, b)
        ref = float(mc.lightness(*[float(x) for x in mc.srgb_to_hsv(
            float(rgb[0]), float(rgb[1]), float(rgb[2]))], metric="gray"))
        worst_rt = max(worst_rt, abs(mc.gray_from_oklab_py(L, a, b) - ref))
    check("标量灰阶快路径 == 向量化版 == 旧 sRGB 往返口径",
          worst_py < 1e-14 and worst_rt < 1e-13,
          "maxΔ(向量)=%.2e maxΔ(往返)=%.2e" % (worst_py, worst_rt))

    scan_pairs = scan_empty = false_pos = false_neg = 0
    combos = ((1.0, 0.2), (1.0, 0.6), (0.5, 1.0), (0.8, 0.9))
    t0 = time.perf_counter()
    for h in hues:
        for s, v in combos:
            L, a, b = (float(x) for x in mc.oklab_ab(h, s, v))
            target = float(mc.gray_from_oklab(L, a, b))
            for axis, other, x0 in (("a", b, a), ("b", a, b)):
                iv = mc.gray_component_interval(axis, other, target, x0, l_hint=L)
                scan_pairs += 1
                if iv is None:
                    scan_empty += 1
                    continue
                for x in (iv[0], 0.5 * (iv[0] + iv[1]), iv[1]):
                    if not dense_ok(axis, other, target, x):
                        false_pos += 1
                if iv[1] + tol < 0.45 and dense_ok(axis, other, target, iv[1] + tol):
                    false_neg += 1
                if iv[0] - tol > -0.45 and dense_ok(axis, other, target, iv[0] - tol):
                    false_neg += 1
    scan_dt = time.perf_counter() - t0
    check("36 色相 × 4 档扫描：假可达 0、假不可达 0（容差 1e-3）",
          scan_empty == 0 and false_pos == 0 and false_neg == 0,
          "pairs=%d empty=%d 假可达=%d 假不可达=%d 耗时=%.2fs"
          % (scan_pairs, scan_empty, false_pos, false_neg, scan_dt))

    # ---- 单次区间调用耗时 + 灰阶求解残差 ------------------------------------
    times = []
    for _ in range(60):
        h = float(rng.random() * 360.0)
        s = float(rng.random())
        v = float(rng.random())
        L, a, b = (float(x) for x in mc.oklab_ab(h, s, v))
        target = float(mc.gray_from_oklab(L, a, b))
        axis = "a" if rng.random() < 0.5 else "b"
        other, x0 = (b, a) if axis == "a" else (a, b)
        t0 = time.perf_counter()
        mc.gray_component_interval(axis, other, target, x0, l_hint=L)
        times.append((time.perf_counter() - t0) * 1000.0)
    times.sort()
    med = times[len(times) // 2]
    check("gray 可达区间单次调用 < 5ms（系统 Python 参考）",
          med < 5.0, "中位 %.3fms 均值 %.3fms 最大 %.3fms"
          % (med, sum(times) / len(times), times[-1]))

    worst_solve = 0.0
    for _ in range(300):
        h = float(rng.random() * 360.0)
        s = float(rng.random())
        v = float(rng.random())
        L, a, b = (float(x) for x in mc.oklab_ab(h, s, v))
        target = float(mc.gray_from_oklab_py(L, a, b))
        Ls = mc.solve_ab_L_for_gray(target, a, b)
        worst_solve = max(worst_solve,
                          abs(mc.gray_from_oklab_py(Ls, a, b) - target))
    check("solve_ab_L_for_gray 灰阶残差 < 1e-9", worst_solve < 1e-9,
          "maxΔ=%.2e" % worst_solve)


def test_perf():
    print("\n== 9. 性能（系统 Python 3.12 + numpy 2.3.0，仅供参考）==")
    def bench(fn, n=5, warm=2):
        for _ in range(warm):
            fn()
        t0 = time.perf_counter()
        for _ in range(n):
            fn()
        return (time.perf_counter() - t0) / n * 1000.0

    t_curve = bench(lambda: mc.iso_lightness_curve(123.4, 0.5, "oklab"))
    print("      iso_lightness_curve 单条        = %6.2f ms" % t_curve)
    t_cluster = bench(lambda: mc.iso_lightness_curves(123.4, [0.1 * i for i in range(1, 10)], "oklab"), n=3)
    print("      iso_cluster 9 条                = %6.2f ms" % t_cluster)
    t_field = bench(lambda: mc.crel_field(123.4, "oklab", n=41), n=10)
    print("      crel_field(41)                  = %6.2f ms" % t_field)
    t_cmax = bench(lambda: mc.cmax_of_L(87.6, "oklab", 0.5), n=20)
    print("      cmax_of_L(新色相,建表)          = %6.2f ms" % t_cmax)
    ax, rel = mc.crel_field(123.4, "oklab", n=41)
    t_iso = bench(lambda: mc.crel_isoline_through(123.4, "oklab", ax, rel, 0.7, 0.8),
                 n=1, warm=1)
    print("      crel_isoline_through(含一次性建场) = %6.2f ms" % t_iso)
    ss_p, vv_p = mc.iso_lightness_curve(123.4, 0.5, "oklab")
    t_strip = bench(lambda: mc.strip_image(123.4, ss_p, vv_p, "arc", 24, 240), n=10)
    print("      strip_image(24x240)             = %6.2f ms" % t_strip)
    check("数学层单帧预算（簇+场+过点线）< 30ms",
          t_cluster + t_field + t_iso < 30.0, "合计 %.2f ms" % (t_cluster + t_field + t_iso))


def main():
    print("=== math_core 回归自检（Krita 版）===")
    print("python = %s" % sys.version.replace("\n", " "))
    print("numpy  = %s" % np.__version__)
    for fn in (test_color_math, test_hsv_roundtrip, test_iso_curve, test_curves_utils,
               test_crel, test_oklab_ab, test_lbar, test_parse, test_strip, test_isoline_append_guard,
               test_v_from_lightness,
               test_abs_chroma, test_t48_cabs, test_t51_cabs_clusters,
               test_reachable_hue, test_gray_metric,
               test_gray_ab_slice_fixes, test_perf):
        try:
            fn()
        except Exception:
            FAIL.append(fn.__name__)
            print("[FAIL] %s 抛异常:\n%s" % (fn.__name__, traceback.format_exc()))
    print("\n" + "=" * 60)
    print("通过 %d 项，失败 %d 项" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败清单：%s" % "、".join(FAIL))
        print("结论：存在失败 ❌")
        return 1
    print("结论：全部通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
