# Manufacturing Multi-Agent System (MAS) v5

자동차 부품 제조 라인을 시뮬레이션하고, 6종 AI 에이전트가 실시간 협업하여 공장을 최적화하는 멀티 에이전트 시스템입니다.

## 핵심 특징

- **6공정 생산 라인** — 블랭킹 → 포밍 → 용접 → 열처리 → CNC → 조립/검사
- **6역할 에이전트** — 설비(EA) · 품질(QA) · 자재(SA) · 수요(DA) · 재고(IA) · 계획(PA)
- **Sense-Reason-Act 루프** — 각 에이전트가 공장 스냅샷을 주기적으로 읽어 판단·행동
- **Contract Net Protocol** — 위기 상황 시 PA가 CNP를 통해 에이전트별 제안을 수집·평가
- **하이브리드 의사결정** — 안전·임계 상황은 규칙, 복합 상황만 조건부 LLM 활용
- **실시간 대시보드** — FastAPI + SSE 기반 웹 모니터링 (OEE, KPI, 에이전트 상태)
- **YAML 시나리오** — 정상/설비고장/품질위기/자재부족/수요폭주/복합위기 6종
- **표준 제조 컨텍스트(v2)** — `ManufacturingContext` 계약, Sense 직전 `enrich_snapshot_for_agents`로 스냅샷 보강
- **비즈니스 이벤트·CNP 비교** — `business_events` 테일, `cnp_comparison.merge_into_proposal`로 제안에 비교 메트릭 병합
- **운영 의사결정 카드** — CNP 전략에 `operational_decision_card`(스키마 `operational_decision_card/v1`) 포함

## 시스템 구조

```
┌──────────────────────────────────────────────────────────┐
│                    Factory (시뮬레이션)                     │
│  WC-01 → WC-02 → WC-03 → WC-04 → WC-05 → WC-06        │
│  블랭킹   포밍    용접    열처리   CNC    조립/검사        │
└──────────────┬───────────────────────────────────────────┘
               │ get_snapshot()
    ┌──────────┼──────────────────────────────────┐
    │    ┌─────▼─────┐  ┌─────────┐  ┌─────────┐ │
    │    │ EA (설비)  │  │ QA (품질)│  │ SA (자재)│ │
    │    └─────┬─────┘  └────┬────┘  └────┬────┘ │
    │          │   MessageBroker (토픽/큐)  │      │
    │    ┌─────▼─────┐  ┌────▼────┐  ┌────▼────┐ │
    │    │ DA (수요)  │  │ IA (재고)│  │ PA (계획)│ │
    │    └───────────┘  └─────────┘  └────┬────┘ │
    │                                CNP 협상     │
    └─────────────────────────────────────────────┘
               │
    ┌──────────▼──────────┐
    │  FastAPI Dashboard  │
    │  http://localhost:8787  │
    └─────────────────────┘
```

## 빠른 시작

### 요구 사항

- Python 3.10+
- (선택) OpenAI API 키 — LLM 기능 활성화 시

### 설치

```bash
git clone <repo-url> && cd Multi-Agent
pip install -r requirements.txt
```

### 환경 설정

```bash
copy .env.example .env
# .env 파일을 열어 필요한 값 수정 (OPENAI_API_KEY 등)
```

### 실행

```bash
# 대화형 모드 (시뮬레이션 + 대시보드)
python main.py

# 대시보드 접속
# http://localhost:8787
```

### 시나리오 테스트

```bash
# 시나리오 목록 확인
python run_scenario.py --list

# 특정 시나리오 실행 (결과 JSON 자동 저장)
python run_scenario.py --scenario scenarios/equipment_failure.yaml --cycles 100

# 결과 비교
python compare_results.py
```

### 테스트

```bash
pip install -r requirements-dev.txt
python -m pytest
```

## 프로젝트 구조

