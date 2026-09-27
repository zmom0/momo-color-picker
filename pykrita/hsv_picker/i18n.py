# -*- coding: utf-8 -*-
"""界面语言：Krita/系统语言为中文（zh*）时用中文，其它语言一律英文。

- `t(zh, en)` 返回当前语言文本；`is_zh()` 判断。
- 语言探测顺序：Krita 设置 language（若有）→ QLocale 默认/系统 uiLanguages → 环境变量 LANG/LC_ALL。
- 本模块只依赖 PyQt5.QtCore（krita 为可选导入），不参与数学层；math_core 不得引用。
"""

import os

_LANG = None


def _detect():
    candidates = []
    try:
        from krita import Krita
        value = Krita.instance().readSetting("", "language", "") or ""
        if value:
            candidates.append(value)
    except Exception:
        pass
    try:
        from PyQt5.QtCore import QLocale
        for loc in (QLocale(), QLocale.system()):
            try:
                candidates.extend(loc.uiLanguages() or [])
            except Exception:
                pass
            try:
                candidates.append(loc.name() or "")
            except Exception:
                pass
    except Exception:
        pass
    candidates.append(os.environ.get("LC_ALL", ""))
    candidates.append(os.environ.get("LANG", ""))
    for item in candidates:
        text = str(item or "").strip().lower()
        if text:
            return text
    return "en"


def lang_code():
    global _LANG
    if _LANG is None:
        _LANG = _detect()
    return _LANG


def is_zh():
    return lang_code().startswith("zh")


def t(zh, en):
    """按当前语言返回中文或英文文本。"""
    return zh if is_zh() else en
