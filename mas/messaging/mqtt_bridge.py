"""
MQTT Bridge — 센서 데이터 Pub/Sub 브리지
==========================================
실제 공장: PLC/센서 → MQTT Broker(Mosquitto) → Edge Gateway → Agent

토픽 구조:
  factory/line3/press-01/vibration      EA 구독
  factory/line3/press-01/oil_temp       EA 구독
  factory/line3/press-01/hydraulic_pressure
  factory/line3/press-01/motor_current
  factory/line3/weld-01/weld_current    QA 구독
  factory/line3/weld-01/weld_voltage    QA 구독
  factory/line3/weld-01/wire_feed
  factory/line3/weld-01/gas_flow
  factory/line3/quality/inspection      QA 구독
  factory/line3/inventory/snapshot      IA 구독
  mas/agents/+/status                   PA 구독
  mas/cnp/#                             PA 구독
  mas/alerts/#                          PA 구독

QoS:
  0 — 센서 스트림 (놓쳐도 다음 값이 옴)
  1 — 알람/재고 알림 (반드시 1회 전달)
  2 — CNP 메시지 (정확히 1회, 중복 불가)

의존:
  pip install paho-mqtt
  docker run -d -p 1883:1883 eclipse-mosquitto
  (미설치/미기동 시 자동 폴백 — in-memory 모드)
"""

import json
import logging
import time
import threading
from typing import Dict, List, Callable, Any, Optional
from dataclasses import dataclass, field

_log = logging.getLogger(__name__)

try:
    import paho.mqtt.client as mqtt
    _HAS_PAHO = True
except ImportError:
    _HAS_PAHO = False


# ── QoS 레벨 ─────────────────────────────────────────────────

QOS_SENSOR = 0    # 센서 스트림 — best effort
QOS_ALERT = 1     # 알람 — at least once
QOS_CNP = 2       # CNP 협상 — exactly once


# ── 토픽 프리셋 ──────────────────────────────────────────────

TOPIC_PREFIX = "factory/line3"

PRESS_TOPICS = [
    f"{TOPIC_PREFIX}/press-01/vibration",
    f"{TOPIC_PREFIX}/press-01/oil_temp",
    f"{TOPIC_PREFIX}/press-01/hydraulic_pressure",
    f"{TOPIC_PREFIX}/press-01/motor_current",
]

WELD_TOPICS = [
    f"{TOPIC_PREFIX}/weld-01/weld_current",
    f"{TOPIC_PREFIX}/weld-01/weld_voltage",
    f"{TOPIC_PREFIX}/weld-01/wire_feed",
    f"{TOPIC_PREFIX}/weld-01/gas_flow",
]

QUALITY_TOPIC = f"{TOPIC_PREFIX}/quality/inspection"
INVENTORY_TOPIC = f"{TOPIC_PREFIX}/inventory/snapshot"

MAS_ALERT_TOPIC = "mas/alerts"
MAS_CNP_TOPIC = "mas/cnp"
MAS_AGENT_STATUS = "mas/agents"
MAS_TOOLS_TOPIC = "mas/tools"


AGENT_SUBSCRIPTIONS: Dict[str, List[str]] = {
    "EA": [f"{TOPIC_PREFIX}/press-01/#"],
    "QA": [f"{TOPIC_PREFIX}/weld-01/#", QUALITY_TOPIC],
    "SA": [f"{TOPIC_PREFIX}/inventory/snapshot"],
    "DA": [],
    "IA": [INVENTORY_TOPIC],
    "PA": [f"{MAS_ALERT_TOPIC}/#", f"{MAS_CNP_TOPIC}/#", f"{MAS_AGENT_STATUS}/+/status"],
}


# ── 메트릭 ────────────────────────────────────────────────────

@dataclass
class MQTTMetrics:
    published: int = 0
    received: int = 0
    errors: int = 0
    reconnects: int = 0
    topics_active: int = 0
    last_publish_ts: float = 0.0
    bytes_sent: int = 0
    bytes_received: int = 0

    def to_dict(self) -> dict:
        return {
            "published": self.published,
            "received": self.received,
            "errors": self.errors,
            "reconnects": self.reconnects,
            "topics_active": self.topics_active,
            "bytes_sent": self.bytes_sent,
            "bytes_received": self.bytes_received,
        }


# ── MQTT 브리지 ───────────────────────────────────────────────

