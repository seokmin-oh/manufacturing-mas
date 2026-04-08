"""
MAS 에이전트 기반 클래스
=======================

모든 상위 에이전트(EA~PA)는 이 클래스를 상속하고, **Sense → Reason → Act** 패턴을 따른다.

- **sense(snapshot)**: `Factory.get_snapshot()` 등에서 온 전역 스냅샷에서 자기 역할에 맞는 관측만 추림.
- **reason(observations)**: 관측으로부터 결정 dict(또는 None) 생성. 우선순위·요약 문자열 등.
- **act(decision)**: 결정에 따라 공장 상태 변경·메시지 발송 등 부수효과.
- **실행 루프**: `FactoryRuntime` 은 기본적으로 `run_cycle_with_router()` 를 쓴다.
  그 경로에서는 라우터가 Reason 전에 끼어들 수 있음(`mas/protocol/agent_protocol.py`).

**메시징**: `send_message` → `broker.deliver` → 수신자 `inbox`. CNP 시 `handle_cfp` / `execute_accepted_proposal`.
"""

from __future__ import annotations

import threading
import time
from abc import ABC, abstractmethod
from enum import Enum
from typing import Any, Dict, List, Optional

from ..messaging.message import AgentMessage, Intent


class AgentState(Enum):
    """대시보드/로그용 거친 상태 머신. 실제 협상은 PA·CNP 코드와 결합."""

    IDLE = "대기"
    SENSING = "감지"
    REASONING = "판단"
    ACTING = "실행"
    NEGOTIATING = "협상"
    ERROR = "오류"


class BaseAgent(ABC):
    """6역할 에이전트 공통: 스냅샷 기반 루프, inbox/outbox, 추론 로그 제한 보관."""

    def __init__(self, agent_id: str, name: str):

        self.agent_id = agent_id
        self.name = name
        self.state = AgentState.IDLE

        self.inbox: List[AgentMessage] = []
        self.outbox: List[AgentMessage] = []
        self._lock = threading.Lock()

        self.message_bus = None
        self.broker = None
        self.mqtt = None

        self.reasoning_log: List[str] = []
        self._snapshot: Optional[Dict] = None
        self._decisions: List[Dict] = []
        self._cycle_count = 0

    def run_cycle(self, snapshot: Dict) -> Optional[Dict]:
        """
        Sense → Reason → Act 한 사이클 (라우터 없음).
        런타임 기본 경로는 `run_cycle_with_router` 이므로, 이 메서드는 테스트·직접 호출용.
        """

        self._snapshot = snapshot
        self._cycle_count += 1

        self.state = AgentState.SENSING
        observations = self.sense(snapshot)

        self.state = AgentState.REASONING
        decision = self.reason(observations)

        if decision:
            self._decisions.append(decision)
            if len(self._decisions) > 100:
                self._decisions = self._decisions[-100:]

        self.state = AgentState.ACTING
        actions = self.act(decision)

        self.state = AgentState.IDLE
        return decision

    @abstractmethod
    def sense(self, snapshot: Dict) -> Dict:
        """환경 감지 — 스냅샷에서 관련 데이터를 추출/분석."""

    @abstractmethod
    def reason(self, observations: Dict) -> Optional[Dict]:
        """판단 — 관측값 기반 의사결정."""

    @abstractmethod
    def act(self, decision: Optional[Dict]) -> List[str]:
        """실행 — 결정에 따른 행동 수행."""

    @abstractmethod
    def handle_cfp(self, cfp_data: Dict) -> Optional[Dict]:
        """CNP 입찰 요청에 대한 제안 반환."""

    @abstractmethod
    def execute_accepted_proposal(self, proposal: Dict):
        """수락된 제안 실행."""

    def send_message(self, receiver: str, intent: Intent, body: Dict):
        """브로커가 연결되어 있으면 즉시 `publish` 경로로 전달(수신자 큐 + receive_message)."""

        msg = AgentMessage.create(self.agent_id, receiver, intent, body)
        with self._lock:
            self.outbox.append(msg)
        if self.broker:
            self.broker.deliver(msg)

    def receive_message(self, message: AgentMessage):
        with self._lock:
            self.inbox.append(message)

    def pop_inbox(self) -> List[AgentMessage]:
        with self._lock:
            msgs = list(self.inbox)
            self.inbox.clear()
        return msgs

    def log_reasoning(self, text: str):
        self.reasoning_log.append(text)
        if len(self.reasoning_log) > 50:
            self.reasoning_log = self.reasoning_log[-50:]

    def get_agent_status(self) -> Dict:
        """REST `/api/agents`, 모니터링 JSON용. 하위 클래스에서 키를 확장할 수 있음."""

        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "state": self.state.value,
            "cycle_count": self._cycle_count,
            "inbox_size": len(self.inbox),
            "recent_decisions": self._decisions[-8:] if self._decisions else [],
            "recent_reasoning": self.reasoning_log[-6:] if self.reasoning_log else [],
            "last_reasoning": self.reasoning_log[-1] if self.reasoning_log else "",
            "decisions_total": len(self._decisions),
        }
