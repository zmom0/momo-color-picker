#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""馍馍拾色器同源图文文档生成器（T-36）。

唯一内容源：
    manual/manual.md

生成物：
    README.md                          —— GitHub 首屏，图片前缀换成 pykrita/hsv_picker/manual/images/
    pykrita/hsv_picker/Manual.html     —— 单文件 HTML + 内嵌 CSS，图片保持 manual/images/（与插件同包）

图片约定：
    源里统一写 manual/images/xxx；真实文件只放 pykrita/hsv_picker/manual/images/（随插件包分发），
    生成 README 时把前缀替换成 pykrita/hsv_picker/manual/images/，生成 Manual.html 时保持原样。

用法：
    python tools/build_manual.py            生成（缺图只警告，不阻止生成）
    python tools/build_manual.py --check    校验（缺图 / 同源哈希 / english 锚点 / LF+UTF-8 / 生成物是否最新）
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

import markdown

# --------------------------------------------------------------------------- 路径与常量

ROOT = Path(__file__).resolve().parents[1]
SOURCE_PATH = ROOT / "manual" / "manual.md"
README_PATH = ROOT / "README.md"
MANUAL_PATH = ROOT / "pykrita" / "hsv_picker" / "Manual.html"

SOURCE_IMAGE_PREFIX = "manual/images/"
README_IMAGE_PREFIX = "pykrita/hsv_picker/manual/images/"
PLUGIN_IMAGE_DIR = ROOT / "pykrita" / "hsv_picker" / "manual" / "images"
ROOT_IMAGE_DIR = ROOT / "manual" / "images"

MD_EXTENSIONS = ["extra", "tables", "fenced_code", "sane_lists", "toc"]
IMAGE_REF_RE = re.compile(r"manual/images/([A-Za-z0-9._-]+)")
ENGLISH_HEADING_RE = re.compile(r"^##\s+English\s*$", re.MULTILINE)

# --------------------------------------------------------------------------- HTML 外壳

