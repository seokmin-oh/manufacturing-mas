"""
Manufacturing MAS REST API + 운영 모니터링 대시보드
====================================================

## 생명주기
1. `MASApiServer(port)` — FastAPI 앱 생성(`_build_app`). uvicorn 은 아직 안 뜸.
2. `bind(broker, llm, env, agents, runtime, decision_router)` — **main.py** 가 런타임과 같은
   객체 참조를 넣어 줌. `broker.on_message` 로 SSE용 훅 연결.
3. `start()` — 별도 **데몬 스레드**에서 uvicorn 실행(포트 충돌 시 `enabled=False`).
4. `stop()` — `should_exit` 로 서버 종료 신호.

## factory_bound
`bind` 에 `env`(Factory) 가 없으면 `/api/factory` 등이 빈 JSON — **API만 단독 실행**한 경우.

## 대시보드 HTML
`mas/api/static/dashboard.html` 에서 로드. CSS/JS 인라인 단일 파일.

## 주요 Endpoints
  GET  /                  운영 모니터링 대시보드
  GET  /api/factory       공장 전체 스냅샷
  GET  /api/agents        에이전트 상태 + 추론 이력
  GET  /api/messages      메시지 로그
  GET  /api/broker        브로커 메트릭
  GET  /api/kpi           공장 KPI 요약
  GET  /api/monitoring    통합 모니터링(JSON)
  POST /api/ask           자연어 질문(현재 스냅샷 기준 답변)
  GET  /api/router        하이브리드 라우터 메트릭
  GET  /api/stream        SSE (message, factory_tick)
  GET  /api/manufacturing/profile  표준 agent_id / station_id (확장·외부 연동용)
"""

import json
import logging
import time
import threading
from queue import Queue, Empty, Full
from typing import Dict, Any, List, Optional

_log = logging.getLogger(__name__)

from ..core import logger

try:
    from fastapi import FastAPI, Request
    from fastapi.responses import HTMLResponse, StreamingResponse, JSONResponse
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn
    _HAS_FASTAPI = True
except ImportError:
    Request = object  # type: ignore
    _HAS_FASTAPI = False


import pathlib as _pathlib


def _load_dashboard_html() -> str:
    _html_path = _pathlib.Path(__file__).with_name("static") / "dashboard.html"
    try:
        return _html_path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return "<h1>dashboard.html not found</h1>"


DASHBOARD_HTML = _load_dashboard_html()


