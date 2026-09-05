import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
from pathlib import Path
import pytest
from ui_wait import wait_for_idle
from PIL import Image
from PySide6.QtCore import QSizeF, QMarginsF, Qt, QMimeData, QUrl, QPoint
from PySide6.QtGui import QPageSize,QPageLayout, QDragEnterEvent, QDragLeaveEvent
from PySide6.QtPrintSupport import QPrinter
from core import Layout, render_page, convert_output, load_photo, check_profile, SRGB
from app import Window, paint_printer, BUILTIN

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
    # The 0.2.9 ICC now has another red -5 baked in; prior brightness stays intact.
    assert 152<=r<=154 and 171<=g<=173 and 164<=b<=166
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


def test_import_matches_photo_orientation(qt,tmp_path):
    w=Window()
    w.pw.setValue(89);w.ph.setValue(127);w.full_region()
    landscape=tmp_path/'landscape.jpg'
    exif=Image.Exif();exif[274]=6
    Image.new('RGB',(40,60),'red').save(landscape,exif=exif)
    w.load(str(landscape))
    wait_for_idle(w)
    assert w.photo.size == (60,40)
    assert (w.model.paper_w,w.model.paper_h,w.model.w,w.model.h)==(127,89,127,89)
    assert w.paper_choice.currentText()=='3R · 89 × 127 mm'
    assert render_page(w.photo,w.model).width > render_page(w.photo,w.model).height
    w.swap_paper()
    assert (w.model.paper_w,w.model.paper_h)==(89,127)
    assert w.paper_choice.currentText()=='3R · 89 × 127 mm'
    w.load(str(landscape))
    wait_for_idle(w)
    assert (w.model.paper_w,w.model.paper_h)==(127,89)
    square=tmp_path/'square.png'
    Image.new('RGB',(40,40)).save(square);w.load(str(square))
    wait_for_idle(w)
    assert (w.model.paper_w,w.model.paper_h)==(127,89)
    portrait=tmp_path/'portrait.png'
    Image.new('RGB',(40,60)).save(portrait);w.load(str(portrait))
    wait_for_idle(w)
    assert (w.model.paper_w,w.model.paper_h)==(89,127)
    w.close()


def test_manual_paper_dimension_switches_to_custom_immediately(qt):
    w=Window()
    assert w.paper_choice.currentText().startswith('3R')
    w.ph.setValue(129)
    assert w.paper_choice.currentText()=='自定义尺寸'
    assert (w.model.paper_w,w.model.paper_h)==(89,129)
    w.paper_choice.setCurrentIndex(1)
    assert w.paper_choice.currentText().startswith('4R')
    assert (w.model.paper_w,w.model.paper_h)==(102,152)
    w.close()


def test_photo_actions_move_between_preview_states(qt, tmp_path):
    from PySide6.QtWidgets import QLabel, QPushButton
    import app
    app.configure_app(qt)
    w=Window();w.show();qt.processEvents()
    assert w.canvas.photo_action.parent() is w.canvas
    assert w.canvas.photo_action.text() == '打开照片'
    assert w.canvas.photo_action.geometry().center().x() == pytest.approx(w.canvas.rect().center().x(), abs=1)
    assert not w.print_btn.isEnabled()
    assert not w.print_action.isEnabled()
    assert w.windowTitle() == '轻印'
    assert qt.applicationDisplayName() == 'QuickPhotoPrint'
    assert [action.text() for action in w.menuBar().actions()] == ['文件', '帮助']
    assert any(action.text() == '关于 QuickPhotoPrint' for action in w.findChildren(app.QAction))
    assert not any(button.text().startswith('导出排版') for button in w.findChildren(QPushButton))
    assert not any(label.text().startswith('拖动照片调整构图') for label in w.findChildren(QLabel))
    photo=tmp_path/'photo.png';Image.new('RGB',(80,120),'red').save(photo)
    w.load(str(photo));qt.processEvents()
    wait_for_idle(w)
    assert w.canvas.photo_action.text() == '选择其他图片'
    assert w.canvas.photo_action.geometry().right() == w.canvas.width()-19
    assert w.canvas.photo_action.y() == 18
    assert w.print_btn.isEnabled()
    assert w.print_action.isEnabled()
    w.close()


def test_preview_responds_while_photo_is_dragged_over_it(qt, tmp_path):
    w=Window();w.show();qt.processEvents()
    photo=tmp_path/'drag-photo.png';Image.new('RGB',(80,120),'red').save(photo)
    mime=QMimeData();mime.setUrls([QUrl.fromLocalFile(str(photo))])
    enter=QDragEnterEvent(QPoint(20,20),Qt.DropAction.CopyAction,mime,
                          Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier)
    qt.sendEvent(w.canvas,enter);qt.processEvents()
    assert enter.isAccepted()
    assert w.canvas.drag_active
    assert w.canvas.photo_action.isHidden()
    leave=QDragLeaveEvent()
    qt.sendEvent(w.canvas,leave);qt.processEvents()
    assert not w.canvas.drag_active
    assert not w.canvas.photo_action.isHidden()
    w.close()


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
    w.margins['left'].setValue(999)
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


