# -*- coding: utf-8 -*-
"""keymap_core 离线单测（系统 Python 即可，不依赖 Qt / Krita / numpy）。

覆盖 T-41：8 种修饰键组合映射、lookup 精确/落回、normalize 容错与旧表迁移、
set_action / parse / dump 往返；T-42：ring 动作表不再含旧动作 hue_lock_l；
T-53：mod_bits/contains/remove、环 4 行 / 方块 3 行新默认、旧默认整组迁移、自定义不动。

用法：
    python tools/keymap_selftest.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pykrita" / "hsv_picker"))
import keymap_core as kc                                    # noqa: E402

FAIL = []
PASS = [0]


def check(name, ok, detail=""):
    if ok:
        PASS[0] += 1
        print("  PASS %s" % name)
    else:
        FAIL.append("%s %s" % (name, detail))
        print("  FAIL %s  %s" % (name, detail))


EXPECT_ORDER = ("none", "shift", "ctrl", "alt",
                "ctrl_shift", "shift_alt", "ctrl_alt", "ctrl_shift_alt")
EXPECT_BOOLS = {
    "none": (0, 0, 0),
    "shift": (1, 0, 0),
    "ctrl": (0, 1, 0),
    "alt": (0, 0, 1),
    "ctrl_shift": (1, 1, 0),
    "shift_alt": (1, 0, 1),
    "ctrl_alt": (0, 1, 1),
    "ctrl_shift_alt": (1, 1, 1),
}
ZH_LABELS = ["无", "Shift", "Ctrl", "Alt", "Ctrl+Shift", "Shift+Alt",
             "Ctrl+Alt", "Ctrl+Shift+Alt"]
# T-42 已删除的旧动作 ID；运行时拼接（join 不会被常量折叠），避免正式源码里残留该字面量
OLD_LOCK_L_ONLY = "".join(("hue_", "lock_l"))
EN_LABELS = ["None", "Shift", "Ctrl", "Alt", "Ctrl+Shift", "Shift+Alt",
             "Ctrl+Alt", "Ctrl+Shift+Alt"]


def test_mods():
    check("MOD_IDS == 8 种且顺序固定",
          tuple(kc.MOD_IDS) == EXPECT_ORDER, str(kc.MOD_IDS))
    check("MODS 与 MOD_IDS 一一对应且中英 label 齐全",
          tuple(m[0] for m in kc.MODS) == EXPECT_ORDER
          and [m[1] for m in kc.MODS] == ZH_LABELS
          and [m[2] for m in kc.MODS] == EN_LABELS,
          str(kc.MODS))
    bad = [mid for mid, bits in EXPECT_BOOLS.items()
           if kc.mods_from_bools(*bits) != mid]
    check("mods_from_bools 映射全部 8 种组合", not bad, "bad=%s" % bad)
    check("未知修饰位 other=True 返回 None（含与已知位同时按下）",
          kc.mods_from_bools(0, 0, 0, True) is None
          and kc.mods_from_bools(1, 0, 1, True) is None
          and kc.mods_from_bools(1, 1, 1, True) is None,
          "0/1/2 位均须 None")
    check("mod_bits 返回三布尔位、未知 ID 全 False",
          kc.mod_bits("shift_alt") == (True, False, True)
          and kc.mod_bits("ctrl_shift_alt") == (True, True, True)
          and kc.mod_bits("none") == (False, False, False)
          and kc.mod_bits("bogus") == (False, False, False),
          "shift_alt=%s bogus=%s" % (kc.mod_bits("shift_alt"), kc.mod_bits("bogus")))
    check("mod_contains：全部位按下才算包含；none 恒 False",
          kc.mod_contains("shift", "shift")
          and kc.mod_contains("ctrl_shift_alt", "shift_alt")
          and kc.mod_contains("ctrl_shift", "ctrl")
          and not kc.mod_contains("shift", "alt")
          and not kc.mod_contains("ctrl_alt", "shift_alt")
          and not kc.mod_contains("shift", "none")
          and not kc.mod_contains("none", "shift"),
          "shift<alt=%s ctrl_alt<shift_alt=%s" % (
              kc.mod_contains("shift", "alt"), kc.mod_contains("ctrl_alt", "shift_alt")))
    check("mod_remove：去掉切换位后返回剩余 MOD_ID",
          kc.mod_remove("shift_alt", "shift") == "alt"
          and kc.mod_remove("ctrl_shift_alt", "ctrl_shift") == "alt"
          and kc.mod_remove("ctrl_shift_alt", "shift_alt") == "ctrl"
          and kc.mod_remove("shift", "shift") == "none"
          and kc.mod_remove("ctrl_shift", "alt") == "ctrl_shift",
          "shift_alt-shift=%s" % kc.mod_remove("shift_alt", "shift"))


def test_lookup():
    km = kc.default_keymap()
    kc.set_action(km, "square", "shift_alt", "middle", "v_only")
    kc.set_action(km, "square", "ctrl_alt", "left", "s_only")
    check("lookup 精确命中新组合",
          kc.lookup(km, "square", "middle", "shift_alt") == "v_only"
          and kc.lookup(km, "square", "left", "ctrl_alt") == "s_only",
          "%s / %s" % (kc.lookup(km, "square", "middle", "shift_alt"),
                       kc.lookup(km, "square", "left", "ctrl_alt")))
    check("lookup 未配组合落回同鼠标键的 none 行",
          kc.lookup(km, "square", "middle", "ctrl_shift_alt") == "rel_l"
          and kc.lookup(km, "square", "middle", "none") == "rel_l",
          str(kc.lookup(km, "square", "middle", "ctrl_shift_alt")))
    bare = {"square": [("none", "left", "abs")]}
    check("lookup 无该鼠标键任何行 -> none",
          kc.lookup(bare, "square", "right", "ctrl_alt") == "none"
          and kc.lookup(bare, "square", "right", "none") == "none",
          str(kc.lookup(bare, "square", "right", "ctrl_alt")))
    check("find_action 区分「无该行」与「动作 none」",
          kc.find_action(km, "square", "middle", "shift_alt") == "v_only"
          and kc.find_action(km, "square", "right", "shift_alt") is None,
          str(kc.find_action(km, "square", "right", "shift_alt")))


def test_normalize_migrate():
    out = kc.normalize(None)
    check("normalize(None) 返回完整默认表",
          isinstance(out, dict) and all(out.get(a) for a in kc.AREA_IDS),
          str(sorted(out)))
    old = {"ring": [["none", "left", OLD_LOCK_L_ONLY],
                    ["shift", "left", "hue_hsv"]],
           "field": [["none", "left", "drag"],
                     ["ctrl", "left", "drag_x2"]]}
    norm = kc.normalize(old)
    check("旧持久化表含已删除动作 -> 该行落为 none，不抛错",
          kc.lookup(norm, "ring", "left", "none") == "none"
          and kc.find_action(norm, "ring", "left", "none") == "none",
          str(norm.get("ring")))
    check("旧 5 种修饰键 ID 继续有效",
          all(kc.lookup(kc.normalize({"field": [[m, "left", "drag"]]}),
                        "field", "left", m) == "drag" for m in
              ("none", "shift", "ctrl", "ctrl_shift", "alt")),
          "")
    bad = {"ring": [["meta", "left", "hue_hsv"],
                    ["ctrl_alt", "left", "hue_hsv"],
                    ["ctrl_alt", "left", "hue_hsv"]],
           "square": "broken"}
    n2 = kc.normalize(bad)
    check("normalize 丢弃未知修饰键 / 同输入去重",
          "meta" not in [m for m, _b, _a in n2["ring"]]
          and kc.lookup(n2, "ring", "left", "ctrl_alt") == "hue_hsv"
          and len([1 for m, b, _a in n2["ring"] if (m, b) == ("ctrl_alt", "left")]) == 1,
          str(n2.get("ring")))
    n3 = kc.normalize({"ring": [["shift_alt", "left", "bogus"]]})
    check("normalize 非法动作落 none",
          kc.lookup(n3, "ring", "left", "shift_alt") == "none",
          str(n3.get("ring")))
    check("normalize 缺区域按默认补全 / 坏区域不抛错",
          len(n2["square"]) == len(kc.DEFAULTS["square"])
          and isinstance(kc.normalize({"ring": "xxx"}), dict),
          str(n2.get("square")))


def test_set_action_and_roundtrip():
    km = kc.default_keymap()
    kc.set_action(km, "ring", "shift_alt", "right", "hue_hsv")
    check("set_action 追加新输入行",
          kc.lookup(km, "ring", "right", "shift_alt") == "hue_hsv",
          str(km.get("ring")))
    kc.set_action(km, "ring", "shift_alt", "right", "hue_lock_lc_rel")
    rows = [1 for m, b, _a in km["ring"] if (m, b) == ("shift_alt", "right")]
    check("set_action 对已有行原地改写、不重复追加",
          len(rows) == 1
          and kc.lookup(km, "ring", "right", "shift_alt") == "hue_lock_lc_rel",
          str(km.get("ring")))
    kc.set_action(km, "field", "ctrl_alt", "left", "bogus")
    check("set_action 非法动作落 none",
          kc.lookup(km, "field", "left", "ctrl_alt") == "none",
          str(kc.lookup(km, "field", "left", "ctrl_alt")))
    text = kc.dump(km)
    check("dump 是 JSON 文本且含新组合",
          json.loads(text)["ring"] and "ctrl_alt" in text,
          text[:120])
    check("parse(dump()) 规范化后往返一致",
          kc.normalize(kc.parse(text)) == kc.normalize(km),
          "")
    check("parse 空串 / 坏 JSON 回默认表且不抛错",
          kc.parse("") == kc.default_keymap()
          and kc.parse("{oops") == kc.default_keymap(),
          "")


def test_ring_actions_t51():
    ids = kc.action_ids("ring")
    check("T-42：ring 动作表不再含旧 hue_lock_l",
          OLD_LOCK_L_ONLY not in ids, str(ids))
    check("T-51 ring 动作表：cur/other 新增，abs/rel/hue_hsv 保留",
          set(ids) == {"none", "hue_hsv", "hue_lock_lc_cur", "hue_lock_lc_other",
                       "hue_lock_lc_abs", "hue_lock_lc_rel"}, str(ids))
    illegal = []
    for area in kc.AREA_IDS:
        for mods, btn, act in kc.default_keymap().get(area, []):
            if mods not in kc.MOD_IDS or act not in kc.action_ids(area):
                illegal.append((area, mods, btn, act))
    check("默认表所有行都在合法 ID 集合内", not illegal, str(illegal))


def test_t53_defaults_and_migration():
    """T-53：环 4 行 / 方块 3 行；旧默认整组迁移；自定义表原样保留。"""
    km = kc.default_keymap()
    check("T-53 环默认 4 行：左/中/右=cur、Ctrl+左=纯 HSV，Shift 无默认行",
          tuple(km["ring"]) == kc.DEFAULTS["ring"] and len(km["ring"]) == 4
          and kc.lookup(km, "ring", "left", "none") == "hue_lock_lc_cur"
          and kc.lookup(km, "ring", "middle", "none") == "hue_lock_lc_cur"
          and kc.lookup(km, "ring", "right", "none") == "hue_lock_lc_cur"
          and kc.lookup(km, "ring", "left", "ctrl") == "hue_hsv"
          and kc.find_action(km, "ring", "left", "shift") is None
          and kc.find_action(km, "ring", "middle", "shift") is None
          and kc.find_action(km, "ring", "right", "shift") is None,
          str(km["ring"]))
    check("T-53 方块默认 3 行：左=abs、中=rel_l、右=rel_c，Shift 无默认行",
          tuple(km["square"]) == kc.DEFAULTS["square"] and len(km["square"]) == 3
          and kc.lookup(km, "square", "left", "none") == "abs"
          and kc.lookup(km, "square", "middle", "none") == "rel_l"
          and kc.lookup(km, "square", "right", "none") == "rel_c"
          and kc.find_action(km, "square", "middle", "shift") is None
          and kc.find_action(km, "square", "right", "shift") is None,
          str(km["square"]))
    check("T-53 *_other 动作保留可选、默认表不含",
          "hue_lock_lc_other" in kc.action_ids("ring")
          and "rel_l_other" in kc.action_ids("square")
          and "rel_c_other" in kc.action_ids("square")
          and all(kc.find_action(km, "square", b, "shift") is None
                  for b in ("left", "middle", "right"))
          and all(kc.find_action(km, "ring", b, "shift") is None
                  for b in ("left", "middle", "right")),
          "%s / %s" % (kc.action_ids("ring"), kc.action_ids("square")))
    old_ids = {"abs_lock_l", "abs_lock_c", "s_only", "v_only",
               "hue_lock_lc_abs", "hue_lock_lc_rel"}
    check("T-53 旧动作保留为可选、默认表不含",
          old_ids <= (set(kc.action_ids("square")) | set(kc.action_ids("ring")))
          and all(kc.find_action(km, "square", "left", "none") != a
                  and kc.find_action(km, "square", "middle", "none") != a
                  for a in ("abs_lock_l", "abs_lock_c", "s_only", "v_only")),
          str(sorted(old_ids)))

    v7_ring = {"ring": [["none", "left", "hue_lock_lc_rel"],
                        ["none", "middle", "hue_lock_lc_abs"],
                        ["none", "right", "hue_lock_lc_abs"],
                        ["shift", "left", "hue_hsv"]]}
    n = kc.normalize(v7_ring)
    check("T-53 v7 环旧默认整组迁移为新默认 4 行",
          n["ring"] == list(kc.DEFAULTS["ring"]),
          str(n["ring"]))

    v7_square = [["none", "left", "abs"], ["none", "middle", "rel_l"],
                 ["none", "right", "rel_c"], ["shift", "left", "s_only"],
                 ["alt", "left", "v_only"]]
    n = kc.normalize({"square": [list(r) for r in v7_square]})
    check("T-53 v7 方块旧默认整组迁移为新默认 3 行",
          n["square"] == list(kc.DEFAULTS["square"]),
          str(n["square"]))

    t48_square = [list(r) for r in v7_square] + [
        ["shift", "middle", "abs_lock_c"], ["shift", "right", "abs_lock_l"]]
    n = kc.normalize({"square": t48_square})
    check("T-53 T-48 方块旧默认（7 行）整组迁移为新默认 3 行",
          n["square"] == list(kc.DEFAULTS["square"]),
          str(n["square"]))

    t51_ring = [["none", "left", "hue_lock_lc_cur"],
                ["none", "middle", "hue_lock_lc_cur"],
                ["none", "right", "hue_lock_lc_cur"],
                ["shift", "left", "hue_lock_lc_other"],
                ["shift", "middle", "hue_lock_lc_other"],
                ["shift", "right", "hue_lock_lc_other"],
                ["ctrl", "left", "hue_hsv"]]
    n = kc.normalize({"ring": [list(r) for r in t51_ring]})
    check("T-53 T-51 环旧默认（7 行）整组迁移为新默认 4 行",
          n["ring"] == list(kc.DEFAULTS["ring"]),
          str(n["ring"]))

    t51_square = [["none", "left", "abs"], ["none", "middle", "rel_l"],
                  ["none", "right", "rel_c"],
                  ["shift", "middle", "rel_l_other"],
                  ["shift", "right", "rel_c_other"]]
    n = kc.normalize({"square": [list(r) for r in t51_square]})
    check("T-53 T-51 方块旧默认（5 行）整组迁移为新默认 3 行",
          n["square"] == list(kc.DEFAULTS["square"]),
          str(n["square"]))

    extra = [list(r) for r in v7_square] + [["ctrl", "left", "abs"]]
    n = kc.normalize({"square": extra})
    check("T-53 旧默认 + 额外一行 -> 自定义表，整表原样保留不迁移",
          len(n["square"]) == 6
          and kc.lookup(n, "square", "left", "shift") == "s_only"
          and kc.lookup(n, "square", "left", "alt") == "v_only"
          and kc.find_action(n, "square", "middle", "shift") is None
          and kc.lookup(n, "square", "middle", "shift") == "rel_l",
          str(n["square"]))

    single = kc.normalize({"square": [["shift", "left", "s_only"]]})
    check("T-53 单行旧动作（非整组旧默认）原样保留",
          kc.lookup(single, "square", "left", "shift") == "s_only"
          and single["square"] == [("shift", "left", "s_only")],
          str(single["square"]))

    custom_other = kc.normalize({"square": [["none", "left", "abs"],
                                            ["shift", "middle", "rel_l_other"],
                                            ["alt", "right", "rel_c_other"]]})
    check("T-53 自定义表里的 *_other 行照旧生效、不被迁移吃掉",
          len(custom_other["square"]) == 3
          and kc.lookup(custom_other, "square", "middle", "shift") == "rel_l_other"
          and kc.lookup(custom_other, "square", "right", "alt") == "rel_c_other",
          str(custom_other["square"]))

    custom = {"ring": [["ctrl_alt", "right", "hue_hsv"]],
              "square": [["ctrl", "middle", "v_only"]]}
    nc = kc.normalize(custom)
    check("T-53 纯自定义表不补新默认行",
          nc["ring"] == [("ctrl_alt", "right", "hue_hsv")]
          and nc["square"] == [("ctrl", "middle", "v_only")],
          str(nc))
    check("T-53 normalize(default) 幂等", kc.normalize(km) == km)


def main():
    print("keymap_core 单测（T-41 / T-42 / T-53）")
    test_mods()
    test_lookup()
    test_normalize_migrate()
    test_set_action_and_roundtrip()
    test_ring_actions_t51()
    test_t53_defaults_and_migration()
    print("")
    print("通过 %d 项，失败 %d 项" % (PASS[0], len(FAIL)))
    for f in FAIL:
        print("  - %s" % f)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
