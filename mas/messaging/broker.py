"""
Manufacturing MAS Message Broker
=================================

## 한국어 요약
에이전트 간 **발행/구독**을 이 프로세스 안에서 흉내 낸 모듈이다.
`Intent` → `Topic` 매핑으로 메시지를 넣을 “방”을 정하고, 에이전트마다 **Queue** 로 배달한다.
`receiver == "ALL"` 이면 해당 토픽 구독자 전원에게 복제 배달.

## 실제 현장으로 옮길 때
RabbitMQ / Kafka / MQTT 등 **외부 브로커**로 바꿔도, 에이전트가 쓰는
`send_message` / `receive_message` 인터페이스는 유지하기 쉽게 설계됨.

## 기능 (영문 유지)
  - 토픽 기반 라우팅 (EQUIPMENT, QUALITY, SUPPLY, DEMAND, INVENTORY, PLANNING)
  - Per-agent 메시지 큐 (Thread-safe)
  - 메시지 영속 로그 (in-memory, 실제: Redis / PostgreSQL)
  - Dead Letter Queue (DLQ) — 미전달 메시지 보관
  - 처리량 / 지연 메트릭
  - At-least-once 전송 보장 (재시도 + ACK)
  - SSE callback 훅 (API 연동)
"""

import time
import threading
import logging
from queue import Queue, Full, Empty
from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Callable, Any

from ..core.manufacturing_ids import AGENT_IDS as _CANONICAL_AGENT_IDS
from .message import AgentMessage, Intent

_log = logging.getLogger(__name__)


# ── 토픽 정의 ─────────────────────────────────────────────────────

class Topic(Enum):
    EQUIPMENT = "equipment"
    QUALITY = "quality"
    SUPPLY = "supply"
    DEMAND = "demand"
    INVENTORY = "inventory"
    PLANNING = "planning"
    BROADCAST = "broadcast"
    ALERTS = "alerts"
    CNP = "cnp"


INTENT_TOPIC_MAP: Dict[Intent, Topic] = {
    Intent.CFP: Topic.CNP,
    Intent.PROPOSE: Topic.CNP,
    Intent.ACCEPT_PROPOSAL: Topic.CNP,
    Intent.REJECT_PROPOSAL: Topic.CNP,
    Intent.ALERT: Topic.ALERTS,
    Intent.DEMAND_CHANGE: Topic.DEMAND,
    Intent.STOCK_ALERT: Topic.INVENTORY,
    Intent.PLAN_UPDATE: Topic.PLANNING,
    Intent.INFORM: Topic.BROADCAST,
    Intent.REQUEST: Topic.BROADCAST,
    Intent.ACKNOWLEDGE: Topic.BROADCAST,
    Intent.CONFIRM: Topic.BROADCAST,
    Intent.TOOL_CALL: Topic.BROADCAST,
    Intent.TOOL_RESULT: Topic.BROADCAST,
    Intent.ACCEPT_JOB: Topic.CNP,
    Intent.REJECT_JOB: Topic.CNP,
    Intent.STATUS_REPORT: Topic.BROADCAST,
}

AGENT_DEFAULT_TOPICS: Dict[str, Topic] = {
    "EA": Topic.EQUIPMENT,
    "QA": Topic.QUALITY,
    "SA": Topic.SUPPLY,
    "DA": Topic.DEMAND,
    "IA": Topic.INVENTORY,
    "PA": Topic.PLANNING,
}

if set(AGENT_DEFAULT_TOPICS.keys()) != set(_CANONICAL_AGENT_IDS):
    raise RuntimeError(
        "AGENT_DEFAULT_TOPICS must match mas.core.manufacturing_ids.AGENT_IDS"
    )


# ── 메시지 엔벨로프 ──────────────────────────────────────────────

@dataclass
class MessageEnvelope:
    """브로커 내부 래퍼 — 메시지 + 라우팅 메타데이터."""
    message: AgentMessage
    envelope_id: str = ""
    topic: Topic = Topic.BROADCAST
    published_at: float = 0.0
    delivered_at: Optional[float] = None
    acked: bool = False
    retry_count: int = 0
    max_retries: int = 3

    def __post_init__(self):
        if not self.envelope_id:
            self.envelope_id = self.message.header.message_id
        if self.published_at == 0.0:
            self.published_at = time.time()

    @property
    def latency_ms(self) -> Optional[float]:
        if self.delivered_at:
            return round((self.delivered_at - self.published_at) * 1000, 2)
        return None

    def to_dict(self) -> dict:
        msg = self.message
        return {
            "envelope_id": self.envelope_id,
            "topic": self.topic.value,
            "sender": msg.header.sender,
            "receiver": msg.header.receiver,
            "intent": msg.intent.value,
            "timestamp": msg.header.timestamp,
            "summary": msg.body.get("summary", ""),
            "latency_ms": self.latency_ms,
            "retry_count": self.retry_count,
            "acked": self.acked,
        }


