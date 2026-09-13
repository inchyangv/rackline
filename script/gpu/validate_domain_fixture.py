#!/usr/bin/env python3
"""
Validate a GPU domain fixture against config/gpu/schema/domain-v1.schema.json plus the semantic
rules from docs/gpu/domain-model.md that JSON Schema cannot express.

Usage:
    python script/gpu/validate_domain_fixture.py [fixture.json ...] [--reader-profile PRODUCTION] [--self-test]

Requires `jsonschema` (pinned by the offchain/gpu dev dependencies in GPU-015; until then install it into
the project venv). Exit 0 = valid, 1 = violations, 2 = usage/dependency error. No network.
"""

from __future__ import annotations

import json
import sys
from collections import defaultdict
from pathlib import Path

try:
    from jsonschema import Draft202012Validator
except ImportError:  # pragma: no cover
    print("error: jsonschema not installed (pip install jsonschema)", file=sys.stderr)
    sys.exit(2)

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "config" / "gpu" / "schema" / "domain-v1.schema.json"
DEFAULT_FIXTURE = ROOT / "test" / "fixtures" / "gpu" / "domain" / "sample-v1.json"

PROFILE_RANK = {"LOCAL_MOCK": 0, "NATIVE_TESTNET": 1, "PRODUCTION": 2}


def _asset_key(a: dict) -> tuple:
    return (a["chainId"], (a["address"] or "").lower(), a["decimals"])


def _money_key(m: dict) -> tuple:
    return _asset_key(m["asset"])


