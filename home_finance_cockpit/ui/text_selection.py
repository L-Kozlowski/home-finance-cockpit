"""Mouse-drag selection for display labels, without a text editing caret."""

import atexit
import weakref

from PyQt6.QtCore import QEvent, QObject, QPointF, Qt, pyqtSignal
from PyQt6.QtGui import QKeySequence, QMouseEvent
from PyQt6.QtWidgets import QApplication, QLabel


class LabelSelection(QObject):
    def __init__(self, app):
        super().__init__(app)
        self.active = None
        app.installEventFilter(self)
        self.installed = True
        app.aboutToQuit.connect(self.shutdown)
        atexit.register(self.shutdown)

    def shutdown(self):
        if not self.installed:
            return
        self.installed = False
        self.clear()
        app = QApplication.instance()
        if app is not None:
            try:
                app.removeEventFilter(self)
            except RuntimeError:
                pass

    def clear(self):
        label = self.active() if self.active else None
        self.active = None
        if label is not None:
            try:
                label.setSelection(0, 0)
            except RuntimeError:
                pass

    def eventFilter(self, watched, event):
        if (
            event.type() == QEvent.Type.MouseButtonPress
            and event.button() == Qt.MouseButton.LeftButton
        ):
            self.clear()
        elif event.type() == QEvent.Type.KeyPress and event.matches(QKeySequence.StandardKey.Copy):
            label = self.active() if self.active else None
            if label is not None:
                try:
                    text = label.selectedText()
                except RuntimeError:
                    text = ""
                if text:
                    QApplication.clipboard().setText(text)
                    return True
        return super().eventFilter(watched, event)


class DragSelectableLabel(QLabel):
    clicked = pyqtSignal()

    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        app = QApplication.instance()
        if not hasattr(app, "_label_selection"):
            app._label_selection = LabelSelection(app)
        elif not app._label_selection.installed:
            app.installEventFilter(app._label_selection)
            app._label_selection.installed = True
        self.selection_manager = app._label_selection
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._origin = None
        self._dragging = False

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.selection_manager.clear()
            self.setSelection(0, 0)
            self._origin = event.position()
            self._global_origin = event.globalPosition()
            self._dragging = False
            event.accept()
        else:
            super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        self.mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._origin is not None and event.buttons() & Qt.MouseButton.LeftButton:
            if (
                not self._dragging
                and (event.position() - self._origin).manhattanLength()
                >= QApplication.startDragDistance()
            ):
                press = QMouseEvent(
                    QEvent.Type.MouseButtonPress,
                    QPointF(self._origin),
                    QPointF(self._global_origin),
                    Qt.MouseButton.LeftButton,
                    Qt.MouseButton.LeftButton,
                    event.modifiers(),
                )
                super().mousePressEvent(press)
                self._dragging = True
                self.clearFocus()
            if self._dragging:
                super().mouseMoveEvent(event)
                self.selection_manager.active = weakref.ref(self)
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self._origin is not None:
            if self._dragging:
                super().mouseReleaseEvent(event)
                self.clearFocus()
                self.selection_manager.active = weakref.ref(self)
            else:
                self.setSelection(0, 0)
                self.clicked.emit()
            self._origin = None
            event.accept()
        else:
            super().mouseReleaseEvent(event)
