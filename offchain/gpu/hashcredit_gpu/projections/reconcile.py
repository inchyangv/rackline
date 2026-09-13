"""Compare event projections with canonical views at the same finalized block."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db.projections_models import (
    ChainBlock,
    ChainCursor,
    ChainDeployment,
    ProjectedEntity,
    ProjectedFacility,
    ProjectionDiscrepancy,
)
from ..domain.enums import ExecutionProfile
from .views import ContractViews


def reconcile_views(engine, rpc, deployment_id: str) -> dict:
    with Session(engine) as s, s.begin():
        deployment, cursor = (
            s.get(ChainDeployment, deployment_id),
            s.get(ChainCursor, deployment_id),
        )
        if not deployment or not cursor:
            return {"checked": 0, "discrepancies": 0, "reason": "INDEX_CURSOR_MISSING"}
        block = s.get(ChainBlock, (deployment_id, cursor.finalized_block_number))
        if not block:
            return {"checked": 0, "discrepancies": 0, "reason": "FINALIZED_BLOCK_PENDING"}
        if (
            rpc.chain_id() != deployment.chain_id
            or rpc.get_block(block.number)["hash"].lower() != block.hash
        ):
            raise ValueError("canonical deployment/block changed during reconciliation")
        views = ContractViews(rpc, deployment.contracts)
        result = {"checked": 0, "discrepancies": 0, "block": block.number}

        def compare(subject, projected, canonical, expected_lag=False):
            result["checked"] += 1
            if str(projected) == str(canonical):
                return
            classification = "EXPECTED_LAG" if expected_lag else "DISCREPANCY"
            if not expected_lag:
                result["discrepancies"] += 1
            exists = s.scalar(
                select(ProjectionDiscrepancy.id)
                .where(
                    ProjectionDiscrepancy.deployment_id == deployment_id,
                    ProjectionDiscrepancy.block_number == block.number,
                    ProjectionDiscrepancy.subject == subject,
                    ProjectionDiscrepancy.projected == str(projected),
                    ProjectionDiscrepancy.canonical == str(canonical),
                )
                .limit(1)
            )
            if not exists:
                s.add(
                    ProjectionDiscrepancy(
                        deployment_id=deployment_id,
                        block_number=block.number,
                        subject=subject,
                        projected=str(projected),
                        canonical=str(canonical),
                        classification=classification,
                        note="Accrued interest in view exceeds last recorded accrual"
                        if expected_lag
                        else "Read model differs from canonical contract",
                    )
                )

        if "DebtLedger" in deployment.contracts:
            facilities = list(
                s.scalars(
                    select(ProjectedFacility).where(
                        ProjectedFacility.deployment_id == deployment_id,
                        ProjectedFacility.tier == "FINALIZED",
                    )
                )
            )
            compare(
                "facilityCount",
                len(facilities),
                views.read("DebtLedger", "facilityCount", [], block.number),
            )
            for facility in facilities:
                data = views.read("DebtLedger", "view_", [facility.facility_key], block.number)
                compare(
                    f"{facility.facility_key}:principal", int(facility.principal), data["principal"]
                )
                compare(f"{facility.facility_key}:fees", int(facility.fees), data["fees"])
                compare(
                    f"{facility.facility_key}:profile",
                    facility.execution_profile,
                    list(ExecutionProfile)[int(data["executionProfile"])].value,
                )
                recorded_debt = views.read(
                    "DebtLedger",
                    "legalDebtAt",
                    [facility.facility_key, int(data["lastAccrualAt"])],
                    block.number,
                )
                compare(
                    f"{facility.facility_key}:recordedDebt",
                    int(facility.principal + facility.fees + facility.unpaid_interest_recorded),
                    recorded_debt,
                )
                compare(
                    f"{facility.facility_key}:currentInterest",
                    int(facility.unpaid_interest_recorded),
                    data["unpaidInterest"],
                    expected_lag=int(data["unpaidInterest"])
                    >= int(facility.unpaid_interest_recorded),
                )
        if "LendingVaultV2" in deployment.contracts:
            address = deployment.contracts["LendingVaultV2"].lower()
            entity = s.get(ProjectedEntity, (deployment_id, "FINALIZED", "VAULT", address))
            canonical = {
                key: views.read("LendingVaultV2", key, [], block.number)
                for key in (
                    "availableCash",
                    "totalShares",
                    "totalBorrowerOwned",
                    "nav",
                    "totalImpairment",
                )
            }
            compare(
                "vault:totalShares",
                entity.state.get("totalShares", "0") if entity else "0",
                canonical["totalShares"],
            )
            if entity:
                for address, shares in entity.state.get("shareBalances", {}).items():
                    compare(
                        f"lp:{address}:shares",
                        shares,
                        views.read("LendingVaultV2", "balanceOf", [address], block.number),
                    )
                entity.state = {
                    **entity.state,
                    "canonical": canonical,
                    "canonicalBlock": block.number,
                }
        if rpc.get_block(block.number)["hash"].lower() != block.hash:
            raise ValueError("canonical block changed before reconciliation commit")
        return result
