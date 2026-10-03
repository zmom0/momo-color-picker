import os
import sys
import tempfile
import traceback

__version__ = "1.1.0"

# 随插件自带的 numpy：先把 vendor/ 加进 sys.path 并**完整**导入一次。
# Krita 5.3.3 的内嵌 Python 3.13 没有 numpy，.desktop 里也不能声明该依赖。
# 注意：必须在主模块 import 之前完成 numpy 的完整导入——Krita 的
# krita/__init__.py 会给 import 加一层钩子，numpy 的惰性子模块在钩子下
# 可能踩到循环导入，提前完整导入可规避。
_VENDOR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor")
if os.path.isdir(_VENDOR) and _VENDOR not in sys.path:
    sys.path.insert(0, _VENDOR)

try:
    import numpy as _np          # noqa: F401
    import numpy.linalg as _npl  # noqa: F401
except Exception:                # 诊断用：把真实失败原因写到系统临时目录
    try:
        _dbg = os.path.join(tempfile.gettempdir(), "hsv_picker_import_error.log")
        with open(_dbg, "a", encoding="utf-8", newline="\n") as _fh:
            _fh.write("numpy 导入失败（hsv_picker v%s）：\n" % __version__
                      + traceback.format_exc() + "\n")
    except Exception:
        pass
else:
    # 正常启动不留下仓库内/临时目录里的旧诊断日志
    try:
        _dbg = os.path.join(tempfile.gettempdir(), "hsv_picker_import_error.log")
        if os.path.isfile(_dbg):
            os.remove(_dbg)
    except Exception:
        pass

from .hsv_picker import *   # noqa: E402,F401,F403
