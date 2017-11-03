import logging
import threading
from queue import Queue, Empty

from typing import Union

LOG = logging.getLogger(__name__)
HAS_UWSGI = False


try:
    import uwsgi
    HAS_UWSGI = True
    LOG.debug('uWSGI support enabled')
except:
    LOG.debug('uWSGI support disabled')


class _generic_Lock(object):

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, exc, type_, tb):
        self.release()


class _threading_Lock(_generic_Lock):

    def __init__(self) -> None:
        self._lock = threading.RLock()

    def acquire(self) -> None:
        self._lock.acquire()

    def release(self) -> None:
        self._lock.release()


class _uwsgi_Lock(_generic_Lock):

    def acquire(self) -> None:
        uwsgi.lock()
        LOG.info('acquired uwsgi lock')

    def release(self) -> None:
        uwsgi.unlock()
        LOG.info('released uwsgi lock')


LOCK: Union[_generic_Lock, None] = None
if HAS_UWSGI:
    LOCK = _uwsgi_Lock()
else:
    LOCK = _threading_Lock()


class ThreadPool(object):

    LOG = logging.getLogger('ThreadPool')

    def __init__(self, thread_num: int=4) -> None:
        self._queue: Queue = Queue()
        self._threads: list = []
        self.running = False
        for x in range(thread_num):
            t = threading.Thread(target=self.run_thread)
            self.LOG.debug('worker %s created', t.name)
            self._threads.append(t)

    def run_thread(self) -> None:
        while self.running:
            try:
                item = self._queue.get(timeout=5)
                method, args, kwargs = item
                method(*args, **kwargs)
            except Empty:
                pass

    def start(self) -> None:
        self.running = True
        for t in self._threads:
            t.start()
            self.LOG.debug('worker %s started', t.name)

    def stop(self) -> None:
        self.running = False
        for t in self._threads:
            while t.isAlive():
                t.join()
            self.LOG.debug('worker %s joined', t.name)
        self.LOG.debug('all threads joined')

    def notify(self, message: object) -> None:
        self._queue.put(message)


class NullThreadPool(object):

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass

    def notify(self, message: tuple) -> None:
        method, args, kwargs = message
        method(*args, **kwargs)


def make_pool(single=False) -> Union[NullThreadPool, ThreadPool, None]:
    result: Union[NullThreadPool, ThreadPool, None] = None
    if HAS_UWSGI or single:
        result = NullThreadPool()
    else:
        result = ThreadPool()
    return result


