import warnings as _w
_w.warn(
    "mas.prompt_registry 은 호환 shim입니다. mas.intelligence.prompt_registry 에서 직접 import하세요.",
    DeprecationWarning,
    stacklevel=2,
)
from mas.intelligence.prompt_registry import *  # noqa: F401,F403
