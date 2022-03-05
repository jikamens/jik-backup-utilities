import base64
import requests
from requests.exceptions import (
    ConnectionError as rConnectionError,
    Timeout as rTimeout,
)
import threading
import time


class RetryException(Exception):
    def __init__(self, msg, retry_operation=None, retry_count=None,
                 retry_reason=None):
        super(RetryException, self).__init__(msg)
        self.retry_operation = retry_operation
        self.retry_count = retry_count
        self.retry_reason = retry_reason


class ApiShutdownException(Exception):
    pass


class B2API(object):
    api_path = '/b2api/v1/'
    api_url = 'https://api.backblazeb2.com/b2api/v1/'
    sleep_max = 10
    retry_max = 10
    throttle_until = {}
    api_shutdown = set()
    throttle_lock = threading.Lock()

    def __init__(self, account_id, account_key, logger=None):
        self.logger = logger
        self.account_id = account_id
        if account_id not in self.throttle_until:
            self.throttle_until[account_id] = None
        self.account_key = account_key
        self._sleep_for = 1
        self.retries = 0
        self.op_start = None
        self.request_count = 0
        self.request_time = 0
        self.connect()

    def log_debug(self, msg):
        if self.logger:
            self.logger.debug(msg)

    def log_info(self, msg):
        if self.logger:
            self.logger.info(msg)

    def log_warning(self, msg):
        if self.logger:
            self.logger.warning(msg)

    def log_error(self, msg):
        if self.logger:
            self.logger.error(msg)

    def check_for_throttling(self, response):
        if response.status_code == 200:
            return False
        if response.status_code == 403:
            self.api_shutdown.add(self.account_id)
            raise ApiShutdownException(str(response))
        try:
            retry_after = int(response.headers['Retry-After'])
        except KeyError:
            print(response.headers)
            response.raise_for_status()
        with self.throttle_lock:
            until = time.time() + retry_after
            current = self.throttle_until[self.account_id]
            if current is None or until > current:
                self.log_warning(f'Throttled for {retry_after} more seconds')
                self.throttle_until[self.account_id] = until
        return True

    def wait_out_throttling(self):
        if self.account_id in self.api_shutdown:
            raise ApiShutdownException()
        with self.throttle_lock:
            throttle_until = self.throttle_until[self.account_id]
            if throttle_until is None:
                return
        delta = throttle_until - time.time()
        if delta > 0:
            self.log_debug(f'Sleeping for {delta} seconds for throttling')
            time.sleep(delta)
        with self.throttle_lock:
            if self.throttle_until[self.account_id] != throttle_until:
                return
            self.log_info('Throttling period has expired, continuing')
            self.throttle_until[self.account_id] = None

    def sleep_and_retry(self, reason, operation, reconnect=False):
        if self.retries == self.retry_max:
            delta = int(time.time() - self.op_start)
            msg = (f'Still failing ({reason}) after {self.retries} attempts '
                   f'({delta} seconds), giving up {operation}')
            self.log_error(msg)
            raise RetryException(msg,
                                 retry_operation=operation,
                                 retry_count=self.retries,
                                 retry_reason=reason)
        self.retries += 1
        self.log_debug(
            f'{reason}, sleeping for {self._sleep_for} seconds' +
            (', reconnecting' if reconnect else '') + ' and retrying ' +
            operation)
        time.sleep(self._sleep_for)
        if reconnect:
            self.log_debug('Done sleeping, attempting to reconnect')
            self.connect()
        else:
            self.log_debug(f'Done sleeping, retrying {operation}')
        self._sleep_for = min(self._sleep_for * 2, self.sleep_max)

    def reset_retries(self):
        delta = time.time() - self.op_start
        # Shouldn't be necessary since op_start should always be set at the
        # start of a chain of operations, but this way if we forget to set it
        # somewhere then the delta math above will fail which will tell us
        # there's something that needs to be fixed in the code.
        self.op_start = None
        self.request_count += 1
        self.request_time += delta
        self.log_debug(
            f'{self.request_time:.2f}s/{self.request_count} requests = '
            f'{self.request_time/self.request_count:.2f}s/req')
        if self.retries:
            self.log_info(f'Success after {self.retries} retries, '
                          f'{int(delta)} seconds')
            self._sleep_for = 1
            self.retries = 0

    def connect(self):
        if self.retries == 0:
            self.op_start = time.time()
        id_and_key = self.account_id + ':' + self.account_key
        basic_auth_string = 'Basic ' + \
            base64.b64encode(str.encode(id_and_key)).decode()
        headers = {'Authorization': basic_auth_string}
        while True:
            self.wait_out_throttling()
            try:
                response = requests.get(self.api_url + 'b2_authorize_account',
                                        headers=headers, timeout=60)
            except (rConnectionError, rTimeout) as e:
                error_string = 'timeout' if isinstance(e, rTimeout) \
                    else 'connection'
                reason = f'B2 login {error_string} error'
                self.sleep_and_retry(reason, 'login')
                continue
            if self.check_for_throttling(response):
                continue
            break
        data = response.json()
        self.api_url = data['apiUrl'] + self.api_path
        self.authorization_token = data['authorizationToken']
        self.download_url = data['downloadUrl'] + self.api_path
        self.log_debug(
            f'Logged into Backblaze account {self.account_id}, '
            f'API URL is {self.api_url}')
        self.reset_retries()

    def call(self, *args, **kwargs):
        while True:
            ret = self._try_call(*args, **kwargs)
            if ret is not None:
                return ret

    def _try_call(self, api_call, params, api_url=None, raw_content=False):
        """Returns None if retry required."""
        if self.retries == 0:
            self.op_start = time.time()
        headers = {'Authorization': self.authorization_token}
        api_url = self.api_url if api_url is None else api_url
        self.wait_out_throttling()
        try:
            response = requests.post(api_url + api_call,
                                     headers=headers, json=params, timeout=60)
        except (rConnectionError, rTimeout) as e:
            error_string = 'timeout' if isinstance(e, rTimeout) \
                else 'connection'
            reason = f'B2 {error_string} error'
            self.sleep_and_retry(reason, api_call, reconnect=True)
            return None
        if self.check_for_throttling(response):
            return None
        self.log_debug(
            f'Successfully called {api_call} with parameters {params}')
        self.reset_retries()
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

    # This is an iterator
    def list_unfinished_large_files(self, bucket_id, prefix=None,
                                    startFileId=None, max_file_count=100):
        params = {'bucketId': bucket_id, 'maxFileCount': max_file_count}
        if prefix:
            params['namePrefix'] = prefix
        if startFileId:
            params['startFileId'] = startFileId
        while True:
            response = self.call('b2_list_unfinished_large_files', params)
            for file in response['files']:
                yield file
            if 'nextFileId' not in response or not response['nextFileId']:
                break
            params['startFileId'] = response['nextFileId']

    def cancel_large_file(self, file_id):
        params = {'fileId': file_id}
        self.call('b2_cancel_large_file', params)

    def get_file_info(self, file_id):
        params = {'fileId': file_id}
        self.call('b2_get_file_info', params)

    def delete_file_version(self, file_name, file_id):
        params = {'fileName': file_name, 'fileId': file_id}
        self.call('b2_delete_file_version', params)

    def download_file_by_id(self, file_id):
        params = {'fileId': file_id}
        return self.call('b2_download_file_by_id', params, self.download_url,
                         raw_content=True)
