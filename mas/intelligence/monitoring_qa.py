"""
모니터링 스냅샷 기반 자연어 Q&A — 대시보드·API 공통.

- OPENAI_API_KEY + LLM: 질문에 맞춰 스냅샷만 근거로 답변
- LLM 없음: 키워드·스냅샷 요약 규칙 답변
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

SYSTEM_KO = """당신은 스마트팩토리 멀티 에이전트(MAS) 모니터링 도우미입니다.
아래 JSON은 현재 시스템이 제공하는 공장·에이전트·브로커 스냅샷입니다.

규칙:
- 한국어로 답합니다.
- 스냅샷에 있는 수치·상태만 근거로 말합니다. 없는 내용은 추측하지 말고 "제공된 데이터에는 없습니다"라고 합니다.
- 2~6문장 정도로 간결하게 합니다.
- 안전·고장 관련 표현은 스냅샷의 상태 필드를 우선합니다.
- "이전 대화"가 있으면 맥락만 참고하고, 수치·상태는 항상 아래 최신 JSON 스냅샷을 따릅니다."""


def build_qa_context(server: Any) -> Dict[str, Any]:
    """모니터링 페이로드에서 토큰 절약용 축약 컨텍스트."""
    mon = server._build_monitoring_payload()
    agents = mon.get("agents") or {}
    slim: Dict[str, Any] = {}
    for aid, a in agents.items():
        if not isinstance(a, dict):
            continue
        slim[aid] = {
            "state": a.get("state"),
            "last_reasoning": _truncate(a.get("last_reasoning"), 280),
            "cycle_count": a.get("cycle_count"),
            "inbox_size": a.get("inbox_size"),
        }
    br = mon.get("broker") or {}
    mbm = (br.get("metrics") or {}) if isinstance(br, dict) else {}
    fac = mon.get("factory") or {}
    rs = mon.get("router_snapshot") or {}
    rt = mon.get("runtime") or {}
    return {
        "factory": {
            "cycle": fac.get("cycle"),
            "clock": fac.get("clock"),
            "shift": fac.get("shift"),
            "avg_oee": fac.get("avg_oee"),
            "fg_stock": fac.get("fg_stock"),
            "total_produced": fac.get("total_produced"),
            "scrap_count": fac.get("scrap_count"),
        },
        "router_snapshot": rs,
        "broker": {
            "published": mbm.get("total_published"),
            "avg_latency_ms": mbm.get("avg_latency_ms"),
        },
        "agents": slim,
        "runtime": {
            "cnp_rounds_total": rt.get("cnp_count"),
            "events": rt.get("total_events"),
        },
        "mas_headline": (mon.get("mas_overview") or {}).get("headline"),
    }


def _truncate(s: Any, n: int) -> str:
    if s is None:
        return ""
    t = str(s).strip()
    return t if len(t) <= n else t[: n - 1] + "…"


def _format_history_block(history: Optional[List[Dict[str, Any]]], max_turns: int = 8) -> str:
    if not history:
        return ""
    lines: List[str] = []
    for h in history[-max_turns:]:
        if not isinstance(h, dict):
            continue
        role = str(h.get("role", "")).strip().lower()
        content = _truncate(h.get("content"), 1200)
        if not content:
            continue
        if role == "user":
            lines.append(f"사용자: {content}")
        elif role == "assistant":
            lines.append(f"도우미: {content}")
    if not lines:
        return ""
    return "## 이전 대화 (참고만, 수치는 아래 최신 스냅샷 우선)\n" + "\n".join(lines) + "\n\n"


def answer_monitoring_question(
    server: Any,
    llm: Any,
    question: str,
    history: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    질문에 대한 답변 dict.
    keys: answer (str), mode ('llm'|'heuristic'), error (optional)
    history: [{"role":"user"|"assistant","content":"..."}, ...]
    """
    q = (question or "").strip()
    if not q:
        return {"answer": "", "mode": "none", "error": "질문이 비어 있습니다."}
    if len(q) > 4000:
        q = q[:3997] + "…"

    ctx = build_qa_context(server)
    ctx_json = json.dumps(ctx, ensure_ascii=False, indent=2)
    hist_block = _format_history_block(history)

    if llm is not None and getattr(llm, "enabled", False):
        user = (
            f"{hist_block}"
            f"## 현재 스냅샷 (JSON)\n```json\n{ctx_json}\n```\n\n"
            f"## 이번 사용자 질문\n{q}"
        )
        text = llm.complete_text(SYSTEM_KO, user, max_tokens=1000, temperature=0.35)
        if text:
            return {"answer": text, "mode": "llm", "model": getattr(llm, "model", "")}

    return {
        "answer": _heuristic_answer(q, ctx),
        "mode": "heuristic",
        "hint": None if (llm and getattr(llm, "enabled", False)) else "OPENAI_API_KEY를 설정하면 자연어로 더 정교하게 답합니다.",
    }


