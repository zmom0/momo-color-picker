# -*- coding: utf-8 -*-
"""自定义按键表的数据层（纯 Python，不 import krita / Qt）。

数据结构：
    keymap = {area_id: [(mods_id, button_id, action_id), ...], ...}

约定：
  · 同一区域内 (mods, button) 不允许重复；
  · action 必须属于该区域的动作清单；非法值一律落回 "none"；
  · 缺区域 / 缺行 / 格式损坏时按默认表补全（不抛异常）。
"""

import json

AREA_IDS = ("ring", "square", "lstrip", "cstrip", "astrip", "bstrip", "field")
BUTTON_IDS = ("left", "middle", "right")
MOD_IDS = ("none", "shift", "ctrl", "alt",
           "ctrl_shift", "shift_alt", "ctrl_alt", "ctrl_shift_alt")

# (id, 中文, English)
AREAS = (
    ("ring", "色相环", "Hue ring"),
    ("square", "S/V 方块", "SV square"),
    ("lstrip", "L 条", "L strip"),
    ("cstrip", "C 条", "C strip"),
    ("astrip", "a 条", "a strip"),
    ("bstrip", "b 条", "b strip"),
    ("field", "数值框", "Fields"),
)
BUTTONS = (("left", "左键", "Left"), ("middle", "中键", "Middle"),
           ("right", "右键", "Right"))
MODS = (("none", "无", "None"), ("shift", "Shift", "Shift"), ("ctrl", "Ctrl", "Ctrl"),
        ("alt", "Alt", "Alt"), ("ctrl_shift", "Ctrl+Shift", "Ctrl+Shift"),
        ("shift_alt", "Shift+Alt", "Shift+Alt"), ("ctrl_alt", "Ctrl+Alt", "Ctrl+Alt"),
        ("ctrl_shift_alt", "Ctrl+Shift+Alt", "Ctrl+Shift+Alt"))

ACTIONS = {
    "ring": (
        ("none", "无", "None"),
        ("hue_hsv", "转色相（纯 HSV）", "Rotate hue (plain HSV)"),
        ("hue_lock_lc_abs", "转色相 + 锁明度 + 锁绝对彩度",
         "Rotate hue + lock L + lock absolute chroma C"),
        ("hue_lock_lc_rel", "转色相 + 锁明度 + 锁相对彩度",
         "Rotate hue + lock L + lock relative chroma C_rel"),
    ),
    "square": (
        ("none", "无", "None"),
        ("abs", "绝对定位", "Absolute positioning"),
        ("abs_lock_l", "绝对定位 + 锁明度", "Absolute positioning + lock lightness"),
        ("abs_lock_c", "绝对定位 + 锁彩度", "Absolute positioning + lock chroma"),
        ("rel_l", "改明度（相对）", "Change lightness (relative)"),
        ("rel_c", "改彩度（相对）", "Change chroma (relative)"),
        ("s_only", "只改 S", "Saturation only"),
        ("v_only", "只改 V", "Value only"),
    ),
    "lstrip": (("none", "无", "None"), ("drag_l", "拖动改明度", "Drag to change lightness")),
    "cstrip": (("none", "无", "None"), ("drag_c", "拖动改彩度", "Drag to change chroma")),
    "astrip": (("none", "无", "None"),
               ("drag_self", "拖动只改本分量", "Drag to change only this component")),
    "bstrip": (("none", "无", "None"),
               ("drag_self", "拖动只改本分量", "Drag to change only this component")),
    "field": (
        ("none", "无", "None"),
        ("text_only", "只编辑文本", "Edit text only"),
        ("drag", "拖动调值", "Drag to adjust value"),
        ("drag_x2", "拖动调值 ×2", "Drag to adjust value x2"),
        ("drag_x4", "拖动调值 ×4", "Drag to adjust value x4"),
        ("drag_x0_5", "拖动调值 ×0.5", "Drag to adjust value x0.5"),
    ),
}

# 默认输入行（v7；唯一来源 = spec v4 §1 R14 / v3 spec §4.2 / v6 R20 / v7 R23）
# 环上默认：左键锁 L + 锁相对彩度 C_rel（转色相时浓淡比例恒定）、
# 中键与右键都锁 L + 锁绝对彩度 C（v7 R23：中键 = 右键，用户可在按键表里自行改其一）、
# Shift+左键 = 纯 HSV（只改色相，S/V 原样不动）。
DEFAULTS = {
    "ring": (("none", "left", "hue_lock_lc_rel"),
             ("none", "middle", "hue_lock_lc_abs"),
             ("none", "right", "hue_lock_lc_abs"),
             ("shift", "left", "hue_hsv")),
    "square": (("none", "left", "abs"),
               ("none", "middle", "rel_l"),
               ("none", "right", "rel_c"),
               ("shift", "left", "s_only"),
               ("alt", "left", "v_only")),
    "lstrip": (("none", "left", "drag_l"),),
    "cstrip": (("none", "left", "drag_c"),),
    "astrip": (("none", "left", "drag_self"),),
    "bstrip": (("none", "left", "drag_self"),),
    "field": (("none", "left", "drag"),
              ("ctrl", "left", "drag_x2"),
              ("ctrl_shift", "left", "drag_x4"),
              ("alt", "left", "drag_x0_5")),
}

