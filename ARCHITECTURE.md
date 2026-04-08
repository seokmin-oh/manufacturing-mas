# Manufacturing Multi AI Agent System — 전체 아키텍처 문서

> **버전**: v5 — Scenario Testing Framework  
> **목적**: 안전재고 최소화를 위한 생산·품질·설비 통합 Multi AI Agent 오케스트레이션  
> **규모**: 38개 파일, ~10,000 라인

---

## 1. 시스템 개요

자동차 부품(브레이크 패드 브래킷) 생산 라인을 시뮬레이션하며,
6개의 자율 AI 에이전트가 **실시간으로** 설비 상태, 품질 데이터, 수요 변동, 재고 수준을 감시하고
**Contract Net Protocol(CNP)** 기반 협상을 통해 안전재고(SS)를 동적으로 최적화한다.

**YAML 기반 시나리오 시스템**으로 코드 수정 없이 6종의 제조 환경(정상/설비고장/수요폭증/품질위기/자재부족/복합위기)을 시뮬레이션하고 결과를 비교할 수 있다.

```
┌──────────────────────────────────────────────────────────────────────┐
│                    Manufacturing Line (Simulation)                    │
│   [프레스] ──→ [용접] ──→ [비전검사] ──→ [완제품 창고] ──→ [출하]      │
│       ↓           ↓           ↓              ↓             ↓         │
│    센서 4종     센서 4종     치수 3종       재고/SS        서비스레벨   │
└──────┬──────────┬──────────┬──────────────┬──────────────┬───────────┘
       │          │          │              │              │
    ┌──▼──┐   ┌──▼──┐   ┌──▼──┐       ┌──▼──┐       ┌──▼──┐
    │ EA  │   │ QA  │   │ SA  │       │ DA  │       │ IA  │
    │설비 │   │품질 │   │공급 │       │수요 │       │재고 │
    └──┬──┘   └──┬──┘   └──┬──┘       └──┬──┘       └──┬──┘
       │         │         │             │             │
       └────────►├─────────┤◄────────────┤◄────────────┘
                 │   ALERT/PROPOSE       │
                 ▼                       │
           ┌─────────┐                   │
           │   PA    │◄──────────────────┘
           │계획/조율│
           └────┬────┘
                │ CNP (CFP → PROPOSE → ACCEPT)
                ▼
         [통합 전략 수립]
         ├─ Rule-based (< 1ms)
         └─ LLM GPT-4o (~ 1-3s)
```

---

## 2. 디렉터리 구조

```
Multi-Agent/
├── main.py                          # 진입점: 인프라 조립 + 대화형 실행 루프 + 대시보드
├── run_scenario.py                  # CLI 시나리오 러너 (자동 실행 + JSON 결과 저장)
├── compare_results.py               # 시나리오 결과 비교 유틸리티
├── requirements.txt                 # 의존성: openai, fastapi, uvicorn, paho-mqtt, pyyaml
│
├── scenarios/                       # YAML 시나리오 파일 6종
│   ├── normal.yaml                  # 정상 운영 (baseline)
│   ├── equipment_failure.yaml       # 설비 고장 (드리프트 3배, 스파이크 30%)
│   ├── demand_surge.yaml            # 수요 폭증 (긴급 60%, 대량 배치)
│   ├── quality_crisis.yaml          # 품질 위기 (노이즈 3배, 용접 편차 대)
│   ├── supply_shortage.yaml         # 자재 부족 (재고 1/3, 보충 느림)
│   └── compound_crisis.yaml         # 복합 위기 (위 4개 동시 발생)
│
├── results/                         # 시나리오 실행 결과 JSON (자동 생성)
│   ├── normal_20260403_143414.json
│   └── equipment_failure_20260403_143552.json
│
├── ARCHITECTURE.md                  # 이 문서 (기술 아키텍처)
├── OVERVIEW.md                      # 비전문가용 쉬운 설명
│
└── mas/                             # 코어 패키지 (레이어별 서브패키지 + 루트 shim)
    ├── __init__.py                  # 공개 API: Factory, 에이전트, FactoryRuntime
    │
    ├── core/                        # 설정·로깅·`manufacturing_ids`(표준 agent/station ID)
    ├── domain/                      # Factory, 기계·재고·수요, `manufacturing_context`, `business_events`, `agent_snapshot`
    ├── messaging/                   # `message`, `broker`(MessageBus 호환), `mqtt_bridge`
    ├── agents/                      # `base_agent`, 6종 + `equipment_sub`, `planning_sub`, `qa_sub`
    ├── intelligence/              # `llm`(감사 로그), `decision_router`, `operational_decision_card`, 솔버·스냅샷 보강
    ├── protocol/                  # `cnp_session`, `agent_protocol`, `sra_langgraph`, `cnp_comparison`, `contract_net`
    ├── adapters/                  # 외부 시스템 연동용 Protocol (`base` 등)
    ├── runtime/                   # `factory_runtime`, `scenario_runtime`
    ├── scenario/                  # `loader` (YAML → ScenarioConfig)
    ├── tools/                     # `ai_tools`, `mock_models`
    ├── api/                       # `server` (MASApiServer, 대시보드)
    │
    └── (루트 *.py)                # 하위 호환: `from mas.config` 등 → 서브패키지 재export
```

