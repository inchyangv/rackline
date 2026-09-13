#!/usr/bin/env python3
"""
Unit-economics and stress model for the first product (GPU-007). TEST_ONLY inputs.

All money is integer base units (6 dp), all rates are basis points, all rounding is floor (conservative
for the lender: income rounds down, costs round up). No floats anywhere.

    python script/gpu/unit_economics.py [scenario.json] [--markdown]

Outputs per-facility economics for the base case, the sensitivity table, and the stress matrix.
Exit 0 on success. The model is documentation support, not the production credit engine (GPU-027/035).
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

BPS = 10_000
DAYS = 365

ROOT = Path(__file__).resolve().parents[2]
DEFAULT = ROOT / "test" / "fixtures" / "gpu" / "scenarios" / "unit-economics-testonly.json"


def floor_div(a: int, b: int) -> int:
    return a // b


def ceil_div(a: int, b: int) -> int:
    return -((-a) // b)


def borrowing_base(s: dict) -> dict:
    """PIVOT §6.3 / term sheet §5 with policy haircuts."""
    gross = int(s["unpaidReceivables"])
    deductions = sum(int(v) for v in s["deductions"].values())
    net = max(0, gross - deductions)
    haircut_bps = sum(int(v) for v in s["haircutsBps"].values())
    eligible = floor_div(net * (BPS - haircut_bps), BPS)
    receivable_limit = floor_div(eligible * int(s["advanceRateBps"]), BPS)
    facility_limit = min(receivable_limit, int(s["approvedCap"]))
    room = max(0, facility_limit - int(s["outstandingDebt"]) - int(s["reservedDraws"]))
    available = max(0, min(room, int(s["concentrationHeadroom"]), int(s["vaultCash"])))
    return {
        "net": net, "eligible": eligible, "receivableLimit": receivable_limit,
        "facilityLimit": facility_limit, "facilityRoom": room, "availableDraw": available,
    }


def facility_pnl(p: dict, principal: int, tenor_days: int, expected_cash_days: int) -> dict:
    """Lender P&L for one draw held `tenor_days`, funded by LPs at `lpCostBps`."""
    interest = floor_div(principal * int(p["borrowerAprBps"]) * tenor_days, BPS * DAYS)
    origination = floor_div(principal * int(p["originationFeeBps"]), BPS)
    servicing = floor_div(principal * int(p["servicingFeeBps"]) * tenor_days, BPS * DAYS)
    revenue = interest + origination + servicing
    lp_cost = ceil_div(principal * int(p["lpCostBps"]) * tenor_days, BPS * DAYS)
    expected_loss = ceil_div(principal * int(p["expectedLossBps"]) * tenor_days, BPS * DAYS)
    conversion = ceil_div(principal * int(p["conversionCostBps"]), BPS)
    fixed = int(p["underwritingFixedCost"]) + int(p["collectionFixedCost"])
    # late cash: extra funding days beyond tenor (interest may or may not be collectable → not counted)
    late_days = max(0, expected_cash_days - tenor_days)
    late_funding = ceil_div(principal * int(p["lpCostBps"]) * late_days, BPS * DAYS)
    contribution = revenue - lp_cost - expected_loss - conversion - fixed - late_funding
    dscr_num = int(p["expectedCashAvailable"])
    dscr_den = principal + interest
    return {
        "principal": principal, "tenorDays": tenor_days, "interest": interest, "origination": origination,
        "servicing": servicing, "revenue": revenue, "lpCost": lp_cost, "expectedLoss": expected_loss,
        "conversion": conversion, "fixed": fixed, "lateFunding": late_funding, "contribution": contribution,
        "dscrBps": floor_div(dscr_num * BPS, dscr_den) if dscr_den else 0,
        "lpYieldBps": floor_div((lp_cost) * BPS * DAYS, principal * tenor_days) if principal and tenor_days else 0,
    }


def min_economic_size(p: dict, tenor_days: int, expected_cash_days: int) -> int:
    """Smallest principal (to the nearest 100 units) whose contribution is >= 0."""
    lo, hi = 0, 10**13
    while lo < hi:
        mid = (lo + hi) // 2
        if facility_pnl(p, mid, tenor_days, expected_cash_days)["contribution"] >= 0:
            hi = mid
        else:
            lo = mid + 1
    return ceil_div(lo, 100) * 100


def apply_stress(base: dict, stress: dict) -> dict:
    s = json.loads(json.dumps(base))  # deep copy
    for k, v in stress.get("set", {}).items():
        cur = s
        parts = k.split(".")
        for part in parts[:-1]:
            cur = cur[part]
        cur[parts[-1]] = v
    for k, bps in stress.get("scaleBps", {}).items():
        cur = s
        parts = k.split(".")
        for part in parts[:-1]:
            cur = cur[part]
        cur[parts[-1]] = floor_div(int(cur[parts[-1]]) * int(bps), BPS)
    for k, delta in stress.get("addDays", {}).items():
        s[k] = int(s[k]) + int(delta)
    return s


def fmt(units: int, dp: int = 6) -> str:
    sign = "-" if units < 0 else ""
    units = abs(units)
    whole, frac = divmod(units, 10**dp)
    return f"{sign}{whole:,}.{frac:0{dp}d}"[: -(dp - 2)] if dp > 2 else f"{sign}{whole:,}"


def run(scenario: dict, markdown: bool) -> dict:
    p = scenario["pricing"]
    bb = borrowing_base(scenario["borrowingBase"])
    base_draw = min(bb["availableDraw"], int(scenario["baseDraw"]))
    base = facility_pnl(p, base_draw, int(scenario["tenorDays"]), int(scenario["expectedCashDays"]))
    mes = min_economic_size(p, int(scenario["tenorDays"]), int(scenario["expectedCashDays"]))
    sens = []
    for size in scenario["sensitivitySizes"]:
        sens.append(facility_pnl(p, int(size), int(scenario["tenorDays"]), int(scenario["expectedCashDays"])))
    stresses = []
    for st in scenario["stresses"]:
        sc = apply_stress(scenario, st)
        sbb = borrowing_base(sc["borrowingBase"])
        draw = min(sbb["availableDraw"], int(sc["baseDraw"]))
        pnl = facility_pnl(sc["pricing"], base_draw, int(sc["tenorDays"]), int(sc["expectedCashDays"]))
        stresses.append({
            "name": st["name"], "availableDraw": sbb["availableDraw"], "drawAllowedNow": draw,
            "coverageBps": floor_div(sbb["eligible"] * BPS, base_draw) if base_draw else 0,
            "contribution": pnl["contribution"], "dscrBps": pnl["dscrBps"], "blocksNewDraw": sbb["availableDraw"] < base_draw,
        })
    out = {"borrowingBase": bb, "baseDraw": base_draw, "base": base, "minEconomicSize": mes, "sensitivity": sens, "stresses": stresses}
    if markdown:
        print("### Borrowing base (TEST_ONLY)\n")
        print("| net | eligible | receivable limit | facility limit | room | available draw |")
        print("| --- | --- | --- | --- | --- | --- |")
        print(f"| {fmt(bb['net'])} | {fmt(bb['eligible'])} | {fmt(bb['receivableLimit'])} | {fmt(bb['facilityLimit'])} | {fmt(bb['facilityRoom'])} | {fmt(bb['availableDraw'])} |\n")
        print(f"### Base draw {fmt(base_draw)} for {scenario['tenorDays']} days (TEST_ONLY)\n")
        print("| item | amount |")
        print("| --- | --- |")
        for k in ("interest", "origination", "servicing", "revenue", "lpCost", "expectedLoss", "conversion", "fixed", "lateFunding", "contribution"):
            print(f"| {k} | {fmt(base[k])} |")
        print(f"| DSCR | {base['dscrBps']/100:.2f}% |")
        print(f"| implied LP funding rate | {base['lpYieldBps']/100:.2f}% (≠ borrower APR {int(p['borrowerAprBps'])/100:.2f}%) |")
        print(f"\nMinimum economic draw size (contribution ≥ 0): **{fmt(mes)}**\n")
        print("### Sensitivity by draw size (TEST_ONLY)\n")
        print("| principal | revenue | LP cost | expected loss | fixed | contribution |")
        print("| --- | --- | --- | --- | --- | --- |")
        for r in sens:
            print(f"| {fmt(r['principal'])} | {fmt(r['revenue'])} | {fmt(r['lpCost'])} | {fmt(r['expectedLoss'])} | {fmt(r['fixed'])} | {fmt(r['contribution'])} |")
        print("\n### Stress matrix (TEST_ONLY)\n")
        print("| scenario | eligible coverage of base draw | available draw now | blocks new draw | contribution | DSCR |")
        print("| --- | --- | --- | --- | --- | --- |")
        for r in stresses:
            print(f"| {r['name']} | {r['coverageBps']/100:.1f}% | {fmt(r['availableDraw'])} | {'yes' if r['blocksNewDraw'] else 'no'} | {fmt(r['contribution'])} | {r['dscrBps']/100:.2f}% |")
    else:
        print(json.dumps(out, indent=2))
    return out


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    path = Path(args[0]) if args else DEFAULT
    scenario = json.loads(path.read_text())
    assert scenario.get("testOnly") is True, "scenario must be flagged testOnly"
    run(scenario, "--markdown" in argv)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
