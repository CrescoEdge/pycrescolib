"""Second review: a refusal that arrives on a RECONNECT (not the first connect) is never surfaced to a receiver."""
from pycrescolib.dataplane import dataplane, STATUS_SUBSCRIPTION_REFUSED

REFUSAL = {"status_code": str(STATUS_SUBSCRIPTION_REFUSED), "status_desc": "Subscription refused: x", "subscription": "refused"}

def test_refusal_on_reconnect_is_surfaced_to_a_receiver():
    got = []
    dp = dataplane('localhost', 8282, 'stream', 'key', callback=got.append)
    dp._on_activation({"status_code": "10"})           # first session: active, connect() returned True
    # reconnect path (_connect): resets message_count/isActive/subscription_refused, then the first frame:
    dp.message_count = 0; dp.isActive = False; dp.subscription_refused = None
    dp._on_activation(REFUSAL)
    print("after a refused re-subscription: is_active() =", dp.is_active(), "subscription_refused =", dp.subscription_refused)
    assert not dp.is_active(), "a receiver whose re-subscription was refused still reports is_active() and gets no error"