---

## 3. 계층별 상세 설명

### 3.1 인프라 계층

#### Message Broker (`broker.py`)
```
에이전트 A ──publish──→ [Topic Queue] ──deliver──→ 에이전트 B
                              │
                         at-least-once
                         DLQ (재시도 실패)
                         ACK 추적
```

| 항목 | 설명 |
|------|------|
| 토픽 수 | 9개 (equipment, quality, supply, demand, inventory, planning, cnp, alerts, broadcast) |
| 큐 깊이 | 에이전트당 128 메시지 |
| 전달 보장 | At-least-once (ACK + 지수 백오프 재시도) |
| DLQ | 최대 재시도 초과 시 Dead Letter Queue |
| 메트릭 | 발행/전달/ACK/지연 시간/처리량 추적 |

Intent ↔ Topic 자동 라우팅:
- `CFP`, `PROPOSE`, `ACCEPT_PROPOSAL` → `cnp`
- `ALERT` → `alerts`
- `DEMAND_CHANGE` → `demand`
- `STOCK_ALERT` → `inventory`
- `TOOL_CALL`, `TOOL_RESULT` → `broadcast`

#### MQTT Bridge (`mqtt_bridge.py`)
```
센서(PLC) ──→ MQTT Broker(Mosquitto:1883) ──→ 에이전트 콜백
         QoS 0 (센서)
         QoS 1 (알람/재고)
         QoS 2 (CNP)
```

토픽 구조:
```
factory/line3/press-01/vibration          EA 구독
factory/line3/press-01/oil_temp           EA 구독
factory/line3/press-01/hydraulic_pressure
factory/line3/press-01/motor_current
factory/line3/weld-01/weld_current        QA 구독
factory/line3/weld-01/weld_voltage        QA 구독
factory/line3/quality/inspection          QA 구독
factory/line3/inventory/snapshot          IA 구독
mas/agents/+/status                       PA 구독
mas/cnp/#                                 PA 구독
mas/alerts/#                              PA 구독
mas/tools/#                               모니터링
```

> **Fallback**: Mosquitto 미기동 시 자동으로 in-memory 로컬 Pub/Sub로 전환.

#### LLM Client (`llm.py`)
```
PlanningAgent ──→ LLMClient ──→ OpenAI GPT-4o-mini
                       │
                  JSON mode 강제
                  시스템 프롬프트 (제조 도메인 지식)
                  토큰 사용량 추적
                  API 키 미설정 → Rule-based 폴백
```

2개의 API:
1. **`evaluate_proposals`**: 5개 에이전트 제안 → 통합 전략 JSON
2. **`analyze_situation`**: 실시간 센서 + 알람 → CNP 개시 여부 판단

#### REST API & 대시보드 (`api.py`)
```
http://localhost:8787
├── GET  /                    실시간 대시보드 (HTML/JS)
├── GET  /api/status          시스템 종합 상태
├── GET  /api/agents          에이전트 상태 상세
├── GET  /api/messages        메시지 로그 (최근 100건)
├── GET  /api/broker          브로커 메트릭
├── GET  /api/llm             LLM 사용 현황
├── GET  /api/inventory       재고/SS/서비스레벨
├── GET  /api/tools           AI Tool Registry 현황
├── POST /api/tools/{name}/invoke  도구 외부 호출
├── GET  /api/decision-router 판단 라우터 통계
├── GET  /api/executors       Agentic Loop 통계
└── GET  /api/stream          SSE 실시간 이벤트
```

---

### 3.2 에이전틱 계층

#### AI Tool Registry (`ai_tools.py`)

