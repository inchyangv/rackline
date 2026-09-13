"""
Minimal JSON-RPC client for the dispatcher (GPU-026).

- Endpoint allowlist: only URLs listed in an Attestcoin environment manifest (`destination.rpcUrls`, or the
  source `rpcUrls` for read-only source probes) may be used; anything else is refused before a request is
  made. Logs and errors carry hostnames only, never the full URL or a query string.
- Transport is injectable (`Transport.request(method, params) -> result`) so tests use a fake EVM without a
  network; `HttpTransport` is a plain urllib POST with a timeout.
- Read-only methods need no key at all; the client never sees a private key (signing is the `Signer`'s job).
"""

from __future__ import annotations

import errno
import hashlib
import http.client
import json
import logging
import socket
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

log = logging.getLogger(__name__)

_RETRYABLE_READ_METHODS = frozenset({
    "eth_chainId", "eth_blockNumber", "eth_getBlockByNumber", "eth_getTransactionCount",
    "eth_gasPrice", "eth_call", "eth_estimateGas", "eth_getTransactionByHash",
    "eth_getTransactionReceipt", "eth_getLogs",
})
_NETWORK_ERRNOS = frozenset({
    errno.ECONNABORTED, errno.ECONNREFUSED, errno.ECONNRESET, errno.EHOSTUNREACH,
    errno.ENETDOWN, errno.ENETRESET, errno.ENETUNREACH, errno.EPIPE, errno.ETIMEDOUT,
})


class RpcError(RuntimeError):
    """JSON-RPC error object or malformed response."""

    def __init__(self, message: str, code: int | None = None):
        super().__init__(message)
        self.code = code


class RpcTransportError(RuntimeError):
    """Network-level failure or timeout. The outcome of a sent transaction is UNKNOWN, never 'failed'."""


class EndpointNotAllowed(PermissionError):
    pass


class Transport(Protocol):
    def request(self, method: str, params: Sequence[Any]) -> Any: ...


def hostname_of(url: str) -> str:
    try:
        return urlparse(url).hostname or "<invalid>"
    except ValueError:
        return "<invalid>"


def load_rpc_allowlist(
    manifest_path: str | Path, *, side: str = "destination"
) -> tuple[int, list[str]]:
    """(chainId, rpcUrls) from an Attestcoin manifest; `side` is 'destination' or 'source'."""
    m = json.loads(Path(manifest_path).read_text())
    digest = "sha256:" + hashlib.sha256(json.dumps(
        {key: value for key, value in m.items() if key != "manifestHash"},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    ).encode()).hexdigest()
    if m.get("manifestHash") != digest:
        raise EndpointNotAllowed("manifest hash mismatch")
    if m.get("executionProfile") != "LOCAL_MOCK" and (
        m.get("mock") is not False or m.get("verificationMethod") != "ATTESTCOIN_NATIVE"
        or m.get("sdk", {}).get("version") != "0.18.0"
    ):
        raise EndpointNotAllowed("native manifest binding required")
    part = m[side]
    return int(part["chainId"]), list(part["rpcUrls"])


@dataclass
class HttpTransport:
    url: str
    timeout_seconds: float = 10.0
    _id: int = field(default=0, init=False)

    def request(self, method: str, params: Sequence[Any]) -> Any:
        self._id += 1
        request_id = self._id
        body = json.dumps(
            {"jsonrpc": "2.0", "id": request_id, "method": method, "params": list(params)}
        ).encode()
        req = urllib.request.Request(
            self.url, data=body,
            # Public RPC gateways may reject urllib's default User-Agent.
            headers={"content-type": "application/json", "user-agent": "rackline-gpu/0.1"},
        )
        attempts = 3 if method in _RETRYABLE_READ_METHODS else 1
        for attempt in range(attempts):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                    raw = resp.read()
                break
            except (OSError, ValueError, http.client.IncompleteRead) as e:
                cause = e.reason if isinstance(e, urllib.error.URLError) else e
                network_failure = not isinstance(e, urllib.error.HTTPError) and (
                    isinstance(cause, (ConnectionError, TimeoutError, socket.gaierror, http.client.IncompleteRead))
                    or isinstance(cause, OSError) and cause.errno in _NETWORK_ERRNOS
                )
                if network_failure and attempt + 1 < attempts:
                    # Reuse the exact URL, body and request ID; never resend a mutation.
                    time.sleep(0.25 * (2 ** attempt))
                    continue
                raise RpcTransportError(
                    f"{method} to {hostname_of(self.url)} failed: {type(e).__name__}"
                ) from e
        try:
            payload = json.loads(raw.decode())
        except ValueError as e:
            raise RpcTransportError(
                f"{method} to {hostname_of(self.url)} failed: {type(e).__name__}"
            ) from e
        if not isinstance(payload, dict) or payload.get("id") != request_id:
            raise RpcTransportError(f"{method} returned a mismatched JSON-RPC envelope")
        if payload.get("error"):
            err = payload["error"]
            raise RpcError(f"{method} RPC error {err.get('code')}", err.get("code"))
        if "result" not in payload:
            raise RpcTransportError(f"{method} returned no result")
        return payload.get("result")


class JsonRpcClient:
    """Typed wrapper. `allowlist` is the manifest's rpcUrls; the URL must match one of them exactly."""

    def __init__(self, url: str, allowlist: Sequence[str], transport: Transport | None = None):
        if url not in set(allowlist):
            raise EndpointNotAllowed(
                f"rpc host {hostname_of(url)} is not in the manifest allowlist"
            )
        if not url.startswith("https://") and not hostname_of(url) in ("127.0.0.1", "localhost"):
            raise EndpointNotAllowed(f"rpc host {hostname_of(url)} must be https")
        self.host = hostname_of(url)
        self._t = transport or HttpTransport(url)

    def _call(self, method: str, *params: Any) -> Any:
        return self._t.request(method, params)

    # ---- reads (no key)
    def chain_id(self) -> int:
        return int(self._call("eth_chainId"), 16)

    def block_number(self) -> int:
        return int(self._call("eth_blockNumber"), 16)

    def get_block(self, number: int | str, full: bool = False) -> dict[str, Any] | None:
        tag = hex(number) if isinstance(number, int) else number
        return self._call("eth_getBlockByNumber", tag, full)

    def transaction_count(self, address: str, tag: str = "pending") -> int:
        return int(self._call("eth_getTransactionCount", address, tag), 16)

    def gas_price(self) -> int:
        return int(self._call("eth_gasPrice"), 16)

    def eth_call(self, tx: dict[str, Any], tag: str = "latest") -> str:
        return self._call("eth_call", tx, tag)

    def estimate_gas(self, tx: dict[str, Any]) -> int:
        return int(self._call("eth_estimateGas", tx), 16)

    def get_transaction(self, tx_hash: str) -> dict[str, Any] | None:
        return self._call("eth_getTransactionByHash", tx_hash)

    def get_receipt(self, tx_hash: str) -> dict[str, Any] | None:
        return self._call("eth_getTransactionReceipt", tx_hash)

    def get_logs(self, addresses: Sequence[str], start: int, end: int) -> list[dict[str, Any]]:
        return self._call(
            "eth_getLogs",
            {"address": list(addresses), "fromBlock": hex(start), "toBlock": hex(end)},
        )

    # ---- write (signed bytes only; signing happened elsewhere)
    def send_raw_transaction(self, raw_hex: str) -> str:
        return self._call("eth_sendRawTransaction", raw_hex)
