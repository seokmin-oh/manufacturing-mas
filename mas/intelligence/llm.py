"""
LLM Orchestration Client
========================

## 한국어 요약
- **역할**: 전략·상황 분석·근거 문장 등 **서술/JSON 보강**. 설비 PLC 를 직접 제어하지 않음.
- **수치 결정**: CNP 승자·목표 속도 등은 `optimization_engine` 규칙/솔버가 담당.
- **폴백**: API 키 없음·SDK 없음 시 동일 인터페이스로 규칙 기반 dict 반환.

## 배포 예시
  - OpenAI GPT-4o / GPT-4o-mini  (클라우드)
  - Azure OpenAI Service          (온프레미스 / 하이브리드)
  - vLLM + Llama 3                (완전 온프레미스)
  - 도메인 소형 모델은 `domain_inference` 훅 또는 MAS_LLM_DOMAIN_MODEL 로 확장
"""

import os
import json
import time
from typing import List, Optional, Dict, Any

from .domain_inference import infer_domain_signals
from .optimization_engine import (
    cnp_numeric_strategy,
    merge_numeric_and_rationale,
)
from .prompt_registry import PROMPT_SUITE_VERSION, prompt_metadata

try:
    from openai import OpenAI
    _HAS_OPENAI = True
except ImportError:
    _HAS_OPENAI = False


# ── 시스템 프롬프트 ───────────────────────────────────────────────

SYSTEM_PROMPT_PA = """\
당신은 자동차 부품 제조 공장의 Multi-Agent System에서 PlanningAgent(PA)입니다.

## 역할
6개 에이전트(EA·QA·SA·DA·IA)의 실시간 보고와 제안을 종합 분석하여,
**완제품 안전재고(SS)를 최소화**하면서 **서비스레벨 ≥ 95%**를 유지하는 통합 전략을 수립합니다.

## 핵심 공식
  SS = z × √(LT × σ_D² + d_avg² × σ_LT²)
  z = 1.645 (서비스레벨 95%)

## 도메인 지식
| 지표 | 정상 | 경고 | 위험 |
|------|------|------|------|
| 프레스 진동 | < 3.5 mm/s | 3.5–4.5 mm/s | ≥ 4.5 mm/s |
| Cpk | ≥ 1.33 | 1.0–1.33 | < 1.0 |
| 서비스레벨 | ≥ 95% | 90–95% | < 90% |

## 의사결정 원칙 (우선순위)
1. **설비 안전** — 인명·장비 보호 최우선
2. **품질 확보** — Cpk 하한 유지, 불량 유출 방지
3. **납기 준수** — 고객 서비스레벨 유지
4. **재고 최적화** — 불확실성 감소 시 SS 동적 하향

## 응답 규칙
- 반드시 **JSON만** 반환 (추가 텍스트 금지)
- 한국어로 작성
- 각 판단에 정량적 근거 포함"""


STRATEGY_PROMPT = """\
현재 상황:
- 프레스 진동: {vibration:.2f} mm/s (MA: {vibration_ma:.2f}, 기울기: {vibration_slope:+.3f})
- 유온: {oil_temp:.1f}°C
- 라인 속도: {line_speed_pct}%
- 완제품 재고: {stock}개 / 안전재고: {safety_stock}개
- 서비스레벨: {service_level:.1%}
- Cpk: {cpk_json}
- 예측 수율: {predicted_yield:.0%}
- 설비 가용능력: {capacity_factor:.0%}

에이전트 제안:
{proposals_text}

다음 JSON 스키마로 통합 전략을 수립하십시오:
{{
  "decision": "integrated_response",
  "target_speed_pct": <int: 40-100>,
  "inspection_mode": "<standard | enhanced>",
  "monitoring_interval_sec": <int: 5-120>,
  "negotiate_deadline": <bool>,
  "recalculate_ss": <bool>,
  "rationale": ["<이유1: 정량 근거 포함>", "<이유2>", ...],
  "risk_assessment": "<현재 핵심 리스크 1줄>",
  "expected_ss_impact": "<SS 변화 예측>",
  "best_agent": "<가장 높은 기여 에이전트 ID>",
  "best_score": <float>
}}"""


