from b2api import B2API
from configparser import ConfigParser
import os
import re
import subprocess
import sys


class RcloneDecoder(object):
    def __init__(self, remote, config_file=None, mode='decode',
                 queue_size=1000):
        self.config_file = config_file
        self.remote = remote
        if mode not in ('decode', 'encode'):
            raise Exception(
                'Invalid mode "{}", should be "decode" or "encode"'.format(
                    mode))
        self.mode = mode
        self.queue_size = queue_size
        self.queue = {}
        self.queue_length = 0
        self.async_queue = []
        self.mappings = {}
        self.arg_limit = 131072

    def add(self, path):
        executed = False
        for name in path.split('/'):
            if name and name not in self.mappings:
                if self.queue_length + len(name) > self.arg_limit:
                    self.execute()
                    executed = True
                self.queue[name] = 1
                self.queue_length += len(name) + 1
        if self.full:
            self.execute()
            executed = True
        return executed

    def get(self, path, execute=True):
        if execute:
            self.execute()
        return '/'.join(self.mappings.get(n, '') for n in path.split('/'))

    def add_get(self, path):
        self.add(path)
        return self.get(path)

    def get_async(self, path, func, *args, **kwargs):
        self.async_queue.append((path, func, args, kwargs))
        self.add(path)

    @property
    def full(self):
        return len(self.queue) >= self.queue_size

    def execute(self):
        if self.queue:
            queue = list(self.queue.keys())
            self.queue.clear()
            self.queue_length = 0
            base_cmd = ['rclone', 'cryptdecode']
            if self.config_file:
                base_cmd.extend(('--config', self.config_file))
            if self.mode == 'encode':
                base_cmd.append('--reverse')
            base_cmd.append(self.remote + ':')
            while queue:
                cmd = base_cmd + ['/'.join(queue[0:1000])]
                queue = queue[1000:]
                output = subprocess.check_output(cmd)
                for result in output.decode().split('\n'):
                    match = re.match(r'(.*) \t (.*)', result)
                    if match:
                        encoded = match.group(1).split('/')
                        decoded = match.group(2).split('/')
                        for i in range(len(encoded)):
                            self.mappings[encoded[i]] = decoded[i]
        for i in self.async_queue:
            i[1](i[0], self.get(i[0], False), *i[2], **i[3])
        self.async_queue = []


def get_rclone_config(conf_file=None):
    if not conf_file:
        for path in ('~/.config/rclone/rclone.conf', '~/.rclone.conf'):
            path = os.path.expanduser(path)
            if os.path.exists(path):
                conf_file = path
                break
        else:
            raise Exception('Could not locate rclone configuration file')

    config_parser = ConfigParser()
    config_parser.read(conf_file)
    return config_parser


def get_encrypted_remote(config, multiple=False):
    """Find encrypted remote(s)"""
    remotes = [name for name, values in config.items()
               if values.get('type', None) == 'crypt']
    if not multiple:
        if len(remotes) > 1:
            raise Exception("Found more than one encrypted remote, so you'll "
                            "have to specify the one you want")
        if not remotes:
            return None
        return remotes[0]
    return remotes


def get_plain_remote(config, encrypted_remote, logger=None):
    plain_remote = config.get(encrypted_remote, 'remote')
    name, bucket_name = plain_remote.split(':')
    _type = config.get(name, 'type')
    if _type != 'b2':
        sys.exit('Type of remote "{}" needs to be "b2", not "{}"'.format(
            name, _type))
    account_id = config.get(name, 'account')
    api_key = config.get(name, 'key')
    b2 = B2API(account_id, api_key, logger=logger)
    buckets = b2.list_buckets(bucket_name=bucket_name)
    bucket_id = buckets[0]['bucketId']
    return b2, bucket_id


def files_versions(b2, bucket_id, prefix=""):
    iterator = b2.list_file_versions(bucket_id, prefix=prefix)
    iterator = (v for v in iterator if v['action'] in ('upload', 'hide'))
    try:
        versions = [next(iterator)]
    except StopIteration:
        return
    for version in iterator:
        if version['fileName'] != versions[-1]['fileName']:
            yield versions
            versions = [version]
        else:
            versions.append(version)
    if versions:
        yield versions
