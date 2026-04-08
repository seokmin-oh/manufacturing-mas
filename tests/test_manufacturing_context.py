"""표준 제조 컨텍스트 어댑터."""

from mas.domain import from_factory_snapshot
from mas.domain.plant_data_model import DEFAULT_LINE_ID, DEFAULT_SITE_ID


def test_from_factory_snapshot_minimal():
    snap = {
        "plant": {
            "schema_version": "1.0",
            "site_id": DEFAULT_SITE_ID,
            "line_id": DEFAULT_LINE_ID,
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
    assert ctx.plant.site_id == DEFAULT_SITE_ID
    assert ctx.temporal.logical_clock_cycle == 3
    assert ctx.summary.avg_oee == 0.82
    assert set(ctx.station_ids) == {"WC-01", "WC-02"}
    assert "STEEL" in ctx.material_skus
    d = ctx.to_dict()
    assert d["summary"]["fg_stock"] == 10


def test_from_factory_snapshot_empty_plant_defaults():
    ctx = from_factory_snapshot({"cycle": 0, "stations": {}})
    assert ctx.plant.schema_version
    assert ctx.temporal.logical_clock_cycle == 0
