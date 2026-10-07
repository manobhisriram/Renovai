from __future__ import annotations

import logging

import pytest

from app.auth.security import create_token, decode_token, hash_password, verify_password
from app.observability.logging import RedactingFilter, redact
from app.utils.errors import UnauthorizedError
from tests.conftest import make_settings


def test_redaction_of_secrets_keys_and_pii():
    assert "sk-ant-abc123456789" not in redact("key sk-ant-abc123456789 used")
    out = redact("Authorization: Bearer eyJhbGciOi.abc.def")
    assert "eyJhbGciOi" not in out and "[REDACTED]" in out
    assert "eyJhbGciOi" not in redact("sent header Bearer eyJhbGciOi.abc.def to server")
    assert "priya***" not in redact("mail priya.nair@example.com") and "p***@example.com" in redact("mail priya.nair@example.com")
    assert "[PHONE]" in redact("call +91 98765 43210 now")
    assert "hunter2xyz" not in redact('{"password": "hunter2xyz"}')
    assert "topsecretvalue" not in redact("x topsecretvalue y", secrets=["topsecretvalue"])


def test_logging_filter_redacts_formatted_messages(caplog):
    f = RedactingFilter(["mysecretvalue1"])
    rec = logging.LogRecord("t", logging.INFO, "", 1, "token=%s", ("mysecretvalue1",), None)
    f.filter(rec)
    assert "mysecretvalue1" not in rec.getMessage()


def test_password_hashing_roundtrip_and_salting():
    h1, h2 = hash_password("correct horse"), hash_password("correct horse")
    assert h1 != h2 and verify_password("correct horse", h1) and not verify_password("wrong", h1)
    assert not verify_password("x", "garbage") and not verify_password("x", "md5$a$b")


def test_jwt_roundtrip_expiry_and_tamper(tmp_path):
    s = make_settings(tmp_path)
    tok = create_token(s, user_id="u1", role="admin")
    assert decode_token(s, tok)["sub"] == "u1"
    with pytest.raises(UnauthorizedError):
        decode_token(s, tok + "x")
    other = make_settings(tmp_path, secret_key="another-secret-another-secret-0123456789")
    with pytest.raises(UnauthorizedError):
        decode_token(other, tok)
    expired = make_settings(tmp_path, access_token_expire_minutes=-1)
    with pytest.raises(UnauthorizedError):
        decode_token(expired, create_token(expired, user_id="u1", role="admin"))
