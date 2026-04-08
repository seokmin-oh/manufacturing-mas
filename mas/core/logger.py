"""
제조 MAS 시뮬레이션 전용 로거.
Andon 보드, 실시간 시계열 테이블, 재고 대시보드, SS 추이.
"""

from typing import List, Optional, Tuple

quiet = False


class C:
    HD = "\033[95m"
    BL = "\033[94m"
    CY = "\033[96m"
    GR = "\033[92m"
    YL = "\033[93m"
    RD = "\033[91m"
    WH = "\033[97m"
    BD = "\033[1m"
    DM = "\033[2m"
    RS = "\033[0m"
    MG = "\033[35m"


AGENT_COLORS = {
    "EA": C.CY, "QA": C.GR, "PA": C.YL, "SA": C.BL,
    "DA": C.MG, "IA": C.HD, "SYS": C.WH,
    "FA": C.CY, "VQA": C.GR, "OA": C.YL, "LA": C.BL,
}

AGENT_NAMES_KR = {
    "EA": "설비", "QA": "품질", "PA": "계획", "SA": "공급",
    "DA": "수요", "IA": "재고", "SYS": "시스템",
}


def _ac(aid: str) -> str:
    return AGENT_COLORS.get(aid, C.RS)


# ── 배너 / 구획 ─────────────────────────────────────────────────────

def print_banner(title: str, subtitle: str, orders_info: str):
    w = 80
    print(f"\n{C.BD}{C.CY}{'═' * w}")
    print(f"  {title}")
    print(f"  {subtitle}")
    print(f"  {orders_info}")
    print(f"{'═' * w}{C.RS}\n")


