"""
Independent accounting reference model (GPU-012). Pure integers, no floats, no DB.

Semantics (docs/gpu/accounting.md):
  * Interest accrues on principal only, simple, ACT/365, per rate segment. The accumulator keeps the exact
    numerator `principal * rate_bps * seconds` so the result does not depend on how often `accrue()` is
    called; units are obtained by floor division (lender-conservative), and payments subtract exact units.
  * Unpaid interest is preserved separately from principal. Capitalization is OFF unless the terms say so.
  * Repayment waterfall: fees -> unpaid interest -> principal -> excess (excess is borrower money).
  * Only cash received at the destination and allocated to the facility reduces debt. Source receipts,
    in-flight legs, proofs, claimable balances never do.
  * Legal debt (what the borrower owes) and NAV book value (what LPs own) are different ledgers. Impairment
    and write-off change NAV, never legal debt; recoveries after write-off are cash in and NAV up.
  * Vault NAV = cash owned by LPs + performing principal + performing accrued interest receivable
    - impairment. Borrower reserve, borrower refundable excess and source escrow are NOT in NAV.
  * Shares use a virtual offset (ERC-4626 style) so a first-depositor donation cannot steal from later LPs.
"""

from __future__ import annotations

from dataclasses import dataclass, field

BPS = 10_000
YEAR = 365 * 86_400
DENOM = BPS * YEAR  # accumulator denominator: 1 unit of interest == DENOM accumulator units


class AccountingError(Exception):
    pass


# ----------------------------------------------------------------------------- facility ledger


@dataclass
class Terms:
    rate_bps: int
    capitalize_unpaid_interest: bool = False
    test_only: bool = True


@dataclass
class RateSegment:
    start: int  # unix seconds (inclusive)
    rate_bps: int


@dataclass
class FacilityLedger:
    facility_id: str
    terms: Terms
    opened_at: int
    principal: int = 0
    fees: int = 0
    interest_accum: int = 0  # numerator: sum(principal * rate_bps * seconds)
    last_accrual_at: int = 0
    segments: list[RateSegment] = field(default_factory=list)
    written_off_principal: int = 0
    written_off_interest: int = 0
    impaired: bool = False
    accrual_frozen: bool = False  # non-accrual after write-off; contractual default interest is out of scope
    history: list[dict] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.segments:
            self.segments = [RateSegment(self.opened_at, self.terms.rate_bps)]
        self.last_accrual_at = self.opened_at

    # --- views
    @property
    def unpaid_interest(self) -> int:
        return self.interest_accum // DENOM

    @property
    def legal_debt(self) -> int:
        """What the borrower owes, independent of NAV treatment (write-off does not forgive)."""
        return self.principal + self.unpaid_interest + self.fees

    def current_rate(self, at: int) -> int:
        rate = self.segments[0].rate_bps
        for seg in self.segments:
            if seg.start <= at:
                rate = seg.rate_bps
        return rate

    # --- mutations
    def unpaid_interest_at(self, at: int) -> int:
        """Interest as of `at` without mutating (pending accrual included)."""
        if self.accrual_frozen or at <= self.last_accrual_at:
            return self.unpaid_interest
        accum = self.interest_accum
        t = self.last_accrual_at
        while t < at:
            rate = self.current_rate(t)
            nxt = at
            for seg in self.segments:
                if t < seg.start < nxt:
                    nxt = seg.start
            accum += self.principal * rate * (nxt - t)
            t = nxt
        return accum // DENOM

    def accrue(self, to_ts: int) -> None:
        if to_ts < self.last_accrual_at:
            raise AccountingError("accrual cannot go backwards")
        if self.accrual_frozen:
            self.last_accrual_at = to_ts
            return
        t = self.last_accrual_at
        while t < to_ts:
            rate = self.current_rate(t)
            # next boundary: next segment start after t, or to_ts
            nxt = to_ts
            for seg in self.segments:
                if t < seg.start < nxt:
                    nxt = seg.start
            self.interest_accum += self.principal * rate * (nxt - t)
            t = nxt
        self.last_accrual_at = to_ts

    def set_rate(self, at: int, rate_bps: int) -> None:
        """Rate changes apply forward only; the past is accrued at the old rate first."""
        self.accrue(at)
        if any(seg.start == at for seg in self.segments):
            self.segments = [seg for seg in self.segments if seg.start != at]
        self.segments.append(RateSegment(at, rate_bps))
        self.segments.sort(key=lambda s: s.start)
        self.history.append({"at": at, "op": "set_rate", "rate_bps": rate_bps})

    def borrow(self, at: int, amount: int) -> None:
        if amount <= 0:
            raise AccountingError("amount must be positive")
        self.accrue(at)
        if self.terms.capitalize_unpaid_interest:
            cap = self.unpaid_interest
            self.principal += cap
            self.interest_accum -= cap * DENOM
        self.principal += amount
        self.history.append({"at": at, "op": "borrow", "amount": amount})

    def charge_fee(self, at: int, amount: int) -> None:
        self.accrue(at)
        self.fees += amount
        self.history.append({"at": at, "op": "fee", "amount": amount})

    def allocate_repayment(self, at: int, amount: int) -> dict[str, int]:
        """Destination cash allocated to this facility: fees -> interest -> principal -> excess."""
        if amount <= 0:
            raise AccountingError("amount must be positive")
        self.accrue(at)
        remaining = amount
        fees = min(remaining, self.fees)
        self.fees -= fees
        remaining -= fees
        interest = min(remaining, self.unpaid_interest)
        self.interest_accum -= interest * DENOM
        remaining -= interest
        principal = min(remaining, self.principal)
        self.principal -= principal
        remaining -= principal
        alloc = {"fees": fees, "interest": interest, "principal": principal, "excess": remaining}
        self.history.append({"at": at, "op": "repay", **alloc})
        return alloc


