"""Mirror a finalized direct repayment receipt/allocation without broadcasting or modifying debt."""

import argparse
import json
import os
from pathlib import Path

from hashcredit_gpu.db.models import Facility
from hashcredit_gpu.db.projections_models import ChainDeployment
from hashcredit_gpu.reconciliation.chain_reader import CanonicalRepaymentReader
from hashcredit_gpu.reconciliation.engine import (
    DestinationRoute,
    record_confirmed_allocation,
    record_destination_receipt,
)
from hashcredit_gpu.transactions.rpc import JsonRpcClient, load_rpc_allowlist
from sqlalchemy import create_engine
from sqlalchemy.orm import Session


def reconcile(engine, rpc, deployment_id, reference):
    reader = CanonicalRepaymentReader(engine, rpc, deployment_id)
    receipt, allocation = reader.receipt(reference), reader.allocation(reference)
    if receipt is None or allocation is None:
        raise ValueError("finalized canonical repayment events not indexed")
    with Session(engine) as s, s.begin():
        deployment = s.get(ChainDeployment, deployment_id)
        facility = s.get(Facility, allocation.facility_id)
        if not deployment or not facility or deployment.chain_id != rpc.chain_id():
            raise ValueError("repayment deployment binding unavailable")
        route = DestinationRoute(
            facility.vault_id, receipt.payee_address, receipt.asset, deployment.execution_profile
        )
        cash = record_destination_receipt(s, reference=reference, route=route, reader=reader)
        if cash.entity_id is None:
            raise ValueError(cash.reason)
        applied = record_confirmed_allocation(s, reference=reference, reader=reader)
        if applied.entity_id is None:
            raise ValueError(applied.reason)
        return {
            "cashReceiptId": cash.entity_id,
            "allocationId": applied.entity_id,
            "measuredReceived": str(receipt.amount),
            "excess": str(allocation.excess),
            "canonicalNewDebt": str(allocation.new_debt),
            "debtMutated": False,
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument(
        "--reference", required=True, action="append", help="txHash:managerOrRouterRepaidLogIndex (direct repayments only)"
    )
    args = parser.parse_args()
    _, urls = load_rpc_allowlist(args.manifest)
    rpc = JsonRpcClient(urls[0], urls)
    engine = create_engine(
        os.environ.get("HASHCREDIT_GPU_DATABASE_URL") or os.environ["GPU_DATABASE_URL"]
    )
    try:
        with Session(engine) as s:
            deployment = s.get(ChainDeployment, args.deployment_id)
            manifest = json.loads(Path(args.manifest).read_text())
            if not deployment or deployment.manifest_hash != manifest["manifestHash"]:
                raise ValueError("repayment manifest differs from deployment")
        print(
            json.dumps([reconcile(engine, rpc, args.deployment_id, ref) for ref in args.reference])
        )
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
