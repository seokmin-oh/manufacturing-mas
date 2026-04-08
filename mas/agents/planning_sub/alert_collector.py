from __future__ import annotations

from typing import Dict, List

from ...messaging.message import AgentMessage, Intent


def collect_inbox_alerts(msgs: List[AgentMessage]) -> List[Dict]:
    """inbox 메시지에서 PA 경보 리스트로 정규화."""
    alerts = []
    for msg in msgs:
        if msg.intent in (Intent.ALERT, Intent.STOCK_ALERT, Intent.DEMAND_CHANGE):
            alerts.append({
                "sender": msg.header.sender,
                "intent": msg.intent.value,
                "severity": msg.body.get("severity", "LOW"),
                "summary": msg.body.get("summary", ""),
                "body": msg.body,
            })
    return alerts
