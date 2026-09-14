from __future__ import annotations

from PyQt5 import QtCore


class GenericTableModel(QtCore.QAbstractTableModel):
    def __init__(self, headers: list[str], rows: list[list[str]] | None = None, parent=None):
        super().__init__(parent)
        self._headers = list(headers)
        self._rows = [list(row) for row in (rows or [])]

    def rowCount(self, parent=QtCore.QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._rows)

    def columnCount(self, parent=QtCore.QModelIndex()) -> int:
        if parent.isValid():
            return 0
        return len(self._headers)

    def data(self, index, role=QtCore.Qt.DisplayRole):
        if not index.isValid():
            return None

        value = self._rows[index.row()][index.column()]
        if role in (QtCore.Qt.DisplayRole, QtCore.Qt.ToolTipRole):
            return value
        if role == QtCore.Qt.TextAlignmentRole and index.column() in self.centered_columns():
            return int(QtCore.Qt.AlignCenter)
        return None

    def headerData(self, section, orientation, role=QtCore.Qt.DisplayRole):
        if role != QtCore.Qt.DisplayRole:
            return None
        if orientation == QtCore.Qt.Horizontal:
            return self._headers[section]
        return str(section + 1)

    def sort(self, column: int, order: QtCore.Qt.SortOrder = QtCore.Qt.AscendingOrder) -> None:
        reverse = order == QtCore.Qt.DescendingOrder
        self.layoutAboutToBeChanged.emit()
        self._rows.sort(key=lambda row: self._sort_key(row[column]), reverse=reverse)
        self.layoutChanged.emit()

    def set_rows(self, rows: list[list[str]]) -> None:
        self.beginResetModel()
        self._rows = [list(row) for row in rows]
        self.endResetModel()

    def row_values(self, row_index: int) -> list[str]:
        return list(self._rows[row_index])

    def all_rows(self) -> list[list[str]]:
        return [list(row) for row in self._rows]

    def headers(self) -> list[str]:
        return list(self._headers)

    def centered_columns(self) -> set[int]:
        return set()

    @staticmethod
    def _sort_key(value: str):
        texto = str(value).strip()
        if texto.isdigit():
            return 0, int(texto)
        return 1, texto.casefold()


class HistoricoTableModel(GenericTableModel):
    def centered_columns(self) -> set[int]:
        return {0, 1, 3, 4, 6, 7, 9, 10, 12, 13, 14}


class TextFilterProxyModel(QtCore.QSortFilterProxyModel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._filter_text = ""
        self._filter_columns: list[int] = []
        self.setDynamicSortFilter(True)
        self.setFilterCaseSensitivity(QtCore.Qt.CaseInsensitive)

    def set_filter_text(self, text: str) -> None:
        self._filter_text = (text or "").strip().casefold()
        self.invalidateFilter()

    def set_filter_columns(self, columns: list[int]) -> None:
        self._filter_columns = list(columns)
        self.invalidateFilter()

    def filterAcceptsRow(self, source_row: int, source_parent: QtCore.QModelIndex) -> bool:
        if not self._filter_text:
            return True

        model = self.sourceModel()
        if model is None:
            return True

        columns = self._filter_columns or list(range(model.columnCount()))
        for column in columns:
            index = model.index(source_row, column, source_parent)
            value = model.data(index, QtCore.Qt.DisplayRole)
            if self._filter_text in str(value or "").casefold():
                return True
        return False
