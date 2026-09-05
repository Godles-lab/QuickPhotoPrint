"""Busy indicators animate during real worker waits and always restore the UI."""
from pathlib import Path
from threading import Event, get_ident
from types import SimpleNamespace

import pytest
from PIL import Image
from PySide6.QtCore import QMarginsF, QSizeF, Qt, QTimer
from PySide6.QtGui import QPageLayout, QPageSize
from PySide6.QtTest import QTest

import app
from ui_wait import wait_for, wait_for_idle


@pytest.fixture
def print_window(qt, monkeypatch):
    info=SimpleNamespace(printerName=lambda:'Test',description=lambda:'Test Printer',isNull=lambda:False)
    monkeypatch.setattr(app,'QPrinterInfo',SimpleNamespace(availablePrinters=lambda:[info],
        defaultPrinterName=lambda:'Test',printerInfo=lambda name:info))
    monkeypatch.setattr(app,'printer_status',lambda info:('online','在线'))
    monkeypatch.setattr(app,'capabilities',lambda name:{'MediaType':['photographic-glossy'],
        'cupsPrintQuality':['High'],'PageSize':['3R']})
    monkeypatch.setattr(app,'configure_paper',lambda *args:SimpleNamespace(key=lambda:'3R',name=lambda:'3R'))
    class Printer:
        def printerName(self):return 'Test'
        def setPrinterName(self,value):pass
        def setResolution(self,value):pass
        def setColorMode(self,value):pass
        def setDocName(self,value):pass
        def setFullPage(self,value):pass
        def pageLayout(self):
            return QPageLayout(QPageSize(QSizeF(89,127),QPageSize.Unit.Millimeter),
                QPageLayout.Orientation.Portrait,QMarginsF(0,0,0,0),QPageLayout.Unit.Millimeter)
    state=SimpleNamespace(dialog_result=app.QDialog.DialogCode.Accepted,painted=[],submitted=[],
                          errors=[],confirmations=0,threads=[])
    class Dialog:
        def __init__(self,*args):pass
        def setWindowTitle(self,title):pass
        def exec(self):
            state.confirmations+=1
            return state.dialog_result
    monkeypatch.setattr(app,'QPrintDialog',Dialog)
    monkeypatch.setattr(app,'PrintConfirmationDialog',Dialog)
    def paint(printer,page):
        state.threads.append(get_ident());state.painted.append(page.size)
        if hasattr(printer,'outputFileName'):
            Path(printer.outputFileName()).write_bytes(b'%PDF-test-only')
    monkeypatch.setattr(app,'paint_printer',paint)
    monkeypatch.setattr(app,'submit_pdf',lambda *args:state.submitted.append(args))
    w=app.Window();w.printer=Printer();w.error=state.errors.append
    w.photo=w.source_photo=Image.new('RGB',(89,127),'#558877')
    w.canvas.set_photo(w.photo);w.set_print_enabled(True)
    w.show();qt.processEvents()
    yield w,state
    w.close()
    wait_for(lambda:w.print_task.worker is None)


def assert_idle(w):
    assert not w._busy_kind
    assert w.sidebar.isEnabled() and w.open_action.isEnabled()
    assert w.print_btn.isEnabled()==(w.photo is not None)
    assert w.print_btn.text()=='打印照片…'
    assert not w.print_btn.bar.timer.isActive() and w.print_btn.bar.isHidden()
    assert w.canvas.loading_overlay.isHidden()
    assert not w.canvas.loading_overlay.bar.timer.isActive()


@pytest.mark.parametrize('direct',[False,True])
def test_button_animates_immediately_and_prevents_duplicate_jobs(qt,monkeypatch,print_window,direct):
    w,state=print_window
    w.media_type.setCurrentIndex(1 if direct else 0)
    w.profile.setCurrentIndex(w.profile.findData(str(app.BUILTIN)))
    started,release=Event(),Event()
    gui=get_ident();calls=[]
    def check(profile):
        calls.append(get_ident());started.set()
        assert release.wait(5)
    monkeypatch.setattr(app,'check_profile',check)
    try:
        QTest.mouseClick(w.print_btn,Qt.MouseButton.LeftButton)
        assert w._busy_kind=='print' and w.print_btn.bar.isVisible()
        assert not w.print_btn.isEnabled() and not w.sidebar.isEnabled()
        wait_for(started.is_set)
        w.print_photo();w.load('should-not-load.png')
        phase=w.print_btn.bar.phase
        ticks=[];QTimer.singleShot(0,lambda:ticks.append(True))
        QTest.qWait(120)
        assert ticks and w.print_btn.bar.phase!=phase
        assert calls==[calls[0]] and calls[0]!=gui
        release.set();wait_for_idle(w)
        assert len(state.painted)==1 and len(state.submitted)==int(direct)
        assert state.confirmations==1 and not state.errors
        assert all(thread!=gui for thread in state.threads)
        assert_idle(w)
    finally:
        release.set()


