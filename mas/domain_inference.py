import warnings as _w
_w.warn(
    "mas.domain_inference 은 호환 shim입니다. mas.intelligence.domain_inference 에서 직접 import하세요.",
    DeprecationWarning,
    stacklevel=2,
)
from mas.intelligence.domain_inference import *  # noqa: F401,F403
