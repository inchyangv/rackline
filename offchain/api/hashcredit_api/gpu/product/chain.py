"""Deployment-pinned, read-only contract queries. Every amount is an exact base-unit string."""

import json
import re
import time
from pathlib import Path
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Request
from sqlalchemy import select
from web3 import Web3

from hashcredit_gpu.db.product_models import FacilityBinding
from hashcredit_gpu.db.projections_models import ChainLog

from ..errors import ApiError, not_configured, not_found
from ..permissions.deps import Principal, current_principal

FACILITY_ACTIVE = 3  # GpuTypes.FacilityState.ACTIVE

ALIASES = {"vault": "LendingVaultV2", "asset": "GpuTestToken", "manager": "CreditFacilityManager",
           "repaymentRouter": "RepaymentRouter", "ledger": "DebtLedger", "roles": "ProtocolRoles"}


def deployment(settings):
    if not settings.deployment_manifest:
        return None
    try:
        value = json.loads(Path(settings.deployment_manifest).read_text())
        if (value["chainId"], value["executionProfile"], value["deploymentId"], value["manifestHash"]) != (
                settings.chain_id, settings.execution_profile, settings.deployment_id, settings.manifest_hash):
            raise ValueError("binding")
        if value["requiredVerification"] != "ATTESTCOIN_NATIVE" and settings.execution_profile != "LOCAL_MOCK":
            raise ValueError("native verification required")
        asset = value["asset"]
        if asset["chainId"] != settings.chain_id or not 0 <= asset["decimals"] <= 36:
            raise ValueError("asset")
        if settings.execution_profile == "PRODUCTION" and asset.get("testOnly"):
            raise ValueError("test asset in production")
        for address in [*value["contracts"].values(), asset["address"]]:
            if not isinstance(address, str) or not re.fullmatch(r"0x[0-9a-fA-F]{40}", address) or int(address, 16) == 0:
                raise ValueError("address")
        for name in ("rpcUrl", "explorerUrl"):
            parsed = urlsplit(value[name])
            if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or parsed.query:
                if settings.execution_profile != "LOCAL_MOCK" or parsed.hostname not in ("127.0.0.1", "localhost"):
                    raise ValueError("public URL")
        return value
    except (OSError, ValueError, KeyError, TypeError):
        raise not_configured("GPU deployment manifest is invalid or does not match this API") from None


