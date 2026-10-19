#!/bin/bash
# 馍馍拾色器 / Momo Color Picker — macOS 安装脚本
#
# 与 install.bat 对应：把插件装进 Krita 用户资源目录，并把插件内置的
# numpy 换成与 Krita 内嵌 Python 匹配的 macOS wheel（发布包里的 Windows
# numpy 是 .pyd/.dll，macOS 无法加载）。
#
# 用法:
#   ./install_macos.sh                 # 安装 / 覆盖升级
#   ./install_macos.sh --uninstall     # 卸载
#
# 可用环境变量:
#   KRITA_APP=/path/to/krita.app       # 不指定时依次尝试 /Applications 与 ~/Applications
#   KRITA_RES_DIR=/path/to/krita       # 自定义 Krita 资源目录
#   NUMPY_VERSION=2.3.0                # 与发布包保持一致
#   NUMPY_WHEEL=/path/to/numpy.whl     # 离线安装：直接指定 wheel
#   FORCE_PLATFORM=macosx_11_0_arm64   # 手动指定 wheel 平台标签
#
# 支持两种目录布局：仓库源码（pykrita/…）与发布 zip 解压后的根目录（hsv_picker/…）。

set -euo pipefail

NUMPY_VERSION="${NUMPY_VERSION:-2.3.0}"
RES_DIR="${KRITA_RES_DIR:-$HOME/Library/Application Support/krita}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 兼容仓库布局（pykrita/）与发布包布局（hsv_picker/）
if [ -d "$SCRIPT_DIR/pykrita/hsv_picker" ]; then
    SRC_PLUGIN="$SCRIPT_DIR/pykrita/hsv_picker"
    SRC_DESKTOP="$SCRIPT_DIR/pykrita/hsv_picker.desktop"
else
    SRC_PLUGIN="$SCRIPT_DIR/hsv_picker"
    SRC_DESKTOP="$SCRIPT_DIR/hsv_picker.desktop"
fi

DEST_PLUGIN="$RES_DIR/pykrita/hsv_picker"
DEST_DESKTOP="$RES_DIR/pykrita/hsv_picker.desktop"
DEST_ACTION="$RES_DIR/actions/hsv_picker.action"

