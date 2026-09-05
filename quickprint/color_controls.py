"""Five relative ICC controls for printing and export; no image processing on change."""
from dataclasses import asdict

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QWidget, QFormLayout, QHBoxLayout, QLabel, QSlider, QSpinBox, QPushButton

from icc_edit import ColorAdjustment


class SignedSpinBox(QSpinBox):
    def textFromValue(self, value):
        return f'+{value}' if value > 0 else str(value)


class ColorControls(QWidget):
    changed = Signal()
    saveRequested = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        form = QFormLayout(self)
        form.setContentsMargins(0, 2, 0, 2)
        form.setSpacing(9)
        note = QLabel('微调为打印后的颜色配置')
        note.setObjectName('muted')
        note.setWordWrap(True)
        form.addRow(note)
        self.sliders, self.values = {}, {}
        for key, title in [('brightness', '亮度'), ('contrast', '对比度'),
                           ('red', '红色'), ('green', '绿色'), ('blue', '蓝色')]:
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(-50, 50)
            slider.setAccessibleName(title+'微调')
            slider.setMinimumWidth(90)
            number = SignedSpinBox()
            number.setRange(-50, 50)
            number.setFixedWidth(64)
            number.setKeyboardTracking(False)
            number.setAccessibleName(title+'微调数值')
            slider.valueChanged.connect(number.setValue)
            number.valueChanged.connect(slider.setValue)
            slider.valueChanged.connect(lambda value: self.changed.emit())
            row = QHBoxLayout()
            row.setSpacing(9)
            row.addWidget(slider, 1)
            row.addWidget(number)
            form.addRow(title, row)
            self.sliders[key], self.values[key] = slider, number
        row = QHBoxLayout()
        self.reset_button = QPushButton('重置微调')
        self.reset_button.clicked.connect(lambda: self.set_adjustment(ColorAdjustment()))
        self.save_button = QPushButton('另存为 ICC…')
        self.save_button.clicked.connect(lambda checked=False: self.saveRequested.emit())
        row.addWidget(self.reset_button)
        row.addWidget(self.save_button)
        form.addRow(row)

    def adjustment(self):
        return ColorAdjustment(**{key: slider.value() for key, slider in self.sliders.items()})

    def set_adjustment(self, adjustment):
        changed = adjustment != self.adjustment()
        for key, value in asdict(adjustment).items():
            for control in (self.sliders[key], self.values[key]):
                control.blockSignals(True)
                control.setValue(value)
                control.blockSignals(False)
        if changed:
            self.changed.emit()