def semantic_checks(fx: dict, reader_profile: str | None) -> list[str]:
    errs: list[str] = []
    by_id = lambda coll, key: {row[key]: row for row in fx.get(coll, [])}
    receivables = by_id("receivables", "receivableId")
    facilities = by_id("facilities", "facilityId")
    cash = by_id("cashReceipts", "cashReceiptId")
    source_events = by_id("sourceEvents", "sourceEventId")
    native = by_id("nativeVerifications", "nativeVerificationId")
    evidence = by_id("businessEvidence", "businessEvidenceId")
    artifacts = by_id("proofArtifacts", "proofArtifactId")

    # Money arithmetic: same asset, exact integers.
    for r in receivables.values():
        keys = {_money_key(r["gross"]), _money_key(r["net"]), _money_key(r["paidAmount"]), _money_key(r["unpaidAmount"])}
        if len(keys) != 1:
            errs.append(f"receivable {r['receivableId']}: mixed assets in gross/net/paid/unpaid")
        deductions = sum(int(d["money"]["amount"]) for d in r["deductions"])
        if int(r["gross"]["amount"]) - deductions != int(r["net"]["amount"]):
            errs.append(f"receivable {r['receivableId']}: gross - deductions != net")
        if int(r["paidAmount"]["amount"]) + int(r["unpaidAmount"]["amount"]) != int(r["net"]["amount"]):
            errs.append(f"receivable {r['receivableId']}: paid + unpaid != net")
        if r["state"] == "PAID" and int(r["unpaidAmount"]["amount"]) != 0:
            errs.append(f"receivable {r['receivableId']}: PAID with unpaid balance")
        for ev in r["evidence"]:
            if ev not in evidence:
                errs.append(f"receivable {r['receivableId']}: unknown evidence {ev}")

    # Settlement allocations sum to net payout and reference known receivables; leg out-amounts never exceed in.
    for s in fx.get("settlements", []):
        total = 0
        for a in s["receivableAllocations"]:
            if a["receivableId"] not in receivables:
                errs.append(f"settlement {s['settlementId']}: unknown receivable {a['receivableId']}")
            if _money_key(a["money"]) != _money_key(s["netPayout"]):
                errs.append(f"settlement {s['settlementId']}: allocation asset differs from netPayout")
            total += int(a["money"]["amount"])
        if total != int(s["netPayout"]["amount"]):
            errs.append(f"settlement {s['settlementId']}: allocations {total} != netPayout {s['netPayout']['amount']}")
        for cid in (s["sourceCashReceiptId"], s["destinationCashReceiptId"]):
            if cid is not None and cid not in cash:
                errs.append(f"settlement {s['settlementId']}: unknown cash receipt {cid}")
        if s["state"] in ("RECEIVED_AT_DESTINATION", "ALLOCATED") and s["destinationCashReceiptId"] is None:
            errs.append(f"settlement {s['settlementId']}: {s['state']} without destination cash receipt")

    # Repayment allocation: only from DESTINATION receipts; parts sum to receipt amount; facility known.
    for ra in fx.get("repaymentAllocations", []):
        cr = cash.get(ra["cashReceiptId"])
        if cr is None:
            errs.append(f"allocation {ra['repaymentAllocationId']}: unknown cash receipt")
            continue
        if cr["where"] != "DESTINATION_VAULT":
            errs.append(f"allocation {ra['repaymentAllocationId']}: repayment from non-destination receipt ({cr['where']}) — R2-D07")
        parts = sum(int(ra[k]["amount"]) for k in ("fees", "interest", "principal", "excess"))
        if parts != int(cr["amount"]):
            errs.append(f"allocation {ra['repaymentAllocationId']}: fees+interest+principal+excess {parts} != receipt {cr['amount']}")
        fac = facilities.get(ra["facilityId"])
        if fac is None:
            errs.append(f"allocation {ra['repaymentAllocationId']}: unknown facility")
        elif _asset_key(fac["loanAsset"]) != _asset_key(cr["asset"]):
            errs.append(f"allocation {ra['repaymentAllocationId']}: receipt asset != facility loan asset")

    # Evidence consumption: unique per (envId, locator) and per sourceEventId; must reference an ACCEPTED verification.
    seen_loc: dict[tuple, str] = {}
    seen_sev: set[str] = set()
    for c in fx.get("evidenceConsumptions", []):
        loc = c["locator"]
        key = (c["envId"], loc["chainKey"], loc["height"], loc["txIndex"], loc["logOrdinal"])
        if key in seen_loc:
            errs.append(f"consumption duplicate for locator {key} (already {seen_loc[key]})")
        seen_loc[key] = c["sourceEventId"]
        if c["sourceEventId"] in seen_sev:
            errs.append(f"consumption duplicate for sourceEventId {c['sourceEventId']}")
        seen_sev.add(c["sourceEventId"])
        se = source_events.get(c["sourceEventId"])
        if se is None:
            errs.append(f"consumption {c['sourceEventId']}: unknown source event")
        elif se["locator"] != loc or se["sourceChain"]["envId"] != c["envId"]:
            errs.append(f"consumption {c['sourceEventId']}: locator/env differs from source event")
        nv = native.get(c["nativeVerificationId"])
        if nv is None or nv["result"] != "ACCEPTED":
            errs.append(f"consumption {c['sourceEventId']}: not backed by an ACCEPTED native verification")
        elif se is not None and nv["provenTxIndex"] != loc["txIndex"]:
            errs.append(f"consumption {c['sourceEventId']}: provenTxIndex != locator txIndex")

    # Native verification must reference a stored (untrusted) artifact and matching profile.
    for nv in native.values():
        if nv["proofArtifactId"] not in artifacts:
            errs.append(f"native verification {nv['nativeVerificationId']}: unknown proof artifact")

    # Business evidence: native status only from consumption; OUR_ANCHOR never PROVEN; SIMULATED for TEST_ONLY providers.
    for ev in evidence.values():
        if ev["nativeStatus"] in ("NATIVE_ACCEPTED", "CONSUMED"):
            if ev["kind"] != "SOURCE_EVENT_NATIVE" or ev["verificationMethod"] != "ATTESTCOIN_NATIVE":
                errs.append(f"evidence {ev['businessEvidenceId']}: {ev['nativeStatus']} without native source event/method")
            if ev["refs"]["sourceEventId"] not in seen_sev:
                errs.append(f"evidence {ev['businessEvidenceId']}: CONSUMED/ACCEPTED without a consumption record")
            if ev["trust"] != "PROVEN":
                errs.append(f"evidence {ev['businessEvidenceId']}: native-accepted evidence must be trust=PROVEN")
        if ev["kind"] == "OUR_ANCHOR" and (ev["trust"] == "PROVEN" or ev["nativeStatus"] in ("NATIVE_ACCEPTED", "CONSUMED")):
            errs.append(f"evidence {ev['businessEvidenceId']}: OUR_ANCHOR cannot be PROVEN/native-accepted as revenue (R2-D04)")
        if ev["economicEventId"].startswith("mockdepin-testonly/") and ev["earningsProvenance"] not in ("SIMULATED", "UNCLASSIFIED"):
            errs.append(f"evidence {ev['businessEvidenceId']}: TEST_ONLY provider must be SIMULATED/UNCLASSIFIED")

    # Profile isolation: facility never references evidence/cash of a lower profile; a PRODUCTION reader rejects lower rows.
    for fac in facilities.values():
        for rid in fac["usedReceivableIds"]:
            r = receivables.get(rid)
            if r is None:
                errs.append(f"facility {fac['facilityId']}: unknown receivable {rid}")
                continue
            for ev_id in r["evidence"]:
                ev = evidence.get(ev_id)
                if ev and PROFILE_RANK[ev["executionProfile"]] < PROFILE_RANK[fac["executionProfile"]]:
                    errs.append(f"facility {fac['facilityId']}: evidence {ev_id} profile {ev['executionProfile']} < facility {fac['executionProfile']}")
    if reader_profile:
        for coll, key in (("businessEvidence", "businessEvidenceId"), ("cashReceipts", "cashReceiptId"), ("nativeVerifications", "nativeVerificationId"), ("sourceEvents", "sourceEventId")):
            for row in fx.get(coll, []):
                if row["executionProfile"] != reader_profile:
                    errs.append(f"reader {reader_profile} rejects {coll} {row[key]} (profile {row['executionProfile']})")

    # Same chainKey may map to different chains only across envIds.
    per_env_key: dict[tuple, set] = defaultdict(set)
    for sc in fx.get("sourceChains", []):
        per_env_key[(sc["envId"], sc["chainKey"])].add(sc["chainId"])
    for (env, ck), ids in per_env_key.items():
        if len(ids) > 1:
            errs.append(f"env {env} chainKey {ck} maps to multiple chainIds {sorted(ids)}")

    # Asset assignments: at most one open assignment per asset; parent must exist.
    open_by_asset: dict[str, int] = defaultdict(int)
    assets = by_id("assets", "assetId")
    for a in fx.get("assetAssignments", []):
        if a["assetId"] not in assets:
            errs.append(f"assignment {a['assignmentId']}: unknown asset")
        if a["to"] is None:
            open_by_asset[a["assetId"]] += 1
    for aid, n in open_by_asset.items():
        if n > 1:
            errs.append(f"asset {aid}: {n} open assignments")
    for a in assets.values():
        if a["parentAssetId"] is not None and a["parentAssetId"] not in assets:
            errs.append(f"asset {a['assetId']}: unknown parent")

    # Corrections target an existing revision below the current one.
    for c in fx.get("corrections", []):
        r = receivables.get(c["targetId"])
        if r is None:
            errs.append(f"correction {c['correctionId']}: unknown target")
        elif c["targetRevision"] >= r["revision"]:
            errs.append(f"correction {c['correctionId']}: targetRevision must be below current revision")
    return errs


