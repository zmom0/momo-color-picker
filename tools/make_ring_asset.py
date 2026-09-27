# -*- coding: utf-8 -*-
"""预生成色相环 PNG 资源（避免插件里每次重算 70 万像素）。

用法：python tools/make_ring_asset.py
产物：pykrita/hsv_picker/assets/ring.png（1024x1024 RGBA）
口径：0° 红在 9 点钟、色相顺时针递增；环内圈比例 = 0.7071、外圈 = 内圈 + 0.18。
"""
import os
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pykrita", "hsv_picker"))

import numpy as np          # noqa: E402
import render as rd         # noqa: E402

SIZE = 1024
# 比例直接取自 render.picker_geometry（单位尺寸），保证与控件几何完全一致
_G = rd.picker_geometry(SIZE, SIZE)
R_IN = _G["r_in"] / (SIZE / 2.0)
R_OUT = _G["r_out"] / (SIZE / 2.0)
OUT = os.path.join(ROOT, "pykrita", "hsv_picker", "assets", "ring.png")


def main():
    t0 = time.perf_counter()
    arr = rd.render_ring_array(SIZE, R_IN, R_OUT, ss=1)
    # 直接用 QImage 写 PNG（系统 Python 没有 PyQt5 -> 手工写 PNG）
    try:
        from PyQt5.QtGui import QImage
        img = QImage(np.ascontiguousarray(arr).data, SIZE, SIZE, SIZE * 4,
                     QImage.Format_RGBA8888)
        os.makedirs(os.path.dirname(OUT), exist_ok=True)
        img.save(OUT, "PNG")
        print("已用 PyQt5 写出 %s" % OUT)
    except ImportError:
        write_png(arr, OUT)
        print("已用内置编码器写出 %s" % OUT)
    print("耗时 %.2f ms，大小 %.1f KB" % (
        (time.perf_counter() - t0) * 1000, os.path.getsize(OUT) / 1024.0))


def write_png(arr, path):
    import struct
    import zlib
    h, w, _ = arr.shape
    raw = b"".join(b"\x00" + arr[y].tobytes() for y in range(h))

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data +
                struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + \
        chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b"")
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as fh:
        fh.write(png)


if __name__ == "__main__":
    main()
