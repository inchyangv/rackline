"""Uniform error envelope (domain-model §11 ErrorCode)."""

from __future__ import annotations

from fastapi import HTTPException


class ApiError(HTTPException):
    def __init__(self, status_code: int, code: str, message: str) -> None:
        super().__init__(status_code=status_code, detail={"code": code, "message": message})
        self.code = code


def unauthenticated(message: str = "authentication required") -> ApiError:
    return ApiError(401, "UNAUTHENTICATED", message)


def forbidden_scope(message: str = "insufficient role") -> ApiError:
    return ApiError(403, "FORBIDDEN_SCOPE", message)


def not_found(message: str = "not found") -> ApiError:
    # Object-level denials and missing objects share this response (no existence leak).
    return ApiError(404, "NOT_FOUND", message)


def validation(message: str) -> ApiError:
    return ApiError(422, "VALIDATION", message)


def unsupported_source(message: str) -> ApiError:
    return ApiError(422, "UNSUPPORTED_SOURCE", message)


def profile_mismatch(message: str) -> ApiError:
    return ApiError(422, "PROFILE_MISMATCH", message)


def rate_limited() -> ApiError:
    return ApiError(429, "RATE_LIMITED", "too many requests")


def not_configured(message: str) -> ApiError:
    return ApiError(503, "UPSTREAM_UNAVAILABLE", message)
