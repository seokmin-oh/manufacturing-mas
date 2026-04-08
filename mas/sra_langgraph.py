import warnings as _w
_w.warn(
    "mas.sra_langgraph 은 호환 shim입니다. mas.protocol.sra_langgraph 에서 직접 import하세요.",
    DeprecationWarning,
    stacklevel=2,
)
from mas.protocol.sra_langgraph import *  # noqa: F401,F403
