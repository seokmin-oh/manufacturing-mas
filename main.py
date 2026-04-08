"""
제조 멀티 AI 에이전트 시스템 v5 — 실제 공장 시뮬레이션
====================================================

## 무엇을 하나
- 6공정 생산라인 (블랭킹→포밍→용접→열처리→CNC→조립/검사)을 **메모리 상의 Factory 객체**로 시뮬.
- 6종 에이전트(EA·QA·SA·DA·IA·PA)가 **각각 별도 스레드**로 주기적으로 깨어나
  공장 스냅샷을 읽고 Sense→Reason→Act 루프를 돈다.
- 에이전트 간 통신은 **MessageBroker**(토픽·에이전트별 큐). 위기 시 PA가 **CNP**로 제안을 모은다.
- **HybridDecisionRouter**: 안전·임계는 규칙, 복합 상황만 조건부 LLM.
- 선택적으로 **FastAPI** 대시보드가 같은 프로세스의 Factory/브로커와 **bind** 된다.

## 데이터 흐름 (한 줄)
  Factory.run_cycle (ENV 스레드) → get_snapshot 캐시 → 각 AGENT 스레드가 스냅샷 소비
  → 브로커로 ALERT/CNP 등 송수신 → (선택) API/SSE로 브라우저에 전달

## 실행
  pip install -r requirements.txt
  python main.py
  대시보드: http://localhost:<MAS_API_PORT 기본 8787>
  종료: Ctrl+C

구현 세부는 `CURRENT_SYSTEM_GUIDE.md`, `MAS_SYSTEM_REFERENCE.md` 참고.
"""

import sys
import os
import time
import logging

os.environ["PYTHONUNBUFFERED"] = "1"
sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1)

from mas.core.config import get_settings
from mas.core.logging_config import setup_logging
from mas import __version__ as MAS_VERSION
from mas.domain.environment import Factory
from mas.messaging.broker import MessageBroker
from mas.messaging.mqtt_bridge import MQTTBridge
from mas.intelligence.llm import LLMClient
from mas.agents.equipment_agent import EquipmentAgent
from mas.agents.quality_agent import QualityAgent
from mas.agents.supply_agent import SupplyAgent
from mas.agents.demand_agent import DemandAgent
from mas.agents.inventory_agent import InventoryAgent
from mas.agents.planning_agent import PlanningAgent
from mas.intelligence.decision_router import HybridDecisionRouter
from mas.runtime import (
    FactoryRuntime, print_factory_header, print_factory_row,
    print_factory_summary, STATION_SHORT,
)
from mas.core import logger
from mas.core.logger import C


