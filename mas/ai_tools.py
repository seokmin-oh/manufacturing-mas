import warnings as _w
_w.warn(
    "mas.ai_tools 은 호환 shim입니다. mas.tools.ai_tools 에서 직접 import하세요.",
    DeprecationWarning,
    stacklevel=2,
)
from mas.tools.ai_tools import *  # noqa: F401,F403
