"""
Adversarial review (review/api-20261104) of the pycrescolib TLS trust settings.

An operator pin in the environment (CRESCO_TLS_FINGERPRINT) is how GaiaKeep tooling and scripts are secured without
code changes. GaiaKeep's own example profile sets ``"verify_ssl": false`` (gaiakeep/profile.py) and passes it straight
to ``clientlib(host, port, service_key, verify_ssl)``. An explicit ``verify_ssl=False`` together with an explicit pin
is refused (TLSConfigError), but with the pin in the environment it is silently dropped: the service key then goes to
whatever server answers, despite the pin the operator set.
"""
import asyncio

import pytest

from pycrescolib import tls
from pycrescolib.tls import Credentials, TLSConfigError, TrustSettings, connect_websocket
from tests.tls_util import WssServer, make_cert


@pytest.fixture(scope="module")
def real_cert():
    return make_cert(region="region-a", agent="agent-a", plugin="plugin/7")


@pytest.fixture(scope="module")
def impostor_cert():
    return make_cert(region="evil", agent="evil", plugin="evil")


def test_an_environment_pin_is_not_silently_dropped_by_verify_ssl_false(real_cert, impostor_cert, monkeypatch):
    monkeypatch.setenv(tls.ENV_FINGERPRINT, real_cert.fingerprint("sha384"))
    monkeypatch.delenv(tls.ENV_CA_FILE, raising=False)
    with WssServer(impostor_cert) as srv:
        async def go():
            trust = TrustSettings(verify=False)          # what clientlib(host, port, key, False) builds
            ws = await connect_websocket(f"wss://127.0.0.1:{srv.port}/api/apisocket", "127.0.0.1", srv.port, trust,
                                         Credentials(service_key="sk-review-secret"))
            await ws.close()

        try:
            asyncio.run(go())
        except (TLSConfigError, ConnectionError):
            pass
        leaked = [r for r in srv.requests if r.get("cresco_service_key")]
        assert leaked == [], ("CRESCO_TLS_FINGERPRINT names the real wsapi, yet an impostor received the service key "
                              "because the code passed verify_ssl=False")
