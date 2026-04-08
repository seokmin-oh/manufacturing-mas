# 제조 멀티 AI 에이전트 시스템 — 구현·구성 완전 참조

> 본 문서는 **현재 저장소 코드 기준**으로 실행 흐름, 모듈 책임, LLM·라우터·CNP·API를 한곳에 정리합니다.  
> **처음 전체 흐름을 읽기 쉽게** 보려면 `CURRENT_SYSTEM_GUIDE.md`를 먼저 보세요.  
> 비전·시나리오 개요는 `OVERVIEW.md`, 다이어그램 중심 설명은 `ARCHITECTURE.md`, 동작 요약은 `HOW_IT_WORKS.md`를 참고하세요.

---

## 0. 쉽게 읽는 설명 (먼저 이것만)

아래는 **기술 문서 전체를 읽기 전에** 이해를 돕기 위한 레이어입니다. 비유와 순서 위주로 적었고, 뒤쪽 절부터가 “정확한 구현 참고”입니다.

### 0.1 이 프로그램이 하는 일 (한 번에 말하면)

1. **가상 공장**이 돌아간다. (6공정 라인, 센서, 재고, 주문 같은 것이 시뮬레이션으로 움직임.)  
2. **역할이 다른 AI 직원 6명**이 각자 맡은 일을 본다. (설비, 품질, 자재, 수요, 재고, 전체 계획.)  
3. 정말 필요할 때만 **챗GPT 같은 LLM**을 불러서 “상황 설명이나 협상 결과 문장”을 보강한다. **매 틱마다 전원 LLM을 쓰는 구조는 아니다.**

### 0.2 비유로 잡기

| 말로 쓰인 말 | 쉬운 비유 |
|--------------|-----------|
| `Factory` | 게임 속 **공장 맵** (상태가 계속 갱신됨) |
| 에이전트 6종 | 공장에 있는 **팀** — 각자 KPI가 다름 |
| `MessageBroker` | 팀원끼리 주고받는 **내부 메신저/게시판** |
| `HybridDecisionRouter` | “**위험하면 즉시 규칙**, 애매하면 (조건맞으면) LLM에게 물어봄”을 정하는 **안전한 관문** |
| LLM | **보고서/설명용 조언자**에 가깝고, 코드 설계상 **설비를 직접 멋대로 켜고 끄는 존재가 아님** |
| CNP | 여러 팀이 **각자 제안**을 내고, PA가 **점수·규칙으로 한 방향**을 고른 뒤, 필요하면 LLM이 **그 선택의 이유만** 다듬는 **회의**에 가깝다 |

### 0.3 `python main.py` 를 실행하면 (시간 순서)

1. 설정 파일(`.env`)을 읽는다.  
2. **공장 객체** 하나를 만든다.  
3. **브로커·(선택) MQTT·LLM 클라이언트·판단 라우터**를 만든다.  
4. **에이전트 6개**를 만들고 브로커에 연결한다.  
5. **`FactoryRuntime`**이 백그라운드에서 동시에 돌아가기 시작한다.  
   - 한쪽은 “**공장 시계**”처럼 일정 간격으로 `run_cycle()`을 돌려 **라인 상태를 갱신**하고,  
   - 다른 쪽은 가끔 **랜덤 이벤트**(고장, 신규 주문 등)를 터뜨리고,  
   - 또 다른 여러 줄기는 **에이전트마다 다른 주기**로 “지금 공장 사진(스냅샷) 보고 판단”을 반복한다.  
6. 웹 서버(FastAPI)가 켜지면 브라우저로 **대시보드**를 볼 수 있다. (이때도 **같은 프로세스 안의 공장**에 붙어 있어야 숫자가 채워짐.)

### 0.4 6명을 이렇게만 기억해도 됨

- **EA** 설비 — 진동·온도·고장 쪽  
- **QA** 품질 — 불량·관리도 쪽  
- **SA** 자재 — 재고 부족·보충 쪽  
- **DA** 수요 — 주문·납기 쪽  
- **IA** 재고/WIP — 흐름·병목 쪽  
- **PA** 계획 — 위를 **종합**하고, 필요하면 **CNP 회의**를 열고, **라인 속도** 같은 큰 레버를 조정

### 0.5 LLM은 “어디에만” 붙어 있나 (초간단)

