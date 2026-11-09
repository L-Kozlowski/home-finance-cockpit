"""Lazy display of structured import diagnostics, including large bank exports."""

from PyQt6.QtCore import QAbstractTableModel, QModelIndex, Qt

from home_finance_cockpit.localization import tr


class ImportIssuesModel(QAbstractTableModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows = []

    def set_rows(self, rows):
        self.beginResetModel()
        self.rows = list(rows)
        self.endResetModel()

    def rowCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else len(self.rows)

    def columnCount(self, parent=QModelIndex()):
        return 0 if parent.isValid() else 3

    def data(self, index, role=Qt.ItemDataRole.DisplayRole):
        if not index.isValid() or not 0 <= index.row() < len(self.rows):
            return None
        if role in (Qt.ItemDataRole.DisplayRole, Qt.ItemDataRole.ToolTipRole):
            value = self.rows[index.row()][index.column()]
            return "—" if value is None or value == "" else str(value)
        if role == Qt.ItemDataRole.TextAlignmentRole:
            return Qt.AlignmentFlag.AlignVCenter | (
                Qt.AlignmentFlag.AlignCenter if index.column() == 1 else Qt.AlignmentFlag.AlignLeft
            )
        return None

    def headerData(self, section, orientation, role=Qt.ItemDataRole.DisplayRole):
        if (
            orientation == Qt.Orientation.Horizontal
            and role == Qt.ItemDataRole.DisplayRole
            and 0 <= section < 3
        ):
            return (tr("Plik"), tr("Wiersz"), tr("Informacja"))[section]
        return None
