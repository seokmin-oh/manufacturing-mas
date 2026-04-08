import warnings as _w
_w.warn(
    "mas.environment 은 호환 shim입니다. mas.domain.environment 에서 직접 import하세요.",
    DeprecationWarning,
    stacklevel=2,
)
from mas.domain.environment import *  # noqa: F401,F403
