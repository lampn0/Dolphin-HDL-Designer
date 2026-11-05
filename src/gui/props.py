"""Properties panel of the state diagram editor: a dock that edits the selected object.

One page per object kind (state, transition, junction, link, point) in a QStackedWidget.
show_object() loads the object's values into the page (with `_loading` set, so the edit
signals do not write them back); every edit then goes straight into the model object through
_save() and is announced with the `changed` signal, which the editor uses to redraw the item
and record an undo step.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QComboBox, QFormLayout, QLabel, QLineEdit, QPlainTextEdit,
                               QSpinBox, QStackedWidget, QVBoxLayout, QWidget)

from model import Junction, Link, Point, State, Transition

MONO = QFont('Courier New', 9)


def _text_edit(h=70) -> QPlainTextEdit:
    """A monospaced multi-line editor for action / condition text (Tab moves the focus, no wrap)."""
    e = QPlainTextEdit()
    e.setFont(MONO)
    e.setMinimumHeight(h)
    e.setTabChangesFocus(True)
    e.setLineWrapMode(QPlainTextEdit.NoWrap)
    return e


class PropertiesPanel(QWidget):
    """The properties dock (see the module docstring). `changed(obj)` is emitted after each edit."""
    changed = Signal(object)          # the edited model object

    def __init__(self, parent=None):
        """Build the pages and connect each field to _save()."""
        super().__init__(parent)
        self.obj = None
        self._loading = False
        self.stack = QStackedWidget()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        self.title = QLabel('<b>No selection</b>')
        lay.addWidget(self.title)
        lay.addWidget(self.stack)
        lay.addStretch(1)

        self.empty = QLabel('Select a state, transition, junction or link\non the diagram to edit it.')
        self.stack.addWidget(self.empty)

        # state
        w = QWidget(); f = QFormLayout(w)
        self.st_name = QLineEdit(); self.st_enc = QLineEdit()
        self.st_entry, self.st_in, self.st_exit = _text_edit(), _text_edit(), _text_edit()
        f.addRow('Name', self.st_name)
        f.addRow('Encoding (manual)', self.st_enc)
        f.addRow('Entry actions', self.st_entry)
        f.addRow('In actions', self.st_in)
        f.addRow('Exit actions', self.st_exit)
        self.page_state = w; self.stack.addWidget(w)
        for e in (self.st_name, self.st_enc):
            e.textEdited.connect(self._save)
        for e in (self.st_entry, self.st_in, self.st_exit):
            e.textChanged.connect(self._save)

        # transition
        w = QWidget(); f = QFormLayout(w)
        self.tr_cond = _text_edit(50); self.tr_act = _text_edit(110)
        self.tr_prio = QSpinBox(); self.tr_prio.setRange(1, 99)
        self.tr_info = QLabel()
        f.addRow('From → To', self.tr_info)
        f.addRow('Condition', self.tr_cond)
        f.addRow('Actions', self.tr_act)
        f.addRow('Priority', self.tr_prio)
        f.addRow(QLabel('<small>Empty condition = always / "others" (case default).<br>'
                        'Use <tt>&lt;=</tt> for clocked signals, <tt>=</tt> for combinatorial.</small>'))
        self.page_tr = w; self.stack.addWidget(w)
        self.tr_cond.textChanged.connect(self._save)
        self.tr_act.textChanged.connect(self._save)
        self.tr_prio.valueChanged.connect(self._save)

        # junction
        w = QWidget(); f = QFormLayout(w)
        self.j_kind = QComboBox(); self.j_kind.addItems(['if', 'case'])
        self.j_expr = QLineEdit(); self.j_expr.setFont(MONO)
        f.addRow('Kind', self.j_kind)
        f.addRow('Case expression', self.j_expr)
        self.page_j = w; self.stack.addWidget(w)
        self.j_kind.currentTextChanged.connect(self._save)
        self.j_expr.textEdited.connect(self._save)

        # link
        w = QWidget(); f = QFormLayout(w)
        self.l_target = QComboBox(); self.l_target.setEditable(True)
        f.addRow('Target state', self.l_target)
        self.page_l = w; self.stack.addWidget(w)
        self.l_target.currentTextChanged.connect(self._save)

        # point
        w = QWidget(); f = QFormLayout(w)
        self.p_info = QLabel(); self.p_info.setWordWrap(True)
        f.addRow(self.p_info)
        self.page_p = w; self.stack.addWidget(w)

    def show_object(self, obj, machine=None):
        """Show `obj` (a State, Transition, Junction, Link, Point or None) on its page. `machine` is
        needed to name the ends of a transition and to list the states a link can target.
        """
        self._loading = True
        self.obj = obj
        if isinstance(obj, State):
            self.title.setText(f'<b>State</b> {obj.name}')
            self.st_name.setText(obj.name); self.st_enc.setText(obj.encoding)
            self.st_entry.setPlainText(obj.entry_actions)
            self.st_in.setPlainText(obj.in_actions)
            self.st_exit.setPlainText(obj.exit_actions)
            self.stack.setCurrentWidget(self.page_state)
        elif isinstance(obj, Transition):
            self.title.setText('<b>Transition</b>')
            src = machine.node(obj.src) if machine else None
            dst = machine.node(obj.dst) if machine else None
            self.tr_info.setText(f'{_node_name(src)} → {_node_name(dst)}')
            self.tr_cond.setPlainText(obj.cond); self.tr_act.setPlainText(obj.actions)
            self.tr_prio.setValue(obj.priority)
            self.stack.setCurrentWidget(self.page_tr)
        elif isinstance(obj, Junction):
            self.title.setText('<b>Junction</b>')
            self.j_kind.setCurrentText(obj.kind); self.j_expr.setText(obj.expr)
            self.stack.setCurrentWidget(self.page_j)
        elif isinstance(obj, Link):
            self.title.setText('<b>Link</b>')
            self.l_target.clear()
            self.l_target.addItems([s.name for s in machine.states] if machine else [])
            self.l_target.setCurrentText(obj.target)
            self.stack.setCurrentWidget(self.page_l)
        elif isinstance(obj, Point):
            self.title.setText(f'<b>{obj.kind.capitalize()} point</b>')
            help_ = {
                'reset': 'Draw a transition from this point to the reset state. The reset signal and '
                         'condition come from the Signals table (Category = reset).',
                'clock': 'The clock edge comes from the Signals table (Category = clock, Expression = posedge clk).',
                'interrupt': 'Transitions from an interrupt point apply to every state and have the highest '
                             'priority. Put the interrupt condition on the transition.',
                'recovery': 'Draw a transition to the state used when the state register holds an invalid '
                            'value (the case default branch). Its actions become the default actions.',
                'enable': 'Enable point (not generated yet).',
            }[obj.kind]
            self.p_info.setText(help_)
            self.stack.setCurrentWidget(self.page_p)
        else:
            self.title.setText('<b>No selection</b>')
            self.stack.setCurrentWidget(self.empty)
        self._loading = False

    def focus_main_field(self):
        """F2: put the cursor in the main text of the shown object."""
        w = {id(self.page_state): self.st_name, id(self.page_tr): self.tr_cond,
             id(self.page_j): self.j_expr}.get(id(self.stack.currentWidget()))
        if w is not None:
            w.setFocus()
            if hasattr(w, 'selectAll'):
                w.selectAll()

    def _save(self, *args):
        """Copy the fields of the current page into the model object and emit `changed`."""
        if self._loading or self.obj is None:
            return
        o = self.obj
        if isinstance(o, State):
            o.name = self.st_name.text().strip()
            o.encoding = self.st_enc.text().strip()
            o.entry_actions = self.st_entry.toPlainText()
            o.in_actions = self.st_in.toPlainText()
            o.exit_actions = self.st_exit.toPlainText()
        elif isinstance(o, Transition):
            o.cond = self.tr_cond.toPlainText().strip()
            o.actions = self.tr_act.toPlainText()
            o.priority = self.tr_prio.value()
        elif isinstance(o, Junction):
            o.kind = self.j_kind.currentText(); o.expr = self.j_expr.text().strip()
        elif isinstance(o, Link):
            o.target = self.l_target.currentText().strip()
        self.changed.emit(o)


def _node_name(n) -> str:
    """How a transition end is named in the panel ("ST_IDLE", "link X", "if junction", ...)."""
    if isinstance(n, State):
        return n.name
    if isinstance(n, Link):
        return f'link {n.target}'
    if isinstance(n, Junction):
        return f'{n.kind} junction'
    if isinstance(n, Point):
        return f'{n.kind} point'
    return '?'
