"""Paper names follow actual dimensions without changing print-driver identifiers."""
from dataclasses import asdict
from types import SimpleNamespace

import pytest
from ui_wait import wait_for_idle

import app
from core import PAPERS


def test_manual_dimensions_recognize_catalog_in_both_orientations(qt):
    w=app.Window()
    for index,(name,width,height) in enumerate(PAPERS[:-1]):
        for pw,ph in ((width,height),(height,width)):
            w.pw.setValue(pw);w.ph.setValue(ph)
            assert w.paper_choice.currentIndex()==index
            assert w.paper_choice.currentText()==name
            assert (w.model.paper_w,w.model.paper_h)==(pw,ph)
    # A different entered size must not be rounded to a nominal paper size.
    w.pw.setValue(89.1);w.ph.setValue(127)
    assert w.paper_choice.currentText()=='自定义尺寸'
    w.pw.setValue(89)
    assert w.paper_choice.currentText()=='3R · 89 × 127 mm'
    w.close()


def test_swapping_and_restoring_presets_recognize_size_without_resetting_crop(qt):
    w=app.Window()
    w.swap_paper()
    assert (w.model.paper_w,w.model.paper_h)==(127,89)
    assert w.paper_choice.currentText()=='3R · 89 × 127 mm'
    w.margin.setValue(5);w.apply_margin()
    w.zoom.setValue(150)
    w.model.pan_x,w.model.pan_y=2,3
    saved=asdict(w.model)
    w.save_preset()
    w.pw.setValue(200)
    assert w.paper_choice.currentText()=='自定义尺寸'
    w.load_preset()
    assert w.paper_choice.currentText()=='3R · 89 × 127 mm'
    assert asdict(w.model)==saved
    w.close()
    restored=app.Window()
    assert restored.paper_choice.currentText()=='3R · 89 × 127 mm'
    assert asdict(restored.model)==saved
    restored.close()


@pytest.mark.parametrize('width,height,key,driver_name,expected',[
    (127,178,'5x7.Fullbleed','5 x 7，无边框','5R · 127 × 178 mm · 无边框'),
    (178,127,'5x7.Fullbleed','5 x 7，无边框','5R · 127 × 178 mm（横向） · 无边框'),
    (89,127,'3.5x5.Fullbleed','3.5 x 5，无边框','3R · 89 × 127 mm · 无边框'),
    (127,178,'5x7','5 x 7','5R · 127 × 178 mm'),
    (126,178,'custom','User Defined','自定义尺寸 · 126 × 178 mm'),
])
def test_confirmation_uses_app_paper_name_and_actual_borderless_mode(qt,monkeypatch,width,height,key,driver_name,expected):
    options={'MediaType':['photographic-glossy'],'cupsPrintQuality':['High'],'PageSize':[key]}
    monkeypatch.setattr(app,'capabilities',lambda name:options)
    info=SimpleNamespace(printerName=lambda:'Test_Printer',description=lambda:'Test Printer')
    matched=SimpleNamespace(key=lambda:key,name=lambda:driver_name)
    confirmations=[]
    class CancelDialog:
        def __init__(self,details,parent):confirmations.append(dict(details))
        def exec(self):return app.QDialog.DialogCode.Rejected
    monkeypatch.setattr(app,'PrintConfirmationDialog',CancelDialog)
    def unexpected_submit(*args):pytest.fail('A cancelled confirmation must never submit a job.')
    monkeypatch.setattr(app,'submit_pdf',unexpected_submit)
    w=app.Window()
    w.pw.setValue(width);w.ph.setValue(height)
    w.media_type.setCurrentIndex(1)
    w.borderless.setChecked(True)  # Preference does not imply a borderless match.
    geometry=asdict(w.model)
    w.print_with_media(info,matched,300)
    wait_for_idle(w)
    assert confirmations[0]['纸张']==expected
    assert driver_name not in confirmations[0]['纸张']
    assert asdict(w.model)==geometry
    w.close()
