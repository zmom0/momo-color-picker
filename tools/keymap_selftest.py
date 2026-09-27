# -*- coding: utf-8 -*-
"""keymap_core 离线单测（系统 Python 即可，不依赖 Qt / Krita / numpy）。

覆盖 T-41：8 种修饰键组合映射、lookup 精确/落回、normalize 容错与旧表迁移、
set_action / parse / dump 往返；以及 T-42：ring 动作表不再含已删除的旧动作 ID。

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


def test_ring_actions_removed():
    ids = kc.action_ids("ring")
    check("T-42：ring 动作表不再含已删除动作",
          OLD_LOCK_L_ONLY not in ids, str(ids))
    check("T-42：ring 保留纯 HSV / 锁绝对 C / 锁相对 C_rel",
          set(ids) == {"none", "hue_hsv", "hue_lock_lc_abs", "hue_lock_lc_rel"},
          str(ids))
    illegal = []
    for area in kc.AREA_IDS:
        for mods, btn, act in kc.default_keymap().get(area, []):
            if mods not in kc.MOD_IDS or act not in kc.action_ids(area):
                illegal.append((area, mods, btn, act))
    check("默认表所有行都在合法 ID 集合内", not illegal, str(illegal))


def main():
    print("keymap_core 单测（T-41 / T-42）")
    test_mods()
    test_lookup()
    test_normalize_migrate()
    test_set_action_and_roundtrip()
    test_ring_actions_removed()
    print("")
    print("通过 %d 项，失败 %d 项" % (PASS[0], len(FAIL)))
    for f in FAIL:
        print("  - %s" % f)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
