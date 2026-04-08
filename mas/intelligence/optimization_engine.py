"""
수치·승자 선정 전용 레이어 — CNP에서 속도·최우선 제안은 LLM이 아닌 결정론적 규칙으로 고정.

LLM은 `mas/llm.py`의 rationalize 경로에서 근거 문장·리스크 서술만 보강한다.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .domain_inference import infer_domain_signals
from .snapshot_enrichment import enrich_snapshot_for_router

_NUMERIC_KEYS = (
    "target_speed_pct",
    "inspection_mode",
    "best_agent",
    "best_score",
    "decision",
)


def cnp_numeric_strategy(proposals: List[Dict[str, Any]]) -> Dict[str, Any]:
    """total_score 기준 최우선 제안 → 속도·검사 모드 등 수치 필드."""
    if not proposals:
        return {}
    ranked = sorted(
        proposals,
        key=lambda p: float(p.get("total_score", 0) or 0),
        reverse=True,
    )
    best = ranked[0]
    try:
        speed = int(float(best.get("speed_recommendation", best.get("target_speed_pct", 100))))
    except (TypeError, ValueError):
        speed = 100
    mode = best.get("inspection_mode", "standard")
    if isinstance(mode, str):
        m = mode.strip().lower()
        if "강화" in mode or "enhanced" in m:
            mode = "enhanced"
        elif "표준" in mode or "standard" in m:
            mode = "standard"
    return {
        "target_speed_pct": max(40, min(100, speed)),
        "inspection_mode": mode if mode in ("standard", "enhanced") else "standard",
        "best_agent": best.get("agent", ""),
        "best_score": float(best.get("total_score", 0) or 0),
        "decision": "solver_first",
    }


def build_llm_context(snapshot: Dict[str, Any]) -> Dict[str, Any]:
    """evaluate_proposals / analyze_situation 에 넣는 통합 컨텍스트."""
    ctx: Dict[str, Any] = enrich_snapshot_for_router(dict(snapshot))

    wh = snapshot.get("warehouse")
    if not isinstance(wh, dict):
        wh = {
            "stock": snapshot.get("fg_stock", 0),
            "safety_stock": snapshot.get("fg_safety_stock", 0),
            "service_level": snapshot.get("service_level", 0.95),
        }
    ctx["warehouse"] = wh

    stations = snapshot.get("stations") or {}
    wc01 = stations.get("WC-01") or {}
    sens = wc01.get("sensors") or {}
    vib = sens.get("vibration")
    if isinstance(vib, dict):
        ctx["vibration_ma"] = float(vib.get("ma", ctx.get("vibration", 0)) or 0)
        ctx["vibration_slope"] = float(vib.get("slope", 0) or 0)
    else:
        ctx.setdefault("vibration_ma", ctx.get("vibration", 0))
        ctx.setdefault("vibration_slope", 0.0)

    ctx["line_speed_pct"] = float(wc01.get("speed_pct", wc01.get("line_speed_pct", 100)) or 100)

    q = {}
    for sid, data in stations.items():
        if isinstance(data, dict) and "cpk" in data:
            q[sid] = data.get("cpk")
    if q:
        ctx["quality_cpk"] = q
    else:
        ctx.setdefault("quality_cpk", {})

    ctx["predicted_yield"] = float(snapshot.get("predicted_yield", 0.95) or 0.95)
    ctx["capacity_factor"] = float(snapshot.get("capacity_factor", 1.0) or 1.0)
    ctx["domain_signals"] = infer_domain_signals(snapshot)
    return ctx


def merge_numeric_and_rationale(
    numeric: Dict[str, Any],
    llm_part: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """수치는 항상 numeric 우선. LLM이 수치 키를 넣어도 무시한다."""
    out = dict(numeric)
    if not llm_part:
        out.setdefault(
            "rationale",
            ["솔버 선정 결과에 따른 규칙 기반 근거( LLM 미사용 또는 실패 )"],
        )
        out.setdefault("risk_assessment", "정보 부족 — 보수적 모니터링")
        out.setdefault("expected_ss_impact", "미평가")
        return out

    for k, v in llm_part.items():
        if k in _NUMERIC_KEYS:
            continue
        if k == "target_speed_pct" or k == "best_score":
            continue
        out[k] = v

    out.setdefault("rationale", ["솔버 결정에 대한 서술적 보강"])
    return out
