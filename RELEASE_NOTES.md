# Momo Color Picker 1.0.0

Momo Color Picker is an Oklab/Oklch-aware color picker plugin for **Krita 5.3.x on 64-bit Windows**. It keeps the familiar HSV-style hue ring and S/V square, while lightness and chroma are locked and read in Oklab (or in Krita's grayscale soft-proof value).

![Overview](https://raw.githubusercontent.com/zmom0/momo-color-picker/windows-release/pykrita/hsv_picker/manual/images/demo-first.gif)

## Highlights

- **HSV-style picking, Oklab precision** — hue ring (0° red at 9 o'clock, clockwise) plus S/V square; lightness can be locked as Oklab L (default) or as the Grayscale (soft proof) value.
- **Chroma in Oklab C** — relative chroma C_rel (default, always reachable) or absolute chroma C; unreachable hues at the locked (L, C) are marked with hatching, and absolute-C drags clamp to the nearest reachable hue.
- **L / C strips and optional Oklab a / b strips** — every value can also be typed into its numeric field; strips and ring stay in sync.
- **Popup panel on `Shift+B`** — auto-close outside, always-on-top and follow-mouse options; the same picker is also available as a docker.
- **Preview overlay** — current color plus the last two colors, with off / 1s / 2s / hover / always modes.
- **Color history and HEX swatch** — click a history entry to reuse it; click the current color swatch to copy its HEX code.
- **Fully customizable keymap** — 8 modifier combinations × left/middle/right button per area (ring, square, strips, numeric fields), editable in a table and persisted immediately.
- **Bilingual manual** — Simplified Chinese and English generated from one source, opened from the plugin's Manual button.

## Installation

1. Download `MomoColorPicker-1.0.0-win64-krita5.3.zip` from the Release assets.
2. In Krita, open **Tools → Scripts → Import Python Plugin From File...** and select the zip.
3. When Krita offers to restart, choose **Yes**; then restart Krita.
4. In **Settings → Configure Krita → Python Plugin Manager**, enable **Momo Color Picker** and restart Krita once more.
5. Open it from **Settings → Dockers → Momo Color Picker**, or press `Shift+B`.

A portable manual installation is also included: unzip the package, run `install.bat`, and restart Krita.

## Compatibility

- **Supported:** Krita 5.3.x on 64-bit Windows (the tested environment).
- The package bundles **numpy 2.3.0** for Krita's embedded Python 3.13, so no separate Python or numpy installation is needed.
- Other platforms are not supported by this build; Krita 5.2 and older are untested.

## License and third-party components

- **Momo Color Picker:** GPL-3.0-or-later.
- **numpy 2.3.0:** BSD-3-Clause; the full text is kept in `pykrita/hsv_picker/vendor/numpy-2.3.0.dist-info/LICENSE.txt`.

## 中文说明

馍馍拾色器 1.0.0：面向 Krita 5.3.x（64 位 Windows）的 Oklab/Oklch 拾色器插件。保留 HSV 色相环 + S/V 方块的顺手操作，同时用 Oklab L 精确锁定明度（可切换到 Krita 灰阶校样口径），彩度使用 Oklab C（默认相对彩度 C_rel，任何色相都可达）。支持 L/C/a/b 色条与数值框、弹出面板、预览浮层、历史颜色、可视化按键表和中英双语说明书。发布包已内置 numpy 2.3.0，下载 zip → 导入插件 → 重启 Krita 即可使用。许可证：GPL-3.0-or-later。

安装：从 Release 下载 `MomoColorPicker-1.0.0-win64-krita5.3.zip`，在 Krita 里打开 **工具 → 脚本 → 从文件导入 Python 插件…** 选择该 zip，按提示重启；再到 **设置 → 配置 Krita → Python 插件管理器** 勾选「馍馍拾色器」并重启一次。也可以解压后运行 `install.bat`。

## Changes in 1.0.0

- First public release: color engine with Oklab L / Oklab C, switchable Grayscale lightness standard, relative/absolute chroma modes and reachability hints.
- Complete picking UI: ring + S/V square, L/C/a/b strips, editable numeric fields, current-color HEX swatch and history.
- Panel, popup and preview overlay with persistent settings and Docker/popup synchronization.
- Editable keymap supporting all modifier + mouse-button combinations.
- Simplified Chinese / English manual and reproducible image assets.
- Release packaging: one Windows zip with bundled numpy 2.3.0, portable `install.bat`, GPL-3.0 license text and a tag-triggered GitHub Actions release workflow.
