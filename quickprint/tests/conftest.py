import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtCore import QEvent, QSettings, QThreadPool
from PySide6.QtWidgets import QApplication
import app
import printer_monitor


@pytest.fixture(scope='session')
def qt():
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def cleanup_test_windows():
    yield
    application=QApplication.instance()
    if application is None:
        return
    # Closed Qt windows can outlive their Python test variables. Drain workers
    # and queued callbacks before deleting them, so later language/style changes
    # never visit stale wrappers from previous tests.
    # Qt also lists owned combo popups as top-level windows; their parent must
    # destroy them, rather than scheduling them independently for deletion.
    windows=[window for window in application.topLevelWidgets() if window.parentWidget() is None]
    for window in windows:
        window.close()
    assert QThreadPool.globalInstance().waitForDone(5000)
    application.processEvents()
    for window in windows:
        window.deleteLater()
    application.sendPostedEvents(None,QEvent.Type.DeferredDelete)


@pytest.fixture(autouse=True)
def isolated_settings(monkeypatch, tmp_path):
    monkeypatch.setattr(app, 'QSettings', lambda organization, name:
                        QSettings(str(tmp_path / f'{name}.ini'), QSettings.Format.IniFormat))


@pytest.fixture(autouse=True)
def isolated_driver_margins(monkeypatch):
    # General geometry tests must not depend on the developer's installed printer.
    monkeypatch.setattr(app, 'read_printable_margins', lambda *args: (0, 0, 0, 0))
    # Windows direct printing has its own driver/session integration tests.
    monkeypatch.setattr(app, 'WINDOWS_PRINTING', False)


@pytest.fixture(autouse=True)
def isolated_status_queries(monkeypatch):
    # UI tests never poll the developer's physical printer in a worker thread.
    monkeypatch.setattr(printer_monitor,'query_status',lambda name: ('unknown','状态未知'))
