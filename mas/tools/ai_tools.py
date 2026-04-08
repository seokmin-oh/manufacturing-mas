"""
AI Tool Registry — 에이전트가 호출할 수 있는 AI 모델 API 패키징
==================================================================
실제 환경에서는 TF Serving / TorchServe / FastAPI micro-service로 배포.
여기서는 mock_models.py 함수들을 Tool 추상화로 래핑하여
에이전트가 `tool_registry.call("vision_inspection", {...})` 형태로 호출한다.

Tool 카테고리:
  1. vision_inspection    — 비전 검사 (치수 측정 + 양불 판정)
  2. defect_prediction    — AI 불량 예측 (XGBoost/LSTM mock)
  3. predictive_maint     — 예지보전 (RUL 추정, 정비 권고)
  4. demand_forecast      — 수요 예측 (시계열 분석)
  5. capacity_estimation  — 설비 가용능력 예측
  6. yield_prediction     — 수율 예측
  7. spc_analysis         — SPC 공정능력 분석 (Cpk)
  8. leadtime_estimation  — 리드타임 변동성 추정
  9. oee_calculator       — OEE (종합설비효율) 산출
  10. safety_stock_calc   — 안전재고 공식 계산

각 Tool은 다음을 포함:
  - name, description, version
  - input_schema (파라미터 정의)
  - output_schema
  - call(**kwargs) → dict
  - latency_ms, call_count (메트릭)
"""

import time
import math
import threading
from dataclasses import dataclass, field
from typing import Dict, Any, Callable, List, Optional
from . import mock_models


@dataclass
class ToolParameter:
    name: str
    type: str  # "float", "int", "str", "list", "dict"
    description: str
    required: bool = True
    default: Any = None


@dataclass
class ToolMetrics:
    call_count: int = 0
    total_latency_ms: float = 0.0
    errors: int = 0
    last_called: float = 0.0

    @property
    def avg_latency_ms(self) -> float:
        return round(self.total_latency_ms / max(self.call_count, 1), 2)

    def to_dict(self) -> dict:
        return {
            "call_count": self.call_count,
            "avg_latency_ms": self.avg_latency_ms,
            "errors": self.errors,
        }


@dataclass
class AITool:
    """에이전트가 호출할 수 있는 개별 AI 모델/함수."""
    name: str
    description: str
    category: str          # "inspection", "prediction", "optimization", "analysis"
    version: str
    owner_agent: str       # 이 도구를 주로 사용하는 에이전트 ID
    parameters: List[ToolParameter]
    _fn: Callable = field(repr=False)
    metrics: ToolMetrics = field(default_factory=ToolMetrics)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def call(self, **kwargs) -> dict:
        """도구 실행 + 메트릭 수집."""
        t0 = time.perf_counter()
        try:
            result = self._fn(**kwargs)
            elapsed = (time.perf_counter() - t0) * 1000
            with self._lock:
                self.metrics.call_count += 1
                self.metrics.total_latency_ms += elapsed
                self.metrics.last_called = time.time()
            return {"status": "ok", "tool": self.name, "result": result, "latency_ms": round(elapsed, 2)}
        except Exception as e:
            with self._lock:
                self.metrics.errors += 1
            return {"status": "error", "tool": self.name, "error": str(e)}

    def get_schema(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "version": self.version,
            "owner_agent": self.owner_agent,
            "parameters": [
                {"name": p.name, "type": p.type, "description": p.description,
                 "required": p.required, "default": p.default}
                for p in self.parameters
            ],
            "metrics": self.metrics.to_dict(),
        }


