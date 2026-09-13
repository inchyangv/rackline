"""Read-only PostgreSQL queries with ownership/profile scope applied before pagination."""

from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import create_engine, exists, or_, select, text
from sqlalchemy.orm import Session

from hashcredit_gpu.db import ledgers as L
from hashcredit_gpu.db import models as M
from hashcredit_gpu.db.assets_models import ProviderAccountLink
from hashcredit_gpu.db.projections_models import ChainBlock, ChainCursor, ChainDeployment, ChainLog, ProjectedEvidence, ProjectedFacility
from hashcredit_gpu.db.product_models import OperationReview, FacilityBinding
from hashcredit_gpu.reconciliation.chain_reader import pair_repayment_events

from ..errors import not_configured
from ..permissions.deps import Principal
from . import models as D
from .settings import ProductSettings


class ProductRepository:
    def __init__(self, settings: ProductSettings):
        self.settings = settings
        self.engine = None
        if settings.database_url:
            self.engine = create_engine(settings.database_url.get_secret_value(), pool_pre_ping=True,
                                        connect_args={"connect_timeout": 3}, hide_parameters=True)

    @contextmanager
    def session(self):
        if self.engine is None:
            raise not_configured("GPU database is not configured")
        with Session(self.engine) as session:
            # Consistent metadata + rows and defense against accidental mutations in read handlers.
            session.connection(execution_options={"isolation_level": "REPEATABLE READ"})
            session.execute(text("SET TRANSACTION READ ONLY"))
            yield session

    def metadata(self, session: Session) -> D.ReadMeta:
        cfg = self.settings
        if cfg.chain_id is None or cfg.deployment_id is None or cfg.manifest_hash is None:
            raise not_configured("GPU chain, deployment, and manifest binding are required")
        deployment = session.get(ChainDeployment, cfg.deployment_id)
        if deployment is None:
            raise not_configured("configured GPU deployment has not been indexed")
        if (deployment.chain_id, deployment.execution_profile, deployment.manifest_hash) != (cfg.chain_id, cfg.execution_profile, cfg.manifest_hash):
            raise not_configured("configured GPU deployment binding does not match the database")
        cursor = session.get(ChainCursor, cfg.deployment_id)
        if cursor is None:
            raise not_configured("canonical GPU projection is not available")
        block = session.get(ChainBlock, (cfg.deployment_id, cursor.finalized_block_number))
        head = session.get(ChainBlock, (cfg.deployment_id, cursor.last_block_number))
        if block is None or block.tier != "FINALIZED" or head is None or head.hash != cursor.last_block_hash:
            raise not_configured("canonical GPU block journal is incomplete")
        now = datetime.now(timezone.utc)
        age = max((now - cursor.updated_at).total_seconds(), now.timestamp() - block.timestamp)
        if cursor.updated_at > now or block.timestamp > now.timestamp() + 30:
            raise not_configured("GPU projection timestamps are invalid")
        return D.ReadMeta(executionProfile=cfg.execution_profile, chainId=cfg.chain_id,
                          deploymentId=cfg.deployment_id, manifestHash=cfg.manifest_hash,
                          observedAt=cursor.updated_at,
                          canonicalBlock=D.CanonicalBlock(number=block.number, hash=block.hash, timestamp=block.timestamp),
                          freshness="STALE" if age > cfg.max_projection_age_seconds else "FRESH")

    def accounts(self, principal: Principal, staff: bool):
        q = select(M.ProviderAccount.provider_account_id).join(M.Provider).where(
            M.Provider.execution_profile == self.settings.execution_profile)
        if not staff:
            q = q.where(M.ProviderAccount.borrower_id == principal.borrower_id)
        return q

    def facilities(self, principal: Principal, staff: bool):
        q = select(M.Facility.facility_id).where(
            M.Facility.execution_profile == self.settings.execution_profile,
            M.Facility.loan_chain_id == self.settings.chain_id)
        if not staff:
            q = q.where(M.Facility.borrower_id == principal.borrower_id)
        return q

    def query(self, resource: str, principal: Principal, staff: bool):
        accounts, facilities = self.accounts(principal, staff), self.facilities(principal, staff)
        profile = self.settings.execution_profile
        if resource == "providers":
            return select(M.Provider).where(M.Provider.execution_profile == profile), M.Provider.provider_id
        if resource == "connections":
            return select(M.ProviderAccount).where(M.ProviderAccount.provider_account_id.in_(accounts)), M.ProviderAccount.provider_account_id
        if resource == "assets":
            assigned = select(M.AssetProviderAssignment.asset_id).where(
                M.AssetProviderAssignment.provider_account_id.in_(accounts), M.AssetProviderAssignment.ended_at.is_(None))
            return select(M.GpuAsset).where(M.GpuAsset.asset_id.in_(assigned)), M.GpuAsset.asset_id
        if resource == "facilities":
            return select(M.Facility).where(M.Facility.facility_id.in_(facilities)), M.Facility.facility_id
        if resource == "receivables":
            return select(L.Receivable).where(L.Receivable.provider_account_id.in_(accounts), L.Receivable.execution_profile == profile), L.Receivable.receivable_id
        if resource == "settlements":
            return select(L.Settlement).where(L.Settlement.provider_account_id.in_(accounts), L.Settlement.execution_profile == profile), L.Settlement.settlement_id
        if resource == "control-agreements":
            q = select(M.ControlAgreement).where(M.ControlAgreement.provider_account_id.in_(accounts))
            if not staff:
                q = q.where(M.ControlAgreement.borrower_id == principal.borrower_id)
            return q, M.ControlAgreement.control_agreement_id
        if resource == "repayments":
            return select(L.Allocation).join(L.CashReceipt).where(
                L.Allocation.facility_id.in_(facilities), L.CashReceipt.execution_profile == profile,
                L.CashReceipt.chain_id == self.settings.chain_id), L.Allocation.allocation_id
        if resource == "recoveries":
            return select(L.RecoveryEvent).where(L.RecoveryEvent.facility_id.in_(facilities)), L.RecoveryEvent.recovery_event_id
        if resource == "operations":
            receivables = select(L.Receivable.receivable_id).where(L.Receivable.provider_account_id.in_(accounts), L.Receivable.execution_profile == profile)
            settlements = select(L.Settlement.settlement_id).where(L.Settlement.provider_account_id.in_(accounts), L.Settlement.execution_profile == profile)
            proofs = select(L.ProofRequest.proof_request_id).where(L.ProofRequest.execution_profile == profile,
                L.ProofRequest.manifest_hash == self.settings.manifest_hash)
            # Legacy/unscoped exceptions have no deployment/profile binding; do not leak them.
            q = select(L.ExceptionCase).where(or_(
                (L.ExceptionCase.entity_table == "facilities") & L.ExceptionCase.entity_id.in_(facilities),
                (L.ExceptionCase.entity_table == "provider_accounts") & L.ExceptionCase.entity_id.in_(accounts),
                (L.ExceptionCase.entity_table == "receivables") & L.ExceptionCase.entity_id.in_(receivables),
                (L.ExceptionCase.entity_table == "settlements") & L.ExceptionCase.entity_id.in_(settlements),
                (L.ExceptionCase.entity_table == "proof_requests") & L.ExceptionCase.entity_id.in_(proofs)))
            return q, L.ExceptionCase.exception_id
        raise not_configured("read model is not available")

    def evidence(self, session: Session, row: L.Receivable) -> D.EvidenceStages:
        stages = D.EvidenceStages(earningsProvenance="SIMULATED" if row.execution_profile != "PRODUCTION" else "UNCLASSIFIED")
        if row.checkpoint_consumption_id is None:
            return stages
        consumed = session.get(L.EvidenceConsumption, row.checkpoint_consumption_id)
        if consumed is None or consumed.provider_account_id != row.provider_account_id or consumed.execution_profile != self.settings.execution_profile:
            raise not_configured("receivable evidence binding is inconsistent")
        verification = session.get(L.NativeVerification, consumed.native_verification_id)
        if verification is None or verification.destination_chain_id != self.settings.chain_id or verification.execution_profile != self.settings.execution_profile:
            raise not_configured("native submission binding is inconsistent")
        proof = session.get(L.ProofRequest, verification.proof_request_id)
        if proof is None or proof.execution_profile != self.settings.execution_profile or proof.manifest_hash != self.settings.manifest_hash:
            raise not_configured("proof request binding is inconsistent")
        projected = session.get(ProjectedEvidence, (self.settings.deployment_id, "FINALIZED", consumed.source_event_id))
        canonical = bool(projected and projected.execution_profile == self.settings.execution_profile
                         and projected.consumption_tx_hash == consumed.consumption_tx_hash
                         and projected.verification_method == consumed.verification_method
                         and projected.verified_in_same_tx and verification.status == "ACCEPTED")
        if canonical:
            block = session.get(ChainBlock, (self.settings.deployment_id, projected.block_number))
            canonical = bool(block and block.tier == "FINALIZED" and block.hash == projected.block_hash)
        stages.proofRequestId, stages.proofRequestStatus = proof.proof_request_id, proof.status
        stages.proofReadyAt, stages.nativeSubmissionStatus = proof.api_ready_at, verification.status
        stages.verificationMethod = consumed.verification_method
        stages.consumptionId, stages.sourceEventId = consumed.consumption_id, consumed.source_event_id
        stages.nativeCanonical = canonical
        # LOCAL_MOCK may have a mined local consumption but never official native acceptance.
        stages.nativeStatus = "CONSUMED" if canonical and consumed.verification_method == "ATTESTCOIN_NATIVE" else None
        return stages

    def serialize(self, session: Session, row):
        if isinstance(row, M.Provider):
            allowed = ("listAssets", "fetchRevenue", "fetchSettlements", "getControlState", "claimRevenue", "requestControlChange")
            caps = {key: ("SUPPORTED" if row.capabilities.get(key) is True else "UNSUPPORTED" if row.capabilities.get(key) is False else "UNCONFIRMED") for key in allowed}
            return D.ProviderDTO(providerId=row.provider_id, displayName=row.display_name, executionProfile=row.execution_profile,
                environmentStatus=row.environment_status, requiredVerification=row.required_verification,
                sourceEnvId=row.source_env_id, sourceChainKey=row.source_chain_key, sourceChainId=row.source_chain_id,
                manifestHash=row.manifest_hash, testOnly=row.test_only, capabilities=caps)
        if isinstance(row, M.ProviderAccount):
            link = session.scalar(select(ProviderAccountLink).where(ProviderAccountLink.provider_account_id == row.provider_account_id,
                ProviderAccountLink.borrower_id == row.borrower_id, ProviderAccountLink.released_at.is_(None)))
            return D.ConnectionDTO(providerAccountId=row.provider_account_id, providerId=row.provider_id, borrowerId=row.borrower_id,
                externalAccountId=row.external_account_id, credentialConfigured=row.credential_ref is not None,
                controlVersion=row.control_version, lastVerifiedAt=row.last_verified_at,
                accountReviewState=link.review_state if link else None, createdAt=row.created_at)
        if isinstance(row, M.GpuAsset):
            return D.AssetDTO(assetId=row.asset_id, kind=row.kind, sku=row.sku, unitCount=row.unit_count,
                ownership=row.ownership, ownershipReview=row.ownership_review, identityConfidence=row.identity_confidence,
                status=row.status, parentAssetId=row.parent_asset_id, eligible=row.eligible)
        if isinstance(row, M.Facility):
            asset = D.AssetRef(chainId=row.loan_chain_id, address=row.loan_token_address, decimals=row.loan_decimals)
            binding = session.get(FacilityBinding, (self.settings.deployment_id, row.facility_id))
            projected = session.get(ProjectedFacility, (self.settings.deployment_id, "FINALIZED", binding.onchain_id)) if binding else None
            canonical = bool(projected and projected.execution_profile == row.execution_profile)
            block = session.get(ChainBlock, (self.settings.deployment_id, projected.last_block)) if canonical else None
            canonical = canonical and block is not None and block.tier == "FINALIZED"
            return D.FacilityDTO(facilityId=row.facility_id, borrowerId=row.borrower_id, vaultId=row.vault_id,
                executionProfile=row.execution_profile, state=projected.state if canonical else row.state, loanAsset=asset,
                recordedPrincipal=money(projected.principal if canonical else row.principal, asset),
                recordedUnpaidInterest=money(projected.unpaid_interest_recorded if canonical else row.unpaid_interest, asset),
                recordedFees=money(projected.fees if canonical else row.fees, asset), recordedReservedDraws=money(row.reserved_draws, asset),
                recordedApprovedCap=money(row.approved_cap, asset), rateBps=str(row.rate_bps), advanceRateBps=str(row.advance_rate_bps),
                maturityAt=row.maturity_at, controlAgreementId=row.control_agreement_id,
                canonicalFacilityId=binding.onchain_id if binding else None,
                recordOrigin="FINALIZED_CHAIN_EVENTS" if canonical else "DATABASE_METADATA",
                financialReadiness="TRANSACTION_CONTEXT_AVAILABLE" if binding else "UNAVAILABLE_ID_BINDING",
                updatedAt=datetime.fromtimestamp(block.timestamp, timezone.utc) if canonical else row.updated_at)
        if isinstance(row, L.Receivable):
            asset = D.AssetRef(chainId=row.asset_chain_id, address=row.asset_token_address, decimals=row.asset_decimals)
            return D.ReceivableDTO(receivableId=row.receivable_id, economicEventId=row.economic_event_id,
                providerAccountId=row.provider_account_id, facilityId=row.facility_id, state=row.state, revision=row.revision,
                gross=money(row.gross, asset), net=money(row.net, asset), paidAmount=money(row.paid_amount, asset),
                unpaidAmount=money(row.unpaid_amount, asset), periodFrom=row.period_from, periodTo=row.period_to,
                dueAt=row.due_at, updatedAt=row.updated_at, evidence=self.evidence(session, row))
        if isinstance(row, L.Settlement):
            receipts = list(session.scalars(select(L.CashReceipt).where(L.CashReceipt.settlement_id == row.settlement_id,
                L.CashReceipt.execution_profile == self.settings.execution_profile, L.CashReceipt.chain_id == self.settings.chain_id).order_by(L.CashReceipt.cash_receipt_id)))
            asset = D.AssetRef(chainId=row.asset_chain_id, address=row.asset_token_address, decimals=row.asset_decimals)
            return D.SettlementDTO(settlementId=row.settlement_id, providerAccountId=row.provider_account_id,
                state=row.state, sourceAmount=money(row.source_amount, asset), payoutConsumptionId=row.payout_consumption_id,
                destinationReceipts=[cash(receipt) for receipt in receipts], destinationCashRecorded=bool(receipts), updatedAt=row.updated_at)
        if isinstance(row, M.ControlAgreement):
            stale = row.last_observed_at is not None and (datetime.now(timezone.utc) - row.last_observed_at).total_seconds() > self.settings.max_projection_age_seconds
            return D.ControlDTO(controlAgreementId=row.control_agreement_id, borrowerId=row.borrower_id,
                providerAccountId=row.provider_account_id, controlGrade=row.control_grade, version=row.version,
                changeAuthority=row.change_authority, receiverChainId=row.receiver_chain_id, receiverAddress=row.receiver_address,
                agreementHash=row.agreement_hash, effectiveFrom=row.effective_from, effectiveTo=row.effective_to,
                lastObservedAt=row.last_observed_at, observationFreshness="UNAVAILABLE" if row.last_observed_at is None else "STALE" if stale else "FRESH")
        if isinstance(row, L.Allocation):
            receipt = session.get(L.CashReceipt, row.cash_receipt_id)
            asset = D.AssetRef(chainId=receipt.chain_id, address=receipt.token_address, decimals=receipt.decimals)
            applied = False
            application_evidence = "UNCONFIRMED_LEDGER_RECORD"
            deployment = session.get(ChainDeployment, self.settings.deployment_id)
            binding = session.get(FacilityBinding, (self.settings.deployment_id, row.facility_id))
            facility = session.get(M.Facility, row.facility_id)
            if (deployment and binding and facility
                and (deployment.chain_id, deployment.execution_profile, deployment.manifest_hash)
                    == (self.settings.chain_id, self.settings.execution_profile, self.settings.manifest_hash)
                and (receipt.chain_id, receipt.execution_profile) == (deployment.chain_id, deployment.execution_profile)
                and (facility.loan_chain_id, facility.loan_token_address, facility.loan_decimals,
                     facility.vault_id, facility.execution_profile)
                    == (receipt.chain_id, receipt.token_address, receipt.decimals, receipt.vault_id, receipt.execution_profile)
                and receipt.cash_state == "ALLOCATED" and receipt.source_kind == "DIRECT_REPAYMENT"
                and row.onchain_tx_hash == receipt.tx_hash and row.received == receipt.amount):
                # Reconciliation anchors a manager/router Repaid, never AllocationApplied or Transfer.
                # Keep only successful finalized logs still anchored in the canonical journal.
                logs = list(session.scalars(select(ChainLog).join(ChainBlock,
                    (ChainBlock.deployment_id == ChainLog.deployment_id)
                    & (ChainBlock.number == ChainLog.block_number)
                    & (ChainBlock.hash == ChainLog.block_hash)).where(
                        ChainLog.deployment_id == deployment.deployment_id,
                        ChainLog.tx_hash == receipt.tx_hash, ChainLog.tier == "FINALIZED",
                        ChainLog.tx_status == 1, ChainBlock.tier == "FINALIZED")))
                paired = pair_repayment_events(logs, deployment.contracts, receipt.log_index, binding.onchain_id)
                if paired is not None:
                    repaid, allocated, vault_receipt = paired
                    allocation, cash_event, repayment = allocated.decoded, vault_receipt.decoded, repaid.decoded
                    expected = {"feePaid": row.fee_paid, "interestPaid": row.interest_paid,
                                "principalPaid": row.principal_paid, "excess": row.excess, "newDebt": row.new_debt}
                    measured = {"received": row.received,
                                "applied": row.fee_paid + row.interest_paid + row.principal_paid,
                                "excess": row.excess}
                    applied = (all(str(allocation.get(key)) == str(int(value)) for key, value in expected.items())
                        and (repaid.contract_name != "RepaymentRouter"
                             or all(str(repayment.get(key)) == str(int(value)) for key, value in expected.items()))
                        and all(str(event.get(key)) == str(int(value))
                                for event in (cash_event, repayment) for key, value in measured.items())
                        and str(repayment.get("newDebt")) == str(int(row.new_debt))
                        and repayment.get("payer") == receipt.payer_address)
                    if applied:
                        application_evidence = ("FINALIZED_ROUTER_EVENT" if repaid.contract_name == "RepaymentRouter"
                                                else "FINALIZED_MANAGER_EVENT")
            return D.RepaymentDTO(repaymentAllocationId=row.allocation_id, facilityId=row.facility_id,
                cashReceiptId=row.cash_receipt_id, received=money(row.received, asset), feePaid=money(row.fee_paid, asset),
                interestPaid=money(row.interest_paid, asset), principalPaid=money(row.principal_paid, asset),
                excess=money(row.excess, asset), recordedNewDebt=money(row.new_debt, asset), onchainTxHash=row.onchain_tx_hash,
                allocatedAt=row.allocated_at, repaymentApplied=True if applied else None,
                applicationEvidence=application_evidence)
        if isinstance(row, L.RecoveryEvent):
            facility = session.get(M.Facility, row.facility_id)
            asset = D.AssetRef(chainId=facility.loan_chain_id, address=facility.loan_token_address, decimals=facility.loan_decimals)
            return D.RecoveryDTO(recoveryEventId=row.recovery_event_id, facilityId=row.facility_id, kind=row.kind,
                amount=money(row.amount, asset), cashReceiptId=row.cash_receipt_id, occurredAt=row.occurred_at)
        if isinstance(row, L.ExceptionCase):
            review = session.get(OperationReview, row.exception_id)
            audit = session.scalars(select(L.AuditLog).where(L.AuditLog.entity_table == "exceptions", L.AuditLog.entity_id == row.exception_id)
                                    .order_by(L.AuditLog.id.desc()).limit(50))
            return D.OperationDTO(exceptionId=row.exception_id, kind=row.kind, severity=row.severity,
                state="RESOLVED" if row.resolved_at else review.state if review else "OPEN", entityType=row.entity_table, entityId=row.entity_id,
                createdAt=row.opened_at, resolvedAt=row.resolved_at, version=review.version if review else 0,
                assignee=review.assignee if review else None, owner=review.assignee if review else None,
                audit=[{"action": a.action, "reason": (a.after or {}).get("reason"), "createdAt": a.occurred_at} for a in audit])
        raise not_configured("unsupported read model")


