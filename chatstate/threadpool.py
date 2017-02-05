import logging
import threading
from queue import Queue, Empty 


def make_pool(single=False):
    result = NullThreadPool()
    try:
        import uwsgi
    except ImportError:
        if not single:
            result = ThreadPool()
    return result
    
class ThreadPool:

    LOG = logging.getLogger('ThreadPool')

    def __init__(self, thread_num=4):
        self._queue = Queue()
        self._threads = []
        self.running = False
        for x in range(thread_num):
            t = threading.Thread(target=self.run_thread)
            self.LOG.debug('worker %s created', t.name)
            self._threads.append(t)

    def run_thread(self):
        while self.running:
            try:
                item = self._queue.get(timeout=5)
                method, args, kwargs = item
                method(*args, **kwargs)
            except Empty:
                pass

    def start(self):
        self.running = True
        for t in self._threads:
            t.start()
            self.LOG.debug('worker %s started', t.name)

    def stop(self):
        self.running = False
        for t in self._threads:
            while t.isAlive():
                t.join()
            self.LOG.debug('worker %s joined', t.name)
        self.LOG.debug('all threads joined')

    def notify(self, message):
        self._queue.put(message)


class NullThreadPool(object):
    
    def start(self):
        pass

    def stop(self):
        pass

    def notify(self, message):
        method, args, kwargs = message
        method(*args, **kwargs)


if __name__ == '__main__':
    pool = make_pool()
    print(pool)



