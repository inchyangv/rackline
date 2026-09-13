"""
Credential handling (GPU-018).

Provider credentials are stored and transported as opaque `secretRef` strings. Only server-side code
resolves a ref to a value through a `SecretStore`; values never appear in responses, logs or fixtures.
`RedactingFilter` masks known secret values and common token shapes in every log record.
"""

from __future__ import annotations

import logging
import os
import re
import traceback
from collections.abc import Iterable
from typing import Protocol

SECRET_REF_RE = re.compile(r"^(env|vault|kms)://[A-Za-z0-9_./-]{1,200}$")

# Common credential shapes: bearer tokens, hex private keys, JWT-ish blobs, "sk_"/"key-" prefixed tokens.
_TOKEN_PATTERNS = [
    re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/=-]{16,}"),
    re.compile(r"0x[0-9a-fA-F]{64}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"(?i)\b(sk|pk|key|token|secret)[-_][A-Za-z0-9_-]{12,}"),
]
MASK = "[REDACTED]"


def is_secret_ref(value: str) -> bool:
    if not SECRET_REF_RE.match(value):
        return False
    path = value.split("://", 1)[1]
    return not any(seg in ("", ".", "..") for seg in path.split("/"))


class SecretStore(Protocol):
    def resolve(self, secret_ref: str) -> str | None:
        """Return the secret value for a ref, or None. Never log the return value."""


class EnvSecretStore:
    """Dev/test store: `env://NAME` resolves to `os.environ[NAME]`."""

    def __init__(self, environ: dict[str, str] | None = None) -> None:
        self._environ = environ if environ is not None else os.environ  # type: ignore[assignment]

    def resolve(self, secret_ref: str) -> str | None:
        if not is_secret_ref(secret_ref) or not secret_ref.startswith("env://"):
            return None
        return self._environ.get(secret_ref[len("env://") :])


class Redactor:
    """Masks registered secret values and token-like substrings."""

    def __init__(self) -> None:
        self._values: set[str] = set()

    def register(self, value: str | None) -> None:
        if value and len(value) >= 8:
            self._values.add(value)

    def redact(self, text: str) -> str:
        for v in sorted(self._values, key=len, reverse=True):
            text = text.replace(v, MASK)
        for pat in _TOKEN_PATTERNS:
            text = pat.sub(MASK, text)
        return text


class RedactingFilter(logging.Filter):
    """Mask messages, exception chains and stack traces before any handler formats them."""

    def __init__(self, redactor: Redactor) -> None:
        super().__init__()
        self._redactor = redactor

    def filter(self, record: logging.LogRecord) -> bool:
        _redact_record(record, (self._redactor,))
        return True


def _redact_record(record: logging.LogRecord, redactors: Iterable[Redactor]) -> None:
    def masked(value: str) -> str:
        for redactor in redactors:
            value = redactor.redact(value)
        return value

    try:
        record.msg = masked(record.getMessage())
        # Format without locals, retaining file/line locations and chained exception types.
        # Keeping exc_info would let another handler format the original secret-bearing object.
        if record.exc_info:
            record.exc_text = masked("".join(traceback.format_exception(*record.exc_info)))
        elif record.exc_text:
            record.exc_text = masked(record.exc_text)
        if record.stack_info:
            record.stack_info = masked(record.stack_info)
    except Exception:  # noqa: BLE001 - redaction must fail closed even for broken formatters
        record.msg = "log details unavailable after redaction"
        record.exc_text = None
        record.stack_info = None
    finally:
        record.args = ()
        record.exc_info = None


_FACTORY_INSTALLED: list[Redactor] = []


def install_record_redaction(redactor: Redactor) -> None:
    """Redact at LogRecord creation so every handler (including ones attached later) sees masked text.
    Logger-level filters do not apply to propagated records; the record factory does."""
    _FACTORY_INSTALLED.append(redactor)
    if len(_FACTORY_INSTALLED) > 1:
        return  # factory already wraps; it consults the whole list
    previous = logging.getLogRecordFactory()

    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        _redact_record(record, _FACTORY_INSTALLED)
        return record

    logging.setLogRecordFactory(factory)
