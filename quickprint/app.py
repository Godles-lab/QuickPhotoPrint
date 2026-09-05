"""Quick Photo Print — local-only single-photo printing for macOS/Windows."""
import json
import sys
from pathlib import Path
from dataclasses import asdict
from PIL import Image, ImageQt
from PySide6.QtCore import Qt, QRectF, QSizeF, QMarginsF, Signal, QSettings, QStandardPaths, QObject, QEvent, QTimer, QSignalBlocker
from PySide6.QtGui import QPainter, QColor, QPen, QPageSize, QPageLayout, QImage, QAction, QKeySequence, QFont, QFontDatabase, QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QDoubleSpinBox, QSpinBox, QSlider, QFileDialog,
    QMessageBox, QFormLayout, QGroupBox, QScrollArea, QCheckBox, QDialog, QSizePolicy, QTabWidget, QAbstractSpinBox, QToolButton, QLayout)
from PySide6.QtPrintSupport import QPrinter, QPrinterInfo, QPrintDialog
from core import Layout, PAPERS, STANDARD_RGB, load_photo, convert_output, render_page, render_output, check_profile, preview_compensated_rect
from core import PREVIEW_SCALE_MIN, PREVIEW_SCALE_MAX
from core import paper_preset_index, paper_description
from color_controls import ColorControls
from icc_edit import ColorAdjustment, save_adjusted_profile
from profile_picker import (StyledComboBox, ProfileComboBox, IMPORT_PROFILE, CUSTOM_ROLE,
                            DESCRIPTION_ROLE, TRAILING_TEXT_ROLE, TRAILING_COLOR_ROLE)
from printing import configure_paper, install_system_translations, read_printable_margins, printer_minimum_margins, printer_status, borderless_page
from media import capabilities, job_arguments, submit_pdf, LABELS, QUALITY
from printer_monitor import PrinterStatusMonitor
from print_dialog import PrintConfirmationDialog
from background import BackgroundTask
from progress_controls import PrintProgressButton, PhotoLoadingOverlay
from scroll_controls import OverflowScrollBar

VERSION = '0.2.11'
BASE = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
APP_ICON = BASE / 'assets' / 'app-icon.png'
BUILTIN = BASE / 'profiles' / 'Brother-T735DW-Kodak-Glossy.icc'
if not BUILTIN.exists():
    BUILTIN = Path(__file__).resolve().parent.parent / 'Brother-T735DW-Kodak-Glossy.icc'


def qimage(im):
    return ImageQt.ImageQt(im.convert('RGBA')).copy()


def preview_image(image):
    thumb = image.copy()
    thumb.thumbnail((1800, 1800))
    return qimage(thumb)


def validated_driver_margins(minimum, width, height):
    if minimum is None:
        return None
    import math
    minimum = tuple(math.ceil(v*100-1e-8)/100 for v in minimum)
    Layout(paper_w=width, paper_h=height).set_margins(*minimum)
    return minimum


def printer_status_icon(code):
    colors = {'online':'#228B69', 'busy':'#3B82F6', 'offline':'#98A4AD',
              'paused':'#D18A24', 'error':'#C45B4A', 'unknown':'#98A4AD'}
    pixmap = QPixmap(12, 12)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(colors[code]))
    painter.drawEllipse(2, 2, 8, 8)
    painter.end()
    return QIcon(pixmap)


PRINTER_STATUS_COLORS = {
    'online':'#228B69', 'busy':'#3B82F6', 'offline':'#85939E',
    'paused':'#D18A24', 'error':'#C45B4A', 'unknown':'#85939E',
}


class Canvas(QWidget):
    changed = Signal()
    zoomed = Signal(int)
    dropped = Signal(str)
    openRequested = Signal()
    def __init__(self, model):
        super().__init__()
        self.model = model
        self.photo = None
        self.paper = QRectF()
        self.k = 1
        self.drag = None
        self.drag_active = False
        self.preview_scale = 100
        self.minimum_margins = (0, 0, 0, 0)
        self.setMinimumSize(400, 420)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.photo_action = QPushButton('打开照片', self)
        self.photo_action.setObjectName('canvasPhotoAction')
        self.photo_action.setMinimumWidth(112)
        self.photo_action.clicked.connect(lambda checked=False: self.openRequested.emit())
        self.loading_overlay = PhotoLoadingOverlay(self)
        self.position_photo_action()

    def position_photo_action(self):
        hint = self.photo_action.sizeHint()
        width = max(112, hint.width())
        height = hint.height()
        if self.photo is None:
            x = (self.width()-width)//2
            y = (self.height()-height)//2+14
        else:
            x = self.width()-width-18
            y = 18
        self.photo_action.setGeometry(x, y, width, height)
        self.photo_action.raise_()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.position_photo_action()
        self.loading_overlay.setGeometry(self.rect())

    def set_loading(self, active):
        self.drag = None
        self.set_drag_active(False)
        self.photo_action.setVisible(not active)
        self.loading_overlay.setGeometry(self.rect())
        self.loading_overlay.set_active(active)

    def set_preview_scale(self, percent):
        self.preview_scale=percent
        self.drag=None
        self.update()

    def input_point(self, position):
        offset_x,offset_y,_,_=preview_compensated_rect(self.model.paper_w,self.model.paper_h,self.preview_scale)
        point=(position-self.paper.topLeft())/self.k
        return ((point.x()-offset_x)/(self.preview_scale/100),
                (point.y()-offset_y)/(self.preview_scale/100))

    def set_photo(self, im, preview=None):
        if im is None:
            self.photo = None
            self.photo_action.setText('打开照片')
        else:
            self.photo = preview if preview is not None else preview_image(im)
            self.photo_action.setText('选择其他图片')
        self.position_photo_action()
        self.update()

    def set_drag_active(self, active):
        if self.drag_active == active:
            return
        self.drag_active = active
        self.photo_action.setVisible(not active)
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
        left, top, right, bottom = self.minimum_margins
        p.setClipRect(QRectF(left, top, m.paper_w-left-right, m.paper_h-top-bottom), Qt.ClipOperation.IntersectClip)
        offset_x,offset_y,_,_=preview_compensated_rect(m.paper_w,m.paper_h,self.preview_scale)
        p.translate(offset_x,offset_y)
        scale=self.preview_scale/100
        p.scale(scale,scale)
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
        pen = QPen(QColor('#258477'), 1.5/(self.k*scale), Qt.PenStyle.DashLine)
        p.setPen(pen)
        p.drawRect(region.adjusted(.15, .15, -.15, -.15))
        p.setBrush(QColor('#258477'))
        side = 9/(self.k*scale)
        p.drawRect(QRectF(region.right()-side/2, region.bottom()-side/2, side, side))
        p.restore()
        p.setPen(QColor('#546276'))
        p.drawText(QRectF(0, self.paper.bottom()+15, self.width(), 24), Qt.AlignmentFlag.AlignCenter,
                   f'{m.paper_w:g} × {m.paper_h:g} mm   ·   打印布局预览')
        if self.photo is None and not self.drag_active:
            p.setPen(QColor('#66788a'))
            hint = QRectF(self.paper.left()+10, self.photo_action.y()-40,
                          self.paper.width()-20, 24)
            p.drawText(hint, Qt.AlignmentFlag.AlignCenter, '拖入一张照片')
        if self.drag_active:
            p.fillRect(self.rect(), QColor(24,116,93,34))
            pen=QPen(QColor('#18745D'),2,Qt.PenStyle.DashLine)
            p.setPen(pen);p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(7,7,-7,-7),12,12)
            p.setPen(QColor('#125E4B'))
            p.setFont(QFont(p.font().family(),14,QFont.Weight.DemiBold))
            message='松开以导入照片' if self.photo is None else '松开以更换图片'
            p.drawText(QRectF(self.rect()),Qt.AlignmentFlag.AlignCenter,message)

    def mousePressEvent(self, e):
        if e.button() != Qt.MouseButton.LeftButton or not self.paper.contains(e.position()):
            return
        m = self.model
        px,py=self.input_point(e.position())
        effective_k=self.k*self.preview_scale/100
        if abs(px-(m.x+m.w))*effective_k < 14 and abs(py-(m.y+m.h))*effective_k < 14:
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
        effective_k=self.k*self.preview_scale/100
        dx, dy = (e.position().x()-start.x())/effective_k, (e.position().y()-start.y())/effective_k
        m = self.model
        left, top, right, bottom = self.minimum_margins
        if mode == 'resize':
            m.w = max(5, min(m.paper_w-right-m.x, old['w']+dx))
            m.h = max(5, min(m.paper_h-bottom-m.y, old['h']+dy))
        elif mode == 'region':
            m.x = max(left, min(m.paper_w-right-m.w, old['x']+dx))
            m.y = max(top, min(m.paper_h-bottom-m.h, old['y']+dy))
        else:
            m.pan_x = max(-m.paper_w*4, min(m.paper_w*4, old['pan_x']+dx))
            m.pan_y = max(-m.paper_h*4, min(m.paper_h*4, old['pan_y']+dy))
        self.changed.emit()
        self.update()

    def mouseReleaseEvent(self, e):
        self.drag = None
        self.setCursor(Qt.CursorShape.OpenHandCursor)

    def wheelEvent(self, e):
        e.ignore()  # Zoom changes only through explicit slider/input actions.

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and e.mimeData().urls()[0].isLocalFile():
            self.set_drag_active(True)
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if self.drag_active:
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        self.set_drag_active(False)
        e.accept()

    def dropEvent(self, e):
        self.set_drag_active(False)
        self.dropped.emit(e.mimeData().urls()[0].toLocalFile())
        e.acceptProposedAction()


