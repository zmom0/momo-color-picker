# -*- coding: utf-8 -*-
"""诊断日志模式（T-16）：把拾色器交互与内部状态写入文件，供离线排查。

约束：
- 只用标准库，不 import krita / PyQt5（可用系统 Python 单测）。
- 默认关闭；关闭时所有公开接口只做一次 bool 判断，不产生可感知开销。
- 任何写盘异常都不得影响插件功能：捕获后自动停用。
- 单文件超过 _MAX_BYTES 时轮转为 "<path>.1"（只保留一份轮转）。
- 环境变量 HSV_PICKER_DEBUG_LOG 可覆盖路径（测试用）。
"""

import os
import sys
import time

_ENABLED = False
_PATH = ""
_BUF = []
_BUFSIZE = 30            # 攒够多少行刷一次盘
_FLUSH_INTERVAL = 0.5    # 或距上次刷盘超过该秒数
_MAX_BYTES = 2 * 1024 * 1024
_LAST_FLUSH = 0.0
_THROTTLE = {}           # event -> 上次写盘 monotonic 时间
_WARNED = False
_SESSION_STARTED = False  # 本进程是否已开启过日志（第一次开启覆盖旧日志）


def default_path():
    """默认日志路径；HSV_PICKER_DEBUG_LOG 优先，其次 %APPDATA%/krita。"""
    override = os.environ.get("HSV_PICKER_DEBUG_LOG")
    if override:
        return override
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "krita", "hsv_picker_debug.log")


def configure(path=None):
    """设置日志文件路径，返回绝对路径。"""
    global _PATH
    _PATH = os.path.abspath(path or default_path())
    return _PATH


def path():
    return _PATH


def is_enabled():
    return _ENABLED


def enable(on, path=None, header=None):
    """开关日志；开启时可传 header 字典写一条会话头。

    每个 Krita 进程第一次开启时**覆盖**旧日志（同一进程内再次开关则追加）。
    """
    global _ENABLED, _LAST_FLUSH
    if path:
        configure(path)
    if on:
        if not _PATH:
            configure()
        _truncate_for_session()
        _ENABLED = True
        _LAST_FLUSH = 0.0
        if header is not None:
            log("SES", **header)
    else:
        flush(force=True)
        _ENABLED = False
        del _BUF[:]
        _THROTTLE.clear()
    return _ENABLED


def _truncate_for_session():
    """本进程第一次开启日志：把上次会话的日志覆盖掉。"""
    global _SESSION_STARTED
    if _SESSION_STARTED:
        return
    _SESSION_STARTED = True
    try:
        folder = os.path.dirname(_PATH)
        if folder:
            os.makedirs(folder, exist_ok=True)
        with open(_PATH, "w", encoding="utf-8", newline="\n"):
            pass
    except Exception:
        pass


def _fmt(value):
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, float):
        return "%.6g" % value
    text = str(value).replace(" ", "_").replace("\n", "\\n").replace("\r", "")
    return text[:200]


def _stamp():
    now = time.time()
    return "%s.%03d" % (time.strftime("%H:%M:%S", time.localtime(now)),
                        int((now % 1.0) * 1000.0))


def log(event, **fields):
    """写一条日志（event + 若干字段）。未开启时零副作用。"""
    if not _ENABLED:
        return
    parts = [_stamp(), str(event)]
    for key in fields:
        parts.append("%s=%s" % (key, _fmt(fields[key])))
    _BUF.append(" ".join(parts))
    if len(_BUF) >= _BUFSIZE:
        flush(force=True)
    else:
        flush()


def log_throttled(event, min_ms, **fields):
    """同一事件名在 min_ms 毫秒内最多记一条（JUMP 等关键事件不要用它）。"""
    if not _ENABLED:
        return
    now = time.monotonic()
    last = _THROTTLE.get(event)
    if last is not None and (now - last) * 1000.0 < float(min_ms):
        return
    _THROTTLE[event] = now
    log(event, **fields)


def flush(force=False):
    """把缓冲写盘；默认最多每 _FLUSH_INTERVAL 秒落一次盘。"""
    global _LAST_FLUSH
    if not _BUF:
        return
    if not _ENABLED and not force:
        return
    now = time.monotonic()
    if not force and (now - _LAST_FLUSH) < _FLUSH_INTERVAL:
        return
    _LAST_FLUSH = now
    text = "\n".join(_BUF) + "\n"
    del _BUF[:]
    try:
        _rotate_if_needed()
        with open(_PATH, "a", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
    except Exception:
        _disable_on_error()


def _rotate_if_needed():
    try:
        if os.path.isfile(_PATH) and os.path.getsize(_PATH) > _MAX_BYTES:
            os.replace(_PATH, _PATH + ".1")
    except Exception:
        pass


def _disable_on_error():
    global _ENABLED, _WARNED
    _ENABLED = False
    del _BUF[:]
    if not _WARNED:
        _WARNED = True
        try:
            sys.stderr.write("[hsv_picker] 诊断日志写入失败，已自动关闭\n")
        except Exception:
            pass