class ToolRegistry:
    """
    AI 모델 Tool Registry.
    에이전트가 필요할 때 `registry.call("tool_name", ...)` 으로 호출.
    REST API `/api/tools/{name}/invoke` 로도 외부 호출 가능.
    """

    def __init__(self):
        self._tools: Dict[str, AITool] = {}
        self._lock = threading.Lock()
        self._call_log: List[dict] = []
        self._register_builtin_tools()

    def register(self, tool: AITool):
        with self._lock:
            self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[AITool]:
        return self._tools.get(name)

    def list_tools(self) -> List[dict]:
        return [t.get_schema() for t in self._tools.values()]

    def list_by_agent(self, agent_id: str) -> List[dict]:
        return [t.get_schema() for t in self._tools.values() if t.owner_agent == agent_id]

    def call(self, name: str, **kwargs) -> dict:
        tool = self._tools.get(name)
        if not tool:
            return {"status": "error", "error": f"Tool '{name}' not found"}
        result = tool.call(**kwargs)
        with self._lock:
            self._call_log.append({
                "tool": name, "status": result["status"],
                "latency_ms": result.get("latency_ms", 0),
                "timestamp": time.time(),
            })
            if len(self._call_log) > 500:
                self._call_log = self._call_log[-250:]
        return result

    def get_metrics(self) -> dict:
        total_calls = sum(t.metrics.call_count for t in self._tools.values())
        total_errors = sum(t.metrics.errors for t in self._tools.values())
        return {
            "total_tools": len(self._tools),
            "total_calls": total_calls,
            "total_errors": total_errors,
            "tools": {n: t.metrics.to_dict() for n, t in self._tools.items()},
        }

    # ── 내장 도구 등록 ────────────────────────────────────────

    def _register_builtin_tools(self):

        # 1. 비전 검사 (QA)
        self.register(AITool(
            name="vision_inspection",
            description="비전 카메라 기반 제품 치수 측정 (두께, 버, 평탄도)",
            category="inspection",
            version="1.0.0",
            owner_agent="QA",
            parameters=[
                ToolParameter("vibration_level", "float", "현재 프레스 진동값 (mm/s)"),
                ToolParameter("weld_deviation", "float", "용접 전류 편차율", False, 0.0),
            ],
            _fn=lambda vibration_level, weld_deviation=0.0: _wrap_measurements(
                mock_models.generate_measurements(vibration_level, weld_deviation)),
        ))

        # 2. AI 불량 예측 (QA)
        self.register(AITool(
            name="defect_prediction",
            description="센서 데이터 기반 불량 확률 예측 (XGBoost/LSTM)",
            category="prediction",
            version="2.1.0",
            owner_agent="QA",
            parameters=[
                ToolParameter("vibration", "float", "프레스 진동값"),
                ToolParameter("oil_temp", "float", "유압유 온도"),
                ToolParameter("vibration_trend_slope", "float", "진동 추세 기울기"),
                ToolParameter("recent_burr_mean", "float", "최근 5개 버 높이 평균"),
            ],
            _fn=mock_models.predict_defect_probability,
        ))

        # 3. 예지보전 (EA)
        self.register(AITool(
            name="predictive_maintenance",
            description="설비 진동/추세 기반 정비 시기·긴급도 예측",
            category="prediction",
            version="1.2.0",
            owner_agent="EA",
            parameters=[
                ToolParameter("vibration", "float", "현재 진동값"),
                ToolParameter("trend_slope", "float", "진동 추세 기울기"),
            ],
            _fn=mock_models.estimate_maintenance,
        ))

        # 4. 수요 예측 (DA)
        self.register(AITool(
            name="demand_forecast",
            description="과거 수요 패턴 기반 향후 수요 예측 (ARIMA/Prophet)",
            category="prediction",
            version="1.0.0",
            owner_agent="DA",
            parameters=[
                ToolParameter("demand_history", "list", "최근 수요 이력 (숫자 리스트)"),
                ToolParameter("horizon", "int", "예측 기간 (사이클 수)", False, 10),
            ],
            _fn=_demand_forecast_fn,
        ))

        # 5. 설비 가용능력 (EA)
        self.register(AITool(
            name="capacity_estimation",
            description="설비 상태 기반 생산능력 계수 예측",
            category="prediction",
            version="1.1.0",
            owner_agent="EA",
            parameters=[
                ToolParameter("vibration", "float", "현재 진동값"),
                ToolParameter("vib_slope", "float", "진동 추세 기울기"),
                ToolParameter("speed_pct", "int", "현재 라인 속도 (%)"),
            ],
            _fn=mock_models.predict_capacity_factor,
        ))

        # 6. 수율 예측 (QA)
        self.register(AITool(
            name="yield_prediction",
            description="품질 데이터 기반 수율 계수 예측",
            category="prediction",
            version="1.0.0",
            owner_agent="QA",
            parameters=[
                ToolParameter("cpk_worst", "float", "최악 Cpk 값"),
                ToolParameter("defect_prob", "float", "불량 예측 확률"),
            ],
            _fn=mock_models.predict_yield_factor,
        ))

        # 7. SPC 분석 (QA)
        self.register(AITool(
            name="spc_analysis",
            description="SPC 공정능력지수 Cpk 계산",
            category="analysis",
            version="1.0.0",
            owner_agent="QA",
            parameters=[
                ToolParameter("values", "list", "측정값 리스트"),
                ToolParameter("usl", "float", "규격 상한"),
                ToolParameter("lsl", "float", "규격 하한"),
            ],
            _fn=lambda values, usl, lsl: {"cpk": mock_models.calculate_cpk(values, usl, lsl)},
        ))

        # 8. 리드타임 추정 (IA)
        self.register(AITool(
            name="leadtime_estimation",
            description="가용능력·수율 기반 실효 리드타임 및 변동성 계산",
            category="optimization",
            version="1.0.0",
            owner_agent="IA",
            parameters=[
                ToolParameter("capacity_factor", "float", "설비 가용능력 계수"),
                ToolParameter("yield_factor", "float", "수율 계수"),
                ToolParameter("base_takt_sec", "float", "기본 택트타임 (초)", False, 45.0),
            ],
            _fn=mock_models.compute_leadtime_params,
        ))

        # 9. OEE 산출 (PA)
        self.register(AITool(
            name="oee_calculator",
            description="종합설비효율(OEE) 산출",
            category="analysis",
            version="1.0.0",
            owner_agent="PA",
            parameters=[
                ToolParameter("produced", "int", "총 생산량"),
                ToolParameter("good", "int", "양품 수"),
                ToolParameter("planned", "int", "계획 수량"),
                ToolParameter("downtime_min", "float", "다운타임 (분)"),
            ],
            _fn=mock_models.calculate_oee,
        ))

        # 10. 안전재고 공식 (IA)
        self.register(AITool(
            name="safety_stock_calc",
            description="안전재고 공식 계산: SS = z × √(LT×σ_D² + d²×σ_LT²)",
            category="optimization",
            version="1.0.0",
            owner_agent="IA",
            parameters=[
                ToolParameter("z_score", "float", "서비스레벨 z값 (1.645=95%)"),
                ToolParameter("leadtime_mean", "float", "평균 리드타임"),
                ToolParameter("demand_std", "float", "수요 표준편차"),
                ToolParameter("avg_demand", "float", "평균 수요"),
                ToolParameter("leadtime_std", "float", "리드타임 표준편차"),
            ],
            _fn=_safety_stock_formula,
        ))


