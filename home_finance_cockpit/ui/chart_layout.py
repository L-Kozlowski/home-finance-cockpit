"""Resizable filter and chart areas shared by analytical tabs."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QScrollArea, QSplitter, QVBoxLayout, QWidget

from home_finance_cockpit.localization import tr
from home_finance_cockpit.ui.scaling import px


class ResizableChartGrid(QWidget):
    """Rows and columns separated by draggable handles; sizes survive redraws."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.outer = QVBoxLayout(self)
        self.outer.setContentsMargins(0, 0, 0, 0)
        self.frames, self.rows, self.shape = [], [], None
        self.splitter = None

    def arrange(self, frames, columns=2, weights=None):
        shape = (tuple(id(frame) for frame in frames), columns)
        if shape == self.shape:
            return
        for frame in self.frames:
            frame.hide()
            frame.setParent(self)
        if self.splitter is not None:
            self.outer.removeWidget(self.splitter)
            self.splitter.deleteLater()
        self.frames, self.rows, self.shape = list(frames), [], shape
        self.splitter = QSplitter(Qt.Orientation.Vertical)
        self.splitter.setChildrenCollapsible(False)
        self.splitter.setHandleWidth(px(8))
        self.splitter.setToolTip(tr("Przeciągnij podział, aby zmienić wysokość wykresów"))
        self.outer.addWidget(self.splitter)
        for start in range(0, len(frames), columns):
            row = QSplitter(Qt.Orientation.Horizontal)
            row.setChildrenCollapsible(False)
            row.setHandleWidth(px(8))
            row.setToolTip(tr("Przeciągnij podział, aby zmienić szerokość wykresów"))
            for frame in frames[start : start + columns]:
                frame.setMinimumWidth(0)
                row.addWidget(frame)
                frame.show()
            row.setSizes([value * 300 for value in (weights or [1] * columns)])
            self.splitter.addWidget(row)
            self.rows.append(row)
        self.splitter.setSizes([300] * len(self.rows))


def chart_splitter(parent, outer_layout):
    splitter = QSplitter(Qt.Orientation.Vertical, parent)
    splitter.setHandleWidth(px(6))
    splitter.setToolTip(tr("Przeciągnij podział, aby zmienić wysokość filtrów i wykresów"))
    top = QScrollArea()
    top.setWidgetResizable(True)
    top.setMinimumHeight(0)
    content = QWidget()
    controls = QVBoxLayout(content)
    controls.setContentsMargins(0, 0, 4, 4)
    controls.setSpacing(px(8))
    top.setWidget(content)
    splitter.addWidget(top)
    splitter.setStretchFactor(0, 0)
    outer_layout.addWidget(splitter)
    return splitter, controls


def add_chart_area(splitter, widget, initial_height):
    splitter.addWidget(widget)
    splitter.setCollapsible(1, False)
    splitter.setStretchFactor(1, 1)
    controls = splitter.widget(0)
    controls.widget().layout().activate()
    # Account for the current toolbar and font metrics instead of clipping to an old fixed height.
    controls_height = (
        controls.widget().minimumSizeHint().height() + 2 * controls.frameWidth() + px(4)
    )
    splitter.setSizes([max(px(initial_height), controls_height), px(700)])
