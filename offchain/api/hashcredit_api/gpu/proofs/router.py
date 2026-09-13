"""
Proof query endpoints (read-only planning; the SDK worker of GPU-079 executes queries).

R2 guard: the request may select only `manifestId`, `providerId`, `emitter`, `txHash`. Any other field —
rpcUrl, verifier, mock, trusted, bypass, markVerified, nativeStatus, … — is rejected (extra="forbid" on
the body model and an explicit query-string check). There is no mutation that marks anything verified.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..auth import roles as R
from ..errors import profile_mismatch, unsupported_source, validation
from ..permissions.deps import Principal, require_role
from .outbound import is_allowed_outbound

ALLOWED_SELECTORS = frozenset({"manifestId", "providerId", "emitter", "txHash"})
FORBIDDEN_HINT = frozenset(
    {"rpcUrl", "rpc", "url", "verifier", "verifierAddress", "mock", "trusted", "bypass", "markVerified",
     "nativeStatus", "precompile", "decoder", "profile", "executionProfile", "manifestUrl", "proofUrl"}
)
_TX = re.compile(r"^0x[0-9a-fA-F]{64}$")
_ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")
_ID = re.compile(r"^[A-Za-z0-9._:-]{1,120}$")


class ProofQueryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    manifestId: str = Field(min_length=1, max_length=120)
    providerId: str = Field(min_length=1, max_length=120)
    emitter: str
    txHash: str

    @field_validator("manifestId", "providerId")
    @classmethod
    def _id(cls, v: str) -> str:
        if not _ID.match(v):
            raise ValueError("invalid identifier")
        return v

    @field_validator("emitter")
    @classmethod
    def _addr(cls, v: str) -> str:
        if not _ADDR.match(v):
            raise ValueError("emitter must be a 20-byte hex address")
        return v.lower()

    @field_validator("txHash")
    @classmethod
    def _tx(cls, v: str) -> str:
        if not _TX.match(v):
            raise ValueError("txHash must be a 32-byte hex hash")
        return v.lower()


class ProofQueryPlan(BaseModel):
    manifestId: str
    executionProfile: str
    manifestHash: str | None
    sourceChainId: int
    chainKey: int
    emitter: str
    txHash: str
    proofHosts: list[str]
    nativeStatus: str = "NOT_REQUESTED"  # planning only; never VERIFIED from here (R2)
    note: str = "query plan only; proof fetch and native submission are the GPU-079 worker's job"


def _plan(request: Request, q: ProofQueryRequest) -> ProofQueryPlan:
    rt = request.app.state.gpu
    m = rt.manifests.get(q.manifestId)
    if m is None:
        raise unsupported_source(f"unknown manifest {q.manifestId}")
    if m.mock and (rt.api_profile == "production" or not rt.allow_mock_manifests):
        raise profile_mismatch("mock manifests are not queryable (LOCAL_MOCK is never a native environment)")
    if rt.api_profile == "production" and m.execution_profile != "PRODUCTION":
        raise profile_mismatch(f"manifest profile {m.execution_profile} is not PRODUCTION")
    allowed = m.emitters | {e.lower() for e in rt.emitter_allowlist.get(q.manifestId, ())}
    if q.emitter not in allowed:
        raise unsupported_source("emitter is not registered for this manifest")
    if q.providerId not in rt.provider_allowlist:
        raise unsupported_source("provider is not admitted")
    return ProofQueryPlan(
        manifestId=m.manifest_id,
        executionProfile=m.execution_profile,
        manifestHash=m.manifest_hash,
        sourceChainId=m.source_chain_id,
        chainKey=m.chain_key,
        emitter=q.emitter,
        txHash=q.txHash,
        proofHosts=sorted(h for h in m.proof_hosts if is_allowed_outbound(f"https://{h}/", m.proof_hosts)),
    )


router = APIRouter(prefix="/gpu/proofs", tags=["gpu-proofs"])


@router.post("/query", response_model=ProofQueryPlan)
async def plan_proof_query(
    body: ProofQueryRequest,
    request: Request,
    _: Principal = Depends(require_role(R.KEEPER, R.OPERATOR, R.UNDERWRITER)),
) -> ProofQueryPlan:
    return _plan(request, body)


@router.get("/query", response_model=ProofQueryPlan)
async def plan_proof_query_get(
    request: Request,
    _: Principal = Depends(require_role(R.KEEPER, R.OPERATOR, R.UNDERWRITER)),
) -> ProofQueryPlan:
    extra = set(request.query_params.keys()) - ALLOWED_SELECTORS
    if extra:
        raise validation(f"unsupported query fields: {sorted(extra)}")
    try:
        q = ProofQueryRequest(**{k: request.query_params[k] for k in ALLOWED_SELECTORS if k in request.query_params})
    except Exception as e:  # pydantic ValidationError
        raise validation(str(e).splitlines()[0])
    return _plan(request, q)
