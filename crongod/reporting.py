import socket
import json
from datetime import datetime, timedelta
import logging

import redis

logger = logging.getLogger(__name__)

class LogstashJSONEncoder(json.JSONEncoder):
    def default(self, o):
        if isinstance(o, datetime):
            return o.replace(microsecond=0).isoformat()
        if isinstance(o, timedelta):
            return o.total_seconds()
        return json.JSONEncoder.default(self, o)


class LogstashRedisClient(object):
    def __init__(self, host='localhost', port=6379, db=0, key='logstash_json'):
        self.redis = redis.StrictRedis(host=host, port=port, db=db, socket_timeout=5)
        self.key = key
        self.encoder = LogstashJSONEncoder()

    def record(self, type, **kwargs):
        kwargs['type'] = type
        try:
            self.redis.lpush(self.key, self.encoder.encode(kwargs))
        except Exception:
            logger.exception('Failed to send record to logstash: type=%s, kwargs=%s', type, kwargs)


class LogstashUDPClient(object):
    def __init__(self, host='localhost', port=5455):
        self.host = host
        self.port = port
        self.encoder = LogstashJSONEncoder()
        self.sock = socket.socket(
            socket.AF_INET,
            socket.SOCK_DGRAM)


    def record(self, type, **kwargs):
        kwargs['type'] = type
        msg = self.encoder.encode(kwargs)
        self.sock.sendto(msg, (self.host, self.port))
