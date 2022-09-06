import json

from pycrescolib.utils import compress_param, decompress_param, get_jar_info, encode_data


class agents(object):

    def __init__(self, messaging):
        self.messaging = messaging

    def is_controller_active(self, dst_region, dst_agent):

        message_event_type = 'EXEC'
        message_payload = dict()
        message_payload['action'] = 'iscontrolleractive'

        reply = self.messaging.global_agent_msgevent(True, message_event_type, message_payload, dst_region, dst_agent)
        reply = bool(reply['is_controller_active'])

        return reply

    def get_controller_status(self, dst_region, dst_agent):

        message_event_type = 'EXEC'
        message_payload = dict()
        message_payload['action'] = 'getcontrollerstatus'

        reply = self.messaging.global_agent_msgevent(True, message_event_type, message_payload, dst_region, dst_agent)
        reply = reply['controller_status']

        return reply

    def add_plugin_agent(self, dst_region, dst_agent, configparams, edges):

        # "configparams"
        '''
        configparams = dict()
        configparams['inode_id'] = 'api-' + str(uuid.uuid1())
        configparams['pluginname'] = 'io.cresco.cepdemo'
        configparams['version'] = '1.0.0.SNAPSHOT-2020-09-01T203900Z'
        configparams['md5'] = '34de550afdac3bcabbbac99ea5a1519c'
        configparams['jarfile'] = configparams['md5']
        configparams['mode'] = '0'
        '''

        message_event_type = 'CONFIG'
        message_payload = dict()
        message_payload['action'] = 'pluginadd'
        message_payload['configparams'] = compress_param(json.dumps(configparams))

        if edges is not None:
            message_payload['edges'] = compress_param(json.dumps(edges))

        reply = self.messaging.global_agent_msgevent(True, message_event_type, message_payload, dst_region, dst_agent)

        # returns reply with status and pluginid
        return reply

    def remove_plugin_agent(self, dst_region, dst_agent, plugin_id):

        message_event_type = 'CONFIG'
        message_payload = dict()
        message_payload['action'] = 'pluginremove'
        message_payload['pluginid'] = plugin_id
        # dst_region = 'global-region'
        # dst_agent = 'global-controller'

        reply = self.messaging.global_agent_msgevent(True, message_event_type, message_payload, dst_region, dst_agent)
        # return reply with status code and pluginid
        return reply

    def list_plugin_agent(self, dst_region, dst_agent):

        message_event_type = 'CONFIG'
        message_payload = dict()
        message_payload['action'] = 'pluginlist'

        reply = self.messaging.global_agent_msgevent(True, message_event_type, message_payload, dst_region, dst_agent)
        reply = json.loads(decompress_param(reply['plugin_list']))
        return reply

    def status_plugin_agent(self, dst_region, dst_agent, plugin_id):

        message_event_type = 'CONFIG'
        message_payload = dict()
        message_payload['action'] = 'pluginstatus'
        message_payload['pluginid'] = plugin_id

        reply = self.messaging.global_agent_msgevent(True, message_event_type, message_payload, dst_region, dst_agent)
        #print(reply)
        #reply = json.loads(decompress_param(reply['plugin_status']))
        return reply

    def get_agent_info(self, dst_region, dst_agent):

        message_event_type = 'CONFIG'
        message_payload = dict()
        message_payload['action'] = 'getagentinfo'

        reply = self.messaging.global_agent_msgevent(True, message_event_type, message_payload, dst_region, dst_agent)
        reply = reply['agent-data']
        return reply

    def get_agent_log(self, dst_region, dst_agent):

        message_event_type = 'EXEC'
        message_payload = dict()
        message_payload['action'] = 'getlog'

        reply = self.messaging.global_agent_msgevent(True, message_event_type, message_payload, dst_region, dst_agent)
        #reply = reply['agent-data']
        return reply


    def repo_pull_plugin_agent(self, dst_region, dst_agent, jar_file_path):

        #get data from jar
        configparams = get_jar_info(jar_file_path)

        # "configparams"
        '''
        configparams = dict()
        configparams['pluginname'] = 'io.cresco.cepdemo'
        configparams['version'] = '1.0.0.SNAPSHOT-2020-09-01T203900Z'
        configparams['md5'] = '34de550afdac3bcabbbac99ea5a1519c'
        '''

        message_event_type = 'CONFIG'
        message_payload = dict()
        message_payload['action'] = 'pluginrepopull'
        message_payload['configparams'] = compress_param(json.dumps(configparams))


        reply = self.messaging.global_agent_msgevent(True, message_event_type, message_payload, dst_region, dst_agent)

        # returns reply with status and pluginid
        return reply

    def upload_plugin_agent(self, dst_region, dst_agent, jar_file_path):

        #get data from jar
        configparams = get_jar_info(jar_file_path)

        # "configparams"
        '''
        configparams = dict()
        configparams['pluginname'] = 'io.cresco.cepdemo'
        configparams['version'] = '1.0.0.SNAPSHOT-2020-09-01T203900Z'
        configparams['md5'] = '34de550afdac3bcabbbac99ea5a1519c'
        '''

        #read input file
        in_file = open(jar_file_path, "rb")  # opening for [r]eading as [b]inary
        jar_data = in_file.read()  # if you only wanted to read 512 bytes, do .read(512)
        in_file.close()

        message_event_type = 'CONFIG'
        message_payload = dict()
        message_payload['action'] = 'pluginupload'
        message_payload['configparams'] = compress_param(json.dumps(configparams))
        message_payload['jardata'] = encode_data(jar_data)


        reply = self.messaging.global_agent_msgevent(True, message_event_type, message_payload, dst_region, dst_agent)

        # returns reply with status and pluginid
        return reply

    def update_plugin_agent(self, dst_region, dst_agent, jar_file_path):

        message_event_type = 'CONFIG'
        message_payload = dict()
        message_payload['action'] = 'controllerupdate'
        message_payload['jar_file_path'] = jar_file_path

        reply = self.messaging.global_agent_msgevent(False, message_event_type, message_payload, dst_region, dst_agent)

        # returns reply with status and pluginid
        return reply

    def get_broadcast_discovery(self, dst_region, dst_agent):

        message_event_type = 'EXEC'
        message_payload = dict()
        message_payload['action'] = 'getbroadcastdiscovery'

        # dst_region = 'global-region'
        # dst_agent = 'global-controller'

        reply = self.messaging.global_agent_msgevent(True, message_event_type, message_payload, dst_region, dst_agent)
        # return reply with status code and pluginid
        return reply

    def cepadd(self, input_stream, input_stream_desc, output_stream, output_stream_desc, query, dst_region, dst_agent):


        cepparams = dict()
        cepparams['input_stream'] = input_stream
        cepparams['input_stream_desc'] = input_stream_desc
        cepparams['output_stream'] = output_stream
        cepparams['output_stream_desc'] = output_stream_desc
        cepparams['query'] = query

        message_event_type = 'CONFIG'
        message_payload = dict()
        message_payload['action'] = 'cepadd'
        message_payload['cepparams'] = compress_param(json.dumps(cepparams))

        print(cepparams)
        reply = self.messaging.global_agent_msgevent(True, message_event_type, message_payload, dst_region, dst_agent)

        print(reply)
        return reply

