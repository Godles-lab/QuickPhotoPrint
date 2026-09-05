"""Driver settings, full-paper coordinates and the Windows confirmation flow."""
import base64
import ctypes as C
from types import SimpleNamespace

import pytest
from PIL import Image, ImageWin
from PySide6.QtGui import QPageSize

import app
from windows_printing import Configuration, DevMode, Geometry, WindowsPrinting, compatible_mode, mode_header
from ui_wait import wait_for_idle, wait_for


def mode_bytes(private=b'private-borderless-quality'):
    dm=DevMode();dm.Size=C.sizeof(DevMode);dm.DriverExtra=len(private)
    dm.SpecVersion=1025;dm.DriverVersion=123
    dm.Fields=0x400;dm.PrintQuality=1200;dm.YResolution=600
    return bytes(dm)+private


def test_native_mode_layout_and_driver_identity():
    assert C.sizeof(DevMode)==220 and DevMode.FormName.offset==102
    data=mode_bytes()
    assert compatible_mode(data,data)
    changed=bytearray(data);changed[66]+=1
    assert not compatible_mode(bytes(changed),data)
    for invalid in (b'',data[:-1],data+b'0'):
        with pytest.raises(ValueError):mode_header(invalid)


def test_prepare_preserves_private_settings_quality_and_normalizes_paper():
    backend=object.__new__(WindowsPrinting);original=mode_bytes();inputs=[]
    backend._mode=lambda name,source=None: inputs.append(source) or source or original
    geometry=Geometry(254,254,2970,2100,30,30,2910,2040)
    backend.inspect=lambda name,data:Configuration(name,data,geometry)
    page=QPageSize(QPageSize.PageSizeId.A4)
    result=backend.prepare('Brother',page,297,210,base64.b64encode(original).decode())
    dm=mode_header(result.mode)
    assert result.mode[220:]==original[220:]
    assert (dm.PrintQuality,dm.YResolution)==(1200,600)
    assert (dm.PaperSize,dm.Orientation,dm.Scale,dm.Copies,dm.Duplex)==(9,2,100,1,1)
    assert not (dm.Fields & (0x4|0x8|0x10000))
    assert inputs[0] is None and inputs[1]==result.mode
    with pytest.raises(ValueError,match='重新设置'):
        backend.prepare('Brother',page,297,210,'corrupt saved mode')


def test_full_paper_geometry_does_not_fit_photo_inside_hardware_margins():
    geometry=Geometry(254,254,890,1270,30,40,820,1180)
    assert geometry.size_mm==pytest.approx((89,127))
    assert geometry.margins_mm==pytest.approx((3,4,4,5))
    assert geometry.drawing_box==(-30,-40,860,1230)
    geometry.require_size(89,127)
    with pytest.raises(ValueError,match='不一致'):geometry.require_size(127,89)


@pytest.mark.parametrize('failure',[None,'geometry','page','end'])
def test_native_submission_checks_geometry_copies_abort_and_cleanup(monkeypatch,failure):
    geometry=Geometry(254,254,890,1270,30,30,830,1210)
    config=Configuration('Test only',mode_bytes(),geometry)
    calls=[];draws=[]
    backend=object.__new__(WindowsPrinting)
    backend.gdi=SimpleNamespace(
        CreateDCW=lambda *args:987,
        DeleteDC=lambda dc:calls.append('delete'),
        StartDocW=lambda *args:calls.append('start') or 123,
        StartPage=lambda dc:calls.append('page') or (-1 if failure=='page' else 1),
        EndPage=lambda dc:calls.append('endpage') or 1,
        EndDoc=lambda dc:calls.append('end') or (-1 if failure=='end' else 1),
        AbortDoc=lambda dc:calls.append('abort'))
    backend._geometry=lambda dc:geometry if failure!='geometry' else Geometry(254,254,890,1270,0,0,890,1270)
    monkeypatch.setattr(ImageWin,'Dib',lambda image:SimpleNamespace(draw=lambda dc,box:draws.append((dc,box))))
    if failure:
        with pytest.raises(ValueError):backend.print_page(config,Image.new('RGB',(89,127)),2)
        assert ('start' in calls)==(failure!='geometry')
        assert ('abort' in calls)==(failure!='geometry')
    else:
        assert backend.print_page(config,Image.new('RGB',(89,127)),2)==123
        assert draws==[(987,(-30,-30,860,1240))]*2
        assert calls==['start','page','endpage','page','endpage','end','delete']
    assert calls[-1]=='delete'


