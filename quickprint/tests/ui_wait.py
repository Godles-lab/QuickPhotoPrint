from time import monotonic
from PySide6.QtTest import QTest


def wait_for(predicate, timeout=10):
    deadline = monotonic() + timeout
    while not predicate() and monotonic() < deadline:
        QTest.qWait(10)
    assert predicate(), 'Timed out waiting for the asynchronous UI operation.'


def wait_for_idle(window):
    wait_for(lambda: not window._busy_kind)
