"""
시나리오 결과 비교 유틸리티 — 여러 시나리오 실행 결과를 나란히 비교한다.

사용법:
  python compare_results.py results/normal_*.json results/equipment_failure_*.json
  python compare_results.py results/*.json
"""

import sys
import os
import json
import argparse
from pathlib import Path

os.environ["PYTHONUNBUFFERED"] = "1"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def load_result(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def format_val(val, fmt=""):
    if val is None:
        return "-"
    if isinstance(val, float):
        if fmt == "pct":
            return f"{val:.1%}"
        return f"{val:.2f}"
    return str(val)


def _status_icon(val, good_threshold, warn_threshold, higher_is_better=True):
    """값에 따른 상태 표시 (+ 양호 / ! 주의 / x 불량)."""
    if higher_is_better:
        if val >= good_threshold:
            return "+"
        elif val >= warn_threshold:
            return "!"
        return "x"
    else:
        if val <= good_threshold:
            return "+"
        elif val <= warn_threshold:
            return "!"
        return "x"


def compare(files: list, output_file: str = None):
    results = []
    for f in files:
        try:
            data = load_result(f)
            data["_file"] = Path(f).name
            results.append(data)
        except Exception as e:
            print(f"  [경고] {f} 로드 실패 — {e}")

    if not results:
        print("  비교할 결과 파일이 없습니다.")
        return

    metrics_groups = [
        ("[시스템]", [
            ("총 사이클",      lambda r: r.get("total_cycles", 0),                              None),
            ("총 이벤트",      lambda r: r.get("total_events", 0),                              None),
            ("CNP 협상",       lambda r: r.get("cnp_count", 0),                                 None),
            ("실행 시간(초)",  lambda r: r.get("uptime_sec", 0),                                None),
        ]),
        ("[재고·납기]", [
            ("최종 재고",      lambda r: r.get("warehouse", {}).get("final_stock", 0),           None),
            ("안전재고(SS)",   lambda r: r.get("warehouse", {}).get("safety_stock", 0),          None),
            ("납기 달성률",    lambda r: format_val(r.get("warehouse", {}).get("service_level", 0), "pct"),
                                                                                                 "sl"),
            ("총 출하",        lambda r: r.get("warehouse", {}).get("total_shipped", 0),         None),
            ("총 요청",        lambda r: r.get("warehouse", {}).get("total_requested", 0),       None),
            ("SS 위반 횟수",   lambda r: r.get("warehouse", {}).get("ss_breach_count", 0),       "breach"),
        ]),
        ("[통신]", [
            ("브로커 메시지",  lambda r: r.get("broker", {}).get("total_published", 0),          None),
            ("평균 지연(ms)",  lambda r: format_val(r.get("broker", {}).get("avg_latency_ms", 0)), None),
            ("실패(DLQ)",      lambda r: r.get("broker", {}).get("total_dlq", 0),               "dlq"),
        ]),
        ("[AI 판단]", [
            ("AI 도구 호출",   lambda r: r.get("tools", {}).get("total_calls", 0),              None),
            ("규칙 기반 판단", lambda r: r.get("decision_router", {}).get("rule_decisions", 0),  None),
            ("LLM 기반 판단",  lambda r: r.get("decision_router", {}).get("llm_decisions", 0),  None),
        ]),
    ]

    n = len(results)
    col_width = 20
    label_width = 18

    total_w = label_width + 4 + (col_width + 1) * n

    lines = []
    lines.append(f"\n{'═' * total_w}")
    lines.append(f"  시나리오 결과 비교 ({n}건)")
    lines.append(f"{'═' * total_w}")

    header = f"  {'KPI 항목':<{label_width}} │"
    for r in results:
        name = r.get("scenario", {}).get("name", r["_file"])
        if len(name) > col_width - 2:
            name = name[:col_width - 4] + ".."
        header += f" {name:^{col_width - 1}}│"
    lines.append(header)
    lines.append(f"  {'─' * (total_w - 2)}")

    for group_name, group_metrics in metrics_groups:
        lines.append(f"  {group_name}")
        for label, extractor, tag in group_metrics:
            row = f"    {label:<{label_width - 2}} │"
            for r in results:
                val = extractor(r)
                val_str = str(val)

                icon = ""
                if tag == "sl":
                    raw_sl = r.get("warehouse", {}).get("service_level", 0)
                    icon = _status_icon(raw_sl, 0.95, 0.90) + " "
                elif tag == "breach":
                    raw_b = r.get("warehouse", {}).get("ss_breach_count", 0)
                    icon = _status_icon(raw_b, 0, 3, higher_is_better=False) + " "
                elif tag == "dlq":
                    raw_d = r.get("broker", {}).get("total_dlq", 0)
                    icon = _status_icon(raw_d, 0, 2, higher_is_better=False) + " "

                cell = f"{icon}{val_str}"
                row += f" {cell:>{col_width - 2}} │"
            lines.append(row)
        lines.append(f"  {'─' * (total_w - 2)}")

    winner_analysis = analyze_winners(results, metrics_groups)
    if winner_analysis:
        lines.append(f"\n  분석 결과:")
        for line in winner_analysis:
            lines.append(f"    {line}")

    lines.append(f"\n{'═' * total_w}")

    output = "\n".join(lines)
    print(output)

    if output_file:
        with open(output_file, "w", encoding="utf-8") as f:
            f.write(output)
        print(f"\n  비교 결과 저장: {output_file}")

    json_data = []
    for r in results:
        json_data.append({
            "scenario": r.get("scenario", {}).get("name", r["_file"]),
            "file": r["_file"],
            "cycles": r.get("total_cycles", 0),
            "events": r.get("total_events", 0),
            "cnp": r.get("cnp_count", 0),
            "final_stock": r.get("warehouse", {}).get("final_stock", 0),
            "safety_stock": r.get("warehouse", {}).get("safety_stock", 0),
            "service_level": r.get("warehouse", {}).get("service_level", 0),
            "ss_breaches": r.get("warehouse", {}).get("ss_breach_count", 0),
            "total_shipped": r.get("warehouse", {}).get("total_shipped", 0),
            "tool_calls": r.get("tools", {}).get("total_calls", 0),
        })

    return json_data


def analyze_winners(results, metrics_groups):
    if len(results) < 2:
        return []

    analysis = []

    sls = [(r.get("scenario", {}).get("name", r["_file"]),
            r.get("warehouse", {}).get("service_level", 0)) for r in results]
    best_sl = max(sls, key=lambda x: x[1])
    worst_sl = min(sls, key=lambda x: x[1])
    if best_sl[1] != worst_sl[1]:
        analysis.append(f"납기율 최고: {best_sl[0]} ({best_sl[1]:.1%}) | "
                        f"최저: {worst_sl[0]} ({worst_sl[1]:.1%})")

    cnps = [(r.get("scenario", {}).get("name", r["_file"]),
             r.get("cnp_count", 0)) for r in results]
    most_cnp = max(cnps, key=lambda x: x[1])
    if most_cnp[1] > 0:
        analysis.append(f"CNP 협상 최다: {most_cnp[0]} ({most_cnp[1]}회) — 위기 대응 빈도 지표")

    breaches = [(r.get("scenario", {}).get("name", r["_file"]),
                 r.get("warehouse", {}).get("ss_breach_count", 0)) for r in results]
    worst_breach = max(breaches, key=lambda x: x[1])
    if worst_breach[1] > 0:
        analysis.append(f"[주의] 안전재고 위반 최다: {worst_breach[0]} ({worst_breach[1]}회)")

    stocks = [(r.get("scenario", {}).get("name", r["_file"]),
               r.get("warehouse", {}).get("final_stock", 0)) for r in results]
    lowest_stock = min(stocks, key=lambda x: x[1])
    highest_stock = max(stocks, key=lambda x: x[1])
    if lowest_stock[1] != highest_stock[1]:
        analysis.append(f"최종 재고 범위: {lowest_stock[0]}({lowest_stock[1]}개) ~ "
                        f"{highest_stock[0]}({highest_stock[1]}개)")

    return analysis


def main():
    parser = argparse.ArgumentParser(
        description="Multi-Agent 시나리오 결과 비교",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""예시:
  python compare_results.py results/normal_*.json results/equipment_failure_*.json
  python compare_results.py results/*.json
  python compare_results.py results/*.json --output comparison.txt
""",
    )
    parser.add_argument("files", nargs="+", help="비교할 결과 JSON 파일(들)")
    parser.add_argument("--output", "-o", type=str, default=None, help="비교 결과 텍스트 파일 저장 경로")

    args = parser.parse_args()
    compare(args.files, args.output)


if __name__ == "__main__":
    main()