@pytest.fixture
def windows_window(qt,monkeypatch):
    state=SimpleNamespace(margin=3,printed=[],dialogs=[],edited=False,result=app.QDialog.DialogCode.Accepted)
    def config():
        edge=round(state.margin*10)
        return Configuration('Test Brother',mode_bytes(),Geometry(254,254,890,1270,edge,edge,890-2*edge,1270-2*edge))
    class Backend:
        def prepare(self,*args):return config()
        def edit(self,configuration,parent):
            state.edited=True;state.margin=0
            return config() if state.result==app.QDialog.DialogCode.Accepted else None
        def print_page(self,*args):state.printed.append(args)
    monkeypatch.setattr(app,'WINDOWS_PRINTING',True)
    monkeypatch.setattr(app,'WindowsPrinting',Backend)
    info=SimpleNamespace(printerName=lambda:'Test Brother',description=lambda:'Brother',
        isNull=lambda:False,supportedPageSizes=lambda:[])
    monkeypatch.setattr(app,'QPrinterInfo',SimpleNamespace(availablePrinters=lambda:[info],
        defaultPrinterName=lambda:'Test Brother',printerInfo=lambda name:info))
    monkeypatch.setattr(app,'printer_status',lambda info:('online','在线'))
    monkeypatch.setattr(app,'capabilities',lambda name:{})
    monkeypatch.setattr(app,'QPrintDialog',lambda *args:pytest.fail('Windows direct mode opened a print dialog'))
    class Dialog:
        def __init__(self,details,parent):state.dialogs.append(details)
        def exec(self):return state.result
    monkeypatch.setattr(app,'PrintConfirmationDialog',Dialog)
    w=app.Window();state.errors=[];w.error=state.errors.append
    w.photo=w.source_photo=Image.new('RGB',(89,127),'#a06040');w.canvas.set_photo(w.photo)
    yield w,state
    w.close();wait_for(lambda:w.print_task.worker is None and w.driver_task.worker is None)


def test_driver_edit_updates_preview_and_persists_without_printing(qt,windows_window):
    w,state=windows_window
    assert w.driver_margins==(3,3,3,3) and w.model.margins()==(3,3,3,3)
    w.open_driver_settings();wait_for_idle(w)
    assert state.edited and not state.printed and not state.errors
    assert w.driver_margins==w.model.margins()==(0,0,0,0)
    assert w.windows_driver_mode('Test Brother')
    assert w.copies.isEnabled() and not w.media_type.isEnabled()
    assert not w._busy_kind and w.driver_settings_btn.text()=='驱动设置…'


def test_cancel_driver_edit_preserves_saved_settings_and_preview(windows_window):
    w,state=windows_window;state.result=app.QDialog.DialogCode.Rejected
    before=w.model.margins()
    w.open_driver_settings();wait_for_idle(w)
    assert w.model.margins()==before and not w.windows_driver_mode('Test Brother')
    assert not state.printed and not state.errors


@pytest.mark.parametrize('accepted',[False,True])
def test_windows_print_uses_app_confirmation_and_one_settings_snapshot(windows_window,accepted):
    w,state=windows_window;w.copies.setValue(2)
    state.result=app.QDialog.DialogCode.Accepted if accepted else app.QDialog.DialogCode.Rejected
    w.print_photo();wait_for_idle(w)
    assert len(state.dialogs)==1 and not state.errors
    assert len(state.printed)==int(accepted)
    if accepted:
        configuration,page,copies=state.printed[0]
        assert configuration.geometry.margins_mm==pytest.approx((3,3,3,3)) and copies==2
        assert page.getpixel((0,0))==(255,255,255)
    assert not w._busy_kind
