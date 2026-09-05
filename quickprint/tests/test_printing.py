import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QSizeF, QMarginsF
from PySide6.QtGui import QPageSize,QPageLayout
from PySide6.QtPrintSupport import QPrinter
from core import Layout, render_page, convert_output, load_photo, check_profile, SRGB
from app import Window, paint_printer, BUILTIN

@pytest.fixture(scope='session')
def qt():
    return QApplication.instance() or QApplication([])


def test_cover_contain_zoom():
    m=Layout(paper_w=100,paper_h=150,w=100,h=150)
    assert m.photo_rect(100,100)==(-25,0,150,150)
    m.fill=False
    assert m.photo_rect(100,100)==(0,25,100,100)
    m.zoom=2
    assert m.photo_rect(100,100)==(-50,-25,200,200)


def test_mm_raster_margin_and_pan():
    m=Layout(paper_w=100,paper_h=150,x=10,y=10,w=80,h=130)
    im=Image.new('RGB',(200,200),'red')
    page=render_page(im,m,254)
    assert page.size==(1000,1500)
    assert page.getpixel((50,750))==(255,255,255)
    assert page.getpixel((500,750))==(255,0,0)
    m.pan_x=200
    assert render_page(im,m,254).getpixel((500,750))==(255,255,255)


def test_icc_actually_changes_values():
    assert 'Brother-T735DW-Kodak-Glossy' in check_profile(BUILTIN)
    im=Image.new('RGB',(10,10),(128,128,128))
    out=convert_output(im,BUILTIN)
    r,g,b=out.getpixel((0,0))
    assert 128<=r<=133 and 149<=g<=155 and 142<=b<=148
    assert convert_output(im).getpixel((0,0))==(128,128,128)


def test_exif_orientation_and_metadata(tmp_path):
    im=Image.new('RGB',(30,60),'red')
    exif=Image.Exif(); exif[274]=6; exif[315]='PRIVATE TEST'
    p=tmp_path/'source.jpg'
    im.save(p,exif=exif,icc_profile=SRGB.tobytes())
    out,note=load_photo(p)
    assert out.size==(60,30)
    assert not out.info


def test_invalid_source_icc(tmp_path):
    p=tmp_path/'bad.jpg'
    Image.new('RGB',(10,10)).save(p,icc_profile=b'invalid')
    with pytest.raises(ValueError): load_photo(p)


def test_invalid_region_and_memory_limit():
    with pytest.raises(ValueError): Layout(x=80,w=20).validate()
    with pytest.raises(ValueError): render_page(Image.new('RGB',(2,2)),Layout(paper_w=420,paper_h=594,w=420,h=594),600)


def test_ui_controls_and_pdf(qt,tmp_path):
    w=Window()
    w.model.__dict__.update(Layout().__dict__)
    w.pw.setValue(89); w.ph.setValue(127); w.full_region()
    w.photo=Image.new('RGB',(600,900),'#bf7b54'); w.source_photo=w.photo
    w.canvas.set_photo(w.photo)
    w.margin.setValue(5); w.apply_margin()
    assert w.model.w==79 and w.model.h==117
    w.zoom.setValue(150)
    assert w.model.zoom==1.5
    w.region[0].setValue(999)
    w.model.validate()
    w.full_region(); w.rotate()
    assert w.photo.size==(900,600)
    w.show(); qt.processEvents()
    printer=QPrinter(QPrinter.PrinterMode.HighResolution)
    printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    path=tmp_path/'page.pdf'; printer.setOutputFileName(str(path)); printer.setResolution(300)
    printer.setPageLayout(QPageLayout(QPageSize(QSizeF(89,127),QPageSize.Unit.Millimeter),QPageLayout.Orientation.Portrait,QMarginsF(0,0,0,0),QPageLayout.Unit.Millimeter))
    printer.setFullPage(True)
    paint_printer(printer,render_page(w.photo,w.model))
    assert path.read_bytes().startswith(b'%PDF-')
    from pypdf import PdfReader
    pdf=PdfReader(path)
    assert len(pdf.pages)==1
    box=pdf.pages[0].mediabox
    assert abs(float(box.width)*25.4/72-89)<.4
    assert abs(float(box.height)*25.4/72-127)<.4
    w.close()
