"""Indeterminate progress indicators in the application's existing colors."""
from PySide6.QtCore import Qt, QRectF, QTimer
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import QWidget, QPushButton, QLabel, QVBoxLayout


class ActivityBar(QWidget):
    def __init__(self, parent=None, light=False):
        super().__init__(parent)
        self.light = light
        self.phase = 0.
        self.setFixedHeight(4)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.timer = QTimer(self)
        self.timer.setInterval(30)
        self.timer.timeout.connect(self.advance)
        self.hide()

    def set_active(self, active):
        self.setVisible(active)
        if active:
            self.phase = 0.
            self.timer.start()
        else:
            self.timer.stop()
        self.update()

    def advance(self):
        self.phase = (self.phase + .025) % 1
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        track = QColor(255, 255, 255, 55) if self.light else QColor('#DFE7E3')
        chunk = QColor('#B9E5D4') if self.light else QColor('#18745D')
        painter.setBrush(track)
        painter.drawRoundedRect(QRectF(self.rect()), 2, 2)
        width = self.width() * .3
        x = -width + (self.width() + width) * self.phase
        painter.setBrush(chunk)
        painter.drawRoundedRect(QRectF(x, 0, width, self.height()), 2, 2)


class PrintProgressButton(QPushButton):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.idle_text = text
        self.bar = ActivityBar(self, light=True)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.bar.setGeometry(16, self.height()-8, max(0, self.width()-32), 4)

    def set_busy(self, text=None):
        active = text is not None
        changed = bool(self.property('busy')) != active
        self.setProperty('busy', active)
        self.setText(text if active else self.idle_text)
        if changed:
            self.style().unpolish(self)
            self.style().polish(self)
        if self.bar.timer.isActive() != active:
            self.bar.set_active(active)


class PhotoLoadingOverlay(QWidget):
    def __init__(self, parent):
        super().__init__(parent)
        self.card = QWidget(self)
        self.card.setObjectName('loadingCard')
        layout = QVBoxLayout(self.card)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(18)
        self.label = QLabel('正在载入照片…', self.card)
        self.label.setObjectName('loadingTitle')
        self.label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.label)
        self.bar = ActivityBar(self.card)
        layout.addWidget(self.bar)
        self.card.setFixedWidth(260)
        self.hide()

    def set_active(self, active, text='正在载入照片…'):
        self.label.setText(text)
        self.setVisible(active)
        self.bar.set_active(active)
        if active:
            self.position_card()
            self.raise_()

    def set_text(self, text):
        self.label.setText(text)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.position_card()

    def position_card(self):
        self.card.adjustSize()
        self.card.move((self.width()-self.card.width())//2, (self.height()-self.card.height())//2)

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor(232, 237, 242, 220))