에이전트가 `tool_registry.call("tool_name", ...)` 형태로 호출하는 10개의 AI 도구:

| # | 도구명 | 카테고리 | 설명 | 주 사용 에이전트 |
|---|--------|----------|------|:---:|
| 1 | `vision_inspection` | inspection | 비전 카메라 기반 치수 측정 | QA |
| 2 | `defect_prediction` | prediction | 센서 데이터 기반 불량 확률 예측 | QA |
| 3 | `predictive_maintenance` | prediction | 설비 진동/추세 기반 정비 시기 예측 | EA |
| 4 | `demand_forecast` | prediction | 과거 수요 패턴 기반 수요 예측 | DA |
| 5 | `capacity_estimation` | prediction | 설비 상태 기반 생산능력 계수 | EA |
| 6 | `yield_prediction` | prediction | 품질 데이터 기반 수율 계수 | QA |
| 7 | `spc_analysis` | analysis | SPC 공정능력지수(Cpk) 계산 | QA |
| 8 | `leadtime_estimation` | optimization | 실효 리드타임 및 변동성 계산 | IA |
| 9 | `oee_calculator` | analysis | 종합설비효율(OEE) 산출 | PA |
| 10 | `safety_stock_calc` | optimization | 안전재고 공식 계산 | IA |

각 도구는 호출 횟수, 평균 지연, 에러 수를 자동 추적하며
REST API를 통해 외부에서도 호출 가능하다.

#### Agentic Loop (`agentic_loop.py`)

각 에이전트가 매 주기마다 실행하는 자율 루프:

```
┌──────────────────────────────────────────────────────────────┐
│                     AgentExecutor.execute_cycle()             │
├──────────────┬──────────────────┬────────────────────────────┤
│    SENSE     │      THINK       │            ACT             │
├──────────────┼──────────────────┼────────────────────────────┤
│ • env 스냅샷 │ • Decision Router│ • TOOL_CALL 실행           │
│ • inbox 메시지│   확인 (Rule/LLM)│   → registry.call(name,kw)│
│ • MQTT 수신  │ • agent.reason() │   → MQTT 결과 발행         │
│              │ • _select_tools()│ • SEND_MESSAGE             │
│              │   도구 자동 선택 │ • UPDATE_STATE             │
│              │                  │ • LOG                      │
└──────────────┴──────────────────┴────────────────────────────┘
```

에이전트별 도구 자동 선택 로직:
- **EA**: 진동 > 3.0 → `predictive_maintenance` + `capacity_estimation`
- **QA**: 검사 5개 이상 → `defect_prediction`
- **DA**: 수요 이력 5개 이상 → `demand_forecast`
- **IA**: 재고 < SS × 1.5 → `safety_stock_calc`

#### Hybrid Decision Router (`decision_router.py`)

```
┌────────────────────────────────────────────────────────────────┐
│                    HybridDecisionRouter                         │
├─────────────────────────────┬──────────────────────────────────┤
│    Hard-coded Rules (< 1ms) │        LLM GPT (1-3s)           │
├─────────────────────────────┼──────────────────────────────────┤
│ • 진동 ≥ 5.5mm/s → 비상정지│ • 2개+ 에이전트 경보 동시 발생  │
│ • 유온 ≥ 75°C → 라인 정지  │ • 공정 간 이해관계 충돌 조정    │
│ • 진동 ≥ 4.5mm/s → 즉시감속│ • 예상치 못한 알람 원인 분석    │
│ • 자재 버퍼 < 1h → 긴급보충│ • 최적 감속률 결정              │
│ • Cpk < 0.67 → SPC 위험    │ • 수요-공급-품질 트레이드오프   │
│ • SL < 90% → 서비스레벨위험│ • 안전재고 동적 최적화 판단     │
└─────────────────────────────┴──────────────────────────────────┘
```

라우팅 우선순위:
1. **안전 인터록** (모든 에이전트) → 무조건 Rule
2. **임계값 규칙** (EA, SA) → Rule
3. **복합 판단** (PA만, 2개+ alert) → LLM
4. **LLM 실패** → Rule 폴백

---

### 3.3 시나리오 계층 (신규)

#### Scenario Config (`scenario.py`)

YAML 파일에서 시뮬레이션의 모든 파라미터를 로드하여 코드 수정 없이 다양한 제조 환경을 재현한다.

