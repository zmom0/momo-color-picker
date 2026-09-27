# -*- coding: utf-8 -*-
"""T-38/T-43 成品图来源核验工具。

对 `pykrita/hsv_picker/manual/images/` 做两类核验：
  1) 复现核验：用 `tools/make_manual_shots.py` 的构建函数在临时目录重画一遍，
     逐像素比较成品 PNG / GIF 是否与构建器输出一致——图片若被手工改过像素
     （除构建器生成的语言中性编号 1/2/3、1~4 与组间分隔线外）这里会立刻失败。
  2) 原始帧核验：三个 GIF 的每一帧与 `tmp/manual_shots_raw/` 对应原始抓图
     比较；仅允许 GIF 调色板量化误差（平均差 ≤ 6/255）。

用法：
    python tools/verify_manual_images.py          # 核验
    python tools/verify_manual_images.py --quiet  # 只输出结论
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import sys
import tempfile

from PIL import Image, ImageChops, ImageStat

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
IMAGES = os.path.join(ROOT, "pykrita", "hsv_picker", "manual", "images")
RAW = os.path.join(ROOT, "tmp", "manual_shots_raw")


def _load_builder():
    path = os.path.join(ROOT, "tools", "make_manual_shots.py")
    spec = importlib.util.spec_from_file_location("momo_manual_shots", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _same_pixels(a_path, b_path):
    a = Image.open(a_path).convert("RGB")
    b = Image.open(b_path).convert("RGB")
    return a.size == b.size and ImageChops.difference(a, b).getbbox() is None


def _gif_mae(a_path, b_path):
    a = Image.open(a_path)
    b = Image.open(b_path)
    if a.size != b.size or getattr(a, "n_frames", 1) != getattr(b, "n_frames", 1):
        return None
    worst = 0.0
    for i in range(a.n_frames):
        a.seek(i)
        b.seek(i)
        d = ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
        worst = max(worst, ImageStat.Stat(d.convert("L")).mean[0])
    return worst


def _gif_vs_raw(name, prefix):
    """返回 (平均 MAE, 最大单通道差)，原始帧缺失时返回 None。"""
    gif = Image.open(os.path.join(IMAGES, name))
    frames = sorted(n for n in os.listdir(RAW)
                    if n.startswith(prefix) and n.endswith(".png"))
    if len(frames) != gif.n_frames:
        return None
    worst = 0
    means = []
    for i in range(gif.n_frames):
        gif.seek(i)
        raw = Image.open(os.path.join(RAW, frames[i])).convert("RGB")
        d = ImageChops.difference(gif.convert("RGB"), raw)
        means.append(ImageStat.Stat(d.convert("L")).mean[0])
        worst = max(worst, max(max(ch) for ch in d.getextrema()))
    return sum(means) / float(len(means)), worst


def main(argv=None):
    quiet = "--quiet" in (argv or sys.argv[1:])
    if not os.path.isdir(RAW):
        print("原始抓图目录不存在：%s（先跑 make_manual_shots.py --capture）" % RAW)
        return 2
    mod = _load_builder()
    ok = True

    # 1) 复现核验：用同一套构建函数在临时目录重画
    tmpdir = tempfile.mkdtemp(prefix="momo_verify_")
    old_images = mod.IMAGES
    try:
        mod.IMAGES = tmpdir
        for name, fn in mod.BUILD_FUNCS.items():
            fn()
    finally:
        mod.IMAGES = old_images

    rows = []
    for name, fn in mod.BUILD_FUNCS.items():
        final = os.path.join(IMAGES, name if "." in name else name + ".png")
        rebuilt = os.path.join(tmpdir, name if "." in name else name + ".png")
        if not os.path.isfile(final):
            rows.append((name, "缺失", "构建器未产出"))
            ok = False
            continue
        if name.endswith(".gif"):
            mae = _gif_mae(final, rebuilt)
            good = mae is not None and mae < 1e-6
            rows.append((name, "复现一致" if good else "与构建器不一致",
                         "MAE %.4f" % (mae if mae is not None else -1.0)))
            ok = ok and good
        else:
            good = _same_pixels(final, rebuilt)
            rows.append((name, "复现一致" if good else "与构建器不一致", ""))
            ok = ok and good

    # 2) GIF 逐帧对原始抓图（只允许调色板量化误差）
    for name, prefix in (("demo-first.gif", "first"), ("demo-ring.gif", "ring"),
                         ("demo-ab.gif", "ab")):
        r = _gif_vs_raw(name, prefix)
        if r is None:
            rows.append((name, "原始帧帧数不匹配", "需重新 --capture"))
            ok = False
            continue
        mae, worst = r
        good = mae <= 6.0 and worst <= 128
        rows.append((name, "来源核验通过" if good else "来源核验失败",
                     "逐帧 MAE %.2f/255，最大 %d/255" % (mae, worst)))
        ok = ok and good

    shutil.rmtree(tmpdir, ignore_errors=True)
    if not quiet:
        print("%-30s %-18s %s" % ("文件", "结论", "备注"))
        print("-" * 84)
        for name, note, extra in rows:
            print("%-30s %-18s %s" % (name, note, extra))
        print("-" * 84)
    print("来源核验（除构建器生成的语言中性编号外，无新增文字 / 无手工涂改）：%s"
          % ("全部通过" if ok else "存在失败"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