def test_styled_sidebar_fits_and_mouse_pan(qt):
    from app import configure_app
    from PySide6.QtCore import QPoint
    from PySide6.QtTest import QTest
    from PySide6.QtWidgets import QScrollArea
    configure_app(qt)
    w=Window(); w.show(); qt.processEvents()
    scroll=w.findChild(QScrollArea)
    assert scroll.widget().width()<=scroll.viewport().width()
    w.photo=Image.new('RGB',(300,300),'blue');w.canvas.set_photo(w.photo)
    w.full_region();qt.processEvents()
    before=w.model.pan_x
    start=w.canvas.paper.center().toPoint()
    QTest.mousePress(w.canvas,Qt.MouseButton.LeftButton,pos=start)
    QTest.mouseMove(w.canvas,start+QPoint(25,0))
    QTest.mouseRelease(w.canvas,Qt.MouseButton.LeftButton,pos=start+QPoint(25,0))
    assert w.model.pan_x>before
    w.close()


def test_driver_native_paper_match_and_orientation(qt):
    from printing import match_page, configure_paper
    normal=QPageSize(QSizeF(88.55,127),QPageSize.Unit.Millimeter,'3.5 x 5',QPageSize.SizeMatchPolicy.ExactMatch)
    bleed=QPageSize(QSizeF(88.9,127),QPageSize.Unit.Millimeter,'3.5 x 5 Fullbleed',QPageSize.SizeMatchPolicy.ExactMatch)
    assert match_page([normal,bleed],89,127,False) is normal
    assert match_page([normal,bleed],89,127,True) is bleed
    assert match_page([normal,bleed],127,89,True) is bleed
    assert match_page([normal],210,297) is None
    class Device:
        def supportedPageSizes(self): return [normal,bleed]
        def supportsCustomPageSizes(self): return True
    printer=QPrinter();printer.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
    result=configure_paper(printer,Device(),127,89,True)
    assert result is bleed
    assert abs(printer.pageLayout().fullRect(QPageLayout.Unit.Millimeter).width()-127)<.5


def test_system_chinese_translation(qt):
    from PySide6.QtCore import QLocale
    from printing import install_system_translations
    translators=install_system_translations(qt,Path(__file__).parent.parent,QLocale('zh_CN'))
    assert translators
    assert qt.translate('QPrintDialog','Print')=='打印'
    for translator in translators: qt.removeTranslator(translator)


def test_wheel_cannot_change_parameters(qt):
    from PySide6.QtCore import QPoint,QPointF
    from PySide6.QtGui import QWheelEvent
    w=Window();w.show();qt.processEvents()
    for field,getter in [(w.pw,w.pw.value),(w.zoom,w.zoom.value),(w.zoom_value,w.zoom_value.value),
                         (w.paper_choice,w.paper_choice.currentIndex),(w.profile,w.profile.currentIndex)]:
        before=getter()
        event=QWheelEvent(QPointF(10,10),QPointF(10,10),QPoint(),QPoint(0,-120),
                         Qt.MouseButton.NoButton,Qt.KeyboardModifier.NoModifier,Qt.ScrollPhase.ScrollUpdate,False)
        qt.sendEvent(field,event)
        assert getter()==before
    w.close()


def test_centered_preview_compensation():
    from core import preview_compensated_rect
    x,y,w,h=preview_compensated_rect(890,1270,97)
    assert x==pytest.approx(13.35)
    assert y==pytest.approx(19.05)
    assert w==pytest.approx(863.3)
    assert h==pytest.approx(1231.9)
    assert x+w/2==pytest.approx(445)
    assert y+h/2==pytest.approx(635)
    assert preview_compensated_rect(890,1270,100)==(0,0,890,1270)
    assert preview_compensated_rect(890,1270,150)==(-222.5,-317.5,1335,1905)
    assert preview_compensated_rect(890,1270,200)==(-445,-635,1780,2540)
    for invalid in (89.9,200.1,float('nan'),float('inf')):
        with pytest.raises(ValueError): preview_compensated_rect(890,1270,invalid)