# ── 도구용 헬퍼 함수 ──────────────────────────────────────────────

def _wrap_measurements(measurements: dict) -> dict:
    """Measurement 객체를 dict로 변환."""
    return {
        k: {"value": m.value, "unit": m.unit, "in_spec": m.in_spec,
             "margin_pct": m.margin_pct, "nominal": m.nominal}
        for k, m in measurements.items()
    }


def _demand_forecast_fn(demand_history: list, horizon: int = 10) -> dict:
    """이동평균 + 추세 기반 수요 예측 (실제: ARIMA/Prophet)."""
    if len(demand_history) < 3:
        avg = sum(demand_history) / max(len(demand_history), 1) if demand_history else 1.0
        return {"forecast": [avg] * horizon, "trend": 0.0, "confidence": 0.5}

    n = len(demand_history)
    recent = demand_history[-min(10, n):]
    avg = sum(recent) / len(recent)

    if n >= 5:
        first_half = sum(recent[:len(recent)//2]) / max(len(recent)//2, 1)
        second_half = sum(recent[len(recent)//2:]) / max(len(recent) - len(recent)//2, 1)
        trend = (second_half - first_half) / max(len(recent)//2, 1)
    else:
        trend = 0.0

    import random
    forecast = []
    for i in range(horizon):
        val = max(0, avg + trend * (i + 1) + random.gauss(0, max(1, avg * 0.1)))
        forecast.append(round(val, 1))

    std = (sum((x - avg)**2 for x in recent) / len(recent)) ** 0.5 if len(recent) > 1 else 0

    return {
        "forecast": forecast,
        "trend": round(trend, 3),
        "mean": round(avg, 2),
        "std": round(std, 3),
        "confidence": round(min(0.95, 0.5 + len(demand_history) * 0.03), 2),
    }


def _safety_stock_formula(z_score: float, leadtime_mean: float, demand_std: float,
                          avg_demand: float, leadtime_std: float) -> dict:
    """SS = z × √(LT × σ_D² + d_avg² × σ_LT²)"""
    variance = leadtime_mean * (demand_std ** 2) + (avg_demand ** 2) * (leadtime_std ** 2)
    ss = z_score * math.sqrt(max(0, variance))
    return {
        "safety_stock": round(ss),
        "variance": round(variance, 4),
        "formula": f"SS = {z_score} × √({leadtime_mean}×{demand_std}² + {avg_demand}²×{leadtime_std}²)",
        "z_score": z_score,
    }