HTML_HEAD = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>馍馍拾色器 / Momo Color Picker — Manual</title>
<style>
  :root { color-scheme: light dark; }
  html, body { background: #fdfdfd; }
  body { font-family: "Segoe UI", "Microsoft YaHei", "PingFang SC", sans-serif;
         line-height: 1.75; font-size: 16px; max-width: 980px; margin: 0 auto;
         padding: 24px 26px 64px; color: #1e1e1e; }
  h1 { font-size: 27px; line-height: 1.35; margin: 0 0 8px; }
  h2 { font-size: 21px; margin: 30px 0 8px; border-bottom: 1px solid #d0d0d0; padding-bottom: 4px; }
  h3 { font-size: 18px; margin: 20px 0 6px; }
  h4 { font-size: 16.5px; margin: 16px 0 4px; }
  p, li { font-size: 16px; }
  img { max-width: 100%; height: auto; border-radius: 6px; }
  table { border-collapse: collapse; width: 100%; margin: 8px 0 12px; }
  th, td { border: 1px solid #c4c4c4; padding: 6px 10px; font-size: 14.5px;
           vertical-align: top; text-align: left; }
  th { background: #f0f0f0; }
  code { background: #f0f0f0; padding: 1px 4px; border-radius: 3px; font-size: 14.5px; }
  blockquote { margin: 8px 0; padding: 6px 12px; border-left: 3px solid #8aa;
               background: #f4f6f6; color: #444; }
  a { color: #2f6fbd; }
  @media (prefers-color-scheme: dark) {
    html, body { background: #232323; }
    body { color: #e8e8e8; }
    h2 { border-color: #555; }
    th, td { border-color: #555; }
    th { background: #333; }
    code, blockquote { background: #3a3a3a; }
    blockquote { border-left-color: #7aa; color: #cfcfcf; }
    a { color: #82b4ea; }
  }
</style>
</head>
<body>
"""

HTML_TAIL = "</body>\n</html>\n"

# --------------------------------------------------------------------------- 基础工具


def read_utf8(path: Path) -> str:
    """按 UTF-8 读取文本。"""
    return path.read_text(encoding="utf-8")


def write_utf8_lf(path: Path, text: str) -> None:
    """按 UTF-8 + LF 写入，保证幂等（newline='\\n'）。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def render_html_body(markdown_text: str) -> str:
    """Markdown -> HTML 正文片段（两端统一走同一套扩展，保证同源哈希一致）。"""
    return markdown.markdown(markdown_text, extensions=MD_EXTENSIONS, output_format="html5")


def build_readme(source_text: str) -> str:
    """README：源里的 manual/images/ 前缀换成 GitHub 上的仓库路径。"""
    return source_text.replace(SOURCE_IMAGE_PREFIX, README_IMAGE_PREFIX)


def build_manual_html(source_text: str) -> str:
    """Manual.html：单文件 HTML + 内嵌 CSS，图片前缀保持 manual/images/。"""
    return HTML_HEAD + render_html_body(source_text) + HTML_TAIL


def normalize_for_hash(html: str) -> str:
    """正文规范化：统一换行、把 README 的图片前缀映射回源前缀，再比较哈希。"""
    text = html.replace("\r\n", "\n").replace("\r", "\n")
    text = text.replace(README_IMAGE_PREFIX, SOURCE_IMAGE_PREFIX)
    return text.strip()


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def source_image_names(source_text: str) -> list:
    """按出现顺序返回去重后的图片文件名（匹配 manual/images/xxx）。"""
    names = []
    for name in IMAGE_REF_RE.findall(source_text):
        if name not in names:
            names.append(name)
    return names


def image_status(names: list) -> tuple:
    """返回 (missing, misplaced)。

    规范位置 = pykrita/hsv_picker/manual/images/（随插件包，README 也引用这里）；
    仓库根 manual/images/ 里如果只有副本，会记为 misplaced 并让 --check 失败。
    """
    missing, misplaced = [], []
    for name in names:
        if (PLUGIN_IMAGE_DIR / name).is_file():
            continue
        if (ROOT_IMAGE_DIR / name).is_file():
            misplaced.append(name)
        else:
            missing.append(name)
    return missing, misplaced


def extract_html_body(html: str) -> str:
    """取出 <body> ... </body> 之间的正文，用于同源哈希比较。"""
    start = html.find("<body>")
    end = html.rfind("</body>")
    if start < 0 or end < 0 or end < start:
        return ""
    return html[start + len("<body>"):end].strip("\n")


def text_file_problem(path: Path) -> str:
    """检查文件是否为 UTF-8 + LF；正常返回空字符串。"""
    data = path.read_bytes()
    if b"\r" in data:
        return "含 CR（要求 LF）"
    try:
        data.decode("utf-8")
    except UnicodeDecodeError as exc:
        return "不是合法 UTF-8：%s" % exc
    return ""


def anchor_problems(source_text: str, readme_text: str, manual_html: str) -> list:
    """检查 english 锚点链路：## English / 中文标题跳转 / HTML id。"""
    problems = []
    if not ENGLISH_HEADING_RE.search(source_text):
        problems.append("源里缺少 '## English' 二级标题")
    if "](#english)" not in source_text:
        problems.append("源里缺少 '[English ↓](#english)' 跳转链接")
    if "](#english)" not in readme_text:
        problems.append("README.md 里缺少指向 #english 的跳转链接")
    if 'id="english"' not in manual_html:
        problems.append('Manual.html 里缺少 id="english" 锚点')
    return problems


# --------------------------------------------------------------------------- 生成模式


def run_build() -> int:
    if not SOURCE_PATH.is_file():
        print("[build] 失败：找不到唯一内容源 %s" % SOURCE_PATH.relative_to(ROOT))
        return 1
    source_text = read_utf8(SOURCE_PATH)

    readme_text = build_readme(source_text)
    manual_html = build_manual_html(source_text)
    write_utf8_lf(README_PATH, readme_text)
    write_utf8_lf(MANUAL_PATH, manual_html)

    names = source_image_names(source_text)
    missing, misplaced = image_status(names)
    print("[build] 源：manual/manual.md（%d 字节，图片引用 %d 个）"
          % (len(source_text.encode("utf-8")), len(names)))
    print("[build] 已生成：README.md（%d 字节）"
          % len(readme_text.encode("utf-8")))
    print("[build] 已生成：pykrita/hsv_picker/Manual.html（%d 字节）"
          % len(manual_html.encode("utf-8")))
    if missing:
        print("[build] 警告：缺图 %d 张（生成照常进行，补图后请跑 --check）：" % len(missing))
        for name in missing:
            print("        - manual/images/%s" % name)
    if misplaced:
        print("[build] 警告：图片位置不对 %d 张（应放 pykrita/hsv_picker/manual/images/）：" % len(misplaced))
        for name in misplaced:
            print("        - manual/images/%s" % name)
    if not missing and not misplaced:
        print("[build] 图片引用全部就位。")
    return 0


# --------------------------------------------------------------------------- 校验模式


def run_check() -> int:
    problems = []
    if not SOURCE_PATH.is_file():
        print("[check] 失败：找不到唯一内容源 manual/manual.md")
        return 1
    source_text = read_utf8(SOURCE_PATH)

    # 1) 图片齐全
    names = source_image_names(source_text)
    missing, misplaced = image_status(names)
    print("[check] 源：manual/manual.md（图片引用 %d 个）" % len(names))
    print("[check] 图片：%d 就位，%d 缺失，%d 位置不对"
          % (len(names) - len(missing) - len(misplaced), len(missing), len(misplaced)))
    for name in missing:
        problems.append("缺图 manual/images/%s（期望 pykrita/hsv_picker/manual/images/%s）"
                        % (name, name))
        print("        - 缺 manual/images/%s" % name)
    for name in misplaced:
        problems.append("图片位置不对 manual/images/%s（README 引用 pykrita/hsv_picker/manual/images/%s）"
                        % (name, name))
        print("        - 位置不对 manual/images/%s" % name)

    # 2) 生成物存在 + 是最新版
    outputs = {}
    for path, expected_builder, label in (
            (README_PATH, build_readme, "README.md"),
            (MANUAL_PATH, build_manual_html, "Manual.html")):
        rel = path.relative_to(ROOT).as_posix()
        if not path.is_file():
            problems.append("%s 不存在，请先运行 python tools/build_manual.py" % rel)
            print("[check] %s：缺失" % rel)
            continue
        file_problem = text_file_problem(path)
        if file_problem:
            problems.append("%s %s" % (rel, file_problem))
            print("[check] %s：%s" % (rel, file_problem))
            continue
        actual = read_utf8(path)
        outputs[label] = actual
        if actual != expected_builder(source_text):
            problems.append("%s 与当前 manual.md 不同步，请重新运行 python tools/build_manual.py" % rel)
            print("[check] %s：与源不同步" % rel)
        else:
            print("[check] %s：与源同步（字节一致）" % rel)
        print("[check] %s：UTF-8 + LF" % rel)

    # 源文件本身也要求 LF + UTF-8
    source_problem = text_file_problem(SOURCE_PATH)
    if source_problem:
        problems.append("manual/manual.md %s" % source_problem)
        print("[check] manual/manual.md：%s" % source_problem)
    else:
        print("[check] manual/manual.md：UTF-8 + LF")

    # 3) 同源哈希：README / Manual 正文与源渲染结果一致
    if "README.md" in outputs and "Manual.html" in outputs:
        readme_text = outputs["README.md"]
        manual_html = outputs["Manual.html"]
        expected_hash = text_sha256(normalize_for_hash(render_html_body(source_text)))
        readme_hash = text_sha256(normalize_for_hash(render_html_body(readme_text)))
        manual_hash = text_sha256(normalize_for_hash(extract_html_body(manual_html)))
        print("[check] 同源哈希：source=%s README=%s Manual=%s"
              % (expected_hash[:12], readme_hash[:12], manual_hash[:12]))
        if readme_hash != expected_hash:
            problems.append("README.md 正文与源不同源（规范化哈希不一致）")
        if manual_hash != expected_hash:
            problems.append("Manual.html 正文与源不同源（规范化哈希不一致）")

        # 4) english 锚点
        anchor = anchor_problems(source_text, readme_text, manual_html)
        if anchor:
            problems.extend(anchor)
            for item in anchor:
                print("[check] 锚点：%s" % item)
        else:
            print("[check] english 锚点链路：OK")

    # 汇总
    if problems:
        print("[check] 结果：FAIL（%d 个问题）" % len(problems))
        for item in problems:
            print("        ! %s" % item)
        return 1
    print("[check] 结果：PASS")
    return 0


# --------------------------------------------------------------------------- 入口


def main(argv=None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(
        description="馍馍拾色器同源图文文档生成器：manual/manual.md -> README.md + Manual.html")
    parser.add_argument("--check", action="store_true",
                        help="只校验不写文件：图片齐全、同源哈希、english 锚点、LF/UTF-8、生成物是否最新")
    args = parser.parse_args(argv)
    if args.check:
        return run_check()
    return run_build()


if __name__ == "__main__":
    raise SystemExit(main())
