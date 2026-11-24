"""A reusable, killable process. No PyMuPDF objects cross a process boundary."""
import multiprocessing as mp
import time
import traceback
import psutil


def child(pipe):
    import os
    os.environ['HF_HUB_OFFLINE'] = '1'
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    os.environ['DO_NOT_TRACK'] = '1'
    import cv2
    cv2.setNumThreads(1)
    while True:
        try:
            task = pipe.recv()
        except EOFError:
            break
        if task is None:
            break
        module,name,args = task
        try:
            import importlib
            result = getattr(importlib.import_module(module),name)(*args)
            pipe.send((True,result))
        except Exception as exc:
            pipe.send((False,f'{type(exc).__name__}: {exc}'))


class IsolatedWorker:
    def __init__(self):
        self.process = None
        self.peak_mb = 0

    def start(self):
        context = mp.get_context('spawn')
        self.pipe,other = context.Pipe()
        self.process = context.Process(target=child,args=(other,),daemon=True)
        self.process.start()
        other.close()

    def call(self, module, name, args, timeout=120, memory_mb=2048, cancelled=lambda:False):
        if not self.process or not self.process.is_alive():
            self.close()
            self.start()
        self.pipe.send((module,name,args))
        start=time.monotonic()
        while not self.pipe.poll(.1):
            if cancelled():
                self.close()
                raise InterruptedError('Operation cancelled')
            if not self.process.is_alive():
                self.close()
                raise RuntimeError('PDF worker exited unexpectedly; retry this page.')
            rss=psutil.Process(self.process.pid).memory_info().rss / 1024**2
            self.peak_mb=max(self.peak_mb,rss)
            if rss > memory_mb or time.monotonic()-start > timeout:
                self.close()
                raise TimeoutError('Worker memory limit exceeded' if rss>memory_mb else 'Page processing timed out')
        ok,result=self.pipe.recv()
        if not ok:
            raise ValueError(result)
        return result

    def close(self):
        if self.process:
            if self.process.is_alive():
                self.process.terminate()
                self.process.join(3)
                if self.process.is_alive():
                    self.process.kill()
                    self.process.join()
            self.process.close()
            self.process=None
        if hasattr(self,'pipe'):
            self.pipe.close()
