"""Preview calibration must never become an extra scaling of the print job."""
from dataclasses import asdict
from pathlib import Path
from types import SimpleNamespace
import json

import pytest
from ui_wait import wait_for_idle
from PIL import Image
from PySide6.QtCore import QMarginsF, QSizeF
from PySide6.QtGui import QPageLayout, QPageSize

import app
from core import Layout, render_output


def striped_photo():
    photo=Image.new('RGB',(890,1270),'#228866')
    photo.paste('#bb4433',(0,0,40,1270))
    photo.paste('#3355bb',(850,0,890,1270))
    return photo


@pytest.mark.parametrize('direct',[False,True])
def test_both_print_paths_ignore_preview_calibration(qt,monkeypatch,direct):
    info=SimpleNamespace(printerName=lambda:'Test_Printer',description=lambda:'Test Printer',isNull=lambda:False)
    catalog=SimpleNamespace(availablePrinters=lambda:[info],defaultPrinterName=lambda:'Test_Printer',
                            printerInfo=lambda name:info)
    options={'MediaType':['photographic-glossy'],'cupsPrintQuality':['High'],'PageSize':['photo3r']}
    monkeypatch.setattr(app,'QPrinterInfo',catalog)
    monkeypatch.setattr(app,'printer_status',lambda info:('online','在线'))
    monkeypatch.setattr(app,'capabilities',lambda name:options)
    matched=SimpleNamespace(key=lambda:'photo3r',name=lambda:'3R')
    monkeypatch.setattr(app,'configure_paper',lambda *args:matched)

    class NativePrintDevice:
        def __init__(self):
            self.name='Test_Printer'
            self.layout=QPageLayout(QPageSize(QSizeF(89,127),QPageSize.Unit.Millimeter),
                                    QPageLayout.Orientation.Portrait,QMarginsF(0,0,0,0),QPageLayout.Unit.Millimeter)
        def printerName(self):return self.name
        def setPrinterName(self,name):self.name=name
        def setResolution(self,value):pass
        def setColorMode(self,value):pass
        def setDocName(self,value):pass
        def setFullPage(self,value):pass
        def pageLayout(self):return QPageLayout(self.layout)

    confirmations=[]
    class AcceptedDialog:
        def __init__(self,*args):
            if isinstance(args[0],list):confirmations.append(args[0])
        def setWindowTitle(self,title):pass
        def exec(self):return app.QDialog.DialogCode.Accepted
    monkeypatch.setattr(app,'QPrintDialog',AcceptedDialog)
    monkeypatch.setattr(app,'PrintConfirmationDialog',AcceptedDialog)
    outputs,submissions,errors=[],[],[]
    def capture(printer,page):
        outputs.append((page.size,page.tobytes()))
        if hasattr(printer,'outputFileName'):
            Path(printer.outputFileName()).write_bytes(b'%PDF-test-only')
    monkeypatch.setattr(app,'paint_printer',capture)
    monkeypatch.setattr(app,'submit_pdf',lambda args,data:submissions.append((args,data)))
    w=app.Window()
    w.error=errors.append
    w.printer=NativePrintDevice()
    w.photo=w.source_photo=striped_photo()
    w.canvas.set_photo(w.photo)
    w.media_type.setCurrentIndex(1 if direct else 0)
    geometry=asdict(w.model)
    for percent in (90,100,106,150,200):
        w.preview_scale.setValue(percent)
        w.print_photo()
        wait_for_idle(w)
        assert asdict(w.model)==geometry
    assert not errors
    assert len(outputs)==5
    assert all(output==outputs[0] for output in outputs)
    if direct:
        assert len(submissions)==5 and all(job==submissions[0] for job in submissions)
        assert all('补偿' not in label for rows in confirmations for label,value in rows)
    else:
        assert not submissions
    w.close()


def test_preview_can_match_simulated_driver_crop_without_changing_output(qt):
    w=app.Window();w.show();qt.processEvents()
    w.photo=w.source_photo=striped_photo()
    w.canvas.set_photo(w.photo)
    raw=render_output(w.photo,w.model,254)
    baseline=raw.tobytes()
    # Independently simulate a driver enlarging the submitted page by 6%.
    scale=1.06
    printed=raw.transform(raw.size,Image.Transform.AFFINE,
                          (1/scale,0,raw.width*(scale-1)/(2*scale),
                           0,1/scale,raw.height*(scale-1)/(2*scale)),
                          resample=Image.Resampling.BICUBIC)
    assert raw.getpixel((20,635))!=(printed.getpixel((20,635)))
    w.preview_scale.setValue(106);qt.processEvents()
    preview=w.canvas.grab().toImage()
    for xmm in (2,12,30,44.5,60,77,87):
        x=round(w.canvas.paper.left()+xmm*w.canvas.k)
        y=round(w.canvas.paper.center().y())
        assert preview.pixelColor(x,y).getRgb()[:3]==printed.getpixel((round(xmm*10),635))
    assert render_output(w.photo,w.model,254).tobytes()==baseline
    assert w.model.zoom==1
    w.close()


def test_legacy_scale_becomes_preview_only_and_new_key_takes_precedence(qt):
    settings=app.QSettings('Godles-lab','QuickPhotoPrintLocal')
    preset={'layout':asdict(Layout()),'profile':'','output_scale':106}
    settings.setValue('preset',json.dumps(preset))
    w=app.Window()
    assert w.preview_scale.value()==w.canvas.preview_scale==106
    assert w.compensation_toggle.text()=='预览尺寸补偿'
    assert not w.compensation_toggle.isChecked() and w.compensation_panel.isHidden()
    assert w.model.zoom==1
    w.save_preset()
    saved=json.loads(w.settings.value('preset'))
    assert saved['preview_scale']==106 and 'output_scale' not in saved
    w.close()
    preset['preview_scale']=110
    settings.setValue('preset',json.dumps(preset))
    restored=app.Window()
    assert restored.preview_scale.value()==110
    restored.close()
