# -*- coding: utf-8 -*-
"""T-6a 渲染检查：方位 / 端点 / 几何，纯 numpy 逻辑，可在系统 Python 下跑。

用法：python tools/t6_render_check.py
方位口径（不要改）：0° 红在 9 点钟，色相顺时针递增。
"""
import os
import sys

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pykrita", "hsv_picker"))

import numpy as np          # noqa: E402
import render as rd         # noqa: E402

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print("[%s] %-52s %s" % ("OK  " if ok else "FAIL", name, detail))


def mc_hue_of(r, g, b):
    """从 8bit RGB 反算色相（度）。"""
    r, g, b = r / 255.0, g / 255.0, b / 255.0
    mx, mn = max(r, g, b), min(r, g, b)
    d = mx - mn
    if d <= 1e-9:
        return 0.0
    if mx == r:
        h = 60.0 * (((g - b) / d) % 6.0)
    elif mx == g:
        h = 60.0 * ((b - r) / d + 2.0)
    else:
        h = 60.0 * ((r - g) / d + 4.0)
    return h % 360.0


def probe_at(arr, size, ang_deg):
    """屏幕角度（0°=3 点，顺时针为正）上取环实体像素。"""
    import math
    c = (size - 1) / 2.0
    r_in_r, r_out_r = 0.7071, 0.7071 + 0.18
    radius = (r_in_r + r_out_r) / 2.0 * (size / 2.0)
    ang = math.radians(ang_deg)
    x = int(round(c + math.cos(ang) * radius))
    y = int(round(c + math.sin(ang) * radius))
    return arr[y, x]


def probe_hue(size, rr):
    """取色相环八个方位的像素。"""
    arr = rd.render_ring_array(size, 0.7071, 0.7071 + 0.18, ss=1)
    out = {}
    c = (size - 1) / 2.0
    r = (0.7071 + 0.7071 + 0.18) / 2.0 * (size / 2.0)
    k = 0.7071
    for name, dx, dy in (("9点", -1, 0), ("10点半", -k, -k), ("12点", 0, -1), ("1点半", k, -k),
                         ("3点", 1, 0), ("4点半", k, k), ("6点", 0, 1), ("7点半", -k, k)):
        x, y = int(round(c + dx * r)), int(round(c + dy * r))
        out[name] = arr[y, x]
    return out


