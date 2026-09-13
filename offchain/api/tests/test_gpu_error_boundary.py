"""Transport failures and exception logging retain diagnostics without exposing credentials."""

import logging
import sys
from contextlib import contextmanager
from types import SimpleNamespace
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from requests.exceptions import Timeout
from web3.exceptions import (
    BadFunctionCallOutput,
    BadResponseFormat,
    ContractLogicError,
    ProviderConnectionError,
    TimeExhausted,
    Web3RPCError,
)

from hashcredit_api.gpu.app import create_app
from hashcredit_api.gpu.middleware import SECURITY_HEADERS
from hashcredit_api.gpu.permissions.deps import current_principal
from hashcredit_api.gpu.product.settings import ProductSettings
from hashcredit_api.gpu.secrets import RedactingFilter, Redactor, install_record_redaction

RPC_SECRET = "https://rpc.example.test/private/demo-credential-value"


@pytest.mark.parametrize("error_type, status", [
    (Timeout, 503), (ProviderConnectionError, 503), (TimeExhausted, 503),
    (Web3RPCError, 503), (BadResponseFormat, 503), (BadFunctionCallOutput, 503),
    (ContractLogicError, 503), (ValueError, 500), (KeyError, 500), (TypeError, 500),
])
def test_rpc_failure_is_sanitized_but_programming_error_is_not_mislabeled(error_type, status, caplog):
    settings = ProductSettings(database_url=None, chain_id=None, session_secret=None,
                               deployment_manifest=None, rpc_url=RPC_SECRET)
    app = create_app(settings)

    @contextmanager
    def session():
        yield None

    def broken_read(*_):
        raise error_type("upstream diagnostics contain " + RPC_SECRET)

    app.state.product.session = session
    app.state.product.metadata = lambda _: None
    app.state.chain.lp = broken_read
    app.dependency_overrides[current_principal] = lambda: SimpleNamespace(wallet="0x" + "12" * 20)
    with TestClient(app) as client:
        response = client.get("/v1/lp")
    assert response.status_code == status
    error = response.json()["error"]
    assert error["code"] == ("UPSTREAM_UNAVAILABLE" if status == 503 else "INTERNAL_ERROR")
    assert error["details"] == {}
    assert str(UUID(error["requestId"])) == response.headers["X-Request-ID"]
    for name, value in SECURITY_HEADERS.items():
        assert response.headers[name] == value
    assert RPC_SECRET not in response.text + caplog.text
    assert "upstream diagnostics" not in response.text
    if status == 500:
        record = next(r for r in caplog.records if "unexpected GPU API failure" in r.message)
        assert record.exc_info is None
        assert "broken_read" in record.exc_text and "[REDACTED]" in record.exc_text


def _exception_info(secret):
    try:
        try:
            raise ValueError("inner " + secret)
        except ValueError as exc:
            raise RuntimeError("outer " + secret) from exc
    except RuntimeError:
        return sys.exc_info()


def test_filter_redacts_chained_exception_and_stack_before_multiple_handlers_format():
    redactor = Redactor()
    redactor.register(RPC_SECRET)
    record = logging.LogRecord("test", logging.ERROR, __file__, 80, "request %s", (RPC_SECRET,),
                               _exception_info(RPC_SECRET), sinfo="stack diagnostics " + RPC_SECRET)
    assert RedactingFilter(redactor).filter(record)
    assert record.exc_info is None and record.args == ()
    for _ in range(2):
        formatted = logging.Formatter("%(message)s").format(record)
        assert RPC_SECRET not in formatted
        assert "ValueError: inner [REDACTED]" in formatted
        assert "RuntimeError: outer [REDACTED]" in formatted
        assert "_exception_info" in formatted
        assert "stack diagnostics [REDACTED]" in formatted


def test_factory_redacts_exception_groups_and_newly_attached_handlers(caplog):
    redactor = Redactor()
    redactor.register(RPC_SECRET)
    install_record_redaction(redactor)
    logger = logging.getLogger("gpu.regression.exception-group")
    try:
        raise ExceptionGroup("group " + RPC_SECRET, [ValueError("child " + RPC_SECRET)])
    except ExceptionGroup:
        logger.exception("failed %s", RPC_SECRET, stack_info=True)
    record = next(r for r in caplog.records if r.name == logger.name)
    assert record.exc_info is None
    assert RPC_SECRET not in logging.Formatter().format(record)
    assert "ExceptionGroup: group [REDACTED]" in record.exc_text
    assert "ValueError: child [REDACTED]" in record.exc_text


def test_filter_redacts_preformatted_exception_text_too():
    redactor = Redactor()
    redactor.register(RPC_SECRET)
    record = logging.LogRecord("test", logging.ERROR, __file__, 110, "failure", (), None)
    record.exc_text = "cached exception " + RPC_SECRET
    RedactingFilter(redactor).filter(record)
    assert RPC_SECRET not in logging.Formatter().format(record)
