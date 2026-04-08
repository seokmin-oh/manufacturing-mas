"""
표준 제조 컨텍스트(Phase A) — Factory.get_snapshot() 딕셔너리 위에 얹는 얇은 계층.

에이전트가 직접 이 타입을 쓸 필요는 없고, 어댑터로 "같은 키 체계·시간축"을
문서/외부 연동용으로 노출할 때 사용한다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .plant_data_model import DEFAULT_LINE_ID, DEFAULT_SITE_ID, PLANT_SCHEMA_VERSION


@dataclass(frozen=True)
class PlantRef:
    schema_version: str
    site_id: str
    line_id: str
    snapshot_kind: str


@dataclass(frozen=True)
class TemporalRef:
    logical_clock_cycle: int
    sim_time_sec: Optional[float]
    display_clock: Optional[str]


@dataclass
class FactorySummary:
    avg_oee: Optional[float]
    fg_stock: int
    total_produced: int
    scrap_count: int
    rework_count: int
    shift: str


@dataclass
class ManufacturingContext:
    plant: PlantRef
    temporal: TemporalRef
    summary: FactorySummary
    station_ids: Tuple[str, ...]
    material_skus: Tuple[str, ...]
    meta: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["station_ids"] = list(self.station_ids)
        d["material_skus"] = list(self.material_skus)
        return d


def from_factory_snapshot(snap: Dict[str, Any]) -> ManufacturingContext:
    """원 스냅샷에서 컨텍스트를 만든다. plant 블록이 없으면 기본 식별자로 채운다."""
    ph = snap.get("plant") if isinstance(snap.get("plant"), dict) else {}
    plant = PlantRef(
        schema_version=str(ph.get("schema_version") or PLANT_SCHEMA_VERSION),
        site_id=str(ph.get("site_id") or DEFAULT_SITE_ID),
        line_id=str(ph.get("line_id") or DEFAULT_LINE_ID),
        snapshot_kind=str(ph.get("snapshot_kind") or "simulation"),
    )
    temporal = TemporalRef(
        logical_clock_cycle=int(snap.get("cycle") or ph.get("logical_clock_cycle") or 0),
        sim_time_sec=_f(ph.get("sim_time_sec")),
        display_clock=snap.get("clock") if isinstance(snap.get("clock"), str) else None,
    )
    stations = snap.get("stations") or {}
    station_ids = tuple(sorted(stations.keys())) if isinstance(stations, dict) else tuple()
    mats = snap.get("materials") or {}
    skus: List[str] = []
    if isinstance(mats, dict):
        skus = sorted(mats.keys())

    summary = FactorySummary(
        avg_oee=_f(snap.get("avg_oee")),
        fg_stock=int(snap.get("fg_stock") or 0),
        total_produced=int(snap.get("total_produced") or 0),
        scrap_count=int(snap.get("scrap_count") or 0),
        rework_count=int(snap.get("rework_count") or 0),
        shift=str(snap.get("shift") or "-"),
    )
    meta: Dict[str, Any] = {
        "orders_n": len(snap["orders"]) if isinstance(snap.get("orders"), list) else 0,
        "wip_buffers_n": len(snap["wip"]) if isinstance(snap.get("wip"), list) else 0,
    }
    return ManufacturingContext(
        plant=plant,
        temporal=temporal,
        summary=summary,
        station_ids=station_ids,
        material_skus=tuple(skus),
        meta=meta,
    )


def _f(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None
