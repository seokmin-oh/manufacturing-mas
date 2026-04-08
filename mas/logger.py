import warnings as _w
_w.warn(
    "mas.logger 은 호환 shim입니다. mas.core.logger 에서 직접 import하세요.",
    DeprecationWarning,
    stacklevel=2,
)
from mas.core.logger import *  # noqa: F401,F403
