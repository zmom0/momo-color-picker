# -*- coding: utf-8 -*-
"""色相环 3 种操作模式 —— 效果对比图（离线渲染 PNG，不进插件）。

目的：在改「色相环默认动作」之前，先看 3 种模式沿色相转一圈到底长什么样。

3 种模式（与 keymap_core 的 ring 动作一一对应）：
  · hue_hsv        纯 HSV：只改色相，保持 S / V 不变
  · hue_lock_lc_abs 锁明度 + 锁绝对彩度 C
  · hue_lock_lc_rel 锁明度 + 锁相对彩度 C_rel

渲染口径：
  · 色相环上取 36 个采样点（每 10°）
  · **不可达的采样点跳过**（画成空档，便于一眼看出"能转多远"）
  · 每个模式四行：① 颜色条 ② 明度图（灰阶 = Oklab L）③ Krita 软打样灰图 ④ 彩度图（灰阶 = 绝对 C / C_MAX）
  · 多组不同明度：起色固定 h=0°，S0 固定，二分 V 得到目标 L0

用法：
    python tools/preview_ring_modes.py                 # 生成 PNG
    python tools/preview_ring_modes.py --check         # 只跑数学自检，不画图
    python tools/preview_ring_modes.py --metric gray   # 明度标准换成灰阶（默认 oklab）
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pykrita" / "hsv_picker"))
import math_core as mc                                     # noqa: E402

M = "oklab"
N_SAMPLE = 36                       # 每 10°
H_START = 0.0                       # 起色色相（红）
S_START = 0.80                      # 起色饱和度
L_TARGETS = (0.35, 0.50, 0.65, 0.80)
CREL_PLOT = 0.60                    # 起色的相对彩度（典型作画色）
C_MAX_PLOT = 0.34                   # 彩度图归一化上限（≈ sRGB 全域 Oklab C 上限 0.3217）

CELL_W, CELL_H = 22, 22             # 采样格
LBL_W = 150                         # 左侧标签宽
PAD = 14
BG = (34, 34, 38)
FG = (232, 232, 236)
DIM = (150, 150, 156)
GAP = (26, 26, 30)                  # 不可达空档
SC = 2                              # 超采样（画完缩一半，字更清楚）

# --badges 与 --no-labels 同用时只画语言中性的数字徽标，不画任何说明文字：
#   · 每个模式块左侧 1/2/3（纯 HSV / 锁绝对彩度 / 锁相对彩度）；
#   · 第一组（最上面的明度组）每一行左侧 1~4（颜色 / Oklab L 灰 / Krita 灰阶 / 绝对彩度灰）；
#   · 组与组之间留更大间隔并画一条分隔线。
BADGES = False
BADGE_W = 36                        # 左侧编号列宽（模式号圆徽 + 行号）
MODE_GAP = 6                        # 有徽标时模式块之间的间隔
GROUP_GAP = 24                      # 有徽标时明度组之间的间隔
BADGE_BG = (232, 232, 236)
BADGE_FG = (34, 34, 38)
ROW_NUM_FG = (205, 205, 210)
SEP_COL = (86, 86, 96)

MODES = (
    ("hue_hsv", "纯 HSV（S/V 不变）"),
    ("hue_lock_lc_abs", "锁明度 + 锁绝对彩度 C"),
    ("hue_lock_lc_rel", "锁明度 + 锁相对彩度 C_rel"),
)


def _srgb_decode(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def _srgb_encode(y):
    return 12.92 * y if y <= 0.0031308 else 1.055 * (y ** (1.0 / 2.4)) - 0.055


def krita_gray(rgb):
    """Krita 软打样（灰阶/透明度 + Gray-D50-elle-V2-srgbtrc.icc）的近似口径：
    相对亮度 Y = 0.2126R+0.7152G+0.0722B（线性 sRGB），再过 sRGB 传输函数编码成灰。
    与「Oklab L 线性 → 灰」不是一回事：L 更接近感知明度，这里是亮度。
    """
    r, g, b = (_srgb_decode(float(x)) for x in rgb)
    y = 0.2126 * r + 0.7152 * g + 0.0722 * b
    return _srgb_encode(max(0.0, min(1.0, y)))


def sample_mode(mode, h, L0, S0, V0, C0, crel0):
    """返回 (s, v) 或 None（**完全不可达**，该色相下不存在这个颜色）。"""
    if mode == "hue_hsv":
        return S0, V0
    if mode == "hue_lock_lc_abs":
        r = mc.sv_at_L_C(h, L0, C0, M)
        return None if r is None else (float(r[0]), float(r[1]))
    if mode == "hue_lock_lc_rel":
        r = mc.sv_at_L_crel(h, L0, crel0, M)
        return None if r is None else (float(r[0]), float(r[1]))
    raise ValueError(mode)


def group(L0, crel):
    """一组 = 一个**同源**起色：(h=H_START, Oklab L=L0, C_rel=crel)。

    起色由 sv_at_L_crel 反解得到，所以 L / C / C_rel 三者出自同一个颜色——
    上一版直接用固定的 S_START 二分解 V，当该 S 到不了目标 L 时会「标题写 L0、
    实际颜色却是另一个 L」，令 C0 与 L0 不同源，把锁绝对彩度的可达性演示得偏小。
    """
    r = mc.sv_at_L_crel(H_START, L0, crel, M)
    if r is None:                       # 极端边界兜底
        s0, v0 = 1.0, 1.0
    else:
        s0, v0 = float(r[0]), float(r[1])
    Lreal = float(mc.lightness(H_START, s0, v0, M))
    C0 = float(mc.ok_L_C(H_START, s0, v0)[1])
    crel_real = float(mc.crel_of_xyz(H_START, M, s0, v0)[0])
    return {"L0": L0, "V0": v0, "S0": s0, "C0": C0, "crel0": crel_real,
            "Lreal": Lreal, "rgb": mc.hsv_to_srgb(H_START, s0, v0)}


def run(check_only=False, no_labels=False, badges=False, out_path=None):
    out_dir = ROOT / "docs" / "2026年09月" / "2026年09月25日" / "images"
    out_dir.mkdir(parents=True, exist_ok=True)
    groups = [group(L, CREL_PLOT) for L in L_TARGETS]

    # --no-labels：去掉全部行/列文字，只留纯色格（说明文字放正文）。
    # --badges：只补语言中性的数字徽标（模式块 1/2/3、第一组行号 1~4、组分隔线）。
    badge_on = bool(no_labels and badges)
    lbl_w = 0 if no_labels else LBL_W
    badge_w = BADGE_W if badge_on else 0
    mode_gap = MODE_GAP if badge_on else (4 if no_labels else 0)
    group_gap = GROUP_GAP if badge_on else PAD
    rows_per_group = len(MODES) * 4 + 1
    W = PAD * 2 + badge_w + lbl_w + N_SAMPLE * CELL_W
    H = PAD + len(groups) * rows_per_group * CELL_H \
        + len(groups) * (len(MODES) - 1) * mode_gap \
        + (len(groups) - 1) * group_gap + PAD
    img = Image.new("RGB", (W * SC, H * SC), BG)
    d = ImageDraw.Draw(img)

    try:
        from PIL import ImageFont
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 11 * SC)
        font_b = ImageFont.truetype("C:/Windows/Fonts/msyhbd.ttc", 12 * SC)
    except Exception:
        font = font_b = None
    # 数字徽标字体：只画 1~4，优先无衬线粗体；取不到时退回 PIL 默认字体。
    num_font = None
    for _path in ("C:/Windows/Fonts/arialbd.ttf", "C:/Windows/Fonts/msyhbd.ttc",
                  "C:/Windows/Fonts/DejaVuSans-Bold.ttf"):
        try:
            from PIL import ImageFont as _IF
            num_font = _IF.truetype(_path, 11 * SC)
            break
        except Exception:
            num_font = None
    if num_font is None:
        from PIL import ImageFont as _IF
        num_font = _IF.load_default()

    def txt(x, y, s, col=FG, bold=False):
        if no_labels:
            return
        d.text((x * SC, y * SC), s, fill=col, font=(font_b if bold else font))

    def _num(s, cx, cy, col=BADGE_FG):
        """把数字 s 居中画在 (cx, cy)（图像像素坐标，SC 前）。"""
        box = d.textbbox((0, 0), s, font=num_font)
        d.text((cx * SC - (box[2] - box[0]) / 2.0 - box[0],
                cy * SC - (box[3] - box[1]) / 2.0 - box[1]),
               s, fill=col, font=num_font)

    def badge(s, cx, cy):
        r = 9
        d.ellipse([(cx - r) * SC, (cy - r) * SC,
                   (cx + r) * SC, (cy + r) * SC], fill=BADGE_BG)
        _num(s, cx, cy - 0.5, BADGE_FG)

    summary = []
    y = PAD
    for gi, g in enumerate(groups):
        if badge_on and gi > 0:
            sep_y = y - group_gap / 2.0
            d.line([(PAD * SC, sep_y * SC), ((W - PAD) * SC, sep_y * SC)],
                   fill=SEP_COL, width=SC)
        txt(PAD, y + 2, "起色：h=%.0f°  目标 L=%.2f  C_rel=%.2f  →  实际 S=%.3f V=%.3f  "
                        "L=%.4f  C=%.4f" % (H_START, g["L0"], CREL_PLOT,
                                            g["S0"], g["V0"], g["Lreal"], g["C0"]), FG, True)
        y += CELL_H
        for mi, (mode, label) in enumerate(MODES):
            cols = []; Ls = []; Cs = []
            n_reach = 0
            for i in range(N_SAMPLE):
                h = (H_START + i * 360.0 / N_SAMPLE) % 360.0
                sv = sample_mode(mode, h, g["L0"], g["S0"], g["V0"], g["C0"], g["crel0"])
                if sv is None:
                    cols.append(None); Ls.append(None); Cs.append(None)
                else:
                    s, v = sv
                    cols.append(mc.hsv_to_srgb(h, s, v))
                    Ls.append(float(mc.lightness(h, s, v, M)))
                    Cs.append(float(mc.ok_L_C(h, s, v)[1]))
                    n_reach += 1
            reachL = [x for x in Ls if x is not None]
            reachC = [x for x in Cs if x is not None]
            drift = max((abs(x - g["L0"]) for x in reachL), default=0.0)
            summary.append((g["L0"], mode, n_reach, drift,
                            min(reachL) if reachL else None, max(reachL) if reachL else None,
                            min(reachC) if reachC else None, max(reachC) if reachC else None))
            if badge_on:
                badge(str(mi + 1), PAD + 10, y + 2 * CELL_H)
            # 四行：颜色 / 明度图 / 灰图 / 彩度图
            grays = [None if c is None else krita_gray(c) for c in cols]
            for band, (vals, tag) in enumerate(
                    ((cols, ""), (Ls, "L 图※我们锁的量：Oklab L（线性→灰）"),
                     (grays, "灰图（Krita 软打样：相对亮度，非我们锁的量）"), (Cs, "C 图（绝对 C）"))):
                if band == 0:
                    txt(PAD, y + 5, label, FG)
                else:
                    txt(PAD + 12, y + 5, tag, DIM)
                if badge_on and gi == 0:
                    _num(str(band + 1), PAD + BADGE_W - 10, y + CELL_H / 2.0, ROW_NUM_FG)
                x0 = PAD + badge_w + lbl_w
                for i, val in enumerate(vals):
                    x = x0 + i * CELL_W
                    if val is None:
                        d.rectangle([x * SC, y * SC, (x + CELL_W) * SC, (y + CELL_H) * SC],
                                    fill=GAP)
                        continue
                    if band == 0:
                        rgb = tuple(int(round(c * 255)) for c in np.clip(val, 0, 1))
                    elif band in (1, 2):
                        k = int(round(np.clip(val, 0, 1) * 255)); rgb = (k, k, k)
                    else:
                        k = int(round(np.clip(val / C_MAX_PLOT, 0, 1) * 255)); rgb = (k, k, k)
                    d.rectangle([x * SC, y * SC, (x + CELL_W) * SC, (y + CELL_H) * SC],
                                fill=rgb)
                y += CELL_H
            if no_labels and mi < len(MODES) - 1:
                y += mode_gap
        y += group_gap
    y -= group_gap - PAD
    img = img.resize((W, H), Image.LANCZOS)
    if out_path:
        out = Path(out_path)
        out.parent.mkdir(parents=True, exist_ok=True)
    else:
        out = out_dir / ("preview-ring-modes-crel%02d.png" % round(CREL_PLOT * 100))
    img.save(str(out))
    print("已生成：%s  (%dx%d)" % (out, W, H))
    print()
    print("%-5s %-19s %6s %9s  %-18s %-18s"
          % ("L0", "模式", "可达/36", "L 最大偏差", "L 范围", "C 范围"))
    for L0, mode, n, drift, lmin, lmax, cmin, cmax in summary:
        print("%-5.2f %-19s %6d %9.4f  %-18s %-18s"
              % (L0, mode, n, drift,
                 ("%.4f~%.4f" % (lmin, lmax)) if lmin is not None else "-",
                 ("%.4f~%.4f" % (cmin, cmax)) if cmin is not None else "-"))
    return out


def check():
    """数学自检：3 种模式在 4 组明度 × 36 采样下的不变量。"""
    bad = []
    for g in [group(L, CREL_PLOT) for L in L_TARGETS]:
        for mode in ("hue_hsv", "hue_lock_lc_abs", "hue_lock_lc_rel"):
            for i in range(N_SAMPLE):
                h = (H_START + i * 360.0 / N_SAMPLE) % 360.0
                sv = sample_mode(mode, h, g["L0"], g["S0"], g["V0"], g["C0"], g["crel0"])
                if sv is None:
                    continue
                s, v = float(sv[0]), float(sv[1])
                L = float(mc.lightness(h, s, v, M))
                C = float(mc.ok_L_C(h, s, v)[1])
                crel = float(mc.crel_of_xyz(h, M, s, v)[0])
                if mode == "hue_hsv":
                    ok = abs(s - g["S0"]) < 1e-12 and abs(v - g["V0"]) < 1e-12
                elif mode == "hue_lock_lc_abs":
                    ok = abs(L - g["L0"]) < 1e-6 and abs(C - g["C0"]) < 1e-6
                else:
                    ok = abs(L - g["L0"]) < 1e-6 and abs(crel - g["crel0"]) < 1e-6
                if not ok:
                    bad.append((g["L0"], mode, round(h, 1), round(L, 6), round(C, 6), round(crel, 6)))
    print("不变量自检：不满足 %d 例" % len(bad))
    for b in bad[:8]:
        print("   ", b)
    print("结论：%s" % ("全部通过 ✅" if not bad else "存在不满足 ❌"))
    return 0 if not bad else 1


def main(argv=None):
    global CREL_PLOT, M
    import argparse
    ap = argparse.ArgumentParser(description="色相环 3 种操作模式效果对比图（可输出无文字版）")
    ap.add_argument("--crel", type=float, default=CREL_PLOT,
                    help="起色相对彩度，默认 %.2f" % CREL_PLOT)
    ap.add_argument("--metric", default=M, help="明度标准：oklab（默认）/ gray")
    ap.add_argument("--no-labels", action="store_true",
                    help="不画任何标题、行名、图注，只输出纯色格")
    ap.add_argument("--badges", action="store_true",
                    help="与 --no-labels 同用：补语言中性的数字徽标（模式块 1/2/3、第一组行号 1~4、组间分隔线）")
    ap.add_argument("--out", default=None, help="输出 PNG 路径（默认 docs/…/images/）")
    ap.add_argument("--check", action="store_true", help="只跑数学自检，不画图")
    args = ap.parse_args(argv)
    CREL_PLOT = float(args.crel)
    M = args.metric
    if args.check:
        return check()
    return 0 if run(no_labels=args.no_labels, badges=args.badges,
                    out_path=args.out) is not None else 0


if __name__ == "__main__":
    sys.exit(main())
