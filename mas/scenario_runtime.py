"""하위 호환 shim → `mas.runtime.scenario_runtime`."""
import warnings as _w
_w.warn(
    "mas.scenario_runtime 은 호환 shim입니다. mas.runtime.scenario_runtime 에서 직접 import하세요.",
    DeprecationWarning,
    stacklevel=2,
)
from mas.runtime.scenario_runtime import *  # noqa: F401,F403
