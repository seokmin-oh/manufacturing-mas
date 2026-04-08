import warnings as _w
_w.warn(
    "mas.mqtt_bridge 은 호환 shim입니다. mas.messaging.mqtt_bridge 에서 직접 import하세요.",
    DeprecationWarning,
    stacklevel=2,
)
from mas.messaging.mqtt_bridge import *  # noqa: F401,F403
