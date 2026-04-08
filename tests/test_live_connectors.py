import json

from mas.integration import (
    FileERPConnector,
    FileMESConnector,
    FileQMSConnector,
    RestERPConnector,
    RestMESConnector,
    RestQMSConnector,
)
from mas.integration import live_connectors as live


def test_file_connectors_load_and_map_payloads(tmp_path):
    mes_path = tmp_path / "mes.json"
    mes_path.write_text(
        json.dumps(
            [
                {
                    "workOrderId": "WO-100",
                    "lineCode": "L1",
                    "materialCode": "PAD-A",
                    "plannedQty": 120,
                    "releasedQty": 80,
                    "status": "RELEASED",
                }
            ]
        ),
        encoding="utf-8",
    )
    erp_path = tmp_path / "erp.json"
    erp_path.write_text(
        json.dumps(
            [
                {
                    "salesOrderNo": "SO-9",
                    "customerCode": "HMC",
                    "itemCode": "PAD-A",
                    "orderQty": 500,
                    "requestedDeliveryDate": "2026-04-10",
                    "priority": "URGENT",
                }
            ]
        ),
        encoding="utf-8",
    )
    qms_path = tmp_path / "qms.json"
    qms_path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "inspectionLotId": "ILOT-7",
                        "lotId": "LOT-7",
                        "itemCode": "PAD-A",
                        "judgement": "PASS",
                        "defectCount": 0,
                        "defects": [],
                        "inspectedAt": "2026-04-08T10:00:00Z",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )

    mes = FileMESConnector(str(mes_path))
    erp = FileERPConnector(str(erp_path))
    qms = FileQMSConnector(str(qms_path))

    assert mes.fetch_mapped_work_orders("L1")[0]["work_order_id"] == "WO-100"
    assert erp.fetch_mapped_sales_orders()[0]["order_id"] == "SO-9"
    assert qms.fetch_mapped_inspections("LOT-7")[0]["result"] == "PASS"


def test_rest_connectors_load_and_map_payloads(monkeypatch):
    payloads = {
        "http://mes.local/work-orders?line_id=L1": [
            {
                "workOrderId": "WO-100",
                "lineCode": "L1",
                "materialCode": "PAD-A",
                "plannedQty": 120,
                "releasedQty": 80,
                "status": "RELEASED",
            }
        ],
        "http://erp.local/sales-orders": [
            {
                "salesOrderNo": "SO-9",
                "customerCode": "HMC",
                "itemCode": "PAD-A",
                "orderQty": 500,
                "requestedDeliveryDate": "2026-04-10",
                "priority": "URGENT",
            }
        ],
        "http://qms.local/inspections?lot_id=LOT-7": {
            "items": [
                {
                    "inspectionLotId": "ILOT-7",
                    "lotId": "LOT-7",
                    "itemCode": "PAD-A",
                    "judgement": "FAIL",
                    "defectCount": 2,
                    "defects": ["BURR"],
                    "inspectedAt": "2026-04-08T10:00:00Z",
                }
            ]
        },
    }

    class _FakeResponse:
        def __init__(self, url):
            self.url = url

        def read(self):
            return json.dumps(payloads[self.url]).encode("utf-8")

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(live, "urlopen", lambda url: _FakeResponse(url))

    mes = RestMESConnector("http://mes.local")
    erp = RestERPConnector("http://erp.local")
    qms = RestQMSConnector("http://qms.local")

    assert mes.fetch_mapped_work_orders("L1")[0]["sku"] == "PAD-A"
    assert erp.fetch_mapped_sales_orders()[0]["priority"] == "URGENT"
    assert qms.fetch_mapped_inspections("LOT-7")[0]["defects"] == ["BURR"]