# ----------------------------------------------------------------------------- vault / LP ledger


@dataclass
class VaultLedger:
    """LP-owned book. Borrower-owned cash (reserve, refundable excess) and source escrow are tracked apart."""

    virtual_shares: int = 1_000  # OZ-style decimals offset: +1000 virtual shares, +1 virtual asset
    virtual_assets: int = 1
    clock: int = 0  # last time-bearing operation; NAV is evaluated as of the clock
    cash: int = 0  # LP-owned loan currency held by the vault
    total_shares: int = 0
    shares_of: dict[str, int] = field(default_factory=dict)
    facilities: dict[str, FacilityLedger] = field(default_factory=dict)
    impairment_by: dict[str, int] = field(default_factory=dict)  # NAV reduction per performing facility
    borrower_reserve: dict[str, int] = field(default_factory=dict)  # borrower-owned, not NAV
    borrower_refundable: dict[str, int] = field(default_factory=dict)  # excess repayments owed back, not NAV
    source_escrow: dict[str, int] = field(default_factory=dict)  # cash at source (collection), not NAV
    in_flight: dict[str, int] = field(default_factory=dict)  # legs in transit, not NAV
    journal: list[dict] = field(default_factory=list)

    # --- NAV
    def performing_principal(self) -> int:
        return sum(f.principal for f in self.facilities.values() if not f.impaired)

    def performing_interest(self) -> int:
        return sum(f.unpaid_interest_at(self.clock) for f in self.facilities.values() if not f.impaired)

    def tick(self, at: int) -> None:
        if at < self.clock:
            raise AccountingError("clock cannot go backwards")
        self.clock = at

    @property
    def impairment(self) -> int:
        return sum(v for fid, v in self.impairment_by.items() if not self.facilities[fid].impaired)

    def nav(self) -> int:
        return self.cash + self.performing_principal() + self.performing_interest() - self.impairment

    def total_legal_debt(self) -> int:
        return sum(f.principal + f.unpaid_interest_at(self.clock) + f.fees for f in self.facilities.values())

    # --- shares (virtual offset)
    def convert_to_shares(self, assets: int) -> int:
        return assets * (self.total_shares + self.virtual_shares) // (self.nav() + self.virtual_assets)

    def convert_to_assets(self, shares: int) -> int:
        return shares * (self.nav() + self.virtual_assets) // (self.total_shares + self.virtual_shares)

    def deposit(self, lp: str, assets: int) -> int:
        shares = self.convert_to_shares(assets)
        if shares <= 0:
            raise AccountingError("deposit too small for one share")
        self.cash += assets
        self.total_shares += shares
        self.shares_of[lp] = self.shares_of.get(lp, 0) + shares
        self.journal.append({"op": "deposit", "lp": lp, "assets": assets, "shares": shares})
        return shares

    def withdraw(self, lp: str, shares: int) -> int:
        if shares > self.shares_of.get(lp, 0):
            raise AccountingError("insufficient shares")
        assets = self.convert_to_assets(shares)
        if assets > self.cash:
            raise AccountingError("insufficient vault cash (withdrawal limited to available cash)")
        self.cash -= assets
        self.total_shares -= shares
        self.shares_of[lp] -= shares
        self.journal.append({"op": "withdraw", "lp": lp, "assets": assets, "shares": shares})
        return assets

    def donate(self, assets: int) -> None:
        """Tokens sent directly to the vault: LP-owned cash, never a borrower repayment."""
        self.cash += assets
        self.journal.append({"op": "donation", "assets": assets})

    # --- lending
    def open_facility(self, facility_id: str, terms: Terms, at: int) -> FacilityLedger:
        f = FacilityLedger(facility_id, terms, at)
        self.facilities[facility_id] = f
        return f

    def draw(self, facility_id: str, at: int, amount: int) -> None:
        f = self.facilities[facility_id]
        if amount > self.cash:
            raise AccountingError("insufficient vault cash")
        self.tick(at)
        f.borrow(at, amount)
        self.cash -= amount
        self.journal.append({"op": "draw", "facility": facility_id, "amount": amount})

    # --- cash pipeline (source -> in-flight -> destination -> allocation)
    def source_receipt(self, settlement_id: str, amount: int) -> None:
        """Cash arrived in the source escrow. Collection only: debt and NAV unchanged."""
        self.source_escrow[settlement_id] = self.source_escrow.get(settlement_id, 0) + amount
        self.journal.append({"op": "source_receipt", "settlement": settlement_id, "amount": amount})

    def start_leg(self, settlement_id: str, amount: int) -> None:
        if amount > self.source_escrow.get(settlement_id, 0):
            raise AccountingError("leg exceeds source escrow balance")
        self.source_escrow[settlement_id] -= amount
        self.in_flight[settlement_id] = self.in_flight.get(settlement_id, 0) + amount
        self.journal.append({"op": "leg_start", "settlement": settlement_id, "amount": amount})

    def destination_receipt(self, settlement_id: str, amount: int) -> None:
        """Loan currency arrived at the destination: now (and only now) it can be allocated."""
        if amount > self.in_flight.get(settlement_id, 0):
            raise AccountingError("destination receipt exceeds in-flight amount")
        self.in_flight[settlement_id] -= amount
        self.cash += amount  # held pending allocation; allocation decides ownership below
        self.journal.append({"op": "destination_receipt", "settlement": settlement_id, "amount": amount})

    def repay_for(self, facility_id: str, at: int, amount: int, payer: str = "destination") -> dict[str, int]:
        """
        Allocate destination cash to one facility. `payer="third_party"` models a direct repayFor by anyone
        (cash comes with the call). Excess is owed back to the borrower and never applied to another facility.
        """
        f = self.facilities[facility_id]
        self.tick(at)
        if payer == "third_party":
            self.cash += amount
        alloc = f.allocate_repayment(at, amount)
        if alloc["excess"]:
            self.cash -= alloc["excess"]
            self.borrower_refundable[facility_id] = self.borrower_refundable.get(facility_id, 0) + alloc["excess"]
        self.journal.append({"op": "repay_for", "facility": facility_id, **alloc})
        return alloc

    # --- borrower reserve (borrower-owned cash, first-loss use)
    def fund_reserve(self, facility_id: str, amount: int) -> None:
        self.borrower_reserve[facility_id] = self.borrower_reserve.get(facility_id, 0) + amount
        self.journal.append({"op": "reserve_fund", "facility": facility_id, "amount": amount})

    # --- losses
    def impair(self, facility_id: str, amount: int) -> None:
        """NAV recognizes an expected loss; legal debt is unchanged."""
        f = self.facilities[facility_id]
        already = self.impairment_by.get(facility_id, 0)
        if amount > f.principal + f.unpaid_interest - already:
            raise AccountingError("impairment exceeds performing exposure")
        self.impairment_by[facility_id] = already + amount
        self.journal.append({"op": "impair", "facility": facility_id, "amount": amount})

    def write_off(self, facility_id: str, at: int) -> dict[str, int]:
        """Apply borrower reserve first, then write the remainder off NAV. Legal debt persists."""
        f = self.facilities[facility_id]
        self.tick(at)
        f.accrue(at)
        reserve = self.borrower_reserve.get(facility_id, 0)
        used = min(reserve, f.legal_debt)
        alloc = {"fees": 0, "interest": 0, "principal": 0, "excess": 0}
        if used:
            self.borrower_reserve[facility_id] -= used
            self.cash += used
            alloc = f.allocate_repayment(at, used)
        loss_principal = f.principal
        loss_interest = f.unpaid_interest
        # remove from the performing book; the facility's own impairment is released (no double count)
        self.impairment_by.pop(facility_id, None)
        f.impaired = True
        f.accrual_frozen = True
        f.written_off_principal += loss_principal
        f.written_off_interest += loss_interest
        self.journal.append({"op": "write_off", "facility": facility_id, "reserve_used": used, "principal": loss_principal, "interest": loss_interest})
        return {"reserve_used": used, "loss_principal": loss_principal, "loss_interest": loss_interest}

    def recover(self, facility_id: str, at: int, amount: int) -> dict[str, int]:
        """Cash recovered after write-off: reduces the still-outstanding legal debt, NAV up by cash."""
        f = self.facilities[facility_id]
        self.tick(at)
        self.cash += amount
        alloc = f.allocate_repayment(at, amount)
        if alloc["excess"]:
            self.cash -= alloc["excess"]
            self.borrower_refundable[facility_id] = self.borrower_refundable.get(facility_id, 0) + alloc["excess"]
        self.journal.append({"op": "recovery", "facility": facility_id, **alloc})
        return alloc


# ----------------------------------------------------------------------------- borrowing base helpers


def borrowing_base(receivables: list[dict], advance_rate_bps: int, approved_cap: int, debt: int, reserved: int) -> dict[str, int]:
    """
    Eligible = sum(unpaid) over receivables whose evidence is native-accepted/consumed and whose
    state is not PAID/CANCELLED/WRITTEN_OFF. Proof-only or paid receivables contribute 0.
    """
    eligible = 0
    for r in receivables:
        if r["nativeStatus"] not in ("NATIVE_ACCEPTED", "CONSUMED"):
            continue
        if r["state"] in ("PAID", "CANCELLED", "WRITTEN_OFF"):
            continue
        eligible += int(r["unpaid"])
    limit = min(eligible * advance_rate_bps // BPS, approved_cap)
    room = max(0, limit - debt - reserved)
    return {"eligible": eligible, "limit": limit, "room": room}
