"""
GPU-012: run test/fixtures/gpu/accounting.json against the independent reference model. Pure Python,
no database. Expectations in the fixture are hand-derived from docs/gpu/accounting.md.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hashcredit_gpu.accounting import AccountingError, Terms, VaultLedger, borrowing_base

FIXTURE = Path(__file__).resolve().parents[3] / "test" / "fixtures" / "gpu" / "accounting.json"
VECTORS = json.loads(FIXTURE.read_text())["vectors"]


def _lookup(v: VaultLedger, last_alloc: dict | None, base: dict | None, key: str):
    if key == "last_alloc":
        return last_alloc
    if key.startswith("vault."):
        _, attr, *rest = key.split(".")
        val = getattr(v, attr)
        val = val() if callable(val) else val
        for r in rest:
            val = val.get(r, 0)
        return val
    if key.startswith("base."):
        return base[key.split(".", 1)[1]]
    fid, attr = key.split(".", 1)
    if attr == "redeemable_ge" or attr == "redeemable_le":
        return v.convert_to_assets(v.shares_of.get(fid, 0))
    f = v.facilities[fid]
    return getattr(f, attr)


def _run(vector: dict) -> tuple[VaultLedger, dict | None, dict | None]:
    v = VaultLedger()
    last_alloc = None
    for step in vector["steps"]:
        op, *args = step
        if op == "deposit":
            v.deposit(args[0], args[1])
        elif op == "donate":
            v.donate(args[0])
        elif op == "open":
            v.open_facility(args[0], Terms(rate_bps=args[1]), 0)
        elif op == "draw":
            v.draw(args[0], args[1], args[2])
        elif op == "set_rate":
            v.facilities[args[0]].set_rate(args[1], args[2])
        elif op == "accrue":
            v.tick(args[1])
            v.facilities[args[0]].accrue(args[1])
        elif op == "accrue_daily":
            for d in range(1, args[1] + 1):
                v.tick(d * 86_400)
                v.facilities[args[0]].accrue(d * 86_400)
        elif op == "fee":
            v.tick(args[1])
            v.facilities[args[0]].charge_fee(args[1], args[2])
        elif op == "repay_for":
            last_alloc = v.repay_for(args[0], args[1], args[2], args[3])
        elif op == "source_receipt":
            v.source_receipt(args[0], args[1])
        elif op == "start_leg":
            v.start_leg(args[0], args[1])
        elif op == "destination_receipt":
            v.destination_receipt(args[0], args[1])
        elif op == "fund_reserve":
            v.fund_reserve(args[0], args[1])
        elif op == "impair":
            v.impair(args[0], args[1])
        elif op == "write_off":
            v.write_off(args[0], args[1])
        elif op == "recover":
            last_alloc = v.recover(args[0], args[1], args[2])
        elif op == "withdraw_expect_fail":
            shares = v.convert_to_shares(args[1])
            with pytest.raises(AccountingError):
                v.withdraw(args[0], shares)
        elif op == "check":
            assert _lookup(v, last_alloc, None, args[0]) == args[1], f"{vector['id']}: mid-step check {args[0]}"
        else:
            raise AssertionError(f"unknown op {op}")
    base = None
    if "receivables" in vector:
        b = vector["base"]
        base = borrowing_base(vector["receivables"], b["advanceRateBps"], b["approvedCap"], b["debt"], b["reserved"])
    return v, last_alloc, base


@pytest.mark.parametrize("vector", VECTORS, ids=[v["id"][:48] for v in VECTORS])
def test_vector(vector: dict):
    v, last_alloc, base = _run(vector)
    for key, expected in vector["expect"].items():
        if key.endswith("redeemable_ge"):
            assert _lookup(v, last_alloc, base, key) >= expected, key
        elif key.endswith("redeemable_le"):
            assert _lookup(v, last_alloc, base, key) <= expected, key
        elif key == "attacker.loss_gt_victim_loss":
            att_in = 1 + 1000 * 10**6
            att_out = v.convert_to_assets(v.shares_of["att"])
            vic_in = 2000 * 10**6
            vic_out = v.convert_to_assets(v.shares_of["victim"])
            assert (att_in - att_out) > (vic_in - vic_out) >= 0, (att_in - att_out, vic_in - vic_out)
        else:
            assert _lookup(v, last_alloc, base, key) == expected, f"{vector['id']}: {key}"
    # global invariants after every vector
    assert v.nav() == v.cash + v.performing_principal() + v.performing_interest() - v.impairment
    assert all(f.principal >= 0 and f.unpaid_interest >= 0 and f.fees >= 0 for f in v.facilities.values())
    assert sum(v.shares_of.values()) == v.total_shares
    # LP claims never exceed NAV beyond the single virtual asset unit (dust favours the vault)
    assert sum(v.convert_to_assets(s) for s in v.shares_of.values()) <= v.nav() + v.virtual_assets


def test_evidence_never_touches_the_ledger():
    """There is no ledger entry point that takes a proof; only cash allocation mutates debt."""
    mutators = {n for n in dir(VaultLedger) if not n.startswith("_") and callable(getattr(VaultLedger, n))}
    assert not any("proof" in n or "evidence" in n for n in mutators)
    v = VaultLedger()
    v.deposit("lp", 10**9)
    v.open_facility("f", Terms(1000), 0)
    v.draw("f", 0, 5 * 10**8)
    before = (v.nav(), v.total_legal_debt())
    bb = borrowing_base([{"unpaid": 10**9, "state": "RECOGNIZED", "nativeStatus": "PROOF_READY"}], 5000, 10**9, 0, 0)
    assert bb["eligible"] == 0 and (v.nav(), v.total_legal_debt()) == before


def test_write_off_rejects_impairment_beyond_exposure_and_repay_zero():
    v = VaultLedger()
    v.deposit("lp", 10**9)
    v.open_facility("f", Terms(1000), 0)
    v.draw("f", 0, 10**8)
    with pytest.raises(AccountingError):
        v.impair("f", 10**8 + 1)
    with pytest.raises(AccountingError):
        v.repay_for("f", 1, 0, "third_party")
    with pytest.raises(AccountingError):
        v.facilities["f"].accrue(-1)
