import json
import time
import websocket

try:
    import thread
except ImportError:
    import _thread as thread

class dataplane(object):

    def __init__(self, host, port, stream_name, callback):
        self.host = host
        self.port = port
        self.stream_name = stream_name
        self.ws = None
        self.isActive = False
        self.message_count = 0
        self.callback = callback

    def on_message(self, ws, message):

        if(self.message_count == 0):
            json_incoming = json.loads(message)
            if int(json_incoming['status_code']) == 10:
                self.isActive = True
        else:
            if self.callback is not None:
                self.callback(message)
            else:
                print("DP Message = " + str(message))
                print("DP Message Type = " + str(type(message)))

        self.message_count += 1

    def on_error(self, ws, error):
        print(error)

    def on_close(self, ws):
        print("### closed dataplane ###")

    def on_open(self, ws):
        self.ws.send(self.stream_name)

    def close(self):
        self.ws.close()

    def connect(self):

        def run(*args):
            ws_url = 'ws://' + self.host + ':' + str(self.port) + '/api/dataplane'
            websocket.enableTrace(False)
            self.ws = websocket.WebSocketApp(ws_url,
                                             on_message=self.on_message,
                                             on_error=self.on_error,
                                             on_close=self.on_close)
            self.ws.on_open = self.on_open
            self.ws.run_forever()

        thread.start_new_thread(run, ())

        while not self.isActive:
            time.sleep(1)

