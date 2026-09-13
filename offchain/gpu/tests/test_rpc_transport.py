"""HTTP compatibility for public JSON-RPC gateways, without external requests."""

import errno
import http.client
import io
import json
import ssl
import urllib.error
import urllib.request

import pytest

from hashcredit_gpu.transactions import rpc as rpc_module
from hashcredit_gpu.transactions.rpc import (
    HttpTransport,
    JsonRpcClient,
    RpcError,
    RpcTransportError,
)


def test_public_rpc_uses_product_user_agent(monkeypatch):
    endpoint = "https://ethereum-sepolia-rpc.publicnode.com"
    seen = []

    def gateway(request, *, timeout):
        # Reproduce gateways that reject the Python-urllib default agent.
        if request.get_header("User-agent") != "rackline-gpu/0.1":
            raise urllib.error.HTTPError(endpoint, 403, "Forbidden", {}, None)
        assert request.full_url == endpoint
        assert request.get_method() == "POST"
        assert request.get_header("Content-type") == "application/json"
        assert timeout == 2.5
        body = json.loads(request.data)
        seen.append(body)
        return io.BytesIO(json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": "0xaa36a7"}).encode())

    monkeypatch.setattr(urllib.request, "urlopen", gateway)
    rpc = JsonRpcClient(endpoint, [endpoint], transport=HttpTransport(endpoint, timeout_seconds=2.5))
    assert rpc.chain_id() == 11155111
    assert seen == [{"jsonrpc": "2.0", "id": 1, "method": "eth_chainId", "params": []}]


def mock_http(monkeypatch, outcomes):
    pending = iter(outcomes)
    requests, delays = [], []

    def gateway(request, *, timeout):
        requests.append((request.full_url, request.data, timeout))
        outcome = next(pending)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(urllib.request, "urlopen", gateway)
    monkeypatch.setattr(rpc_module.time, "sleep", delays.append)
    return requests, delays


def response(payload):
    return io.BytesIO(json.dumps(payload).encode())


class ReadTimeout(io.BytesIO):
    def read(self, *args):
        raise TimeoutError("read timed out")


@pytest.mark.parametrize("failure", [
    TimeoutError("connect timed out"), ConnectionResetError("connection reset"),
    urllib.error.URLError(TimeoutError("connect timed out")),
    urllib.error.URLError(OSError(errno.ENETUNREACH, "network unreachable")),
    http.client.RemoteDisconnected("remote closed connection"),
    http.client.IncompleteRead(b"partial response"),
])
def test_read_network_failure_retries_with_same_endpoint_body_and_id(monkeypatch, failure):
    requests, delays = mock_http(monkeypatch, [failure, failure,
        response({"jsonrpc": "2.0", "id": 1, "result": "0x1"}),
        response({"jsonrpc": "2.0", "id": 2, "result": "0x2"})])
    transport = HttpTransport("https://rpc.example.test", timeout_seconds=2)
    assert transport.request("eth_chainId", []) == "0x1"
    assert requests[0] == requests[1] == requests[2]
    assert delays == [0.25, 0.5]
    assert transport.request("eth_blockNumber", []) == "0x2"
    assert [json.loads(request[1])["id"] for request in requests] == [1, 1, 1, 2]


def test_read_timeout_during_response_body_retries(monkeypatch):
    requests, delays = mock_http(monkeypatch, [ReadTimeout(),
        response({"jsonrpc": "2.0", "id": 1, "result": []})])
    assert HttpTransport("https://rpc.example.test").request("eth_getLogs", [{}]) == []
    assert len(requests) == 2 and delays == [0.25]


def test_read_network_retries_stop_after_three_attempts(monkeypatch):
    requests, delays = mock_http(monkeypatch, [TimeoutError("timeout") for _ in range(3)])
    with pytest.raises(RpcTransportError, match="TimeoutError"):
        HttpTransport("https://rpc.example.test").request("eth_getBlockByNumber", ["0x1", False])
    assert len(requests) == 3 and delays == [0.25, 0.5]


@pytest.mark.parametrize("method", ["eth_sendRawTransaction", "eth_sendTransaction", "eth_newFilter", "unknown_method"])
def test_mutations_and_methods_outside_read_allowlist_never_retry(monkeypatch, method):
    requests, delays = mock_http(monkeypatch, [TimeoutError("unknown submission outcome")])
    with pytest.raises(RpcTransportError):
        HttpTransport("https://rpc.example.test").request(method, [])
    assert len(requests) == 1 and delays == []


@pytest.mark.parametrize("payload,error", [
    ({"jsonrpc": "2.0", "id": 99, "result": "0x1"}, RpcTransportError),
    ({"jsonrpc": "2.0", "id": 1}, RpcTransportError),
    ({"jsonrpc": "2.0", "id": 1, "error": {"code": -32000, "message": "reverted"}}, RpcError),
])
def test_rpc_error_or_invalid_envelope_never_retries(monkeypatch, payload, error):
    requests, delays = mock_http(monkeypatch, [response(payload)])
    with pytest.raises(error):
        HttpTransport("https://rpc.example.test").request("eth_call", [{}, "latest"])
    assert len(requests) == 1 and delays == []


def test_malformed_json_never_retries(monkeypatch):
    requests, delays = mock_http(monkeypatch, [io.BytesIO(b"not json")])
    with pytest.raises(RpcTransportError, match="JSONDecodeError"):
        HttpTransport("https://rpc.example.test").request("eth_chainId", [])
    assert len(requests) == 1 and delays == []


@pytest.mark.parametrize("status", [401, 403, 429, 500, 503])
def test_http_errors_never_retry(monkeypatch, status):
    endpoint = "https://rpc.example.test"
    requests, delays = mock_http(monkeypatch, [urllib.error.HTTPError(endpoint, status, "HTTP failure", {}, None)])
    with pytest.raises(RpcTransportError, match="HTTPError"):
        HttpTransport(endpoint).request("eth_chainId", [])
    assert len(requests) == 1 and delays == []


def test_tls_authentication_failure_never_retries(monkeypatch):
    failure = urllib.error.URLError(ssl.SSLCertVerificationError(1, "certificate verification failed"))
    requests, delays = mock_http(monkeypatch, [failure])
    with pytest.raises(RpcTransportError):
        HttpTransport("https://rpc.example.test").request("eth_chainId", [])
    assert len(requests) == 1 and delays == []
