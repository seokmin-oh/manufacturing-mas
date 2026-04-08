"""
시나리오 러너 — YAML 시나리오를 로드하여 지정된 사이클만큼 자동 실행 후 결과를 JSON으로 저장.

사용법:
  python run_scenario.py --scenario scenarios/normal.yaml --cycles 100
  python run_scenario.py --scenario scenarios/equipment_failure.yaml
  python run_scenario.py --list
"""

import sys
import os
import json
import time
import argparse
from datetime import datetime
from pathlib import Path

os.environ["PYTHONUNBUFFERED"] = "1"
sys.stdout.reconfigure(encoding="utf-8")

from mas.scenario import ScenarioConfig, list_scenarios
from mas.domain.environment import ManufacturingEnvironment
from mas.domain.production import ProductionOrder
from mas.domain.demand import CustomerOrder, OrderPriority
from mas.messaging.broker import MessageBroker
from mas.messaging.mqtt_bridge import MQTTBridge
from mas.tools.ai_tools import ToolRegistry
from mas.intelligence.decision_router import HybridDecisionRouter
from mas.intelligence.llm import LLMClient
from mas.core.config import get_settings
from mas.agents.equipment_agent import EquipmentAgent
from mas.agents.quality_agent import QualityAgent
from mas.agents.supply_agent import SupplyAgent
from mas.agents.demand_agent import DemandAgent
from mas.agents.inventory_agent import InventoryAgent
from mas.agents.planning_agent import PlanningAgent
from mas.runtime import AgentRuntime
from mas.core import logger
from mas.core.logger import C


def print_scenario_list():
    scenarios = list_scenarios("scenarios")
    if not scenarios:
        print("  시나리오 파일을 찾을 수 없습니다. scenarios/ 디렉터리를 확인하세요.")
        return
    print(f"\n{C.BD}{C.CY}{'═' * 78}{C.RS}")
    print(f"  {C.BD}사용 가능한 시나리오 ({len(scenarios)}종){C.RS}")
    print(f"{C.BD}{C.CY}{'═' * 78}{C.RS}")
    for i, s in enumerate(scenarios, 1):
        print(f"\n  {C.BD}{C.CY}{i}.{C.RS} {C.BD}{s['name']}{C.RS}")
        print(f"     파일: {C.DM}{s['file']}{C.RS}")
        if s['description']:
            print(f"     설명: {s['description'][:70]}")
    print(f"\n{C.BD}{C.CY}{'═' * 78}{C.RS}")
    print(f"  {C.DM}사용법: python run_scenario.py -s scenarios/<파일명> -c <사이클수>{C.RS}\n")