class ParameterWheelGuard(QObject):
    """Scrolling over a field scrolls its panel without changing the field."""
    def eventFilter(self, obj, event):
        if event.type()==QEvent.Type.Wheel:
            parent=obj.parentWidget()
            while parent is not None and not isinstance(parent,QScrollArea):
                parent=parent.parentWidget()
            if parent is not None:
                bar=parent.verticalScrollBar()
                delta=event.pixelDelta().y() or event.angleDelta().y()/120*bar.singleStep()*3
                bar.setValue(bar.value()-round(delta))
            event.accept()
            return True
        return super().eventFilter(obj,event)


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('轻印')
        self.setWindowIcon(QIcon(str(APP_ICON)))
        self.resize(1120, 810)
        self.model = Layout()
        self.driver_margins = (0, 0, 0, 0)
        self.driver_margins_known = False
        self._driver_signature = None
        self.photo = None
        self.source_photo = None
        self.turns = 0
        self._tuning_profile = ''
        self._toast = None
        self._busy_kind = ''
        self._closed = False
        self.settings = QSettings('Godles-lab', 'QuickPhotoPrintLocal')
        if not self.settings.contains('preset'):
            old=QSettings('Godles-lab','QuickPhotoPrint').value('preset','')
            if old: self.settings.setValue('preset',old)
        self.printer = QPrinter(QPrinter.PrinterMode.HighResolution)
        self.setAcceptDrops(True)
        host = QWidget()
        self.setCentralWidget(host)
        outer = QVBoxLayout(host)
        outer.setContentsMargins(22, 18, 22, 14)
        header = QHBoxLayout()
        title = QLabel('轻印')
        title.setObjectName('title')
        header.addWidget(title)
        wordmark=QLabel('PHOTO PRINT'); wordmark.setObjectName('wordmark'); header.addWidget(wordmark)
        header.addStretch()
        self.print_btn = PrintProgressButton('打印照片…')
        self.print_btn.setObjectName('primary')
        self.print_btn.setMinimumWidth(120)
        self.print_btn.setEnabled(False)
        self.print_btn.clicked.connect(self.print_photo)
        header.addWidget(self.print_btn)
        outer.addLayout(header)
        self.filename = QLabel('照片在本机处理，不会上传。')
        self.filename.setObjectName('muted')
        self.filename.setSizePolicy(QSizePolicy.Policy.Ignored,QSizePolicy.Policy.Fixed)
        outer.addWidget(self.filename)
        row = QHBoxLayout()
        self.canvas = Canvas(self.model)
        self.canvas.changed.connect(self.sync_region)
        self.canvas.zoomed.connect(lambda d: self.zoom.setValue(self.zoom.value()+d))
        self.canvas.dropped.connect(self.load)
        self.canvas.openRequested.connect(self.open_photo)
        row.addWidget(self.canvas, 1)
        side = QWidget()
        self.sidebar = side
        side.setObjectName('sidebar')
        self.controls = QVBoxLayout(side)
        self.controls.setContentsMargins(16, 16, 16, 16)
        self.controls.setSpacing(14)
        self.tabs=QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setDrawBase(False)
        self.tabs.tabBar().setExpanding(True)
        self.controls.addWidget(self.tabs,1)
        row.setSpacing(20)
        row.addWidget(side)
        outer.addLayout(row, 1)
        self.make_controls()
        for combo in side.findChildren(QComboBox):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(8)
            combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.wheel_guard=ParameterWheelGuard(self)
        for field in side.findChildren(QWidget):
            if isinstance(field,(QComboBox,QAbstractSpinBox,QSlider)):
                field.installEventFilter(self.wheel_guard)
                if isinstance(field,QAbstractSpinBox):
                    field.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        side.ensurePolished()
        needed=max(self.tabs.widget(i).widget().minimumSizeHint().width() for i in range(self.tabs.count()))
        side.setFixedWidth(max(354,needed+56))
        self.make_menus()
        self.photo_task = BackgroundTask(self)
        self.photo_task.progress.connect(self.canvas.loading_overlay.set_text)
        self.print_task = BackgroundTask(self)
        self.print_task.progress.connect(self.print_btn.set_busy)
        self.load_preset(quiet=True)
        # Migrate the old implicit ICC default once; later explicitly saved choices persist.
        if not self.settings.value('printerManagedDefaultApplied',False,type=bool):
            self.profile.setCurrentIndex(self.profile.findData(''))
            raw=self.settings.value('preset','')
            if raw:
                try:
                    preset=json.loads(raw);preset['profile']=''
                    self.settings.setValue('preset',json.dumps(preset))
                except (ValueError,TypeError): pass
            self.settings.setValue('printerManagedDefaultApplied',True)
        self.profile_changed()
        self.sync_region()
        self.refresh_printable_area()
        self.status_monitor=PrinterStatusMonitor(self)
        self.status_monitor.statusChanged.connect(self.update_printer_status)
        self.status_timer=QTimer(self)
        self.status_timer.setInterval(2000)
        self.status_timer.timeout.connect(self.refresh_current_printer_status)
        self.printer_choice.currentIndexChanged.connect(self.refresh_current_printer_status)
        self.status_timer.start()
        self.refresh_current_printer_status()

    def closeEvent(self,event):
        self._closed = True
        self.photo_task.stop()
        self.print_task.stop()
        self.canvas.set_loading(False)
        self.print_btn.set_busy(None)
        self.status_timer.stop()
        self.status_monitor.stop()
        super().closeEvent(event)

    def make_menus(self):
        menu_bar=self.menuBar()
        menu_bar.setNativeMenuBar(True)
        file_menu=menu_bar.addMenu('文件')
        self.open_action=QAction('打开照片…',self)
        self.open_action.setShortcut(QKeySequence.StandardKey.Open)
        self.open_action.triggered.connect(self.open_photo)
        file_menu.addAction(self.open_action)
        self.print_action=QAction('打印照片…',self)
        self.print_action.setShortcut(QKeySequence.StandardKey.Print)
        self.print_action.setEnabled(False)
        self.print_action.triggered.connect(self.print_photo)
        file_menu.addAction(self.print_action)
        file_menu.addSeparator()
        quit_action=QAction('退出 QuickPhotoPrint',self)
        quit_action.setMenuRole(QAction.MenuRole.QuitRole)
        quit_action.setShortcut(QKeySequence.StandardKey.Quit)
        quit_action.triggered.connect(QApplication.instance().quit)
        file_menu.addAction(quit_action)
        help_menu=menu_bar.addMenu('帮助')
        about_action=QAction('关于 QuickPhotoPrint',self)
        about_action.setMenuRole(QAction.MenuRole.AboutRole)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def show_about(self):
        QMessageBox.about(self,'关于 QuickPhotoPrint',
                          f'<b>轻印 · QuickPhotoPrint</b><br>版本 {VERSION}<br><br>本地照片排版与打印工具')

    def set_print_enabled(self, enabled):
        enabled = enabled and not self._busy_kind
        self.print_btn.setEnabled(enabled)
        if hasattr(self,'print_action'):
            self.print_action.setEnabled(enabled)

    def set_operation(self, kind=''):
        self._busy_kind = kind
        self.sidebar.setEnabled(not kind)
        self.canvas.setEnabled(not kind)
        self.canvas.setAcceptDrops(not kind)
        self.open_action.setEnabled(not kind)
        self.set_print_enabled(self.photo is not None)
        self.canvas.set_loading(kind == 'photo')
        self.print_btn.set_busy('准备打印…' if kind == 'print' else None)

    def operation_failed(self, error):
        kind = self._busy_kind
        self.set_operation()
        self.error(f'未能完成打印：{error}' if kind == 'print' else str(error))

    def group(self, name):
        index=self.tabs.count()
        page=QWidget()
        layout=QVBoxLayout(page)
        layout.setContentsMargins(0,12,8,4)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinAndMaxSize)
        box=QGroupBox()
        form=QFormLayout(box)
        form.setContentsMargins(0,0,0,0)
        form.setSpacing(12)
        layout.addWidget(box);layout.addStretch()
        scroll=QScrollArea();scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # Keep the gutter stable, but only paint a scrollbar when content overflows.
        scroll.setVerticalScrollBar(OverflowScrollBar(scroll))
        scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOn)
        scroll.setWidget(page)
        self.tabs.addTab(scroll,['相纸','排版','颜色'][index])
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
        f = self.group('01  打印机与相纸')
        self.printer_choice=StyledComboBox(BASE / 'assets')
        self.printer_choice.setToolTip('先选择打印机，工具会匹配驱动中的相纸尺寸。')
        self.refresh_printers()
        f.addRow('打印机',self.printer_choice)
        refresh=QPushButton('刷新打印机列表'); refresh.clicked.connect(self.refresh_printers)
        f.addRow(refresh)
        self.borderless=QCheckBox('优先匹配无边框纸张')
        self.borderless.setToolTip('如果驱动列出同尺寸的无边框纸张，优先选择它；仍需设备支持。')
        f.addRow(self.borderless)
        self.media_type=StyledComboBox(BASE / 'assets')
        self.print_quality=StyledComboBox(BASE / 'assets')
        self.copies=QSpinBox();self.copies.setRange(1,99);self.copies.setValue(1)
        f.addRow('纸张类型',self.media_type)
        f.addRow('打印质量',self.print_quality)
        f.addRow('份数',self.copies)
        self.printer_choice.currentIndexChanged.connect(self.refresh_media)
        self.media_type.currentIndexChanged.connect(self.media_changed)
        self.refresh_media()
        self.paper_choice = StyledComboBox(BASE / 'assets')
        for name, w, h in PAPERS:
            self.paper_choice.addItem(name, (w,h))
        f.addRow(self.paper_choice)
        self.pw = self.spin(20,420,89)
        self.ph = self.spin(20,594,127)
        f.addRow('纸张宽度',self.pw)
        f.addRow('纸张高度',self.ph)
        orient = QPushButton('横竖切换')
        orient.clicked.connect(self.swap_paper)
        f.addRow(orient)
        self.paper_choice.currentIndexChanged.connect(self.paper_preset)
        self.pw.valueChanged.connect(self.paper_changed)
        self.ph.valueChanged.connect(self.paper_changed)

        f = self.group('02  构图与打印区域')
        self.mode = StyledComboBox(BASE / 'assets')
        self.mode.addItems(['铺满区域（超出部分裁切）', '完整显示（可能留白）'])
        self.mode.currentIndexChanged.connect(self.mode_changed)
        f.addRow(self.mode)
        self.printable_note = QLabel()
        self.printable_note.setWordWrap(True); self.printable_note.setObjectName('muted')
        f.addRow(self.printable_note)
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
        reset.setToolTip('将照片与区域一起移至整张相纸中心，同步上下、左右留白，保留缩放比例。')
        pair.addWidget(rotate); pair.addWidget(reset); f.addRow(pair)
        self.margin = self.spin(0,100,0); self.margin.setDecimals(2)
        self.margin.setToolTip('输入后点击“应用白边”，统一设置四边；下方可分别调整。')
        apply_margin = QPushButton('应用白边'); apply_margin.clicked.connect(self.apply_margin)
        pair = QHBoxLayout(); pair.addWidget(self.margin); pair.addWidget(apply_margin)
        f.addRow('四边留白',pair)
        self.margins = {}
        for pair_items in [[('上','top'),('下','bottom')],[('左','left'),('右','right')]]:
            row=QHBoxLayout()
            for text,key in pair_items:
                label=QLabel(text);label.setObjectName('muted');label.setFixedWidth(18)
                spin=self.spin(0,594,0); spin.setDecimals(2); spin.setSingleStep(.1)
                spin.setAccessibleName(f'{text}留白')
                spin.valueChanged.connect(self.margins_changed)
                self.margins[key] = spin
                row.addWidget(label);row.addWidget(spin,1)
            f.addRow(row)
        full = QPushButton('恢复相纸区域'); full.clicked.connect(self.full_region)
        full.setToolTip('清除额外留白，恢复驱动允许的最大可打印区域。'); f.addRow(full)
        self.compensation_toggle=QToolButton()
        self.compensation_toggle.setText('预览尺寸补偿')
        self.compensation_toggle.setCheckable(True)
        self.compensation_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.compensation_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.compensation_toggle.setObjectName('advancedToggle')
        f.addRow(self.compensation_toggle)
        self.compensation_panel=QWidget()
        advanced=QFormLayout(self.compensation_panel)
        advanced.setContentsMargins(0,0,0,0)
        self.preview_scale=QDoubleSpinBox()
        self.preview_scale.setRange(PREVIEW_SCALE_MIN,PREVIEW_SCALE_MAX);self.preview_scale.setDecimals(1)
        self.preview_scale.setSingleStep(.5);self.preview_scale.setSuffix(' %')
        self.preview_scale.setValue(100);self.preview_scale.setKeyboardTracking(False)
        self.preview_scale.valueChanged.connect(self.canvas.set_preview_scale)
        self.canvas.set_preview_scale(self.preview_scale.value())
        advanced.addRow('预览比例',self.preview_scale)
        note=QLabel('按实物校准预览大小与裁切，不改变打印尺寸。\n100% 为未补偿，调大可模拟更多扩印。')
        note.setObjectName('muted');note.setWordWrap(True)
        advanced.addRow(note)
        f.addRow(self.compensation_panel)
        compensation_form=f
        compensation_page=self.tabs.widget(1).widget()
        compensation_form.setRowVisible(self.compensation_panel,False)
        def toggle_compensation(expanded):
            compensation_form.setRowVisible(self.compensation_panel,expanded)
            self.compensation_toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
            compensation_page.layout().activate()
            compensation_page.adjustSize()
        self.compensation_toggle.toggled.connect(toggle_compensation)

        f = self.group('03  颜色与输出')
        self.profile = ProfileComboBox(BASE / 'assets')
        self.profile.addItem('由打印机管理颜色', '')
        self.profile.addItem('普通RGB配置', STANDARD_RGB)
        self.profile.addItem('Brother·柯达·高光', str(BUILTIN))
        self.profile.addItem('导入其他配置文件...', IMPORT_PROFILE)
        self.restore_imported_profiles()
        self.profile.setCurrentIndex(0)
        self.profile.setToolTip('内置配置适合 Brother DCP-T735DW + 柯达高光；其他相纸请选择对应的 RGB ICC。')
        self.profile.setItemData(1, '标准 sRGB，不含打印机或相纸专属补偿。', Qt.ItemDataRole.ToolTipRole)
        self.profile.importRequested.connect(self.choose_icc)
        self.profile.removeRequested.connect(self.remove_imported_profile)
        f.addRow('ICC 配置文件',self.profile)
        self.tuning_toggle = QToolButton()
        self.tuning_toggle.setText('微调设置')
        self.tuning_toggle.setCheckable(True)
        self.tuning_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.tuning_toggle.setArrowType(Qt.ArrowType.RightArrow)
        self.tuning_toggle.setObjectName('advancedToggle')
        f.addRow(self.tuning_toggle)
        self.tuning = ColorControls()
        self.tuning.saveRequested.connect(self.save_edited_icc)
        f.addRow(self.tuning)
        tuning_form = f
        tuning_page = self.tabs.widget(2).widget()
        tuning_form.setRowVisible(self.tuning, False)
        def toggle_tuning(expanded):
            tuning_form.setRowVisible(self.tuning, expanded)
            self.tuning_toggle.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
            tuning_page.layout().activate()
            tuning_page.adjustSize()
        self.tuning_toggle.toggled.connect(toggle_tuning)
        self.intent = StyledComboBox(BASE / 'assets')
        self.intent.addItem('相对比色',1); self.intent.addItem('可感知',0); self.intent.addItem('饱和度',2); self.intent.addItem('绝对比色',3)
        f.addRow('渲染意图',self.intent)
        self.bpc = QCheckBox('黑点补偿'); f.addRow(self.bpc)
        self.profile.currentIndexChanged.connect(self.profile_changed)
        self.dpi = StyledComboBox(BASE / 'assets')
        for dpi in (300,600): self.dpi.addItem(f'{dpi} dpi',dpi)
        f.addRow('分辨率',self.dpi)
        pair = QHBoxLayout()
        self.save_preset_btn = QPushButton('保存当前预设'); self.save_preset_btn.clicked.connect(self.save_preset)
        restore = QPushButton('恢复预设'); restore.clicked.connect(self.load_preset)
        pair.addWidget(self.save_preset_btn); pair.addWidget(restore); self.controls.addLayout(pair)
        self.controls.addStretch()
        self.printer_choice.currentIndexChanged.connect(self.refresh_printable_area)
        self.borderless.toggled.connect(self.refresh_printable_area)
        self.dpi.currentIndexChanged.connect(self.refresh_printable_area)

    def refresh_printers(self):
        old=self.printer_choice.currentData() or self.settings.value('printer','')
        # Rebuild atomically: temporary empty/first entries must not reset media.
        with QSignalBlocker(self.printer_choice):
            self.printer_choice.clear()
            default=QPrinterInfo.defaultPrinterName()
            for info in QPrinterInfo.availablePrinters():
                code, status = printer_status(info)
                name = info.description() or info.printerName()
                self.printer_choice.addItem(name, info.printerName())
                self.update_printer_status(info.printerName(),code,status)
            selected=self.printer_choice.findData(old)
            if selected<0: selected=self.printer_choice.findData(default)
            self.printer_choice.setCurrentIndex(max(0,selected))
        self.refresh_media()
        self.refresh_printable_area(force=True)
        self.refresh_current_printer_status()

    def refresh_current_printer_status(self):
        if hasattr(self,'status_monitor'):
            self.status_monitor.request(self.printer_choice.currentData() or '')

    def update_printer_status(self,printer_name,code,status):
        index=self.printer_choice.findData(printer_name)
        if index<0:return
        name=self.printer_choice.itemText(index)
        self.printer_choice.setItemIcon(index,printer_status_icon(code))
        self.printer_choice.setItemData(index,status,TRAILING_TEXT_ROLE)
        self.printer_choice.setItemData(index,PRINTER_STATUS_COLORS[code],TRAILING_COLOR_ROLE)
        self.printer_choice.setItemData(index,f'{name}，{status}',Qt.ItemDataRole.AccessibleTextRole)
        self.printer_choice.setItemData(index,f'{name}\n系统队列：{printer_name}\n状态：{status}',Qt.ItemDataRole.ToolTipRole)

    def refresh_media(self):
        if not hasattr(self,'media_type'): return
        previous=self.media_type.currentData()
        previous_quality=self.print_quality.currentData()
        try: self.media_options=capabilities(self.printer_choice.currentData())
        except Exception: self.media_options={}
        self.media_type.blockSignals(True)
        self.media_type.clear();self.media_type.addItem('系统打印窗口中选择',None)
        for value in self.media_options.get('MediaType',[]):
            self.media_type.addItem(LABELS.get(value,value),value)
        index=self.media_type.findData(previous)
        self.media_type.setCurrentIndex(max(0,index))
        self.media_type.blockSignals(False)
        self.print_quality.clear()
        for value in self.media_options.get('cupsPrintQuality',[]):
            self.print_quality.addItem(QUALITY.get(value,value),value)
        quality=self.print_quality.findData(previous_quality)
        if quality<0:quality=self.print_quality.findData('High')
        self.print_quality.setCurrentIndex(max(0,quality))
        self.media_changed()

    def media_changed(self):
        direct=bool(self.media_type.currentData())
        self.print_quality.setEnabled(direct);self.copies.setEnabled(direct)

    def profile_changed(self):
        profile = self.profile.selected_profile()
        if profile != self._tuning_profile:
            self._tuning_profile = profile
            self.tuning.set_adjustment(ColorAdjustment())
        enabled = bool(profile)
        self.tuning.setEnabled(enabled)
        self.tuning_toggle.setEnabled(enabled)
        if not enabled:
            self.tuning_toggle.setChecked(False)
        self.intent.setEnabled(enabled); self.bpc.setEnabled(enabled)

    def save_edited_icc(self):
        profile = self.profile.selected_profile()
        if not profile:
            return
        stem = 'sRGB' if profile == STANDARD_RGB else Path(profile).stem
        folder = self.settings.value('iccExportDirectory', QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation))
        # Keep the platform-native save panel and its system-provided labels.
        # macOS localization is declared in the bundle's Info.plist (build.py).
        filename, _ = QFileDialog.getSaveFileName(self, '另存微调后的 ICC',
            str(Path(folder) / f'{stem}-Adjusted.icc'), 'ICC 配置 (*.icc)')
        if not filename:
            return
        destination = Path(filename)
        if not destination.suffix:
            destination = destination.with_suffix('.icc')
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            if not Path(filename).suffix and destination.exists():
                raise ValueError('同名 ICC 已存在，请在保存窗口中选择完整文件名或换一个名称。')
            path = save_adjusted_profile(profile, destination, self.tuning.adjustment())
            self.settings.setValue('iccExportDirectory', str(path.parent))
            self.notify(self.tuning.save_button, 'ICC 已保存，可自行导入；导入后微调从 0 开始。')
        except Exception as exc:
            self.error(f'无法保存 ICC：{exc}')
        finally:
            QApplication.restoreOverrideCursor()

    def paper_preset(self):
        if self.paper_choice.currentIndex() == len(PAPERS)-1:
            self.sync_paper_choice()
            self.pw.setFocus();self.pw.selectAll()
            return
        w,h = self.paper_choice.currentData()
        if self.photo is not None and self.photo.width > self.photo.height:
            w,h = h,w
        for control,value in [(self.pw,w),(self.ph,h)]:
            control.blockSignals(True); control.setValue(value); control.blockSignals(False)
        self.paper_changed()

    def paper_changed(self):
        self.model.paper_w,self.model.paper_h = self.pw.value(),self.ph.value()
        self.sync_paper_choice()
        self.refresh_printable_area(reset=True)

    def sync_paper_choice(self):
        # Updating the label must not reapply a preset or reset crop/zoom.
        index=paper_preset_index(self.model.paper_w,self.model.paper_h)
        with QSignalBlocker(self.paper_choice):
            self.paper_choice.setCurrentIndex(index)

    def refresh_printable_area(self, *args, force=False, reset=False):
        if not hasattr(self, 'dpi'): return
        signature = (self.printer_choice.currentData(), self.model.paper_w, self.model.paper_h,
                     self.borderless.isChecked(), self.dpi.currentData())
        if force or signature != self._driver_signature:
            try:
                minimum = read_printable_margins(*signature)
                minimum = validated_driver_margins(minimum, self.model.paper_w, self.model.paper_h)
            except Exception:
                minimum = None
            self.set_driver_margins(minimum, reset=reset)
            self._driver_signature = signature
        elif reset:
            self.full_region()
        else:
            self.constrain_region()
            self.sync_region()

    def set_driver_margins(self, minimum, reset=False):
        was_full = all(abs(a-b) < .02 for a,b in zip(self.model.margins(), self.driver_margins))
        self.driver_margins_known = minimum is not None
        self.driver_margins = minimum if minimum is not None else (0, 0, 0, 0)
        self.canvas.minimum_margins = self.driver_margins
        left, top, right, bottom = self.driver_margins
        if minimum is None:
            text = '未读取到驱动边距；当前仅显示设置的留白。'
        elif not any(minimum):
            text = '当前驱动边距为 0 mm；可铺满相纸，也可另设留白。'
        else:
            text = f'驱动最小留白（mm）：上 {top:g} · 下 {bottom:g} · 左 {left:g} · 右 {right:g}。'
        self.printable_note.setText(text)
        if reset:
            self.full_region()
        elif was_full:
            self.model.set_margins(*self.driver_margins)
            self.sync_region()
        else:
            self.constrain_region()
            self.sync_region()

    def constrain_region(self):
        m = self.model
        dl, dt, dr, db = self.driver_margins
        left, top, right, bottom = m.margins()
        left = min(max(left, dl), m.paper_w-dr-5)
        top = min(max(top, dt), m.paper_h-db-5)
        right = min(max(right, dr), m.paper_w-left-5)
        bottom = min(max(bottom, db), m.paper_h-top-5)
        m.set_margins(left, top, max(dr, right), max(db, bottom))

    def swap_paper(self):
        w,h = self.model.paper_h,self.model.paper_w
        if w>420:
            return self.error('旋转后宽度超过 420 mm，请先缩小纸张。')
        for control,value in [(self.pw,w),(self.ph,h)]:
            control.blockSignals(True); control.setValue(value); control.blockSignals(False)
        self.paper_changed()

    def mode_changed(self):
        self.model.fill = self.mode.currentIndex()==0
        self.reset_photo_position()

    def reset_photo_position(self):
        self.model.pan_x = self.model.pan_y = 0
        self.zoom.setValue(100)
        self.model.zoom = 1
        self.canvas.update()

    def center_photo(self):
        try:
            self.model.center_on_paper(self.driver_margins)
        except ValueError:
            return self.error('驱动边距过大，无法在相纸中心放置至少 5 × 5 mm 的区域。')
        self.sync_region()

    def zoom_changed(self,value):
        self.model.zoom=value/100
        self.zoom_value.blockSignals(True); self.zoom_value.setValue(value); self.zoom_value.blockSignals(False)
        self.canvas.update()

    def full_region(self):
        self.model.set_margins(*self.driver_margins)
        self.reset_photo_position(); self.sync_region()

    def apply_margin(self):
        m=self.model; margin=self.margin.value()
        try:
            m.set_margins(margin, margin, margin, margin)
        except ValueError:
            return self.error('白边过大，剩余打印区域至少需要 5 × 5 mm。')
        self.reset_photo_position(); self.sync_region()

    def margins_changed(self):
        self.model.set_margins(*(self.margins[key].value() for key in ('left', 'top', 'right', 'bottom')))
        self.sync_region()

    def sync_region(self):
        import math
        values = dict(zip(('left', 'top', 'right', 'bottom'), self.model.margins()))
        minimums = dict(zip(('left', 'top', 'right', 'bottom'), self.driver_margins))
        for key, opposite, dimension in (('left','right',self.model.paper_w), ('right','left',self.model.paper_w),
                                         ('top','bottom',self.model.paper_h), ('bottom','top',self.model.paper_h)):
            c = self.margins[key]
            c.blockSignals(True)
            maximum = math.floor((dimension-values[opposite]-5)*100+1e-8)/100
            c.setRange(minimums[key], max(minimums[key], maximum))
            c.setValue(values[key]); c.blockSignals(False)
        self.margin.blockSignals(True)
        max_uniform = math.floor((min(self.model.paper_w, self.model.paper_h)-5)*50+1e-8)/100
        self.margin.setRange(max(self.driver_margins), max(max(self.driver_margins), max_uniform))
        if max(values.values())-min(values.values()) < .01:
            self.margin.setValue(values['left'])
        self.margin.blockSignals(False)
        self.canvas.update()

    def open_photo(self):
        if self._busy_kind or self._closed: return
        path,_=QFileDialog.getOpenFileName(self,'打开照片','','照片 (*.jpg *.jpeg *.png *.tif *.tiff *.bmp *.webp)')
        if path: self.load(path)

    def load(self,path):
        if self._busy_kind or self._closed: return
        self.set_operation('photo')
        def read(progress):
            progress('正在载入照片…')
            image,note=load_photo(path)
            progress('正在生成预览…')
            return image,note,preview_image(image)
        def loaded(result):
            image,note,preview=result
            self.source_photo=image; self.photo=image; self.turns=0
            self.filename.setText(f'{Path(path).name}  ·  {image.width} × {image.height} px  ·  {note}')
            self.canvas.set_photo(image,preview)
            self.match_photo_orientation()
            self.reset_photo_position()
            self.set_operation()
        self.photo_task.start(read,loaded,self.operation_failed)

    def match_photo_orientation(self):
        """Use the EXIF-corrected photo orientation; square photos keep the paper direction."""
        if self.photo is None or self.photo.width == self.photo.height:
            return
        w,h=self.model.paper_w,self.model.paper_h
        if w == h or (w > h) == (self.photo.width > self.photo.height):
            return
        if h > self.pw.maximum():
            return
        for control,value in ((self.pw,h),(self.ph,w)):
            control.blockSignals(True);control.setValue(value);control.blockSignals(False)
        self.paper_changed()

    def rotate(self):
        if self.source_photo is None: return
        self.turns=(self.turns+1)%4
        self.photo=self.source_photo.rotate(-90*self.turns,expand=True)
        self.canvas.set_photo(self.photo); self.reset_photo_position()

    def choose_icc(self):
        path,_=QFileDialog.getOpenFileName(self,'选择 RGB 输出配置','','ICC 配置 (*.icc *.icm)')
        if not path: return
        try:
            name=check_profile(path)
            self.profile.setCurrentIndex(self.add_imported_profile(path, name))
        except Exception as exc: self.error(f'无法使用这个 ICC：{exc}')

    def restore_imported_profiles(self):
        try:
            entries = json.loads(self.settings.value('importedProfiles', '[]'))
        except (ValueError, TypeError):
            return
        if not isinstance(entries, list): return
        for entry in entries:
            if not isinstance(entry, dict) or not isinstance(entry.get('path'), str) or not entry['path']: continue
            path = str(Path(entry['path']).expanduser().resolve())
            if path == str(BUILTIN.resolve()): continue
            self.profile.add_custom(path, str(entry.get('description', Path(path).stem)))

    def persist_imported_profiles(self):
        entries = [{'path': self.profile.itemData(i), 'description': self.profile.itemData(i, DESCRIPTION_ROLE)}
                   for i in range(self.profile.count()) if self.profile.itemData(i, CUSTOM_ROLE)]
        self.settings.setValue('importedProfiles', json.dumps(entries))

    def add_imported_profile(self, path, description):
        path = str(Path(path).expanduser().resolve())
        if path == str(BUILTIN.resolve()):
            return self.profile.findData(str(BUILTIN))
        index = self.profile.add_custom(path, description)
        self.persist_imported_profiles()
        return index

    def remove_imported_profile(self, path):
        index = self.profile.findData(path)
        if index < 0 or not self.profile.itemData(index, CUSTOM_ROLE): return
        if self.profile.selected_profile() == path:
            self.profile.setCurrentIndex(self.profile.findData(''))
        self.profile.removeItem(index)
        self.persist_imported_profiles()
        # A removed entry must not be re-imported by the saved preset on restart.
        try:
            preset = json.loads(self.settings.value('preset', '{}'))
            saved = preset.get('profile')
            if saved and saved not in ('builtin', STANDARD_RGB) and str(Path(saved).expanduser().resolve()) == path:
                preset['profile'] = ''
                self.settings.setValue('preset', json.dumps(preset))
        except (ValueError, TypeError, AttributeError):
            pass
        self.notify(self.profile, '已从列表移除；原始 ICC 文件保留。')

    def print_request(self, dpi):
        return {'photo':self.photo, 'layout':Layout(**asdict(self.model)),
                'profile':self.profile.selected_profile(), 'intent':self.intent.currentData(),
                'bpc':self.bpc.isChecked(), 'adjustment':self.tuning.adjustment(), 'dpi':dpi,
                'name':self.printer_choice.currentData(), 'borderless':self.borderless.isChecked(),
                'media':self.media_type.currentData(), 'quality':self.print_quality.currentData(),
                'copies':self.copies.value(), 'minimum_margins':self.driver_margins}

    def print_photo(self):
        if self._busy_kind or self._closed: return
        if self.photo is None: return self.error('请先打开照片。')
        request=self.print_request(self.dpi.currentData())
        printer=self.printer
        self.set_operation('print')
        def prepare(progress):
            progress('准备打印…')
            model=request['layout'];model.validate()
            dpi=request['dpi']
            if round(model.paper_w*dpi/25.4)*round(model.paper_h*dpi/25.4)>40_000_000:
                raise ValueError('此尺寸在 600 dpi 下过大，请改为 300 dpi。')
            if not QPrinterInfo.availablePrinters():
                raise ValueError('系统中未找到打印机，请先在系统设置中添加。')
            if request['profile']:check_profile(request['profile'])
            info=QPrinterInfo.printerInfo(request['name'] or '')
            if info.isNull():raise ValueError('所选打印机已不可用，请刷新打印机列表。')
            try:
                minimum=read_printable_margins(request['name'],model.paper_w,model.paper_h,request['borderless'],dpi)
                minimum=validated_driver_margins(minimum,model.paper_w,model.paper_h)
            except Exception:
                minimum=None
            if printer.printerName()!=request['name']:printer.setPrinterName(request['name'])
            printer.setResolution(dpi)
            printer.setColorMode(QPrinter.ColorMode.Color)
            printer.setDocName('Quick Photo Print')
            matched=configure_paper(printer,info,model.paper_w,model.paper_h,request['borderless'])
            options=capabilities(info.printerName()) if request['media'] else None
            return info,matched,minimum,options
        self.print_task.start(prepare,lambda result:self.print_prepared(request,result),self.operation_failed)

    def print_prepared(self, request, result):
        info,matched,minimum,options=result
        self.set_driver_margins(minimum)
        self._driver_signature=(request['name'],self.model.paper_w,self.model.paper_h,
                                request['borderless'],request['dpi'])
        self.model.validate()
        request['layout']=Layout(**asdict(self.model))
        request['minimum_margins']=self.driver_margins
        self.settings.setValue('printer',request['name'])
        if request['media']:
            self.print_with_media(info,matched,request['dpi'],request=request,options=options)
            return
        dialog=QPrintDialog(self.printer,self)
        dialog.setWindowTitle('打印照片 · 请核对相纸、无边距与颜色设置')
        preview_margins,known=self.driver_margins,self.driver_margins_known
        self.print_btn.set_busy(None)
        if dialog.exec()!=QDialog.DialogCode.Accepted:
            self.set_operation()
            return
        if self._closed:return
        self.print_btn.set_busy('准备打印…')
        selected=self.printer_choice.findData(self.printer.printerName())
        if selected>=0:self.printer_choice.setCurrentIndex(selected)
        self.settings.setValue('printer',self.printer.printerName())
        actual=self.printer.pageLayout().fullRect(QPageLayout.Unit.Millimeter)
        model=request['layout']
        if abs(actual.width()-model.paper_w)>1 or abs(actual.height()-model.paper_h)>1:
            raise ValueError(f'系统最终纸张为 {actual.width():.1f} × {actual.height():.1f} mm，与预览 {model.paper_w:g} × {model.paper_h:g} mm 不一致。本次未发送，请调整纸张后重试。')
        if known and any(abs(a-b)>.05 for a,b in zip(printer_minimum_margins(self.printer),preview_margins)):
            raise ValueError('系统最终可打印边距与预览不一致。本次未发送，请核对无边框模式并刷新打印机后重试。')
        self.printer.setFullPage(True)
        self.submit_prepared_photo(request)

    def print_with_media(self, info, matched, dpi, *, request=None, options=None):
        if request is None:
            if self._busy_kind or self._closed:return
            request=self.print_request(dpi)
            self.set_operation('print')
            # Re-read options before confirmation; stale choices must never fall back silently.
            self.print_task.start(lambda progress:capabilities(info.printerName()),
                lambda options:self.print_with_media(info,matched,dpi,request=request,options=options),
                self.operation_failed)
            return
        args=job_arguments(info.printerName(),matched.key(),request['media'],request['quality'],
                           request['copies'],options)
        model=request['layout']
        left,top,right,bottom=model.margins()
        paper=paper_description(model.paper_w,model.paper_h)
        if borderless_page(matched):paper+=' · 无边框'
        details=[('打印机',info.description() or info.printerName()),
                 ('纸张',paper),
                 ('纸张类型',self.media_type.currentText()),
                 ('打印质量',f"{self.print_quality.currentText()}  ·  {request['copies']} 份"),
                 ('留白（mm）',f'上 {top:g} / 下 {bottom:g} / 左 {left:g} / 右 {right:g}'),
                 ('ICC 配置',self.profile.currentText())]
        self.print_btn.set_busy(None)
        dialog=PrintConfirmationDialog(details,self)
        if dialog.exec()!=QDialog.DialogCode.Accepted:
            self.set_operation()
            return
        if not self._closed:self.submit_prepared_photo(request,args,info)

    def submit_prepared_photo(self, request, arguments=None, info=None):
        printer=self.printer
        self.print_btn.set_busy('处理照片…')
        def submit(progress):
            import tempfile
            # Worker reads a snapshot; all GUI/driver settings stay locked until completion.
            progress('处理照片…')
            converted=convert_output(request['photo'],request['profile'],request['intent'],
                                     request['bpc'],request['adjustment'])
            progress('生成排版…')
            page=render_output(converted,request['layout'],request['dpi'],
                               minimum_margins=request['minimum_margins'])
            if arguments is None:
                progress('正在提交…')
                paint_printer(printer,page)
            else:
                with tempfile.TemporaryDirectory(prefix='quickprint-') as folder:
                    pdf=QPrinter(QPrinter.PrinterMode.HighResolution)
                    pdf.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
                    filename=Path(folder)/'print.pdf'
                    pdf.setOutputFileName(str(filename));pdf.setResolution(request['dpi'])
                    model=request['layout']
                    configure_paper(pdf,info,model.paper_w,model.paper_h,request['borderless'])
                    paint_printer(pdf,page)
                    progress('正在提交…')
                    submit_pdf(arguments,filename.read_bytes())
        self.print_task.start(submit,self.print_submitted,self.operation_failed)

    def print_submitted(self, result):
        self.set_operation()
        self.notify(self.print_btn,'已提交到系统打印队列。')
        self.refresh_current_printer_status()

    def save_preset(self):
        profile=self.profile.selected_profile()
        data={'layout':asdict(self.model),'profile':'builtin' if profile==str(BUILTIN) else profile,
              'intent':self.intent.currentData(),'bpc':self.bpc.isChecked(),'dpi':self.dpi.currentData(),
              'borderless':self.borderless.isChecked(),'preview_scale':self.preview_scale.value(),'media_type':self.media_type.currentData(),
              'print_quality':self.print_quality.currentData(),'copies':self.copies.value(),
              'color_tuning':asdict(self.tuning.adjustment())}
        self.settings.setValue('preset',json.dumps(data))
        self.notify(self.save_preset_btn, '预设已保存。')

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
            self.sync_paper_choice()
            profile=d.get('profile','')
            if profile=='builtin': self.profile.setCurrentIndex(self.profile.findData(str(BUILTIN)))
            elif profile == STANDARD_RGB: self.profile.setCurrentIndex(self.profile.findData(STANDARD_RGB))
            elif not profile: self.profile.setCurrentIndex(self.profile.findData(''))
            elif Path(profile).is_file():
                self.profile.setCurrentIndex(self.add_imported_profile(profile, check_profile(profile)))
            else:
                self.profile.setCurrentIndex(self.profile.findData(''))
                if not quiet: self.error('预设中的 ICC 已找不到，已改为打印机管理颜色，请重新选择。')
            self.intent.setCurrentIndex(max(0,self.intent.findData(d.get('intent',1))))
            self.bpc.setChecked(bool(d.get('bpc',False)))
            self.tuning.set_adjustment(ColorAdjustment(**d.get('color_tuning', {})) if self.profile.selected_profile() else ColorAdjustment())
            self.borderless.blockSignals(True)
            self.borderless.setChecked(bool(d.get('borderless',False)))
            self.borderless.blockSignals(False)
            # Old percentages are now preview calibration only; never scale print data.
            self.preview_scale.setValue(float(d.get('preview_scale',d.get('output_scale',100))))
            media_index=self.media_type.findData(d.get('media_type'))
            self.media_type.setCurrentIndex(max(0,media_index))
            quality_index=self.print_quality.findData(d.get('print_quality','High'))
            self.print_quality.setCurrentIndex(max(0,quality_index))
            self.copies.setValue(int(d.get('copies',1)))
            self.dpi.blockSignals(True)
            self.dpi.setCurrentIndex(max(0,self.dpi.findData(d.get('dpi',300))))
            self.dpi.blockSignals(False)
            self.refresh_printable_area()
        except Exception:
            if not quiet: self.error('无法恢复这个预设，请重新设置并保存。')

    def dragEnterEvent(self,e):
        if not self._busy_kind and e.mimeData().hasUrls() and e.mimeData().urls()[0].isLocalFile(): e.acceptProposedAction()
    def dropEvent(self,e): self.load(e.mimeData().urls()[0].toLocalFile())
    def notify(self, anchor, text, duration=2600):
        host=self.centralWidget()
        if self._toast is not None:
            previous=self._toast
            self._toast=None
            previous.hide();previous.deleteLater()
        bubble=QLabel(text,host)
        bubble.setObjectName('toast')
        bubble.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        bubble.setContentsMargins(14,9,14,9)
        bubble.adjustSize()
        anchor_pos=anchor.mapTo(host,anchor.rect().topLeft())
        x=anchor_pos.x()+(anchor.width()-bubble.width())//2
        x=max(8,min(x,host.width()-bubble.width()-8))
        above=anchor_pos.y()-bubble.height()-8
        if above>=8:
            y=above
        else:
            y=anchor_pos.y()+anchor.height()+8
        y=max(8,min(y,host.height()-bubble.height()-8))
        bubble.move(x,y);bubble.show();bubble.raise_()
        self._toast=bubble
        QTimer.singleShot(duration,lambda: self.dismiss_toast(bubble))
    def dismiss_toast(self,bubble):
        if self._toast is not bubble:return
        self._toast=None
        bubble.hide();bubble.deleteLater()
    def error(self,text): QMessageBox.warning(self,'轻印',text)


