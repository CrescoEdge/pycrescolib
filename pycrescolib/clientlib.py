import traceback

from pycrescolib.admin import admin
from pycrescolib.agents import agents
from pycrescolib.dataplane import dataplane
from pycrescolib.globalcontroller import globalcontroller
from pycrescolib.logstreamer import logstreamer
from pycrescolib.messaging import messaging
from pycrescolib.wc_interface import ws_interface
import ssl

try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    # Legacy Python that doesn't verify HTTPS certificates by default
    pass
else:
    # Handle target environment that doesn't support HTTPS verification
    ssl._create_default_https_context = _create_unverified_https_context

class clientlib(object):

    def __init__(self,host, port, service_key):
        self.host = host
        self.port = port
        self.service_key = service_key
        self.ws_interface = ws_interface()
        self.messaging = messaging(self.ws_interface)
        self.agents = agents(self.messaging)
        self.admin = admin(self.messaging)
        self.globalcontroller = globalcontroller(self.messaging)

    def connect(self):
        try:
            ws_url = 'wss://' + self.host + ':' + str(self.port) +'/api/apisocket'
            isWSConnected = self.ws_interface.connect(ws_url)
            return isWSConnected
        except:
            traceback.print_exc()
            return False

    def connected(self):
        try:
            return self.ws_interface.connected()
        except:
            return False

    def close(self):
        if self.ws_interface.connected():
            self.ws_interface.close()

    def get_dataplane(self, stream_name, callback=None):
        return dataplane(self.host, self.port, stream_name, callback)

    def get_logstreamer(self, callback=None):
        return logstreamer(self.host, self.port, callback)




