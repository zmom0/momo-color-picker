# -*- coding: utf-8 -*-
"""把本工程的插件包安装（复制）到 Krita 用户插件目录，并校验自带 numpy 完整性。

用法：
    python tools/install_plugin.py                 安装/更新插件代码（保留已有 vendor/）
    python tools/install_plugin.py --with-vendor   连自带 numpy（vendor/）一起完整复制
    python tools/install_plugin.py --repair        只补齐 vendor/ 里缺失/损坏的文件

目标：[APPDATA]/krita/pykrita/hsv_picker.desktop 与 hsv_picker/ 目录
说明：
  · 只做复制，不改 Krita 配置；启用/停用仍需在 Krita 的
    设置 -> 配置 Krita -> Python 插件管理器 里操作。
  · Krita 运行时会锁住 vendor 里的 .pyd；此时请勿删整个 vendor 目录，
    用 --repair 补齐即可（逐文件覆盖不会碰被锁文件）。
"""
import hashlib
import os
import shutil
import sys
import zipfile

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_ROOT = os.path.join(ROOT, "pykrita")
PLUGIN_ID = "hsv_picker"
DESKTOP_SRC = os.path.join(SRC_ROOT, PLUGIN_ID + ".desktop")
PKG_SRC = os.path.join(SRC_ROOT, PLUGIN_ID)
VENDOR_SRC = os.path.join(PKG_SRC, "vendor")
WHEEL = os.path.join(ROOT, "tmp", "wheels", "numpy-2.3.0-cp313-cp313-win_amd64.whl")
def _discover_py_files():
    """包内所有 .py（自动收集，避免新增模块漏装）。"""
    try:
        names = [fn for fn in os.listdir(PKG_SRC) if fn.endswith(".py")]
    except OSError:
        names = ["__init__.py", "hsv_picker.py", "math_core.py", "render.py", "picker_widget.py"]
    return tuple(sorted(names))


PY_FILES = _discover_py_files()


def dest_paths():
    appdata = os.environ.get("APPDATA")
    if not appdata:
        raise SystemExit("找不到 APPDATA 环境变量，无法定位 Krita 资源目录")
    dst_root = os.path.join(appdata, "krita", "pykrita")
    return dst_root, os.path.join(dst_root, PLUGIN_ID + ".desktop"), os.path.join(dst_root, PLUGIN_ID)


def verify_vendor(vendor_dir, quiet=False):
    """按 wheel 清单校验 vendor 完整性；返回 (缺失数, 损坏数)。"""
    if not os.path.isfile(WHEEL):
        if not quiet:
            print("提示：找不到 %s，跳过 vendor 完整性校验" % WHEEL)
        return 0, 0
    zf = zipfile.ZipFile(WHEEL)
    names = [n for n in zf.namelist() if not n.endswith("/")]
    missing, corrupt = [], []
    for name in names:
        dst = os.path.join(vendor_dir, name.replace("/", os.sep))
        if not os.path.exists(dst):
            missing.append(name)
        elif hashlib.md5(zf.read(name)).hexdigest() != hashlib.md5(open(dst, "rb").read()).hexdigest():
            corrupt.append(name)
    return missing, corrupt


def repair_vendor(dst_pkg):
    """按 wheel 清单补齐 vendor（逐文件复制，不删除被 Krita 锁住的文件）。"""
    dst_vendor = os.path.join(dst_pkg, "vendor")
    if not os.path.isdir(VENDOR_SRC):
        print("本地没有 vendor/，请先运行 tools/fetch_vendor.py")
        return 1
    copied = 0
    for dp, _, files in os.walk(VENDOR_SRC):
        rel = os.path.relpath(dp, VENDOR_SRC)
        out_dir = os.path.join(dst_vendor, rel) if rel != "." else dst_vendor
        os.makedirs(out_dir, exist_ok=True)
        for fn in files:
            src, dst = os.path.join(dp, fn), os.path.join(out_dir, fn)
            need = True
            if os.path.exists(dst) and os.path.getsize(dst) == os.path.getsize(src):
                need = hashlib.md5(open(src, "rb").read()).hexdigest() != \
                       hashlib.md5(open(dst, "rb").read()).hexdigest()
            if need:
                try:
                    shutil.copy2(src, dst)
                    copied += 1
                except PermissionError as exc:
                    print("警告：%s 被占用，跳过（%s）" % (fn, exc))
    missing, corrupt = verify_vendor(dst_vendor)
    print("vendor 修复：复制 %d 个文件；剩余缺失 %d、损坏 %d" % (copied, len(missing), len(corrupt)))
    for name in (missing + corrupt)[:8]:
        print("   ", name)
    return 0 if not missing and not corrupt else 2


def _copy_if_changed(src, dst, label):
    """按内容判断是否需要复制；返回是否更新。"""
    if os.path.isfile(dst):
        old = hashlib.md5(open(dst, "rb").read()).hexdigest()
        new = hashlib.md5(open(src, "rb").read()).hexdigest()
        if old == new:
            return False
    shutil.copy2(src, dst)
    print("更新 %s" % label)
    return True


