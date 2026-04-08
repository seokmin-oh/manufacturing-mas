import warnings as _w
_w.warn(
    "mas.cnp_session 은 호환 shim입니다. mas.protocol.cnp_session 에서 직접 import하세요.",
    DeprecationWarning,
    stacklevel=2,
)
from mas.protocol.cnp_session import *  # noqa: F401,F403