class MQTTBridge:
    """
    MQTT Pub/Sub 브리지.

    paho-mqtt 미설치 또는 브로커 미기동 시 자동 폴백:
      - publish → 로컬 콜백으로 직접 전달 (in-memory)
      - subscribe → 로컬 콜백 등록만
    """

    def __init__(
        self,
        broker_host: str = "localhost",
        broker_port: int = 1883,
        client_id: str = "mas-bridge",
        keepalive: int = 60,
    ):
        self.broker_host = broker_host
        self.broker_port = broker_port
        self.client_id = client_id
        self.keepalive = keepalive

        self.enabled = False
        self.connected = False
        self.fallback_reason = ""
        self.client: Any = None

        self._lock = threading.Lock()
        self._subscriptions: Dict[str, List[Callable]] = {}
        self._local_callbacks: Dict[str, List[Callable]] = {}
        self.metrics = MQTTMetrics()

        self._try_connect()

    def _try_connect(self):
        if not _HAS_PAHO:
            self.fallback_reason = "paho-mqtt 미설치 (pip install paho-mqtt)"
            return

        try:
            self.client = mqtt.Client(
                client_id=self.client_id,
                callback_api_version=mqtt.CallbackAPIVersion.VERSION2,
            )
            self.client.on_connect = self._on_connect
            self.client.on_disconnect = self._on_disconnect
            self.client.on_message = self._on_message

            self.client.connect(self.broker_host, self.broker_port, self.keepalive)
            self.client.loop_start()
            self.enabled = True
            self.connected = True
        except Exception as e:
            self.fallback_reason = f"MQTT 브로커 연결 실패 ({self.broker_host}:{self.broker_port}): {e}"
            self.enabled = False

    def _on_connect(self, client, userdata, flags, rc, properties=None):
        self.connected = True
        with self._lock:
            for topic in self._subscriptions:
                qos = self._topic_qos(topic)
                client.subscribe(topic, qos)
                self.metrics.topics_active += 1

    def _on_disconnect(self, client, userdata, flags, rc, properties=None):
        self.connected = False
        self.metrics.reconnects += 1

    def _on_message(self, client, userdata, msg):
        self.metrics.received += 1
        self.metrics.bytes_received += len(msg.payload)

        topic = msg.topic
        try:
            payload = json.loads(msg.payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            payload = msg.payload

        with self._lock:
            for pattern, callbacks in self._subscriptions.items():
                if self._topic_matches(pattern, topic):
                    for cb in callbacks:
                        try:
                            cb(topic, payload)
                        except Exception as e:
                            _log.debug("MQTT 콜백 오류 (%s): %s", topic, e)
                            self.metrics.errors += 1

    @staticmethod
    def _topic_matches(pattern: str, topic: str) -> bool:
        """MQTT 와일드카드 매칭 (# 및 +)."""
        if pattern == topic:
            return True
        p_parts = pattern.split("/")
        t_parts = topic.split("/")
        for i, pp in enumerate(p_parts):
            if pp == "#":
                return True
            if i >= len(t_parts):
                return False
            if pp != "+" and pp != t_parts[i]:
                return False
        return len(p_parts) == len(t_parts)

    @staticmethod
    def _topic_qos(topic: str) -> int:
        if "cnp" in topic:
            return QOS_CNP
        if "alert" in topic:
            return QOS_ALERT
        return QOS_SENSOR

    # ── 발행 ──────────────────────────────────────────────

    def publish(self, topic: str, data: dict, qos: Optional[int] = None):
        """토픽에 JSON 데이터 발행."""
        if qos is None:
            qos = self._topic_qos(topic)

        payload = json.dumps(data, ensure_ascii=False, default=str)
        payload_bytes = payload.encode("utf-8")

        if self.enabled and self.connected:
            try:
                self.client.publish(topic, payload_bytes, qos=qos)
                self.metrics.published += 1
                self.metrics.bytes_sent += len(payload_bytes)
                self.metrics.last_publish_ts = time.time()
            except Exception as e:
                _log.debug("MQTT publish 실패, 로컬 폴백: %s", e)
                self.metrics.errors += 1
                self._deliver_local(topic, data)
        else:
            self._deliver_local(topic, data)

    def _deliver_local(self, topic: str, data: dict):
        """MQTT 미사용 시 로컬 콜백으로 직접 전달."""
        self.metrics.published += 1
        with self._lock:
            for pattern, callbacks in self._local_callbacks.items():
                if self._topic_matches(pattern, topic):
                    for cb in callbacks:
                        try:
                            cb(topic, data)
                        except Exception as e:
                            _log.debug("로컬 콜백 오류 (%s): %s", topic, e)
                            self.metrics.errors += 1

    # ── 구독 ──────────────────────────────────────────────

    def subscribe(self, topic_pattern: str, callback: Callable):
        """토픽 패턴 구독 + 콜백 등록."""
        with self._lock:
            if topic_pattern not in self._subscriptions:
                self._subscriptions[topic_pattern] = []
            self._subscriptions[topic_pattern].append(callback)

            if topic_pattern not in self._local_callbacks:
                self._local_callbacks[topic_pattern] = []
            self._local_callbacks[topic_pattern].append(callback)

        if self.enabled and self.connected:
            qos = self._topic_qos(topic_pattern)
            self.client.subscribe(topic_pattern, qos)
            self.metrics.topics_active = len(self._subscriptions)

    # ── 센서 발행 헬퍼 ────────────────────────────────────

    def publish_press_sensors(self, readings: dict, sim_time: float):
        """프레스 센서 4종 각각 개별 토픽에 발행."""
        for sensor_name, reading in readings.items():
            topic = f"{TOPIC_PREFIX}/press-01/{sensor_name}"
            self.publish(topic, {
                "sensor": sensor_name,
                "value": reading.value,
                "unit": reading.unit,
                "status": reading.status,
                "timestamp": sim_time,
            }, qos=QOS_SENSOR)

    def publish_weld_sensors(self, readings: dict, sim_time: float):
        """용접 센서 4종 각각 개별 토픽에 발행."""
        for sensor_name, reading in readings.items():
            topic = f"{TOPIC_PREFIX}/weld-01/{sensor_name}"
            self.publish(topic, {
                "sensor": sensor_name,
                "value": reading.value,
                "unit": reading.unit,
                "status": reading.status,
                "timestamp": sim_time,
            }, qos=QOS_SENSOR)

    def publish_quality_result(self, product_serial: str, verdict: str,
                               measurements: dict, cpk: dict):
        """품질 검사 결과 발행."""
        self.publish(QUALITY_TOPIC, {
            "serial": product_serial,
            "verdict": verdict,
            "measurements": {
                k: {"value": m.value, "in_spec": m.in_spec, "margin_pct": m.margin_pct}
                for k, m in measurements.items()
            },
            "cpk": cpk,
        }, qos=QOS_ALERT)

    def publish_inventory(self, snapshot: dict):
        """재고 스냅샷 발행."""
        self.publish(INVENTORY_TOPIC, snapshot, qos=QOS_ALERT)

    def publish_alert(self, agent_id: str, alert_type: str, data: dict):
        """에이전트 알람 발행."""
        self.publish(f"{MAS_ALERT_TOPIC}/{agent_id}", {
            "agent": agent_id,
            "type": alert_type,
            **data,
        }, qos=QOS_ALERT)

    def publish_cnp(self, phase: str, data: dict):
        """CNP 메시지 발행 (cfp/propose/accept)."""
        self.publish(f"{MAS_CNP_TOPIC}/{phase}", data, qos=QOS_CNP)

    def publish_agent_status(self, agent_id: str, status: dict):
        """에이전트 상태 발행."""
        self.publish(f"{MAS_AGENT_STATUS}/{agent_id}/status", status, qos=QOS_SENSOR)

    def publish_tool_call(self, agent_id: str, tool_name: str, result: dict):
        """Tool 호출 결과 발행."""
        self.publish(f"{MAS_TOOLS_TOPIC}/{tool_name}", {
            "agent": agent_id, "tool": tool_name, **result,
        }, qos=QOS_SENSOR)

    # ── 상태 ──────────────────────────────────────────────

    def get_status(self) -> dict:
        return {
            "enabled": self.enabled,
            "connected": self.connected,
            "mode": "MQTT (Mosquitto)" if self.enabled else f"Local fallback ({self.fallback_reason})",
            "broker": f"{self.broker_host}:{self.broker_port}" if self.enabled else "N/A",
            "subscriptions": len(self._subscriptions),
            "metrics": self.metrics.to_dict(),
        }

    def stop(self):
        if self.enabled and self.client:
            try:
                self.client.loop_stop()
                self.client.disconnect()
            except Exception as e:
                _log.debug("MQTT disconnect 오류 (무시): %s", e)
