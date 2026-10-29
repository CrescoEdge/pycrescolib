"""A refused dataplane subscription (wsapi status 40) is a typed error for a receiver; a sender carries on."""
import pytest

from pycrescolib.dataplane import dataplane, DataplaneSubscriptionRefused, STATUS_SUBSCRIPTION_REFUSED

REFUSAL = {"status_code": str(STATUS_SUBSCRIPTION_REFUSED),
           "status_desc": "Subscription refused: selector asks for the stream of recipient rgA_a1",
           "subscription": "refused"}


def test_a_receiver_gets_a_typed_error():
    told = []
    dp = dataplane('localhost', 8282, 'stream', 'key', callback=lambda m: None, refused_callback=told.append)
    dp._on_activation(REFUSAL)
    assert not dp.is_active()
    assert told == [REFUSAL["status_desc"]]
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


def test_every_refusal_is_reported_including_reconnects():
    told = []
    dp = dataplane('localhost', 8282, 'stream', 'key', binary_callback=lambda b: None, refused_callback=told.append)
    dp._on_activation({"status_code": "10"})
    assert dp.is_active()
    for _ in range(2):                                   # two reconnects, both refused
        dp.message_count = 0; dp.isActive = False; dp.subscription_refused = None
        dp._on_activation(REFUSAL)
        assert not dp.is_active()
    assert told == [REFUSAL["status_desc"]] * 2
