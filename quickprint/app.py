"""Quick Photo Print — local-only single-photo printing for macOS/Windows."""
import json
import sys
from pathlib import Path
from dataclasses import asdict
from PIL import Image, ImageQt
from PySide6.QtCore import Qt, QRectF, QSizeF, QMarginsF, Signal, QSettings, QStandardPaths
from PySide6.QtGui import QPainter, QColor, QPen, QPageSize, QPageLayout, QImage, QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QDoubleSpinBox, QSpinBox, QSlider, QFileDialog,
    QMessageBox, QFormLayout, QGroupBox, QScrollArea, QCheckBox, QDialog)
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo, QPrintDialog
from core import Layout, PAPERS, load_photo, convert_output, render_page, check_profile

VERSION = '0.1.0'
BASE = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
BUILTIN = BASE / 'profiles' / 'Brother-T735DW-Kodak-Glossy.icc'
if not BUILTIN.exists():
    BUILTIN = Path(__file__).resolve().parent.parent / 'Brother-T735DW-Kodak-Glossy.icc'


def qimage(im):
    return ImageQt.ImageQt(im.convert('RGBA')).copy()


class Canvas(QWidget):
    changed = Signal()
    zoomed = Signal(int)
    dropped = Signal(str)
    def __init__(self, model):
        super().__init__()
        self.model = model
        self.photo = None
        self.paper = QRectF()
        self.k = 1
        self.drag = None
        self.setMinimumSize(400, 420)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)

    def set_photo(self, im):
        if im is None:
            self.photo = None
        else:
            thumb = im.copy()
            thumb.thumbnail((1800, 1800))
            self.photo = qimage(thumb)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor('#e8edf2'))
        m = self.model
        self.k = min((self.width()-90)/m.paper_w, (self.height()-100)/m.paper_h)
        self.paper = QRectF((self.width()-m.paper_w*self.k)/2, (self.height()-m.paper_h*self.k)/2, m.paper_w*self.k, m.paper_h*self.k)
        p.fillRect(self.paper.translated(4, 6), QColor('#ced5dd'))
        p.fillRect(self.paper, Qt.GlobalColor.white)
        p.save()
        p.setClipRect(self.paper)
        p.translate(self.paper.topLeft())
        p.scale(self.k, self.k)
        region = QRectF(m.x, m.y, m.w, m.h)
        if self.photo is not None:
            p.save()
            p.setClipRect(region, Qt.ClipOperation.IntersectClip)
            try:
                dest = QRectF(*m.photo_rect(self.photo.width(), self.photo.height()))
                p.drawImage(dest, self.photo)
            except ValueError:
                pass
            p.restore()
        pen = QPen(QColor('#258477'), 1.5/self.k, Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawRect(region.adjusted(.15, .15, -.15, -.15))
        p.setBrush(QColor('#258477'))
        side = 9/self.k
        p.drawRect(QRectF(region.right()-side/2, region.bottom()-side/2, side, side))
        p.restore()
        p.setPen(QColor('#546276'))
        p.drawText(QRectF(0, self.paper.bottom()+15, self.width(), 24), Qt.AlignmentFlag.AlignCenter,
                   f'{m.paper_w:g} × {m.paper_h:g} mm   ·   排版预览')
        if self.photo is None:
            p.setPen(QColor('#66788a'))
            p.drawText(self.paper.adjusted(10, 10, -10, -10), Qt.AlignmentFlag.AlignCenter | Qt.TextFlag.TextWordWrap,
                       '拖入一张照片\n或点击“打开照片”')

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton or not self.paper.contains(e.position()):
            return
        m = self.model
        pos = (e.position()-self.paper.topLeft())/self.k
        if abs(pos.x()-(m.x+m.w))*self.k < 14 and abs(pos.y()-(m.y+m.h))*self.k < 14:
            mode = 'resize'
        elif e.modifiers() & Qt.KeyboardModifier.ShiftModifier:
            mode = 'region'
        else:
            mode = 'photo'
        self.drag = (mode, e.position(), asdict(m))
        self.setCursor(Qt.CursorShape.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if not self.drag:
            self.setCursor(Qt.CursorShape.OpenHandCursor if self.paper.contains(e.position()) else Qt.CursorShape.ArrowCursor)
            return
        mode, start, old = self.drag
        dx, dy = (e.position().x()-start.x())/self.k, (e.position().y()-start.y())/self.k
        m = self.model
        if mode == 'resize':
            m.w = max(5, min(m.paper_w-m.x, old['w']+dx))
            m.h = max(5, min(m.paper_h-m.y, old['h']+dy))
        elif mode == 'region':
            m.x = max(0, min(m.paper_w-m.w, old['x']+dx))
            m.y = max(0, min(m.paper_h-m.h, old['y']+dy))
        else:
            m.pan_x = max(-m.paper_w*4, min(m.paper_w*4, old['pan_x']+dx))
            m.pan_y = max(-m.paper_h*4, min(m.paper_h*4, old['pan_y']+dy))
        self.changed.emit()
        self.update()

    def mouseReleaseEvent(self, e):
        self.drag = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def wheelEvent(self, e):
        if self.paper.contains(e.position()):
            self.zoomed.emit(5 if e.angleDelta().y() > 0 else -5)
            e.accept()
        else:
            e.ignore()

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and e.mimeData().urls()[0].isLocalFile():
            e.acceptProposedAction()

    def dropEvent(self, e):
        self.dropped.emit(e.mimeData().urls()[0].toLocalFile())


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('轻印 · Quick Photo Print')
        self.resize(1100, 820)
        self.model = Layout()
        self.photo = None
        self.source_photo = None
        self.turns = 0
        self.settings = QSettings('Godles-lab', 'QuickPhotoPrint')
        self.printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        self.setAcceptDrops(True)
        host = QWidget()
        self.setCentralWidget(host)
        outer = QVBoxLayout(host)
        outer.setContentsMargins(22, 18, 22, 14)
        header = QHBoxLayout()
        title = QLabel('轻印  /  Quick Photo Print')
        title.setObjectName('title')
        header.addWidget(title)
        header.addStretch()
        open_btn = QPushButton('打开照片…')
        open_btn.clicked.connect(self.open_photo)
        header.addWidget(open_btn)
        outer.addLayout(header)
        self.filename = QLabel('照片在本机处理，不会上传。')
        self.filename.setObjectName('muted')
        outer.addWidget(self.filename)
        row = QHBoxLayout()
        self.canvas = Canvas(self.model)
        self.canvas.changed.connect(self.sync_region)
        self.canvas.zoomed.connect(lambda d: self.zoom.setValue(self.zoom.value()+d))
        self.canvas.dropped.connect(self.load)
        row.addWidget(self.canvas, 1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedWidth(340)
        side = QWidget()
        self.controls = QVBoxLayout(side)
        self.controls.setContentsMargins(10, 0, 8, 0)
        scroll.setWidget(side)
        row.addWidget(scroll)
        outer.addLayout(row, 1)
        self.make_controls()
        hint = QLabel('拖动照片调整构图 · 滚轮缩放 · Shift + 拖动移动打印区域 · 拖右下角调整区域大小')
        hint.setWordWrap(True)
        hint.setObjectName('muted')
        outer.addWidget(hint)
        bottom = QHBoxLayout()
        self.status = QLabel('先打开照片，再调整版式。')
        self.status.setWordWrap(True)
        bottom.addWidget(self.status, 1)
        export = QPushButton('导出排版 PNG…')
        export.clicked.connect(self.export_png)
        bottom.addWidget(export)
        self.print_btn = QPushButton('打印…')
        self.print_btn.setObjectName('primary')
        self.print_btn.setMinimumWidth(120)
        self.print_btn.clicked.connect(self.print_photo)
        bottom.addWidget(self.print_btn)
        outer.addLayout(bottom)
        for key, slot in [(QKeySequence.StandardKey.Open, self.open_photo), (QKeySequence.StandardKey.Print, self.print_photo)]:
            action = QAction(self)
            action.setShortcut(QKeySequence(key))
            action.triggered.connect(slot)
            self.addAction(action)
        self.load_preset(quiet=True)
        self.sync_region()

    def group(self, name):
        box = QGroupBox(name)
        form = QFormLayout(box)
        form.setSpacing(9)
        self.controls.addWidget(box)
        return form

    def spin(self, low, high, value):
        w = QDoubleSpinBox()
        w.setRange(low, high)
        w.setDecimals(1)
        w.setSingleStep(1)
        w.setSuffix(' mm')
        w.setValue(value)
        w.setKeyboardTracking(False)
        return w

    def make_controls(self):
        f = self.group('01  相纸')
        self.paper_choice = QComboBox()
        for name, w, h in PAPERS:
            self.paper_choice.addItem(name, (w,h))
        f.addRow(self.paper_choice)
        self.pw = self.spin(20,420,89)
        self.ph = self.spin(20,594,127)
        pair = QHBoxLayout(); pair.addWidget(self.pw); pair.addWidget(self.ph)
        f.addRow('宽 / 高', pair)
        orient = QPushButton('横竖切换')
        orient.clicked.connect(self.swap_paper)
        f.addRow(orient)
        self.paper_choice.currentIndexChanged.connect(self.paper_preset)
        self.pw.valueChanged.connect(self.paper_changed)
        self.ph.valueChanged.connect(self.paper_changed)

        f = self.group('02  构图与打印区域')
        self.mode = QComboBox()
        self.mode.addItems(['铺满区域（超出部分裁切）', '完整显示（可能留白）'])
        self.mode.currentIndexChanged.connect(self.mode_changed)
        f.addRow(self.mode)
        self.zoom = QSlider(Qt.Orientation.Horizontal)
        self.zoom.setRange(10,400); self.zoom.setValue(100)
        self.zoom_value = QSpinBox(); self.zoom_value.setRange(10,400); self.zoom_value.setSuffix('%'); self.zoom_value.setValue(100)
        self.zoom.valueChanged.connect(self.zoom_changed)
        self.zoom_value.valueChanged.connect(self.zoom.setValue)
        pair = QHBoxLayout(); pair.addWidget(self.zoom); pair.addWidget(self.zoom_value)
        f.addRow('照片缩放',pair)
        pair = QHBoxLayout()
        rotate = QPushButton('旋转 90°'); rotate.clicked.connect(self.rotate)
        reset = QPushButton('照片居中'); reset.clicked.connect(self.center_photo)
        pair.addWidget(rotate); pair.addWidget(reset); f.addRow(pair)
        self.margin = self.spin(0,100,0)
        apply_margin = QPushButton('应用白边'); apply_margin.clicked.connect(self.apply_margin)
        pair = QHBoxLayout(); pair.addWidget(self.margin); pair.addWidget(apply_margin)
        f.addRow('四边留白',pair)
        self.region = []
        for text, val in [('距左',0),('距上',0),('区域宽',89),('区域高',127)]:
            spin = self.spin(0 if len(self.region)<2 else 5,594,val)
            spin.valueChanged.connect(self.region_changed)
            self.region.append(spin)
            f.addRow(text,spin)
        full = QPushButton('恢复整张相纸区域'); full.clicked.connect(self.full_region); f.addRow(full)

        f = self.group('03  颜色与输出')
        self.profile = QComboBox()
        self.profile.addItem('Brother · 柯达高光（提亮 165）',str(BUILTIN))
        self.profile.addItem('由打印机管理颜色', '')
        self.profile.setToolTip('内置配置适合 Brother DCP-T735DW + 柯达高光；其他相纸请选择对应的 RGB ICC。')
        f.addRow('ICC',self.profile)
        browse = QPushButton('选择其他 ICC / ICM…'); browse.clicked.connect(self.choose_icc); f.addRow(browse)
        self.intent = QComboBox()
        self.intent.addItem('相对比色',1); self.intent.addItem('可感知',0); self.intent.addItem('饱和度',2); self.intent.addItem('绝对比色',3)
        f.addRow('渲染意图',self.intent)
        self.bpc = QCheckBox('黑点补偿'); f.addRow(self.bpc)
        self.profile.currentIndexChanged.connect(self.profile_changed)
        self.dpi = QComboBox()
        for dpi in (300,600): self.dpi.addItem(f'{dpi} dpi',dpi)
        f.addRow('分辨率',self.dpi)
        self.color_note = QLabel('选择 ICC 后由工具转换颜色；请关闭驱动额外颜色调整。首次请与 Photoshop 试印比较。')
        self.color_note.setWordWrap(True); self.color_note.setObjectName('muted'); f.addRow(self.color_note)
        note = QLabel('满幅排版 ≠ 硬件无边距。相纸类型、无边距、打印机和份数在系统打印窗口设置。预览只显示排版。')
        note.setWordWrap(True); note.setObjectName('muted'); f.addRow(note)
        pair = QHBoxLayout()
        save = QPushButton('保存当前预设'); save.clicked.connect(self.save_preset)
        restore = QPushButton('恢复预设'); restore.clicked.connect(self.load_preset)
        pair.addWidget(save); pair.addWidget(restore); self.controls.addLayout(pair)
        self.controls.addStretch()

    def profile_changed(self):
        enabled = bool(self.profile.currentData())
        self.intent.setEnabled(enabled); self.bpc.setEnabled(enabled)
        if hasattr(self,'color_note'):
            self.color_note.setText('工具已负责 ICC 转换；请关闭驱动额外颜色调整。首次与 Photoshop 试印比较。' if enabled else '不应用输出 ICC，交给打印机管理颜色；可使用驱动颜色增强设置。')

    def paper_preset(self):
        if self.paper_choice.currentIndex() == len(PAPERS)-1: return
        w,h = self.paper_choice.currentData()
        for control,value in [(self.pw,w),(self.ph,h)]:
            control.blockSignals(True); control.setValue(value); control.blockSignals(False)
        self.paper_changed()

    def paper_changed(self):
        self.model.paper_w,self.model.paper_h = self.pw.value(),self.ph.value()
        self.full_region()

    def swap_paper(self):
        w,h = self.model.paper_h,self.model.paper_w
        if w>420:
            return self.error('旋转后宽度超过 420 mm，请先缩小纸张。')
        for control,value in [(self.pw,w),(self.ph,h)]:
            control.blockSignals(True); control.setValue(value); control.blockSignals(False)
        self.paper_choice.blockSignals(True); self.paper_choice.setCurrentIndex(len(PAPERS)-1); self.paper_choice.blockSignals(False)
        self.paper_changed()

    def mode_changed(self):
        self.model.fill = self.mode.currentIndex()==0
        self.center_photo()

    def center_photo(self):
        self.model.pan_x=self.model.pan_y=0
        self.zoom.setValue(100)
        self.canvas.update(); self.update_status()

    def zoom_changed(self,value):
        self.model.zoom=value/100
        self.zoom_value.blockSignals(True); self.zoom_value.setValue(value); self.zoom_value.blockSignals(False)
        self.canvas.update(); self.update_status()

    def full_region(self):
        m=self.model
        m.x=m.y=0; m.w=m.paper_w; m.h=m.paper_h
        self.margin.setValue(0)
        self.center_photo(); self.sync_region()

    def apply_margin(self):
        m=self.model; margin=self.margin.value()
        if 2*margin+5>min(m.paper_w,m.paper_h):
            return self.error('白边过大，剩余打印区域至少需要 5 × 5 mm。')
        m.x=m.y=margin; m.w=m.paper_w-2*margin; m.h=m.paper_h-2*margin
        self.center_photo(); self.sync_region()

    def region_changed(self):
        m=self.model
        x,y,w,h=[c.value() for c in self.region]
        m.x=min(x,m.paper_w-5); m.y=min(y,m.paper_h-5)
        m.w=min(w,m.paper_w-m.x); m.h=min(h,m.paper_h-m.y)
        self.sync_region()

    def sync_region(self):
        for c,value in zip(self.region,(self.model.x,self.model.y,self.model.w,self.model.h)):
            c.blockSignals(True); c.setValue(value); c.blockSignals(False)
        self.canvas.update(); self.update_status()

    def update_status(self):
        if not hasattr(self,'status'): return
        if self.photo is None:
            self.status.setText('先打开照片，再调整版式。'); return
        x,y,w,h=self.model.photo_rect(*self.photo.size)
        ppi=min(self.photo.width/w,self.photo.height/h)*25.4
        self.status.setText(f'打印区域 {self.model.w:.1f} × {self.model.h:.1f} mm  ·  有效分辨率约 {ppi:.0f} ppi'+ ('  ·  放大较多，可能不够清晰' if ppi<150 else ''))

    def open_photo(self):
        path,_=QFileDialog.getOpenFileName(self,'打开照片','','照片 (*.jpg *.jpeg *.png *.tif *.tiff *.bmp *.webp)')
        if path: self.load(path)

    def load(self,path):
        try:
            image,note=load_photo(path)
            self.source_photo=image; self.photo=image; self.turns=0
            self.filename.setText(f'{Path(path).name}  ·  {image.width} × {image.height} px  ·  {note}')
            self.canvas.set_photo(image); self.center_photo()
        except Exception as exc: self.error(str(exc))

    def rotate(self):
        if self.source_photo is None: return
        self.turns=(self.turns+1)%4
        self.photo=self.source_photo.rotate(-90*self.turns,expand=True)
        self.canvas.set_photo(self.photo); self.center_photo()

    def choose_icc(self):
        path,_=QFileDialog.getOpenFileName(self,'选择 RGB 输出配置','','ICC 配置 (*.icc *.icm)')
        if not path: return
        try:
            name=check_profile(path)
            self.profile.addItem(name,path); self.profile.setCurrentIndex(self.profile.count()-1)
        except Exception as exc: self.error(f'无法使用这个 ICC：{exc}')

    def export_png(self):
        if self.photo is None: return self.error('请先打开照片。')
        path,_=QFileDialog.getSaveFileName(self,'导出排版预览（sRGB，无输出补偿）','photo-layout.png','PNG (*.png)')
        if not path: return
        try:
            from core import SRGB
            page=render_page(self.photo,self.model,self.dpi.currentData())
            page.save(path,icc_profile=SRGB.tobytes(),dpi=(self.dpi.currentData(),)*2)
            self.status.setText('排版 PNG 已导出（sRGB，未应用打印 ICC，便于检查构图）。')
        except Exception as exc: self.error(str(exc))

    def print_photo(self):
        if self.photo is None: return self.error('请先打开照片。')
        if not QPrinterInfo.availablePrinters(): return self.error('系统中未找到打印机，请先在系统设置中添加。')
        try:
            self.model.validate()
            dpi=self.dpi.currentData()
            if round(self.model.paper_w*dpi/25.4)*round(self.model.paper_h*dpi/25.4)>40_000_000:
                raise ValueError('此尺寸在 600 dpi 下过大，请改为 300 dpi。')
            # Validate ICC before displaying the OS print dialog.
            if self.profile.currentData(): check_profile(self.profile.currentData())
            self.printer.setResolution(dpi)
            self.printer.setColorMode(QPrinter.ColorMode.Color)
            self.printer.setDocName('Quick Photo Print')
            w,h=self.model.paper_w,self.model.paper_h
            orientation=QPageLayout.Orientation.Landscape if w>h else QPageLayout.Orientation.Portrait
            page=QPageSize(QSizeF(min(w,h),max(w,h)),QPageSize.Unit.Millimeter,'Photo',QPageSize.SizeMatchPolicy.FuzzyMatch)
            self.printer.setPageLayout(QPageLayout(page,orientation,QMarginsF(0,0,0,0),QPageLayout.Unit.Millimeter))
            self.printer.setFullPage(True)
            dialog=QPrintDialog(self.printer,self)
            dialog.setWindowTitle('打印照片 · 请核对相纸、无边距与颜色设置')
            if dialog.exec()!=QDialog.DialogCode.Accepted: return
            actual=self.printer.pageLayout().fullRect(QPageLayout.Unit.Millimeter)
            if abs(actual.width()-w)>1 or abs(actual.height()-h)>1:
                raise ValueError(f'系统最终纸张为 {actual.width():.1f} × {actual.height():.1f} mm，与预览 {w:g} × {h:g} mm 不一致。本次未发送，请调整纸张后重试。')
            self.printer.setFullPage(True)
            self.print_btn.setEnabled(False)
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                # Convert photo only; unprinted white margins must stay white.
                converted=convert_output(self.photo,self.profile.currentData(),self.intent.currentData(),self.bpc.isChecked())
                page=render_page(converted,self.model,dpi)
                paint_printer(self.printer,page)
            finally:
                QApplication.restoreOverrideCursor(); self.print_btn.setEnabled(True)
            self.status.setText('已提交到系统打印队列，请查看打印机状态。')
        except Exception as exc: self.error(f'未能完成打印：{exc}')

    def save_preset(self):
        profile=self.profile.currentData()
        data={'layout':asdict(self.model),'profile':'builtin' if profile==str(BUILTIN) else profile,
              'intent':self.intent.currentData(),'bpc':self.bpc.isChecked(),'dpi':self.dpi.currentData()}
        self.settings.setValue('preset',json.dumps(data))
        self.status.setText('已保存尺寸、构图和 ICC 预设，下次打开自动恢复；不保存照片。')

    def load_preset(self,checked=False,quiet=False):
        raw=self.settings.value('preset','')
        if not raw: return
        try:
            d=json.loads(raw); m=Layout(**d['layout']); m.validate()
            self.model.__dict__.update(asdict(m))
            for c,val in [(self.pw,m.paper_w),(self.ph,m.paper_h),(self.mode,0 if m.fill else 1),(self.zoom,round(m.zoom*100))]:
                c.blockSignals(True)
                if isinstance(c,QComboBox): c.setCurrentIndex(val)
                else: c.setValue(val)
                c.blockSignals(False)
            self.zoom_value.setValue(round(m.zoom*100))
            self.paper_choice.blockSignals(True); self.paper_choice.setCurrentIndex(len(PAPERS)-1); self.paper_choice.blockSignals(False)
            profile=d.get('profile','builtin')
            if profile=='builtin': self.profile.setCurrentIndex(0)
            elif not profile: self.profile.setCurrentIndex(1)
            elif Path(profile).is_file():
                self.profile.addItem(check_profile(profile),profile); self.profile.setCurrentIndex(self.profile.count()-1)
            else:
                self.profile.setCurrentIndex(1)
                if not quiet: self.error('预设中的 ICC 已找不到，已改为打印机管理颜色，请重新选择。')
                else: self.status.setText('预设 ICC 已找不到，请重新选择。')
            self.intent.setCurrentIndex(max(0,self.intent.findData(d.get('intent',1))))
            self.bpc.setChecked(bool(d.get('bpc',False)))
            self.dpi.setCurrentIndex(max(0,self.dpi.findData(d.get('dpi',300))))
            self.sync_region()
        except Exception:
            if not quiet: self.error('无法恢复这个预设，请重新设置并保存。')

    def dragEnterEvent(self,e):
        if e.mimeData().hasUrls() and e.mimeData().urls()[0].isLocalFile(): e.acceptProposedAction()
    def dropEvent(self,e): self.load(e.mimeData().urls()[0].toLocalFile())
    def error(self,text): QMessageBox.warning(self,'轻印',text)


def paint_printer(printer,page):
    painter=QPainter()
    if not painter.begin(printer): raise RuntimeError('无法启动打印任务。')
    try:
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        target=printer.pageLayout().fullRectPixels(printer.resolution())
        painter.drawImage(QRectF(0,0,target.width(),target.height()),qimage(page))
    finally:
        ok=painter.end()
    if not ok or printer.printerState()==QPrinter.PrinterState.Error:
        raise RuntimeError('系统打印引擎报告错误，请检查打印队列。')


def configure_app(app):
    app.setStyle('Fusion')
    app.setApplicationName('QuickPhotoPrint')
    app.setStyleSheet('''
        QWidget { font-size: 13px; color: #263747; }
        QMainWindow, QScrollArea, QScrollArea > QWidget > QWidget { background: #f6f8fa; }
        QScrollArea { border: none; }
        QLabel#title { font-size: 22px; font-weight: 600; }
        QLabel#muted { color: #617183; font-size: 12px; }
        QGroupBox { background: white; border: 1px solid #dce3e9; border-radius: 8px; margin-top: 14px; padding: 14px 8px 8px; font-weight: 600; }
        QGroupBox::title { subcontrol-origin: margin; left: 12px; }
        QPushButton { background: white; border: 1px solid #cdd7e0; border-radius: 6px; padding: 8px 10px; }
        QPushButton:hover { background: #e9f3f1; border-color: #278779; }
        QPushButton#primary { background: #18796b; color: white; border: none; font-weight: 600; }
        QComboBox, QSpinBox, QDoubleSpinBox { background: white; border: 1px solid #ccd6e0; border-radius: 4px; padding: 5px; min-height: 20px; }
        QSlider::groove:horizontal { height: 4px; background: #dbe3ea; }
        QSlider::handle:horizontal { width: 14px; margin: -5px 0; background: #18796b; border-radius: 7px; }
    ''')


def main():
    app=QApplication(sys.argv)
    configure_app(app)
    w=Window(); w.show()
    if len(sys.argv)>1 and not sys.argv[1].startswith('--'): w.load(sys.argv[1])
    return app.exec()

if __name__=='__main__': sys.exit(main())
