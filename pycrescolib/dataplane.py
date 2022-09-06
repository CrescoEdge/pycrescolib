import json
import ssl
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

    def is_active(self):
        return self.isActive

    def on_data(self, ws, incoming_string, data_type, continue_flag):
        print('on_data message: incoming_string' + str(incoming_string) + ' data_type:' + str(data_type) + ' continue_flag: ' + str(continue_flag))

    def on_message(self, ws, message):

        if not self.isActive:
            try:
                json_incoming = json.loads(message)
                if int(json_incoming['status_code']) == 10:
                    self.isActive = True
            except:
                print('DP Activation failure: ' + str(message))

        else:
            if self.callback is not None:
                self.callback(message)
            else:
                print("DP Message = " + str(message))
                print("DP Message Type = " + str(type(message)))

        self.message_count += 1

    def on_error(self, ws, error):
        print(error)

    def on_close(self, ws, close_code, close_desc):

        print('closed dp_id: ' + str(self.dp_id))

        if (close_code is not None) and (close_desc is not None):
            print('dp closed: code:' + str(close_code) + ' desc: ' + str(close_desc))

    def on_open(self, ws):
        self.ws.send(self.stream_name)

    def close(self):
        self.ws.close()

    def send(self, data):
        if(self.isActive):
            self.ws.send(data)
        else:
            print('send(): not sending, not active')

    def connect(self):

        def run(*args):
            ws_url = 'wss://' + self.host + ':' + str(self.port) + '/api/dataplane'
            websocket.enableTrace(False)
            self.ws = websocket.WebSocketApp(ws_url,
                                             on_message=self.on_message,
                                             #on_data=self.on_data,
                                             on_error=self.on_error,
                                             on_close=self.on_close,
                                             #sslopt={"cert_reqs": ssl.CERT_NONE},
                                             header={'cresco_service_key': 'abc-8675309'}
                                             )
            self.ws.on_open = self.on_open
            self.ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})

        thread.start_new_thread(run, ())

        while not self.isActive:
            time.sleep(1)

