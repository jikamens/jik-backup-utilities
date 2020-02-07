import base64
import requests
import time


class B2API(object):
    api_path = '/b2api/v1/'
    api_url = 'https://api.backblazeb2.com/b2api/v1/'
    sleep_max = 10

    def __init__(self, account_id, account_key, logger=None):
        self.logger = logger
        self.account_id = account_id
        self.account_key = account_key
        self.connect()
        self._sleep_for = 1

    def sleep_for(self):
        ret = self._sleep_for
        self._sleep_for = min(self._sleep_for * 2, self.sleep_max)
        return ret

    def reset_sleep_for(self):
        self._sleep_for = 1

    def connect(self):
        id_and_key = self.account_id + ':' + self.account_key
        basic_auth_string = 'Basic ' + \
            base64.b64encode(str.encode(id_and_key)).decode()
        headers = {'Authorization': basic_auth_string}
        while True:
            try:
                response = requests.get(self.api_url + 'b2_authorize_account',
                                        headers=headers)
            except requests.exceptions.ConnectionError:
                sleep_for = self.sleep_for()
                self.logger.info('B2 login connection error, sleeping for {} '
                                 'seconds and retrying'.format(sleep_for))
                time.sleep(sleep_for)
                continue
            if response.status_code == 429:
                sleep_for = self.sleep_for()
                self.logger.info('B2 login throttled, sleeping for {} seconds '
                                 'and retrying'.format(sleep_for))
                time.sleep(sleep_for)
                continue
            response.raise_for_status()
            break
        data = response.json()
        self.api_url = data['apiUrl'] + self.api_path
        self.authorization_token = data['authorizationToken']
        self.download_url = data['downloadUrl'] + self.api_path
        if self.logger:
            self.logger.debug(
                'Logged into Backblaze account {}, API URL is {}',
                self.account_id, self.api_url)
        self.reset_sleep_for()

    def call(self, api_call, params, api_url=None, raw_content=False):
        headers = {'Authorization': self.authorization_token}
        api_url = self.api_url if api_url is None else api_url
        try:
            response = requests.post(api_url + api_call,
                                     headers=headers, json=params)
        except requests.exceptions.ConnectionError:
            sleep_for = self.sleep_for()
            self.logger.info('B2 connection error, sleeping for {} seconds, '
                             'reconnecting and retrying {}'.format(
                                 sleep_for, api_call))
            time.sleep(sleep_for)
            self.connect()
            return self.call(api_call, params)
        if response.status_code == 429:
            sleep_for = self.sleep_for()
            self.logger.info('API is throttled, sleeping for {} seconds and '
                             'retrying {}'.format(sleep_for, api_call))
            time.sleep(sleep_for)
            return self.call(api_call, params)
        try:
            response.raise_for_status()
        except:  # NOQA
            print(response.content)
            raise
        if self.logger:
            self.logger.debug('Successfully called {} with parameters {}',
                              api_call, params)
        self.reset_sleep_for()
        return response.content if raw_content else response.json()

    def list_buckets(self, bucket_types=None, bucket_name=None):
        params = {'accountId': self.account_id}
        if bucket_types:
            params['bucketTypes'] = bucket_types
        if bucket_name:
            params['bucketName'] = bucket_name
        response = self.call('b2_list_buckets', params)
        return response['buckets']

    # This is an iterator
    def list_file_names(self, bucket_id, start_file_name=None,
                        max_file_count=1000, prefix=None, delimiter=None):
        params = {'bucketId': bucket_id, 'maxFileCount': max_file_count}
        if start_file_name:
            params['startFileName'] = start_file_name
        if prefix:
            params['prefix'] = prefix
        if delimiter:
            params['delimiter'] = delimiter
        while True:
            response = self.call('b2_list_file_names', params)
            for file in response['files']:
                yield file
            if 'nextFileName' not in response or not response['nextFileName']:
                break
            params['startFileName'] = response['nextFileName']

    # This is an iterator
    def list_file_versions(self, bucket_id, prefix=None, delimiter=None,
                           startFileName=None):
        params = {'bucketId': bucket_id, 'maxFileCount': 1000}
        if prefix:
            params['prefix'] = prefix
        if delimiter:
            params['delimiter'] = delimiter
        if startFileName:
            params['startFileName'] = startFileName
        while True:
            response = self.call('b2_list_file_versions', params)
            for file in response['files']:
                yield file
            if 'nextFileName' not in response or not response['nextFileName']:
                break
            params['startFileName'] = response['nextFileName']
            params['startFileId'] = response['nextFileId']

    def delete_file_version(self, file_name, file_id):
        params = {'fileName': file_name, 'fileId': file_id}
        self.call('b2_delete_file_version', params)

    def download_file_by_id(self, file_id):
        params = {'fileId': file_id}
        return self.call('b2_download_file_by_id', params, self.download_url,
                         raw_content=True)