```
scenarios/normal.yaml
        │
        ▼
  ScenarioConfig.load()
        │
        ├── press_sensors: {vibration: {baseline, noise_std, drift_rate}, ...}
        ├── weld_sensors:  {weld_current: {baseline, noise_std, drift_rate}, ...}
        ├── warehouse:     {stock, safety_stock, service_level_target, ...}
        ├── materials:     {steel_stock, weld_wire, shield_gas, restock_threshold}
        ├── demand:        {initial_orders, shipment_interval, order_quantities}
        ├── events:        {new_order, vibration_spike, urgent_order_ratio, ...}
        ├── runtime:       {takt_sec, agent_intervals, event_interval_range}
        └── execution:     {max_cycles}
              │
              ▼
    ┌─────────────────────────────────────────────┐
    │ ManufacturingEnvironment(scenario=sc)        │ ← 센서/창고/자재/출하 파라미터 주입
    │ PressMachine(sensor_overrides=sc.press)      │ ← 센서 기준값/노이즈/드리프트 오버라이드
    │ WeldingMachine(sensor_overrides=sc.weld)     │ ← 용접 센서 오버라이드
    │ AgentRuntime(scenario=sc)                    │ ← 택트/에이전트주기/이벤트확률/max_cycles
    └─────────────────────────────────────────────┘
```

설정 가능 항목:

| 카테고리 | 파라미터 | 적용 대상 |
|----------|----------|-----------|
| 센서 | 기준값, 노이즈 σ, 드리프트율 (프레스 4종, 용접 4종) | `machines.py` SensorSimulator |
| 창고 | 초기 재고, 안전재고, SL 목표, 수요 σ, 리드타임 | `inventory.py` FinishedGoodsWarehouse |
| 자재 | 강판/와이어/가스 초기 재고, 보충 임계값 | `environment.py` materials |
| 수요 | 초기 주문 목록, 주문 수량 분포, 출하 주기/배치 | `environment.py` demand |
| 이벤트 | 6종 이벤트 발생 확률, 스파이크 크기, 긴급 주문 비율 | `runtime.py` _event_loop |
| 런타임 | 택트타임, 에이전트 6종 주기, 이벤트 간격, 요약 주기 | `runtime.py` AgentRuntime |
| 실행 | 최대 사이클 수 (자동 종료) | `runtime.py` _env_loop |

#### 시나리오 6종

| 파일 | 시나리오 | 핵심 변경 | 테스트 대상 |
|------|----------|-----------|-------------|
| `normal.yaml` | 정상 운영 | 기본값 (baseline) | 비교 기준선 |
| `equipment_failure.yaml` | 설비 고장 | drift ×3, spike 30%, noise ×2 | EA 예지보전 |
| `demand_surge.yaml` | 수요 폭증 | 긴급 60%, 배치 200~300, takt 2.0s | IA·PA 대응력 |
| `quality_crisis.yaml` | 품질 위기 | 센서 noise ×3, 용접편차 대 | QA SPC·검사전환 |
| `supply_shortage.yaml` | 자재 부족 | 재고 1/3, 보충 5%, AGV 변경 빈번 | SA 자재관리 |
| `compound_crisis.yaml` | 복합 위기 | 위 4개 동시 발생 | 전체 MAS 종합 |

#### 시나리오 러너 (`run_scenario.py`)

```bash
# 시나리오 목록
python run_scenario.py --list

# 실행 (지정 사이클 후 자동 종료 → JSON 저장)
python run_scenario.py --scenario scenarios/normal.yaml --cycles 100
python run_scenario.py --scenario scenarios/equipment_failure.yaml --cycles 100

# 결과 비교
python compare_results.py results/normal_*.json results/equipment_failure_*.json
```

실행 흐름:
```
YAML 로드 → ScenarioConfig → Environment+Runtime 구성 → 에이전트 생성
  → 자동 실행 (진행률 출력) → max_cycles 도달 → 종료
  → KPI 수집 (get_results) → JSON 저장 (results/)
  → 결과 테이블 출력
```

수집 KPI:
- 총 사이클, 이벤트, CNP 실행 횟수
- 최종 재고, 안전재고, 서비스레벨, SS 위반 횟수
- 브로커 메시지 수, 평균 지연, DLQ
- AI 도구 호출 수, Rule/LLM 판단 비율

---

### 3.4 에이전트 계층

#### 기반 클래스 (`base_agent.py`)

