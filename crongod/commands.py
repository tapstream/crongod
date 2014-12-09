#!/usr/bin/env python

import sys
import logging
import argparse
import time
import errno

import redis

from . import supervisor
from . import reporting
from . import locking

import crongod

logger = logging.getLogger(__name__)


def _get_log_level(name):
    level = getattr(logging, name.upper())
    if not isinstance(level, int):
        raise ValueError('Invalid log level: %s' % name)
    return level


def _build_lock_factory(config):
    lock_type = config.lock_type.lower()
    if lock_type == 'none':
        return locking.NoOpLockFactory()
    elif lock_type == 'file':
        return locking.FileLockFactory(
            directory=config.lock_prefix,
            blocking=config.lock_blocking)
    elif lock_type == 'redis':
        redis_client = redis.StrictRedis(
            host=config.redis_host,
            port=config.redis_port,
            db=config.redis_db,
            socket_timeout=5)
        return locking.RedisLockFactory(
            redis=redis_client,
            prefix=config.lock_prefix,
            blocking=config.lock_blocking)
    else:
        raise ValueError("Unknown lock type {}".format(lock_type))

def supervise_single_task():
    parser = argparse.ArgumentParser(
        description='crongod (%s)' % crongod.__version__,)

    parser.add_argument('cmd', help='the command to supervise')
    parser.add_argument('args', help='optional args to cmd', nargs=argparse.REMAINDER)
    parser.add_argument('--name', required=True)
    parser.add_argument('--version')
    parser.add_argument('--log-level', default='error', choices=('debug', 'info', 'warning', 'error', 'critial'))
    parser.add_argument('--timeout', default=None, type=int, help='command timeout in seconds')

    # Locking
    parser.add_argument('--lock-type', default='file', choices=('file', 'redis', 'none'))
    parser.add_argument('--lock-blocking', action='store_true', help='Enable lock blocking')
    parser.add_argument('--lock-prefix', default=None, help='The implementation dependant lock prefix')

    # Redis
    parser.add_argument('--redis-host', default='logstash')
    parser.add_argument('--redis-port', default=6379, type=int)
    parser.add_argument('--redis-db', default=0, type=int)
    parser.add_argument('--redis-key', default='logstash_json')

    parser.set_defaults(lock_blocking=False)
    config = parser.parse_args()

    logging.basicConfig(level=_get_log_level(config.log_level))
    logger.debug(config)

    logstash = reporting.LogstashRedisClient(
        host=config.redis_host,
        port=config.redis_port,
        db=config.redis_db,
        key=config.redis_key)

    lock_factory = _build_lock_factory(config=config)
    lock = lock_factory.build(name=config.name)
    logger.debug('Acquiring lock %s', lock)
    if not lock.acquire():
        logger.debug('Lock %s already acquired and blocking is disabled', lock)
        sys.exit(errno.EWOULDBLOCK)

    try:
        task = supervisor.SupervisedTask(name=config.name, cmd=config.cmd, args=config.args, timeout=config.timeout)
        task.start()
        logstash.record(type='cron', action='STARTED', string_id=str(task.id), status='OK', name=task.name, cmd=task.cmd)
        while task.supervise():
            time.sleep(1)
        context = task.build_context()
        if task.in_exceptional_state():
            print(task.build_error_message(context))
            status = 'ERROR'
        else:
            status = 'OK'
        logstash.record(type='cron', action='STOPPED', string_id=str(task.id), status=status, name=task.name, cmd=task.cmd, result=context, timeline=task.format_timeline())
        sys.exit(task.returncode())
    finally:
        lock.release()

if __name__ == '__main__':
    supervise_single_task()