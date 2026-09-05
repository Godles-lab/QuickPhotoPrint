"""Read queue status off the GUI thread; coalesce overlapping refresh requests."""
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal, Slot
from PySide6.QtPrintSupport import QPrinterInfo
from printing import printer_status


def query_status(name):
    # QPrinterInfo is a snapshot, so obtain a fresh one on every poll.
    info=QPrinterInfo.printerInfo(name)
    if info.isNull():return 'unknown','状态未知'
    return printer_status(info)


class _Result(QObject):
    finished=Signal(str,object)


class _Query(QRunnable):
    def __init__(self,name,query):
        super().__init__()
        self.name=name
        self.query=query
        self.result=_Result()

    def run(self):
        try:status=self.query(self.name)
        except Exception:status=('unknown','状态未知')
        self.result.finished.emit(self.name,status)


class PrinterStatusMonitor(QObject):
    statusChanged=Signal(str,str,str)

    def __init__(self,parent=None,query=None):
        super().__init__(parent)
        self._query_fn=query or query_status
        self._running=None
        self._name=''
        self._pending=False
        self._stopped=False

    def request(self,name):
        if self._stopped:return
        self._name=name
        if self._running is not None:
            self._pending=True
            return
        if not name:return
        self._pending=False
        worker=_Query(name,self._query_fn)
        worker.result.finished.connect(self._finished)
        self._running=worker
        QThreadPool.globalInstance().start(worker)

    @Slot(str,object)
    def _finished(self,name,status):
        self._running=None
        if self._stopped:return
        if name==self._name:
            self.statusChanged.emit(name,*status)
        if self._pending:self.request(self._name)

    def stop(self):
        self._stopped=True
        self._pending=False
