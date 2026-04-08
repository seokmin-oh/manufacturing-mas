import warnings as _w
_w.warn(
    "mas.config 은 호환 shim입니다. mas.core.config 에서 직접 import하세요.",
    DeprecationWarning,
    stacklevel=2,
)
from mas.core.config import *  # noqa: F401,F403
