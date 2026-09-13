"""
Reference reconciler (GPU-014): observations from API / webhook / signed statement / chain (native) are
reduced to ONE economic event per `economicEventId`, then to receivable lifecycles, settlements, cash and
repayment allocations. Pure Python, integers only. The production reconciler (GPU-024/016) must reproduce
the golden fixtures under test/fixtures/gpu/settlements/.

Rules (docs/gpu/evidence-and-reconciliation.md):
  * economicEventId is the merge key; observationId, sourceEventId, proofQueryKey, proofArtifactId are
    technical ids and never merge keys.
  * trust of an economic event = strongest observation (PROVEN > ASSERTED > OBSERVED > CLAIMED); a native
    observation without consumption is NATIVE_ACCEPTED only, not CONSUMED.
  * conflicting amounts across observations => RECONCILIATION_EXCEPTION (no silent pick).
  * corrections are deltas against a target revision; out-of-order revisions are flagged, not applied.
  * PAYOUT at the source reduces unpaidAmount and creates SOURCE_ESCROW cash; only a destination receipt
    with an allocation reduces facility debt (destination currency).
  * paid receivables contribute 0 to the base and cannot be re-pledged; unknown-origin cash is UNCLASSIFIED.
  * caller-claimed locator fields must equal proven ones, else the observation is rejected.
"""

from __future__ import annotations

from dataclasses import dataclass, field

TRUST_RANK = {"CLAIMED": 0, "OBSERVED": 1, "ASSERTED": 2, "PROVEN": 3}


@dataclass
class Receivable:
    receivable_id: str
    economic_event_id: str
    account: str
    obligation_ref: str
    asset: str
    net: int
    paid: int = 0
    revision: int = 1
    state: str = "RECOGNIZED"
    assigned_facility: str | None = None
    trust: str = "CLAIMED"
    used_in_decision: bool = False

    @property
    def unpaid(self) -> int:
        return max(0, self.net - self.paid)


@dataclass
class Ledger:
    economic_events: dict[str, dict] = field(default_factory=dict)
    receivables: dict[str, Receivable] = field(default_factory=dict)  # by obligation key (account|ref)
    settlements: dict[str, dict] = field(default_factory=dict)
    cash: list[dict] = field(default_factory=list)
    allocations: list[dict] = field(default_factory=list)
    facility_debt: dict[str, int] = field(default_factory=dict)
    exceptions: list[dict] = field(default_factory=list)
    consumed_source_events: set[str] = field(default_factory=set)
    decisions_revoked: set[str] = field(default_factory=set)

    def summary(self) -> dict:
        return {
            "economicEvents": len(self.economic_events),
            "receivables": {k: {"net": r.net, "paid": r.paid, "unpaid": r.unpaid, "state": r.state, "revision": r.revision, "trust": r.trust, "assigned": r.assigned_facility} for k, r in sorted(self.receivables.items())},
            "eligibleUnpaid": sum(r.unpaid for r in self.receivables.values() if r.state in ("RECOGNIZED", "ASSIGNED", "PARTIALLY_PAID") and r.trust == "PROVEN" and r.assigned_facility),
            "sourceEscrow": sum(c["amount"] for c in self.cash if c["where"] == "SOURCE_ESCROW"),
            "inFlight": sum(c["amount"] for c in self.cash if c["where"] == "IN_FLIGHT"),
            "destinationReceived": sum(c["amount"] for c in self.cash if c["where"] == "DESTINATION"),
            "unclassifiedCash": sum(c["amount"] for c in self.cash if c.get("provenance") == "UNCLASSIFIED"),
            "facilityDebt": dict(sorted(self.facility_debt.items())),
            "allocations": self.allocations,
            "consumedSourceEvents": sorted(self.consumed_source_events),
            "exceptions": sorted(e["code"] for e in self.exceptions),
            "decisionsRevoked": sorted(self.decisions_revoked),
        }


def _key(account: str, ref: str) -> str:
    return f"{account}|{ref}"