@pytest.mark.parametrize('direct',[False,True])
def test_cancel_confirmation_clears_progress_without_rendering(print_window,direct):
    w,state=print_window
    w.media_type.setCurrentIndex(1 if direct else 0)
    state.dialog_result=app.QDialog.DialogCode.Rejected
    w.print_photo();wait_for_idle(w)
    assert not state.painted and not state.submitted and not state.errors
    assert_idle(w)


@pytest.mark.parametrize('stage',['preflight','render','submit'])
@pytest.mark.parametrize('direct',[False,True])
def test_print_failure_restores_controls_and_allows_retry(monkeypatch,print_window,stage,direct):
    w,state=print_window
    w.media_type.setCurrentIndex(1 if direct else 0)
    name={'preflight':'configure_paper','render':'render_output','submit':'submit_pdf' if direct else 'paint_printer'}[stage]
    original=getattr(app,name)
    def fail(*args,**kwargs):raise ValueError('test failure')
    monkeypatch.setattr(app,name,fail)
    w.print_photo();wait_for_idle(w)
    assert len(state.errors)==1 and 'test failure' in state.errors[0]
    assert not state.submitted
    assert_idle(w)
    monkeypatch.setattr(app,name,original)
    before=len(state.painted)
    w.print_photo();wait_for_idle(w)
    assert len(state.painted)==before+1 and len(state.submitted)==int(direct)
    assert_idle(w)


@pytest.mark.parametrize('stage',['decode','thumbnail'])
def test_photo_overlay_animates_during_decode_and_thumbnail(qt,monkeypatch,stage):
    started,release=Event(),Event()
    image=Image.new('RGB',(120,80),(60,110,90))
    monkeypatch.setattr(app,'load_photo',lambda path:(image,'test'))
    target='load_photo' if stage=='decode' else 'preview_image'
    original=getattr(app,target);threads=[]
    def slow(*args):
        threads.append(get_ident());started.set()
        assert release.wait(5)
        return original(*args)
    monkeypatch.setattr(app,target,slow)
    w=app.Window();w.show();qt.processEvents()
    try:
        w.load('test.png')
        assert w.canvas.loading_overlay.isVisible() and not w.print_btn.isEnabled()
        wait_for(started.is_set)
        bar=w.canvas.loading_overlay.bar
        phase=bar.phase;QTest.qWait(120)
        assert bar.phase!=phase and threads[0]!=get_ident()
        assert w.photo is None
        release.set();wait_for_idle(w)
        assert w.photo is image and w.canvas.photo.pixelColor(0,0).getRgb()[:3]==(60,110,90)
        assert (w.model.paper_w,w.model.paper_h)==(127,89)
        assert_idle(w)
    finally:
        release.set();w.close();wait_for(lambda:w.photo_task.worker is None)


def test_bad_photo_keeps_previous_preview_and_allows_retry(qt,monkeypatch):
    w=app.Window();errors=[];w.error=errors.append
    previous=Image.new('RGB',(80,120),'green')
    w.photo=w.source_photo=previous;w.canvas.set_photo(previous)
    preview=w.canvas.photo.cacheKey()
    def bad(path):raise ValueError('invalid photo')
    monkeypatch.setattr(app,'load_photo',bad)
    w.load('bad.png');wait_for_idle(w)
    assert errors==['invalid photo'] and w.photo is previous
    assert w.canvas.photo.cacheKey()==preview
    assert_idle(w)
    monkeypatch.setattr(app,'load_photo',lambda path:(Image.new('RGB',(100,100),'blue'),'test'))
    w.load('valid.png');wait_for_idle(w)
    assert w.photo.size==(100,100)
    assert_idle(w);w.close()


@pytest.mark.parametrize('direct',[False,True])
def test_close_during_preparation_does_not_submit_later(qt,monkeypatch,print_window,direct):
    w,state=print_window;w.media_type.setCurrentIndex(1 if direct else 0)
    started,release=Event(),Event()
    def convert(image,*args):
        started.set();assert release.wait(5)
        return image.copy()
    monkeypatch.setattr(app,'convert_output',convert)
    try:
        w.print_photo();wait_for(started.is_set)
        w.close();release.set()
        wait_for(lambda:w.print_task.worker is None)
        assert not state.painted and not state.submitted and not state.errors
        assert not w.print_btn.bar.timer.isActive()
    finally:
        release.set()
