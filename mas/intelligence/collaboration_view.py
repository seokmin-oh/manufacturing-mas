"""
에이전트 간 협업 가시화 — 모니터링 API용 정적 토폴로지 + 브로커 최근 메시지 기반 활동도.

설계 의도: EA~PA가 ‘나란히 카드’로만 보이면 협업 관계가 드러나지 않아,
중심(PA)·방사형 메시지·교차 링크를 한 화면에 고정한다.
"""

from __future__ import annotations

import logging
import math
from typing import Any, Dict, List, Optional, Set, Tuple

_log = logging.getLogger(__name__)

# 6 에이전트 ID (브로커 집계용)
_AGENT_IDS: Set[str] = {"EA", "QA", "SA", "DA", "IA", "PA"}

# SVG 좌표 — 여유 viewBox, 바깥 반지름을 키워 선·노드 간격 확보
_CX, _CY, _R_OUT = 240.0, 178.0, 132.0
_RING: List[str] = ["EA", "QA", "SA", "DA", "IA"]


def _node_positions() -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {
        "PA": {"x": _CX, "y": _CY, "r": 34},
    }
    n = len(_RING)
    for i, aid in enumerate(_RING):
        ang = math.radians(-90 + i * (360 / n))
        out[aid] = {
            "x": round(_CX + _R_OUT * math.cos(ang), 1),
            "y": round(_CY + _R_OUT * math.sin(ang), 1),
            "r": 30,
        }
    return out


# 정적 협업 링크 — 운영자가 ‘누가 누구와 무엇을 주고받는지’를 읽도록 문장 라벨
COLLABORATION_EDGES: List[Dict[str, Any]] = [
    {"from": "EA", "to": "PA", "label": "설비 이상·RUL → 속도·제약", "kind": "sense_to_plan"},
    {"from": "QA", "to": "PA", "label": "SPC·불량 → 전역 경보", "kind": "sense_to_plan"},
    {"from": "SA", "to": "PA", "label": "ROP·부족 → 생산 조정", "kind": "sense_to_plan"},
    {"from": "DA", "to": "PA", "label": "납기·수요 급변 → 우선순위", "kind": "sense_to_plan"},
    {"from": "IA", "to": "PA", "label": "WIP·FG → 물량·속도 협의", "kind": "sense_to_plan"},
    {"from": "PA", "to": "EA", "label": "라인 속도·지시", "kind": "plan_to_act"},
    {"from": "PA", "to": "QA", "label": "검사·관리도 한계 힌트", "kind": "plan_to_act"},
    {"from": "PA", "to": "SA", "label": "발주·입고 이벤트", "kind": "plan_to_act"},
    {"from": "PA", "to": "DA", "label": "스케줄·납기 반영", "kind": "plan_to_act"},
    {"from": "PA", "to": "IA", "label": "버퍼·출하 목표", "kind": "plan_to_act"},
    {"from": "EA", "to": "QA", "label": "라인 상태 ↔ 품질 상관", "kind": "cross", "curve": True},
    {"from": "DA", "to": "IA", "label": "수요 ↔ 재고 압력", "kind": "cross", "curve": True},
    {"from": "SA", "to": "IA", "label": "자재 ↔ WIP 흐름", "kind": "cross", "curve": True},
]


def _aggregate_edge_activity(broker: Any, limit: int = 600) -> Tuple[List[Dict[str, Any]], int]:
    """브로커 envelope 로그에서 (발신,수신) 쌍별 최근 건수."""
    if broker is None or not hasattr(broker, "envelope_log"):
        return [], 0
    try:
        log = list(broker.envelope_log)[-limit:]
    except Exception as e:
        _log.debug("envelope_log 접근 실패: %s", e)
        return [], 0

    counts: Dict[Tuple[str, str], int] = {}
    for env in log:
        try:
            msg = env.message
            s = msg.header.sender
            r = msg.header.receiver
        except Exception as e:
            _log.debug("envelope 파싱 건너뜀: %s", e)
            continue
        if s not in _AGENT_IDS:
            continue
        if r in _AGENT_IDS:
            key = (s, r)
            counts[key] = counts.get(key, 0) + 1
        elif r == "ALL":
            for aid in _AGENT_IDS:
                if aid != s:
                    key = (s, aid)
                    counts[key] = counts.get(key, 0) + 1

    total = sum(counts.values())
    ranked = sorted(counts.items(), key=lambda x: -x[1])
    activity = [{"from": a, "to": b, "count": c} for (a, b), c in ranked[:24]]
    return activity, total


def build_collaboration_payload(broker: Optional[Any] = None) -> Dict[str, Any]:
    activity, activity_total = _aggregate_edge_activity(broker)
    # 빠른 조회: "EA|PA" -> count
    act_map = {f"{x['from']}|{x['to']}": x["count"] for x in activity}

    edges_out: List[Dict[str, Any]] = []
    for e in COLLABORATION_EDGES:
        key = f"{e['from']}|{e['to']}"
        c = act_map.get(key, 0)
        edges_out.append({**e, "recent_count": c})

    max_c = max((e["recent_count"] for e in edges_out), default=0)

    return {
        "summary": (
            "중앙은 계획(PA), 주변은 나머지 역할입니다. "
            "→계획(청록)·계획→(보라) 선은 안쪽/바깥쪽으로 나뉘어 겹침을 줄였습니다. "
            "곡선은 교차 협업, 굵기는 최근 메시지 빈도입니다. 긴 설명은 아래 표를 보세요."
        ),
        "view_box": "0 0 480 360",
        "nodes": _node_positions(),
        "edges": edges_out,
        "edge_activity": activity,
        "edge_activity_total": activity_total,
        "edge_activity_max_on_map": max_c,
    }
