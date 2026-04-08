from mas.adapters.base import (
    ERPOrderAdapter,
    MaintenanceHistoryAdapter,
    MESAdapter,
    QualityInspectionAdapter,
    SOPDocumentAdapter,
    SensorAdapter,
)
from mas.integration import (
    MockERPOrderAdapter,
    MockMaintenanceHistoryAdapter,
    MockMESAdapter,
    MockQualityInspectionAdapter,
    MockSOPDocumentAdapter,
    MockSensorAdapter,
)


def test_mock_adapters_satisfy_protocols():
    sensor = MockSensorAdapter({"WC-01": {"temp": 32}})
    mes = MockMESAdapter({"L1": [{"wo_id": "WO-1"}]})
    erp = MockERPOrderAdapter([{"order_id": "SO-1"}])
    quality = MockQualityInspectionAdapter({"LOT-1": [{"result": "PASS"}]})
    maintenance = MockMaintenanceHistoryAdapter({"EQ-1": [{"event": "repair"}]})
    sop = MockSOPDocumentAdapter([{"title": "Brake SOP", "body": "inspection before run"}])

    assert isinstance(sensor, SensorAdapter)
    assert isinstance(mes, MESAdapter)
    assert isinstance(erp, ERPOrderAdapter)
    assert isinstance(quality, QualityInspectionAdapter)
    assert isinstance(maintenance, MaintenanceHistoryAdapter)
    assert isinstance(sop, SOPDocumentAdapter)

    assert sensor.fetch_station_tags("WC-01")["temp"] == 32
    assert mes.fetch_work_orders("L1")[0]["wo_id"] == "WO-1"
    assert erp.fetch_open_orders()[0]["order_id"] == "SO-1"
    assert quality.fetch_recent_inspections("LOT-1")[0]["result"] == "PASS"
    assert maintenance.fetch_recent_events("EQ-1")[0]["event"] == "repair"
    assert sop.search_snippets("inspection")[0]["title"] == "Brake SOP"
