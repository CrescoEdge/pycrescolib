"""
Local (non-wire) method tests.

Some public methods do not emit a wire message (they return client-side state), so they are not
in the conformance corpus. They are covered here for parity with the Java LocalMethodsTest.
"""
from pycrescolib.dataplane import dataplane

METRIC_KEYS = {'stream_name', 'messages_received', 'messages_sent', 'bytes_received', 'bytes_sent', 'active'}


def test_dataplane_get_metrics_keys():
    dp = dataplane('localhost', 8282, 'my-stream', 'key')
    m = dp.get_metrics()
    assert set(m) == METRIC_KEYS
    assert m['stream_name'] == 'my-stream'
    assert m['messages_sent'] == 0
    assert m['bytes_sent'] == 0
    assert m['messages_received'] == 0
    assert m['bytes_received'] == 0
    assert m['active'] is False