def money(amount: int | Decimal, asset: D.AssetRef) -> D.Money:
    if amount is None or Decimal(amount) != Decimal(amount).to_integral_value():
        raise not_configured("invalid exact amount in the ledger")
    return D.Money(amount=str(int(amount)), asset=asset)


def cash(row: L.CashReceipt) -> D.CashDTO:
    asset = D.AssetRef(chainId=row.chain_id, address=row.token_address, decimals=row.decimals)
    return D.CashDTO(cashReceiptId=row.cash_receipt_id, amount=money(row.amount, asset), cashState=row.cash_state,
                     sourceKind=row.source_kind, txHash=row.tx_hash, logIndex=row.log_index, receivedAt=row.received_at)


class DatabaseOwnership:
    """Auth links are re-read on every request; unverified/released wallets have no identity."""

    def __init__(self, repository: ProductRepository):
        self.repository = repository

    def borrower_of_wallet(self, wallet: str) -> str | None:
        with self.repository.session() as session:
            return session.scalar(select(M.BorrowerWallet.borrower_id).where(
                M.BorrowerWallet.chain_id == self.repository.settings.chain_id,
                M.BorrowerWallet.address == wallet.lower(), M.BorrowerWallet.verified_at.is_not(None),
                M.BorrowerWallet.released_at.is_(None)))

    def borrower_of_account(self, account_key: str) -> str | None:
        # Existing auth expects hashed account keys; no hash<->DB binding is assumed here.
        return None

    def borrower_of_facility(self, facility_id: str) -> str | None:
        with self.repository.session() as session:
            return session.scalar(select(M.Facility.borrower_id).where(M.Facility.facility_id == facility_id,
                M.Facility.loan_chain_id == self.repository.settings.chain_id,
                M.Facility.execution_profile == self.repository.settings.execution_profile))
