"""
플랜트 데이터 계층 (시뮬 전용, 현장 연동 없음).

목적: OPC·MES에 붙였을 때와 같은 **식별자·태그·품질 플래그** 형태로 스냅샷을 맞춰,
     나중에 히스토리안·대시보드·에이전트가 동일 스키마를 쓰도록 한다.

- `tag_id`: Site/Line/Station/Sensor 형태의 계층 문자열 (가독성용; ISA-95 풀 패스는 아님)
- `data_quality`: 시뮬에서는 GOOD 고정, 추후 STALE/INVALID 등 확장
"""

from __future__ import annotations

from typing import Any, Dict

PLANT_SCHEMA_VERSION = "2.0"

DEFAULT_SITE_ID = "SITE-KR-01"
DEFAULT_PLANT_ID = "PLANT-BRAKE-MAIN"
DEFAULT_LINE_ID = "LINE-BRAKE-01"
DEFAULT_CELL_ID = "CELL-LINE-01"


def make_sensor_tag_id(
    station_id: str,
    sensor_name: str,
    *,
    site_id: str = DEFAULT_SITE_ID,
    line_id: str = DEFAULT_LINE_ID,
) -> str:
    safe = sensor_name.replace(" ", "_")
    return f"{site_id}/{line_id}/{station_id}/{safe}"


def make_resource_id(
    station_id: str,
    *,
    site_id: str = DEFAULT_SITE_ID,
    line_id: str = DEFAULT_LINE_ID,
) -> str:
    return f"{site_id}/{line_id}/{station_id}"


def enrich_sensor_row(
    station_id: str,
    sensor_name: str,
    row: Dict[str, Any],
    *,
    cycle: int,
    sim_time_sec: float,
    site_id: str = DEFAULT_SITE_ID,
    line_id: str = DEFAULT_LINE_ID,
) -> Dict[str, Any]:
    out = dict(row)
    out["tag_id"] = make_sensor_tag_id(
        station_id, sensor_name, site_id=site_id, line_id=line_id
    )
    out["sample_seq"] = int(cycle)
    out["observed_at_sim_sec"] = round(float(sim_time_sec), 3)
    out["data_quality"] = "GOOD"
    return out


def enrich_station_sensors(
    station_id: str,
    sensors: Dict[str, Any],
    *,
    cycle: int,
    sim_time_sec: float,
    site_id: str = DEFAULT_SITE_ID,
    line_id: str = DEFAULT_LINE_ID,
) -> Dict[str, Any]:
    return {
        name: enrich_sensor_row(
            station_id,
            name,
            row if isinstance(row, dict) else {"value": row},
            cycle=cycle,
            sim_time_sec=sim_time_sec,
            site_id=site_id,
            line_id=line_id,
        )
        for name, row in sensors.items()
    }


def plant_header(
    *,
    sim_time_sec: float,
    cycle: int,
    site_id: str = DEFAULT_SITE_ID,
    plant_id: str = DEFAULT_PLANT_ID,
    line_id: str = DEFAULT_LINE_ID,
    cell_id: str = DEFAULT_CELL_ID,
) -> Dict[str, Any]:
    return {
        "schema_version": PLANT_SCHEMA_VERSION,
        "site_id": site_id,
        "plant_id": plant_id,
        "line_id": line_id,
        "cell_id": cell_id,
        "snapshot_kind": "simulation",
        "sim_time_sec": round(float(sim_time_sec), 3),
        "logical_clock_cycle": int(cycle),
    }
