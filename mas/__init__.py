"""
Manufacturing Multi-Agent System (MAS) v5
=======================================

자동차 부품 **가상 공장** 시뮬 + **6역할 에이전트** + 브로커 + (선택) FastAPI 대시보드.

## 패키지 레이어 (읽을 때 이 순서 추천)
| 경로 | 책임 |
|------|------|
| `mas.domain.*` | Factory, 공정·센서·재고·주문 |
| `mas.messaging.*` | MessageBroker, AgentMessage |
| `mas.agents.*` | EA~PA Sense-Reason-Act |
| `mas.intelligence.*` | LLMClient, HybridDecisionRouter, 솔버·스냅샷 보강 |
| `mas.protocol.*` | CNP, SRA, LangGraph 래퍼 |
| `mas.runtime.*` | FactoryRuntime — 스레드·틱 |
| `mas.api.*` | MASApiServer |
| `mas.core.*` | get_settings, manufacturing_ids |

## 하위 호환
`mas.config`, `mas.environment` 등 **루트 shim** 은 짧은 import 경로용 re-export.
새 코드는 위 표의 **하위 패키지**에서 직접 import 하는 것을 권장.
"""


__version__ = "5.0.0"

from mas.domain.environment import Factory
from mas.domain.machines import WorkCenter, create_production_line
from mas.agents.base_agent import BaseAgent
from mas.agents.equipment_agent import EquipmentAgent
from mas.agents.quality_agent import QualityAgent
from mas.agents.supply_agent import SupplyAgent
from mas.agents.demand_agent import DemandAgent
from mas.agents.inventory_agent import InventoryAgent
from mas.agents.planning_agent import PlanningAgent
from mas.runtime.factory_runtime import FactoryRuntime

__all__ = [
    "Factory",
    "WorkCenter",
    "create_production_line",
    "BaseAgent",
    "EquipmentAgent",
    "QualityAgent",
    "SupplyAgent",
    "DemandAgent",
    "InventoryAgent",
    "PlanningAgent",
    "FactoryRuntime",
]
