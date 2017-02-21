import threading
import logging

LOG = logging.getLogger(__name__)
HAS_UWSGI = False


class _generic_Lock(object):

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc, type_, tb):
        self.release()


class _threading_Lock(_generic_Lock):

    def __init__(self):
        self._lock = threading.RLock()


    def acquire(self):
        return self._lock.acquire()

    def release(self):
        return self._lock.release()


class _uwsgi_Lock(_generic_Lock):

    def acquire(self):
        uwsgi.lock()
        LOG.info('acquired uwsgi lock')

    def release(self):
        uwsgi.unlock()
        LOG.info('released uwsgi lock')


try:
    import uwsgi
    HAS_UWSGI = True
    LOG.debug('uWSGI support enabled')
except:
    LOG.debug('uWSGI support disabled')


LOCK = None
if HAS_UWSGI:
    LOCK = _uwsgi_Lock()
else:
    LOCK = _threading_Lock()


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)

    LOCK.acquire()
    LOCK.release()

    with LOCK:
        LOG.debug('say hello!')