def _heuristic_answer(question: str, ctx: Dict[str, Any]) -> str:
    """LLM 없을 때 간단 한국어 응답."""
    f = ctx.get("factory") or {}
    ag = ctx.get("agents") or {}
    br = ctx.get("broker") or {}
    rt = ctx.get("runtime") or {}
    rs = ctx.get("router_snapshot") or {}

    lines: list[str] = []

    if _wants_status(question):
        oee = f.get("avg_oee")
        oee_s = f"{float(oee)*100:.1f}%" if isinstance(oee, (int, float)) else "알 수 없음"
        lines.append(
            f"스냅샷 기준: 교대 {f.get('shift', '-')}, 시계 {f.get('clock', '-')}, "
            f"사이클 {f.get('cycle', '-')}, 평균 OEE(스냅샷) {oee_s}."
        )
        lines.append(
            f"완제품 재고 {f.get('fg_stock', '-')}, 누적 생산 {f.get('total_produced', '-')}, "
            f"폐기 {f.get('scrap_count', '-')}."
        )
        active = [aid for aid, a in ag.items() if isinstance(a, dict) and a.get("state") not in (None, "대기")]
        if active:
            lines.append("활성에 가까운 에이전트: " + ", ".join(active) + ".")
        st_parts = [f"{aid}:{(a or {}).get('state', '-')}" for aid, a in list(ag.items())[:6]]
        if st_parts:
            lines.append("에이전트 상태 요약 — " + " · ".join(st_parts) + ".")

    if _wants_oee(question) and not _wants_status(question):
        oee = f.get("avg_oee")
        if isinstance(oee, (int, float)):
            lines.append(f"평균 OEE(스냅샷): {oee*100:.1f}%.")

    if _wants_broker(question):
        lines.append(
            f"브로커: 누적 발행 {br.get('published', '-')}, 평균 지연 {br.get('avg_latency_ms', '-')} ms."
        )

    if _wants_cnp(question):
        lines.append(f"누적 CNP 협상 횟수(런타임): {rt.get('cnp_rounds_total', '-')}.")

    if _wants_sensor(question):
        lines.append(
            f"라우터 스냅샷: 진동 {rs.get('vibration_mm_s', '-')} mm/s, "
            f"유온 {rs.get('oil_temp_c', '-')} °C, 자재버퍼 {rs.get('material_buffer_hours', '-')} h."
        )

    if not lines:
        lines.append(
            "질문을 더 구체적으로 해 주세요. 예: «현재 상태 어때?», «OEE는?», «브로커 지연은?» "
            "OPENAI_API_KEY가 있으면 같은 스냅샷으로 자연어 답변이 가능합니다."
        )
    else:
        lines.append("(LLM 미연결 시 규칙 기반 요약입니다. 키 설정 시 문장형으로 보강됩니다.)")

    return "\n".join(lines)


def _wants_status(q: str) -> bool:
    return bool(
        re.search(r"상태|어때|어떻게|지금|현재|요약|개요|전반", q, re.I)
    )


def _wants_oee(q: str) -> bool:
    return bool(re.search(r"OEE|oee|설비.?효율|가동.?효율", q, re.I))


def _wants_broker(q: str) -> bool:
    return bool(re.search(r"브로커|메시지.?발행|지연|latency", q, re.I))


def _wants_cnp(q: str) -> bool:
    return bool(re.search(r"CNP|협상|제안", q, re.I))


def _wants_sensor(q: str) -> bool:
    return bool(re.search(r"진동|유온|온도|센서|버퍼", q, re.I))
