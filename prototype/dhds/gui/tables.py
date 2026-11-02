"""Signals Table and Parameters Table editors."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (QComboBox, QHBoxLayout, QHeaderView, QPushButton,
                               QStyledItemDelegate, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from ..model import CATEGORIES, MODES, SCHEMES, Parameter, Signal as Sig

MONO = QFont('Courier New', 9)


class ComboDelegate(QStyledItemDelegate):
    def __init__(self, choices, parent=None):
        super().__init__(parent)
        self.choices = choices

    def createEditor(self, parent, option, index):
        cb = QComboBox(parent)
        cb.addItems(self.choices)
        return cb

    def setEditorData(self, editor, index):
        editor.setCurrentText(index.data() or '')

    def setModelData(self, editor, model, index):
        model.setData(index, editor.currentText())


class _ListTable(QWidget):
    """Table bound to a list of dataclass rows."""
    changed = Signal()
    COLUMNS: list[tuple[str, str]] = []      # (header, attribute)
    COMBOS: dict[str, tuple] = {}
    ROW_TYPE = None

    def __init__(self, parent=None):
        super().__init__(parent)
        self.rows: list = []
        self.table = QTableWidget(0, len(self.COLUMNS))
        self.table.setHorizontalHeaderLabels([h for h, _ in self.COLUMNS])
        self.table.setFont(MONO)
        self.table.verticalHeader().setDefaultSectionSize(20)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setAlternatingRowColors(True)
        self.table.setSortingEnabled(False)
        for col, (_, attr) in enumerate(self.COLUMNS):
            if attr in self.COMBOS:
                self.table.setItemDelegateForColumn(col, ComboDelegate(self.COMBOS[attr], self.table))
        self.table.itemChanged.connect(self._item_changed)
        add = QPushButton('Add row')
        rem = QPushButton('Delete selected rows')
        add.clicked.connect(self.add_row)
        rem.clicked.connect(self.remove_rows)
        btns = QHBoxLayout()
        btns.addWidget(add)
        btns.addWidget(rem)
        btns.addStretch(1)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.table)
        lay.addLayout(btns)
        self._loading = False

    def set_rows(self, rows: list):
        self.rows = rows
        self._loading = True
        self.table.setRowCount(0)
        for r in rows:
            self._append(r)
        self.table.resizeColumnsToContents()
        self._loading = False

    def _append(self, row):
        i = self.table.rowCount()
        self.table.insertRow(i)
        for col, (_, attr) in enumerate(self.COLUMNS):
            val = getattr(row, attr)
            item = QTableWidgetItem('yes' if val is True else '' if val is False else str(val))
            self.style_cell(row, attr, item)
            self.table.setItem(i, col, item)

    def style_cell(self, row, attr, item):
        pass

    def _item_changed(self, item: QTableWidgetItem):
        if self._loading:
            return
        row = self.rows[item.row()]
        attr = self.COLUMNS[item.column()][1]
        cur = getattr(row, attr)
        text = item.text().strip()
        setattr(row, attr, text.lower() in ('yes', 'true', '1') if isinstance(cur, bool) else text)
        self._loading = True
        for col, (_, a) in enumerate(self.COLUMNS):
            self.style_cell(row, a, self.table.item(item.row(), col))
        self._loading = False
        self.changed.emit()

    def add_row(self):
        row = self.new_row()
        self.rows.append(row)
        self._loading = True
        self._append(row)
        self._loading = False
        self.table.scrollToBottom()
        self.changed.emit()

    def remove_rows(self):
        idx = sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True)
        for i in idx:
            del self.rows[i]
            self.table.removeRow(i)
        if idx:
            self.changed.emit()

    def new_row(self):
        raise NotImplementedError


class SignalsTable(_ListTable):
    COLUMNS = [('Group', 'group'), ('Name', 'name'), ('Mode', 'mode'), ('Type', 'type'),
               ('Signed', 'signed'), ('Bounds', 'bounds'), ('Category', 'category'),
               ('Expression', 'expression'), ('Scheme', 'scheme'), ('Default', 'default'),
               ('Reset', 'reset'), ('Comment', 'comment')]
    COMBOS = {'mode': MODES, 'scheme': SCHEMES, 'category': CATEGORIES, 'signed': ('', 'yes'),
              'type': ('wire', 'reg', 'logic')}

    def new_row(self):
        names = {r.name for r in self.rows}
        i = len(self.rows)
        while f'sig{i}' in names:
            i += 1
        return Sig(name=f'sig{i}', mode='output', type='reg', scheme='comb', default="1'b0")

    def style_cell(self, row: Sig, attr, item):
        if item is None:
            return
        readonly = (attr in ('scheme', 'default', 'reset') and row.mode in ('input', 'inout')) or \
                   (attr == 'expression' and row.category == 'data')
        item.setBackground(QColor(225, 225, 225) if readonly else QColor(255, 255, 255))


class ParametersTable(_ListTable):
    COLUMNS = [('Group', 'group'), ('Name', 'name'), ('Value', 'value'), ('Comment', 'comment')]

    def new_row(self):
        return Parameter(name=f'PARAM{len(self.rows)}', value='0')