def copy_code(dst_pkg):
    """只更新插件代码文件（vendor 保持不动，兼容 Krita 运行中）。"""
    os.makedirs(dst_pkg, exist_ok=True)
    for fn in PY_FILES:
        src = os.path.join(PKG_SRC, fn)
        dst = os.path.join(dst_pkg, fn)
        if not os.path.isfile(src):
            continue
        _copy_if_changed(src, dst, fn)
    # 非代码资源：Manual.html（Krita 插件说明）与 assets（预生成色相环）
    manual = os.path.join(PKG_SRC, "Manual.html")
    if os.path.isfile(manual):
        _copy_if_changed(manual, os.path.join(dst_pkg, "Manual.html"), "Manual.html")
    assets_src = os.path.join(PKG_SRC, "assets")
    if os.path.isdir(assets_src):
        assets_dst = os.path.join(dst_pkg, "assets")
        os.makedirs(assets_dst, exist_ok=True)
        for fn in sorted(os.listdir(assets_src)):
            src = os.path.join(assets_src, fn)
            if os.path.isfile(src):
                _copy_if_changed(src, os.path.join(assets_dst, fn), "assets/%s" % fn)
    # Manual.html 引用的图文资产（manual/images/*.png|gif），随插件包一起安装
    manual_src = os.path.join(PKG_SRC, "manual")
    if os.path.isdir(manual_src):
        manual_dst = os.path.join(dst_pkg, "manual")
        os.makedirs(manual_dst, exist_ok=True)
        for dp, _, files in os.walk(manual_src):
            rel_dir = os.path.relpath(dp, manual_src)
            dst_dir = manual_dst if rel_dir == "." else os.path.join(manual_dst, rel_dir)
            os.makedirs(dst_dir, exist_ok=True)
            for fn in sorted(files):
                src = os.path.join(dp, fn)
                rel = os.path.relpath(src, manual_src).replace(os.sep, "/")
                _copy_if_changed(src, os.path.join(dst_dir, fn), "manual/%s" % rel)
    pycache = os.path.join(dst_pkg, "__pycache__")
    if os.path.isdir(pycache):
        shutil.rmtree(pycache, ignore_errors=True)
        print("清理 __pycache__")


def install_actions(dst_root):
    """把插件包里的 actions/*.action 复制到 Krita 的 actions 目录（快捷键需要）。"""
    src = os.path.join(PKG_SRC, "actions")
    if not os.path.isdir(src):
        return
    resource_root = os.path.dirname(dst_root)          # .../krita
    dst = os.path.join(resource_root, "actions")
    os.makedirs(dst, exist_ok=True)
    for fn in sorted(os.listdir(src)):
        if fn.endswith(".action"):
            shutil.copyfile(os.path.join(src, fn), os.path.join(dst, fn))
            print("已安装快捷键声明：actions/%s" % fn)


def main(mode):
    dst_root, dst_desktop, dst_pkg = dest_paths()
    if not os.path.isdir(dst_root):
        print("目标目录不存在：%s\n请先启动一次 Krita，让资源目录建出来" % dst_root)
        return 1
    if mode == "repair":
        return repair_vendor(dst_pkg)
    shutil.copyfile(DESKTOP_SRC, dst_desktop)
    copy_code(dst_pkg)
    install_actions(dst_root)
    if mode == "with-vendor":
        if not os.path.isdir(os.path.join(dst_pkg, "vendor")):
            shutil.copytree(VENDOR_SRC, os.path.join(dst_pkg, "vendor"))
        rc = repair_vendor(dst_pkg)
        if rc != 0:
            return rc
    has_vendor = os.path.isdir(os.path.join(dst_pkg, "vendor"))
    print("已安装到：%s" % dst_root)
    print("  %s.desktop" % PLUGIN_ID)
    print("  %s/  (vendor 自带 numpy: %s)" % (PLUGIN_ID, "有" if has_vendor else "无"))
    if has_vendor:
        missing, corrupt = verify_vendor(os.path.join(dst_pkg, "vendor"), quiet=True)
        print("  vendor 校验：缺失 %d、损坏 %d" % (len(missing), len(corrupt)))
    else:
        print("提示：未安装 vendor/。需要自带 numpy 时：tools/fetch_vendor.py 后加 --with-vendor")
    print("下一步：重启 Krita -> 设置 / 配置 Krita / Python 插件管理器 -> "
          "勾选 馍馍拾色器（Momo Color Picker）-> 再重启 Krita")
    return 0


if __name__ == "__main__":
    if "--repair" in sys.argv:
        MODE = "repair"
    elif "--with-vendor" in sys.argv:
        MODE = "with-vendor"
    else:
        MODE = "code"
    sys.exit(main(MODE))