```python
class BaseAgent(ABC):
    # 스레드 안전 (threading.Lock)
    inbox:  List[AgentMessage]     # 수신 메시지 큐
    outbox: List[AgentMessage]     # 발신 메시지 이력
    internal_state: Dict[str, Any] # 에이전트 내부 상태
    reasoning_log: List[str]       # 추론 이력

    @abstractmethod sense(env_data) → dict      # 환경 감지
    @abstractmethod reason(sensed) → dict       # 판단
    @abstractmethod act(decision) → dict        # 행동
    @abstractmethod handle_cfp(msg, data) → msg # CNP 제안
    @abstractmethod execute_accepted_proposal()  # 지시 실행
```

#### 6개 에이전트 상세

| ID | 이름 | 주기 | Sense | Reason | Act |
|----|------|:----:|-------|--------|-----|
| **EA** | Equipment Agent | 2s | 진동·유온·추세 분석, MA/slope 계산, 가용능력 예측 | 3단계 알람 (L1-L3), 경고 잔존 사이클 추정 | PA에 `ALERT` 전송, PLC 감속 명령, 모니터링 주기 변경 |
| **QA** | Quality Agent | 3s | 제품 치수 측정(두께/버/평탄도), SPC Cpk 계산, 수율 예측 | Cpk < 1.0 시 경보, 불량 예측 확률 분석 | PA에 `ALERT` 전송, 전수검사 모드 전환 |
| **SA** | Supply Agent | 5s | 자재 재고(강판/와이어/가스), AGV 상태, 버퍼 시간 계산 | 자재 버퍼 < 3h 시 보충 요청 | PA에 `ALERT` 전송, AGV 디스패치 |
| **DA** | Demand Agent | 4s | 수요 이력, 예측 정확도, 수요 표준편차 | 정확도 < 75% 시 재보정, 변동성 높을 시 경고 | 수요 예측 재보정, PA에 `DEMAND_CHANGE` 전송 |
| **IA** | Inventory Agent | 3s | 완제품 재고, SS, 서비스레벨, SS 위반 여부 | stock < SS 시 PA에 알림 | PA에 `STOCK_ALERT` 전송, SS 동적 재계산 |
| **PA** | Planning Agent | 2s | 수신함의 ALERT 메시지 수집 | 2개+ alert → CNP 개시 결정 (LLM/Rule 하이브리드) | CNP 실행: CFP 브로드캐스트 → 제안 수집 → 전략 수립 → 지시 전파 |

> 모든 에이전트 주기는 시나리오 YAML로 오버라이드 가능.

---

### 3.5 시뮬레이션 계층

#### 제조 환경 (`environment.py`)

**생산 라인**:
```
프레스(PRESS-01) → 용접(WELD-01) → 비전검사 → 완제품 창고 → 출하
```

`ManufacturingEnvironment(scenario=ScenarioConfig)` — 시나리오 설정이 주어지면 해당 파라미터로 초기화:

| 항목 | 기본값 | 시나리오 오버라이드 |
|------|--------|---------------------|
| 창고 재고 | 120 | `warehouse.stock` |
| 안전재고 | 45 | `warehouse.safety_stock` |
| 강판 재고 | 850 | `materials.steel_stock` |
| 출하 주기 | 2사이클 | `demand.shipment_interval` |
| 출하 배치 | 3개 | `demand.shipment_batch_size` |

#### 센서 시뮬레이션 (`machines.py`)

각 센서는 `SensorSimulator`로 구현되며, **시나리오에서 `sensor_overrides`로 파라미터를 주입**할 수 있다:
```
value = baseline + accumulated_drift + gaussian_noise
              │              │              │
         초기 설정값   베어링 마모 등    랜덤 산포
        (YAML 설정)  (YAML drift_rate)  (YAML noise_std)
```

**프레스 센서 4종 (기본값)**:

| 센서 | 기준값 | 노이즈 σ | 드리프트 | 정상 | 경고 | 위험 |
|------|:------:|:--------:|:--------:|:----:|:----:|:----:|
| 진동 (mm/s) | 1.8 | 0.15 | 0.10 | < 3.5 | 3.5–4.5 | ≥ 4.5 |
| 유온 (°C) | 42.0 | 0.5 | 0.03 | < 65 | 65–75 | ≥ 75 |
| 유압 (bar) | 180 | 2.0 | -0.08 | 170–190 | 160–200 | 150–210 |
| 모터전류 (A) | 45 | 1.0 | 0.02 | 40–55 | 35–60 | 30–70 |

