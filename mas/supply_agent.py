import warnings as _w
_w.warn(
    "mas.supply_agent 은 호환 shim입니다. mas.agents.supply_agent 에서 직접 import하세요.",
    DeprecationWarning,
    stacklevel=2,
)
from mas.agents.supply_agent import *  # noqa: F401,F403
