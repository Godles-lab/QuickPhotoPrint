import json
from dataclasses import asdict

import pytest
from PIL import Image
from PySide6.QtCore import Qt, QPoint
from PySide6.QtGui import QPageLayout
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QPushButton, QLabel

import app
from core import Layout, render_output
from printing import printer_minimum_margins


def set_sides(window, left, top, right, bottom):
    for key, value in zip(('left', 'top', 'right', 'bottom'), (left, top, right, bottom)):
        window.margins[key].setValue(value)


def test_four_sides_are_distances_from_paper_and_keep_legacy_geometry(qt):
    w = app.Window()
    set_sides(w, 2.15, 2.35, 4.25, 5.45)
    assert w.model.margins() == pytest.approx((2.15, 2.35, 4.25, 5.45))
    assert (w.model.x, w.model.y, w.model.w, w.model.h) == pytest.approx((2.15, 2.35, 82.6, 119.2))
    assert not any(label.text() in ('距左','距上','区域宽','区域高') for label in w.findChildren(QLabel))
    w.margin.setValue(6.25); w.apply_margin()
    assert w.model.margins() == pytest.approx((6.25,)*4)
    assert [w.margins[key].value() for key in ('left','top','right','bottom')] == pytest.approx((6.25,)*4)
    w.margins['left'].setValue(999)
    assert w.model.w == 5
    w.model.validate()
    w.save_preset(); w.close()
    restored = app.Window()
    assert restored.model.w == 5
    assert restored.margins['right'].value() == 6.25
    restored.close()


