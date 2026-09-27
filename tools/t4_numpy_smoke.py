# -*- coding: utf-8 -*-
"""T-4 自带 numpy 的 import 冒烟（在 Krita Scripter 里整段运行）。

前置：已执行
    python tools/fetch_vendor.py
    python tools/install_plugin.py --with-vendor
本脚本不依赖插件是否启用，直接把 vendor 目录加进 sys.path 后 import numpy。
cp313 的 numpy 无法用系统 Python（3.12）验证，必须在 Krita 的 3.13 里跑。
"""
import os
import sys
import time
import traceback

VENDOR = os.path.join(os.environ.get("APPDATA", ""),
                      "krita", "pykrita", "hsv_picker", "vendor")
def _momo_repo_root():
    root = os.environ.get("MOMO_REPO")
    if not root:
        try:
            base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        except NameError:
            base = ""
        if base and os.path.isfile(os.path.join(base, "tools", "math_selftest.py")):
            root = base
    if not root:
        import tempfile
        root = tempfile.gettempdir()
    return root


LOG_PATH = os.path.join(_momo_repo_root(), "tmp", "t4_numpy_smoke.txt")
LINES = []


def put(msg=""):
    text = str(msg)
    LINES.append(text)
    try:
        print(text)
    except Exception:
        pass
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        with open(LOG_PATH, "w", encoding="utf-8", newline="\n") as fh:
            fh.write("\n".join(LINES) + "\n")
    except Exception:
        pass


def main():
    put("=== T-4 自带 numpy import 冒烟 ===")
    put("python = %s" % sys.version.replace("\n", " "))
    put("vendor = %s" % VENDOR)
    put("vendor 存在 = %s" % os.path.isdir(VENDOR))
    if not os.path.isdir(VENDOR):
        put("!! 找不到 vendor 目录，请先跑 tools/fetch_vendor.py 与 install_plugin.py --with-vendor")
        return
    if VENDOR not in sys.path:
        sys.path.insert(0, VENDOR)
    try:
        import numpy as np
        put("import numpy = OK 版本 %s" % np.__version__)
        put("numpy 文件 = %s" % np.__file__)
        a = np.arange(1024 * 1024, dtype=np.float64)
        t0 = time.perf_counter()
        for _ in range(20):
            b = a * 1.0001 + 0.5
            c = float(b.sum())
        dt = (time.perf_counter() - t0) / 20.0
        put("1M float64 向量 20 次平均 = %.3f ms（应 < 5ms）" % (dt * 1000.0))
        put("dot/sum 结果抽样 = %.3f" % c)
        grid = np.linspace(0.0, 1.0, 256)
        t0 = time.perf_counter()
        for _ in range(50):
            ok = float(np.sqrt(grid).mean())
        dt2 = (time.perf_counter() - t0) / 50.0
        put("256 点向量 50 次平均 = %.4f ms" % (dt2 * 1000.0))
        put("=== 冒烟通过 ===")
    except Exception:
        put("!! import 或运算失败:\n%s" % traceback.format_exc())


main()
