import json

from pycrescolib.utils import decompress_param, get_jar_info, compress_param, encode_data


class globalcontroller(object):

    def __init__(self, messaging):
        self.messaging = messaging

    def submit_pipeline(self, cadl):

        message_event_type = 'CONFIG'
        message_payload = dict()
        message_payload['action'] = 'gpipelinesubmit'
        message_payload['action_gpipeline'] = compress_param(json.dumps(cadl))
        message_payload['action_tenantid'] = '0'

        retry = self.messaging.global_controller_msgevent(True, message_event_type, message_payload)
        # returns status and gpipeline_id
        return retry

    def remove_pipeline(self, pipeline_id):

        message_event_type = 'CONFIG'
        message_payload = dict()
        message_payload['action'] = 'gpipelineremove'
        message_payload['action_pipelineid'] = pipeline_id
        retry = self.messaging.global_controller_msgevent(True, message_event_type, message_payload)

        return retry

    def get_pipeline_list(self):

        message_event_type = 'EXEC'
        message_payload = dict()
        message_payload['action'] = 'getgpipelinestatus'

        reply = self.messaging.global_controller_msgevent(True, message_event_type, message_payload)
        reply = json.loads(decompress_param(reply['pipelineinfo']))['pipelines']

        return reply

    def get_pipeline_info(self, pipeline_id):

        message_event_type = 'EXEC'
        message_payload = dict()
        message_payload['action'] = 'getgpipeline'
        message_payload['action_pipelineid'] = pipeline_id

        reply = self.messaging.global_controller_msgevent(True, message_event_type, message_payload)
        reply = json.loads(decompress_param(reply['gpipeline']))

        return reply

    def get_pipeline_status(self, pipeline_id):

        reply = self.get_pipeline_info(pipeline_id)
        status_code = int(reply['status_code'])
        return status_code

    def get_agent_list(self, dst_region=None):

        message_event_type = 'EXEC'
        message_payload = dict()
        message_payload['action'] = 'listagents'
        if dst_region is not None:
            message_payload['action_region'] = dst_region

        reply = self.messaging.global_controller_msgevent(True, message_event_type, message_payload)

        reply = json.loads(decompress_param(reply['agentslist']))['agents']

        '''
        for agent in reply:
            dst_agent = agent['name']
            dst_region = agent['region']
            r = self.get_agent_resources(dst_region,dst_agent)
            print(r)
        '''

        return reply

    def get_agent_resources(self, dst_region, dst_agent):

        message_event_type = 'EXEC'
        message_payload = dict()
        message_payload['action'] = 'resourceinfo'
        message_payload['action_region'] = dst_region
        message_payload['action_agent'] = dst_agent

        reply = self.messaging.global_controller_msgevent(True, message_event_type, message_payload)

        reply = json.loads(json.loads(decompress_param(reply['resourceinfo']))['agentresourceinfo'][0]['perf'])

        return reply

    def get_plugin_list(self):
        # this code makes use of a global message to find a specific plugin type, then send a message to that plugin
        message_event_type = 'EXEC'
        message_payload = dict()
        message_payload['action'] = 'listplugins'

        result = self.messaging.global_controller_msgevent(message_event_type, message_payload)

        pluginslist = json.loads(decompress_param(result['pluginslist']))

        plugin_name = 'io.cresco.repo'
        pluginlist = pluginslist['plugins']
        for plugin in pluginlist:
            if plugin['pluginname'] == plugin_name:
                break;

        message_payload['action'] = 'repolist'
        for i in range(10):
            result = self.messaging.global_plugin_msgevent(True, message_event_type, message_payload, plugin['region'], plugin['agent'], plugin['name'])
            print(result)

    def upload_plugin_global(self, jar_file_path):

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
        message_payload['action'] = 'savetorepo'
        message_payload['configparams'] = compress_param(json.dumps(configparams))
        message_payload['jardata'] = encode_data(jar_data)

        reply = self.messaging.global_controller_msgevent(True, message_event_type, message_payload)

        # returns reply with status and pluginid
        return reply

    def get_region_resources(self, dst_region):

        message_event_type = 'EXEC'
        message_payload = dict()
        message_payload['action'] = 'resourceinfo'
        message_payload['action_region'] = dst_region

        reply = self.messaging.global_controller_msgevent(True, message_event_type, message_payload)

        #reply = json.loads(json.loads(decompress_param(reply['resourceinfo']))['agentresourceinfo'][0]['perf'])
        reply = json.loads(decompress_param(reply['resourceinfo']))

        return reply

    def get_region_list(self):

        message_event_type = 'EXEC'
        message_payload = dict()
        message_payload['action'] = 'listregions'

        reply = self.messaging.global_controller_msgevent(True, message_event_type, message_payload)
        reply = json.loads(decompress_param(reply['regionslist']))['regions']

        return reply