class ContractReads:
    def __init__(self, settings):
        self.settings = settings
        self.manifest = deployment(settings)
        self.web3 = None
        if self.manifest:
            url = settings.rpc_url.get_secret_value() if settings.rpc_url else self.manifest["rpcUrl"]
            self.web3 = Web3(Web3.HTTPProvider(url, request_kwargs={"timeout": 12}))

    def contract(self, name):
        if self.web3 is None or self.manifest is None or not self.settings.abi_directory:
            raise not_configured("canonical GPU contract reads are not configured")
        address = self.manifest["asset"]["address"] if name == "GpuTestToken" else self.manifest["contracts"].get(name)
        if address is None:
            raise not_configured("required contract is missing from the deployment")
        try:
            abi = json.loads((Path(self.settings.abi_directory) / f"{name}.json").read_text())
            if isinstance(abi, dict):
                abi = abi["abi"]
            return self.web3.eth.contract(address=Web3.to_checksum_address(address), abi=abi)
        except (OSError, ValueError, KeyError):
            raise not_configured("required generated ABI is unavailable") from None

    def check(self, meta):
        if self.web3 is None:
            raise not_configured("GPU contract RPC is not configured")
        if self.web3.eth.chain_id != self.settings.chain_id:
            raise not_configured("GPU RPC chain does not match the deployment")
        block = self.web3.eth.get_block(meta.canonicalBlock.number)
        if Web3.to_hex(block.hash).lower() != meta.canonicalBlock.hash.lower():
            raise not_configured("canonical GPU block changed; wait for reconciliation")
        return meta.canonicalBlock.number

    def call(self, name, method, block, *args):
        return getattr(self.contract(name).functions, method)(*args).call(block_identifier=block)

    def lp(self, session, meta, wallet):
        block = self.check(meta)
        wallet = Web3.to_checksum_address(wallet)
        c = lambda method, *args: self.call("LendingVaultV2", method, block, *args)
        asset = self.manifest["asset"]
        if c("asset").lower() != asset["address"].lower() or self.call("GpuTestToken", "decimals", block) != asset["decimals"]:
            raise not_configured("vault loan currency differs from the verified deployment")
        shares = c("balanceOf", wallet)
        epoch = c("currentEpoch")
        locked = c("lockedShares", epoch, wallet)
        recoveries = []
        if epoch > 101:
            raise not_configured("recovery history exceeds page limit")
        for prior in range(1, epoch):
            if c("sharesOfEpoch", prior, wallet):
                recoveries.append({"epoch": str(prior), "claimable": str(c("recoveryClaimable", prior, wallet))})
        query = select(ChainLog).where(ChainLog.deployment_id == self.settings.deployment_id,
            ChainLog.tier == "FINALIZED", ChainLog.contract_name == "LendingVaultV2",
            ChainLog.event_name == "WithdrawalRequested", ChainLog.decoded["owner"].astext.ilike(wallet))
        rows = session.scalars(query.order_by(ChainLog.block_number.desc()).limit(101))
        withdrawals = []
        for row in rows:
            if len(withdrawals) >= 100:
                raise not_configured("withdrawal history exceeds page limit; use the indexed history endpoint")
            request_id = int(row.decoded["requestId"])
            value = c("withdrawalRequest", request_id)
            if value[0].lower() != wallet.lower():
                raise not_configured("withdrawal ownership does not match its event")
            withdrawals.append({"requestId": str(request_id), "epoch": str(value[1]), "expiresAt": value[2],
                "sharesRequested": str(value[3]), "sharesRemaining": str(value[4]), "minAssets": str(value[5]),
                "assetsReserved": str(value[6]), "assetsClaimed": str(value[7]), "cancelled": value[8]})
        result = {"wallet": wallet, "asset": asset, "nav": str(c("nav")), "availableCash": str(c("availableCash")),
            "walletBalance": str(self.call("GpuTestToken", "balanceOf", block, wallet)), "shares": str(shares),
            "shareAssets": str(c("previewWithdraw", shares)) if shares else "0", "currentEpoch": str(epoch),
            "availableShares": str(shares - locked), "recoveries": recoveries,
            "totalShares": str(c("totalShares")), "withdrawals": withdrawals,
            "impairment": str(c("totalImpairment")), "borrowerOwned": str(c("totalBorrowerOwned")),
            "withdrawalReserved": str(c("totalWithdrawalReserved")), "pendingWithdrawalShares": str(c("pendingWithdrawalShares")),
            "depositsPaused": c("depositsPaused"), "epochRolloverRequired": c("epochRolloverRequired"),
            "shareDecimals": 18, "realizedYield": None}
        self.check(meta)
        return result

    def facility(self, session, meta, row, wallet):
        """Execution-time debt and draw quote; `drawBlockedReason` names the first gate that refuses a draw."""
        binding = session.get(FacilityBinding, (self.settings.deployment_id, row.facility_id))
        if binding is None:
            raise not_configured("facility has no verified on-chain ID binding")
        block = self.check(meta)
        ident = bytes.fromhex(binding.onchain_id[2:])
        c = lambda method, *args: self.call("CreditFacilityManager", method, block, ident, *args)
        info = c("facilityInfo")
        if not info[7] or info[1].lower() != wallet.lower():
            raise not_found()
        ledger = c("facility")
        loan_asset = ledger[1]
        if loan_asset[0] != self.settings.chain_id or loan_asset[1].lower() != self.manifest["asset"]["address"].lower():
            raise not_configured("facility loan currency does not match this deployment")
        debt = self.call("DebtLedger", "legalDebtAt", block, ident, meta.canonicalBlock.timestamp)
        reason, available = None, None
        if meta.freshness != "FRESH":
            reason = "EVIDENCE_STALE"
        elif info[6] is not None and int(info[6]) != FACILITY_ACTIVE:
            # Frozen, delinquent, defaulted, in recovery, repaid or written off: the state gate precedes eligibility.
            reason, available = "FACILITY_NOT_ACTIVE", "0"
        else:
            try:
                evaluation = c("evaluateDraw", 0)
                vault_cash = self.call("LendingVaultV2", "availableCash", block)
                drawable = min(evaluation[6], vault_cash)
                available = str(drawable)
                if drawable == 0:
                    reason = "INSUFFICIENT_VAULT_CASH" if vault_cash == 0 else "NO_ELIGIBLE_DRAW"
            except Exception:
                reason = "DRAW_REQUIREMENTS_NOT_MET"
        self.check(meta)
        return {"facilityId": row.facility_id, "canonicalFacilityId": binding.onchain_id,
            "wallet": wallet, "chainId": self.settings.chain_id, "asset": self.manifest["asset"],
            "manager": self.manifest["contracts"]["CreditFacilityManager"],
            "repaymentRouter": self.manifest["contracts"]["RepaymentRouter"], "debt": str(debt),
            "principal": str(ledger[2]), "unpaidInterest": str(ledger[3]), "fees": str(ledger[4]),
            "availableDraw": available, "drawBlockedReason": reason, "expiresAt": int(time.time()) + 30}


