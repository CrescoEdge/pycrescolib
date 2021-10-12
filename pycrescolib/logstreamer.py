import time

import websocket
try:
    import thread
except ImportError:
    import _thread as thread

class logstreamer(object):

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.ws = None
        self.isActive = False
        self.message_count = 0

    def on_message(self, message):

        if(self.message_count == 0):
            print(message)
            self.isActive = True
        else:
            print('w ' + message)

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
        message = dst_region + ',' + dst_agent + ',Trace,default'
        self.ws.send(message)

    def on_error(self, error):
        print(error)

    def on_close(self):
        print("### closed logstreamer ###")

    def on_open(self):
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
            ws_url = 'ws://' + self.host + ':' + str(self.port) + '/api/logstreamer'
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