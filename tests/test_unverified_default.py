"""Verification turned off for every connection by code (tls.VERIFY_BY_DEFAULT = False) is logged, once per process.
Before 1.5.0 it was silent: only an explicit verify_ssl=False warned."""
import asyncio
import logging

from pycrescolib import tls


def test_the_unverified_default_warns_once(monkeypatch, caplog):
    monkeypatch.delenv(tls.ENV_FINGERPRINT, raising=False)
    monkeypatch.delenv(tls.ENV_CA_FILE, raising=False)
    monkeypatch.setattr(tls, "VERIFY_BY_DEFAULT", False)
    monkeypatch.setattr(tls, "_unverified_default_warned", False)
    with caplog.at_level(logging.WARNING, logger="pycrescolib.tls"):
        for port in (1, 2, 3):
            settings = tls.TrustSettings()
            assert settings.mode == "insecure"
            asyncio.run(settings._server_trust("127.0.0.1", port, f"wss://127.0.0.1:{port}/api/apisocket", 1.0))
    warnings = [r.getMessage() for r in caplog.records if "VERIFY_BY_DEFAULT" in r.getMessage()]
    assert len(warnings) == 1 and "OFF" in warnings[0]


def test_a_verified_default_says_nothing(monkeypatch, caplog):
    monkeypatch.setattr(tls, "_unverified_default_warned", False)
    with caplog.at_level(logging.WARNING, logger="pycrescolib.tls"):
        assert tls.TrustSettings(fingerprint="sha256:" + "ab" * 32).mode == "fingerprint"
    assert not [r for r in caplog.records if "VERIFY_BY_DEFAULT" in r.getMessage()]
