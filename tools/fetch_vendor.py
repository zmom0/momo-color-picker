# -*- coding: utf-8 -*-
"""下载并解压随插件自带的 numpy（cp313 / win_amd64）。

用法：python tools/fetch_vendor.py
产物：pykrita/hsv_picker/vendor/{numpy, numpy.libs, numpy-*.dist-info}
说明：Krita 5.3.3 的内嵌 Python 是 3.13 / win_amd64，且不带 numpy；
     本脚本用系统 Python 的 pip 只下载 wheel，不安装，不改系统环境。
"""
import os
import shutil
import subprocess
import sys
import zipfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

NUMPY_VERSION = "2.3.0"
WHEEL_NAME = "numpy-%s-cp313-cp313-win_amd64.whl" % NUMPY_VERSION
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WHEEL_DIR = os.path.join(ROOT, "tmp", "wheels")
VENDOR_DIR = os.path.join(ROOT, "pykrita", "hsv_picker", "vendor")


def download_wheel():
    os.makedirs(WHEEL_DIR, exist_ok=True)
    target = os.path.join(WHEEL_DIR, WHEEL_NAME)
    if os.path.isfile(target):
        print("已存在 wheel：%s" % target)
        return target
    cmd = [sys.executable, "-m", "pip", "download", "numpy==%s" % NUMPY_VERSION,
           "--only-binary=:all:", "--platform", "win_amd64",
           "--python-version", "3.13", "--implementation", "cp",
           "--abi", "cp313", "--no-deps", "-d", WHEEL_DIR]
    print("下载：%s" % " ".join(cmd))
    subprocess.check_call(cmd)
    if not os.path.isfile(target):
        raise SystemExit("下载后找不到 %s" % target)
    return target


def extract_wheel(wheel):
    if os.path.isdir(VENDOR_DIR):
        shutil.rmtree(VENDOR_DIR)
    os.makedirs(VENDOR_DIR, exist_ok=True)
    with zipfile.ZipFile(wheel) as zf:
        names = zf.namelist()
        zf.extractall(VENDOR_DIR)
    top = sorted({n.split("/")[0] for n in names})
    print("解压 %d 个条目到 %s" % (len(names), VENDOR_DIR))
    print("顶层内容：%s" % ", ".join(top))


def main():
    wheel = download_wheel()
    extract_wheel(wheel)
    size = sum(os.path.getsize(os.path.join(dp, f))
               for dp, _, fs in os.walk(VENDOR_DIR) for f in fs)
    print("vendor 体积：%.1f MB" % (size / 1024.0 / 1024.0))
    print("下一步：python tools/install_plugin.py --with-vendor")
    return 0


if __name__ == "__main__":
    sys.exit(main())