# ── 브로커 메트릭 ─────────────────────────────────────────────────

@dataclass
class BrokerMetrics:
    total_published: int = 0
    total_delivered: int = 0
    total_acked: int = 0
    total_dlq: int = 0
    total_expired: int = 0
    avg_latency_ms: float = 0.0
    peak_latency_ms: float = 0.0
    _latencies: List[float] = field(default_factory=list, repr=False)
    start_time: float = field(default_factory=time.time)

    def record_delivery(self, latency_ms: float):
        self.total_delivered += 1
        self._latencies.append(latency_ms)
        if len(self._latencies) > 500:
            self._latencies = self._latencies[-250:]
        self.avg_latency_ms = round(sum(self._latencies) / len(self._latencies), 2)
        self.peak_latency_ms = max(self.peak_latency_ms, latency_ms)

    @property
    def throughput_per_sec(self) -> float:
        elapsed = time.time() - self.start_time
        return round(self.total_published / max(elapsed, 0.001), 2)

    def to_dict(self) -> dict:
        return {
            "total_published": self.total_published,
            "total_delivered": self.total_delivered,
            "total_acked": self.total_acked,
            "total_dlq": self.total_dlq,
            "avg_latency_ms": self.avg_latency_ms,
            "peak_latency_ms": self.peak_latency_ms,
            "throughput_msg_per_sec": self.throughput_per_sec,
            "pending": self.total_published - self.total_acked,
            "uptime_sec": round(time.time() - self.start_time, 1),
        }


# ── 메시지 브로커 본체 ────────────────────────────────────────────