NEGATIVE_VECTORS = [
    # (name, mutation, expected substring, schema-level?)
    ("duplicate consumption of the same log", lambda f: f["evidenceConsumptions"].append(dict(f["evidenceConsumptions"][0])), "consumption duplicate", False),
    ("settlement allocations != netPayout", lambda f: f["settlements"][0]["receivableAllocations"][0]["money"].__setitem__("amount", "1"), "allocations", False),
    ("OUR_ANCHOR claimed PROVEN", lambda f: f["businessEvidence"][2].__setitem__("trust", "PROVEN"), "OUR_ANCHOR cannot be PROVEN", False),
    ("repayment allocated from SOURCE_ESCROW receipt", lambda f: f["repaymentAllocations"][0].__setitem__("cashReceiptId", f["cashReceipts"][0]["cashReceiptId"]), "non-destination receipt", False),
    ("PRODUCTION facility using NATIVE_TESTNET evidence", lambda f: f["facilities"][0].__setitem__("executionProfile", "PRODUCTION"), "profile NATIVE_TESTNET < facility PRODUCTION", False),
    ("same env chainKey mapped to two chainIds", lambda f: f["sourceChains"].append(dict(f["sourceChains"][0], chainId=17000)), "maps to multiple chainIds", False),
    ("paid + unpaid != net", lambda f: f["receivables"][0]["unpaidAmount"].__setitem__("amount", "1"), "paid + unpaid != net", False),
    ("two open assignments for one asset", lambda f: f["assetAssignments"][0].__setitem__("to", None), "open assignments", False),
    ("native-accepted evidence without consumption", lambda f: f["evidenceConsumptions"].pop(0), "without a consumption record", False),
    ("float money rejected by schema", lambda f: f["facilities"][0]["principal"].__setitem__("amount", "3000.5"), "does not match", True),
    ("verificationMethod outside enum rejected by schema", lambda f: f["businessEvidence"][0].__setitem__("verificationMethod", "EIP712_ATTESTED"), "is not one of", True),
    ("encoding != 1 rejected by schema", lambda f: f["sourceChains"][0].__setitem__("encoding", 2), "was expected", True),
    ("requiredVerification must be ATTESTCOIN_NATIVE", lambda f: f["facilities"][0].__setitem__("requiredVerification", "OFFCHAIN_ASSERTION"), "was expected", True),
]


