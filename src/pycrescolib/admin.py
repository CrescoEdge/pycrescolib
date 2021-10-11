
class admin(object):

    def __init__(self, messaging):
        self.messaging = messaging


    def stopcontroller(self, dst_region, dst_agent):

        message_event_type = 'CONFIG'
        message_payload = dict()
        message_payload['action'] = 'stopcontroller'


        self.messaging.global_agent_msgevent(False, message_event_type, message_payload, dst_region, dst_agent)

    def restartcontroller(self, dst_region, dst_agent):

        message_event_type = 'CONFIG'
        message_payload = dict()
        message_payload['action'] = 'restartcontroller'


        self.messaging.global_agent_msgevent(False, message_event_type, message_payload, dst_region, dst_agent)


    def restartframework(self, dst_region, dst_agent):

        message_event_type = 'CONFIG'
        message_payload = dict()
        message_payload['action'] = 'restartframework'


        self.messaging.global_agent_msgevent(False, message_event_type, message_payload, dst_region, dst_agent)

    def killjvm(self, dst_region, dst_agent):

        message_event_type = 'CONFIG'
        message_payload = dict()
        message_payload['action'] = 'killjvm'


        self.messaging.global_agent_msgevent(False, message_event_type, message_payload, dst_region, dst_agent)