def paint_printer(printer,page):
    painter=QPainter()
    if not painter.begin(printer): raise RuntimeError('无法启动打印任务。')
    try:
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        target=printer.pageLayout().fullRectPixels(printer.resolution())
        painter.drawImage(QRectF(target),qimage(page))
    finally:
        ok=painter.end()
    if not ok or printer.printerState()==QPrinter.PrinterState.Error:
        raise RuntimeError('系统打印引擎报告错误，请检查打印队列。')


def configure_app(app):
    install_system_translations(app,BASE)
    app.setStyle('Fusion')
    app.setApplicationName('QuickPhotoPrint')
    app.setApplicationDisplayName('QuickPhotoPrint')
    app.setApplicationVersion(VERSION)
    app.setOrganizationName('Godles-lab')
    app.setOrganizationDomain('godleslab.github.io')
    app.setWindowIcon(QIcon(str(APP_ICON)))
    families=QFontDatabase.families()
    for family in ('PingFang SC','Microsoft YaHei UI','Noto Sans CJK SC','Segoe UI'):
        if family in families:
            app.setFont(QFont(family,10));break
    assets=(BASE/'assets').as_posix()
    style = """
        QWidget { font-size: 13px; color: #24333E; }
        QMainWindow { background: #F5F7F9; }
        QDialog#printConfirmation { background: #F5F7F9; }
        QLabel#dialogTitle { font-size: 20px; font-weight: 600; color: #173E36; }
        QWidget#printDetails { background: #FFFFFF; border: 1px solid #E0E6EB; border-radius: 14px; }
        QWidget#loadingCard { background: #FFFFFF; border: 1px solid #E0E6EB; border-radius: 14px; }
        QLabel#loadingTitle { color: #173E36; font-size: 15px; font-weight: 600; }
        QWidget#sidebar { background: #FFFFFF; border: 1px solid #E0E6EB; border-radius: 14px; }
        QLabel#title { font-size: 27px; font-weight: 600; color: #173E36; }
        QLabel#wordmark { font-size: 11px; font-weight: 600; color: #85948E; padding-left: 10px; }
        QLabel#sectionTitle { font-size: 16px; font-weight: 600; padding-top: 2px; }
        QLabel#muted { color: #73818D; font-size: 12px; }
        QGroupBox { border: none; background: transparent; }
        QScrollArea, QScrollArea > QWidget > QWidget, QTabWidget::pane { background: transparent; border: none; }
        QTabBar::tab { background: transparent; color: #73818D; border: none; border-bottom: 2px solid #E5EAED; border-radius: 0; padding: 12px 27px; margin: 0; }
        QTabBar::tab:selected { background: transparent; color: #176B56; font-weight: 600; border-bottom: 2px solid #18745D; }
        QTabBar::tab:hover:!selected { background: #F7FAF8; color: #436B5D; }
        QPushButton { background: #FFFFFF; border: 1px solid #DCE3E8; border-radius: 8px; padding: 9px 12px; }
        QPushButton:hover { background: #F1F7F4; border-color: #90B7A7; }
        QPushButton:pressed { background: #E5F0EA; }
        QPushButton#primary { background: #18745D; color: white; border: 1px solid #18745D; font-weight: 600; padding: 10px 24px; }
        QPushButton#primary:hover { background: #125E4B; }
        QPushButton#primary:disabled { color: #9DA9AF; background: #E9EEF1; border-color: #DCE3E8; }
        QPushButton#primary[busy="true"] { color: white; background: #18745D; border-color: #18745D; }
        QPushButton#canvasPhotoAction { background: rgba(255,255,255,238); border-color: #C9D7D2; font-weight: 600; }
        QPushButton#canvasPhotoAction:hover { background: #F1F7F4; border-color: #6EA58F; }
        QPushButton:disabled { color: #A2ADB5; background: #F1F4F6; }
        QComboBox, QSpinBox, QDoubleSpinBox { background: #F8FAFB; border: 1px solid #E2E7EB; border-radius: 7px; padding: 7px 10px; min-height: 20px; selection-background-color: #D8EBE3; selection-color: #173E36; }
        QComboBox { padding-right: 26px; }
        QComboBox:focus, QSpinBox:focus, QDoubleSpinBox:focus { border-color: #4B9B7E; background: white; }
        QComboBox::drop-down { border: none; width: 26px; }
        QComboBox::down-arrow { image: url(ASSET/chevron.svg); width: 16px; height: 16px; }
        QComboBox QAbstractItemView { background: white; border: 1px solid #DFE6EA; padding: 5px; selection-background-color: #E5F2ED; selection-color: #176B56; outline: none; }
        QFrame#comboPopupContainer { background: transparent; border: none; }
        QListView#comboPopup { background: white; border: 1px solid #DCE3E8; border-radius: 9px; padding: 5px; outline: none; }
        QSlider::groove:horizontal { height: 4px; background: #DFE7E3; border-radius: 2px; }
        QSlider::sub-page:horizontal { background: #398F72; border-radius: 2px; }
        QSlider::handle:horizontal { width: 14px; margin: -5px 0; background: #18745D; border-radius: 7px; }
        QCheckBox { spacing: 8px; }
        QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #CCD8D1; border-radius: 4px; background: white; }
        QCheckBox::indicator:checked { background: #18745D; border-color: #18745D; image: url(ASSET/check.svg); }
        QScrollBar:vertical { background: transparent; width: 7px; margin: 3px 0; }
        QScrollBar::handle:vertical { background: #CBD5D9; border-radius: 3px; min-height: 38px; }
        QScrollBar::handle:vertical:hover { background: #9FADB4; }
        QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; border: none; background: transparent; }
        QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; }
        QToolButton#advancedToggle { border: none; background: #F1F5F3; border-radius: 7px; padding: 9px; color: #436B5D; text-align: left; }
        QToolButton#advancedToggle:hover { background: #E5F0EA; }
        QLabel#toast { background: #214C40; color: white; border: none; border-radius: 7px; font-size: 12px; }
        QToolTip { background: #263D35; color: white; border: none; padding: 6px; }
    """
    app.setStyleSheet(style.replace('ASSET',assets))



