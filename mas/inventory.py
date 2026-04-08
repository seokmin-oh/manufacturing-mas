import warnings as _w
_w.warn(
    "mas.inventory 은 호환 shim입니다. mas.domain.inventory 에서 직접 import하세요.",
    DeprecationWarning,
    stacklevel=2,
)
from mas.domain.inventory import *  # noqa: F401,F403
