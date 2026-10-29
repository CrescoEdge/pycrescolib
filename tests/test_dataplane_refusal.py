"""A refused dataplane subscription (wsapi status 40) is a typed error for a receiver; a sender carries on."""
import pytest

from pycrescolib.dataplane import dataplane, DataplaneSubscriptionRefused, STATUS_SUBSCRIPTION_REFUSED

REFUSAL = {"status_code": str(STATUS_SUBSCRIPTION_REFUSED),
           "status_desc": "Subscription refused: selector asks for the stream of recipient rgA_a1",
           "subscription": "refused"}


def test_a_receiver_gets_a_typed_error():
    dp = dataplane('localhost', 8282, 'stream', 'key', callback=lambda m: None)
    dp._on_activation(REFUSAL)
    with pytest.raises(DataplaneSubscriptionRefused) as e:
        dp._raise_if_refused()
    assert e.value.reason == REFUSAL["status_desc"]
    assert e.value.stream_name == 'stream'


def test_a_sender_stays_open_for_sending():
    dp = dataplane('localhost', 8282, 'stream', 'key')
    dp._on_activation(REFUSAL)
    dp._raise_if_refused()
    assert dp.is_active()
    assert dp.subscription_refused == REFUSAL["status_desc"]


def test_an_active_listener_is_not_refused():
    dp = dataplane('localhost', 8282, 'stream', 'key', callback=lambda m: None)
    dp._on_activation({"status_code": "10", "status_desc": "Listener Active"})
    dp._raise_if_refused()
    assert dp.is_active()
    assert dp.subscription_refused is None
