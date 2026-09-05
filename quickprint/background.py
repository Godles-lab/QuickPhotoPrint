"""Run one operation off the GUI thread, delivering results back through Qt signals."""
from threading import Event

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot


class _Cancelled(Exception):
    pass


class _Signals(QObject):
    progress = Signal(str)
    finished = Signal(object, object)


class _Worker(QRunnable):
    def __init__(self, operation):
        super().__init__()
        self.operation = operation
        self.signals = _Signals()
        self.cancelled = Event()

    def report(self, text):
        # A closed window must not progress from preparation to submission.
        if self.cancelled.is_set():
            raise _Cancelled()
        self.signals.progress.emit(text)

    def run(self):
        try:
            self.report('')
            result = self.operation(self.report)
        except Exception as exc:
            self.signals.finished.emit(None, exc)
        else:
            self.signals.finished.emit(result, None)


class BackgroundTask(QObject):
    progress = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.worker = None
        self.stopped = False

    def start(self, operation, success, failure):
        if self.stopped:
            return
        if self.worker is not None:
            raise RuntimeError('已有任务正在处理。')
        self.success, self.failure = success, failure
        worker = _Worker(operation)
        worker.signals.progress.connect(self._progress)
        worker.signals.finished.connect(self._finished)
        self.worker = worker
        QThreadPool.globalInstance().start(worker)

    @Slot(str)
    def _progress(self, text):
        if not self.stopped and text:
            self.progress.emit(text)

    @Slot(object, object)
    def _finished(self, result, error):
        self.worker = None
        success, failure = self.success, self.failure
        self.success = self.failure = None
        if self.stopped:
            return
        if error is not None:
            failure(error)
        else:
            try:
                success(result)
            except Exception as exc:
                failure(exc)

    def stop(self):
        self.stopped = True
        if self.worker is not None:
            self.worker.cancelled.set()
