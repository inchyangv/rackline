"""GPU-014: golden settlement/reconciliation fixtures must be reproduced by the reference reconciler."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from hashcredit_gpu.reconciliation import reconcile

FIXTURES = sorted((Path(__file__).resolve().parents[3] / "test" / "fixtures" / "gpu" / "settlements").glob("s-*.json"))


@pytest.mark.parametrize("path", FIXTURES, ids=[p.stem for p in FIXTURES])
def test_golden_fixture(path: Path):
    fx = json.loads(path.read_text())
    ledger = reconcile(fx["observations"], fx["facilities"])
    got = ledger.summary()
    exp = fx["expect"]
    for key in exp:
        assert got[key] == exp[key], f"{fx['id']}: {key}\n got={got[key]}\n exp={exp[key]}"
    # invariants: every settlement's allocations never exceed its source amount; consumed ids unique
    for sid, s in ledger.settlements.items():
        assert sum(s["allocations"].values()) <= s["sourceAmount"], sid
    assert len(ledger.consumed_source_events) == len(set(ledger.consumed_source_events))


def test_ids_are_not_merge_keys():
    """Same provider event ref on a different account or chain is a different economic event."""
    base = json.loads(FIXTURES[0].read_text())
    fac = base["facilities"]
    obs = [
        {"observationId": "x1", "source": "API", "trust": "OBSERVED", "economicEventId": "p/acct-A/OBLIGATION/inv-1", "eventType": "OBLIGATION", "account": "p:acct-A", "obligationRef": "inv-1", "asset": "usdc:11155111", "amount": 100, "revision": 1},
        {"observationId": "x2", "source": "API", "trust": "OBSERVED", "economicEventId": "p/acct-B/OBLIGATION/inv-1", "eventType": "OBLIGATION", "account": "p:acct-B", "obligationRef": "inv-1", "asset": "usdc:11155111", "amount": 100, "revision": 1},
        {"observationId": "x3", "source": "API", "trust": "OBSERVED", "economicEventId": "p/acct-A/OBLIGATION/chain:3:1:0:0", "eventType": "OBLIGATION", "account": "p:acct-A", "obligationRef": "inv-1-mainnet", "asset": "usdc:1", "amount": 100, "revision": 1},
    ]
    ledger = reconcile(obs, fac)
    assert len(ledger.economic_events) == 3 and len(ledger.receivables) == 3
