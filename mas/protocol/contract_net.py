"""
Contract Net Protocol (CNP) 구현.
FIPA 표준 기반 [공고(CFP) -> 입찰(Propose) -> 수락(Accept)] 프로세스.
"""

import uuid
from typing import List, Dict, Any

from ..messaging.message import AgentMessage, Intent
from ..core import logger


class ContractNetProtocol:

    def __init__(self, initiator, participants: list):
        self.conversation_id = str(uuid.uuid4())[:8]
        self.initiator = initiator
        self.participants = {p.agent_id: p for p in participants}
        self.proposals: List[AgentMessage] = []

    def execute(self, context: dict, env_data: dict, env) -> dict:

        # ── CFP Broadcast ────────────────────────────────────────
        logger.print_phase("3", "Contract Net Protocol — 협상 개시")
        logger.print_summary_separator()

        self.initiator.think(
            "설비 경고와 품질 위험이 동시에 감지되었다. "
            f"잔여 목표 {env.order.remaining}개, 납기 {env.order.due_date}. "
            "에이전트 협의를 통해 최적 대응을 결정한다."
        )

        cfp = self.initiator.broadcast_cfp(context, self.conversation_id)
        logger.print_message_json(cfp.to_dict())

        # ── Proposal Collection ──────────────────────────────────
        logger.print_phase("3.1", "제안 수집 (Proposal Collection)")
        for aid, agent in self.participants.items():
            logger.print_summary_separator()
            proposal = agent.handle_cfp(cfp, env_data)
            self.proposals.append(proposal)
            agent.send_message(proposal)
            logger.print_message_json(proposal.to_dict())

        # ── Evaluation ───────────────────────────────────────────
        logger.print_phase("3.2", "제안 평가 (Proposal Evaluation)")
        logger.print_summary_separator()

        ranked, strategy = self.initiator.evaluate_and_decide(self.proposals, env_data)

        # ── Decision Announcement ────────────────────────────────
        logger.print_phase("3.3", "의사결정 통보 (Decision Announcement)")
        logger.print_summary_separator()

        self.initiator.think(
            "통합 전략을 확정하고 각 에이전트에 실행 지시를 전송한다."
        )
        logger.agent_log("OA", "=== 최종 의사결정 ===", "DECISION")
        for line in strategy.get("rationale", []):
            logger.agent_log("OA", f"  {line}", "INFO")

        accept_msgs = self.initiator.send_accepts(strategy, self.conversation_id)

        # ── Execution ────────────────────────────────────────────
        logger.print_phase("4", "지시 실행 (Execution)")
        logger.print_summary_separator()

        results = {}
        for msg in accept_msgs:
            rid = msg.header.receiver
            if rid in self.participants:
                r = self.participants[rid].execute_accepted_proposal(msg, env)
                results[rid] = r

        return {
            "strategy": strategy,
            "execution_results": results,
            "conversation_id": self.conversation_id,
        }
