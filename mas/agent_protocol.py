"""하위 호환 shim → `mas.protocol.agent_protocol`."""
import warnings as _w
_w.warn(
    "mas.agent_protocol 은 호환 shim입니다. mas.protocol.agent_protocol 에서 직접 import하세요.",
    DeprecationWarning,
    stacklevel=2,
)
from mas.protocol.agent_protocol import (  # noqa: F401
    AGENT_PROTOCOL_ID,
    _apply_think_result,
    _run_sra_sequential,
    run_cycle_with_router,
)

__all__ = [
    "AGENT_PROTOCOL_ID",
    "_apply_think_result",
    "_run_sra_sequential",
    "run_cycle_with_router",
]
