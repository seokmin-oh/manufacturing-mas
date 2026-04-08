# AI·모델·에이전트 구성 (공정 매핑 포함)

이 문서는 저장소 **현재 구현** 기준으로 정리합니다.  
“모델”이 **학습된 ONNX/PyTorch 파일**으로 배포된 것은 아니고, 대부분 **휴리스틱·규칙·통계식**과 **선택적 LLM API 호출**의 조합입니다.

---

## 1. 용어 정리

| 구분 | 의미 (이 프로젝트에서) |
|------|-------------------------|
| **LLM** | OpenAI 호환 API (`LLMClient`) — 기본 모델명은 `MAS_LLM_MODEL` (예: `gpt-4o-mini`). 키 없으면 규칙 폴백. |
| **도메인 소형 LLM** | `MAS_LLM_DOMAIN_MODEL` — 메타만 있고, 전 에이전트 전용 분기는 확장용. |
| **공정 유형별 PdM 프로파일** | `mas/intelligence/equipment_predictive_models.py` 의 **`EQUIPMENT_PM_MODELS`** — 유형(PRESS/WELD/…)마다 `model_id`, 주요 신호, 이상 민감도, RUL 스케일 등 **설정형 프로파일** (별도 가중치 파일 없음). |
| **이상·RUL** | `mas/agents/equipment_sub/` 의 통계·스케일 함수 — **시뮬용 경량 로직**. |
| **서브 에이전트** | 문서·모니터링용 **논리 역할** (`multi_agent_teams`) + 일부는 `get_agent_status()["sub_agent_views"]` 에 실측 요약이 붙음. |

---

## 2. 공정(WC) ↔ 설비 유형 ↔ 예지(PdM) 프로파일

`create_production_line()` (`mas/domain/machines.py`) 순서와 `station_type` 이 아래와 같이 대응합니다.

| 공정 ID | 공정 이름(요약) | `station_type` | PdM `model_id` | 모델 이름(한글) | 주요 신호(예) |
|---------|-----------------|----------------|----------------|----------------|---------------|
| **WC-01** | 블랭킹 프레스 | `PRESS` | `pm-press-vib-hyd-v1` | 프레스 진동·유압 예지 | vibration, oil_temp, tonnage |
| **WC-02** | 포밍 프레스 | `PRESS` | *(동일 유형 → 동일 프로파일)* | ↑ | springback, stroke_position 등 |
| **WC-03** | 스팟 용접 | `WELD` | `pm-weld-nugget-v2` | 스팟용접 너겟·전극 예지 | weld_current, weld_force, nugget_dia |
| **WC-04** | 열처리 | `HEAT` | `pm-furnace-soak-v1` | 열처리 노·경도 예지 | furnace_temp, hardness, quench_temp |
| **WC-05** | CNC 가공 | `CNC` | `pm-cnc-spindle-v1` | CNC 스핀들·진동 예지 | spindle_vib, spindle_load, surface_ra |
| **WC-06** | 조립/검사 | `ASSY` | `pm-assy-torque-vision-v1` | 조립 토크·비전 예지 | torque, vision_score, force |

- **같은 `station_type`** 이면 **같은 PdM 프로파일**을 공유합니다 (WC-01·02 둘 다 PRESS).
- EA(설비)가 스냅샷을 읽을 때 `profile_for_station_type()` 으로 위 프로파일을 골라 이상도 스케일·RUL 스케일에 반영합니다.

---

## 3. LLM이 어디에 쓰이나

| 용도 | 위치 | 비고 |
|------|------|------|
| **PA 전략·서술** | `PlanningAgent` + `mas/intelligence/llm.py` | `OPENAI_API_KEY` 있을 때 JSON 전략 등 생성 시도, 없으면 규칙. |
| **하이브리드 라우터** | `mas/intelligence/decision_router.py` | 복합 경보 등 조건에서 **상황 분석** 경로로 LLM 후보 (`MAS_LLM_ROUTER_SCOPE`, `MAS_LLM_PER_AGENT_ASSIST`). |
| **대시보드 질의** | `mas/intelligence/monitoring_qa.py` | 스냅샷 축약 컨텍스트 + LLM 또는 휴리스틱 답변. |
| **도메인 추론 훅** | `domain_inference` 등 | LLM과 결합 가능한 메타; 기본은 규칙 중심. |

**한 줄**: LLM은 **전 공정 매 틱 전부**가 아니라, **PA·라우터·질의 등 제한된 경로**에서만 호출됩니다.

---

## 4. 상위 에이전트 6종 구성 (역할·데이터·협업)

`mas/intelligence/agent_domain_registry.py` 의 `AGENT_FACTORY_COVERAGE` 와 일치합니다.