```
Multi-Agent/
├── main.py                    # 진입점: 대화형 시뮬레이션 + 대시보드
├── run_scenario.py            # CLI 시나리오 러너 (자동 실행 + JSON 결과)
├── compare_results.py         # 시나리오 결과 비교
│
├── mas/                       # 메인 패키지
│   ├── domain/                # Factory, 센서, 재고, manufacturing_context, business_events, agent_snapshot
│   ├── agents/                # 6종 에이전트 + planning_sub / qa_sub (내부 모듈)
│   ├── adapters/              # 외부 연동 경계용 Protocol 스텁 (센서·MES·ERP 등)
│   ├── messaging/             # MessageBroker, MQTT 브릿지
│   ├── intelligence/          # LLM(감사 로그), 라우터, 최적화, operational_decision_card
│   ├── protocol/              # CNP 세션, SRA, LangGraph, cnp_comparison(대안 비교 블록)
│   ├── runtime/               # FactoryRuntime (스레드 관리, 틱 루프)
│   ├── api/                   # FastAPI 서버 + 대시보드
│   │   └── static/            # dashboard.html
│   ├── core/                  # 설정, 로깅, 제조 ID 상수
│   ├── scenario/              # YAML 시나리오 로더
│   └── tools/                 # AI 도구 레지스트리
│
├── scenarios/                 # YAML 시나리오 6종
│   ├── normal.yaml            # 정상 운영 (baseline)
│   ├── equipment_failure.yaml # 설비 고장
│   ├── quality_crisis.yaml    # 품질 위기
│   ├── supply_shortage.yaml   # 자재 부족
│   ├── demand_surge.yaml      # 수요 폭주
│   └── compound_crisis.yaml   # 복합 위기
│
├── tests/                     # 단위 + E2E·로드맵 통합 테스트 (pytest 수집 약 48개)
│
├── pyproject.toml             # 패키지 메타데이터 + 빌드 설정
├── requirements.txt           # 런타임 의존성
├── requirements-dev.txt       # 개발 의존성
├── .env.example               # 환경변수 템플릿
└── .gitignore
```

## 환경 변수

| 변수 | 기본값 | 설명 |
|------|--------|------|
| `OPENAI_API_KEY` | (없음) | OpenAI API 키 (LLM 비활성 시 규칙 기반으로 동작) |
| `MAS_API_HOST` | `127.0.0.1` | 대시보드 바인딩 호스트 |
| `MAS_API_PORT` | `8787` | 대시보드 포트 |
| `MAS_TAKT_SEC` | `2.0` | 공장 사이클 간격 (초) |
| `MAS_LLM_MODEL` | `gpt-4o-mini` | PA 오케스트레이션 LLM 모델 |
| `MAS_LOG_LEVEL` | `INFO` | 로깅 레벨 |
| `MAS_API_BEARER_TOKEN` | (없음) | API 인증 토큰 (비어 있으면 비활성) |
| `MAS_CORS_ORIGINS` | `*` | CORS 허용 Origin |

전체 옵션은 `.env.example` 참조.

## 에이전트 역할

| ID | 이름 | 역할 |
|----|------|------|
| **EA** | 설비 에이전트 | 예지보전, 이상 탐지, RUL 추정 |
| **QA** | 품질 에이전트 | SPC, Cpk 관리도, 런 규칙 위반 감지 |
| **SA** | 자재 에이전트 | 재고 모니터링, ROP 발주, 소모율 분석 |
| **DA** | 수요 에이전트 | 수요 예측, 주문 스케줄링, 납기 관리 |
| **IA** | 재고 에이전트 | WIP 버퍼 관리, 병목 탐지, 폐기율 모니터링 |
| **PA** | 계획 에이전트 | 전체 조율, CNP 협상, LLM 전략 생성 |

## API 엔드포인트

| Method | Path | 설명 |
|--------|------|------|
| GET | `/` | 모니터링 대시보드 |
| GET | `/api/factory` | 공장 전체 스냅샷 |
| GET | `/api/agents` | 에이전트 상태 + 추론 이력 |
| GET | `/api/kpi` | KPI 요약 (OEE, FPY, 납기율) |
| GET | `/api/broker` | 브로커 메트릭 |
| GET | `/api/monitoring` | 통합 모니터링 JSON |
| GET | `/api/stream` | SSE 실시간 스트림 |
| POST | `/api/ask` | 자연어 질의 (스냅샷 기반) |

## 기술 스택

- **Python 3.10+** — 런타임
- **FastAPI + Uvicorn** — REST API + 대시보드
- **OpenAI API** — (선택) LLM 의사결정
- **LangGraph** — SRA 에이전트 프로토콜 그래프
- **Paho MQTT** — (선택) 외부 브로커 연동
- **PyYAML** — 시나리오 설정

## 참고 문서

| 문서 | 내용 |
|------|------|
| `OVERVIEW.md` | 비전문가용 프로젝트 개요 |
| `ARCHITECTURE.md` | 기술 아키텍처 상세 |
| `HOW_IT_WORKS.md` | 코드 흐름 설명 |
| `CURRENT_SYSTEM_GUIDE.md` | 현행 시스템 가이드 |
| `MAS_SYSTEM_REFERENCE.md` | 시스템 레퍼런스 |
| `AI_MODELS_AND_AGENTS.md` | AI 모델·에이전트 설명 |

## 라이선스

MIT