def test_compensation_preview_and_collapsed_control(qt):
    from PySide6.QtCore import QPointF
    w=Window();w.show();qt.processEvents()
    assert not w.compensation_toggle.isChecked()
    assert w.compensation_panel.isHidden()
    assert w.preview_scale.value()==100
    assert (w.preview_scale.minimum(),w.preview_scale.maximum())==(90,200)
    w.source_photo=Image.new('RGB',(890,1270),'red');w.photo=w.source_photo
    w.model.__dict__.update(Layout().__dict__)
    w.canvas.set_photo(w.photo)
    w.preview_scale.setValue(90);qt.processEvents()
    assert w.canvas.preview_scale==90
    image=w.canvas.grab().toImage()
    x=round(w.canvas.paper.left()+2*w.canvas.k)
    y=round(w.canvas.paper.center().y())
    assert image.pixelColor(x,y).name()=='#ffffff'
    w.preview_scale.setValue(100);qt.processEvents()
    assert w.canvas.grab().toImage().pixelColor(x,y).name()=='#ff0000'
    # Mouse coordinates map back through the preview compensation transform.
    for percent in (90,110.5,150,200):
        w.preview_scale.setValue(percent);qt.processEvents()
        assert w.canvas.preview_scale==percent
        scale=percent/100
        cx=w.canvas.paper.left()+(89*(1-scale)/2+20*scale)*w.canvas.k
        cy=w.canvas.paper.top()+(127*(1-scale)/2+30*scale)*w.canvas.k
        px,py=w.canvas.input_point(QPointF(cx,cy))
        assert px==pytest.approx(20) and py==pytest.approx(30)
    w.compensation_toggle.setChecked(True)
    assert not w.compensation_panel.isHidden()
    w.preview_scale.setValue(150.5)
    w.save_preset()
    w.close()
    restored=Window()
    assert restored.preview_scale.value()==restored.canvas.preview_scale==150.5
    assert restored.compensation_panel.isHidden()
    restored.close()


def test_compensation_toggle_keeps_form_width_stable(qt):
    from PySide6.QtWidgets import QScrollArea
    w=Window();w.resize(1000,720);w.show();w.tabs.setCurrentIndex(1);qt.processEvents()
    scroll=w.tabs.currentWidget()
    assert isinstance(scroll,QScrollArea)
    assert scroll.verticalScrollBarPolicy()==Qt.ScrollBarPolicy.ScrollBarAlwaysOn
    before=(scroll.viewport().width(),w.mode.geometry().getRect(),w.printable_note.geometry().getRect())
    w.compensation_toggle.setChecked(True);qt.processEvents()
    expanded=(scroll.viewport().width(),w.mode.geometry().getRect(),w.printable_note.geometry().getRect())
    w.compensation_toggle.setChecked(False);qt.processEvents()
    collapsed=(scroll.viewport().width(),w.mode.geometry().getRect(),w.printable_note.geometry().getRect())
    assert before==expanded==collapsed
    assert w.compensation_panel.isHidden()
    w.close()


def test_scrollbar_only_paints_when_tab_content_overflows(qt):
    from app import configure_app
    configure_app(qt)
    w=Window();w.resize(1000,1200);w.show();qt.processEvents()
    scroll=w.tabs.currentWidget();bar=scroll.verticalScrollBar()
    width=scroll.viewport().width()
    def handle_pixels():
        image=w.grab().toImage()
        point=bar.mapTo(w,QPoint(0,0))
        ratio=image.devicePixelRatio()
        return sum(image.pixelColor(x,y).name() in ('#cbd5d9','#9fadb4')
            for x in range(round(point.x()*ratio),round((point.x()+bar.width())*ratio))
            for y in range(round(point.y()*ratio),round((point.y()+bar.height())*ratio)))
    assert bar.maximum()==0 and handle_pixels()==0
    w.resize(1000,620);qt.processEvents()
    assert bar.maximum()>0 and handle_pixels()>0
    assert scroll.viewport().width()==width
    bar.setValue(bar.maximum());qt.processEvents()
    assert scroll.widget().y()<0
    w.resize(1000,1200);qt.processEvents()
    assert bar.maximum()==0 and handle_pixels()==0
    assert scroll.viewport().width()==width
    w.close()


def test_button_notification_stays_inside_window_and_prefers_above(qt):
    w=Window();w.show();qt.processEvents()
    w.notify(w.save_preset_btn,'预设已保存。',10000);qt.processEvents()
    bubble=w._toast
    assert bubble is not None and bubble.isVisible()
    button_top=w.save_preset_btn.mapTo(w.centralWidget(),w.save_preset_btn.rect().topLeft()).y()
    assert bubble.geometry().bottom()<button_top
    assert w.centralWidget().rect().contains(bubble.geometry())
    w.dismiss_toast(bubble);w.close()


def test_media_job_is_explicit_and_does_not_change_defaults():
    from media import parse_options,job_arguments
    options=parse_options('MediaType/MediaType: *any photographic-glossy\ncupsPrintQuality/Quality: *Normal High\nPageSize/Paper: A4 3.5x5.Fullbleed')
    args=job_arguments('Printer with spaces','3.5x5.Fullbleed','photographic-glossy','High',1,options)
    assert args[0]=='/usr/bin/lp' and args[-1]=='-'
    assert args[2]=='Printer with spaces'
    assert 'MediaType=photographic-glossy' in args
    assert 'print-scaling=none' in args
    with pytest.raises(ValueError): job_arguments('Printer','3.5x5.Fullbleed','unsupported','High',1,options)