info() { printf '==> %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*"; }
die()  { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

find_krita() {
    local candidates=("${KRITA_APP:-}" "/Applications/krita.app" "$HOME/Applications/krita.app")
    local c
    for c in "${candidates[@]}"; do
        if [ -n "$c" ] && [ -d "$c" ]; then
            printf '%s\n' "$c"
            return 0
        fi
    done
    return 1
}

# ---------- 卸载 ----------
if [ "${1:-}" = "--uninstall" ]; then
    info "Removing Momo Color Picker from: $RES_DIR"
    rm -rf "$DEST_PLUGIN" "$DEST_DESKTOP" "$DEST_ACTION"
    info "Done. Restart Krita."
    exit 0
fi

# ---------- 前置检查 ----------
[ -d "$SRC_PLUGIN" ] || die "plugin folder not found: $SRC_PLUGIN"
[ -f "$SRC_DESKTOP" ] || die "desktop file not found: $SRC_DESKTOP"
[ -f "$SRC_PLUGIN/actions/hsv_picker.action" ] || die "action file not found: $SRC_PLUGIN/actions/hsv_picker.action"

KRITA_APP="$(find_krita)" || die "Krita not found. Set KRITA_APP=/path/to/krita.app"
PY_FRAMEWORK="$KRITA_APP/Contents/Frameworks/Python.framework/Versions"
[ -d "$PY_FRAMEWORK" ] || die "no embedded Python in: $KRITA_APP"

PYVER="$(ls "$PY_FRAMEWORK" | grep -E '^3\.[0-9]+$' | sort -V | tail -1)"
[ -n "$PYVER" ] || die "cannot detect the embedded Python version"
ABI="cp${PYVER/./}"

ARCH="${FORCE_ARCH:-$(uname -m)}"
if [ -n "${FORCE_PLATFORM:-}" ]; then
    PLATFORM="$FORCE_PLATFORM"
elif [ "$ARCH" = "arm64" ]; then
    PLATFORM="macosx_11_0_arm64"
else
    PLATFORM="macosx_10_9_x86_64"
fi

info "Krita: $KRITA_APP"
info "Embedded Python: $PYVER ($ABI), wheel platform: $PLATFORM"
info "Resource folder: $RES_DIR"

# ---------- 准备 numpy wheel ----------
TMP="$(mktemp -d "${TMPDIR:-/tmp}/momo_macos.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT

if [ -n "${NUMPY_WHEEL:-}" ]; then
    [ -f "$NUMPY_WHEEL" ] || die "NUMPY_WHEEL not found: $NUMPY_WHEEL"
    WHEEL="$NUMPY_WHEEL"
    info "Using local wheel: $WHEEL"
else
    command -v python3 >/dev/null 2>&1 || \
        die "python3 is required to download numpy (or set NUMPY_WHEEL)"
    info "Downloading numpy $NUMPY_VERSION ($PLATFORM, $ABI) ..."
    python3 -m pip download --no-deps --only-binary=:all: \
        --platform "$PLATFORM" --python-version "$PYVER" \
        --implementation cp --abi "$ABI" \
        -d "$TMP" "numpy==$NUMPY_VERSION" >/dev/null
    WHEEL="$(ls "$TMP"/numpy-*.whl 2>/dev/null | head -1)"
    [ -n "$WHEEL" ] || die "failed to download the numpy wheel"
fi

# ---------- 组装插件 ----------
info "Staging plugin (source + macOS numpy) ..."
STAGE="$TMP/stage/hsv_picker"
mkdir -p "$STAGE"
rsync -a \
    --exclude 'vendor' --exclude '__pycache__' --exclude '*.pyc' --exclude '.DS_Store' \
    "$SRC_PLUGIN/" "$STAGE/"

mkdir -p "$STAGE/vendor"
unzip -q "$WHEEL" -d "$STAGE/vendor"
[ -d "$STAGE/vendor/numpy" ] || die "the wheel has no numpy/ folder"

# 与 Windows 发布包一致：去掉 tests 与 C 头文件，运行时不需要
find "$STAGE/vendor/numpy" -type d -name tests -prune -exec rm -rf {} + 2>/dev/null || true
rm -rf "$STAGE/vendor/numpy/_core/include"

# ---------- 安装 ----------
info "Installing ..."
mkdir -p "$RES_DIR/pykrita" "$RES_DIR/actions"
rsync -a --delete "$STAGE/" "$DEST_PLUGIN/"
cp -f "$SRC_DESKTOP" "$DEST_DESKTOP"
cp -f "$SRC_PLUGIN/actions/hsv_picker.action" "$DEST_ACTION"

# 下载来的文件可能带 quarantine，去掉以免 Gatekeeper 拦截 .so
xattr -dr com.apple.quarantine "$DEST_PLUGIN" 2>/dev/null || true
xattr -dr com.apple.quarantine "$DEST_DESKTOP" 2>/dev/null || true

# ---------- 校验 ----------
if command -v python3 >/dev/null 2>&1 && \
   python3 -c "import sys; sys.exit(0 if sys.version_info[:2] == tuple(int(x) for x in '$PYVER'.split('.')) else 1)"; then
    info "Checking numpy ..."
    PYTHONPATH="$DEST_PLUGIN/vendor" python3 -c \
        "import numpy, numpy.linalg; print('    numpy', numpy.__version__, 'OK')"
else
    warn "local python3 is not $PYVER, skipped the numpy import check"
fi

cat <<EOF

Installed:
  plugin      $DEST_PLUGIN
  desktop     $DEST_DESKTOP
  action      $DEST_ACTION

Next:
  1. Restart Krita
  2. Settings > Configure Krita > Python Plugin Manager: enable "Momo Color Picker"
  3. Restart Krita again
  4. Settings > Dockers > Momo Color Picker, or press Shift+B

Uninstall: $0 --uninstall
EOF