def main():
    """전체 시뮬레이터 조립 후 블로킹 메인 루프(터미널 표)까지 담당."""
    settings = get_settings()
    setup_logging(settings.log_level)
    log = logging.getLogger(__name__)

    # ═══════════════════════════════════════════════════════
    # 1. 인프라 초기화
    # 브로커·MQTT·LLM·라우터는 에이전트보다 먼저 만든다. 에이전트는 broker.register 시
    # 자신의 inbox/outbox와 토픽 구독이 연결된다.
    # ═══════════════════════════════════════════════════════

    broker = MessageBroker()
    mqtt = MQTTBridge()
    llm = LLMClient(
        model=settings.llm_model,
        domain_model=settings.llm_domain_model or None,
    )
    decision_router = HybridDecisionRouter(
        llm_client=llm,
        llm_router_scope=settings.llm_router_scope,
        llm_per_agent_assist=settings.llm_per_agent_assist,
    )

    api = None
    try:
        from mas.api import MASApiServer
        api = MASApiServer(host=settings.api_host, port=settings.api_port)
    except ImportError as e:
        log.warning("FastAPI/uvicorn 미설치 — REST API 비활성: %s", e)
    except Exception:
        log.exception("REST API 서버 초기화 실패")

    # ═══════════════════════════════════════════════════════
    # 2. 공장 환경 생성
    # ═══════════════════════════════════════════════════════
    factory = Factory()

    # ═══════════════════════════════════════════════════════
    # 3. 6종 AI 에이전트 생성
    # ═══════════════════════════════════════════════════════
    ea = EquipmentAgent()
    qa = QualityAgent()
    sa = SupplyAgent()
    da = DemandAgent()
    ia = InventoryAgent()
    pa = PlanningAgent(llm_client=llm)
    agents = [ea, qa, sa, da, ia, pa]

    for a in agents:
        broker.register(a)
        a.mqtt = mqtt

    # ═══════════════════════════════════════════════════════
    # 4. 런타임 구성
    # ═══════════════════════════════════════════════════════
    runtime = FactoryRuntime(
        factory, broker, agents,
        llm=llm, mqtt=mqtt, api=api,
        decision_router=decision_router,
    )

    if api:
        try:
            api.bind(
                broker=broker,
                llm=llm,
                env=factory,
                agents=agents,
                runtime=runtime,
                decision_router=decision_router,
            )
            api.start()
            time.sleep(1.0)
        except Exception:
            log.exception("API bind/start 실패 — 터미널만 사용")
            api = None

    # ═══════════════════════════════════════════════════════
    # 배너 출력
    # ═══════════════════════════════════════════════════════
    print(f"\n{C.BD}{C.CY}{'═' * 110}{C.RS}")
    print(f"  {C.BD}제조 멀티 AI 에이전트 시스템 v{MAS_VERSION} — 실제 공장 시뮬레이션{C.RS}")
    print(f"  {C.DM}6공정 라인 × 6종 AI 에이전트 × 실시간 센서 × 확률적 이벤트{C.RS}")
    print(f"{C.BD}{C.CY}{'═' * 110}{C.RS}\n")

    # 생산라인 정보
    print(f"  {C.BD}6공정 생산라인{C.RS}")
    print(f"  {'─' * 90}")
    for i, s in enumerate(factory.line):
        arrow = "  →  " if i < 5 else ""
        print(f"    {C.CY}●{C.RS} {C.BD}{s.station_id}{C.RS} {s.name:<12} "
              f"│ 사이클 {s.design_cycle_time:.0f}초 │ "
              f"공구수명 {s.tool.max_life}회 │ "
              f"센서 {len(s.sensors)}종{arrow}")

    # 인프라 상태
    print(f"\n  {C.BD}인프라{C.RS}")
    print(f"  {'─' * 90}")
    print(f"    {C.GR}●{C.RS} 메시지 브로커    At-least-once 보장")

    if mqtt.enabled:
        print(f"    {C.GR}●{C.RS} MQTT 브릿지      센서 데이터 발행")
    else:
        print(f"    {C.YL}○{C.RS} MQTT 브릿지      내부 모드")

    if llm.enabled:
        print(f"    {C.GR}●{C.RS} LLM 엔진         {C.CY}{llm.model}{C.RS}")
    else:
        print(f"    {C.YL}○{C.RS} LLM 엔진         규칙 기반 ({llm.fallback_reason})")

    if api and api.enabled:
        display_host = "localhost" if settings.api_host in ("127.0.0.1", "0.0.0.0") else settings.api_host
        print(f"    {C.GR}●{C.RS} REST API          {C.CY}http://{display_host}:{settings.api_port}{C.RS}")
    else:
        print(f"    {C.YL}○{C.RS} REST API          비활성")

    # 에이전트 정보
    AGENT_DESC = {
        "EA": "예지보전·이상탐지·RUL추정",
        "QA": "SPC·관리도·Cpk·런규칙",
        "SA": "자재흐름·ROP·공급관리",
        "DA": "수요예측·스케줄링·납기관리",
        "IA": "WIP최적화·병목탐지·처리량",
        "PA": "OEE최적화·CNP·전략판단",
    }
    print(f"\n  {C.BD}AI 에이전트 (6종){C.RS}")
    print(f"  {'─' * 90}")
    for a in agents:
        c = logger.AGENT_COLORS.get(a.agent_id, "")
        desc = AGENT_DESC.get(a.agent_id, "")
        print(f"    {c}●{C.RS} {C.BD}{a.agent_id}{C.RS} {a.name:<12} │ {desc}")

    # 초기 상태
    total_demand = sum(o.remaining for o in factory.orders)
    total_mats = sum(m.stock for m in factory.materials.values())
    print(f"\n  {C.BD}초기 상태{C.RS}")
    print(f"  {'─' * 90}")
    print(f"    고객 주문: {C.BD}{len(factory.orders)}건{C.RS} ({total_demand}개)  │  "
          f"자재: {C.BD}{total_mats:,}개{C.RS}  │  "
          f"교대: {C.BD}{factory.shift_mgr.current.shift.value}{C.RS}")
    print()

    # ═══════════════════════════════════════════════════════
    # 5. 런타임 시작
    # ═══════════════════════════════════════════════════════
    runtime.start()

    print(f"  {C.GR}{C.BD}▶ 전체 시스템 가동 시작{C.RS}")
    print(f"  {C.DM}  6공정 센서 데이터 수집 중... (Ctrl+C로 종료){C.RS}\n")

    time.sleep(1.5)
    print_factory_header()

    # ═══════════════════════════════════════════════════════
    # 6. 메인 디스플레이 루프 (메인 스레드)
    # 백그라운드에서 ENV/이벤트/에이전트가 돌아가고, 여기서는 1초마다
    # factory.cycle 이 증가했을 때만 한 줄 로그를 그린다 → 터미널 부하 완화.
    # ═══════════════════════════════════════════════════════
    last_cycle = 0
    summary_interval = 25

    try:
        while True:
            time.sleep(1.0)

            current_cycle = factory.cycle
            if current_cycle <= last_cycle:
                continue
            last_cycle = current_cycle

            logs = runtime.pop_logs()
            print_factory_row(runtime, logs)

            if current_cycle % summary_interval == 0 and current_cycle > 0:
                print_factory_summary(runtime)


    except KeyboardInterrupt:
        print(f"\n\n  {C.YL}{C.BD}▶ 종료 요청 수신...{C.RS}")
        runtime.stop()
        mqtt.stop()
        if api:
            api.stop()

        # ═══════════════════════════════════════════════════
        # 7. 최종 리포트
        # ═══════════════════════════════════════════════════
        kpi = factory.get_kpi_summary()

        print(f"\n{C.BD}{C.CY}{'═' * 110}{C.RS}")
        print(f"  {C.BD}최종 리포트 — {kpi['cycle']}사이클 실행 완료{C.RS}")
        print(f"{C.BD}{C.CY}{'═' * 110}{C.RS}")

        print(f"\n  {C.BD}생산 실적{C.RS}")
        print(f"  {'─' * 60}")
        print(f"    총 생산            {C.BD}{kpi['total_produced']:>8}{C.RS}  개")
        print(f"    완제품 재고        {C.BD}{kpi['fg_stock']:>8}{C.RS}  개")
        print(f"    폐기               {C.BD}{kpi['scrap_count']:>8}{C.RS}  개")
        print(f"    재작업             {C.BD}{kpi['rework_count']:>8}{C.RS}  개")
        print(f"    직행률 (FPY)       {C.BD}{kpi['fpy']:>7.1%}{C.RS}")
        print(f"    전체 OEE           {C.BD}{kpi['avg_oee']:>7.1%}{C.RS}")
        print(f"    납기 준수율        {C.BD}{kpi['on_time_delivery']:>7.1%}{C.RS}")

        print(f"\n  {C.BD}에너지{C.RS}")
        print(f"  {'─' * 60}")
        print(f"    총 에너지          {C.BD}{kpi['total_energy_kwh']:>8.0f}{C.RS}  kWh")
        print(f"    단위 에너지        {C.BD}{kpi['energy_per_unit']:>8.3f}{C.RS}  kWh/개")

        print(f"\n  {C.BD}공정별 OEE{C.RS}")
        print(f"  {'─' * 60}")
        for sid, oee_data in kpi.get("station_oee", {}).items():
            name = STATION_SHORT.get(sid, sid)
            oee_val = oee_data["oee"]
            avail = oee_data["availability"]
            perf = oee_data["performance"]
            qual = oee_data["quality"]
            oc = C.GR if oee_val >= 0.85 else (C.YL if oee_val >= 0.65 else C.RD)
            bn_mark = " ← 병목" if sid == kpi.get("bottleneck") else ""
            print(f"    {name:<8} {oc}{oee_val:>6.1%}{C.RS}  "
                  f"(가용 {avail:.0%} × 성능 {perf:.0%} × 품질 {qual:.0%})"
                  f"{C.RD}{bn_mark}{C.RS}")

        bm = broker.metrics
        print(f"\n  {C.BD}통신{C.RS}")
        print(f"  {'─' * 60}")
        print(f"    브로커 메시지      {C.BD}{bm.total_published:>8}{C.RS}  건")
        print(f"    평균 지연          {C.BD}{bm.avg_latency_ms:>7.2f}{C.RS}  ms")
        print(f"    CNP 협상           {C.BD}{runtime.cnp_count:>8}{C.RS}  회")
        print(f"    총 이벤트          {C.BD}{runtime.total_events:>8}{C.RS}  건")
        print(f"    교대 변경          {C.BD}{kpi['shift_changes']:>8}{C.RS}  회")

        print(f"\n  {C.BD}에이전트 최종 상태{C.RS}")
        print(f"  {'─' * 60}")
        for a in agents:
            c = logger.AGENT_COLORS.get(a.agent_id, "")
            last = a.reasoning_log[-1] if a.reasoning_log else "—"
            print(f"    {c}{C.BD}[{a.name}]{C.RS} {last[:70]}")

        print(f"\n{C.BD}{C.CY}{'═' * 110}{C.RS}")
        print(f"  {C.GR}{C.BD}[정상] 시스템 정상 종료{C.RS}\n")


if __name__ == "__main__":
    main()
