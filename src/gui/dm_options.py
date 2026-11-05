"""Design Manager option dialogs laid out as in the legacy tool:
File > Page Setup... (Layout, Boundaries, Misc) and Options > Verilog... (File, Style,
Headers, Default Directives, Default Packages). Settings HDL Studio uses are live; the
others are kept in the preferences or shown greyed."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog, QComboBox, QDialog, QDialogButtonBox,
                               QFormLayout, QFrame, QGridLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QPlainTextEdit, QPushButton, QRadioButton, QSpinBox, QTabWidget,
                               QVBoxLayout, QWidget)

from prefs import Prefs
from .main_settings import _off

HEADER_TYPES = ['Block Diagram', 'Embedded Constraints', 'Flow Chart', 'State Diagram', 'Test Bench',
                'Truth Table']
PAPER_SIZES = ['Letter (8.5" x 11")', 'Legal (8.5" x 14")', 'Tabloid (11" x 17")', 'A4 (210mm x 297mm)',
               'A3 (297mm x 420mm)', 'A2 (420mm x 594mm)', 'A1 (594mm x 841mm)', 'A0 (841mm x 1189mm)']


def _buttons(dlg: QDialog, apply: bool = False) -> QDialogButtonBox:
    """OK / Cancel / Help (and Apply when asked) buttons; Help is disabled (no help pages yet)."""
    flags = QDialogButtonBox.Ok | QDialogButtonBox.Cancel | QDialogButtonBox.Help
    bb = QDialogButtonBox(flags | (QDialogButtonBox.Apply if apply else QDialogButtonBox.NoButton))
    bb.button(QDialogButtonBox.Help).setEnabled(False)
    return bb


class _ColorButton(QPushButton):
    """A button showing a colour; a click opens the colour chooser."""
    def __init__(self, color: str):
        """Start with `color` ('#rrggbb')."""
        super().__init__()
        self.setFixedWidth(40)
        self.set_color(color)
        self.clicked.connect(lambda: (lambda c: c.isValid() and self.set_color(c.name()))(
            QColorDialog.getColor(QColor(self.color), self)))

    def set_color(self, color: str):
        """Show and remember a new colour."""
        self.color = color
        self.setStyleSheet(f'background:{color}; border:1px solid #555;')


class PageSetupDialog(QDialog):
    """Kept in the preferences (page_setup); printing is not part of HDL Studio yet."""

    def __init__(self, prefs: Prefs, parent=None):
        """Build the Layout, Boundaries and Misc tabs from prefs.page_setup."""
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
            """A group box of check boxes (key, text) on the Boundaries tab; the boxes are kept in self.checks."""
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
        """Enable the scaling fields of the chosen scaling mode (percent, or pages wide x tall)."""
        self.percent.setEnabled(self.adjust.isChecked())
        self.wide.setEnabled(self.fit.isChecked()); self.tall.setEnabled(self.fit.isChecked())

    def _connectors(self, on: bool):
        """Enable the connector options only while connectors are switched on."""
        self.connector_style.setEnabled(on)
        for c in self.sub_checks:
            c.setEnabled(on)

    def values(self) -> dict:
        """Every field of the dialog as a dict (what prefs.page_setup stores)."""
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
        """Store the values in the preferences and close."""
        self.prefs.page_setup = self.values()
        self.prefs.save()
        self.accept()


class VerilogOptionsDialog(QDialog):
    """Options > Verilog...: File (extensions, naming rules, search path), Style (indentation and
    the Verilog 2005 generation choices; tab width, parameter mapping and @* are used when
    generating), Headers (one template per view type), Default Directives and Default Packages.
    `applied` tells the caller that the preferences were written.
    """
    def __init__(self, prefs: Prefs, parent=None, project=None):
        """Build the tabs from `prefs`. `project` lists the libraries on the Default Packages tab. The
        small helpers below (chk, edit, radios, ...) create a Style widget and register it in
        self.style_widgets under its preference key, so style_values() can read them all back.
        """
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

        # ---- Style (kept in prefs.verilog_style; Tab Width is used when generating)
        st = dict(p.verilog_style)
        self.style_widgets: dict = {}

        def chk(key, text, default=False):
            """A Style check box for preference `key`."""
            c = QCheckBox(text); c.setChecked(st.get(key, default)); self.style_widgets[key] = c
            return c

        def edit(key, default, width=60):
            """A short Style line edit for preference `key`."""
            e = QLineEdit(str(st.get(key, default))); e.setFixedWidth(width); self.style_widgets[key] = e
            return e

        def radios(key, texts, default):
            """Radio buttons for preference `key` (one QButtonGroup); the saved text is checked."""
            group = QButtonGroup(self); self.style_widgets[key] = group
            buttons = [QRadioButton(t) for t in texts]
            for b in buttons:
                group.addButton(b); b.setChecked(b.text() == st.get(key, default))
            return buttons

        def vline():
            """A vertical separator line."""
            f = QFrame(); f.setFrameShape(QFrame.VLine); f.setFrameShadow(QFrame.Sunken)
            return f

        w = QWidget(); v = QVBoxLayout(w)
        box = QGroupBox('Style Options'); h = QHBoxLayout(box)
        left = QGridLayout()
        self.tab_width = QSpinBox(); self.tab_width.setRange(1, 8); self.tab_width.setValue(st.get('tab_width', 2))
        self.tab_width.setToolTip('Tab width of Verilog text views (DesignPad)')
        left.addWidget(QLabel('Tab Width (spaces):'), 0, 0); left.addWidget(self.tab_width, 0, 1, Qt.AlignLeft)
        left.addWidget(chk('begin_else_lines', 'Generate "begin" and "else" keyword\nseparate lines'), 1, 0, 1, 3)
        blank = chk('blank_lines', 'Add blank lines around comments:')
        left.addWidget(blank, 2, 0, 1, 3)
        row = QHBoxLayout(); before, after = edit('blank_before', 1, 30), edit('blank_after', 1, 30)
        row.addWidget(QLabel('Before:')); row.addWidget(before); row.addWidget(QLabel('After:')); row.addWidget(after)
        row.addStretch(1); left.addLayout(row, 3, 0, 1, 3)
        left.setRowStretch(4, 1)
        h.addLayout(left, 1); h.addWidget(vline())
        right = QVBoxLayout()
        label = chk('block_label', 'Add a label for always/initial blocks'); right.addWidget(label)
        grid = QGridLayout(); grid.setContentsMargins(16, 0, 0, 0)
        use_prefix, prefix = chk('use_prefix', 'Use prefix for block label'), edit('label_prefix', '', 120)
        use_suffix, suffix = chk('use_suffix', 'Use suffix for block label'), edit('label_suffix', 'PROC', 120)
        grid.addWidget(use_prefix, 0, 0); grid.addWidget(prefix, 0, 1)
        grid.addWidget(use_suffix, 1, 0); grid.addWidget(suffix, 1, 1)
        right.addLayout(grid)
        case_label = QLabel('Case of block label:'); right.addWidget(case_label)
        row = QHBoxLayout(); row.setContentsMargins(16, 0, 0, 0)
        case = radios('label_case', ['Uppercase', 'Lowercase'], 'Lowercase')
        for b in case:
            row.addWidget(b)
        row.addStretch(1); right.addLayout(row); right.addStretch(1)
        h.addLayout(right, 1)
        v.addWidget(box)
        row = QHBoxLayout(); row.addStretch(1)
        row.addWidget(chk('include_properties', 'Include associated properties in generated Verilog'))
        v.addLayout(row)

        mid = QHBoxLayout()
        box = QGroupBox('ModuleWare Generation'); g = QGridLayout(box)
        blocking, nonblocking = radios('mw_assignment', ['Blocking Assignment', 'Non-Blocking Assignment'],
                                       'Blocking Assignment')
        b_delay, nb_delay = edit('mw_blocking_delay', 0, 50), edit('mw_nonblocking_delay', '', 50)
        nb_label = QLabel('Non-Blocking delay')
        g.addWidget(blocking, 0, 0); g.addWidget(b_delay, 0, 1)
        g.addWidget(nonblocking, 1, 0, 1, 2)
        g.addWidget(nb_label, 2, 0, Qt.AlignRight); g.addWidget(nb_delay, 2, 1)
        g.addWidget(QLabel('Signal Name Prefix:'), 3, 0, Qt.AlignRight); g.addWidget(edit('mw_prefix', 'mw_', 60), 3, 1)
        g.addWidget(chk('mw_pragmas', 'Use Pragmas when needed'), 4, 0, 1, 2)
        g.setRowStretch(5, 1)
        mid.addWidget(box, 1)
        col = QVBoxLayout()
        box = QGroupBox('Test Bench Generation'); b = QVBoxLayout(box)
        b.addWidget(QLabel('Specify default settings for test bench generation'))
        row = QHBoxLayout(); row.addWidget(QLabel('Test Bench View Name (graphical):'))
        row.addWidget(edit('tb_view', 'struct', 100)); row.addStretch(1); b.addLayout(row)
        col.addWidget(box)
        box = QGroupBox('Parameters'); b = QVBoxLayout(box)
        b.addWidget(chk('init_symbol_params', 'Initialize the symbol parameters on instances to default values'))
        b.addWidget(chk('template_pragma', 'Add template pragma above parameter declarations.'))
        col.addWidget(box)
        mid.addLayout(col, 1)
        v.addLayout(mid)

        box = QGroupBox('Verilog 2005 Generation'); h = QHBoxLayout(box)
        left = QVBoxLayout()

        def radio_row(layout, key, texts, default, indent=16):
            """A row of radio buttons (see radios), indented by `indent` pixels."""
            r = QHBoxLayout(); r.setContentsMargins(indent, 0, 0, 0)
            buttons = radios(key, texts, default)
            for x in buttons:
                r.addWidget(x)
            r.addStretch(1); layout.addLayout(r)
            return buttons
        left.addWidget(QLabel('Module Ports Declaration:'))
        ansi, _ = radio_row(left, 'ports_decl', ['ANSI-C', 'List'], 'ANSI-C')
        net_label = QLabel('Net/Variable Type:'); net_label.setContentsMargins(16, 0, 0, 0); left.addWidget(net_label)
        net = radio_row(left, 'net_type', ['Combined', 'Separate'], 'Combined', 32)
        left.addWidget(QLabel('Module Parameters Declaration:'))
        radio_row(left, 'params_decl', ['ANSI-C', 'List'], 'ANSI-C')
        h.addLayout(left, 1); h.addWidget(vline())
        right = QVBoxLayout()
        right.addWidget(QLabel('Instance Parameters Mapping:'))
        radio_row(right, 'param_mapping', ['Positional', 'Named'], 'Named')
        right.addWidget(QLabel('Sensitivity List:'))
        radio_row(right, 'sensitivity', ['Comma Separator', 'OR Separator'], 'Comma Separator')
        right.addWidget(chk('implicit_event', 'Allow implicit event expression (@*) when appropriate'))
        right.addStretch(1)
        h.addLayout(right, 1)
        v.addWidget(box)
        row = QHBoxLayout(); pragma = QPushButton('Pragma Setup...')
        self.pragma = dict(p.pragma); pragma.clicked.connect(self._pragma_setup)
        row.addWidget(pragma); row.addStretch(1); v.addLayout(row)
        v.addStretch(1)
        tabs.addTab(w, 'Style')

        def follow(src, targets, invert=False):
            """Enable targets while src is checked (unchecked with invert), as the legacy dialog does."""
            def upd(*_):
                """Apply the enabled state of the targets now."""
                for t in targets:
                    t.setEnabled(src.isChecked() != invert)
            src.toggled.connect(upd); upd()
        follow(blank, [before, after])

        def upd_label(*_):
            """Enable the block label options only while "label" is checked."""
            on = label.isChecked()
            for x in [use_prefix, use_suffix, case_label] + case:
                x.setEnabled(on)
            prefix.setEnabled(on and use_prefix.isChecked()); suffix.setEnabled(on and use_suffix.isChecked())
        for x in (label, use_prefix, use_suffix):
            x.toggled.connect(upd_label)
        upd_label()
        follow(blocking, [b_delay]); follow(nonblocking, [nb_label, nb_delay])
        follow(ansi, [net_label] + net, invert=True)      # separate net/variable types only with List ports

        # ---- Headers: one template per view type
        w = QWidget(); v = QVBoxLayout(w)
        box = QGroupBox('View Header'); b = QVBoxLayout(box)
        self.header_type = QComboBox(); self.header_type.addItems(HEADER_TYPES)
        self.header_type.setFixedWidth(240)
        self.headers = {t: p.header_for(t) for t in HEADER_TYPES}
        self.header = QPlainTextEdit(self.headers[HEADER_TYPES[0]])
        self.header.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.header.setToolTip('Variables: %(library) %(unit) %(view) %(project_name) %(user) %(date) %(time) '
                               '%(year) %(graphical_source_author) %(graphical_source_date) %(graphical_source_time)')
        self._header_shown = HEADER_TYPES[0]
        self.header_type.currentTextChanged.connect(self._show_header)
        b.addWidget(self.header_type); b.addWidget(self.header, 1)
        v.addWidget(box, 1)
        box = QGroupBox('Generation Property Information'); b = QVBoxLayout(box)
        self.gen_props = QCheckBox('Include generation properties after header in generated Verilog')
        self.gen_props.setChecked(p.gen_properties)
        self.gen_status = QCheckBox('Include signal status in generated state machine Verilog')
        self.gen_status.setChecked(p.gen_signal_status)
        self.gen_status.setContentsMargins(16, 0, 0, 0)
        row = QHBoxLayout(); row.setContentsMargins(16, 0, 0, 0); row.addWidget(self.gen_status)
        b.addWidget(self.gen_props); b.addLayout(row)
        follow(self.gen_props, [self.gen_status])
        v.addWidget(box)
        tabs.addTab(w, 'Headers')

        # ---- Default Directives: copied into new diagrams and text views
        w = QWidget(); v = QVBoxLayout(w)
        v.addWidget(QLabel('These directives will be added to all new verilog diagrams and text views.'))
        self.directives = {}
        for key, title, stretch in (('pre_module', 'Pre-Module Directives', 1), ('post_module', 'Post-Module Directives', 1),
                                    ('end_module', 'End-Module Directives', 3)):
            box = QGroupBox(title); b = QVBoxLayout(box)
            e = QPlainTextEdit(getattr(p, key)); e.setLineWrapMode(QPlainTextEdit.NoWrap)
            b.addWidget(e); v.addWidget(box, stretch)
            self.directives[key] = e
        tabs.addTab(w, 'Default Directives')

        # ---- Default Packages: lines copied before the module of new SystemVerilog views
        w = QWidget(); v = QVBoxLayout(w)
        box = QGroupBox('Default Package References'); b = QVBoxLayout(box)
        self.package_refs = QPlainTextEdit(p.package_refs)
        self.package_refs.setToolTip('Written before the module of new SystemVerilog diagrams and text views')
        b.addWidget(self.package_refs); v.addWidget(box, 1)
        box = QGroupBox('Preview'); g = QGridLayout(box)
        self.preview = QLineEdit(); add = QPushButton('Add')
        add.clicked.connect(self._add_package)
        self.lib_list, self.pkg_list = QListWidget(), QListWidget()
        g.addWidget(self.preview, 0, 0, 1, 2); g.addWidget(add, 0, 2)
        g.addWidget(QLabel('Library'), 1, 0); g.addWidget(QLabel('Package'), 1, 1, 1, 2)
        g.addWidget(self.lib_list, 2, 0); g.addWidget(self.pkg_list, 2, 1, 1, 2)
        g.setColumnStretch(0, 1); g.setColumnStretch(1, 2)
        v.addWidget(box, 2)
        self.project = project
        self.lib_list.addItems(sorted(lib.name for lib in project.libraries) if project else [])
        self.lib_list.currentTextChanged.connect(self._show_packages)
        self.pkg_list.currentTextChanged.connect(lambda t: t and self.preview.setText(f'import {t}::*;'))
        tabs.addTab(w, 'Default Packages')

        bb = _buttons(self, apply=True)
        bb.accepted.connect(self._ok); bb.rejected.connect(self.reject)
        bb.button(QDialogButtonBox.Apply).clicked.connect(self.apply)
        lay = QVBoxLayout(self); lay.addWidget(tabs); lay.addWidget(bb)
        self.tabs = tabs
        self.applied = False
        self.resize(660, 700)

    def _exts(self) -> list[str]:
        """The allowed extensions typed on the File tab, without dots."""
        return [e.lstrip('.') for e in self.allowed.text().split() if e.strip('.')]

    def _ext_combo(self, value: str) -> QComboBox:
        """An editable combo box offering the allowed extensions, showing `value`."""
        c = QComboBox(); c.setEditable(True)
        c.addItems(self._exts()); c.setCurrentText(value)
        return c

    def _refill_exts(self):
        """Offer the new list of allowed extensions in the three extension combo boxes."""
        for c in (self.source_ext, self.generated_ext, self.sv_ext):
            cur = c.currentText(); c.blockSignals(True); c.clear(); c.addItems(self._exts())
            c.setCurrentText(cur); c.blockSignals(False)

    @staticmethod
    def _case_combo(value: str) -> QComboBox:
        """Combo box of the case rules of a file name."""
        c = QComboBox(); c.addItems(['Preserve case', 'Always lower case', 'Always upper case'])
        c.setCurrentText(value)
        return c

    def _edit_search_path(self):
        """Add a folder to the ':'-separated default search path."""
        from PySide6.QtWidgets import QFileDialog
        d = QFileDialog.getExistingDirectory(self, 'Add to search path')
        if d:
            self.search.setText(':'.join([x for x in self.search.text().split(':') if x] + [d]))

    def _pragma_setup(self):
        """Style > Pragma Setup...: edit the pragma keyword and directives."""
        dlg = PragmaSetupDialog(self.pragma, self)
        if dlg.exec():
            self.pragma = dlg.values()

    def validate(self) -> str:
        """Error message for invalid input ('' when acceptable): directive texts may only hold
        compiler directives and comments, naming rules must contain their variable.
        """
        for key, title in (('pre_module', 'Pre-Module'), ('post_module', 'Post-Module'), ('end_module', 'End-Module')):
            for line in self.directives[key].toPlainText().split('\n'):
                line = line.strip()
                if line and not line.startswith(('//', '`')):      # comment lines are not checked
                    return f'{title} directives: "{line}" is not a compiler directive.'
        if '%(unit)' not in self.gen_rule.text():
            return 'The generated file rule must contain %(unit).'
        if '%(module_name)' not in self.source_rule.text() and '%(unit)' not in self.source_rule.text():
            return 'The source file rule must contain %(module_name).'
        return ''

    def apply(self) -> bool:
        """Validate, then write every tab into the preferences and save. False when invalid."""
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
        p.verilog_style = self.style_values()
        self.headers[self._header_shown] = self.header.toPlainText()
        p.view_headers = {t: h for t, h in self.headers.items() if h != p.header_template}
        p.gen_properties, p.gen_signal_status = self.gen_props.isChecked(), self.gen_status.isChecked()
        for key, e in self.directives.items():
            setattr(p, key, e.toPlainText())
        p.package_refs = self.package_refs.toPlainText()
        p.pragma = self.pragma
        p.save()
        self.applied = True
        return True

    def style_values(self) -> dict:
        """The Style tab as a dict: tab width plus every widget registered in style_widgets."""
        d = {'tab_width': self.tab_width.value()}
        for key, w in self.style_widgets.items():
            if isinstance(w, QCheckBox):
                d[key] = w.isChecked()
            elif isinstance(w, QLineEdit):
                d[key] = w.text()
            elif w.checkedButton() is not None:
                d[key] = w.checkedButton().text()
        return d

    def _show_header(self, view_type: str):
        """Headers tab: keep the text being edited, then show the template of `view_type`."""
        self.headers[self._header_shown] = self.header.toPlainText()
        self._header_shown = view_type
        self.header.setPlainText(self.headers[view_type])

    def _show_packages(self, name: str):
        """Packages of a library (SystemVerilog `package` units); the library is scanned on demand."""
        self.preview.setText(name)
        self.pkg_list.clear()
        lib = self.project.library(name) if self.project and name else None
        if lib is None:
            return
        if not lib.scanned:
            lib.scan()
        self.pkg_list.addItems(sorted(u.name for u in lib.units.values() if u.hdl and u.hdl.kind == 'package'))

    def _add_package(self):
        """Default Packages: append the package reference shown in the preview line."""
        line = self.preview.text().strip()
        if line:
            self.package_refs.appendPlainText(line)

    def _ok(self):
        """OK: apply and close, unless the input is invalid."""
        if self.apply():
            self.accept()


class PragmaSetupDialog(QDialog):
    """Keyword and off/on directives of HDL translation pragmas: // <keyword> <directive>."""

    def __init__(self, values: dict, parent=None):
        """Build the dialog from the saved pragma `values` (keyword, directive, sm_state_vector)."""
        super().__init__(parent)
        self.setWindowTitle('Pragma Setup')
        v = QVBoxLayout(self)
        note = QLabel('A Pragma is a form of compiler directive which is inserted into the generated HDL as a '
                      'special type of comment. You can choose which keyword to use to indicate a Pragma comment. '
                      'You can also specify which directives to use to exclude sections of HDL from being compiled '
                      'by the downstream tool (e.g. Synthesis).')
        note.setWordWrap(True); v.addWidget(note)
        box = QGroupBox('Options'); g = QGridLayout(box)
        self.keyword = QComboBox(); self.keyword.setEditable(True)
        self.keyword.addItems(['pragma', 'synopsys', 'synthesis', 'exemplar'])
        self.keyword.setCurrentText(values.get('keyword', 'pragma'))
        self.synthesis = QRadioButton('synthesis_off / synthesis_on')
        self.translate = QRadioButton('translate_off / translate_on')
        (self.translate if values.get('directive') == 'translate' else self.synthesis).setChecked(True)
        g.addWidget(QLabel('Pragma format:'), 0, 0); g.addWidget(QLabel('//   <keyword> <directive>'), 0, 1)
        g.addWidget(QLabel('Pragma keyword:'), 1, 0); g.addWidget(self.keyword, 1, 1)
        g.addWidget(QLabel('Off/On directives:'), 2, 0); g.addWidget(self.synthesis, 2, 1)
        g.addWidget(self.translate, 3, 1)
        v.addWidget(box)
        row = QHBoxLayout(); row.addWidget(QLabel('Format preview:'))
        self.preview = QLineEdit(); self.preview.setReadOnly(True); row.addWidget(self.preview, 1)
        v.addLayout(row)
        self.sm_vector = QCheckBox('New State Machine Pragma State Vector Default')
        self.sm_vector.setChecked(values.get('sm_state_vector', False)); v.addWidget(self.sm_vector)
        for w in (self.synthesis, self.translate):
            w.toggled.connect(self._preview)
        self.keyword.currentTextChanged.connect(self._preview)
        self._preview()
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.accepted.connect(self.accept); bb.rejected.connect(self.reject); v.addWidget(bb)

    def pragma(self, on: bool = False) -> str:
        """The pragma line, e.g. '// pragma synthesis_off'."""
        directive = 'translate' if self.translate.isChecked() else 'synthesis'
        return f'// {self.keyword.currentText().strip() or "pragma"} {directive}_{"on" if on else "off"}'

    def _preview(self, *_):
        """Show how a pragma line will look."""
        self.preview.setText(self.pragma())

    def values(self) -> dict:
        """The dialog's choices as the dict kept in prefs.pragma."""
        return {'keyword': self.keyword.currentText().strip() or 'pragma',
                'directive': 'translate' if self.translate.isChecked() else 'synthesis',
                'sm_state_vector': self.sm_vector.isChecked()}