def run_scenario(scenario_path: str, max_cycles: int, output_dir: str = "results"):
    sc = ScenarioConfig.load(scenario_path)

    if max_cycles > 0:
        sc.max_cycles = max_cycles

    if sc.max_cycles <= 0:
        sc.max_cycles = 100

    print(f"\n{C.BD}{C.CY}{'═' * 80}{C.RS}")
    print(f"  {C.BD}시나리오 실행: {C.CY}{sc.name}{C.RS}")
    print(f"  {C.DM}{sc.description}{C.RS}")
    print(f"  {C.BD}총 {sc.max_cycles}사이클 실행 예정{C.RS}")
    print(f"{C.BD}{C.CY}{'═' * 80}{C.RS}\n")

    settings = get_settings()
    broker = MessageBroker()
    mqtt = MQTTBridge()
    tool_registry = ToolRegistry()
    llm = LLMClient(
        model=settings.llm_model,
        domain_model=settings.llm_domain_model or None,
    )
    decision_router = HybridDecisionRouter(
        llm_client=llm,
        llm_router_scope=settings.llm_router_scope,
        llm_per_agent_assist=settings.llm_per_agent_assist,
    )

    env = ManufacturingEnvironment(scenario=sc)

    order = ProductionOrder(
        order_id="PO-2026-SCENARIO-001", part_number="BRK-PAD-2026A",
        part_name="브레이크 패드 브래킷", target_qty=9999,
        material_spec="SPCC 강판 2.3t x 850mm",
        material_lot="LOT-MTL-SCENARIO-01",
        customer="시나리오 테스트", due_date="연속생산",
    )
    env.load_order(order)

    for io in sc.initial_orders:
        pri = OrderPriority.URGENT if io.priority == "URGENT" else OrderPriority.NORMAL
        env.demand.add_order(CustomerOrder(io.order_id, io.customer, io.quantity, io.due_date, pri))

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

    wh = env.warehouse
    wh.demand_std = sc.demand_std
    wh.leadtime_mean = sc.leadtime_mean
    wh.leadtime_std = sc.leadtime_std
    wh.avg_demand_per_cycle = sc.avg_demand_per_cycle
    wh.service_level_target = sc.service_level_target
    wh.recalculate_safety_stock()

    initial_ss = wh.safety_stock
    initial_stock = wh.stock

    runtime = AgentRuntime(
        env, broker, agents, llm=llm, mqtt=mqtt,
        tool_registry=tool_registry, decision_router=decision_router,
        scenario=sc,
    )

    logger.quiet = True

    print(f"  {C.BD}초기 상태{C.RS}")
    print(f"     완제품 재고: {C.BD}{initial_stock}개{C.RS}  │  안전재고: {C.BD}{initial_ss}개{C.RS}  │  목표 납기율: {C.BD}{sc.service_level_target:.0%}{C.RS}")
    print(f"     고객 주문: {C.BD}{env.demand.total_demand}개{C.RS} ({len(env.demand.open_orders)}건)")
    print()
    print(f"  {C.BD}센서 설정{C.RS}")
    vib_cfg = sc.press_sensors['vibration']
    print(f"     진동 기준값: {C.BD}{vib_cfg.baseline}{C.RS}mm/s  │  노이즈: {C.BD}{vib_cfg.noise_std}{C.RS}  │  열화속도: {C.BD}{vib_cfg.drift_rate}{C.RS}/사이클")
    print()
    print(f"  {C.BD}이벤트 확률{C.RS}")
    print(f"     진동스파이크: {C.BD}{sc.events.vibration_spike:.0%}{C.RS}  │  "
          f"신규주문: {C.BD}{sc.events.new_order:.0%}{C.RS}  │  "
          f"긴급비율: {C.BD}{sc.events.urgent_order_ratio:.0%}{C.RS}")
    print()

    runtime.start()

    progress_interval = max(1, sc.max_cycles // 10)
    last_printed = 0

    try:
        while runtime._running:
            time.sleep(0.5)
            current = runtime.total_cycles

            if current >= sc.max_cycles:
                break

            if current > last_printed and current % progress_interval == 0:
                last_printed = current
                pct = current / sc.max_cycles * 100
                sl = wh.service_level
                stock = wh.stock
                ss = wh.safety_stock
                bar_len = 20
                filled = int(pct / 100 * bar_len)
                bar = "█" * filled + "░" * (bar_len - filled)

                stock_icon = "+" if stock >= ss * 1.2 else ("!" if stock >= ss else "x")
                sl_icon = "+" if sl >= 0.95 else ("!" if sl >= 0.90 else "x")

                print(f"  {C.CY}{bar}{C.RS} {pct:5.1f}% │ "
                      f"{stock_icon} 재고 {C.BD}{stock:4d}{C.RS}/{ss}  "
                      f"{sl_icon} 납기 {C.BD}{sl:.1%}{C.RS}  │  "
                      f"협상 {runtime.cnp_count}회  이벤트 {runtime.total_events}건")

    except KeyboardInterrupt:
        print("\n  사용자 중단")

    runtime.stop()
    mqtt.stop()

    results = runtime.get_results()
    results["scenario"] = sc.to_dict()
    results["initial_state"] = {
        "stock": initial_stock,
        "safety_stock": initial_ss,
    }
    results["timestamp"] = datetime.now().isoformat()

    Path(output_dir).mkdir(exist_ok=True)
    scenario_name = Path(scenario_path).stem
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_file = Path(output_dir) / f"{scenario_name}_{ts}.json"

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)

    wh_r = results["warehouse"]
    sl_val = wh_r['service_level']
    sl_icon = "+" if sl_val >= 0.95 else ("!" if sl_val >= 0.90 else "x")
    stock_icon = "+" if wh_r['final_stock'] >= wh_r['safety_stock'] else "x"
    breach_icon = "+" if wh_r['ss_breach_count'] == 0 else "!"

    print(f"\n{C.BD}{C.CY}{'═' * 80}{C.RS}")
    print(f"  {C.BD}실행 결과: {C.CY}{sc.name}{C.RS}")
    print(f"{C.BD}{C.CY}{'═' * 80}{C.RS}")

    print(f"\n  {C.BD}시스템 요약{C.RS}")
    print(f"  {'─' * 50}")
    print(f"     총 생산 사이클       {C.BD}{results['total_cycles']:>8}{C.RS}  사이클")
    print(f"     발생 이벤트          {C.BD}{results['total_events']:>8}{C.RS}  건")
    print(f"     CNP 협상 실행        {C.BD}{results['cnp_count']:>8}{C.RS}  회")
    print(f"     실행 시간            {C.BD}{results['uptime_sec']:>8}{C.RS}  초")

    print(f"\n  {C.BD}재고 & 납기{C.RS}")
    print(f"  {'─' * 50}")
    print(f"  {stock_icon} 최종 재고            {C.BD}{wh_r['final_stock']:>8}{C.RS}  개")
    print(f"     안전재고(SS)         {C.BD}{wh_r['safety_stock']:>8}{C.RS}  개")
    print(f"  {sl_icon} 납기 달성률(SL)      {C.BD}{sl_val:>7.1%}{C.RS}")
    print(f"     총 출하              {C.BD}{wh_r['total_shipped']:>8}{C.RS}  / {wh_r['total_requested']}개 요청")
    print(f"  {breach_icon} 안전재고 위반 횟수   {C.BD}{wh_r['ss_breach_count']:>8}{C.RS}  회")

    print(f"\n  {C.BD}통신 & 인프라{C.RS}")
    print(f"  {'─' * 50}")
    print(f"     브로커 메시지         {C.BD}{results['broker']['total_published']:>8}{C.RS}  건")
    print(f"     평균 메시지 지연      {C.BD}{results['broker']['avg_latency_ms']:>7.2f}{C.RS}  ms")

    tr = results.get("tools", {})
    if tr:
        print(f"\n  {C.BD}AI 도구 & 판단{C.RS}")
        print(f"  {'─' * 50}")
        print(f"     AI 도구 호출         {C.BD}{tr.get('total_calls', 0):>8}{C.RS}  회")

    dr = results.get("decision_router", {})
    if dr:
        rule = dr.get('rule_decisions', 0)
        llm_d = dr.get('llm_decisions', 0)
        total_d = rule + llm_d
        rule_pct = f"({rule / total_d * 100:.0f}%)" if total_d > 0 else ""
        llm_pct = f"({llm_d / total_d * 100:.0f}%)" if total_d > 0 else ""
        print(f"     규칙 기반 판단       {C.BD}{rule:>8}{C.RS}  회  {C.DM}{rule_pct}{C.RS}")
        print(f"     LLM 기반 판단        {C.BD}{llm_d:>8}{C.RS}  회  {C.DM}{llm_pct}{C.RS}")

    print(f"\n  {C.BD}{C.GR}결과 저장: {C.RS}{out_file}")
    print(f"{C.BD}{C.CY}{'═' * 80}{C.RS}\n")

    return str(out_file)


