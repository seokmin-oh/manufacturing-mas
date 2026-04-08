from mas.integration import (
    SampleERPConnector,
    SampleMESConnector,
    SampleQMSConnector,
    build_connector_payload_bundle,
    map_erp_sales_order,
    map_mes_work_order,
    map_qms_inspection_result,
    sample_bundle,
)


def test_mapping_functions_normalize_external_payloads():
    mes = map_mes_work_order(
        {
            "workOrderId": "WO-100",
            "lineCode": "L1",
            "materialCode": "PAD-A",
            "plannedQty": 120,
            "releasedQty": 80,
            "status": "RELEASED",
            "plannedStartTs": "2026-04-08T09:00:00Z",
            "plannedEndTs": "2026-04-08T18:00:00Z",
        }
    )
    erp = map_erp_sales_order(
        {
            "salesOrderNo": "SO-9",
            "customerCode": "HMC",
            "itemCode": "PAD-A",
            "orderQty": 500,
            "requestedDeliveryDate": "2026-04-10",
            "priority": "URGENT",
        }
    )
    qms = map_qms_inspection_result(
        {
            "inspectionLotId": "ILOT-7",
            "lotId": "LOT-7",
            "itemCode": "PAD-A",
            "judgement": "FAIL",
            "defectCount": 2,
            "defects": ["BURR", "CRACK"],
            "inspectedAt": "2026-04-08T10:00:00Z",
        }
    )

    assert mes["work_order_id"] == "WO-100"
    assert erp["priority"] == "URGENT"
    assert qms["defects"] == ["BURR", "CRACK"]


def test_sample_connectors_build_payload_bundle():
    mes = SampleMESConnector(
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
    )
    erp = SampleERPConnector(
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
    )
    qms = SampleQMSConnector(
        [
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
    )

    bundle = sample_bundle(
        mes_connector=mes,
        erp_connector=erp,
        qms_connector=qms,
        line_id="L1",
        lot_id="LOT-7",
    )
    assert bundle["mes_work_orders"][0]["work_order_id"] == "WO-100"
    assert bundle["erp_sales_orders"][0]["order_id"] == "SO-9"
    assert bundle["qms_inspections"][0]["result"] == "PASS"

    direct = build_connector_payload_bundle(
        mes_rows=mes.fetch_raw_work_orders("L1"),
        erp_rows=erp.fetch_raw_sales_orders(),
        qms_rows=qms.fetch_raw_inspections("LOT-7"),
    )
    assert direct == bundle
