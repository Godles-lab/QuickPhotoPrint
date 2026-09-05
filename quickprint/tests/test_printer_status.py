import pytest
from PySide6.QtPrintSupport import QPrinter
from PySide6.QtWidgets import QLabel, QPushButton
from PySide6.QtCore import Qt, QTimer, QThreadPool
from PySide6.QtTest import QTest

import app
import printing
from profile_picker import TRAILING_TEXT_ROLE


class Info:
    def __init__(self, name, state):
        self._name = name
        self._state = state

    def printerName(self): return self._name
    def description(self): return self._name.replace('_', ' ')
    def state(self): return self._state


@pytest.mark.parametrize('state,offline,expected', [
    (QPrinter.PrinterState.Idle, False, ('online','在线')),
    (QPrinter.PrinterState.Idle, True, ('offline','离线')),
    (QPrinter.PrinterState.Active, False, ('busy','正在打印')),
    (QPrinter.PrinterState.Aborted, False, ('paused','已暂停')),
    (QPrinter.PrinterState.Error, False, ('error','错误')),
    (QPrinter.PrinterState.Idle, None, ('unknown','状态未知')),
])
def test_macos_printer_status_mapping(monkeypatch, state, offline, expected):
    monkeypatch.setattr(printing.sys, 'platform', 'darwin')
    monkeypatch.setattr(printing, 'cups_offline_status', lambda name: offline)
    assert printing.printer_status(Info('Printer', state)) == expected


def test_other_platform_idle_queue_is_online(monkeypatch):
    monkeypatch.setattr(printing.sys, 'platform', 'win32')
    assert printing.printer_status(Info('Printer', QPrinter.PrinterState.Idle)) == ('online','在线')


def test_cups_offline_report_and_unavailable_state(monkeypatch):
    monkeypatch.setattr(printing.sys, 'platform', 'darwin')
    class Result:
        returncode = 0
        stdout = 'Alerts: offline-report\n'
    calls = []
    monkeypatch.setattr(printing.subprocess, 'run', lambda args, **kwargs: calls.append((args,kwargs)) or Result())
    assert printing.cups_offline_status('Printer Name') is True
    assert calls[0][0] == ['/usr/bin/lpstat','-l','-p','Printer Name']
    monkeypatch.setattr(printing.subprocess, 'run', lambda *args, **kwargs: (_ for _ in ()).throw(OSError()))
    assert printing.cups_offline_status('Printer') is None


def test_printer_list_shows_status_and_refreshes(qt, monkeypatch):
    infos = [Info('Studio_Printer', QPrinter.PrinterState.Idle),
             Info('Travel_Printer', QPrinter.PrinterState.Idle)]
    class Catalog:
        @staticmethod
        def availablePrinters(): return infos
        @staticmethod
        def defaultPrinterName(): return 'Studio_Printer'
    statuses = {'Studio_Printer':('online','在线'), 'Travel_Printer':('offline','离线')}
    monkeypatch.setattr(app, 'QPrinterInfo', Catalog)
    monkeypatch.setattr(app, 'printer_status', lambda info: statuses[info.printerName()])
    monkeypatch.setattr(app, 'capabilities', lambda name: {})
    w = app.Window()
    assert [w.printer_choice.itemText(i) for i in range(2)] == ['Studio Printer', 'Travel Printer']
    assert [w.printer_choice.itemData(i, TRAILING_TEXT_ROLE) for i in range(2)] == ['在线','离线']
    assert w.printer_choice.currentData() == 'Studio_Printer'
    assert all(not w.printer_choice.itemIcon(i).isNull() for i in range(2))
    statuses['Studio_Printer'] = ('offline','离线')
    w.refresh_printers()
    assert w.printer_choice.currentText() == 'Studio Printer'
    assert w.printer_choice.currentData(TRAILING_TEXT_ROLE) == '离线'
    w.close()


def test_tabs_have_no_heading_copy_and_compensation_is_under_layout(qt):
    w = app.Window()
    removed = {'纸张与设备','先选打印机，纸张尺寸会自动匹配。',
               '选择适合相纸的颜色','内置 Brother 配置，也可导入其他 ICC。',
               '直接提交纸张类型、质量和份数；打印前显示确认窗口。请先试印确认。'}
    assert not any(label.text() in removed for label in w.findChildren(QLabel))
    assert w.tabs.widget(1).isAncestorOf(w.compensation_toggle)
    assert w.tabs.widget(1).isAncestorOf(w.compensation_panel)
    assert not w.tabs.widget(0).isAncestorOf(w.compensation_toggle)
    assert not w.compensation_toggle.isChecked() and w.compensation_panel.isHidden()
    w.close()


