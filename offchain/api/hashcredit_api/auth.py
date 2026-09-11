"""
Simple token-based authentication for the API.
"""

from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import APIKeyHeader

from .config import Settings, get_settings


# API key can be passed via header or query param
api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


async def verify_api_token(
    request: Request,
    api_key: Optional[str] = Depends(api_key_header),
    settings: Settings = Depends(get_settings),
) -> bool:
    """
    Verify API token if configured.

    Security model:
    - If API_TOKEN is not set, authentication is disabled (local use)
    - If API_TOKEN is set, all requests must include valid token
    - Token can be passed via X-API-Key header or api_key query param

    For local development (127.0.0.1), authentication is optional
    even if token is configured.
    """
    # Get token from header or query param
    token = api_key or request.query_params.get("api_key")

    # If no token configured, allow all (local use only)
    if not settings.api_token:
        return True

    # Allow local requests without token (for development convenience)
    client_host = request.client.host if request.client else None
    if client_host in ("127.0.0.1", "localhost", "::1"):
        # Still verify if token is provided
        if token and token != settings.api_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid API token",
            )
        return True

    # For non-local requests, token is required
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API token required. Provide via X-API-Key header or api_key query param.",
        )

    if token != settings.api_token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API token",
        )

    return True