class MASApiServer:
    """
    FastAPI 앱 래퍼 + uvicorn 백그라운드 스레드.

    - `_build_app` 안에서 라우트를 클로저로 등록하며 `server` 변수로 self 에 접근.
    - SSE 클라이언트마다 `Queue` 를 `_sse_queues` 에 넣고 `push_event` / 브로커 콜백으로 채움.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 8787):

        self.host = host
        self.port = port
        self.app: Any = None
        self._thread: Optional[threading.Thread] = None
        self._server = None
        self._running = False
        self.enabled = _HAS_FASTAPI

        self._broker: Any = None
        self._llm: Any = None
        self._env: Any = None  # Factory object
        self._agents: Dict[str, Any] = {}
        self._state: Dict[str, Any] = {"start_time": time.time(), "cycle": 0}
        self._sse_queues: List[Queue] = []
        self._runtime: Any = None
        self._decision_router: Any = None

        if self.enabled:
            self._build_app()

    def _build_app(self):
        """FastAPI 인스턴스 생성, CORS·선택적 Bearer 미들웨어, 전 REST 라우트 등록."""

        from ..core.config import get_settings
        from .. import __version__ as mas_version

        settings = get_settings()
        self.app = FastAPI(title="Manufacturing MAS API", version=mas_version)
        self.app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_origin_list(),
            allow_methods=["*"],
            allow_headers=["*"],
        )
        server = self

        @self.app.middleware("http")
        async def _optional_api_key(request: Request, call_next):
            """MAS_API_BEARER_TOKEN 이 설정된 경우에만 /api/* 에 Bearer 또는 ?token= 검사."""

            token = settings.api_bearer_token
            if not token or request.url.path in ("/", "/docs", "/openapi.json", "/redoc"):
                return await call_next(request)
            if not str(request.url.path).startswith("/api"):
                return await call_next(request)
            auth = request.headers.get("Authorization", "")
            q = request.query_params.get("token")
            ok = q == token
            if auth.startswith("Bearer "):
                ok = ok or auth[7:].strip() == token
            if not ok:
                return JSONResponse({"detail": "Unauthorized"}, status_code=401)
            return await call_next(request)

        @self.app.get("/", response_class=HTMLResponse)
        async def dashboard():
            return DASHBOARD_HTML

        @self.app.get("/api/status")
        async def get_status():
            from .. import __version__ as mas_version

            rt = server._runtime
            return JSONResponse({
                "system": "Manufacturing MAS v5.0",
                "version": mas_version,
                "factory_bound": server._env is not None,
                "cycle": server._env.cycle if server._env else 0,
                "uptime_sec": round(time.time() - server._state.get("start_time", time.time()), 1),
                "total_events": rt.total_events if rt else 0,
                "cnp_count": rt.cnp_count if rt else 0,
            })

        @self.app.get("/api/manufacturing/profile")
        async def manufacturing_profile():
            """표준 6역할·6공정 ID — 대시보드·통합 시스템이 동일 스키마를 쓰도록."""
            from ..core.manufacturing_ids import (
                AGENT_IDS,
                PROFILE_SCHEMA_VERSION,
                STATION_IDS,
            )

            return JSONResponse(
                {
                    "schema_version": PROFILE_SCHEMA_VERSION,
                    "agent_ids": list(AGENT_IDS),
                    "station_ids": list(STATION_IDS),
                }
            )

        @self.app.get("/api/factory")
        async def get_factory():
            if not server._env:
                return JSONResponse({})
            try:
                return JSONResponse(server._env.get_snapshot())
            except Exception as e:
                return JSONResponse({"error": str(e)})

        @self.app.get("/api/kpi")
        async def get_kpi():
            if not server._env:
                return JSONResponse({})
            try:
                return JSONResponse(server._env.get_kpi_summary())
            except Exception as e:
                return JSONResponse({"error": str(e)})

        @self.app.get("/api/agents")
        async def get_agents():
            out = {}
            for aid, agent in server._agents.items():
                out[aid] = agent.get_agent_status()
            return JSONResponse(out)

        @self.app.get("/api/monitoring")
        async def get_monitoring():
            return JSONResponse(server._build_monitoring_payload())

        @self.app.post("/api/ask")
        async def post_ask(request: Request):
            """자연어 질문 → 현재 모니터링 스냅샷 기준 답변(LLM 또는 규칙)."""
            from ..intelligence.monitoring_qa import answer_monitoring_question

            try:
                body = await request.json()
            except Exception:
                body = {}
            q = str((body or {}).get("question", "")).strip()
            raw_hist = (body or {}).get("history")
            hist = None
            if isinstance(raw_hist, list):
                hist = []
                for item in raw_hist[-12:]:
                    if not isinstance(item, dict):
                        continue
                    role = item.get("role")
                    if role not in ("user", "assistant"):
                        continue
                    c = str(item.get("content", ""))[:2000]
                    if c:
                        hist.append({"role": role, "content": c})
                if not hist:
                    hist = None
            try:
                out = answer_monitoring_question(server, server._llm, q, history=hist)
                return JSONResponse(out)
            except Exception as e:
                return JSONResponse(
                    {"answer": "", "mode": "error", "error": str(e)},
                    status_code=500,
                )

        @self.app.get("/api/router")
        async def get_router():
            dr = server._decision_router
            if not dr:
                return JSONResponse({"enabled": False})
            try:
                return JSONResponse(dr.get_status())
            except Exception as e:
                return JSONResponse({"error": str(e)})

        @self.app.get("/api/messages")
        async def get_messages():
            if not server._broker:
                return JSONResponse({"messages": [], "total": 0})
            try:
                msgs = [e.to_dict() for e in server._broker.envelope_log[-100:]]
                return JSONResponse({"messages": msgs, "total": len(server._broker.envelope_log)})
            except Exception:
                return JSONResponse({"messages": [], "total": 0})

        @self.app.get("/api/broker")
        async def get_broker():
            return JSONResponse(server._broker.get_status() if server._broker else {})

        @self.app.get("/api/llm")
        async def get_llm():
            return JSONResponse(server._llm.get_status() if server._llm else {"enabled": False})

        @self.app.get("/api/stream")
        async def sse_stream():
            q: Queue = Queue(maxsize=200)
            server._sse_queues.append(q)
            async def gen():
                try:
                    while server._running:
                        try:
                            data = q.get(timeout=1.0)
                            yield f"data: {json.dumps(data, ensure_ascii=False)}\n\n"
                        except Empty:
                            yield ": heartbeat\n\n"
                finally:
                    if q in server._sse_queues:
                        server._sse_queues.remove(q)
            return StreamingResponse(gen(), media_type="text/event-stream",
                                     headers={"Cache-Control": "no-cache", "Connection": "keep-alive"})

    def bind(
        self,
        broker=None,
        llm=None,
        env=None,
        agents=None,
        runtime=None,
        decision_router=None,
        **kwargs,
    ):
        """시뮬레이터 프로세스가 가진 단일 공장·에이전트·브로커 인스턴스를 API에 연결."""

        self._broker = broker
        self._llm = llm
        self._env = env
        self._runtime = runtime
        self._decision_router = decision_router
        if agents:
            self._agents = {a.agent_id: a for a in agents}
        self._state["start_time"] = time.time()
        if broker:
            broker.on_message(self._on_broker_message)

    def _build_monitoring_payload(self) -> Dict[str, Any]:
        """통합 모니터링 JSON — 대시보드·외부 대시보드 연동용."""
        from ..core.config import get_settings
        from ..intelligence.agent_domain_registry import build_factory_coverage_payload
        from ..intelligence.control_matrix import build_control_payload
        from ..intelligence.multi_agent_teams import build_multi_agent_teams_payload
        from ..intelligence.collaboration_view import build_collaboration_payload
        from ..intelligence.mas_overview import build_mas_overview_payload
        from ..intelligence.equipment_predictive_models import model_catalog as pm_model_catalog
        from ..intelligence.snapshot_enrichment import enrich_snapshot_for_router
        from ..domain.manufacturing_context import from_factory_snapshot

        settings = get_settings()
        control_matrix = build_control_payload(settings)

        env = self._env
        rt = self._runtime
        snap: Dict[str, Any] = {}
        if env:
            try:
                snap = env.get_snapshot()
            except Exception as e:
                _log.debug("모니터링 스냅샷 취득 실패: %s", e)

        enriched: Dict[str, Any] = {}
        if snap:
            try:
                enriched = enrich_snapshot_for_router(snap)
            except Exception as e:
                _log.debug("스냅샷 enrichment 실패: %s", e)
                enriched = {}

        agents_out: Dict[str, Any] = {}
        for aid, agent in self._agents.items():
            try:
                agents_out[aid] = agent.get_agent_status()
            except Exception as e:
                _log.debug("에이전트 %s 상태 취득 실패: %s", aid, e)
                agents_out[aid] = {"agent_id": aid, "error": "status_failed"}

        dr_status: Dict[str, Any] = {"enabled": False}
        if self._decision_router:
            try:
                dr_status = self._decision_router.get_status()
                dr_status["enabled"] = True
            except Exception as e:
                dr_status = {"enabled": True, "error": str(e)}

        ea_pm = agents_out.get("EA") or {}
        try:
            mas_overview = build_mas_overview_payload()
        except Exception as e:
            logger.print_message_json({"mas_overview_build_error": str(e)})
            mas_overview = {
                "headline": "에이전트 요약(오류)",
                "lead": "요약 실패. 역할 표는 factory_coverage 참고.",
                "roles": [],
                "collaboration": {"title": "협업", "points": []},
                "implementation_note": str(e)[:200],
            }

        mctx: Dict[str, Any] = {}
        if snap:
            try:
                mctx = from_factory_snapshot(snap).to_dict()
            except Exception as e:
                _log.debug("ManufacturingContext 변환 실패: %s", e)
                mctx = {}

        return {
            "timestamp": time.time(),
            "manufacturing_context": mctx,
            "mas_overview": mas_overview,
            "collaboration_view": build_collaboration_payload(self._broker),
            "factory_coverage": build_factory_coverage_payload(),
            "multi_agent_teams": build_multi_agent_teams_payload(),
            "control_matrix": control_matrix,
            "equipment_catalog": pm_model_catalog(),
            "equipment_monitoring": ea_pm.get("equipment_by_station") or {},
            "data_flow": {
                "pipeline": [
                    {
                        "step": 1,
                        "name": "공장 환경 틱",
                        "detail": "공정·센서·에너지·재고·출하·시뮬 시계 갱신",
                    },
                    {
                        "step": 2,
                        "name": "에이전트 루프 (6종)",
                        "detail": "택트마다 관측 → 판단 → 행동 · 브로커로 메시지 교환",
                    },
                    {
                        "step": 3,
                        "name": "판단 라우터",
                        "detail": "안전·임계 규칙 우선, 필요 시 상황 분석 경로",
                    },
                    {
                        "step": 4,
                        "name": "CNP 협상 (계획)",
                        "detail": "제안 수집 → 정규화·점수 → 솔버로 전략 확정",
                    },
                    {
                        "step": 5,
                        "name": "관측·대시보드",
                        "detail": "REST 폴링 + SSE로 틱·메시지 반영",
                    },
                ],
            },
            "factory": {
                "cycle": snap.get("cycle"),
                "clock": snap.get("clock"),
                "shift": snap.get("shift"),
                "avg_oee": snap.get("avg_oee"),
                "fg_stock": snap.get("fg_stock"),
                "total_produced": snap.get("total_produced"),
                "scrap_count": snap.get("scrap_count"),
                "stations_count": len(snap.get("stations") or {}),
            },
            "router_snapshot": {
                "vibration_mm_s": enriched.get("vibration"),
                "oil_temp_c": enriched.get("oil_temp"),
                "material_buffer_hours": enriched.get("material_buffer_hours"),
            },
            "agents": agents_out,
            "broker": self._broker.get_status() if self._broker else {},
            "llm": self._llm.get_status() if self._llm else {"enabled": False},
            "decision_router": dr_status,
            "runtime": {
                "uptime_sec": round(rt.uptime, 1) if rt else 0,
                "total_events": rt.total_events if rt else 0,
                "cnp_count": rt.cnp_count if rt else 0,
            },
        }

    def _on_broker_message(self, envelope):
        """브로커 `on_message` 훅 — 모든 SSE 구독자 큐에 message 이벤트 push."""

        msg = envelope.message
        event = {
            "type": "message",
            "sender": msg.header.sender,
            "receiver": msg.header.receiver,
            "intent": msg.intent.value,
            "topic": envelope.topic.value,
            "summary": msg.body.get("summary", ""),
            "timestamp": msg.header.timestamp,
        }
        for q in list(self._sse_queues):
            try:
                q.put_nowait(event)
            except Full:
                _log.debug("SSE 큐 가득참 — 이벤트 드롭")
            except Exception as e:
                _log.debug("SSE 큐 push 실패: %s", e)

    def push_event(self, event_type: str, data: dict):
        """런타임(`FactoryRuntime`) 등에서 factory_tick 등 임의 이벤트를 SSE 로 브로드캐스트."""

        event = {"type": event_type, **data}
        for q in list(self._sse_queues):
            try:
                q.put_nowait(event)
            except Full:
                _log.debug("SSE 큐 가득참 — 이벤트 드롭")
            except Exception as e:
                _log.debug("SSE 큐 push 실패: %s", e)

    def start(self):
        """포트 사용 가능 여부를 소켓으로 선검사 후 uvicorn.Server 를 데몬 스레드에서 run."""

        if not self.enabled:
            return
        self._running = True
        def _run():
            import socket
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                sock.bind((self.host, self.port))
            except OSError:
                self.enabled = False
                sock.close()
                return
            sock.close()
            config = uvicorn.Config(
                self.app, host=self.host, port=self.port,
                log_level="error", access_log=False,
            )
            self._server = uvicorn.Server(config)
            self._server.run()

        self._thread = threading.Thread(target=_run, daemon=True, name="MAS-API")
        self._thread.start()

    def stop(self):
        """메인 프로세스 종료 시 서버 루프에 종료 플래그 전달."""

        self._running = False
        if self._server:
            self._server.should_exit = True


def _safe(v: Any) -> Any:
    if isinstance(v, (str, int, float, bool, type(None))):
        return v
    if isinstance(v, list):
        return [_safe(i) for i in v[:20]]
    if isinstance(v, dict):
        return {str(k): _safe(val) for k, val in list(v.items())[:20]}
    return str(v)
