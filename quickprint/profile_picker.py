"""Styled ICC picker with an import action and removable custom entries."""
from pathlib import Path

from PySide6.QtCore import Qt, QEvent, QPoint, QRect, QSize, Signal, QTimer
from PySide6.QtGui import QColor, QIcon, QPainter, QPalette
from PySide6.QtWidgets import (QComboBox, QListView, QStyle, QStyledItemDelegate,
                               QStyleOptionComboBox, QStylePainter, QToolTip)

IMPORT_PROFILE = '__import_profile__'
CUSTOM_ROLE = Qt.ItemDataRole.UserRole + 1
DESCRIPTION_ROLE = Qt.ItemDataRole.UserRole + 2
TRAILING_TEXT_ROLE = Qt.ItemDataRole.UserRole + 10
TRAILING_COLOR_ROLE = Qt.ItemDataRole.UserRole + 11


def delete_rect(rect):
    return QRect(rect.right() - 37, rect.top(), 32, rect.height())


class ComboItemDelegate(QStyledItemDelegate):
    def __init__(self, parent, assets):
        super().__init__(parent)
        self.trash = QIcon(str(assets / 'trash.svg'))

    def sizeHint(self, option, index):
        return QSize(240, 40)

    def paint(self, painter, option, index):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        rect = option.rect.adjusted(3, 2, -3, -2)
        active = option.state & (QStyle.StateFlag.State_Selected | QStyle.StateFlag.State_MouseOver)
        if active:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor('#E5F2ED'))
            painter.drawRoundedRect(rect, 6, 6)
        importing = index.data(Qt.ItemDataRole.UserRole) == IMPORT_PROFILE
        custom = bool(index.data(CUSTOM_ROLE))
        trailing = index.data(TRAILING_TEXT_ROLE) or ''
        painter.setPen(QColor('#176B56' if active or importing else '#24333E'))
        painter.setFont(option.font)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        has_icon = isinstance(icon, QIcon) and not icon.isNull()
        if has_icon:
            icon.paint(painter, QRect(rect.left()+11, rect.center().y()-6, 12, 12))
        trailing_width = option.fontMetrics.horizontalAdvance(trailing) if trailing else 0
        right_space = 40 if custom else 12
        if trailing:
            right_space += trailing_width + 12
        text_rect = rect.adjusted(31 if has_icon else 12, 0, -right_space, 0)
        text = option.fontMetrics.elidedText(index.data(), Qt.TextElideMode.ElideRight, text_rect.width())
        painter.drawText(text_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, text)
        if trailing:
            painter.setPen(QColor(index.data(TRAILING_COLOR_ROLE) or '#73818D'))
            trailing_rect = QRect(rect.right()-trailing_width-12, rect.top(), trailing_width, rect.height())
            painter.drawText(trailing_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, trailing)
        if custom:
            target = delete_rect(option.rect)
            icon_rect = QRect(target.center().x() - 8, target.center().y() - 8, 16, 16)
            self.trash.paint(painter, icon_rect)
        painter.restore()


class StyledComboBox(QComboBox):
    """App-wide combo box whose rounded popup always opens below its field."""
    def __init__(self, assets, parent=None):
        super().__init__(parent)
        view = QListView(self)
        view.setObjectName('comboPopup')
        view.setMouseTracking(True)
        view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setView(view)
        popup = view.window()
        popup.setObjectName('comboPopupContainer')
        # Set the popup type and hints together; adding hints individually can
        # retain native title-bar flags and lose NoDropShadow on Windows.
        popup.setWindowFlags(Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint |
                             Qt.WindowType.NoDropShadowWindowHint)
        popup.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        popup.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        popup.setAutoFillBackground(False)
        palette = popup.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(0, 0, 0, 0))
        popup.setPalette(palette)
        popup.setStyleSheet('QFrame#comboPopupContainer { background-color: rgba(0,0,0,0); border: none; }')
        self.setItemDelegate(ComboItemDelegate(view, assets))
        self.setMaxVisibleItems(8)
        self._delete_pressed = None

    def showPopup(self):
        self.view().setMinimumWidth(self.width())
        super().showPopup()
        self._place_popup_below()
        # Some platform styles make one final geometry adjustment after showPopup.
        QTimer.singleShot(0, self._place_popup_below)

    def paintEvent(self, event):
        trailing = self.currentData(TRAILING_TEXT_ROLE)
        if not trailing:
            return super().paintEvent(event)
        painter = QStylePainter(self)
        option = QStyleOptionComboBox()
        self.initStyleOption(option)
        painter.drawComplexControl(QStyle.ComplexControl.CC_ComboBox, option)
        edit = self.style().subControlRect(QStyle.ComplexControl.CC_ComboBox, option,
                                           QStyle.SubControl.SC_ComboBoxEditField, self)
        width = option.fontMetrics.horizontalAdvance(trailing)
        icon_space = option.iconSize.width()+5 if not option.currentIcon.isNull() else 0
        option.currentText = option.fontMetrics.elidedText(
            self.currentText(), Qt.TextElideMode.ElideRight,
            max(10, edit.width()-width-icon_space-12))
        painter.drawControl(QStyle.ControlElement.CE_ComboBoxLabel, option)
        painter.setPen(QColor(self.currentData(TRAILING_COLOR_ROLE) or '#73818D'))
        painter.drawText(edit.adjusted(0, 0, -5, 0),
                         Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, trailing)

    def _place_popup_below(self):
        popup = self.view().window()
        if not popup.isVisible():
            return
        # The internal container reserves a transparent top inset. Offset it so
        # the visible rounded list begins exactly below the combo box.
        list_inset = self.view().geometry().top()
        anchor = self.mapToGlobal(QPoint(0, self.height()))
        popup.move(anchor.x(), anchor.y() - list_inset)