**시나리오별 센서 변화 예시**:

| 시나리오 | 진동 기준값 | 노이즈 σ | 드리프트 |
|----------|:----------:|:--------:|:--------:|
| 정상 운영 | 1.80 | 0.15 | 0.10 |
| 설비 고장 | 2.50 | 0.30 | **0.30** |
| 품질 위기 | 2.20 | **0.40** | 0.12 |
| 복합 위기 | **2.80** | **0.45** | **0.35** |

#### 안전재고 공식 (`inventory.py`)

```
SS = z × √(LT × σ_D² + d_avg² × σ_LT²)
```

| 파라미터 | 의미 | 갱신 주체 | 시나리오 설정 |
|----------|------|-----------|--------------|
| z | 서비스레벨 z-score (95% → 1.645) | 고정 | `service_level_target` |
| LT | 평균 리드타임 (사이클) | EA → IA | `leadtime_mean` |
| σ_D | 수요 표준편차 | DA → IA | `demand_std` |
| d_avg | 평균 사이클 수요 | DA → IA | `avg_demand_per_cycle` |
| σ_LT | 리드타임 표준편차 | EA → IA | `leadtime_std` |

CNP 완료 시 `IA.recalculate_ss()`가 호출되어 SS를 동적 하향 조정.

---

## 4. 전체 데이터 흐름

### 4.1 정상 운영 흐름 (매 사이클)

```
[ENV 스레드: takt_sec 주기 (기본 2.5초, 시나리오로 조정 가능)]
    │
    ├─① environment.run_cycle()
    │   ├─ 프레스 stroke → 센서 4종 생성 (진동, 유온, 유압, 전류)
    │   ├─ 용접 실행 → 센서 4종 생성 (전류, 전압, 와이어, 가스)
    │   ├─ 비전 검사 → 치수 3종 (두께, 버높이, 평탄도) → 양품/보류/불합격
    │   ├─ 양품 → 창고 입고
    │   ├─ 출하 처리 → 서비스레벨 갱신
    │   └─ 자재 소모 차감
    │
    ├─② MQTT로 센서 데이터 발행
    │   ├─ factory/line3/press-01/vibration   (QoS 0)
    │   ├─ factory/line3/weld-01/weld_current (QoS 0)
    │   └─ factory/line3/inventory/snapshot   (QoS 1)
    │
    ├─③ 환경 스냅샷 갱신 (thread-safe copy)
    │
    ├─④ max_cycles 도달 확인 (시나리오 모드 시)
    │
    └─⑤ 센서 다이나믹스 적용 (시나리오 확률 사용)
        ├─ drift_recovery_prob 확률: 진동 드리프트 감쇠 (정비 효과)
        ├─ drift_spike_prob 확률: 진동 드리프트 증가 (마모)
        └─ 자재 < restock_threshold 시 자동 보충
```

### 4.2 이벤트 생성기 (시나리오 설정 기반)

```
시나리오별 누적 확률 임계값:

정상 운영:                           복합 위기:
  roll < 0.20 → 신규 주문              roll < 0.25 → 신규 주문 (대량)
  roll < 0.35 → 진동 스파이크           roll < 0.50 → 진동 스파이크 (강력)
  roll < 0.50 → 설비 안정화             roll < 0.53 → 설비 안정화 (낮음)
  roll < 0.60 → 강판 입고              roll < 0.58 → 강판 입고 (드묾)
  roll < 0.70 → AGV 상태 변경          roll < 0.73 → AGV 상태 변경 (빈번)
  roll < 0.80 → 라인 속도 복원          roll < 0.75 → 라인 속도 복원 (드묾)

이벤트 간격: 10~30초                   이벤트 간격: 4~12초
긴급 주문 비율: 40%                    긴급 주문 비율: 70%
스파이크 크기: 0.3~1.2                 스파이크 크기: 0.8~2.5
```

### 4.3 CNP 협상 흐름

