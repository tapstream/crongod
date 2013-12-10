import os
import errno
import fcntl
import logging

logger = logging.getLogger(__name__)


class BaseLock(object):
    def __enter__(self):
        return self.acquire()

    def __exit__(self, exc_type, exc_value, traceback):
        self.release()


class NoOpLockFactory(object):

    def build(self):
        return NoOpLock()


class NoOpLock(BaseLock):

    def __str__(self):
        return '<NoOpLock>'

    def acquire(self):
        return True

    def release(self):
        return None


class RedisLockFactory(object):
    '''Build distributed Redis locks'''

    def __init__(self, redis, prefix=None, timeout=None, sleep=0.1):
        if prefix is None:
            prefix = 'lock:'
        self.redis = redis
        self.prefix = prefix
        self.timeout = timeout
        self.sleep = sleep

    def build(self, name):
        return RedisLock(
            redis=self.redis,
            name='{prefix}{name}'.format(prefix=self.prefix, name=name),
            timeout=self.timeout,
            sleep=self.sleep,
        )

class RedisLock(BaseLock):
    def __init__(self, redis, name, timeout=None, sleep=0.1, blocking=True):
        self.lock = redis.lock(name, timeout, sleep)
        self.blocking = blocking

    def __str__(self):
        return '<RedisLock: {}>'.format(self.name)

    def acquire(self):
        return self.lock.acquire(blocking=self.blocking)

    def release(self):
        return self.lock.release()


class FileLockFactory(object):
    '''Build node local filesystem locks'''

    def __init__(self, directory=None, blocking=True):
        if directory is None:
            for directory in ('/var/run/lock', '/var/run', '/tmp', '.'):
                if os.path.isdir(directory) and os.access(directory, os.R_OK | os.W_OK):
                    break
            else:
                raise RuntimeError('Unable to find a suitable lock directory. Please specify one.')

        self.directory = directory
        self.blocking = blocking

    def build(self, name):
        return FileLock(
            filename=os.path.join(self.directory, name),
            blocking=self.blocking,
        )


class FileLock(BaseLock):
    def __init__(self, filename, blocking=True):
        self.filename = filename
        self.blocking = blocking
        self.file = open(self.filename, 'w')

    def __str__(self):
        return '<FileLock: {}>'.format(self.filename)

    def acquire(self):
        flags = fcntl.LOCK_EX
        if not self.blocking:
            flags |= fcntl.LOCK_NB
        try:
            fcntl.lockf(self.file, flags)
        except IOError as e:
            if e.errno == errno.EWOULDBLOCK:
                return False
            raise
        return True

    def release(self):
        fcntl.lockf(self.file, fcntl.LOCK_UN)