class ProfileComboBox(StyledComboBox):
    importRequested = Signal()
    removeRequested = Signal(str)

    def __init__(self, assets, parent=None):
        super().__init__(assets, parent)
        self._selected_profile = ''
        self.setObjectName('profilePicker')
        view = self.view()
        view.viewport().installEventFilter(self)
        view.installEventFilter(self)
        self.currentIndexChanged.connect(self._remember_profile)
        self.activated.connect(self._activate)

    def selected_profile(self):
        # The import row is an action, never an output profile or saved value.
        return self._selected_profile

    def _remember_profile(self, index):
        value = self.itemData(index)
        if value != IMPORT_PROFILE:
            self._selected_profile = value or ''

    def _activate(self, index):
        if self.itemData(index) == IMPORT_PROFILE:
            self.setCurrentIndex(max(0, self.findData(self._selected_profile)))
            self.importRequested.emit()

    def add_custom(self, path, description):
        index = self.findData(path)
        if index < 0:
            index = self.count() - 1
            self.insertItem(index, Path(path).stem, path)
            self.setItemData(index, True, CUSTOM_ROLE)
            self.setItemData(index, description, DESCRIPTION_ROLE)
            self.setItemData(index, f'{description}\n{path}', Qt.ItemDataRole.ToolTipRole)
            self.setItemData(index, '导入的配置；可点击右侧删除图标或按 Delete 从列表移除。', Qt.ItemDataRole.AccessibleDescriptionRole)
        return index

    def showPopup(self):
        self._delete_pressed = None
        super().showPopup()

    def eventFilter(self, obj, event):
        # Destruction and style events can arrive after the item view has begun
        # tearing down. Only access its viewport for events handled below.
        if event.type() not in (QEvent.Type.KeyPress, QEvent.Type.MouseButtonPress,
                                QEvent.Type.MouseButtonRelease, QEvent.Type.ToolTip):
            return super().eventFilter(obj,event)
        view = self.view()
        if obj is view and event.type() == QEvent.Type.KeyPress and event.key() == Qt.Key.Key_Delete:
            index = view.currentIndex()
            if index.data(CUSTOM_ROLE):
                self.removeRequested.emit(index.data(Qt.ItemDataRole.UserRole))
                return True
        if obj is view.viewport():
            if event.type() in (QEvent.Type.MouseButtonPress, QEvent.Type.MouseButtonRelease, QEvent.Type.ToolTip):
                position = event.pos() if event.type() == QEvent.Type.ToolTip else event.position().toPoint()
                index = view.indexAt(position)
                over_delete = bool(index.data(CUSTOM_ROLE)) and delete_rect(view.visualRect(index)).contains(position)
                if event.type() == QEvent.Type.ToolTip and over_delete:
                    QToolTip.showText(event.globalPos(), '从列表移除（保留原文件）', view)
                    return True
                if event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton and over_delete:
                    self._delete_pressed = index.data(Qt.ItemDataRole.UserRole)
                    return True
                if event.type() == QEvent.Type.MouseButtonRelease and self._delete_pressed is not None:
                    path, self._delete_pressed = self._delete_pressed, None
                    if over_delete and index.data(Qt.ItemDataRole.UserRole) == path:
                        self.removeRequested.emit(path)
                    return True
        return super().eventFilter(obj, event)
