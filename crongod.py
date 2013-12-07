import sys
import re
import subprocess
import logging
import argparse
import tempfile
import time
import string
import json
import pprint
from datetime import datetime, timedelta
from pkg_resources import resource_string
from cStringIO import StringIO

import redis

logger = logging.getLogger('crongod')

def build_ps4_trace_pattern():
    PS4 = subprocess.check_output('/bin/echo -n $PS4', shell=True)
    if not PS4:
        return None
    pattern = r'''^{initial}+{remainder}'''.format(
        initial=re.escape(PS4[0:1]),
        remainder=re.escape(PS4[1:]))
    logger.debug('Trace pattern: %s', pattern)
    return re.compile(pattern)


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


class SupervisedTask(object):

    def __init__(self, name, cmd, args=tuple(), timeout=None, template=None, trace_pattern=None):
        self.state = 'INITIAL'
        self.name = name
        self.cmd = cmd
        self.args = args
        self.process = None
        self.stdout = tempfile.TemporaryFile()
        self.stderr = tempfile.TemporaryFile()
        self.start_time = None
        self.stop_time = None
        self.timeline = []

        if timeout is not None:
            timeout = timedelta(seconds=timeout)
        self.timeout = timeout

        if template is None:
            template = string.Template(resource_string(__name__, 'error-template'))
        self.template = template

        if trace_pattern is None:
            trace_pattern = build_ps4_trace_pattern()
        self.trace_pattern = trace_pattern

    def __repr__(self):
        return '<SupervisedTask cmd="{0.cmd}" state="{0.state}">'.format(self)

    def start(self):
        logger.debug('Starting task %r', self)
        self.process = subprocess.Popen(
            args=[self.cmd] + self.args,
            stdout=self.stdout,
            stderr=self.stderr)
        self.start_time = datetime.utcnow()
        self.add_action('task started')
        self.state = 'STARTED'

    def terminate(self):
        logger.debug("Terminating task %r", self)
        self.state = 'TERMINATED'
        self.add_action('forceful termination')
        self.process.terminate()

    def kill(self):
        logger.warn("Killing task %r", self)
        self.state = 'KILLED'
        self.add_action('forceful kill')
        self.process.kill()

    def poll(self):
        logger.debug("Polling task %r", self)
        code = self.process.poll()
        if code is not None:
            self.stop_time = datetime.utcnow()
            self.add_action('task stopped')
        return code

    def add_action(self, action):
        self.timeline.append((datetime.utcnow(), action))

    def run_time(self):
        if self.start_time is None:
            return None
        elif self.stop_time is None:
            return datetime.utcnow() - self.start_time
        else:
            return self.stop_time - self.start_time

    def timed_out(self):
        if self.timeout is None:
            return False
        if self.state == 'TIMEDOUT':
            return True

        run_time = self.run_time()
        if run_time is None:
            return False
        elif run_time > self.timeout:
            logger.debug("Task timed out! %r", self)
            self.state = 'TIMEDOUT'
            self.add_action('timed out')
            return True
        else:
            return False

    def returncode(self):
        return self.process.returncode

    def is_alive(self):
        return self.returncode() is None

    def supervise(self):
        self.poll()
        if self.is_alive() and self.timed_out():
            if self.state == 'TERMINATED':
                self.kill()
            else:
                self.terminate()
        return self.is_alive()

    def split_stderr(self):
        self.stderr.seek(0)
        if self.trace_pattern is None:
            return self.stderr.read()

        stderr = StringIO()
        trace = StringIO()

        for line in iter(self.stderr.readline, ''):
            match = self.trace_pattern.match(line)
            if match is None:
                stderr.write(line)
            else:
                trace.write(line)

        return stderr.getvalue(), trace.getvalue()

    def format_timeline(self):
        buf = StringIO()
        for timestamp, action in self.timeline:
            buf.write('  * {} - {}\n'.format(timestamp, action))
        return buf.getvalue().strip('\n')

    def build_context(self):
        self.stdout.seek(0)
        stderr, trace = self.split_stderr()
        ctx = {
            'cmd': self.cmd,
            'return_code': self.returncode(),
            'start_time': self.start_time,
            'stop_time': self.stop_time,
            'run_time': self.run_time(),
            'timeout': self.timeout,
            'stdout': self.stdout.read(),
            'stderr': stderr,
            'trace': trace,
        }
        logger.debug("task context: %s", pprint.pformat(ctx))
        return ctx

    def build_error_message(self, context):
        msg_context = {
            'timeline': self.format_timeline()
        }
        msg_context.update(context)
        return self.template.substitute(msg_context)

    def in_exceptional_state(self):
        if self.state == 'TIMEDOUT':
            return True
        code = self.returncode()
        if code is not None and code != 0:
            return True
        return False


def _get_log_level(name):
    level = getattr(logging, name.upper())
    if not isinstance(level, int):
        raise ValueError('Invalid log level: %s' % name)
    return level


def main():
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

    logstash = LogstashRedisClient(
        host=config.redis_host,
        port=config.redis_port,
        db=config.redis_db,
        key=config.redis_key)

    task = SupervisedTask(name=config.name, cmd=config.cmd, args=config.args, timeout=config.timeout)
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
    main()