def main():
    parser = argparse.ArgumentParser(
        description="Multi-Agent 시나리오 러너",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""예시:
  python run_scenario.py --list
  python run_scenario.py --scenario scenarios/normal.yaml
  python run_scenario.py --scenario scenarios/equipment_failure.yaml --cycles 200
  python run_scenario.py --scenario scenarios/compound_crisis.yaml --cycles 50
""",
    )
    parser.add_argument("--scenario", "-s", type=str, help="시나리오 YAML 파일 경로")
    parser.add_argument("--cycles", "-c", type=int, default=0, help="실행 사이클 수 (0=YAML 설정값 사용)")
    parser.add_argument("--output", "-o", type=str, default="results", help="결과 저장 디렉터리")
    parser.add_argument("--list", "-l", action="store_true", help="사용 가능한 시나리오 목록")

    args = parser.parse_args()

    if args.list:
        print_scenario_list()
        return

    if not args.scenario:
        parser.print_help()
        print("\n  오류: --scenario 또는 --list 중 하나를 지정하세요.")
        sys.exit(1)

    if not Path(args.scenario).exists():
        print(f"\n  오류: 시나리오 파일을 찾을 수 없습니다: {args.scenario}")
        sys.exit(1)

    run_scenario(args.scenario, args.cycles, args.output)


if __name__ == "__main__":
    main()
