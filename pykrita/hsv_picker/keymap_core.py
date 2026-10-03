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
        ("hue_lock_lc_cur", "转色相 + 锁明度 + 锁当前彩度口径",
         "Rotate hue + lock L + lock current chroma scale"),
        ("hue_lock_lc_other", "转色相 + 锁明度 + 锁另一彩度口径",
         "Rotate hue + lock L + lock the other chroma scale"),
        ("hue_lock_lc_abs", "转色相 + 锁明度 + 锁绝对彩度",
         "Rotate hue + lock L + lock absolute chroma C"),
        ("hue_lock_lc_rel", "转色相 + 锁明度 + 锁相对彩度",
         "Rotate hue + lock L + lock relative chroma C_rel"),
    ),
    "square": (
        ("none", "无", "None"),
        ("abs", "点哪到哪", "Absolute positioning"),
        ("abs_lock_l", "绝对定位 + 锁明度", "Absolute positioning + lock lightness"),
        ("abs_lock_c", "绝对定位 + 锁彩度", "Absolute positioning + lock chroma"),
        ("rel_l", "改明度（锁当前彩度口径）",
         "Change lightness (locks current chroma scale)"),
        ("rel_l_other", "改明度（锁另一彩度口径）",
         "Change lightness (locks the other chroma scale)"),
        ("rel_c", "改彩度（锁明度）", "Change chroma (locks lightness)"),
        ("rel_c_other", "改彩度（锁明度，临时另一口径）",
         "Change chroma (locks lightness, temporary other scale)"),
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

# 默认输入行（T-53：临时口径由设置「临时切换键」统一翻转，默认 Shift）
# 环上默认：左/中/右 = 转色相 + 锁 L + 锁当前口径 C；Ctrl+左 = 纯 HSV。
# 方块内默认：左 = 点哪到哪；中 = 改明度（锁当前口径）；右 = 改彩度（锁明度）。
# 按住临时切换键再按基础行 = 同一动作锁另一口径（动作解析时翻转，不占默认行）。
DEFAULTS = {
    "ring": (("none", "left", "hue_lock_lc_cur"),
             ("none", "middle", "hue_lock_lc_cur"),
             ("none", "right", "hue_lock_lc_cur"),
             ("ctrl", "left", "hue_hsv")),
    "square": (("none", "left", "abs"),
               ("none", "middle", "rel_l"),
               ("none", "right", "rel_c")),
    "lstrip": (("none", "left", "drag_l"),),
    "cstrip": (("none", "left", "drag_c"),),
    "astrip": (("none", "left", "drag_self"),),
    "bstrip": (("none", "left", "drag_self"),),
    "field": (("none", "left", "drag"),
              ("ctrl", "left", "drag_x2"),
              ("ctrl_shift", "left", "drag_x4"),
              ("alt", "left", "drag_x0_5")),
}

# T-53 旧默认表迁移：区域的**整组行集合**与某个旧默认集合完全相等才替换为新默认；
# 多一行/少一行都视为自定义表，原样保留（R21）。旧动作 ID 仍可作为可选动作手动绑定。
_OLD_DEFAULT_SETS = {
    "ring": (
        # v7：左/中/右 = rel / abs / abs，Shift+左 = 纯 HSV
        frozenset({("none", "left", "hue_lock_lc_rel"),
                   ("none", "middle", "hue_lock_lc_abs"),
                   ("none", "right", "hue_lock_lc_abs"),
                   ("shift", "left", "hue_hsv")}),
        # T-51/T-52 旧默认：左/中/右 = cur，Shift 三键 = other，Ctrl+左 = 纯 HSV
        frozenset({("none", "left", "hue_lock_lc_cur"),
                   ("none", "middle", "hue_lock_lc_cur"),
                   ("none", "right", "hue_lock_lc_cur"),
                   ("shift", "left", "hue_lock_lc_other"),
                   ("shift", "middle", "hue_lock_lc_other"),
                   ("shift", "right", "hue_lock_lc_other"),
                   ("ctrl", "left", "hue_hsv")}),
    ),
    "square": (
        # v7：左/中/右 = abs / rel_l / rel_c，Shift+左 = s_only，Alt+左 = v_only
        frozenset({("none", "left", "abs"), ("none", "middle", "rel_l"),
                   ("none", "right", "rel_c"), ("shift", "left", "s_only"),
                   ("alt", "left", "v_only")}),
        # T-48：v7 + Shift+中/右 = abs_lock_c / abs_lock_l
        frozenset({("none", "left", "abs"), ("none", "middle", "rel_l"),
                   ("none", "right", "rel_c"), ("shift", "left", "s_only"),
                   ("alt", "left", "v_only"),
                   ("shift", "middle", "abs_lock_c"),
                   ("shift", "right", "abs_lock_l")}),
        # T-51/T-52 旧默认：左/中/右 = abs / rel_l / rel_c，Shift+中/右 = rel_l_other / rel_c_other
        frozenset({("none", "left", "abs"), ("none", "middle", "rel_l"),
                   ("none", "right", "rel_c"),
                   ("shift", "middle", "rel_l_other"),
                   ("shift", "right", "rel_c_other")}),
    ),
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


def mod_bits(mods):
    """MOD_ID -> (shift, ctrl, alt) 三个布尔位；未知 ID 返回全 False。"""
    bits = {"none": (0, 0, 0), "shift": (1, 0, 0), "ctrl": (0, 1, 0),
            "alt": (0, 0, 1), "ctrl_shift": (1, 1, 0), "shift_alt": (1, 0, 1),
            "ctrl_alt": (0, 1, 1), "ctrl_shift_alt": (1, 1, 1)}.get(str(mods))
    return tuple(bool(x) for x in (bits or (0, 0, 0)))


def mod_contains(outer, inner):
    """outer 是否包含 inner 的全部修饰位；inner = "none" 恒为 False（不触发自动翻转）。"""
    ib = mod_bits(inner)
    if not any(ib):
        return False
    ob = mod_bits(outer)
    return all(i <= o for o, i in zip(ob, ib))


def mod_remove(outer, inner):
    """从 outer 中去掉 inner 的全部修饰位，返回剩余 MOD_ID（可能为 "none"）。"""
    ob, ib = mod_bits(outer), mod_bits(inner)
    return mods_from_bools(*(bool(o and not i) for o, i in zip(ob, ib)))


def normalize(raw):
    """把任意来源的数据规范成合法 keymap：补默认、丢非法行、按区域去重、整组旧默认迁移。"""
    out = default_keymap()
    if not isinstance(raw, dict):
        return out
    for area in AREA_IDS:
        rows = raw.get(area)
        if not isinstance(rows, (list, tuple)):
            continue
        acts = action_ids(area)
        # 先扫有效行的 (mods, btn, action) 集合：与某个旧默认集合完全相等才整组迁移
        present = set()
        for row in rows:
            if isinstance(row, (list, tuple)) and len(row) == 3:
                m, b, a = str(row[0]), str(row[1]), str(row[2])
                if m in MOD_IDS and b in BUTTON_IDS:
                    present.add((m, b, a if a in acts else "none"))
        if present in _OLD_DEFAULT_SETS.get(area, ()):
            out[area] = list(DEFAULTS[area])
            continue
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
