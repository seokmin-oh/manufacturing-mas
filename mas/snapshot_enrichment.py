import warnings as _w
_w.warn(
    "mas.snapshot_enrichment 은 호환 shim입니다. mas.intelligence.snapshot_enrichment 에서 직접 import하세요.",
    DeprecationWarning,
    stacklevel=2,
)
from mas.intelligence.snapshot_enrichment import *  # noqa: F401,F403
