"""
FIPA-ACL 스타일 에이전트 간 메시지 프로토콜
===========================================

- **AgentMessage**: `header`(발신·수신·대화ID·타임스탬프) + `intent` + `body`(임의 dict).
- **Intent**: CNP 계열(CFP/PROPOSE/…)과 도메인(ALERT, PLAN_UPDATE 등)을 한 열거형으로 통일.
- 브로커는 `Intent` 를 보고 `Topic` 으로 라우팅(`mas/messaging/broker.py` 의 INTENT_TOPIC_MAP).

직렬화: `to_dict` / JSON — 로그·API 응답에 사용.
"""


import json
import uuid
from datetime import datetime
from enum import Enum
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


class Intent(Enum):
    """에이전트 대화 의도. 값 문자열은 로그·프론트 표시에 그대로 노출되는 경우가 많음."""

    # --- CNP (Contract Net Protocol): PA가 입찰·제안·수락 조율 ---
    CFP = "CFP"

    PROPOSE = "PROPOSE"
    ACCEPT_PROPOSAL = "ACCEPT_PROPOSAL"
    REJECT_PROPOSAL = "REJECT_PROPOSAL"
    # --- 일반 대화 ---
    INFORM = "INFORM"

    REQUEST = "REQUEST"
    ALERT = "ALERT"
    ACKNOWLEDGE = "ACKNOWLEDGE"
    CONFIRM = "CONFIRM"
    # --- 도메인 이벤트(수요·재고·계획 변경 알림) ---
    DEMAND_CHANGE = "DEMAND_CHANGE"

    STOCK_ALERT = "STOCK_ALERT"
    PLAN_UPDATE = "PLAN_UPDATE"
    # --- 도구 위임(확장용) ---
    TOOL_CALL = "TOOL_CALL"

    TOOL_RESULT = "TOOL_RESULT"
    # --- 작업 수락/거절 ---
    ACCEPT_JOB = "ACCEPT_JOB"

    REJECT_JOB = "REJECT_JOB"
    # --- 상태 보고 ---
    STATUS_REPORT = "STATUS_REPORT"



@dataclass
class MessageHeader:
    """메시지 메타. message_id 는 UUID 축약, conversation_id 로 CNP 스레드 묶음."""

    sender: str
    receiver: str
    conversation_id: str
    timestamp: str = field(default_factory=lambda: datetime.now().strftime("%H:%M:%S.%f")[:-3])
    message_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    protocol: str = "CNP"


@dataclass
class AgentMessage:
    """브로커·에이전트 inbox 가 다루는 1건의 메시지 본체."""

    header: MessageHeader
    intent: Intent
    body: Dict[str, Any]

    def to_dict(self) -> dict:
        return {
            "header": {
                "sender": self.header.sender,
                "receiver": self.header.receiver,
                "conversation_id": self.header.conversation_id,
                "timestamp": self.header.timestamp,
                "message_id": self.header.message_id,
                "protocol": self.header.protocol,
            },
            "intent": self.intent.value,
            "body": self.body,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @staticmethod
    def create(
        sender: str,
        receiver: str,
        intent: Intent,
        body: dict,
        conversation_id: Optional[str] = None,
    ) -> "AgentMessage":
        return AgentMessage(
            header=MessageHeader(
                sender=sender,
                receiver=receiver,
                conversation_id=conversation_id or str(uuid.uuid4())[:8],
            ),
            intent=intent,
            body=body,
        )
