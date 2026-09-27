# -*- coding: utf-8 -*-
"""debug_log 模块离线单测（系统 Python，不依赖 Krita / Qt）。"""

import os
import shutil
import subprocess
import sys
import tempfile

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pykrita", "hsv_picker"))

import debug_log as dl  # noqa: E402


def main():
    tmp = tempfile.mkdtemp(prefix="hsvdbg_")
    path = os.path.join(tmp, "debug.log")
    passed = [0]
    failed = []

    def check(name, ok, detail=""):
        if ok:
            passed[0] += 1
        else:
            failed.append("%s %s" % (name, detail))

    check("默认关闭", dl.is_enabled() is False)
    dl.log("SHOULD_NOT_WRITE", a=1)
    check("关闭时不落盘", not os.path.exists(path))

    dl.enable(True, path=path, header={"panel": "selftest", "krita": "n/a"})
    check("开启生效", dl.is_enabled() is True)
    dl.log("DOWN", x=1, s=0.5)
    dl.log_throttled("MOVE", 1000, i=1)
    dl.log_throttled("MOVE", 1000, i=2)
    dl.enable(False)

    text = open(path, encoding="utf-8").read()
    lines = [ln for ln in text.splitlines() if ln.strip()]
    check("SES 头写入", any("SES" in ln and "panel=selftest" in ln for ln in lines), text)
    check("普通行写入", any("DOWN" in ln and "s=0.5" in ln for ln in lines), text)
    check("节流只留一条", sum(1 for ln in lines if "MOVE" in ln) == 1, text)
    check("关闭后不再写", dl.is_enabled() is False)

    # 会话覆盖：新 Krita 进程第一次开启日志 → 旧内容被覆盖
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("OLD_SESSION_JUNK\n")
    dl._SESSION_STARTED = False
    dl.enable(True, path=path, header={"panel": "second"})
    dl.log("NEW_SESSION", a=2)
    dl.enable(False)
    text2 = open(path, encoding="utf-8").read()
    check("新会话覆盖旧日志", "OLD_SESSION_JUNK" not in text2 and "NEW_SESSION" in text2, text2)
    check("覆盖后仍有会话头", "panel=second" in text2, text2)

    # 轮转：外部先把文件撑过 2MB，再写一条触发轮转
    dl.enable(True, path=path)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write("x" * (2 * 1024 * 1024 + 10))
    dl.log("AFTER_BIG", z=1)
    dl.enable(False)
    check("超限轮转为 .1", os.path.exists(path + ".1"), "")
    check("轮转后新文件含新行", "AFTER_BIG" in open(path, encoding="utf-8").read(), "")

    # numpy 导入失败 -> 系统临时目录留诊断；成功导入 -> 清掉旧诊断
    src_init = os.path.join(ROOT, "pykrita", "hsv_picker", "__init__.py")
    work = tempfile.mkdtemp(prefix="hsvimp_")
    try:
        pkg_parent = os.path.join(work, "pkg")
        pkg = os.path.join(pkg_parent, "hsv_picker")
        os.makedirs(pkg)
        shutil.copyfile(src_init, os.path.join(pkg, "__init__.py"))
        with open(os.path.join(pkg, "hsv_picker.py"), "w",
                  encoding="utf-8", newline="\n") as fh:
            fh.write("# dummy\n")
        fake = os.path.join(work, "fakenp")
        os.makedirs(os.path.join(fake, "numpy"))
        with open(os.path.join(fake, "numpy", "__init__.py"), "w",
                  encoding="utf-8", newline="\n") as fh:
            fh.write("raise ImportError('selftest simulated numpy missing')\n")
        temphome = os.path.join(work, "temp")
        os.makedirs(temphome)
        logp = os.path.join(temphome, "hsv_picker_import_error.log")
        env = dict(os.environ)
        env["TEMP"] = temphome
        env["TMP"] = temphome
        code_fail = ("import sys\n"
                     "sys.path.insert(0, %r)\n"
                     "sys.path.insert(0, %r)\n"
                     "import hsv_picker\n" % (pkg_parent, fake))
        subprocess.run([sys.executable, "-c", code_fail], env=env, cwd=work,
                       capture_output=True, text=True, timeout=60)
        text_log = open(logp, encoding="utf-8").read() if os.path.isfile(logp) else ""
        check("numpy 失败日志写入系统临时目录（可诊断）",
              "selftest simulated numpy missing" in text_log
              and "numpy 导入失败" in text_log, logp)
        code_ok = ("import sys\n"
                   "sys.path.insert(0, %r)\n"
                   "import hsv_picker\n" % (pkg_parent,))
        subprocess.run([sys.executable, "-c", code_ok], env=env, cwd=work,
                       capture_output=True, text=True, timeout=60)
        check("numpy 成功导入清理旧诊断日志", not os.path.isfile(logp), logp)
    finally:
        shutil.rmtree(work, ignore_errors=True)

    shutil.rmtree(tmp, ignore_errors=True)
    print("通过 %d 项，失败 %d 项" % (passed[0], len(failed)))
    for item in failed:
        print("  -", item)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