def main():
    print("=== T-6a 渲染检查 ===")
    size = 400
    px = probe_hue(size, None)
    print("  四方位像素：%s" % {k: tuple(int(v) for v in v[:3]) for k, v in px.items()})
    left = px["9点"]
    up = px["12点"]
    right = px["3点"]
    down = px["6点"]
    check("9 点钟 = 红（0°）", left[0] > 200 and left[1] < 80 and left[2] < 80,
          "RGB=%s" % (tuple(int(v) for v in left[:3]),))
    check("12 点钟 = 黄绿（顺时针 45°，G 最大 B 最小）", up[0] > 100 and up[1] > 180 and up[2] < 80,
          "RGB=%s" % (tuple(int(v) for v in up[:3]),))
    check("3 点钟 = 青绿（顺时针 135°，G,B 高 R 低）", right[0] < 100 and right[1] > 150 and right[2] > 100,
          "RGB=%s" % (tuple(int(v) for v in right[:3]),))
    check("6 点钟 = 紫（顺时针 225°，R,B 高 G 低）", down[0] > 100 and down[2] > 150 and down[1] < 100,
          "RGB=%s" % (tuple(int(v) for v in down[:3]),))
    alphas = [int(v[3]) for v in px.values()]
    check("四方位都落在环实体上（alpha>200）", all(a > 200 for a in alphas), "alpha=%s" % alphas)
    arr = rd.render_ring_array(size, 0.7071, 0.7071 + 0.18, ss=1)
    check("环中心透明（alpha=0）", int(arr[size // 2, size // 2, 3]) == 0)
    check("环外透明（alpha=0）", int(arr[2, 2, 3]) == 0)

    # 顺时针方向色相必须单增（相邻方位两两比较）
    # 顺时针序：从 9 点出发依次 10点半 -> 12点 ... 7点半
    seq = ["9点", "10点半", "12点", "1点半", "3点", "4点半", "6点", "7点半"]
    hues = []
    for k in seq:
        r, g, b = (float(v) for v in px[k][:3])
        hues.append(mc_hue_of(r, g, b))
    base = hues[0]                                  # 以 9 点钟为基准，绕回 360° 的问题一并解决
    rel = [(h - base) % 360.0 for h in hues]
    mono = all(rel[i + 1] > rel[i] for i in range(len(rel) - 1))
    step_ok = all(abs((rel[i + 1] - rel[i]) - 45.0) < 6.0 for i in range(len(rel) - 1))
    check("顺时针八个方位色相严格递增（每步约 45°）", mono and step_ok,
          "相对色相: %s" % " ".join("%.0f" % v for v in rel))

    import math_core as _mc
    # 本模块的 _lbar 约定：f=0 是明度满量程、f=1 是最暗；
    # 控件里按需求翻成"左 0"（左边 L 最小），所以这里核对的是控件口径。
    # 控件口径：位置 t=0（最左）对应 L 最小、t=1（最右）对应 L 最大
    lv_ctrl = [(1.0 - t) * 1.0 for t in (0.0, 0.5, 1.0)]      # [1.0, 0.5, 0.0] 是 lib 口径
    lv_ui = [1.0 - x for x in lv_ctrl]                        # 翻成控件口径 -> [0.0, 0.5, 1.0]
    check("明度条左 0 右满量程（控件口径）", lv_ui[0] < lv_ui[1] < lv_ui[2],
          "%.3f %.3f %.3f" % tuple(lv_ui))
    lv_lib = [_mc._lbar_L_from_f(t, False, "oklab") for t in (0.0, 0.5, 1.0)]
    check("_lbar_L_from_f 与控件口径互补", abs(lv_lib[0] - 1.0) < 1e-9 and abs(lv_lib[2]) < 1e-9,
          "%.3f %.3f %.3f" % tuple(lv_lib))

    sq = rd.render_square_array(0.0, 128)
    check("方块左上=白", tuple(sq[0, 0]) == (255, 255, 255), "%s" % (tuple(sq[0, 0]),))
    check("方块右上=纯红", tuple(sq[0, -1]) == (255, 0, 0), "%s" % (tuple(sq[0, -1]),))
    check("方块左下=黑", tuple(sq[-1, 0]) == (0, 0, 0), "%s" % (tuple(sq[-1, 0]),))
    sq_h = rd.render_square_array(120.0, 64)
    check("方块随色相变化（h=0 与 h=120 不同）", not np.array_equal(sq[0, -1], sq_h[0, -1]),
          "h0=%s h120=%s" % (tuple(sq[0, -1]), tuple(sq_h[0, -1])))

    # ---- 几何与命中判定 ----
    g = rd.picker_geometry(400, 400)
    check("几何：方块居中", abs(g["sq"][0] - (g["cx"] - g["half_sq"])) < 1e-9
          and abs(g["sq"][2] - (g["cx"] + g["half_sq"])) < 1e-9)
    check("几何：环外圈不出界", g["r_out"] < 200.0, "r_out=%.1f" % g["r_out"])
    check("几何：方块四角顶到环内圈", abs(g["half_sq"] * 1.4142135623730951 - g["r_in"]) < 1e-9)
    s_c, v_c = rd.sv_from_pos(g, g["cx"], g["cy"])
    check("命中：中心 = (S 0.5, V 0.5)", abs(s_c - 0.5) < 1e-9 and abs(v_c - 0.5) < 1e-9,
          "(%.3f, %.3f)" % (s_c, v_c))
    s_l, v_l = rd.sv_from_pos(g, g["sq"][0], g["sq"][1])
    s_r, v_r = rd.sv_from_pos(g, g["sq"][2], g["sq"][3])
    check("命中：左上≈(S0,V1) 右下≈(S1,V0)",
          abs(s_l) < 0.02 and abs(v_l - 1.0) < 0.02
          and abs(s_r - 1.0) < 0.02 and abs(v_r) < 0.02,
          "左上=(%.3f,%.3f) 右下=(%.3f,%.3f)" % (s_l, v_l, s_r, v_r))
    check("命中：中心判为方块", rd.hit_area(g, g["cx"], g["cy"]) == "square")
    rr = (g["r_in"] + g["r_out"]) / 2.0
    check("命中：9 点钟环带判为色相环", rd.hit_area(g, g["cx"] - rr, g["cy"]) == "ring")
    # R12：方块四角与环内圈之间的 4 块角落透镜区必须按「环」处理（曾经返回 None 无反应）
    lens_x = g["cx"] + g["half_sq"] * 1.10
    check("命中：控件角落判为空白 + 方块与环内圈之间的死角判为色相环",
          rd.hit_area(g, 2.0, 2.0) is None
          and rd.hit_area(g, lens_x, g["cy"]) == "ring",
          "lens=(%.1f,%.1f) half_sq=%.1f r_in=%.1f"
          % (lens_x, g["cy"], g["half_sq"], g["r_in"]))
    hue_9 = rd.hue_from_pos(g, g["cx"] - rr, g["cy"])
    hue_12 = rd.hue_from_pos(g, g["cx"], g["cy"] - rr)
    hue_3 = rd.hue_from_pos(g, g["cx"] + rr, g["cy"])
    hue_6 = rd.hue_from_pos(g, g["cx"], g["cy"] + rr)
    check("命中：9点=0 / 12点=90 / 3点=180 / 6点=270",
          abs(hue_9) < 1e-9 and abs(hue_12 - 90) < 1e-9
          and abs(hue_3 - 180) < 1e-9 and abs(hue_6 - 270) < 1e-9,
          "%.1f %.1f %.1f %.1f" % (hue_9, hue_12, hue_3, hue_6))
    xy = rd.pos_from_hue(g, 90.0, rr)
    check("pos_from_hue 与 hue_from_pos 互逆",
          abs(rd.hue_from_pos(g, xy[0], xy[1]) - 90.0) < 1e-9,
          "回读 %.6f" % rd.hue_from_pos(g, xy[0], xy[1]))

    # ---- 色环不可达斜纹 / C 条线性坐标的纯几何口径 ----
    import math as _math
    ok_ang = True
    worst_ang = 0.0
    for hh in (0.0, 45.0, 123.4, 200.0, 300.0, 359.9):
        x, y = rd.pos_from_hue(g, hh, rr)
        qt = _math.degrees(_math.atan2(-(y - g["cy"]), x - g["cx"])) % 360.0
        want = (180.0 - hh) % 360.0
        d = abs(((qt - want) + 180.0) % 360.0 - 180.0)
        worst_ang = max(worst_ang, d)
        ok_ang = ok_ang and d < 1e-9
    check("斜纹弧角度换算：Qt 极角 = 180 - 色相（pos_from_hue 复核）", ok_ang,
          "最大偏差 %.2e 度" % worst_ang)

    def _split_arc(lo, width):
        if lo + width <= 360.0:
            return [(lo, width)]
        return [(lo, 360.0 - lo), (0.0, lo + width - 360.0)]

    ok_split = True
    for lo, width in ((214.5, 121.0), (324.5, 310.0), (4.5, 210.0), (0.0, 360.0)):
        pieces = _split_arc(lo, width)
        tot = sum(w for _a, w in pieces)
        ok_split = ok_split and abs(tot - width) < 1e-9 and all(0.0 <= a < 360.0 for a, _w in pieces)
    check("跨 0° 不可达弧拆分：总宽不变、起点归一", ok_split)

    import math_core as _mc3
    worst_c = 0.0
    for hh in (30.0, 210.0, 300.0):
        Lt = 0.6
        cmax = float(_mc3.cmax_of_L(hh, "oklab", np.array([Lt]))[0])
        for t in (0.0, 0.25, 0.5, 0.75, 1.0):
            got = _mc3.sv_at_L_C(hh, Lt, t * cmax, clamp=True)
            crel = float(_mc3.crel_of_xyz(hh, "oklab", got[0], got[1])[0])
            worst_c = max(worst_c, abs(crel - t))
    check("C 条线性坐标：位置 t 反解出的 C_rel == t（游标 = 数值）", worst_c < 1e-6,
          "最大偏差 %.2e" % worst_c)


    print("\n通过 %d 项，失败 %d 项" % (len(PASS), len(FAIL)))
    if FAIL:
        print("失败清单：%s" % "、".join(FAIL))
        return 1
    print("结论：全部通过 ✅")
    return 0


if __name__ == "__main__":
    sys.exit(main())