- **① 협상(CNP)이 끝난 뒤** — 숫자(누가 이겼는지, 속도 몇 %)는 이미 **규칙/솔버**가 정함 → LLM은 **왜 그렇게 했는지 문장**을 보강할 수 있음.  
- **② 여러 경보가 겹친 애매한 상황** — 라우터가 허용할 때만 **상황 분석 JSON**을 요청함.  

그 외 대부분은 **if 문·임계값·에이전트 규칙**으로 처리된다. 그래서 API 키가 없어도 **시뮬은 돌아간다.**

### 0.6 용어를 한 줄씩만

| 용어 | 한 줄 설명 |
|------|------------|
| **스냅샷** | 그 시점 공장 상태를 담은 **딕셔너리** (에이전트가 보는 “현재 화면”) |
| **SRA** | Sense(보기) → Reason(판단) → Act(행동) **세 단계 루프** |
| **라우터** | “규칙으로 끝낼지, LLM을 부를지”를 **먼저** 가르는 모듈 |
| **솔버** | CNP에서 **점수·숫자 후보**를 정하는 쪽 (LLM이 숫자를 바꾸지 않도록 설계됨) |
| **SSE** | 브라우저가 서버와 **실시간 스트림**으로 연결하는 방식 (대시보드 메시지·틱) |

### 0.7 이 문서를 어떻게 읽으면 좋나

