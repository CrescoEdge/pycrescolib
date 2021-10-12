import json
import time
import websocket

try:
    import thread
except ImportError:
    import _thread as thread

class dataplane(object):

    def __init__(self, host, port, stream_name):
        self.host = host
        self.port = port
        self.stream_name = stream_name
        self.ws = None
        self.isActive = False
        self.message_count = 0

    def on_message(self, ws, message):

        if(self.message_count == 0):
            json_incoming = json.loads(message)
            if int(json_incoming['status_code']) == 10:
                self.isActive = True
        else:
            print(self.stream_name + ' ' + message)
            print(type(message))

        self.message_count += 1

    def on_error(self, ws, error):
        print(error)

    def on_close(self, ws):
        print("### closed dataplane ###")

    def on_open(self, ws):
        self.ws.send(self.stream_name)

        '''
        def run(*args):
            self.ws.send(self.stream_name)
            for i in range(30):
                time.sleep(1)
                # ws.send("Hello %d" % i)
                # ws.send("cat")
            time.sleep(1)
            self.ws.close()
            print("thread terminating...")

        thread.start_new_thread(run, ())
        '''

        #def run(*args):
        #    self.ws.send(self.stream_name)

        #thread.start_new_thread(run, ())


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

        '''
        ws_url = 'ws://' + self.host + ':' + str(self.port) +'/api/dataplane'
        websocket.enableTrace(True)
        self.ws = websocket.WebSocketApp(ws_url,
                                    on_message=self.on_message,
                                    on_error=self.on_error,
                                    on_close=self.on_close)
        self.ws.on_open = self.on_open
        self.ws.run_forever()
        '''