| ID | 이름 | 담당 공장 영역 | 주 데이터 | 지능(구현 관점) | 협업 |
|----|------|----------------|-----------|----------------|------|
| **EA** | 설비 | 라인·이벤트 | 공정 센서·OEE·공구·MTBF 등 | 유형별 PdM 프로파일 + 이상·RUL 휴리스틱 | PA·CNP에 제약·속도 제안 |
| **QA** | 품질 | 라인·FG | 측정·Cpk·관리도·불량 | SPC·런 규칙 등 | 이상 시 PA 알림 |
| **SA** | 자재 | 원자재 | 재고·ROP·리드타임 | 소모·발주 판단 | 부족 시 PA 등 |
| **DA** | 수요 | 주문 | 수량·납기·우선순위 | 변동·긴급 감지 | PA·IA |
| **IA** | 재고 | WIP·FG | 버퍼·완제품 | 흐름·병목 힌트 | PA |
| **PA** | 계획 | 광역 | 전역 스냅샷·CNP | 규칙 CNP + (선택) LLM | CFP·라인 속도 |

브로커 기본 토픽: EA→equipment, QA→quality, SA→supply, DA→demand, IA→inventory, PA→planning (`mas/messaging/broker.py`).

---

## 5. 내부 “서브 에이전트” (문서·모니터링 관점)

`mas/intelligence/multi_agent_teams.py` 의 **`MULTI_AGENT_TEAMS`** — **런타임 별도 프로세스는 아니고**, 책임 분해·확장 기준선입니다.

| 상위 | 서브 ID (예) | 초점 |
|------|--------------|------|
| EA | EA-PdM-VIB, EA-PdM-HYD, EA-PdM-TOOL, EA-LINE | 진동·유압·공구·라인 조율 |
| QA | QA-SPC, QA-RULE, QA-CORR, QA-ALERT | 관리도·런규칙·상관·경보 |
| SA | SA-ROP, SA-SUP, SA-SHOR | ROP·공급사·부족 예측 |
| DA | DA-ORD, DA-SURGE, DA-FCS | 주문·수동·예측 보정 |
| IA | IA-WIP, IA-FG, IA-BN | WIP·완제품·병목 |
| PA | PA-ORCH, PA-CNP, PA-LLM, PA-POL | 오케스트레이션·CNP·서술·정책 |

**대시보드 `sub_agent_views` 에 실제로 붙는 예** (구현 차이 있음):

- **EA**: `EA-AD`(이상), `EA-RUL`(RUL) — `equipment_agent.get_agent_status()`
- **PA**: `PA-ORCH`, `PA-ALERT` — `planning_agent.get_agent_status()`
- **QA, SA, DA, IA**: 클래스 내부 `_sub_views` 를 그대로 노출 (SPC·ROP 등 요약 필드)

---

## 6. PA·QA 내부 모듈 · CNP 비교 · 감사

| 내용 | 파일 |
|------|------|
| PA — 제안 순위·보고 보조 | `mas/agents/planning_sub/` (`rank_proposals_by_comparison` 등) |
| QA — SPC·비전 확장 스텁 | `mas/agents/qa_sub/` |
| CNP 제안에 비교 메트릭 병합 | `mas/protocol/cnp_comparison.py` |
| CNP 전략 → 운영 카드 | `mas/intelligence/operational_decision_card.py` |
| 에이전트 스냅샷 보강 | `mas/domain/agent_snapshot.py` (`enrich_snapshot_for_agents`) |
| LLM 호출 감사 로그 | `mas/intelligence/llm.py` — `LLMClient.audit_log` |

## 7. 관련 소스 파일

| 내용 | 파일 |
|------|------|
| WC 생성·`station_type` | `mas/domain/machines.py` |
| 유형별 PdM 프로파일·카탈로그 | `mas/intelligence/equipment_predictive_models.py` |
| EA 이상·RUL | `mas/agents/equipment_agent.py`, `mas/agents/equipment_sub/` |
| 6역할 담당 영역 표 | `mas/intelligence/agent_domain_registry.py` |
| 서브 팀 정의 | `mas/intelligence/multi_agent_teams.py` |
| LLM 클라이언트 | `mas/intelligence/llm.py` |
| 라우터 | `mas/intelligence/decision_router.py` |
| 설정 `MAS_LLM_*` | `mas/core/config.py`, `.env.example` |
| 외부 연동 경계(Protocol) | `mas/adapters/base.py` |

---

*공정 수나 유형을 바꾸면 `create_production_line`, `EQUIPMENT_PM_MODELS`, 대시보드/스냅샷을 함께 맞춰야 합니다 (`mas/core/manufacturing_ids.py` 의 `STATION_IDS` 참고). 통합 동작은 `tests/test_roadmap_integration.py` 등에서 검증합니다.*
