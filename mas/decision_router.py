import warnings as _w
_w.warn(
    "mas.decision_router 은 호환 shim입니다. mas.intelligence.decision_router 에서 직접 import하세요.",
    DeprecationWarning,
    stacklevel=2,
)
from mas.intelligence.decision_router import *  # noqa: F401,F403
