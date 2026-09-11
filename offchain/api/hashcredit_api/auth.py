"""
Token-based authentication for the API.

Security model:
- If API_TOKEN is not set, authentication is disabled (local development only)
- If API_TOKEN is set, endpoints that include `Depends(verify_api_token)` require a valid token via X-API-Key
- No query param token support (prevents log/referrer leakage)
- No local bypass when token is configured for those endpoints (prevents proxy bypass attacks)

WARNING: If running with HOST=0.0.0.0, you MUST set API_TOKEN and ensure
the host is behind a firewall or reverse proxy with proper access control.
"""

from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader

from .config import Settings, get_settings


# API key via header only (no query param for security)
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_token(
    request: Request,
    api_key: Optional[str] = Depends(api_key_header),
    settings: Settings = Depends(get_settings),
) -> bool:
    """
    Verify API token if configured.

    Security model:
    - If API_TOKEN is not set, authentication is disabled (for local development)
    - If API_TOKEN is set, ALL requests must include valid token via X-API-Key header
    - No local bypass: once token is configured, it's always required
    - No query param support: prevents token leakage via logs/referrer

    Returns:
        True if authentication passes

    Raises:
        HTTPException: 401 if authentication fails
    """
    # If no token configured, allow all (local development mode)
    # WARNING: Never run in production without API_TOKEN set
    if not settings.api_token:
        return True

    # Token is configured: require it for ALL requests (no local bypass)
    # This prevents attacks when API is behind a reverse proxy that
    # spoofs or forwards X-Forwarded-For headers
    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API token required. Provide via X-API-Key header.",
            headers={"WWW-Authenticate": "X-API-Key"},
        )

    if api_key != settings.api_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API token",
            headers={"WWW-Authenticate": "X-API-Key"},
        )

    return True