def main():
    app=QApplication(sys.argv)
    configure_app(app)
    if '--smoke-test' in sys.argv:
        # Exercise the frozen bundle with synthetic pixels only; never spool a job.
        try:
            import tempfile
            from PySide6.QtCore import QLocale
            assert install_system_translations(app,BASE,QLocale('zh_CN'))
            assert app.translate('QPrintDialog','Print')=='打印'
            assert not QImage(str(BASE/'assets'/'chevron.svg')).isNull()
            assert not app.windowIcon().isNull()
            w=Window(); w.show(); app.processEvents()
            sample=convert_output(Image.new('RGB',(60,90),(128,128,128)),BUILTIN)
            page=render_page(sample,Layout())
            with tempfile.TemporaryDirectory() as folder:
                # The frozen app must include and execute the asynchronous photo loader.
                from PySide6.QtCore import QEventLoop
                photo_path=Path(folder)/'load-test.png'
                Image.new('RGB',(80,120),(60,110,90)).save(photo_path)
                errors=[];w.error=errors.append
                w.load(str(photo_path))
                assert w._busy_kind=='photo' and w.canvas.loading_overlay.bar.timer.isActive()
                loop=QEventLoop()
                poll=QTimer();poll.setInterval(10)
                poll.timeout.connect(lambda:loop.quit() if not w._busy_kind else None)
                timeout=QTimer();timeout.setSingleShot(True);timeout.timeout.connect(loop.quit)
                poll.start();timeout.start(10000);loop.exec();poll.stop();timeout.stop()
                assert not errors and not w._busy_kind and w.photo.size==(80,120)
                assert w.canvas.loading_overlay.isHidden()
                edited = save_adjusted_profile(str(BUILTIN), Path(folder)/'Adjusted.icc',
                                               ColorAdjustment(brightness=12, red=-10))
                assert check_profile(edited) == 'Adjusted'
                w.profile.setCurrentIndex(w.profile.findData(''))
                w.profile.setCurrentIndex(w.profile.findData(str(BUILTIN)))
                assert not w.tuning.adjustment().active and w.tuning.isHidden()
                w.profile.setCurrentIndex(w.profile.findData(STANDARD_RGB))
                w.source_photo = w.photo = Image.new('RGB', (60,90), (128,104,80))
                w.canvas.set_photo(w.photo)
                preview_key = w.canvas.photo.cacheKey()
                w.tuning.sliders['red'].setValue(-10)
                assert w.tuning.adjustment().red == -10
                app.processEvents()
                assert w.canvas.photo.cacheKey() == preview_key
                w.preview_scale.setValue(200)
                app.processEvents()
                assert w.preview_scale.value() == w.canvas.preview_scale == 200
                live = convert_output(Image.new('RGB',(1,1),(128,128,128)),BUILTIN,
                                      adjustment=ColorAdjustment(brightness=12,red=-10))
                saved = convert_output(Image.new('RGB',(1,1),(128,128,128)),edited)
                assert max(abs(a-b) for a,b in zip(live.tobytes(), saved.tobytes())) <= 2
                p=QPrinter(QPrinter.PrinterMode.HighResolution)
                p.setOutputFormat(QPrinter.OutputFormat.PdfFormat)
                p.setOutputFileName(str(Path(folder)/'smoke.pdf'))
                p.setPageSize(QPageSize(QSizeF(89,127),QPageSize.Unit.Millimeter))
                p.setFullPage(True)
                paint_printer(p,page)
                assert (Path(folder)/'smoke.pdf').read_bytes().startswith(b'%PDF-')
            w.close()
            return 0
        except Exception:
            import traceback
            if sys.stderr is not None: traceback.print_exc()
            return 1
    w=Window(); w.show()
    if len(sys.argv)>1 and not sys.argv[1].startswith('--'): w.load(sys.argv[1])
    return app.exec()

if __name__=='__main__': sys.exit(main())
