"""Security middleware: body size cap, security headers, auth-endpoint rate limit (in-memory)."""

from __future__ import annotations

import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cache-Control": "no-store",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
}


def _err(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": {"code": code, "message": message}})


class GpuSecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        rt = getattr(request.app.state, "gpu", None)
        path = request.url.path
        if rt is not None and path.startswith("/gpu/"):
            length = request.headers.get("content-length")
            if length is not None:
                try:
                    if int(length) > rt.max_body_bytes:
                        return _err(413, "VALIDATION", "request body too large")
                except ValueError:
                    return _err(400, "VALIDATION", "bad content-length")
            if path.startswith("/gpu/auth/"):
                client = request.client.host if request.client else "unknown"
                if not rt.auth_rate_limiter.allow(f"ip:{client}", time.time()):
                    return _err(429, "RATE_LIMITED", "too many requests")
        response = await call_next(request)
        if path.startswith("/gpu/"):
            for k, v in SECURITY_HEADERS.items():
                response.headers.setdefault(k, v)
        return response
