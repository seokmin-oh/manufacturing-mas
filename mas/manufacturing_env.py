import warnings as _w
_w.warn(
    "mas.manufacturing_env 은 호환 shim입니다. mas.domain.manufacturing_env 에서 직접 import하세요.",
    DeprecationWarning,
    stacklevel=2,
)
from mas.domain.manufacturing_env import *  # noqa: F401,F403
