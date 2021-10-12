import json

class messaging(object):

    def __init__(self, ws_interface):
        self.ws_interface = ws_interface

    # WS functions
    def global_controller_msgevent(self, is_rpc, message_event_type, message_payload):
        message_info = dict()
        message_info['message_type'] = 'global_controller_msgevent'
        message_info['message_event_type'] = message_event_type
        message_info['is_rpc'] = is_rpc

        message = dict()
        message['message_info'] = message_info
        message['message_payload'] = message_payload

        #print("Sending..")
        json_message = json.dumps(message)
        #print(json_message)

        self.ws_interface.ws.send(json_message)

        if is_rpc:
            #print("Receiving...")
            json_incoming = json.loads(self.ws_interface.ws.recv())
            #print(json_incoming)
            return json_incoming
        else:
            return None

    def regional_controller_msgevent(self, is_rpc, message_event_type, message_payload):
        message_info = dict()
        message_info['message_type'] = 'regional_controller_msgevent'
        message_info['message_event_type'] = message_event_type
        message_info['is_rpc'] = is_rpc

        message = dict()
        message['message_info'] = message_info
        message['message_payload'] = message_payload

        #print("Sending..")
        json_message = json.dumps(message)
        #print(json_message)

        self.ws_interface.ws.send(json_message)

        if is_rpc:
            #print("Receiving...")
            json_incoming = json.loads(self.ws_interface.ws.recv())
            #print(json_incoming)
            return json_incoming
        else:
            return None

    def global_agent_msgevent(self, is_rpc, message_event_type, message_payload, dst_region, dst_agent):
        message_info = dict()
        message_info['message_type'] = 'global_agent_msgevent'
        message_info['message_event_type'] = message_event_type
        message_info['dst_region'] = dst_region
        message_info['dst_agent'] = dst_agent
        message_info['is_rpc'] = is_rpc

        message = dict()
        message['message_info'] = message_info
        message['message_payload'] = message_payload

        #print("Sending..")
        json_message = json.dumps(message)
        #print(json_message)

        self.ws_interface.ws.send(json_message)

        if is_rpc:
            #print("Receiving...")
            json_incoming = json.loads(self.ws_interface.ws.recv())
            #print(json_incoming)
            return json_incoming
        else:
            return None

    def regional_agent_msgevent(self, is_rpc, message_event_type, message_payload, dst_agent):
        message_info = dict()
        message_info['message_type'] = 'regional_agent_msgevent'
        message_info['message_event_type'] = message_event_type
        message_info['dst_agent'] = dst_agent
        message_info['is_rpc'] = is_rpc

        message = dict()
        message['message_info'] = message_info
        message['message_payload'] = message_payload

        #print("Sending..")
        json_message = json.dumps(message)
        #print(json_message)

        self.ws_interface.ws.send(json_message)

        if is_rpc:
            #print("Receiving...")
            json_incoming = json.loads(self.ws_interface.ws.recv())
            #print(json_incoming)
            return json_incoming
        else:
            return None

    def agent_msgevent(self, is_rpc, message_event_type, message_payload):
        message_info = dict()
        message_info['message_type'] = 'agent_msgevent'
        message_info['message_event_type'] = message_event_type
        message_info['is_rpc'] = is_rpc

        message = dict()
        message['message_info'] = message_info
        message['message_payload'] = message_payload

        #print("Sending..")
        json_message = json.dumps(message)
        #print(json_message)

        self.ws_interface.ws.send(json_message)

        if is_rpc:
            #print("Receiving...")
            json_incoming = json.loads(self.ws_interface.ws.recv())
            #print(json_incoming)
            return json_incoming
        else:
            return None

    def global_plugin_msgevent(self, is_rpc, message_event_type, message_payload, dst_region, dst_agent, dst_plugin):
        message_info = dict()
        message_info['message_type'] = 'global_plugin_msgevent'
        message_info['message_event_type'] = message_event_type
        message_info['dst_region'] = dst_region
        message_info['dst_agent'] = dst_agent
        message_info['dst_plugin'] = dst_plugin
        message_info['is_rpc'] = is_rpc

        message = dict()
        message['message_info'] = message_info
        message['message_payload'] = message_payload

        #print("Sending..")
        json_message = json.dumps(message)
        #print(json_message)

        self.ws_interface.ws.send(json_message)

        if is_rpc:
            #print("Receiving...")
            json_incoming = json.loads(self.ws_interface.ws.recv())
            #print(json_incoming)
            return json_incoming
        else:
            return None

    def regional_plugin_msgevent(self, is_rpc, message_event_type, message_payload, dst_agent, dst_plugin):
        message_info = dict()
        message_info['message_type'] = 'regional_plugin_msgevent'
        message_info['message_event_type'] = message_event_type
        message_info['dst_agent'] = dst_agent
        message_info['dst_plugin'] = dst_plugin
        message_info['is_rpc'] = is_rpc

        message = dict()
        message['message_info'] = message_info
        message['message_payload'] = message_payload

        #print("Sending..")
        json_message = json.dumps(message)
        #print(json_message)

        self.ws_interface.ws.send(json_message)

        if is_rpc:
            #print("Receiving...")
            json_incoming = json.loads(self.ws_interface.ws.recv())
            #print(json_incoming)
            return json_incoming
        else:
            return None

    def plugin_msgevent(self, is_rpc, message_event_type, message_payload, dst_plugin):
        message_info = dict()
        message_info['message_type'] = 'plugin_msgevent'
        message_info['message_event_type'] = message_event_type
        message_info['dst_plugin'] = dst_plugin
        message_info['is_rpc'] = is_rpc

        message = dict()
        message['message_info'] = message_info
        message['message_payload'] = message_payload

        #print("Sending..")
        json_message = json.dumps(message)
        #print(json_message)

        self.ws_interface.ws.send(json_message)

        if is_rpc:
            #print("Receiving...")
            json_incoming = json.loads(self.ws_interface.ws.recv())
            #print(json_incoming)
            return json_incoming
        else:
            return None
