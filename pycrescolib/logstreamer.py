import ssl
import time
import json
import websocket
try:
    import thread
except ImportError:
    import _thread as thread

class logstreamer(object):

    def __init__(self, host, port, callback):
        self.host = host
        self.port = port
        self.ws = None
        self.isActive = False
        self.message_count = 0
        self.callback = callback

    def on_message(self, ws, message):

        if (self.message_count == 0):
            json_incoming = json.loads(message)
            if int(json_incoming['status_code']) == 10:
                self.isActive = True
        else:
            if self.callback is not None:
                self.callback(message)
            else:
                print("Log Message = " + str(message))

        self.message_count += 1

    def update_config(self, dst_region, dst_agent):

        '''
        String region_id = sst[0];
        String agent_id = sst[1];
        String baseclass = sst[2];
        String loglevel = sst[3];

        dst_region = "global-region"
        dst_agent = "global-controller"

        '''
        #message = 'global-region,global-controller,io.cresco,Trace'
        #message = dst_region + ',' + dst_agent + ',Info,default'
        message = dst_region + ',' + dst_agent + ',Trace,default'

        self.ws.send(message)

    def on_error(self, ws, error):
        print(error)

    def on_close(self, ws):
        print("### closed logstreamer ###")

    def on_open(self, ws):
        #self.ws.send(self.stream_name)

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
            ws_url = 'wss://' + self.host + ':' + str(self.port) + '/api/logstreamer'
            websocket.enableTrace(False)
            self.ws = websocket.WebSocketApp(ws_url,
                                             on_message=self.on_message,
                                             on_error=self.on_error,
                                             on_close=self.on_close,
                                             #sslopt = {"cert_reqs": ssl.CERT_NONE},
                                             header={'cresco_service_key': 'abc-8675309'}
                                             )
            self.ws.on_open = self.on_open
            self.ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})

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