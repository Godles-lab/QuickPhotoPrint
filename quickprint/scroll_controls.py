"""Reserve the scrollbar gutter without painting a handle when nothing can scroll."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QScrollBar


class OverflowScrollBar(QScrollBar):
    def __init__(self, parent=None):
        super().__init__(Qt.Orientation.Vertical, parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.rangeChanged.connect(lambda minimum, maximum: self.update())

    def paintEvent(self, event):
        if self.maximum() > self.minimum():
            super().paintEvent(event)