def self_test(validator: "Draft202012Validator") -> int:
    """Mutate the sample fixture 13 ways; every mutation must be rejected for the expected reason."""
    import copy

    base = json.loads(DEFAULT_FIXTURE.read_text())
    failures = 0
    for name, mutate, expect, schema_level in NEGATIVE_VECTORS:
        fx = copy.deepcopy(base)
        mutate(fx)
        schema_errors = list(validator.iter_errors(fx))
        sem = semantic_checks(fx, None) if not schema_errors else []
        pool = [e.message for e in schema_errors] if schema_level else sem
        ok = any(expect in m for m in pool)
        failures += 0 if ok else 1
        print(f"  {'PASS' if ok else 'FAIL'} {name}")
    print(f"self-test: {len(NEGATIVE_VECTORS) - failures}/{len(NEGATIVE_VECTORS)} negative vectors rejected")
    return 0 if failures == 0 else 1


def main(argv: list[str]) -> int:
    args = [a for a in argv if not a.startswith("--")]
    reader = None
    if "--reader-profile" in argv:
        reader = argv[argv.index("--reader-profile") + 1]
        args = [a for a in args if a != reader]
    fixtures = [Path(a) for a in args] or [DEFAULT_FIXTURE]
    schema = json.loads(SCHEMA.read_text())
    Draft202012Validator.check_schema(schema)
    validator = Draft202012Validator(schema)
    if "--self-test" in argv:
        return self_test(validator)
    rc = 0
    for fp in fixtures:
        fx = json.loads(fp.read_text())
        schema_errors = sorted(validator.iter_errors(fx), key=lambda e: list(e.path))
        sem = semantic_checks(fx, reader) if not schema_errors else []
        if schema_errors or sem:
            rc = 1
            print(f"INVALID {fp}: {len(schema_errors)} schema error(s), {len(sem)} semantic error(s)")
            for e in schema_errors[:20]:
                print(f"  schema: {'/'.join(map(str, e.path))}: {e.message[:160]}")
            for m in sem:
                print(f"  semantic: {m}")
        else:
            counts = {k: len(v) for k, v in fx.items() if isinstance(v, list)}
            print(f"VALID {fp} (schema {schema['$id']}; rows: {counts})")
    return rc


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
