import warnings as _w
_w.warn(
    "mas.logging_config 은 호환 shim입니다. mas.core.logging_config 에서 직접 import하세요.",
    DeprecationWarning,
    stacklevel=2,
)
from mas.core.logging_config import *  # noqa: F401,F403
