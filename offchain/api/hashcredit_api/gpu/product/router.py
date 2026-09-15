"""Versioned product read routes; unsupported commands never return stub success."""

import base64
import binascii
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from ..auth import roles as R
from ..errors import ApiError, forbidden_scope, not_configured, not_found, validation
from ..permissions.deps import Principal, current_principal
from . import models as D

RESOURCES = {
    "providers": (D.ProviderDTO, set()),
    "connections": (D.ConnectionDTO, {R.OPERATOR}),
    "assets": (D.AssetDTO, {R.UNDERWRITER, R.OPERATOR}),
    "facilities": (D.FacilityDTO, {R.UNDERWRITER, R.OPERATOR, R.KEEPER, R.SERVICER, R.TREASURY, R.GUARDIAN}),
    "receivables": (D.ReceivableDTO, {R.UNDERWRITER, R.OPERATOR}),
    "settlements": (D.SettlementDTO, {R.OPERATOR, R.KEEPER}),
    "control-agreements": (D.ControlDTO, {R.UNDERWRITER, R.OPERATOR}),
    "repayments": (D.RepaymentDTO, {R.OPERATOR, R.SERVICER}),
    "recoveries": (D.RecoveryDTO, {R.OPERATOR, R.UNDERWRITER, R.SERVICER}),
    "operations": (D.OperationDTO, {R.OPERATOR, R.SERVICER, R.GUARDIAN}),
}


def scope(resource: str, p: Principal) -> bool:
    if resource == "providers":
        return False
    staff = bool(p.roles & RESOURCES[resource][1])
    if resource in ("recoveries", "operations") and not staff:
        raise forbidden_scope("operator or credit scope required")
    if not staff and (R.BORROWER not in p.roles or p.borrower_id is None):
        raise forbidden_scope("verified borrower linkage or resource-specific staff scope required")
    return staff


def cursor_value(cursor: str | None, resource: str) -> str | None:
    if cursor is None:
        return None
    try:
        decoded = base64.b64decode(cursor.encode("ascii"), altchars=b"-_", validate=True).decode("utf-8")
        prefix, key = decoded.split("\n", 1)
        if prefix != resource or not key or len(key) > 300 or "\n" in key:
            raise ValueError()
        return key
    except (UnicodeError, ValueError, binascii.Error):
        raise validation("invalid pagination cursor") from None


def encode_cursor(resource: str, key: str) -> str:
    return base64.urlsafe_b64encode(f"{resource}\n{key}".encode()).decode()


def build_product_router() -> APIRouter:
    router = APIRouter(prefix="/v1", tags=["gpu-product"])

    @router.get("/me")
    def me(request: Request, p: Principal = Depends(current_principal)):
        return {"schemaVersion": "1.0", "data": {"wallet": p.wallet, "borrowerId": p.borrower_id,
                "roles": sorted(p.roles)}, "meta": {"executionProfile": request.app.state.product.settings.execution_profile,
                "chainId": p.chain_id, "financialAuthorization": False}}

    def register(resource, model):
        def collection(request: Request, limit: Annotated[int, Query(ge=1, le=100)] = 25,
                       cursor: Annotated[str | None, Query(max_length=500)] = None,
                       p: Principal = Depends(current_principal)):
            staff = scope(resource, p)
            last = cursor_value(cursor, resource)
            repository = request.app.state.product
            with repository.session() as session:
                metadata = repository.metadata(session)
                if resource in repository.HISTORY_RESOURCES:
                    # Ledger imports merged with finalized chain projections; keys are opaque and totally ordered.
                    history = [(k, row) for k, row in repository.history(session, resource, p, staff) if last is None or k > last]
                    rows = history[:limit + 1]
                    next_cursor = encode_cursor(resource, rows[limit - 1][0]) if len(rows) > limit else None
                    return {"schemaVersion": "1.0", "data": [repository.serialize_history(session, row, p, staff) for _, row in rows[:limit]],
                            "meta": metadata, "pagination": {"limit": limit, "nextCursor": next_cursor}}
                query, key = repository.query(resource, p, staff)
                if last is not None:
                    query = query.where(key > last)
                rows = list(session.scalars(query.order_by(key).limit(limit + 1)))
                next_cursor = encode_cursor(resource, str(getattr(rows[limit - 1], key.key))) if len(rows) > limit else None
                return {"schemaVersion": "1.0", "data": [repository.serialize(session, row) for row in rows[:limit]],
                        "meta": metadata, "pagination": {"limit": limit, "nextCursor": next_cursor}}

        def item(objectId: str, request: Request, p: Principal = Depends(current_principal)):
            staff = scope(resource, p)
            repository = request.app.state.product
            with repository.session() as session:
                metadata = repository.metadata(session)
                if resource in repository.HISTORY_RESOURCES:
                    match = next((row for k, row in repository.history(session, resource, p, staff)
                                  if objectId in repository.history_ids(k, row)), None)
                    if match is None:
                        raise not_found()
                    return {"schemaVersion": "1.0", "data": repository.serialize_history(session, match, p, staff), "meta": metadata}
                query, key = repository.query(resource, p, staff)
                row = session.scalar(query.where(key == objectId))
                if row is None:
                    raise not_found()
                return {"schemaVersion": "1.0", "data": repository.serialize(session, row), "meta": metadata}

        collection.__name__ = f"list_{resource.replace('-', '_')}"
        item.__name__ = f"get_{resource.replace('-', '_')}"
        router.add_api_route(f"/{resource}", collection, methods=["GET"], response_model=D.Page[model])
        router.add_api_route(f"/{resource}/{{objectId}}", item, methods=["GET"], response_model=D.Item[model])

    for resource, (model, _) in RESOURCES.items():
        register(resource, model)

    @router.api_route("/{resource}", methods=["POST", "PATCH", "DELETE"])
    @router.api_route("/{resource}/{objectId:path}", methods=["POST", "PUT", "PATCH", "DELETE"])
    def unavailable_command(resource: str, objectId: str = "", p: Principal = Depends(current_principal)):
        if "verified" in objectId.lower() or "verification" in objectId.lower():
            raise ApiError(405, "FORBIDDEN_SCOPE", "verification state is not an API mutation")
        if resource not in RESOURCES and resource != "lp":
            raise not_found()
        raise not_configured("authorized durable mutation service is not connected; no change was made")

    return router
