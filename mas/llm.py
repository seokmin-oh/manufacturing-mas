import warnings as _w
_w.warn(
    "mas.llm 은 호환 shim입니다. mas.intelligence.llm 에서 직접 import하세요.",
    DeprecationWarning,
    stacklevel=2,
)
from mas.intelligence.llm import *  # noqa: F401,F403
