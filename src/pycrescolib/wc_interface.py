from websocket import create_connection

class ws_interface(object):

    def __init__(self):
        self.url = None
        self.ws = None

    def connect(self, url):
        self.url = url
        self.ws = create_connection(self.url)
        return self.ws.connected

    def connected(self):
        if self.ws is None:
            return False
        else:
            return self.ws.connected

    def close(self):
        if self.ws is not None:
            self.ws.close()
