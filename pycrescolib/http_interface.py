import time

import requests

class http_interface(object):

    def __init__(self):
        self.url = None
        self.service_key = None
        self.isconnected = False

    def api_version(self):

        version = None
        try:
            headers = {'Content-Type': 'application/json',
                       'X-Auth-API-Service-Key': self.service_key,
                       }
            version_url = self.url + '/dashboard/api/version'

            res = requests.get(url=version_url,
                               headers=headers
                               )

            response_json = res.json()
            version = response_json['version']
        except:
            print('HTTP Client: api_version failed for ' + version_url)

        return version

    def connected(self):
        return self.isconnected


    def connect(self, url, service_key):

        try:

            if url[-1] == '/':
                url = url[:-1]

            self.url = url
            self.service_key = service_key

            if self.api_version() is not None:
                self.isconnected = True

        except:
            print('HTTP Client: Failed to connect to ' + self.url)

        return self.isconnected

    #HTTP functions
    def add_repo_plugin(self, file_path, verify=False):

        # '/Users/cody/IdeaProjects/cepdemo/target/cepdemo-1.0-SNAPSHOT.jar'
        data = open(file_path, 'rb').read()
        headers = {'Content-Type': 'application/octet-stream',
                   'X-Auth-API-Service-Key': self.service_key,
                   'Content-Type': 'application/java-archive'
                   }
        upload_url = self.http_url + '/dashboard/plugins/uploadplugin'
        res = requests.post(url=upload_url,
                            data=data,
                            headers=headers,
                            )

        plugin_info = res.json()

        if verify:

            isUploaded = False

            headers = {'Content-Type': 'application/json',
                       'X-Auth-API-Service-Key': self.service_key,
                       }
            list_url = self.http_url + '/dashboard/plugins/listrepo'

            while not isUploaded:
                res = requests.get(url=list_url,
                                   headers=headers
                                   )
                plugin_list = res.json()
                print(plugin_list)
                for plugin in plugin_list['plugins']:
                    if plugin == plugin_info:
                        isUploaded = True
                time.sleep(1)

        return plugin_info
