#!/usr/bin/env python

import sys
import logging
import argparse
import time

from . import supervisor
from . import reporting


logger = logging.getLogger(__name__)


def _get_log_level(name):
    level = getattr(logging, name.upper())
    if not isinstance(level, int):
        raise ValueError('Invalid log level: %s' % name)
    return level


def supervise_single_task():
    parser = argparse.ArgumentParser(description='CRON supervisor')
    parser.add_argument('cmd', help='the command to supervise')
    parser.add_argument('args', help='optional args to cmd', nargs=argparse.REMAINDER)
    parser.add_argument('--name')
    parser.add_argument('--loglevel', default='error', choices=('debug', 'info', 'warning', 'error', 'critial'))
    parser.add_argument('--timeout', default=None, type=int, help='command timeout in seconds')
    parser.add_argument('--redis-host', default='logstash')
    parser.add_argument('--redis-port', default=6379, type=int)
    parser.add_argument('--redis-db', default=0, type=int)
    parser.add_argument('--redis-key', default='logstash_json')
    config = parser.parse_args()

    logging.basicConfig(level=_get_log_level(config.loglevel))
    logger.debug(config)

    logstash = reporting.LogstashRedisClient(
        host=config.redis_host,
        port=config.redis_port,
        db=config.redis_db,
        key=config.redis_key)

    task = supervisor.SupervisedTask(name=config.name, cmd=config.cmd, args=config.args, timeout=config.timeout)
    task.start()
    logstash.record(type='cron', action='STARTED', status='OK', name=task.name, cmd=task.cmd)
    while task.supervise():
        time.sleep(1)
    context = task.build_context()
    if task.in_exceptional_state():
        print(task.build_error_message(context))
        status = 'ERROR'
    else:
        status = 'OK'
    logstash.record(type='cron', action='STOPPED', status=status, name=task.name, cmd=task.cmd, result=context)
    sys.exit(task.returncode())

if __name__ == '__main__':
    supervise_single_task()