- **처음**: 위 “0번”만 읽고, 궁금한 단어가 나오면 **0.6 용어**를 본다.  
- **조금 더 깊게**: 아래 [1. 시스템 한눈에](#1-시스템-한눈에)부터 순서대로.  
- **코드까지 맞춰볼 때**: 절 번호·파일 경로를 따라가면 된다.

---

## 목차

0. [쉽게 읽는 설명](#0-쉽게-읽는-설명-먼저-이것만) ← **입문용**  
1. [시스템 한눈에](#1-시스템-한눈에)
2. [실행 진입점](#2-실행-진입점)
3. [설정(환경 변수)](#3-설정환경-변수)
4. [런타임: 스레드와 데이터 흐름](#4-런타임-스레드와-데이터-흐름)
5. [공장 도메인](#5-공장-도메인)
6. [에이전트 6종](#6-에이전트-6종)
7. [SRA 루프와 라우터](#7-sra-루프와-라우터)
8. [LLM 연결(코드 경로 2종)](#8-llm-연결코드-경로-2종)
9. [CNP(Contract Net)](#9-cnpcontract-net)
10. [메시징·MQTT·SSE](#10-메시징mqttsse)
11. [REST API·대시보드](#11-rest-api대시보드)
12. [제어 스택 표(control_matrix)](#12-제어-스택-표control_matrix)
13. [패키지·파일 맵](#13-패키지파일-맵)
14. [시나리오·결과 JSON](#14-시나리오결과-json)

---

## 1. 시스템 한눈에

| 구분 | 내용 |
|------|------|
| **목적** | 6공정 생산 라인 시뮬레이션 + 6종 AI 에이전트의 Sense–Reason–Act, CNP 협상, (선택) LLM 근거·상황 분석 |
| **진입** | `python main.py` — 터미널 MES 스타일 로그 + 선택적 웹 대시보드 |
| **핵심 패키지** | `mas/` — `domain`, `agents`, `intelligence`, `protocol`, `runtime`, `messaging`, `api`, `core` |
| **판단 원칙** | 안전·임계 **규칙 우선** → 필요 시 **LLM(서술·권고)** → CNP는 **솔버 수치 확정** 후 **LLM 근거 보강(선택)** |

---

## 2. 실행 진입점

### 2.1 `main.py`

1. `get_settings()` — `MAS_*` 및 프로젝트 루트 `.env` 로드 (`mas/core/config.py`).
2. 인프라: `MessageBroker`, `MQTTBridge`, `LLMClient`, `HybridDecisionRouter`  
   - 라우터 생성 시 `llm_router_scope`, `llm_per_agent_assist` 전달.
3. `Factory()` — 공장 환경 인스턴스 (`mas/environment.py` → `mas/domain/environment.py`).
4. 에이전트 6종 생성: EA, QA, SA, DA, IA, **PA는 `PlanningAgent(llm_client=llm)`**.
5. 각 에이전트를 브로커에 등록, `mqtt` 연결.
6. `FactoryRuntime(factory, broker, agents, llm, mqtt, api, decision_router)` 생성.
7. FastAPI 사용 가능 시 `MASApiServer(port)` → `bind(env, agents, runtime, …)` → `start()` (별도 스레드에서 uvicorn).
8. `runtime.start()` 후 메인 스레드에서 `factory.cycle` 증가 시 터미널 출력 루프.

### 2.2 `run_scenario.py`

- YAML 시나리오 기반 **별도 런타임**(`AgentRuntime` / `ManufacturingEnvironment` 등) 경로.
- 동일하게 `LLMClient`, `HybridDecisionRouter`(설정 전달) 조립 가능.
- 결과는 `results/*.json` 등으로 저장 (프로젝트에 따라 상이 — `run_scenario.py` 참고).

---

## 3. 설정(환경 변수)

| 변수 | 기본·예시 | 설명 |
|------|-----------|------|
| `OPENAI_API_KEY` | (없으면 LLM 비활성) | OpenAI API 키. 없으면 규칙·솔버만 사용. |
| `MAS_LLM_MODEL` | `gpt-4o-mini` | 오케스트레이터/공용 채팅 모델 ID. |
| `MAS_LLM_DOMAIN_MODEL` | (비움) | 도메인 전용 모델명 **메타**. 현재는 **별도 모델 자동 호출 분기 없음**. |
| `MAS_API_PORT` | `8787` | REST·대시보드 포트. |
| `MAS_TAKT_SEC` | `2.0` | 환경 루프(`Factory.run_cycle`) 주기(초). |
| `MAS_LOG_LEVEL` | `INFO` | 로깅 레벨. |
| `MAS_API_BEARER_TOKEN` | (비움) | 설정 시 `/api/*`에 `Authorization: Bearer` 또는 `?token=` 필요. |
| `MAS_CORS_ORIGINS` | `*` | CORS Origin 목록. |
| `MAS_LLM_ROUTER_SCOPE` | `pa_only` | `pa_only`: 라우터의 `analyze_situation` 후보는 **주로 PA + 복합경보 조건**. `all_gated`: 비PA도 정책 허용 시 후보. |
| `MAS_LLM_PER_AGENT_ASSIST` | `0` | `1`이고 `all_gated`일 때 EA·QA·SA·DA·IA에서 **고심각·복합 경보** 시 LLM 후보. |
| `MAS_USE_LANGGRAPH` | `1` | `1`: SRA를 LangGraph로, `0` 또는 미설치: 순차 구현 폴백. |

`.env`는 `mas/core/config.py`의 `_resolve_dotenv_path()`로 **프로젝트 루트**를 찾아 로드합니다.

---

## 4. 런타임: 스레드와 데이터 흐름

**파일:** `mas/runtime/factory_runtime.py`

| 스레드 | 역할 |
|--------|------|
| **ENV-TICK** | `while _running`: `factory.run_cycle()` → `get_snapshot()` → `_snapshot` 갱신 → (API 있으면) ~1.5초마다 `api.push_event("factory_tick", {cycle, clock, avg_oee, fg_stock, shift})` → `TAKT_SEC` 만큼 sleep |
| **EVENT-GEN** | 랜덤 간격으로 고장·신규 주문·품질 드리프트·입고 등 이벤트 → 공장 상태·로그 갱신 |
| **AGENT-{id}** | 에이전트별 `AGENT_INTERVALS` 간격으로 스냅샷 읽어 **`run_cycle_with_router`** (또는 PA는 `_run_pa`) |

**스냅샷 일관성:** 에이전트는 `_lock`으로 보호된 `_snapshot`을 읽습니다. 환경 틱이 스냅샷을 갱신합니다.

**PA 전용:** `_run_pa`에서 `decision.initiate_cnp`이면 `PlanningAgent.initiate_cnp(다른 에이전트 목록, snap)` 호출 → 전략의 `target_speed_pct`로 **전 공정 속도** 조정.

---

## 5. 공장 도메인

**파일:** `mas/domain/environment.py` — 클래스 `Factory`

- **6공정** `line` (예: WC-01 … WC-06), 센서·OEE·상태 머신.
- **`run_cycle()`** — 생산 1스텝/시뮬 시간 진행.
- **`get_snapshot()`** — 에이전트·API용 딕셔너리: `stations`, `materials`, `avg_oee`, `cycle`, `clock`, 주문 등. **`business_events`** 키로 최근 비즈니스 이벤트 테일이 포함될 수 있습니다 (`BusinessEventStore`, `mas/domain/business_events.py`).
- **`get_kpi_summary()`** — OEE, FPY, 납기, 에너지 등.

### 5.1 현장 연동 없이 “데이터만” 실제에 가깝게 (`plant_data_model`)

PLC·OPC를 붙이기 전에도, 스냅샷을 **히스토리안/MES에 넣었을 때와 비슷한 식별 규칙**으로 맞추기 위해 `mas/domain/plant_data_model.py`에서 메타를 붙입니다.

| 필드 | 의미 |
|------|------|
| **`plant`** | `schema_version`, `site_id`, `line_id`, `snapshot_kind`(simulation), `sim_time_sec`, `logical_clock_cycle` |
| **공정(`stations.*`)** | `resource_id` — `Site/Line/WC-xx` 형태의 리소스 URI |
| **센서(각 채널)** | 기존 `value`, `ma`, … 외에 `tag_id`, `sample_seq`, `observed_at_sim_sec`, `data_quality`(시뮬은 `GOOD`) |
| **자재** | `sku`, `uom`(EA), `supplier_id` |
| **주문** | `part`, `due_date` 포함 |

나중에 **시계열 DB**로 넣을 때는 `tag_id`·`observed_at_sim_sec`를 키로 삼기 쉽고, 실제 현장에서는 `sim_time_sec` 대신 **UTC 타임스탬프**만 바꿔 끼우면 같은 스키마를 유지할 수 있습니다.

---

## 6. 에이전트 6종

**베이스:** `mas/agents/base_agent.py` — `sense` / `reason` / `act`, 인박스, `handle_cfp` 등.

| ID | 클래스(대표) | 역할 요약 |
|----|----------------|-----------|
| EA | `EquipmentAgent` | 설비·진동·유온 등 |
| QA | `QualityAgent` | 품질·SPC |
| SA | `SupplyAgent` | 자재·ROP |
| DA | `DemandAgent` | 수요·납기 |
| IA | `InventoryAgent` | WIP·재고 |
| PA | `PlanningAgent` | OEE·CNP 주관, **LLM 클라이언트 보유**, 전략 로그 |

### 6.0 전 공장 에이전트화 (6역할 분할)

- **원칙:** 예지보전만 별도 AI가 아니라, **품질·자재·수요·재고·계획**까지 역할을 나눠 **같은 공장 스냅샷** 위에서 동작한다.
- **`mas/intelligence/agent_domain_registry.py`** — EA~PA 각각의 **담당 영역·주 데이터·지능 계층·협업 관계**를 표로 고정. API `factory_coverage`, 대시보드 **「전 공장 에이전트 커버리지」**에 표시.
- **PA**는 라인만 보는 게 아니라 주문·자재·완제품까지 묶어 **오케스트레이션**(CNP·속도) 담당.

### 6.0b 상위 에이전트 내부도 멀티 에이전트 (서브 역할)

- **원칙:** EA만 공정별 모델이 있는 것이 아니라, **QA·SA·…·PA도 내부를 전문 역할(서브 에이전트)의 합**으로 본다. 런타임은 한 클래스에 있어도 책임 분리·추후 마이크로서비스 분리의 기준선이 된다.
- **`mas/intelligence/multi_agent_teams.py`** — EA~PA 각각에 `EA-PdM-VIB`, `QA-SPC`, `PA-CNP` 등 **서브 ID·이름·초점** 정의. API `multi_agent_teams`, 대시보드 **「에이전트 내부 멀티 구성」**에 표시.
- **런타임 `get_agent_status["sub_agent_views"]`** (실측 요약):  
  - **EA** — `EA-AD`(이상), `EA-RUL`(RUL) (`equipment_sub` 모듈과 연동).  
  - **QA** — `QA-SPC`, `QA-VISION`, `QA-RISK`.  
  - **SA** — `SA-ROP`, `SA-STOCK`.  
  - **DA** — `DA-SCHED`, `DA-CAP`.  
  - **IA** — `IA-WIP`, `IA-SCRAP`.  
  - **PA** — `PA-ORCH`, `PA-ALERT`.  
  CNP `proposal_metrics` 는 EA·QA·SA·DA·IA 제안에 포함(비용·위반량 휴리스틱).

### 6.1 설비(EA) · 공정 유형별 예지보전 모델

- **`mas/intelligence/equipment_predictive_models.py`** — `PRESS`, `WELD`, `HEAT`, `CNC`, `ASSY`마다 **다른 `model_id`·주요 센서 가중·RUL 스케일**을 둔 프로파일.
- **`EquipmentAgent`** — 스냅샷의 `stations[*].type`으로 유형을 읽고, 센서별 이상 점수에 **유형·주/부 신호**에 따른 스케일을 적용. 공정별 `equipment_by_station`·`pm_model_catalog`를 `get_agent_status()`에 실음.
- **모니터링** — `/api/monitoring`의 `equipment_monitoring`, `equipment_catalog` 및 대시보드 **「설비 예지보전」** 블록에서 WC별 카드·카탈로그 표로 확인.

루트의 `mas/equipment_agent.py` 등은 `mas/agents/*`로 re-export 하는 shim일 수 있음.

---

## 7. SRA 루프와 라우터

**프로토콜 ID:** `mas/protocol/agent_protocol.py` — `AGENT_PROTOCOL_ID = "mas.sra.v2"`

**흐름:** `run_cycle_with_router(agent, snapshot, decision_router, log_fn, broker)`

1. **스냅샷 보강(에이전트)** — `snapshot = enrich_snapshot_for_agents(dict(snapshot))` (`mas/domain/agent_snapshot.py`) — `manufacturing_context`·수집 시각 등  
2. **Sense** — `agent.sense(snapshot)`  
3. **관측 보강** — `observations["new_alerts"]` 등  
4. **스냅샷 보강(라우터)** — `enriched = enrich_snapshot_for_router(snapshot)` (`mas/intelligence/snapshot_enrichment.py`)  
5. **HybridDecisionRouter.route(agent_id, observations, enriched)**  
6. **Reason** — `agent.reason(observations)`  
7. **Act** — `agent.act(decision)`

**LangGraph:** `MAS_USE_LANGGRAPH=1` 이고 `langgraph` 사용 가능 시 `mas/protocol/sra_langgraph.py`의 그래프 실행.  
**폴백:** `_run_sra_sequential` — 위와 동일한 단계를 순차 실행.

**라우터 파일:** `mas/intelligence/decision_router.py` — `HybridDecisionRouter`

- **1단계 안전:** 진동·유온 등 **인터록** → `ThinkResult` (로그 위주).
- **2단계 임계:** EA·SA 등 에이전트별 규칙.
- **3단계 LLM:**  
  - `llm_router_scope == pa_only` → **PA**만 `_should_use_llm_pa` (경보 유형 2종 이상 등).  
  - `all_gated` + `llm_per_agent_assist` → 비PA는 `_should_use_llm_non_pa` (고심각 또는 다건 경보).  
  - `LLMClient.analyze_situation(..., agent_id=...)` 호출.

라우터가 반환한 `ThinkResult`는 로그/메시지 적용 후에도 **에이전트 `reason`은 실행**됩니다(순차 구현 기준).

---

## 8. LLM 연결(코드 경로 2종)

**클라이언트:** `mas/intelligence/llm.py` — `LLMClient`

| 경로 | 진입 | API | 비고 |
|------|------|-----|------|
| **A. CNP 근거** | `PlanningAgent._build_strategy_llm` | `evaluate_proposals` → 솔버 수치 + `rationalize_cnp_decision` | 수치·승자는 **솔버 고정**, LLM은 문장·리스크 |
| **B. 라우터 상황 분석** | `HybridDecisionRouter._route_to_llm` | `analyze_situation` | JSON 권고·심각도 등, **설비 직접 명령 아님** |

**감사:** 주요 호출은 `LLMClient._audit()` → `audit_log`(최대 길이 상한 있음)에 메타가 누적됩니다.

`MAS_LLM_DOMAIN_MODEL`은 **저장·상태 표시용**이며, **자동으로 두 번째 모델을 호출하는 분기는 현재 없음**.

---

## 9. CNP(Contract Net)

**PA:** `mas/agents/planning_agent.py`

- `reason`에서 조건 충족 시 `initiate_cnp: true` 등.
- `initiate_cnp`: `CNPSession`, CFP 브로커 발행, 타 에이전트 `handle_cfp`로 제안 수집 — EA·QA 등은 **`mas/protocol/cnp_comparison.merge_into_proposal`** 로 제안에 **`comparison`** 블록을 병합할 수 있음. PA는 **`rank_proposals_by_comparison`**(`mas/agents/planning_sub/`)으로 순위 정리 후 **`_build_strategy`**.  
  - LLM 활성 시 `_build_strategy_llm` → `llm.evaluate_proposals`.
- 전략에 **`operational_decision_card`** (`mas/intelligence/operational_decision_card.py`, 스키마 `operational_decision_card/v1`) 및 `pa_report_lines` 등이 붙을 수 있음.

**런타임:** `FactoryRuntime._run_pa` / 시나리오 런타임에서 CNP 호출 시 **`enrich_snapshot_for_agents`** 적용 스냅샷을 넘기며, 완료 후 `target_speed_pct`로 라인 속도 반영.

---

## 10. 메시징·MQTT·SSE

| 구성 | 파일·동작 |
|------|-----------|
| **브로커** | `mas/messaging/broker.py` — 에이전트 등록, 메시지 전달, 메트릭 |
| **MQTT** | `mas/messaging/mqtt_bridge.py` — 선택적 센서 토픽 발행 |
| **SSE** | `mas/api/server.py` — `/api/stream`, 큐에 `factory_tick`·브로커 메시지 이벤트 |

---

## 11. REST API·대시보드

**서버:** `mas/api/server.py` — `MASApiServer`

- **`bind`** 시 `_env`, `_runtime`, `_decision_router`, `_agents`, `_llm` 연결. 브로커 메시지 시 SSE로 푸시.
- **주요 엔드포인트**

| 메서드·경로 | 설명 |
|-------------|------|
| `GET /` | 임베디드 HTML 대시보드 |
| `GET /api/status` | 시스템·`factory_bound`, uptime 등 |
| `GET /api/factory` | `Factory.get_snapshot()` |
| `GET /api/kpi` | KPI 요약 |
| `GET /api/agents` | 에이전트 상태 |
| `GET /api/monitoring` | 통합 JSON (`control_matrix`, `mas_overview`, `manufacturing_context` 어댑터, 스냅샷 등) |
| `GET /api/router` | `HybridDecisionRouter.get_status()` |
| `GET /api/stream` | SSE |

**주의:** `python main.py`로 API에 `Factory`가 bind되어야 `factory_bound`가 참이고 KPI·공정이 채워짐. API만 단독 실행 시 빈 응답이 정상일 수 있음.

---

## 12. 제어 스택 표(control_matrix)

**파일:** `mas/intelligence/control_matrix.py`

- `CONTROL_LAYERS`, `AGENT_ROLES`, `LLM_PATHS` 정의.
- `build_control_payload(get_settings())` → `/api/monitoring`의 `control_matrix` 및 웹 **표 섹션**에 사용.

---

## 13. 패키지·파일 맵

```
mas/
  core/           config, logging, manufacturing_ids
  domain/         Factory, machines, inventory, demand, manufacturing_context, business_events, agent_snapshot …
  agents/         6종 + base_agent, planning_agent, equipment_sub/, planning_sub/, qa_sub/
  adapters/       외부 연동 Protocol (base 등)
  intelligence/   llm(audit_log), decision_router, operational_decision_card, control_matrix, snapshot_enrichment, optimization_engine …
  protocol/       agent_protocol, sra_langgraph, cnp_session, cnp_comparison, contract_net …
  runtime/        factory_runtime, scenario_runtime
  messaging/      broker, message, mqtt_bridge
  api/            server (FastAPI + 대시보드 HTML)
  environment.py, broker.py, llm.py …  # domain/messaging re-export shim
```

---

## 14. 시나리오·결과 JSON

- **`scenarios/*.yaml`** — 시나리오 정의.
- **`run_scenario.py`** — 시나리오 실행·JSON 출력.
- **`compare_results.py`** — 결과 비교.
- **`results/`** — 실행별 결과 저장(타임스탬프 파일명).

---

## 문서 역할 구분

| 파일 | 용도 |
|------|------|
| **본 문서 (`MAS_SYSTEM_REFERENCE.md`)** | 구현·구성 **완전 참조**(코드 경로·설정·스레드) |
| **`CURRENT_SYSTEM_GUIDE.md`** | 현재 구성·구현 **통합 가이드**(흐름·대시보드·API 한눈에) |
| `ARCHITECTURE.md` | 다이어그램·디렉터리·버전 스코프 |
| `OVERVIEW.md` | 비기술 독자용 개요 |
| `HOW_IT_WORKS.md` | 동작 요약·엔드포인트 안내 |

---

*문서 버전: 저장소 현재 상태 기준. 코드 변경 시 본 문서와 함께 갱신하는 것을 권장합니다.*