```
PA가 2개 이상의 ALERT를 수신하면 CNP 개시:

Time ──────────────────────────────────────────────────────→

PA      EA      QA      SA      DA      IA
│       │       │       │       │       │
├─CFP──►├──────►├──────►├──────►├──────►│  ① CFP 브로드캐스트
│       │       │       │       │       │     "설비이상+품질저하"
│◄PROP──┤       │       │       │       │  ② 각 에이전트 제안
│       │◄PROP──┤       │       │       │     EA: "감속80%+모니터링"
│       │       │◄PROP──┤       │       │     QA: "전수검사+수율예측"
│       │       │       │◄PROP──┤       │     SA: "물류지원+버퍼확대"
│       │       │       │       │◄PROP──┤     DA: "납기연장+예측정밀화"
│       │       │       │       │       │     IA: "SS하향가능"
│       │       │       │       │       │
├─EVAL──┤       │       │       │       │  ③ 제안 평가 (KPI 가중)
│ LLM   │       │       │       │       │     quality:30% delivery:25%
│ or    │       │       │       │       │     cost:25% safety:20%
│ Rule  │       │       │       │       │
│       │       │       │       │       │
├─ACPT─►├──────►├──────►├──────►├──────►│  ④ 통합 전략 전파
│       │       │       │       │       │     속도=80%, 검사=enhanced
│       │       │       │       │       │     모니터링=10초
│       │       │       │       │       │
│       ├─exec──┤       │       │       │  ⑤ 각 에이전트 지시 실행
│       │  PLC  │ 검사  │ AGV   │ 수요  │     EA: PLC 감속 명령
│       │  감속  │ 강화  │ 조정  │ 분석  │     QA: 전수검사 전환
│       │       │       │       │       │     SA: 물류 재배치
│       │       │       │       │       │
│       │       │       │       ├─SS────┤  ⑥ SS 재계산
│       │       │       │       │  재계산│     demand_std × 0.6
│       │       │       │       │       │     leadtime 반영
│       │       │       │       │       │     SS 동적 하향
```

---

## 5. 스레드 구성

```
┌─ [Main Thread]           메인 디스플레이 루프 (1초 주기)
├─ [ENV-TICK]              환경 틱 (takt_sec ± 0.3, 시나리오 설정)
├─ [EVENT-GEN]             랜덤 이벤트 (event_interval_range, 시나리오 설정)
├─ [AGENT-EA]              설비 에이전트 (agent_intervals.EA ± 0.3)
├─ [AGENT-QA]              품질 에이전트 (agent_intervals.QA ± 0.3)
├─ [AGENT-SA]              공급 에이전트 (agent_intervals.SA ± 0.3)
├─ [AGENT-DA]              수요 에이전트 (agent_intervals.DA ± 0.3)
├─ [AGENT-IA]              재고 에이전트 (agent_intervals.IA ± 0.3)
├─ [AGENT-PA]              계획 에이전트 (agent_intervals.PA ± 0.3)
├─ [MAS-API]               FastAPI/uvicorn (데몬)
└─ [MQTT-loop]             paho-mqtt 네트워크 루프 (데몬, 선택)
```

스레드 안전:
- `_snap_lock`: 환경 스냅샷 접근 시 copy.copy()
- `_log_lock`: 로그 버퍼 접근
- `BaseAgent._lock`: inbox/outbox/internal_state 접근
- `ToolRegistry._lock`: 도구 호출 로그
- `RouterMetrics._lock`: 판단 통계

---

## 6. 메시지 프로토콜 (FIPA-ACL)

```json
{
  "header": {
    "sender": "EA",
    "receiver": "PA",
    "conversation_id": "cnp-001",
    "timestamp": "14:32:15.123",
    "message_id": "a1b2c3d4",
    "protocol": "CNP"
  },
  "intent": "ALERT",
  "body": {
    "type": "facility_anomaly",
    "alarm_level": "L2",
    "vibration": 4.12,
    "vibration_ma": 3.85,
    "capacity": { "capacity_factor": 0.72, "reliability": 0.68 },
    "summary": "설비 경고 L2 - 진동 4.12mm/s, 가용능력 72%"
  }
}
```

Intent 전체 목록:
```
CNP:      CFP, PROPOSE, ACCEPT_PROPOSAL, REJECT_PROPOSAL
기본:     INFORM, REQUEST, ALERT, ACKNOWLEDGE, CONFIRM
도메인:   DEMAND_CHANGE, STOCK_ALERT, PLAN_UPDATE
도구:     TOOL_CALL, TOOL_RESULT
협업:     ACCEPT_JOB, REJECT_JOB
상태:     STATUS_REPORT
```

---

## 7. 콘솔 라이브 모니터링

