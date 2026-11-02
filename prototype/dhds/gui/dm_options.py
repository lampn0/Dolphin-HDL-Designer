"""Design Manager option dialogs laid out as in the legacy tool:
File > Page Setup... (Layout, Boundaries, Misc) and Options > Verilog... (File, Style,
Headers, Default Directives, Default Packages). Settings Dolphin HDS uses are live; the
others are kept in the preferences or shown greyed."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QPlainTextEdit, QPushButton, QRadioButton, QSpinBox, QTabWidget, QVBoxLayout,
                               QWidget)

from ..model import ENCODINGS, STATE_DECLS
from ..prefs import Prefs
from .main_settings import _off

PAPER_SIZES = ['Letter (8.5" x 11")', 'Legal (8.5" x 14")', 'Tabloid (11" x 17")', 'A4 (210mm x 297mm)',
               'A3 (297mm x 420mm)', 'A2 (420mm x 594mm)', 'A1 (594mm x 841mm)', 'A0 (841mm x 1189mm)']


def _buttons(dlg: QDialog, apply: bool = False) -> QDialogButtonBox:
    flags = QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Help
    bb = QDialogButtonBox(flags | (QDialogButtonBox.Apply if apply else QDialogButtonBox.NoButton))
    bb.button(QDialogButtonBox.Help).setEnabled(False)
    return bb


class _ColorButton(QPushButton):
    def __init__(self, color: str):
        super().__init__()
        self.setFixedWidth(40)
        self.set_color(color)
        self.clicked.connect(lambda: (lambda c: c.isValid() and self.set_color(c.name()))(
            QColorDialog.getColor(QColor(self.color), self)))

    def set_color(self, color: str):
        self.color = color
        self.setStyleSheet(f'background:{color}; border:1px solid #555;')


class PageSetupDialog(QDialog):
    """Kept in the preferences (page_setup); printing is not part of Dolphin HDS yet."""

    def __init__(self, prefs: Prefs, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Page Setup')
        self.prefs = prefs
        ps = dict(prefs.page_setup)
        tabs = QTabWidget()

        # ---- Layout
        w = QWidget(); v = QVBoxLayout(w)
        box = QGroupBox('Margins'); h = QHBoxLayout(box)
        self.hmargin = QLineEdit(ps.get('hmargin', '0.69"')); self.vmargin = QLineEdit(ps.get('vmargin', '0.69"'))
        for e in (self.hmargin, self.vmargin):
            e.setFixedWidth(60)
        h.addWidget(QLabel('Horizontal:')); h.addWidget(self.hmargin); h.addSpacing(12)
        h.addWidget(QLabel('Vertical:')); h.addWidget(self.vmargin); h.addStretch(1)
        v.addWidget(box)
        box = QGroupBox('Scaling'); g = QGridLayout(box)
        self.adjust = QRadioButton('Adjust to:'); self.fit = QRadioButton('Fit to:')
        (self.fit if ps.get('fit') else self.adjust).setChecked(True)
        self.percent = QSpinBox(); self.percent.setRange(10, 400); self.percent.setValue(ps.get('percent', 100))
        self.wide = QSpinBox(); self.tall = QSpinBox()
        for s, k in ((self.wide, 'wide'), (self.tall, 'tall')):
            s.setRange(1, 99); s.setValue(ps.get(k, 1))
        g.addWidget(self.adjust, 0, 0); g.addWidget(self.percent, 0, 1); g.addWidget(QLabel('% normal size'), 0, 2, 1, 3)
        g.addWidget(self.fit, 1, 0); g.addWidget(self.wide, 1, 1); g.addWidget(QLabel('page(s) wide by'), 1, 2)
        g.addWidget(self.tall, 1, 3); g.addWidget(QLabel('tall'), 1, 4)
        self.adjust.toggled.connect(self._scaling)
        v.addWidget(box)
        row = QHBoxLayout()
        row.addWidget(QLabel('Paper size:'))
        self.paper = QComboBox(); self.paper.addItems(PAPER_SIZES)
        self.paper.setCurrentText(ps.get('paper', PAPER_SIZES[0])); row.addWidget(self.paper, 1)
        custom = QPushButton('Custom Size...'); _off(custom); row.addWidget(custom)
        v.addLayout(row)
        row = QHBoxLayout()
        box = QGroupBox('Orientation'); b = QVBoxLayout(box)
        self.orient = QButtonGroup(self)
        for k, text in enumerate(('Portrait', 'Landscape', 'Best Fit')):
            r = QRadioButton(text); self.orient.addButton(r, k); b.addWidget(r)
        self.orient.button(2).setEnabled(False)
        self.orient.button(ps.get('orientation', 1)).setChecked(True)
        row.addWidget(box)
        row.addStretch(1)
        box = QGroupBox('Panel Outline Visibility'); b = QVBoxLayout(box)
        self.panels = QButtonGroup(self)
        for k, text in enumerate(('Show All Panels', 'Show Specified Panel', 'Hide All Panels')):
            r = QRadioButton(text); self.panels.addButton(r, k); b.addWidget(r)
        self.panels.button(ps.get('panels', 2)).setChecked(True)
        row.addWidget(box)
        v.addLayout(row)
        self.headers = QCheckBox('Show Headers and Footers'); self.headers.setChecked(ps.get('headers', False))
        v.addWidget(self.headers); v.addStretch(1)
        tabs.addTab(w, 'Layout')
        self._scaling()

        # ---- Boundaries
        w = QWidget(); v = QVBoxLayout(w)
        self.checks = {}

        def checks(title, entries):
            box = QGroupBox(title); b = QVBoxLayout(box)
            for key, text in entries:
                c = QCheckBox(text); c.setChecked(ps.get(key, False)); b.addWidget(c); self.checks[key] = c
            v.addWidget(box)
            return box
        checks('Display options', [('show_boundaries', 'Show boundaries on diagram'),
                                   ('show_page_numbers', 'Show page numbers on diagram'),
                                   ('relocate_origin', 'Automatically relocate origin on update')])
        checks('Print options', [('print_boundaries', 'Show boundaries when printed'),
                                 ('index_markers', 'Add index markers when printed')])
        box = QGroupBox('Appearance'); g = QGridLayout(box)
        self.line_color = _ColorButton(ps.get('line_color', '#000000'))
        self.line_style = QComboBox(); self.line_style.addItems(['Dotted', 'Dashed', 'Solid'])
        self.line_style.setCurrentText(ps.get('line_style', 'Dotted'))
        self.line_width = QComboBox(); self.line_width.addItems(['1', '2', '3'])
        self.line_width.setCurrentText(str(ps.get('line_width', 1)))
        self.feint = QCheckBox('Use feint image for display'); self.feint.setChecked(ps.get('feint', False))
        g.addWidget(QLabel('Line Color:'), 0, 0); g.addWidget(self.line_color, 0, 1); g.addWidget(self.feint, 0, 2)
        g.addWidget(QLabel('Line Style'), 1, 0); g.addWidget(self.line_style, 1, 1)
        g.addWidget(QLabel('Line Width'), 2, 0); g.addWidget(self.line_width, 2, 1)
        g.setColumnStretch(3, 1)
        v.addWidget(box); v.addStretch(1)
        tabs.addTab(w, 'Boundaries')

        # ---- Misc
        w = QWidget(); v = QVBoxLayout(w)
        box = QGroupBox('Block Diagram Print Options'); b = QVBoxLayout(box)
        self.connectors = QCheckBox('Show page connectors when printed')
        self.connectors.setChecked(ps.get('connectors', False)); b.addWidget(self.connectors)
        row = QHBoxLayout(); row.addWidget(QLabel('Page Connector Style :'))
        self.connector_style = QComboBox(); self.connector_style.addItems(['Across Page Boundaries', 'All Connections'])
        self.connector_style.setCurrentText(ps.get('connector_style', 'Across Page Boundaries'))
        row.addWidget(self.connector_style, 1); b.addLayout(row)
        self.sub_checks = []
        for key, text in (('by_name', 'Include Connection by name page connectors'),
                          ('signal_name', 'Display signal name'),
                          ('same_elements', 'Only show attached connections of same elements')):
            c = QCheckBox(text); c.setChecked(ps.get(key, key == 'signal_name')); b.addWidget(c)
            self.checks[key] = c; self.sub_checks.append(c)
        app = QGroupBox('Appearance'); g = QGridLayout(app)
        self.connector_color = _ColorButton(ps.get('connector_color', '#0000ff'))
        self.connector_font = QLineEdit(ps.get('connector_font', 'courier Bold 8 point'))
        font_set = QPushButton('Set...'); _off(font_set)
        g.addWidget(QLabel('Color'), 0, 0); g.addWidget(self.connector_color, 0, 1, Qt.AlignLeft)
        g.addWidget(QLabel('Font'), 1, 0); g.addWidget(self.connector_font, 1, 1); g.addWidget(font_set, 1, 2)
        b.addWidget(app)
        v.addWidget(box)
        box = QGroupBox('IBD Diagram Print Options'); b = QVBoxLayout(box)
        ibd = QCheckBox('Print all ICT views'); _off(ibd); b.addWidget(ibd)
        v.addWidget(box); v.addStretch(1)
        self.connectors.toggled.connect(self._connectors)
        self._connectors(self.connectors.isChecked())
        tabs.addTab(w, 'Misc')

        bb = _buttons(self)
        bb.accepted.connect(self._ok); bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self); lay.addWidget(tabs); lay.addWidget(bb)
        self.tabs = tabs
        self.resize(620, 500)

    def _scaling(self):
        self.percent.setEnabled(self.adjust.isChecked())
        self.wide.setEnabled(self.fit.isChecked()); self.tall.setEnabled(self.fit.isChecked())

    def _connectors(self, on: bool):
        self.connector_style.setEnabled(on)
        for c in self.sub_checks:
            c.setEnabled(on)

    def values(self) -> dict:
        d = {'hmargin': self.hmargin.text(), 'vmargin': self.vmargin.text(), 'fit': self.fit.isChecked(),
             'percent': self.percent.value(), 'wide': self.wide.value(), 'tall': self.tall.value(),
             'paper': self.paper.currentText(), 'orientation': self.orient.checkedId(),
             'panels': self.panels.checkedId(), 'headers': self.headers.isChecked(),
             'line_color': self.line_color.color, 'line_style': self.line_style.currentText(),
             'line_width': int(self.line_width.currentText()), 'feint': self.feint.isChecked(),
             'connectors': self.connectors.isChecked(), 'connector_style': self.connector_style.currentText(),
             'connector_color': self.connector_color.color, 'connector_font': self.connector_font.text()}
        d.update({k: c.isChecked() for k, c in self.checks.items()})
        return d

    def _ok(self):
        self.prefs.page_setup = self.values()
        self.prefs.save()
        self.accept()


class VerilogOptionsDialog(QDialog):
    def __init__(self, prefs: Prefs, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Verilog Options')
        self.prefs = p = prefs
        tabs = QTabWidget()

        # ---- File
        w = QWidget(); v = QVBoxLayout(w)
        box = QGroupBox('File Extensions'); g = QGridLayout(box)
        self.allowed = QLineEdit(p.verilog_extensions)
        self.allowed.setToolTip('Files with these extensions are read as Verilog/SystemVerilog source')
        self.source_ext, self.generated_ext, self.sv_ext = (self._ext_combo(p.source_ext), self._ext_combo(p.generated_ext),
                                                            self._ext_combo(p.sv_ext))
        self.allowed.textChanged.connect(self._refill_exts)
        g.addWidget(QLabel('Allowed Extensions:'), 0, 0); g.addWidget(self.allowed, 0, 1, 1, 3)
        g.addWidget(QLabel('Source Verilog (default):'), 1, 0); g.addWidget(self.source_ext, 1, 1)
        g.addWidget(QLabel('Generated Verilog:'), 1, 2); g.addWidget(self.generated_ext, 1, 3)
        g.addWidget(QLabel('System Verilog (default):'), 2, 0); g.addWidget(self.sv_ext, 2, 1)
        v.addWidget(box)
        box = QGroupBox('File Naming Rules'); b = QVBoxLayout(box)
        b.addWidget(QLabel('Selecting a File Type will display the naming rule settings for that type.'))
        src = QGroupBox('Source Files'); f = QFormLayout(src)
        note = QLabel('Specify the default filename rule for source HDL files. This rule will be used when no '
                      'template specified rule is available. To include module names use the variable '
                      '%(module_name).'); note.setWordWrap(True); f.addRow(note)
        self.file_type = QComboBox(); self.file_type.addItem('Verilog Module'); f.addRow('File Type:', self.file_type)
        self.source_rule = QLineEdit(p.source_rule); f.addRow('Rule', self.source_rule)
        self.source_case = self._case_combo(p.source_case); f.addRow('Case:', self.source_case)
        b.addWidget(src)
        gen = QGroupBox('Generated Files'); f = QFormLayout(gen)
        note = QLabel('Specify the filename rule for generated HDL files. To include design unit and/or view '
                      'names use the variables %(unit) and %(view).'); note.setWordWrap(True); f.addRow(note)
        self.gen_rule = QLineEdit(p.generated_name_rule); f.addRow('Rule:', self.gen_rule)
        self.gen_case = self._case_combo('Always lower case' if p.generated_lowercase else 'Preserve case')
        self.gen_case.model().item(2).setEnabled(False)          # upper case: not offered for generated files
        f.addRow('Case:', self.gen_case)
        b.addWidget(gen)
        v.addWidget(box)
        box = QGroupBox('Default Search Path'); h = QHBoxLayout(box)
        self.search = QLineEdit(p.search_path); edit = QPushButton('Edit...')
        edit.clicked.connect(self._edit_search_path)
        h.addWidget(self.search, 1); h.addWidget(edit)
        v.addWidget(box); v.addStretch(1)
        tabs.addTab(w, 'File')

        # ---- Style: generated state machine code
        w = QWidget(); v = QVBoxLayout(w)
        box = QGroupBox('State Machines'); f = QFormLayout(box)
        self.decl = QComboBox(); self.decl.addItems(STATE_DECLS); self.decl.setCurrentText(p.default_state_decl)
        self.enc = QComboBox(); self.enc.addItems(ENCODINGS); self.enc.setCurrentText(p.default_encoding)
        f.addRow('Default state declaration:', self.decl); f.addRow('Default state encoding:', self.enc)
        v.addWidget(box)
        box = QGroupBox('Layout'); f = QFormLayout(box)
        indent = QSpinBox(); indent.setValue(3); _off(indent); f.addRow('Indentation:', indent)
        v.addWidget(box); v.addStretch(1)
        tabs.addTab(w, 'Style')

        # ---- Headers
        w = QWidget(); v = QVBoxLayout(w)
        v.addWidget(QLabel('Header written at the top of generated files:'))
        self.header = QPlainTextEdit(p.header_template)
        v.addWidget(self.header, 1)
        v.addWidget(QLabel('<small>Variables: %(library) %(unit) %(view) %(project_name) %(user) %(date) '
                           '%(time) %(year)</small>'))
        tabs.addTab(w, 'Headers')

        # ---- Default Directives / Default Packages
        for title, text in (('Default Directives', 'Compiler directives added to new Verilog files'),
                            ('Default Packages', 'Packages imported in new SystemVerilog files')):
            w = QWidget(); v = QVBoxLayout(w)
            v.addWidget(QLabel(text + ':'))
            e = QPlainTextEdit(); _off(e); v.addWidget(e, 1)
            tabs.addTab(w, title)

        bb = _buttons(self, apply=True)
        bb.accepted.connect(self._ok); bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.Apply).clicked.connect(self.apply)
        lay = QVBoxLayout(self); lay.addWidget(tabs); lay.addWidget(bb)
        self.tabs = tabs
        self.applied = False
        self.resize(660, 700)

    def _exts(self) -> list[str]:
        return [e.lstrip('.') for e in self.allowed.text().split() if e.strip('.')]

    def _ext_combo(self, value: str) -> QComboBox:
        c = QComboBox(); c.setEditable(True)
        c.addItems(self._exts()); c.setCurrentText(value)
        return c

    def _refill_exts(self):
        for c in (self.source_ext, self.generated_ext, self.sv_ext):
            cur = c.currentText(); c.blockSignals(True); c.clear(); c.addItems(self._exts())
            c.setCurrentText(cur); c.blockSignals(False)

    @staticmethod
    def _case_combo(value: str) -> QComboBox:
        c = QComboBox(); c.addItems(['Preserve case', 'Always lower case', 'Always upper case'])
        c.setCurrentText(value)
        return c

    def _edit_search_path(self):
        from PySide6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(self, 'Add to search path')
        if d:
            self.search.setText(':'.join([x for x in self.search.text().split(':') if x] + [d]))

    def validate(self) -> str:
        if '%(unit)' not in self.gen_rule.text():
            return 'The generated file rule must contain %(unit).'
        if '%(module_name)' not in self.source_rule.text() and '%(unit)' not in self.source_rule.text():
            return 'The source file rule must contain %(module_name).'
        return ''

    def apply(self) -> bool:
        err = self.validate()
        if err:
            from PySide6.QtWidgets import QMessageBox
            QMessageBox.warning(self, 'Verilog Options', err)
            return False
        p = self.prefs
        p.verilog_extensions = ' '.join(self._exts())
        p.source_ext = self.source_ext.currentText().lstrip('.') or 'v'
        p.generated_ext = self.generated_ext.currentText().lstrip('.') or 'v'
        p.sv_ext = self.sv_ext.currentText().lstrip('.') or 'sv'
        p.source_rule = self.source_rule.text().strip()
        p.source_case = self.source_case.currentText()
        p.generated_name_rule = self.gen_rule.text().strip()
        p.generated_lowercase = self.gen_case.currentText() == 'Always lower case'
        p.search_path = self.search.text().strip()
        p.default_state_decl = self.decl.currentText()
        p.default_encoding = self.enc.currentText()
        p.header_template = self.header.toPlainText()
        p.save()
        self.applied = True
        return True

    def _ok(self):
        if self.apply():
            self.accept()
