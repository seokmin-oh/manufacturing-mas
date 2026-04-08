"""
Contract Net Protocol 세션 — 상태, 제약, 제안 속도 검증, 전략 클램프.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Optional


class CNPState(Enum):
    IDLE = "idle"
    CFP_OPEN = "cfp_open"
    COLLECTING = "collecting"
    EVALUATING = "evaluating"
    COMPLETED = "completed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


PROTOCOL_VERSION = "cnp/1"


@dataclass
class CNPConstraints:
    """협상에 적용되는 하드 제약(라인·안전)."""

    speed_min_pct: int = 40
    speed_max_pct: int = 100
    deadline_sec: float = 45.0


class CNPSession:
    """한 번의 CNP 라운드 메타데이터."""

    def __init__(self, constraints: Optional[CNPConstraints] = None):
        self.constraints = constraints or CNPConstraints()
        self.state: CNPState = CNPState.IDLE
        self.conversation_id: str = ""
        self.started_at: float = 0.0
        self.proposals: List[Dict[str, Any]] = []

    def begin(self) -> str:
        self.conversation_id = str(uuid.uuid4())[:12]
        self.started_at = time.time()
        self.state = CNPState.CFP_OPEN
        self.proposals = []
        return self.conversation_id

    def mark_collecting(self) -> None:
        self.state = CNPState.COLLECTING

    def mark_evaluating(self) -> None:
        self.state = CNPState.EVALUATING

    def mark_completed(self) -> None:
        self.state = CNPState.COMPLETED

    def mark_timeout(self) -> None:
        self.state = CNPState.TIMEOUT

    def is_expired(self) -> bool:
        if self.started_at <= 0:
            return False
        return (time.time() - self.started_at) > self.constraints.deadline_sec

    def validate_proposal(self, proposal: Dict[str, Any]) -> bool:
        sp = proposal.get("speed_recommendation", proposal.get("target_speed_pct", 100))
        try:
            sp = int(float(sp))
        except (TypeError, ValueError):
            return False
        return self.constraints.speed_min_pct <= sp <= self.constraints.speed_max_pct

    def clamp_strategy(self, strategy: Dict[str, Any]) -> Dict[str, Any]:
        sp = strategy.get("target_speed_pct", 100)
        try:
            sp = int(float(sp))
        except (TypeError, ValueError):
            sp = 100
        sp = max(self.constraints.speed_min_pct, min(self.constraints.speed_max_pct, sp))
        strategy = dict(strategy)
        strategy["target_speed_pct"] = sp
        strategy["constraints_applied"] = True
        strategy["protocol_version"] = PROTOCOL_VERSION
        strategy["conversation_id"] = self.conversation_id
        return strategy

    def to_cfp_body(self, situation_summary: str) -> Dict[str, Any]:
        c = self.constraints
        return {
            "protocol_version": PROTOCOL_VERSION,
            "conversation_id": self.conversation_id,
            "constraints": {
                "speed_min_pct": c.speed_min_pct,
                "speed_max_pct": c.speed_max_pct,
                "deadline_sec": c.deadline_sec,
            },
            "situation": situation_summary,
            "summary": "CNP 입찰 요청 (CFP)",
        }
