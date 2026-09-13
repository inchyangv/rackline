"""BTC-free GPU API entrypoint: uvicorn hashcredit_api.gpu.app:create_app --factory.

Liveness does not claim readiness. No schema creation, data seeding, signing key, BTC import,
legacy write route, or external RPC request is performed at startup.
"""

import logging
from contextlib import asynccontextmanager
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from requests.exceptions import RequestException
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException
from starlette.middleware.cors import CORSMiddleware
from web3.exceptions import (
    BadFunctionCallOutput,
    BadResponseFormat,
    ContractLogicError,
    ProviderConnectionError,
    TimeExhausted,
    Web3RPCError,
)

from .auth.challenge import InMemoryChallengeStore
from .auth.database import DatabaseChallengeStore, DatabaseRoleRegistry
from .auth.erc1271 import RejectAllErc1271Checker, RpcErc1271Checker
from .auth.roles import InMemoryRoleRegistry, RoleRegistry
from .auth.router import router as auth_router
from .errors import ApiError
from .middleware import SECURITY_HEADERS
from .product.chain import ContractReads, build_chain_router
from .product.commands import build_commands_router
from .product.proofs import build_proof_router
from .product.repository import DatabaseOwnership, ProductRepository
from .product.router import build_product_router
from .product.settings import ProductSettings
from .runtime import GpuRuntime, RateLimiter
from .secrets import EnvSecretStore, Redactor, install_record_redaction

log = logging.getLogger(__name__)
RPC_FAILURES = (RequestException, ProviderConnectionError, TimeExhausted, Web3RPCError,
                BadResponseFormat, BadFunctionCallOutput, ContractLogicError)


def error_response(request: Request, status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message,
                        "details": {}, "requestId": getattr(request.state, "request_id", "")}})


def create_app(settings: ProductSettings | None = None, *, roles: RoleRegistry | None = None) -> FastAPI:
    settings = settings or ProductSettings()
    repository = ProductRepository(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        yield
        if repository.engine is not None:
            repository.engine.dispose()

    app = FastAPI(title="Rackline GPU API", version="1.0", lifespan=lifespan)
    app.state.product = repository
    app.state.chain = ContractReads(settings)
    secret = settings.session_secret.get_secret_value() if settings.session_secret else None
    redactor = Redactor()
    redactor.register(secret)
    if settings.database_url:
        redactor.register(settings.database_url.get_secret_value())
    if settings.rpc_url:
        redactor.register(settings.rpc_url.get_secret_value())
    install_record_redaction(redactor)
    app.state.gpu = GpuRuntime(
        api_profile="production" if settings.execution_profile == "PRODUCTION" else "testnet_demo",
        chain_id=settings.chain_id or 0, app_domain=settings.app_domain or "UNCONFIGURED",
        session_secret=secret if settings.chain_id and settings.app_domain else None,
        session_ttl_seconds=settings.session_ttl_seconds, challenge_ttl_seconds=settings.challenge_ttl_seconds,
        max_body_bytes=settings.max_body_bytes, challenges=DatabaseChallengeStore(repository.engine) if repository.engine is not None else InMemoryChallengeStore(),
        # No environment-provided self-assigned admin roles. A reviewed canonical registry may be injected.
        roles=roles or (DatabaseRoleRegistry(repository.engine, settings.chain_id) if repository.engine is not None else InMemoryRoleRegistry()), ownership=DatabaseOwnership(repository),
        erc1271=RpcErc1271Checker(app.state.chain.web3, settings.chain_id) if app.state.chain.web3 is not None else RejectAllErc1271Checker(), secrets=EnvSecretStore(), redactor=redactor,
        manifests={}, allow_mock_manifests=False, provider_allowlist=frozenset(), emitter_allowlist={},
        auth_rate_limiter=RateLimiter(settings.auth_rate_limit_per_minute))

    @app.middleware("http")
    async def security(request: Request, call_next):
        import time
        request.state.request_id = str(uuid4())
        if request.url.path.startswith("/gpu/auth/"):
            host = request.client.host if request.client else "unknown"
            if not app.state.gpu.auth_rate_limiter.allow(host, time.time()):
                response = error_response(request, 429, "RATE_LIMITED", "too many authentication requests")
            else:
                response = None
        else:
            response = None
        if response is None:
            # Check streamed bytes too; Content-Length alone does not constrain chunked input.
            size = 0
            chunks = []
            async for chunk in request.stream():
                size += len(chunk)
                if size > settings.max_body_bytes:
                    response = error_response(request, 413, "VALIDATION", "request body too large")
                    break
                chunks.append(chunk)
            if response is None:
                request._body = b"".join(chunks)
                # An app-level catch-all sits outside this middleware in Starlette and loses
                # these security headers. Keep the boundary here; never serialize RPC details.
                try:
                    response = await call_next(request)
                except RPC_FAILURES as exc:
                    log.warning("canonical RPC unavailable (%s), request %s",
                                type(exc).__name__, request.state.request_id)
                    response = error_response(request, 503, "UPSTREAM_UNAVAILABLE",
                                              "canonical GPU RPC is unavailable")
                except Exception:
                    log.exception("unexpected GPU API failure, request %s", request.state.request_id)
                    response = error_response(request, 500, "INTERNAL_ERROR",
                                              "an unexpected server error occurred")
        for name, value in SECURITY_HEADERS.items():
            response.headers[name] = value
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @app.exception_handler(HTTPException)
    async def http_error(request: Request, exc: HTTPException):
        if isinstance(exc, ApiError):
            return error_response(request, exc.status_code, exc.code, exc.detail["message"])
        return error_response(request, exc.status_code, "NOT_FOUND" if exc.status_code == 404 else "VALIDATION", "not found" if exc.status_code == 404 else "request is not supported")

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request: Request, _: RequestValidationError):
        # Pydantic's default validation payload includes caller input, possibly a credential/signature.
        return error_response(request, 422, "VALIDATION", "request does not match the API schema")

    @app.exception_handler(SQLAlchemyError)
    async def unavailable_database(request: Request, _: SQLAlchemyError):
        return error_response(request, 503, "UPSTREAM_UNAVAILABLE", "GPU database or required schema is unavailable")

    @app.get("/health", tags=["system"])
    def health():
        return {"status": "alive", "service": "rackline-gpu-api", "schemaVersion": "1.0"}

    @app.get("/ready", tags=["system"])
    def ready(request: Request):
        if app.state.gpu.session_secret is None:
            return error_response(request, 503, "UPSTREAM_UNAVAILABLE", "GPU authentication configuration is incomplete")
        with repository.session() as session:
            metadata = repository.metadata(session)
        if metadata.freshness != "FRESH":
            return error_response(request, 503, "EVIDENCE_STALE", "canonical GPU projection is stale")
        return {"status": "ready", "service": "rackline-gpu-api", "readOnly": False,
                "financialMutationsAvailable": False, "meta": metadata.model_dump(mode="json")}

    app.include_router(auth_router)  # Auth only: never mount GPU-018's provisional success handlers.
    app.include_router(build_commands_router())
    app.include_router(build_chain_router())
    app.include_router(build_proof_router())
    app.include_router(build_product_router())
    if settings.cors_origins:
        app.add_middleware(CORSMiddleware, allow_origins=settings.cors_origins,
                           allow_methods=["GET", "POST", "OPTIONS"],
                           allow_headers=["Authorization", "Content-Type", "Idempotency-Key"], allow_credentials=False)
    return app