@pytest.mark.parametrize('portrait', [True, False])
def test_cover_preview_and_output_respect_driver_margins(qt, monkeypatch, portrait):
    monkeypatch.setattr(app, 'read_printable_margins', lambda *args: (3, 4, 5, 6))
    w = app.Window()
    if not portrait: w.swap_paper()
    w.photo = Image.new('RGB', (600,900), 'red'); w.source_photo = w.photo
    w.canvas.set_photo(w.photo)
    w.show(); qt.processEvents()
    assert w.model.margins() == pytest.approx((3,4,5,6))
    assert w.mode.currentIndex() == 0
    for scale in (100, 105, 150, 200):
        w.preview_scale.setValue(scale); qt.processEvents()
        preview = w.canvas.grab().toImage()
        x = round(w.canvas.paper.left()+w.canvas.k)
        y = round(w.canvas.paper.center().y())
        assert preview.pixelColor(x,y).name() == '#ffffff'
        output = render_output(w.photo, w.model, 254, minimum_margins=w.driver_margins)
        assert output.getpixel((10, output.height//2)) == (255,255,255)
        assert output.getpixel((output.width//2,10)) == (255,255,255)
        assert output.getpixel((output.width-10,output.height//2)) == (255,255,255)
        assert output.getpixel((output.width//2,output.height-10)) == (255,255,255)
        assert output.getpixel((output.width//2,output.height//2)) == (255,0,0)
    w.close()


def test_borderless_preference_uses_driver_result_and_preserves_custom_margins(qt, monkeypatch):
    monkeypatch.setattr(app, 'read_printable_margins', lambda name,w,h,borderless,dpi: (0,0,0,0) if borderless else (3,3,3,3))
    w = app.Window()
    assert w.model.margins() == (3,3,3,3)
    w.borderless.setChecked(True)
    assert w.model.margins() == (0,0,0,0)
    w.margin.setValue(8); w.apply_margin()
    w.borderless.setChecked(False)
    assert w.model.margins() == (8,8,8,8)
    w.full_region()
    assert w.model.margins() == (3,3,3,3)
    assert all(field.minimum() == 3 for field in w.margins.values())
    # The preference alone cannot promise borderless output on an unsupported driver.
    monkeypatch.setattr(app, 'read_printable_margins', lambda *args: (3,3,3,3))
    w.borderless.setChecked(True)
    assert w.model.margins() == (3,3,3,3)
    w.close()


@pytest.mark.parametrize('fill', [True, False])
def test_center_moves_region_and_photo_to_paper_center_without_resetting_zoom(qt, fill):
    w = app.Window()
    w.photo = Image.new('RGB', (600,900)); w.canvas.set_photo(w.photo)
    w.model.fill = fill
    set_sides(w, 6, 8, 18, 24)
    size = (w.model.w, w.model.h)
    w.zoom.setValue(175)
    w.model.pan_x, w.model.pan_y = 12, -15
    button = next(b for b in w.findChildren(QPushButton) if b.text() == '照片居中')
    button.click()
    assert (w.model.w, w.model.h) == size
    assert w.model.margins() == pytest.approx((12,16,12,16))
    assert w.model.zoom == 1.75 and w.zoom.value() == 175
    x,y,width,height = w.model.photo_rect(*w.photo.size)
    assert (x+width/2, y+height/2) == pytest.approx((w.model.paper_w/2, w.model.paper_h/2))
    assert w.margins['left'].value() == w.margins['right'].value() == 12
    w.close()


def test_center_with_asymmetric_hardware_and_restore(qt, monkeypatch):
    monkeypatch.setattr(app, 'read_printable_margins', lambda *args: (3,4,8,10))
    w = app.Window()
    w.center_photo()
    assert w.model.margins() == (8,10,8,10)
    w.full_region()
    assert w.model.margins() == (3,4,8,10)
    w.close()


def test_region_drag_updates_sides_and_cannot_cross_driver_boundary(qt, monkeypatch):
    monkeypatch.setattr(app, 'read_printable_margins', lambda *args: (3,3,3,3))
    w = app.Window()
    w.margin.setValue(10); w.apply_margin()
    w.show(); qt.processEvents()
    start = w.canvas.paper.center().toPoint()
    QTest.mousePress(w.canvas, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.ShiftModifier, start)
    QTest.mouseMove(w.canvas, start+QPoint(100,100))
    QTest.mouseRelease(w.canvas, Qt.MouseButton.LeftButton, pos=start+QPoint(100,100))
    assert w.model.margins() == pytest.approx((17,17,3,3))
    assert w.margins['left'].value() == 17 and w.margins['right'].value() == 3
    w.close()


def test_legacy_region_preset_translates_to_side_margins(qt):
    settings = app.QSettings('Godles-lab', 'QuickPhotoPrintLocal')
    settings.setValue('preset', json.dumps({'layout': asdict(Layout(x=2.15,y=2.35,w=80,h=120)), 'profile':''}))
    w = app.Window()
    assert [w.margins[key].value() for key in ('left','top','right','bottom')] == pytest.approx((2.15,2.35,6.85,4.65))
    w.close()


def test_output_keeps_requested_physical_size():
    m = Layout()
    page = render_output(Image.new('RGB',(89,127),'red'), m, 254)
    assert page.getpixel((43,600)) == (255,0,0)
    assert page.getpixel((46,600)) == (255,0,0)
    # The print image keeps its original coordinates without preview calibration.
    photo=Image.new('RGB',(890,1270),'white')
    photo.paste('red',(400,600,490,670))
    output=render_output(photo,m,254)
    assert output.size==(890,1270)
    assert output.tobytes()==photo.tobytes()


def test_driver_minimum_margin_units_are_millimeters():
    from PySide6.QtCore import QMarginsF
    from PySide6.QtGui import QPageSize
    layout = QPageLayout(QPageSize(QPageSize.PageSizeId.A4), QPageLayout.Orientation.Landscape,
                         QMarginsF(9,18,27,36), QPageLayout.Unit.Point)
    layout.setMinimumMargins(QMarginsF(9,18,27,36))
    class Printer:
        def pageLayout(self): return QPageLayout(layout)
    assert printer_minimum_margins(Printer()) == pytest.approx((3.18,6.35,9.52,12.7), abs=.01)