# 数值框拖动倍率（action -> 相对标准速的倍数）
FIELD_DRAG_GAIN = {"drag": 1.0, "drag_x2": 2.0, "drag_x4": 4.0, "drag_x0_5": 0.5}


def _pick(table, key, zh=True):
    for row in table:
        if row[0] == key:
            return row[1] if zh else row[2]
    return str(key)


def area_label(area, zh=True):
    return _pick(AREAS, area, zh)


def button_label(btn, zh=True):
    return _pick(BUTTONS, btn, zh)


def mod_label(mods, zh=True):
    return _pick(MODS, mods, zh)


def action_ids(area):
    return tuple(a[0] for a in ACTIONS.get(area, ()))


def action_label(area, action, zh=True):
    return _pick(ACTIONS.get(area, ()), action, zh)


def input_label(mods, btn, zh=True):
    """输入列文本：无修饰键时只显示鼠标键，否则「修饰键 + 鼠标键」。"""
    b = button_label(btn, zh)
    if mods in (None, "none"):
        return b
    return "%s + %s" % (mod_label(mods, zh), b)


def default_keymap():
    return dict((a, list(DEFAULTS[a])) for a in AREA_IDS)


def mods_from_bools(shift, ctrl, alt, other=False):
    """Qt 修饰键位 -> MOD_IDS；Meta / Keypad / GroupSwitch 等未知位返回 None（调用方落回无修饰行）。"""
    shift, ctrl, alt = bool(shift), bool(ctrl), bool(alt)
    if other:
        return None
    if ctrl and shift and alt:
        return "ctrl_shift_alt"
    if ctrl and shift and not alt:
        return "ctrl_shift"
    if shift and alt and not ctrl:
        return "shift_alt"
    if ctrl and alt and not shift:
        return "ctrl_alt"
    if ctrl and not shift and not alt:
        return "ctrl"
    if shift and not ctrl and not alt:
        return "shift"
    if alt and not shift and not ctrl:
        return "alt"
    return "none"


def normalize(raw):
    """把任意来源的数据规范成合法 keymap：补默认、丢非法行、按区域去重。"""
    out = default_keymap()
    if not isinstance(raw, dict):
        return out
    for area in AREA_IDS:
        rows = raw.get(area)
        if not isinstance(rows, (list, tuple)):
            continue
        acts = action_ids(area)
        valid, seen = [], set()
        for row in rows:
            if not (isinstance(row, (list, tuple)) and len(row) == 3):
                continue
            mods, btn, act = str(row[0]), str(row[1]), str(row[2])
            if mods not in MOD_IDS or btn not in BUTTON_IDS:
                continue
            if act not in acts:
                act = "none"
            key = (mods, btn)
            if key in seen:
                continue
            seen.add(key)
            valid.append((mods, btn, act))
        out[area] = valid if valid else list(DEFAULTS[area])
    return out


def lookup(keymap, area, btn, mods):
    """(区域, 鼠标键, 修饰键) -> 动作 id。

    精确匹配优先；该鼠标键没有对应修饰键的行时，落回该鼠标键的「无修饰」行；
    两者都没有则返回 "none"。
    """
    rows = (keymap or {}).get(area) or []
    if mods in MOD_IDS:
        for m, b, a in rows:
            if b == btn and m == mods:
                return a
    for m, b, a in rows:
        if b == btn and m == "none":
            return a
    return "none"


def find_action(keymap, area, btn, mods):
    """精确查找某输入行的动作；没有该行返回 None（用于「是否已存在」判定）。"""
    for m, b, a in (keymap or {}).get(area) or []:
        if b == btn and m == mods:
            return a
    return None


def set_action(keymap, area, mods, btn, action):
    """原地把 (area, mods, btn) 的动作改成 action；行不存在则追加。返回 keymap。"""
    rows = keymap.setdefault(area, [])
    acts = action_ids(area)
    if action not in acts:
        action = "none"
    for i, (m, b, a) in enumerate(rows):
        if b == btn and m == mods:
            rows[i] = (mods, btn, action)
            return keymap
    rows.append((mods, btn, action))
    return keymap


def dump(keymap):
    """序列化为紧凑 JSON（持久化用）；键顺序固定、纯 ASCII 无关。"""
    data = dict((a, [list(r) for r in (keymap or {}).get(a) or DEFAULTS[a]])
                for a in AREA_IDS)
    return json.dumps(data, ensure_ascii=False, separators=(",", ":"))


def parse(text):
    """反序列化 + 规范化；空串 / 坏 JSON 一律返回默认表。"""
    try:
        raw = json.loads(text or "")
    except Exception:
        raw = None
    return normalize(raw)
