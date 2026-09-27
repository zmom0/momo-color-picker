# -*- coding: utf-8 -*-
"""生成「sRGB 色域切片包围盒」按明度 L 的查表数据，并写进 math_core.py。

背景：切片包围盒只随明度 L 变（与色相同），本可以内嵌成常量表：
  · 运行时现算（二维栅格扫）7.99ms/次，拖动时每帧一次 -> 吃掉整帧预算；
  · 运行时惰性建表也要 63ms 冷启动；
  · 内嵌常量表：0ms 冷启动 + 0.003ms/次查表（np.interp）。

精度：明度方向插值在「包围盒跳变处」（低明度 ~L=0.038 有一处）残差可达 ~0.01，
      占色条满量程 2%，只影响刻度观感；可达性由 ab_strip_range 的并集兜底保证。
本脚本离线算一次（栅格 401²，明度按余弦分布取 129 点），把结果写成 Python 字面量。

用法：python tools/make_ab_box_table.py            # 只打印
      python tools/make_ab_box_table.py --write    # 写回 math_core.py
"""
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pykrita" / "hsv_picker"))
import math_core as mc          # noqa: E402

N_L = 129          # 明度采样数（余弦分布：两端更密）
N_G = 401          # a/b 栅格采样数（步长 0.0018）
LIM = 0.36
L_START, L_END = 0.002, 0.998


def build():
    u = np.arange(N_L) / (N_L - 1.0)
    Ls = L_START + (L_END - L_START) * (0.5 - 0.5 * np.cos(np.pi * u))   # 两端更密
    ax = np.linspace(-LIM, LIM, N_G)
    A, B = np.meshgrid(ax, ax, indexing="ij")
    out = np.zeros((4, N_L))
    for i in range(N_L):
        m = mc.oklab_in_gamut(float(Ls[i]), A, B)
        if not m.any():
            continue
        out[0, i] = A[m].min()
        out[1, i] = A[m].max()
        out[2, i] = B[m].min()
        out[3, i] = B[m].max()
    # 向外扩 pad：宁可量程略大，也不能因为量化/插值把「可达点」切在条外
    pad = 0.002
    out[0] = np.maximum(out[0] - pad, -LIM)
    out[1] = np.minimum(out[1] + pad, LIM)
    out[2] = np.maximum(out[2] - pad, -LIM)
    out[3] = np.minimum(out[3] + pad, LIM)
    return Ls, out


def verify(Ls, tab, n=4000, seed=3):
    """随机抽 L，与直接栅格扫（n=401）对比最大偏差。"""
    rng = np.random.default_rng(seed)
    worst, worst_L = 0.0, None
    ax = np.linspace(-LIM, LIM, N_G)
    A, B = np.meshgrid(ax, ax, indexing="ij")
    for L in rng.uniform(L_START, L_END, n):
        m = mc.oklab_in_gamut(float(L), A, B)
        if not m.any():
            continue
        ref = (float(A[m].min()), float(A[m].max()), float(B[m].min()), float(B[m].max()))
        got = tuple(float(np.interp(L, Ls, tab[k])) for k in range(4))
        d = max(abs(got[k] - ref[k]) for k in range(4))
        if d > worst:
            worst, worst_L = d, float(L)
    return worst, worst_L


def literal(Ls, tab):
    def arr(v):
        items = ["%.5f" % x for x in v]
        lines = []
        for i in range(0, len(items), 8):
            lines.append("        " + ", ".join(items[i:i + 8]) + ",")
        return "(\n" + "\n".join(lines) + "\n    )"

    return (
        "_AB_BOX_L = " + arr(Ls) + "\n"
        "_AB_BOX_A_LO = " + arr(tab[0]) + "\n"
        "_AB_BOX_A_HI = " + arr(tab[1]) + "\n"
        "_AB_BOX_B_LO = " + arr(tab[2]) + "\n"
        "_AB_BOX_B_HI = " + arr(tab[3]) + "\n")


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    Ls, tab = build()
    worst, worst_L = verify(Ls, tab)
    print("明度采样 %d 点（余弦分布）｜ a/b 栅格 %d²" % (N_L, N_G))
    print("随机 4000 个明度上，插值表相对直接栅格扫的最大偏差 = %.5f（L=%.4f）" % (worst, worst_L))
    if worst >= 0.012:
        print("偏差过大（%.5f），不写入" % worst)
        return 1
    text = literal(Ls, tab)
    if "--write" in sys.argv:
        p = ROOT / "pykrita" / "hsv_picker" / "math_core.py"
        t = p.read_text(encoding="utf-8")
        a = t.index("# ---- 切片包围盒查表（由 tools/make_ab_box_table.py 生成）----")
        b = t.index("# ---- 切片包围盒查表结束 ----")
        t = t[:a] + "# ---- 切片包围盒查表（由 tools/make_ab_box_table.py 生成）----\n" + text + t[b:]
        p.write_text(t, encoding="utf-8", newline="\n")
        print("已写入 %s" % p)
    else:
        print(text[:400] + " ...（省略）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
