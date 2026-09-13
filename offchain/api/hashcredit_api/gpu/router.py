"""
GPU router assembly: auth, proof-query guard and the object-scoped resources of domain-model §11.

Resource handlers here are thin (read models are GPU-045); what matters for GPU-018 is the dependency
chain: bearer session → principal → role gate / ownership gate. Underwriting, funding and control
mutations require staff roles; a borrower session can never call them.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field

from .auth import roles as R
from .auth.router import router as auth_router
from .errors import validation
from .permissions.deps import Principal, account_access, borrower_access, current_principal, facility_access, require_role
from .proofs.router import router as proofs_router
from .secrets import is_secret_ref


class ConnectionCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    providerId: str = Field(min_length=1, max_length=120)
    externalAccountId: str = Field(min_length=1, max_length=200)
    credentialRef: str = Field(min_length=1, max_length=256, description="opaque secret ref, never a value")


def build_gpu_router() -> APIRouter:
    r = APIRouter()
    r.include_router(auth_router)
    r.include_router(proofs_router)

    @r.get("/gpu/me", tags=["gpu"])
    async def me(p: Principal = Depends(current_principal)) -> dict:
        return {"wallet": p.wallet, "borrowerId": p.borrower_id, "roles": sorted(p.roles)}

    @r.get("/gpu/borrowers/{borrowerId}", tags=["gpu"])
    async def get_borrower(borrowerId: str = Depends(borrower_access)) -> dict:
        return {"borrowerId": borrowerId}

    @r.get("/gpu/accounts/{accountKey}", tags=["gpu"])
    async def get_account(accountKey: str = Depends(account_access)) -> dict:
        return {"accountKey": accountKey}

    @r.get("/gpu/facilities/{facilityId}", tags=["gpu"])
    async def get_facility(facilityId: str = Depends(facility_access)) -> dict:
        return {"facilityId": facilityId}

    @r.post("/gpu/borrowers/{borrowerId}/connections", tags=["gpu"], status_code=201)
    async def create_connection(body: ConnectionCreate, borrowerId: str = Depends(borrower_access)) -> dict:
        # Credentials only ever arrive as refs. A raw value here is a client bug and is rejected.
        if not is_secret_ref(body.credentialRef):
            raise validation("credentialRef must be a secret reference (env://, vault://, kms://)")
        return {"borrowerId": borrowerId, "providerId": body.providerId, "credentialRef": body.credentialRef}

    # ---- staff-only mutations (GPU-013 roles); borrowers get FORBIDDEN_SCOPE
    @r.post("/gpu/facilities/{facilityId}/underwrite", tags=["gpu-staff"])
    async def underwrite(facilityId: str, _: Principal = Depends(require_role(R.UNDERWRITER))) -> dict:
        return {"facilityId": facilityId, "action": "underwrite-recorded"}

    @r.post("/gpu/facilities/{facilityId}/fund", tags=["gpu-staff"])
    async def fund(facilityId: str, _: Principal = Depends(require_role(R.TREASURY))) -> dict:
        return {"facilityId": facilityId, "action": "funding-intent-recorded"}

    @r.post("/gpu/control-agreements/{agreementId}/revoke", tags=["gpu-staff"])
    async def revoke_control(agreementId: str, _: Principal = Depends(require_role(R.GUARDIAN))) -> dict:
        return {"agreementId": agreementId, "action": "revocation-intent-recorded"}

    @r.patch("/gpu/recoveries/{caseId}", tags=["gpu-staff"])
    async def patch_recovery(caseId: str, _: Principal = Depends(require_role(R.SERVICER, R.OPERATOR))) -> dict:
        return {"caseId": caseId, "action": "case-updated"}

    return r