```
════════════════════════════════════════════════════════════════
  LIVE MONITORING — Multi AI Agent System  (Ctrl+C 종료)
════════════════════════════════════════════════════════════════
      시간   Cyc │     진동    유온 │   판정   Cpk │   재고  SS    SL │ Agent Activity
  ─────────────────────────────────────────────────────────────────
  08:12:30 C0014 │  3.5▰▰▰▱▱▱   43° │ 양품   0.7 │   89/31 100% │
  08:13:15 C0015 │  3.8▰▰▰▰▱▱   43° │ 보류   0.6 │   84/31 100% │ EA(!) L2 vib:3.82
                                │               │ EA(.) Tool:predictive_maintenance [ok]
                                │               │ QA(!) Cpk:0.65 yield:68%
                                │               │ QA(.) Tool:defect_prediction [ok]
  08:14:00 C0016 │  3.6▰▰▰▰▱▱   43° │ 양품   0.6 │   79/31 100% │ PA(N) [*] CNP 개시
                                │               │ PA(N) CFP 브로드캐스트 → ALL
                                │               │ EA(N) PROPOSE: 감속80%
                                │               │ QA(N) PROPOSE: 전수검사
                                │               │ PA(N) 전략 확정 [Rule-based]
                                │               │ EA(v) 지시 실행 완료
                                │               │ IA(v) SS 재계산: 31→12
```

---

## 8. 대시보드 (http://localhost:8787)

실시간 폴링 (2초) + SSE 스트림:

| 카드 | 표시 내용 |
|------|-----------|
| System Status | 사이클 수, 가동 시간, LLM 모드 |
| Message Broker | 발행/전달 수, 평균 지연, DLQ, 처리량 |
| Inventory & Safety Stock | 재고, SS, 서비스레벨, 재고 차트 |
| Agent Status | 6개 에이전트 상태 바 + inbox 크기 |
| Message Stream | 실시간 메시지 흐름 (SSE) |
| LLM Orchestration | 모델명, 토큰 사용량, API 호출 수 |
| AI Tool Registry | 도구 수, 총 호출, 에러, 도구별 통계 |
| Decision Router | Rule/LLM 판단 비율, 폴백 수 |

---

## 9. 실행 방법

### 기본 실행 (대시보드 + 실시간 모니터링, Ctrl+C까지)
```bash
pip install -r requirements.txt
set OPENAI_API_KEY=sk-...              # (선택) LLM 활성화
python main.py                         # 대화형 모드 (6공정 시뮬 + 대시보드)
python run_scenario.py --scenario scenarios/equipment_failure.yaml  # 시나리오 모드
python run_scenario.py --list-scenarios  # 시나리오 목록
```

### 시나리오 테스트 (자동 실행 + JSON 결과 저장)
```bash
# 시나리오 목록 확인
python run_scenario.py --list

# 시나리오 실행
python run_scenario.py -s scenarios/normal.yaml -c 100
python run_scenario.py -s scenarios/equipment_failure.yaml -c 100
python run_scenario.py -s scenarios/demand_surge.yaml -c 100
python run_scenario.py -s scenarios/quality_crisis.yaml -c 100
python run_scenario.py -s scenarios/supply_shortage.yaml -c 100
python run_scenario.py -s scenarios/compound_crisis.yaml -c 100

# 결과 비교
python compare_results.py results/normal_*.json results/equipment_failure_*.json
python compare_results.py results/*.json
```

### MQTT 브로커 (선택)
```bash
docker run -d -p 1883:1883 eclipse-mosquitto
```

---

## 10. 핵심 공식 요약

| 공식 | 수식 | 용도 |
|------|------|------|
| 안전재고 | `SS = z × √(LT × σ_D² + d² × σ_LT²)` | 동적 SS 계산 |
| 서비스레벨 | `SL = 총출하 / 총요청` | 납기 준수율 |
| Cpk | `min((USL-μ)/3σ, (μ-LSL)/3σ)` | 공정능력 |
| OEE | `가동률 × 성능률 × 양품률` | 종합설비효율 |
| 불량확률 | `0.05 + vib×0.4 + temp×0.1 + trend×0.2 + burr×0.25` | 불량 예측 |
| 가용능력 | `speed/100 - degradation - trend_penalty` | 생산능력 계수 |

---

## 11. 의사결정 우선순위

```
1. 설비 안전    ← 인명·장비 보호 (Rule, 즉시, < 1ms)
2. 품질 확보    ← Cpk 유지, 불량 유출 방지
3. 납기 준수    ← 고객 서비스레벨 ≥ 95%
4. 재고 최적화  ← 불확실성 감소 시 SS 동적 하향
```
