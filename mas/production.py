import warnings as _w
_w.warn(
    "mas.production 은 호환 shim입니다. mas.domain.production 에서 직접 import하세요.",
    DeprecationWarning,
    stacklevel=2,
)
from mas.domain.production import *  # noqa: F401,F403
