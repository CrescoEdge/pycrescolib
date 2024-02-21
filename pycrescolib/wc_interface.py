import ssl

from websocket import create_connection

class ws_interface(object):

    def __init__(self):
        self.url = None
        self.ws = None
        self.cresco_service_key = None

    def connect(self, url, cresco_service_key):
        self.url = url
        self.cresco_service_key = cresco_service_key
        self.ws = create_connection(self.url, sslopt={"cert_reqs": ssl.CERT_NONE}, header={'cresco_service_key': self.cresco_service_key})
        return self.ws.connected

    def connected(self):
        if self.ws is None:
            return False
        else:
            return self.ws.connected

    def close(self):
        if self.ws is not None:
            self.ws.close()
