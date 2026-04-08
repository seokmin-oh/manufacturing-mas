"""표준 제조 컨텍스트 어댑터 및 계약 v2."""

from mas.domain import CONTEXT_CONTRACT_VERSION, from_factory_snapshot
from mas.domain.manufacturing_context import IdentifierContract, TemporalAxes
from mas.domain.plant_data_model import DEFAULT_LINE_ID, DEFAULT_SITE_ID


def test_from_factory_snapshot_minimal():
    snap = {
        "plant": {
            "schema_version": "2.0",
            "site_id": DEFAULT_SITE_ID,
            "plant_id": "PLANT-X",
            "line_id": DEFAULT_LINE_ID,
            "cell_id": "CELL-01",
            "snapshot_kind": "simulation",
            "sim_time_sec": 12.5,
            "logical_clock_cycle": 3,
        },
        "cycle": 3,
        "clock": "08:00:12",
        "shift": "주간A",
        "avg_oee": 0.82,
        "fg_stock": 10,
        "total_produced": 100,
        "scrap_count": 1,
        "rework_count": 0,
        "stations": {"WC-01": {}, "WC-02": {}},
        "materials": {"STEEL": {"stock": 5}},
        "orders": [],
        "wip": [],
    }
    ctx = from_factory_snapshot(snap)
    assert ctx.contract_version == CONTEXT_CONTRACT_VERSION
    assert ctx.plant.site_id == DEFAULT_SITE_ID
    assert ctx.plant.plant_id == "PLANT-X"
    assert ctx.plant.cell_id == "CELL-01"
    assert ctx.temporal.logical_clock_cycle == 3
    assert ctx.temporal.sim_time_sec == 12.5
    assert ctx.temporal.event_time_utc_iso is None
    assert ctx.temporal.ingest_time_utc_iso is None
    assert ctx.summary.avg_oee == 0.82
    assert set(ctx.station_ids) == {"WC-01", "WC-02"}
    assert "STEEL" in ctx.material_skus
    assert ctx.identifiers.shift_code == "주간A"
    assert ctx.kpi_slices.by_shift["shift_code"] == "주간A"
    d = ctx.to_dict()
    assert d["contract_version"] == CONTEXT_CONTRACT_VERSION
    assert d["summary"]["fg_stock"] == 10
    assert "identifiers" in d and "temporal" in d and "kpi_slices" in d
    assert d["identifiers"]["plant_id"] == "PLANT-X"
    assert d["identifiers"]["lot_ids"] == []


def test_from_factory_snapshot_empty_plant_defaults():
    ctx = from_factory_snapshot({"cycle": 0, "stations": {}})
    assert ctx.plant.schema_version
    assert ctx.temporal.logical_clock_cycle == 0
    assert isinstance(ctx.identifiers, IdentifierContract)
    assert isinstance(ctx.temporal, TemporalAxes)


def test_contract_fixed_identifier_keys():
    """site/plant/line/cell/station/equipment/SKU/order/shift 축이 모두 존재."""
    snap = {
        "plant": {
            "schema_version": "2.0",
            "site_id": "S1",
            "plant_id": "P1",
            "line_id": "L1",
            "cell_id": "C1",
            "sim_time_sec": 0.0,
            "logical_clock_cycle": 1,
        },
        "cycle": 1,
        "shift": "야간",
        "stations": {
            "WC-01": {
                "station_id": "WC-01",
                "resource_id": "S1/L1/WC-01",
                "oee": {"oee": 0.7},
                "yield": 0.99,
                "state": "RUN",
            },
        },
        "materials": {"SKU-A": {"sku": "SKU-A", "stock": 3, "days_supply": 2.0}},
        "orders": [{"id": "ORD-1", "remaining": 5}],
        "lot_ids": ["LOT-99"],
        "avg_oee": 0.7,
        "fg_stock": 0,
        "total_produced": 0,
        "scrap_count": 0,
        "rework_count": 0,
        "wip": [],
    }
    ctx = from_factory_snapshot(snap)
    ids = ctx.identifiers
    assert ids.site_id == "S1"
    assert ids.plant_id == "P1"
    assert ids.line_id == "L1"
    assert ids.cell_id == "C1"
    assert ids.station_ids == ("WC-01",)
    assert ids.equipment_ids == ("S1/L1/WC-01",)
    assert ids.material_skus == ("SKU-A",)
    assert ids.lot_ids == ("LOT-99",)
    assert ids.order_ids == ("ORD-1",)
    assert ids.shift_code == "야간"
    assert "WC-01" in ctx.kpi_slices.by_station
    assert "SKU-A" in ctx.kpi_slices.by_sku


def test_temporal_event_and_ingest_iso():
    snap = {
        "plant": {
            "schema_version": "2.0",
            "site_id": DEFAULT_SITE_ID,
            "line_id": DEFAULT_LINE_ID,
            "sim_time_sec": 1.0,
            "logical_clock_cycle": 0,
            "event_time_utc_iso": "2026-04-08T10:00:00+00:00",
        },
        "cycle": 0,
        "stations": {},
        "materials": {},
        "orders": [],
        "wip": [],
    }
    ctx = from_factory_snapshot(snap, ingest_time_utc_iso="2026-04-08T10:00:01+00:00")
    assert ctx.temporal.event_time_utc_iso == "2026-04-08T10:00:00+00:00"
    assert ctx.temporal.ingest_time_utc_iso == "2026-04-08T10:00:01+00:00"


def test_temporal_legacy_view():
    snap = {
        "plant": {
            "schema_version": "2.0",
            "site_id": DEFAULT_SITE_ID,
            "line_id": DEFAULT_LINE_ID,
            "sim_time_sec": 5.0,
            "logical_clock_cycle": 2,
        },
        "cycle": 2,
        "clock": "09:00:00",
        "stations": {},
        "materials": {},
        "orders": [],
        "wip": [],
    }
    ctx = from_factory_snapshot(snap)
    leg = ctx.temporal_legacy
    assert leg.logical_clock_cycle == 2
    assert leg.sim_time_sec == 5.0
    assert leg.display_clock == "09:00:00"


def test_factory_snapshot_integration():
    """실제 Factory 한 사이클 스냅샷이 계약을 만족."""
    from mas.domain import Factory

    f = Factory()
    f.run_cycle()
    snap = f.get_snapshot()
    ctx = from_factory_snapshot(snap)
    assert ctx.contract_version == CONTEXT_CONTRACT_VERSION
    assert len(ctx.identifiers.station_ids) == 6
    assert ctx.identifiers.plant_id
    assert ctx.identifiers.cell_id
    assert ctx.kpi_slices.line.get("avg_oee") is not None or snap.get("avg_oee") is not None
