# -*- coding: utf-8 -*-
"""构建 Momo Color Picker 发布 zip（T-37 R6）。

用法：
    python tools/build_release_zip.py [--version 1.0.0] [--vendor 目录] [--out 目录]

行为：
  · 复制 pykrita/hsv_picker（排除 vendor/__pycache__/*.pyc/*.pyo）；
  · 复制 --vendor（默认 pykrita/hsv_picker/vendor）并只对副本瘦身：
    删 numpy/**/tests 与 numpy/_core/include，保留 numpy-2.3.0.dist-info；
  · 加入 pykrita/hsv_picker.desktop、install.bat、install.txt；
  · 输出 <out>/MomoColorPicker-<version>-win64-krita5.3.zip，并打印条目数/大小/顶层结构。

本脚本只读仓库源码、只在临时目录和 dist/ 生成产物；不修改开发仓库的 vendor。
GitHub Actions 复用：先下载并解压 cp313 的 numpy wheel 到 --vendor 指向的目录再调用本脚本。
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG_REL = Path("pykrita") / "hsv_picker"
DESKTOP_REL = Path("pykrita") / "hsv_picker.desktop"
INSTALL_FILES = ("install.bat", "install.txt")
SKIP_DIRS = {"__pycache__"}
SKIP_SUFFIX = (".pyc", ".pyo")


def read_version() -> str:
    text = (ROOT / PKG_REL / "__init__.py").read_text(encoding="utf-8")
    m = re.search(r'^__version__\s*=\s*["\']([^"\']+)["\']', text, re.MULTILINE)
    if not m:
        raise SystemExit("找不到插件 __version__")
    return m.group(1)


def copy_plugin(src: Path, dst: Path) -> int:
    """复制插件源码（不含 vendor，不含缓存），返回文件数。"""
    count = 0
    for dirpath, dirnames, filenames in os.walk(src):
        rel = os.path.relpath(dirpath, src)
        parts = [] if rel == "." else rel.replace(os.sep, "/").split("/")
        if parts and parts[0] == "vendor":
            dirnames[:] = []
            continue
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        out_dir = dst if not parts else dst.joinpath(*parts)
        out_dir.mkdir(parents=True, exist_ok=True)
        for name in sorted(filenames):
            if name.endswith(SKIP_SUFFIX):
                continue
            shutil.copy2(os.path.join(dirpath, name), out_dir / name)
            count += 1
    return count


def copy_vendor_slim(src: Path, dst: Path) -> tuple[int, int]:
    """复制 vendor 到打包目录并瘦身；返回（文件数，字节数）。

    瘦身只作用于副本：删 numpy 下所有 tests 目录与 numpy/_core/include，
    保留 numpy-2.3.0.dist-info（含 BSD 许可）；同时排除 Python 缓存。
    """
    if not src.is_dir():
        raise SystemExit("找不到 vendor 目录：%s" % src)
    count = 0
    total = 0
    for dirpath, dirnames, filenames in os.walk(src):
        rel = os.path.relpath(dirpath, src)
        parts = [] if rel == "." else rel.replace(os.sep, "/").split("/")
        if parts and parts[0] == "numpy":
            if parts[-1] == "tests":
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames if d != "tests"]
            if parts[:2] == ["numpy", "_core"]:
                dirnames[:] = [d for d in dirnames if d != "include"]
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        out_dir = dst if not parts else dst.joinpath(*parts)
        out_dir.mkdir(parents=True, exist_ok=True)
        for name in sorted(filenames):
            if name.endswith(SKIP_SUFFIX):
                continue
            src_file = Path(dirpath) / name
            shutil.copy2(src_file, out_dir / name)
            count += 1
            total += src_file.stat().st_size
    if not (dst / "numpy").is_dir():
        raise SystemExit("瘦身后的 vendor 缺少 numpy/：%s" % src)
    return count, total


def dir_size(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description="构建 Momo Color Picker 发布 zip")
    ap.add_argument("--version", default=None, help="默认读插件 __version__")
    ap.add_argument("--vendor", default=str(ROOT / PKG_REL / "vendor"),
                    help="numpy vendor 源目录（默认 pykrita/hsv_picker/vendor）")
    ap.add_argument("--out", default=str(ROOT / "dist"), help="输出目录（默认 dist/）")
    args = ap.parse_args(argv)

    version = args.version or read_version()
    vendor = Path(args.vendor)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    if not (vendor / "numpy").is_dir():
        raise SystemExit("--vendor 下没有 numpy/：%s" % vendor)

    full_size = dir_size(vendor)
    stage = Path(tempfile.mkdtemp(prefix="momo_release_"))
    try:
        plugin_dir = stage / "hsv_picker"
        plugin_count = copy_plugin(ROOT / PKG_REL, plugin_dir)
        vendor_count, vendor_size = copy_vendor_slim(vendor, plugin_dir / "vendor")
        for name in INSTALL_FILES:
            shutil.copy2(ROOT / name, stage / name)
        shutil.copy2(ROOT / DESKTOP_REL, stage / "hsv_picker.desktop")

        zip_path = out_dir / ("MomoColorPicker-%s-win64-krita5.3.zip" % version)
        dirs = sorted(p for p in stage.rglob("*") if p.is_dir())
        files = sorted(p for p in stage.rglob("*") if p.is_file())
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
            # 官方导入器靠 zip 内的目录条目（"<模块名>/"）定位插件模块，必须写入
            for path in dirs:
                arc = str(path.relative_to(stage)).replace(os.sep, "/") + "/"
                zf.write(path, arc)
            for path in files:
                arc = str(path.relative_to(stage)).replace(os.sep, "/")
                zf.write(path, arc)
        with zipfile.ZipFile(zip_path) as zf:
            all_infos = zf.infolist()
            infos = [i for i in all_infos if not i.is_dir()]
            dir_infos = [i for i in all_infos if i.is_dir()]
            top = {}
            for info in infos:
                top.setdefault(info.filename.split("/", 1)[0], [0, 0])
                top[info.filename.split("/", 1)[0]][0] += 1
                top[info.filename.split("/", 1)[0]][1] += info.file_size
        bad = [i.filename for i in infos
               if "__pycache__" in i.filename or i.filename.endswith(SKIP_SUFFIX)
               or "/tests/" in i.filename or i.filename.startswith("numpy/_core/include/")]
        print("插件源码文件数 : %d" % plugin_count)
        print("vendor 文件数   : %d（%d 字节）" % (vendor_count, vendor_size))
        print("vendor 瘦身前   : %d 字节" % full_size)
        print("vendor 瘦身后   : %d 字节（省 %.1f%%）"
              % (vendor_size, 100.0 * (full_size - vendor_size) / max(full_size, 1)))
        print("zip 路径        : %s" % zip_path)
        print("zip 大小        : %d 字节" % zip_path.stat().st_size)
        print("zip 条目数      : %d（文件 %d + 目录 %d）"
              % (len(all_infos), len(infos), len(dir_infos)))
        print("顶层结构        : %s"
              % ", ".join("%s(%d)" % (k, v[0]) for k, v in sorted(top.items())))
        if bad:
            print("!! 不应出现的条目：%r" % bad[:5])
            return 1
        if set(top) != {"hsv_picker", "hsv_picker.desktop", "install.bat", "install.txt"}:
            print("!! 顶层结构不符合预期：%s" % sorted(top))
            return 1
    finally:
        shutil.rmtree(stage, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