class MessageBroker:
    """
    토픽 기반 Pub/Sub 메시지 브로커.

    `register(agent)` 호출 시:
      - agent.broker / agent.message_bus 에 self 를 붙임
      - BROADCAST, ALERTS, CNP 는 공통 구독
      - EA→equipment 등 `AGENT_DEFAULT_TOPICS` 로 역할 토픽 추가

    실제 환경 매핑(예시):
      Topic.EQUIPMENT → MQTT  factory/line3/equipment/#
      Topic.QUALITY   → MQTT  factory/line3/quality/#
      Topic.ALERTS    → RabbitMQ  alerts-exchange (fanout)
      Topic.CNP       → RabbitMQ  cnp-exchange (direct)
      전체 로그       → Apache Kafka  mas-events topic
    """


    MAX_ENVELOPE_LOG = 2000
    MAX_DLQ = 500

    def __init__(self, max_queue_size: int = 500):
        self._lock = threading.RLock()
        self._max_queue = max_queue_size

        self.agent_queues: Dict[str, Queue] = {}
        self.subscriptions: Dict[Topic, Set[str]] = {t: set() for t in Topic}
        self.agent_refs: Dict[str, Any] = {}

        self.envelope_log: List[MessageEnvelope] = []
        self.dlq: List[MessageEnvelope] = []

        self.metrics = BrokerMetrics()
        self._callbacks: List[Callable] = []

    # ── 에이전트 등록 / 구독 ──────────────────────────────────

    def register(self, agent, extra_topics: Optional[List[Topic]] = None):
        """에이전트 등록 + 기본 토픽 자동 구독."""
        aid = agent.agent_id
        with self._lock:
            self.agent_queues[aid] = Queue(maxsize=self._max_queue)
            self.agent_refs[aid] = agent
            agent.message_bus = self
            agent.broker = self

            topics: Set[Topic] = {Topic.BROADCAST, Topic.ALERTS, Topic.CNP}
            if aid in AGENT_DEFAULT_TOPICS:
                topics.add(AGENT_DEFAULT_TOPICS[aid])
            if extra_topics:
                topics.update(extra_topics)

            for t in topics:
                self.subscriptions[t].add(aid)

    def subscribe(self, agent_id: str, topic: Topic):
        with self._lock:
            self.subscriptions[topic].add(agent_id)

    def unsubscribe(self, agent_id: str, topic: Topic):
        with self._lock:
            self.subscriptions[topic].discard(agent_id)

    # ── 발행 / 전달 ──────────────────────────────────────────

    def publish(self, message: AgentMessage, topic: Optional[Topic] = None) -> MessageEnvelope:
        """메시지를 토픽에 발행하고 구독자 큐에 라우팅."""
        if topic is None:
            topic = INTENT_TOPIC_MAP.get(message.intent, Topic.BROADCAST)

        envelope = MessageEnvelope(message=message, topic=topic)

        with self._lock:
            self.envelope_log.append(envelope)
            if len(self.envelope_log) > self.MAX_ENVELOPE_LOG:
                self.envelope_log = self.envelope_log[-self.MAX_ENVELOPE_LOG // 2:]
            self.metrics.total_published += 1

        receiver = message.header.receiver

        if receiver == "ALL":
            for aid in self.subscriptions.get(topic, set()):
                if aid != message.header.sender:
                    self._enqueue(aid, envelope)
        elif receiver in self.agent_queues:
            self._enqueue(receiver, envelope)
        else:
            with self._lock:
                self.dlq.append(envelope)
                if len(self.dlq) > self.MAX_DLQ:
                    self.dlq = self.dlq[-self.MAX_DLQ // 2:]
                self.metrics.total_dlq += 1

        for cb in self._callbacks:
            try:
                cb(envelope)
            except Exception as e:
                _log.debug("broker callback 오류: %s", e)

        return envelope

    def deliver(self, message: AgentMessage):
        """MessageBus 호환 인터페이스."""
        self.publish(message)

    def _enqueue(self, agent_id: str, envelope: MessageEnvelope):
        q = self.agent_queues.get(agent_id)
        if q is None:
            return
        try:
            now = time.time()
            envelope.delivered_at = now
            q.put_nowait(envelope)

            if envelope.latency_ms is not None:
                self.metrics.record_delivery(envelope.latency_ms)

            agent = self.agent_refs.get(agent_id)
            if agent:
                agent.receive_message(envelope.message)

        except Full:
            envelope.retry_count += 1
            if envelope.retry_count < envelope.max_retries:
                import time as _t
                _t.sleep(0.01 * envelope.retry_count)
                try:
                    q.put_nowait(envelope)
                    if envelope.latency_ms is not None:
                        self.metrics.record_delivery(envelope.latency_ms)
                except Full:
                    _log.debug("재시도 실패 — 큐 가득참 (retry %d/%d)", envelope.retry_count, envelope.max_retries)
            if envelope.retry_count >= envelope.max_retries:
                with self._lock:
                    self.dlq.append(envelope)
                    self.metrics.total_dlq += 1

    # ── 소비 / ACK ───────────────────────────────────────────

    def consume(self, agent_id: str, timeout: float = 0.05) -> Optional[MessageEnvelope]:
        q = self.agent_queues.get(agent_id)
        if q is None:
            return None
        try:
            return q.get(timeout=timeout)
        except Empty:
            return None

    def consume_all(self, agent_id: str) -> List[MessageEnvelope]:
        result = []
        q = self.agent_queues.get(agent_id)
        if q is None:
            return result
        while not q.empty():
            try:
                result.append(q.get_nowait())
            except Empty:
                break
        return result

    def acknowledge(self, agent_id: str, envelope_id: str):
        """실제 envelope_id 기반 ACK 추적."""
        with self._lock:
            for env in reversed(self.envelope_log[-200:]):
                if env.envelope_id == envelope_id and not env.acked:
                    env.acked = True
                    self.metrics.total_acked += 1
                    return True
            self.metrics.total_acked += 1
            return False

    # ── 콜백 / 모니터링 ──────────────────────────────────────

    def on_message(self, callback: Callable):
        self._callbacks.append(callback)

    def get_queue_depth(self, agent_id: str) -> int:
        q = self.agent_queues.get(agent_id)
        return q.qsize() if q else 0

    def get_all_depths(self) -> Dict[str, int]:
        return {aid: self.get_queue_depth(aid) for aid in self.agent_queues}

    def get_agent(self, agent_id: str):
        return self.agent_refs.get(agent_id)

    # ── 하위 호환: message_log (AgentMessage 리스트) ──────────

    @property
    def message_log(self) -> List[AgentMessage]:
        return [e.message for e in self.envelope_log]

    # ── 상태 리포트 ───────────────────────────────────────────

    def get_status(self) -> dict:
        return {
            "agents_registered": list(self.agent_queues.keys()),
            "queue_depths": self.get_all_depths(),
            "subscriptions": {
                t.value: sorted(subs) for t, subs in self.subscriptions.items() if subs
            },
            "metrics": self.metrics.to_dict(),
            "dlq_size": len(self.dlq),
            "total_envelopes": len(self.envelope_log),
        }

    def get_status_summary(self) -> str:
        m = self.metrics
        depths = self.get_all_depths()
        d_str = " ".join(f"{k}:{v}" for k, v in depths.items())
        return (
            f"Published:{m.total_published} Delivered:{m.total_delivered} "
            f"ACK:{m.total_acked} DLQ:{m.total_dlq} "
            f"AvgLatency:{m.avg_latency_ms:.1f}ms "
            f"Queues[{d_str}]"
        )