def build_chain_router():
    router = APIRouter(prefix="/v1", tags=["gpu-chain"])

    @router.get("/config")
    def config(request: Request):
        settings = request.app.state.product.settings
        manifest = deployment(settings)
        base = {"schemaVersion": "1.0", "configured": manifest is not None, "executionProfile": settings.execution_profile,
                "chainId": settings.chain_id, "appDomain": settings.app_domain, "deploymentId": settings.deployment_id,
                "manifestHash": settings.manifest_hash, "requiredVerification": "ATTESTCOIN_NATIVE"}
        if manifest:
            base.update({"rpcUrl": manifest["rpcUrl"], "explorerUrl": manifest["explorerUrl"], "asset": manifest["asset"],
                "nativeStatus": manifest.get("nativeStatus", "NOT_SUBMITTED"),
                "partnerRevenue": manifest.get("partnerRevenue", "UNCONFIGURED"),
                "contracts": {alias: manifest["asset"]["address"] if alias == "asset" else manifest["contracts"].get(name)
                              for alias, name in ALIASES.items()},
                "capabilities": {"onboarding": True, "connections": True, "lp": True, "walletTransactions": True,
                                 "nativeProofRequired": True, "partnerRevenue": manifest.get("partnerRevenue", "UNCONFIGURED")}})
        return base

    @router.get("/lp")
    def lp(request: Request, p: Principal = Depends(current_principal)):
        repository = request.app.state.product
        with repository.session() as session:
            metadata = repository.metadata(session)
            data = request.app.state.chain.lp(session, metadata, p.wallet)
            return {"schemaVersion": "1.0", "data": data, "meta": metadata}

    @router.get("/facilities/{facility_id}/transaction-context")
    def facility(facility_id: str, request: Request, p: Principal = Depends(current_principal)):
        from .router import scope
        staff = scope("facilities", p)
        repository = request.app.state.product
        with repository.session() as session:
            query, key = repository.query("facilities", p, staff)
            row = session.scalar(query.where(key == facility_id))
            if row is None:
                raise not_found()
            metadata = repository.metadata(session)
            data = request.app.state.chain.facility(session, metadata, row, p.wallet)
            return {"schemaVersion": "1.0", "data": data, "meta": metadata}

    return router