def reconcile(obs_list: list[dict], facilities: dict[str, dict]) -> Ledger:
    """
    obs_list items (all amounts are int base units, already parsed from strings):
      {observationId, source: API|WEBHOOK|STATEMENT|CHAIN, trust, economicEventId, eventType,
       account, obligationRef?, asset, amount, revision?, facility?, targetEconomicEventId?, delta?,
       sourceEventId?, consumed?, proven?: {height, txIndex, logOrdinal}, claimed?: {...}, settlementId?,
       leg?: {...}, destination?: bool}
    facilities: {facilityId: {"account": ..., "asset": ..., "chainKey": ..., "debt": int, "loanAsset": ...}}
    """
    L = Ledger()
    for fid, f in facilities.items():
        L.facility_debt[fid] = int(f.get("debt", 0))

    # 1. merge observations into economic events (chronological by observedAt then order)
    for o in sorted(obs_list, key=lambda x: (x.get("observedAt", ""), x["observationId"])):
        # 1a. native observations: claimed locator must match proven locator
        if o["source"] == "CHAIN":
            proven, claimed = o.get("proven"), o.get("claimed")
            if claimed and proven and any(claimed.get(k) != proven.get(k) for k in ("height", "txIndex", "logOrdinal")):
                L.exceptions.append({"code": "LOCATOR_TAMPERED", "observationId": o["observationId"]})
                continue
            sev = o.get("sourceEventId")
            if sev and o.get("consumed"):
                if sev in L.consumed_source_events:
                    L.exceptions.append({"code": "DUPLICATE_CONSUMPTION", "observationId": o["observationId"]})
                    continue
                L.consumed_source_events.add(sev)
            if o.get("emitterRegistered") is False:
                L.exceptions.append({"code": "EMITTER_NOT_REGISTERED", "observationId": o["observationId"]})
                continue
            if o.get("anchor"):
                # our own hash anchor: recorded, never a business fact
                L.exceptions.append({"code": "OWN_ANCHOR_INELIGIBLE", "observationId": o["observationId"]})
                continue
        eid = o["economicEventId"]
        trust = o["trust"] if not (o["source"] == "CHAIN" and not o.get("consumed")) else "OBSERVED"
        ev = L.economic_events.get(eid)
        if ev is None:
            L.economic_events[eid] = {
                "economicEventId": eid, "eventType": o["eventType"], "account": o["account"], "asset": o["asset"],
                "amount": o.get("amount"), "delta": o.get("delta"), "revision": o.get("revision", 1),
                "obligationRef": o.get("obligationRef"), "facility": o.get("facility"), "target": o.get("targetEconomicEventId"),
                "trust": trust, "observedVia": [o["observationId"]], "settlementId": o.get("settlementId"),
                "sourceEventId": o.get("sourceEventId"), "payer": o.get("payer"), "payerIsBorrower": bool(o.get("payerIsBorrower")), "provenance": o.get("provenance"),
            }
        else:
            if ev["amount"] is not None and o.get("amount") is not None and ev["amount"] != o["amount"]:
                L.exceptions.append({"code": "AMOUNT_CONFLICT", "economicEventId": eid, "observationId": o["observationId"]})
                continue
            ev["observedVia"].append(o["observationId"])
            if TRUST_RANK[trust] > TRUST_RANK[ev["trust"]]:
                ev["trust"] = trust
                ev["sourceEventId"] = o.get("sourceEventId", ev["sourceEventId"])

    # 2. apply economic events in first-observation order (dict insertion order); revision checks
    #    catch out-of-order corrections explicitly instead of silently re-sorting them.
    events = list(L.economic_events.values())
    for e in events:
        t = e["eventType"]
        if t == "OBLIGATION":
            k = _key(e["account"], e["obligationRef"])
            if k in L.receivables:
                r = L.receivables[k]
                if e["revision"] <= r.revision:
                    L.exceptions.append({"code": "REVISION_OUT_OF_ORDER", "economicEventId": e["economicEventId"]})
                    continue
                r.net, r.revision = e["amount"], e["revision"]
                r.trust = e["trust"] if TRUST_RANK[e["trust"]] >= TRUST_RANK[r.trust] else r.trust
            else:
                L.receivables[k] = Receivable(receivable_id=k, economic_event_id=e["economicEventId"], account=e["account"], obligation_ref=e["obligationRef"], asset=e["asset"], net=e["amount"], revision=e["revision"], trust=e["trust"])
        elif t == "ASSIGNMENT":
            fac = facilities.get(e["facility"], {})
            if fac.get("account") != e["account"]:
                L.exceptions.append({"code": "ACCOUNT_MISMATCH", "economicEventId": e["economicEventId"]})
                continue
            k = _key(e["account"], e["obligationRef"])
            r = L.receivables.get(k)
            if r is None:
                L.exceptions.append({"code": "ASSIGNMENT_WITHOUT_OBLIGATION", "economicEventId": e["economicEventId"]})
                continue
            if r.state == "PAID":
                L.exceptions.append({"code": "PAID_REPLEDGE", "economicEventId": e["economicEventId"]})
                continue
            r.assigned_facility = e["facility"]
            r.state = "ASSIGNED" if r.paid == 0 else "PARTIALLY_PAID"
        elif t == "CORRECTION":
            target = L.economic_events.get(e["target"])
            k = _key(e["account"], target["obligationRef"]) if target else None
            r = L.receivables.get(k) if k else None
            if r is None:
                L.exceptions.append({"code": "CORRECTION_TARGET_MISSING", "economicEventId": e["economicEventId"]})
                continue
            if e["revision"] != r.revision + 1:
                L.exceptions.append({"code": "REVISION_OUT_OF_ORDER", "economicEventId": e["economicEventId"]})
                continue
            r.net += e["delta"]
            r.revision = e["revision"]
            if r.used_in_decision and r.unpaid < 0 or (r.used_in_decision and e["delta"] < 0):
                L.decisions_revoked.add(r.assigned_facility or "?")
            if r.net <= r.paid:
                r.state = "PAID" if r.net == r.paid else "PAID"
        elif t == "PAYOUT":
            fac_ok = True
            k = _key(e["account"], e["obligationRef"]) if e.get("obligationRef") else None
            r = L.receivables.get(k) if k else None
            if r is not None and r.asset != e["asset"]:
                L.exceptions.append({"code": "TOKEN_MISMATCH", "economicEventId": e["economicEventId"]})
                fac_ok = False
            provenance = e.get("provenance") or ("PROVIDER_SETTLEMENT" if r is not None else "UNCLASSIFIED")
            if e.get("payer") and e.get("payerIsBorrower"):
                provenance = "SELF_TRANSFER"
            L.cash.append({"where": "SOURCE_ESCROW", "amount": e["amount"], "settlementId": e.get("settlementId"), "provenance": provenance, "economicEventId": e["economicEventId"]})
            if r is not None and fac_ok and provenance == "PROVIDER_SETTLEMENT":
                r.paid += e["amount"]
                r.state = "PAID" if r.paid >= r.net else ("PARTIALLY_PAID" if r.assigned_facility else "RECOGNIZED")
            if e.get("settlementId"):
                s = L.settlements.setdefault(e["settlementId"], {"sourceAmount": 0, "allocations": {}, "legs": [], "destinationAmount": 0})
                s["sourceAmount"] += e["amount"]
                if r is not None:
                    s["allocations"][r.receivable_id] = s["allocations"].get(r.receivable_id, 0) + e["amount"]
        elif t == "CANCELLATION":
            k = _key(e["account"], e["obligationRef"])
            r = L.receivables.get(k)
            if r is None or r.paid < e["amount"]:
                L.exceptions.append({"code": "CANCEL_EXCEEDS_PAID", "economicEventId": e["economicEventId"]})
                continue
            r.paid -= e["amount"]
            r.state = "PARTIALLY_PAID" if r.paid else ("ASSIGNED" if r.assigned_facility else "RECOGNIZED")
            L.cash.append({"where": "SOURCE_ESCROW", "amount": -e["amount"], "settlementId": e.get("settlementId"), "provenance": "REFUND_OR_REVERSAL", "economicEventId": e["economicEventId"]})
            if r.used_in_decision:
                L.decisions_revoked.add(r.assigned_facility or "?")
        elif t == "LEG":
            s = L.settlements.setdefault(e["settlementId"], {"sourceAmount": 0, "allocations": {}, "legs": [], "destinationAmount": 0})
            s["legs"].append({"from": e["amount"], "to": e.get("toAmount"), "asset": e["asset"], "toAsset": e.get("toAsset")})
            L.cash.append({"where": "SOURCE_ESCROW", "amount": -e["amount"], "settlementId": e["settlementId"]})
            L.cash.append({"where": "IN_FLIGHT", "amount": e.get("toAmount", e["amount"]), "settlementId": e["settlementId"]})
        elif t == "DESTINATION_RECEIPT":
            s = L.settlements.setdefault(e["settlementId"], {"sourceAmount": 0, "allocations": {}, "legs": [], "destinationAmount": 0})
            s["destinationAmount"] += e["amount"]
            L.cash.append({"where": "IN_FLIGHT", "amount": -e["amount"], "settlementId": e["settlementId"]})
            L.cash.append({"where": "DESTINATION", "amount": e["amount"], "settlementId": e["settlementId"]})
        elif t == "ALLOCATION":
            fid = e["facility"]
            fac = facilities.get(fid, {})
            if fac.get("loanAsset") != e["asset"]:
                L.exceptions.append({"code": "LOAN_ASSET_MISMATCH", "economicEventId": e["economicEventId"]})
                continue
            received = sum(c["amount"] for c in L.cash if c["where"] == "DESTINATION" and c.get("settlementId") == e.get("settlementId"))
            allocated = sum(a["amount"] for a in L.allocations if a.get("settlementId") == e.get("settlementId"))
            if allocated + e["amount"] > received:
                L.exceptions.append({"code": "ALLOCATION_EXCEEDS_RECEIPT", "economicEventId": e["economicEventId"]})
                continue
            applied = min(e["amount"], L.facility_debt.get(fid, 0))
            L.facility_debt[fid] = L.facility_debt.get(fid, 0) - applied
            L.allocations.append({"facility": fid, "amount": e["amount"], "applied": applied, "excess": e["amount"] - applied, "settlementId": e.get("settlementId")})
        elif t == "DECISION_USE":
            k = _key(e["account"], e["obligationRef"])
            r = L.receivables.get(k)
            if r is not None:
                r.used_in_decision = True
        else:
            L.exceptions.append({"code": "UNKNOWN_EVENT_TYPE", "economicEventId": e["economicEventId"]})
    return L
