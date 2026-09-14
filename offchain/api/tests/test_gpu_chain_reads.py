"""A borrowing-base quote cannot advertise cash the vault cannot release."""
from types import SimpleNamespace

import pytest

from hashcredit_api.gpu.product.chain import ContractReads


@pytest.mark.parametrize("base,cash,expected,reason,state", [
    (500, 200, "200", None, 3), (200, 500, "200", None, 3),
    (500, 0, "0", "INSUFFICIENT_VAULT_CASH", 3), (0, 500, "0", "NO_ELIGIBLE_DRAW", 3),
    # the facility state gate precedes eligibility: DEFAULTED (6) and CLOSED_WITH_LOSS (10) never quote a draw
    (500, 500, "0", "FACILITY_NOT_ACTIVE", 6), (500, 500, "0", "FACILITY_NOT_ACTIVE", 10),
])
def test_available_draw_is_bounded_by_canonical_vault_cash(base, cash, expected, reason, state):
    token, wallet = "0x" + "11" * 20, "0x" + "22" * 20
    reader = ContractReads.__new__(ContractReads)
    reader.settings = SimpleNamespace(deployment_id="release", chain_id=102031)
    reader.manifest = {"asset": {"address": token}, "contracts": {
        "CreditFacilityManager": "0x" + "33" * 20, "RepaymentRouter": "0x" + "44" * 20}}
    reader.check = lambda meta: 100
    reads = []

    def call(contract, method, block, *args):
        reads.append((contract, method, block))
        assert block == 100
        return {"facilityInfo": [None, wallet, None, None, None, None, state, True],
                "facility": [None, [102031, token], 0, 0, 0], "legalDebtAt": 0,
                "evaluateDraw": [None] * 6 + [base], "availableCash": cash}[method]

    reader.call = call
    session = SimpleNamespace(get=lambda *args: SimpleNamespace(onchain_id="0x" + "55" * 32))
    meta = SimpleNamespace(freshness="FRESH", canonicalBlock=SimpleNamespace(timestamp=1700000000))
    result = reader.facility(session, meta, SimpleNamespace(facility_id="facility"), wallet)
    assert result["availableDraw"] == expected
    assert result["drawBlockedReason"] == reason
    assert (("LendingVaultV2", "availableCash", 100) in reads) == (state == 3)  # no quote is computed behind the state gate