SITUATION_PROMPT = """\
현재 센서 데이터:
- 진동: {vibration:.2f} mm/s (MA: {vibration_ma:.2f})
- 유온: {oil_temp:.1f}°C
- 재고: {stock}개 / SS: {safety_stock}개 / SL: {service_level:.1%}

수신된 경보:
{alerts_text}

다음 JSON 형식으로 상황 분석을 반환하십시오:
{{
  "should_initiate_cnp": <bool>,
  "severity": "<LOW | MEDIUM | HIGH | CRITICAL>",
  "reasoning": "<판단 근거 1-2문장>",
  "immediate_actions": ["<즉시 조치>", ...],
  "risk_factors": ["<위험 요소>", ...]
}}"""


SYSTEM_RATIONALIZE = """\
당신은 제조 공장 PlanningAgent의 **서술 보조** 모델입니다.

## 절대 규칙
- **목표 속도·최우선 에이전트·점수는 이미 솔버가 확정**했습니다. 이를 바꾸지 마세요.
- 당신의 역할은 근거 문장·리스크·안전재고 영향 서술만 작성하는 것입니다.
- 반드시 **JSON만** 반환 (추가 텍스트 금지). 한국어."""


RATIONALIZE_USER = """\
## 확정된 수치 (이 값과 모순되면 안 됨)
{numeric_json}

## 현장 맥락
- 진동 {vibration:.2f} mm/s (MA {vibration_ma:.2f}), 유온 {oil_temp:.1f}°C, 라인 {line_speed_pct}%
- 재고 {stock} / 안전재고 {safety_stock}, 서비스레벨 {service_level:.1%}
- 도메인 신호(규칙·소형모델): {domain_json}

## 에이전트 제안 (참고)
{proposals_text}

다음 키**만** 포함하는 JSON을 반환하세요. target_speed_pct·best_agent·best_score는 넣지 마세요.
{{
  "rationale": ["<정량 근거가 든 이유1>", "<이유2>"],
  "risk_assessment": "<핵심 리스크 1줄>",
  "expected_ss_impact": "<SS 변화에 대한 질적 예측>",
  "negotiate_deadline": <bool>,
  "recalculate_ss": <bool>
}}"""


# ── LLM 클라이언트 ────────────────────────────────────────────────

