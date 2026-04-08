"""
표준 제조 컨텍스트 — 시스템 1급 데이터 계약 (Contract v2).

`Factory.get_snapshot()` 딕셔너리를 `ManufacturingContext` 로 변환한다.
에이전트·외부 연동은 가능한 한 **본 타입의 식별자·시간축·KPI 슬라이스**만 참조하도록
점진적으로 옮긴다 (raw 스냅샷 직접 의존 축소).

계약 버전: `CONTEXT_CONTRACT_VERSION` — 하위 호환 깨질 때만 올린다.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from .plant_data_model import (
    DEFAULT_CELL_ID,
    DEFAULT_LINE_ID,
    DEFAULT_PLANT_ID,
    DEFAULT_SITE_ID,
    PLANT_SCHEMA_VERSION,
)


# ── 계약 메타 ─────────────────────────────────────────────────────

CONTEXT_CONTRACT_VERSION = "2.0"


@dataclass(frozen=True)
class IdentifierContract:
    """현장·시뮬 공통 식별자 축 (고정 키). LOT 등 미수집 시 빈 튜플."""

    site_id: str
    plant_id: str
    line_id: str
    cell_id: str
    station_ids: Tuple[str, ...]
    equipment_ids: Tuple[str, ...]
    material_skus: Tuple[str, ...]
    lot_ids: Tuple[str, ...]
    order_ids: Tuple[str, ...]
    shift_code: str


@dataclass(frozen=True)
class TemporalAxes:
    """시간 축 분리: 논리 사이클 / 시뮬 시각 / 비즈니스·수집 시각(실장비)."""

    logical_clock_cycle: int
    sim_time_sec: Optional[float]
    event_time_utc_iso: Optional[str]
    ingest_time_utc_iso: Optional[str]
    display_clock: Optional[str]


@dataclass
class KpiSliceBundle:
    """KPI를 공정·설비·품번·시프트 등 슬라이스로 명시 (집계 단위 고정)."""

    line: Dict[str, Any]
    by_station: Dict[str, Dict[str, Any]]
    by_shift: Dict[str, Any]
    by_sku: Dict[str, Dict[str, Any]]


@dataclass(frozen=True)
class PlantRef:
    """스냅샷 plant 헤더와 동형 — 하위·API 호환."""

    schema_version: str
    site_id: str
    plant_id: str
    line_id: str
    cell_id: str
    snapshot_kind: str


@dataclass(frozen=True)
class TemporalRef:
    """호환 별칭 — TemporalAxes 와 동일 필드명 사용."""

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
    """
    제조 표준 컨텍스트 (1급 계약).

    - `contract_version`: `CONTEXT_CONTRACT_VERSION`
    - `identifiers` / `temporal` / `kpi_slices`: 필수 축
    - `plant` / `summary`: 기존 모니터링·문서 호환
    """

    contract_version: str
    identifiers: IdentifierContract
    temporal: TemporalAxes
    kpi_slices: KpiSliceBundle
    plant: PlantRef
    summary: FactorySummary
    meta: Dict[str, Any] = field(default_factory=dict)

    @property
    def station_ids(self) -> Tuple[str, ...]:
        return self.identifiers.station_ids

    @property
    def material_skus(self) -> Tuple[str, ...]:
        return self.identifiers.material_skus

    @property
    def temporal_legacy(self) -> TemporalRef:
        """이전 코드용 얇은 시간 뷰 (이벤트·수집 시각 제외)."""
        return TemporalRef(
            logical_clock_cycle=self.temporal.logical_clock_cycle,
            sim_time_sec=self.temporal.sim_time_sec,
            display_clock=self.temporal.display_clock,
        )

    def to_dict(self) -> Dict[str, Any]:
        """API·JSON 직렬화 — 계약 전체를 한 번에 노출."""
        id_ = self.identifiers
        return {
            "contract_version": self.contract_version,
            "identifiers": {
                "site_id": id_.site_id,
                "plant_id": id_.plant_id,
                "line_id": id_.line_id,
                "cell_id": id_.cell_id,
                "station_ids": list(id_.station_ids),
                "equipment_ids": list(id_.equipment_ids),
                "material_skus": list(id_.material_skus),
                "lot_ids": list(id_.lot_ids),
                "order_ids": list(id_.order_ids),
                "shift_code": id_.shift_code,
            },
            "temporal": asdict(self.temporal),
            "kpi_slices": {
                "line": dict(self.kpi_slices.line),
                "by_station": {k: dict(v) for k, v in self.kpi_slices.by_station.items()},
                "by_shift": dict(self.kpi_slices.by_shift),
                "by_sku": {k: dict(v) for k, v in self.kpi_slices.by_sku.items()},
            },
            "plant": asdict(self.plant),
            "summary": asdict(self.summary),
            "meta": dict(self.meta),
        }


def from_factory_snapshot(
    snap: Dict[str, Any],
    *,
    ingest_time_utc_iso: Optional[str] = None,
) -> ManufacturingContext:
    """
    원 스냅샷에서 `ManufacturingContext` 를 만든다.

    Parameters
    ----------
    snap
        `Factory.get_snapshot()` 결과 또는 동형 dict.
    ingest_time_utc_iso
        어댑터가 컨텍스트를 생성한 시각(UTC ISO8601). 미입력 시 None (순수 시뮬).
    """
    ph = snap.get("plant") if isinstance(snap.get("plant"), dict) else {}

    site_id = str(ph.get("site_id") or DEFAULT_SITE_ID)
    plant_id = str(ph.get("plant_id") or DEFAULT_PLANT_ID)
    line_id = str(ph.get("line_id") or DEFAULT_LINE_ID)
    cell_id = str(ph.get("cell_id") or DEFAULT_CELL_ID)
    schema_ver = str(ph.get("schema_version") or PLANT_SCHEMA_VERSION)
    snapshot_kind = str(ph.get("snapshot_kind") or "simulation")

    stations = snap.get("stations") or {}
    station_ids: Tuple[str, ...] = tuple()
    equipment_ids: List[str] = []
    by_station_kpi: Dict[str, Dict[str, Any]] = {}

    if isinstance(stations, dict):
        station_ids = tuple(sorted(stations.keys()))
        for sid in station_ids:
            row = stations[sid] if isinstance(stations[sid], dict) else {}
            rid = row.get("resource_id")
            equipment_ids.append(str(rid) if rid else str(sid))
            by_station_kpi[sid] = _station_kpi_slice(row)

    mats = snap.get("materials") or {}
    skus: List[str] = []
    by_sku: Dict[str, Dict[str, Any]] = {}
    if isinstance(mats, dict):
        skus = sorted(mats.keys())
        for name, mrow in mats.items():
            if isinstance(mrow, dict):
                by_sku[name] = {
                    "stock": mrow.get("stock"),
                    "days_supply": mrow.get("days_supply"),
                    "needs_reorder": mrow.get("needs_reorder"),
                    "sku": mrow.get("sku") or name,
                }

    orders = snap.get("orders") if isinstance(snap.get("orders"), list) else []
    order_ids: List[str] = []
    for o in orders:
        if isinstance(o, dict) and o.get("id") is not None:
            order_ids.append(str(o["id"]))

    raw_lots = snap.get("lot_ids") or ph.get("lot_ids") or []
    if isinstance(raw_lots, (list, tuple)):
        lot_ids = tuple(str(x) for x in raw_lots)
    else:
        lot_ids = tuple()

    shift_code = str(snap.get("shift") or "-")

    identifiers = IdentifierContract(
        site_id=site_id,
        plant_id=plant_id,
        line_id=line_id,
        cell_id=cell_id,
        station_ids=station_ids,
        equipment_ids=tuple(equipment_ids),
        material_skus=tuple(skus),
        lot_ids=lot_ids,
        order_ids=tuple(order_ids),
        shift_code=shift_code,
    )

    logical = int(snap.get("cycle") or ph.get("logical_clock_cycle") or 0)
    sim_sec = _f(ph.get("sim_time_sec"))
    event_iso = ph.get("event_time_utc_iso")
    if event_iso is None:
        event_iso = snap.get("event_time_utc_iso")
    event_iso = str(event_iso) if event_iso else None

    temporal = TemporalAxes(
        logical_clock_cycle=logical,
        sim_time_sec=sim_sec,
        event_time_utc_iso=event_iso,
        ingest_time_utc_iso=ingest_time_utc_iso,
        display_clock=snap.get("clock") if isinstance(snap.get("clock"), str) else None,
    )

    line_kpi = {
        "avg_oee": _f(snap.get("avg_oee")),
        "fg_stock": int(snap.get("fg_stock") or 0),
        "total_produced": int(snap.get("total_produced") or 0),
        "scrap_count": int(snap.get("scrap_count") or 0),
        "rework_count": int(snap.get("rework_count") or 0),
        "total_demand": snap.get("total_demand"),
        "total_delivered": snap.get("total_delivered"),
    }

    by_shift = {
        "shift_code": shift_code,
        "shift_skill": _f(snap.get("shift_skill")),
    }

    kpi_slices = KpiSliceBundle(
        line=line_kpi,
        by_station=by_station_kpi,
        by_shift=by_shift,
        by_sku=by_sku,
    )

    plant = PlantRef(
        schema_version=schema_ver,
        site_id=site_id,
        plant_id=plant_id,
        line_id=line_id,
        cell_id=cell_id,
        snapshot_kind=snapshot_kind,
    )

    summary = FactorySummary(
        avg_oee=_f(snap.get("avg_oee")),
        fg_stock=int(snap.get("fg_stock") or 0),
        total_produced=int(snap.get("total_produced") or 0),
        scrap_count=int(snap.get("scrap_count") or 0),
        rework_count=int(snap.get("rework_count") or 0),
        shift=shift_code,
    )

    meta: Dict[str, Any] = {
        "orders_n": len(orders),
        "wip_buffers_n": len(snap["wip"]) if isinstance(snap.get("wip"), list) else 0,
        "plant_schema_version": schema_ver,
    }

    return ManufacturingContext(
        contract_version=CONTEXT_CONTRACT_VERSION,
        identifiers=identifiers,
        temporal=temporal,
        kpi_slices=kpi_slices,
        plant=plant,
        summary=summary,
        meta=meta,
    )


def _station_kpi_slice(station_row: Dict[str, Any]) -> Dict[str, Any]:
    oee = station_row.get("oee")
    out: Dict[str, Any] = {
        "station_id": station_row.get("station_id"),
        "oee": oee if isinstance(oee, dict) else None,
        "yield": station_row.get("yield"),
        "state": station_row.get("state"),
    }
    return {k: v for k, v in out.items() if v is not None}


def _f(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None