def print_andon(press_state: str, weld_state: str, inspect_mode: str, speed: int, stock: int = 0, ss: int = 0):
    s_bar = "█" * (speed // 10) + "░" * (10 - speed // 10)
    sc = C.GR if stock >= ss else C.RD
    stock_icon = "[OK]" if stock >= ss else "[NG]"
    print(f"  {C.BD}┌─ 안돈 보드 (ANDON) ────────────────────────────────────────────────────────┐{C.RS}")
    print(f"  {C.BD}│{C.RS}  [{C.CY}프레스{C.RS}] ──→ [{C.CY}용접{C.RS}] ──→ [{C.GR}비전검사{C.RS}] ──→ [{C.HD}완제품창고{C.RS}] ──→ 출하   {C.BD}│{C.RS}")
    print(f"  {C.BD}│{C.RS}   ● {press_state:<10}   ● {weld_state:<10}   ● {inspect_mode:<10}   {stock_icon}{sc}재고:{stock:3d}{C.RS}/{C.YL}안전재고:{ss}{C.RS}  {C.BD}│{C.RS}")
    print(f"  {C.BD}│{C.RS}   라인속도: {speed}% {s_bar}                                                {C.BD}│{C.RS}")
    print(f"  {C.BD}└───────────────────────────────────────────────────────────────────────────────┘{C.RS}")


def print_time_header(clock: str, title: str):
    print(f"\n  {C.BD}{C.DM}── {clock} {title} {'─' * max(0, 60 - len(title) - len(clock))}{C.RS}")


def print_phase(num, title: str):
    w = 76
    print(f"\n{C.BD}{C.HD}{'─' * w}")
    print(f"  Phase {num}: {title}")
    print(f"{'─' * w}{C.RS}")


# ── 에이전트 로그 ────────────────────────────────────────────────────

def agent_log(aid: str, msg: str, level: str = "INFO"):
    if quiet:
        return
    c = _ac(aid)
    icons = {
        "INFO": f"{C.DM}(i){C.RS}", "ALERT": f"{C.RD}(!){C.RS}",
        "THINK": f"{C.YL}(*){C.RS}", "ACTION": f"{C.GR}(>){C.RS}",
        "NEGOTIATE": f"{C.HD}(~){C.RS}", "DECISION": f"{C.YL}(*){C.RS}",
        "SUCCESS": f"{C.GR}(v){C.RS}", "ERROR": f"{C.RD}(x){C.RS}",
        "ALARM_L1": f"{C.YL}[L1]{C.RS}", "ALARM_L2": f"{C.RD}[L2]{C.RS}",
        "ALARM_L3": f"{C.RD}{C.BD}[L3]{C.RS}",
    }
    icon = icons.get(level, f"{C.DM}(.){C.RS}")
    print(f"  {c}{C.BD}[{aid:>3}]{C.RS} {icon} {msg}")


def agent_thought(aid: str, thought: str):
    if quiet:
        return
    c = _ac(aid)
    print(f"  {c}{C.BD}[{aid:>3}]{C.RS} {C.YL}(*){C.RS} \"{thought}\"")


def message_flow(sender: str, receiver: str, intent: str, summary: str):
    if quiet:
        return
    sc = _ac(sender)
    rc = _ac(receiver)
    s_kr = AGENT_NAMES_KR.get(sender, sender)
    r_kr = AGENT_NAMES_KR.get(receiver, receiver)
    intent_kr = {
        "CFP": "입찰요청", "PROPOSE": "제안", "ACCEPT_PROPOSAL": "수락",
        "REJECT_PROPOSAL": "거절", "ALERT": "경보", "DEMAND_CHANGE": "수요변경",
        "STOCK_ALERT": "재고경보", "PLAN_UPDATE": "계획변경",
    }.get(intent, f"→ {intent}")
    print(f"        {sc}{C.BD}{s_kr}{C.RS} ──{intent_kr}──> "
          f"{rc}{C.BD}{r_kr}{C.RS}  {C.DM}{summary}{C.RS}")


# ── 시계열 테이블 (재고 열 추가) ──────────────────────────────────────

def vib_bar(value: float, max_val: float = 6.0, width: int = 6) -> str:
    filled = min(width, round(value / max_val * width))
    return "▰" * filled + "▱" * (width - filled)


def sparkline(data: List[float], min_val: float = 1.0, max_val: float = 5.0) -> str:
    blocks = " ▁▂▃▄▅▆▇█"
    chars = []
    for v in data[-25:]:
        norm = max(0.0, min(1.0, (v - min_val) / max(max_val - min_val, 0.01)))
        chars.append(blocks[int(norm * 8)])
    return "".join(chars)


def print_table_header():
    hdr = (
        f"  {C.BD}  시간    사이클 │ 진동     유온 │"
        f" 판정 공정능력 │ 생산  수율 │"
        f" 재고 안전재고 납기율{C.RS}"
    )
    sep = (
        f"  {C.DM}────────────────┼──────────────────┼"
        f"──────────────────┼───────────┼"
        f"──────────────────────{C.RS}"
    )
    print(hdr)
    print(sep)


def print_compact_row(
    clock: str, cycle: int,
    vib: float, vib_status: str, oil_temp: float,
    verdict: str, cpk_worst: float,
    produced: int, target: int, yield_rate: float,
    stock: int, ss: int, service_level: float,
):
    vc = C.GR if vib_status == "NORMAL" else (C.YL if vib_status == "WARNING" else C.RD)
    bar = vib_bar(vib)

    vdc = C.GR if verdict == "양품" else (C.YL if verdict == "보류" else C.RD)

    if cpk_worst >= 50:
        cpk_s = f"{C.DM} ─ {C.RS}"
    elif cpk_worst >= 1.33:
        cpk_s = f"{C.GR}OK {C.RS}"
    elif cpk_worst >= 1.0:
        cpk_s = f"{C.YL}{cpk_worst:.1f}{C.RS}"
    else:
        cpk_s = f"{C.RD}{cpk_worst:.1f}{C.RS}"

    yc = C.GR if yield_rate >= 95 else (C.YL if yield_rate >= 85 else C.RD)
    stc = C.GR if stock >= ss else C.RD
    slc = C.GR if service_level >= 0.95 else (C.YL if service_level >= 0.90 else C.RD)

    print(
        f"  {C.DM}{clock}{C.RS} C{cycle:02d} │"
        f" {vc}{vib:4.1f}{C.RS} {bar} {oil_temp:3.0f}° │"
        f" {vdc}{verdict:<2}{C.RS} {cpk_s} │"
        f" {produced:3d}/{target} {yc}{yield_rate:4.0f}%{C.RS} │"
        f" {stc}{stock:3d}{C.RS}/{C.YL}{ss}{C.RS} {slc}{service_level:4.0%}{C.RS}"
    )


def print_table_break():
    print(
        f"  {C.DM}─────────────┼─────────────────┼"
        f"───────────┼───────────┼"
        f"──────────────{C.RS}"
    )


# ── 이벤트 배너 ─────────────────────────────────────────────────────

def print_event_banner(agent_id: str, message: str):
    c = _ac(agent_id)
    print(f"  {c}{C.BD}══════ [{agent_id}] {message} ══════{C.RS}")


# ── 확장 블록 ────────────────────────────────────────────────────────

def print_expanded_header(clock: str, cycle: int, serial: str):
    print(f"\n  {C.BD}{'═' * 80}{C.RS}")
    print(f"  {C.BD}[{clock}] Cycle {cycle:02d}{C.RS}  {C.DM}{serial}{C.RS}")
    print(f"  {C.BD}{'═' * 80}{C.RS}")


def print_agent_block(aid: str, lines: List[str]):
    c = _ac(aid)
    for i, line in enumerate(lines):
        prefix = f"   {c}{C.BD}{aid:<3}{C.RS} │" if i == 0 else f"       {C.DM}│{C.RS}"
        print(f"{prefix} {line}")


def print_alert_banner():
    print(f"  {C.RD}{C.BD}{'▓' * 80}{C.RS}")


# ── SS 추이 스파크라인 ───────────────────────────────────────────────

def print_ss_trend(ss_history: List[int], stock_history: List[int]):
    if len(ss_history) < 3:
        return
    ss_sl = sparkline([float(x) for x in ss_history], 0, max(max(ss_history) + 10, 60))
    st_sl = sparkline([float(x) for x in stock_history], 0, max(max(stock_history) + 10, 80))
    stock_icon = "[OK]" if stock_history[-1] >= ss_history[-1] else "[NG]"
    print(f"\n  {C.BD}완제품 재고 추이{C.RS}")
    print(f"  {C.GR}재고     {C.RS}: {C.GR}{st_sl}{C.RS}  {stock_history[0]}개 → {C.BD}{stock_history[-1]}개{C.RS} {stock_icon}")
    print(f"  {C.YL}안전재고 {C.RS}: {C.YL}{ss_sl}{C.RS}  {ss_history[0]}개 → {C.BD}{ss_history[-1]}개{C.RS}")


def print_sparkline_trend(title: str, data: List[float], warn_val: float):
    if len(data) < 3:
        return
    sl = sparkline(data, min(data) - 0.3, max(max(data), warn_val) + 0.3)
    fc = C.GR if data[-1] < warn_val else C.RD
    status = "[정상]" if data[-1] < warn_val else "[경고]"
    print(f"\n  {C.BD}{title}{C.RS}")
    print(f"  {C.CY}{sl}{C.RS}  {data[0]:.2f} → {fc}{C.BD}{data[-1]:.2f}{C.RS} mm/s  {status}")
    print(f"  {C.DM}{'─' * len(sl)}{C.RS}  {C.YL}임계치 {warn_val} mm/s{C.RS}")


# ── 기존 유지 함수 ──────────────────────────────────────────────────

def print_table(title: str, rows: List[Tuple[str, str]]):
    w = 56
    print(f"\n  {C.BD}{title}{C.RS}")
    print(f"  {'─' * w}")
    for label, value in rows:
        print(f"  {label:<36} {C.BD}{value}{C.RS}")
    print(f"  {'─' * w}")


def print_score_table(proposals: list):
    if quiet:
        return
    print(f"\n  {C.BD}  CNP 제안 평가표 (가중 점수){C.RS}")
    print(f"  {'─' * 72}")
    hdr = f"  {'에이전트':<10} {'품질':>9} {'납기':>9} {'비용':>9} {'안전':>9} {'총점':>9}"
    print(f"  {C.BD}{hdr}{C.RS}")
    wt = f"  {'(가중치)':<10} {'x0.30':>9} {'x0.25':>9} {'x0.25':>9} {'x0.20':>9}"
    print(f"  {C.DM}{wt}{C.RS}")
    print(f"  {'─' * 72}")
    for p in proposals:
        sc = p["scores"]
        c = _ac(p["agent"])
        name_kr = AGENT_NAMES_KR.get(p["agent"], p["agent"])
        print(f"  {c}{C.BD}{name_kr:<8}{C.RS}"
              f" {sc.get('quality', 0):>8.2f}  {sc.get('delivery', 0):>8.2f}"
              f"  {sc.get('cost', 0):>8.2f}  {sc.get('safety', 0):>8.2f}"
              f"  {C.BD}{p['total']:>8.3f}{C.RS}")
    print(f"  {'─' * 72}")


def print_message_json(msg_dict: dict):
    if quiet:
        return
    sender = msg_dict["header"]["sender"]
    receiver = msg_dict["header"]["receiver"]
    intent = msg_dict.get("intent", "")
    sc = _ac(sender)
    lines = [
        f"        {C.DM}┌─ Message ──────────────────────────────────────┐{C.RS}",
        f"        {C.DM}│{C.RS}  sender: {sc}{sender}{C.RS}, receiver: {_ac(receiver)}{receiver}{C.RS}, intent: {C.BD}{intent}{C.RS}",
    ]
    body = msg_dict.get("body", {})
    for k, v in body.items():
        if k == "summary":
            continue
        vs = str(v)
        if len(vs) > 48:
            vs = vs[:48] + "..."
        lines.append(f"        {C.DM}│{C.RS}  {k}: {vs}")
    lines.append(f"        {C.DM}└────────────────────────────────────────────────┘{C.RS}")
    print("\n".join(lines))


def print_summary_separator():
    print()