class LLMClient:
    """
    PlanningAgent·라우터용 LLM 오케스트레이션.

    - OPENAI_API_KEY 환경변수 또는 생성자 인자로 API 키 설정
    - 키 미설정 시 자동으로 Rule-based 폴백
    - CNP 수치 선정은 솔버 우선, LLM은 근거 보강 (`RATIONALIZE_USER`)
    - `domain_model`: 불량/RUL 등 전용 소형 모델명(선택). 현재는 메타·추후 호출 분기용.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        model: str = "gpt-4o-mini",
        domain_model: Optional[str] = None,
        temperature: float = 0.15,
        max_tokens: int = 2000,
    ):
        self.model = model
        self.domain_model = (domain_model or "").strip() or None
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.prompt_suite_version = PROMPT_SUITE_VERSION

        self.client: Optional[Any] = None
        self.enabled = False
        self.fallback_reason = ""

        self.token_usage = {
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "calls": 0,
            "errors": 0,
        }
        self.call_log: List[Dict[str, Any]] = []
        self._max_call_log = 200
        self.audit_log: List[Dict[str, Any]] = []
        self._max_audit_log = 300

        resolved_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        if not resolved_key:
            self.fallback_reason = "OPENAI_API_KEY 미설정"
        elif not _HAS_OPENAI:
            self.fallback_reason = "openai 패키지 미설치 (pip install openai)"
        else:
            try:
                self.client = OpenAI(api_key=resolved_key)
                self.enabled = True
            except Exception as e:
                self.fallback_reason = str(e)

    def _audit(self, kind: str, meta: Dict[str, Any]) -> None:
        """프롬프트·컨텍스트·허용 필드 메타 감사 (수치 결정은 기록하지 않음)."""
        entry = {"kind": kind, "ts": time.time(), **meta}
        self.audit_log.append(entry)
        if len(self.audit_log) > self._max_audit_log:
            self.audit_log = self.audit_log[-self._max_audit_log // 2 :]

    # ── 내부 호출 ─────────────────────────────────────────────

    def _call(
        self,
        system: str,
        user: str,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
        model: Optional[str] = None,
        log_extra: Optional[Dict[str, Any]] = None,
    ) -> Optional[dict]:
        if not self.enabled:
            return None

        use_model = model or self.model
        t0 = time.time()
        try:
            resp = self.client.chat.completions.create(
                model=use_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature or self.temperature,
                max_tokens=max_tokens or self.max_tokens,
                response_format={"type": "json_object"},
            )

            usage = resp.usage
            if usage:
                self.token_usage["prompt_tokens"] += usage.prompt_tokens
                self.token_usage["completion_tokens"] += usage.completion_tokens
                self.token_usage["total_tokens"] += usage.total_tokens
            self.token_usage["calls"] += 1

            content = resp.choices[0].message.content
            result = json.loads(content)
            self._audit(
                "chat_completion_json",
                {
                    "model": use_model,
                    "prompt_chars": len(system) + len(user),
                    "response_keys": list(result.keys()) if isinstance(result, dict) else [],
                    "allowed_surface": "strategy_rationale_only",
                },
            )

            elapsed = round(time.time() - t0, 2)
            entry: Dict[str, Any] = {
                "model": use_model,
                "prompt_tokens": usage.prompt_tokens if usage else 0,
                "completion_tokens": usage.completion_tokens if usage else 0,
                "elapsed_sec": elapsed,
                "prompt_suite": self.prompt_suite_version,
            }
            if log_extra:
                entry.update(log_extra)
            self.call_log.append(entry)
            if len(self.call_log) > self._max_call_log:
                self.call_log = self.call_log[-self._max_call_log // 2:]

            return result

        except Exception as e:
            self.token_usage["errors"] += 1
            self.call_log.append({"error": str(e), "elapsed_sec": round(time.time() - t0, 2)})
            return None

    def complete_text(
        self,
        system: str,
        user: str,
        *,
        max_tokens: int = 700,
        temperature: float = 0.35,
        model: Optional[str] = None,
    ) -> Optional[str]:
        """자연어 답변용(모니터링 Q&A 등). JSON 강제 없음."""
        if not self.enabled or not self.client:
            return None
        use_model = model or self.model
        t0 = time.time()
        try:
            resp = self.client.chat.completions.create(
                model=use_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=temperature,
                max_tokens=max_tokens,
            )
            usage = resp.usage
            if usage:
                self.token_usage["prompt_tokens"] += usage.prompt_tokens
                self.token_usage["completion_tokens"] += usage.completion_tokens
                self.token_usage["total_tokens"] += usage.total_tokens
            self.token_usage["calls"] += 1
            content = (resp.choices[0].message.content or "").strip()
            self._audit(
                "chat_completion_text",
                {
                    "model": use_model,
                    "prompt_chars": len(system) + len(user),
                    "response_chars": len(content),
                    "allowed_surface": "monitoring_qa",
                },
            )
            elapsed = round(time.time() - t0, 2)
            self.call_log.append(
                {
                    "model": use_model,
                    "prompt_tokens": usage.prompt_tokens if usage else 0,
                    "elapsed_sec": elapsed,
                    "prompt_id": "monitoring_qa_v1",
                }
            )
            if len(self.call_log) > self._max_call_log:
                self.call_log = self.call_log[-self._max_call_log // 2:]
            return content or None
        except Exception as e:
            self.token_usage["errors"] += 1
            self.call_log.append({"error": str(e), "elapsed_sec": round(time.time() - t0, 2)})
            return None

    # ── 공개 API ──────────────────────────────────────────────

    def rationalize_cnp_decision(
        self,
        context: dict,
        proposals: List[dict],
        numeric: Dict[str, Any],
    ) -> Optional[dict]:
        """솔버 확정 수치에 대해 근거·리스크 JSON만 생성."""
        proposals_text = "\n".join(
            f"  [{p.get('agent', '?')}] {p.get('summary', p.get('proposal', ''))}  "
            f"점수: {json.dumps(p.get('scores', {}), ensure_ascii=False)}"
            for p in proposals
        )
        wh = context.get("warehouse", {})
        ds = context.get("domain_signals") or infer_domain_signals(context)
        user_msg = RATIONALIZE_USER.format(
            numeric_json=json.dumps(numeric, ensure_ascii=False, indent=2),
            vibration=float(context.get("vibration", 0) or 0),
            vibration_ma=float(context.get("vibration_ma", 0) or 0),
            oil_temp=float(context.get("oil_temp", 0) or 0),
            line_speed_pct=float(context.get("line_speed_pct", 100) or 100),
            stock=wh.get("stock", 0),
            safety_stock=wh.get("safety_stock", 0),
            service_level=float(wh.get("service_level", 1.0) or 1.0),
            domain_json=json.dumps(ds, ensure_ascii=False),
            proposals_text=proposals_text,
        )
        return self._call(
            SYSTEM_RATIONALIZE,
            user_msg,
            max_tokens=900,
            log_extra={"prompt_id": "cnp_rationale_v1"},
        )

    def evaluate_proposals(
        self, context: dict, proposals: List[dict]
    ) -> Optional[dict]:
        """
        CNP 통합 전략: 솔버로 수치·승자 고정 후 LLM은 근거 서술만(키 충돌 시 수치 우선).
        """
        if not proposals:
            return None

        numeric = cnp_numeric_strategy(proposals)
        if not numeric:
            return None

        rat: Optional[dict] = None
        if self.enabled:
            rat = self.rationalize_cnp_decision(context, proposals, numeric)

        merged = merge_numeric_and_rationale(numeric, rat)
        merged["decision"] = (
            "hybrid_solver_llm" if self.enabled and rat else "solver_only"
        )
        merged["prompt_suite_version"] = self.prompt_suite_version
        return merged

    def analyze_situation(
        self,
        env_data: dict,
        alerts: List[dict],
        agent_id: str = "PA",
    ) -> Optional[dict]:
        """실시간 상황 분석 + CNP 개시 여부 판단. agent_id 는 라우터가 호출한 에이전트 관점 힌트."""
        alerts_text = "\n".join(
            f"  - [{a.get('sender', '?')}] {a.get('type', '')}: {a.get('summary', '')}"
            for a in alerts
        ) or "  (없음)"

        wh = env_data.get("warehouse", {})
        ds = env_data.get("domain_signals") or infer_domain_signals(env_data)
        user_msg = SITUATION_PROMPT.format(
            vibration=env_data.get("vibration", 0),
            vibration_ma=env_data.get("vibration_ma", 0),
            oil_temp=env_data.get("oil_temp", 0),
            stock=wh.get("stock", 0),
            safety_stock=wh.get("safety_stock", 0),
            service_level=wh.get("service_level", 1.0),
            alerts_text=alerts_text,
        )
        user_msg += (
            "\n\n도메인 신호(불량·RUL 대역, 규칙 또는 소형 모델):\n"
            + json.dumps(ds, ensure_ascii=False)
        )
        if agent_id != "PA":
            user_msg = (
                f"## 라우터 호출 에이전트: {agent_id}\n"
                "동일 JSON 스키마를 유지하되, 이 에이전트 역할 관점에서 위험·즉시 조치를 우선 서술하세요.\n\n"
            ) + user_msg
        return self._call(
            SYSTEM_PROMPT_PA,
            user_msg,
            max_tokens=800,
            log_extra={"prompt_id": "situation_user_v1", "router_agent": agent_id},
        )

    # ── 상태 리포트 ───────────────────────────────────────────

    def get_status(self) -> dict:
        return {
            "enabled": self.enabled,
            "orchestrator_model": self.model,
            "domain_model": self.domain_model,
            "model": self.model,
            "prompt_suite": prompt_metadata(),
            "mode": f"LLM ({self.model})" if self.enabled else f"Rule-based ({self.fallback_reason})",
            "token_usage": self.token_usage.copy(),
            "call_count": len(self.call_log),
            "recent_calls": self.call_log[-5:],
        }