def test_refresh_preserves_selected_queue_media_quality_and_copies(qt,monkeypatch):
    infos=[Info('Studio',QPrinter.PrinterState.Idle),Info('Travel',QPrinter.PrinterState.Idle)]
    options={'Studio':{'MediaType':['stationery'],'cupsPrintQuality':['Normal']},
             'Travel':{'MediaType':['photographic-glossy','stationery'],
                       'cupsPrintQuality':['Normal','High']}}
    class Catalog:
        availablePrinters=staticmethod(lambda:infos)
        defaultPrinterName=staticmethod(lambda:'Studio')
    calls=[]
    monkeypatch.setattr(app,'QPrinterInfo',Catalog)
    monkeypatch.setattr(app,'printer_status',lambda info:('online','在线'))
    monkeypatch.setattr(app,'capabilities',lambda name:calls.append(name) or options.get(name,{}))
    w=app.Window()
    w.printer_choice.setCurrentIndex(w.printer_choice.findData('Travel'))
    w.media_type.setCurrentIndex(w.media_type.findData('photographic-glossy'))
    w.print_quality.setCurrentIndex(w.print_quality.findData('Normal'))
    w.copies.setValue(3)
    signals=[]
    w.printer_choice.currentIndexChanged.connect(signals.append)
    calls.clear()
    infos.reverse()  # Also preserve by queue name when enumeration order changes.
    refresh=next(b for b in w.findChildren(QPushButton) if b.text()=='刷新打印机列表')
    refresh.click()
    assert w.printer_choice.currentData()=='Travel'
    assert w.media_type.currentData()=='photographic-glossy'
    assert w.print_quality.currentData()=='Normal' and w.copies.value()==3
    assert w.print_quality.isEnabled() and w.copies.isEnabled()
    assert calls==['Travel'] and not signals
    # A real capability removal must still invalidate the unavailable selection.
    options['Travel']['MediaType']=['stationery']
    refresh.click()
    assert w.media_type.currentData() is None and not w.print_quality.isEnabled()
    infos[:]=[infos[1]]  # Selected queue has been removed; use available default.
    refresh.click()
    assert w.printer_choice.currentData()=='Studio'
    assert w.media_type.count()==2
    w.close()


def wait_for(qt,predicate):
    from time import monotonic
    deadline=monotonic()+3
    while not predicate() and monotonic()<deadline:
        QTest.qWait(10)
    assert predicate()


def test_status_monitor_is_async_and_discards_stale_queue_results(qt):
    from threading import Event, get_ident
    from printer_monitor import PrinterStatusMonitor
    started,release=Event(),Event()
    gui_thread=get_ident()
    worker_threads=[]
    calls=[]
    def query(name):
        worker_threads.append(get_ident());calls.append(name)
        if name=='Old':
            started.set()
            assert release.wait(3)
            return 'busy','正在打印'
        return 'online','在线'
    monitor=PrinterStatusMonitor(query=query)
    results=[]
    monitor.statusChanged.connect(lambda *args:results.append(args))
    try:
        monitor.request('Old')
        wait_for(qt,started.is_set)
        monitor.request('New');monitor.request('New')
        ticks=[]
        QTimer.singleShot(0,lambda:ticks.append(True))
        wait_for(qt,lambda:bool(ticks))
        assert not results and calls==['Old']
        release.set()
        wait_for(qt,lambda:bool(results))
        assert results==[('New','online','在线')]
        assert calls==['Old','New']
        assert all(thread!=gui_thread for thread in worker_threads)
    finally:
        release.set();monitor.stop()
        # Receipt of a queued result can precede QRunnable.run() returning.
        # Let the runnable finish before this standalone QObject is destroyed.
        assert QThreadPool.globalInstance().waitForDone(3000)


def test_status_timer_updates_busy_to_idle_without_resetting_media(qt,monkeypatch):
    import printer_monitor
    current=[('online','在线')]
    class Catalog:
        availablePrinters=staticmethod(lambda:[Info('Studio',QPrinter.PrinterState.Idle)])
        defaultPrinterName=staticmethod(lambda:'Studio')
    monkeypatch.setattr(app,'QPrinterInfo',Catalog)
    monkeypatch.setattr(app,'printer_status',lambda info:current[0])
    monkeypatch.setattr(printer_monitor,'query_status',lambda name:current[0])
    monkeypatch.setattr(app,'capabilities',lambda name:{'MediaType':['photographic-glossy'],
                                                      'cupsPrintQuality':['Normal','High']})
    w=app.Window()
    w.media_type.setCurrentIndex(1)
    w.print_quality.setCurrentIndex(0)
    w.copies.setValue(2)
    assert w.status_timer.isActive() and w.status_timer.interval()==2000
    w.status_timer.setInterval(20)
    for status in [('busy','正在打印'),('online','在线'),('offline','离线')]:
        current[0]=status
        wait_for(qt,lambda:w.printer_choice.currentData(TRAILING_TEXT_ROLE)==status[1])
        assert w.printer_choice.currentData()=='Studio'
        assert w.media_type.currentData()=='photographic-glossy'
        assert w.print_quality.currentData()=='Normal' and w.copies.value()==2
        assert status[1] in w.printer_choice.currentData(Qt.ItemDataRole.AccessibleTextRole)
    w.close()
    assert not w.status_timer.isActive()
