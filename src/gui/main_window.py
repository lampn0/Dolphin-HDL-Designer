"""The state diagram editor window (MainWindow).

Layout, as in HDS 2021.1: the diagram canvas (diagram.FsmScene / FsmGraphicsView) in the
middle, one page at a time (State Diagram, Signals Table, Parameters Table: the tab bar is
hidden, pages are reached from the Structure Navigator and the menus), the Diagram Browser
(Structure Navigator + Content) on the right, and HDL Studio's own Properties / Messages docks,
hidden at start.

Data flow:
  - the window owns the FsmView (`self.view`) and the machine shown (`self.machine`);
  - FsmScene edits that model directly and emits `changed_model`; model_changed() then marks
    the window dirty, records an undo step (undo.SnapshotUndo) and schedules regenerate(),
    which regenerates the HDL text (shown in the hidden code pane and used for warnings);
  - saving goes through the EditorContext when the window was opened from the Design Manager
    (locks, write-back to the HDS .sm), or straight to a file when standalone.
"""
from __future__ import annotations

from version import APP_NAME, about_text
import os

from PySide6.QtCore import QEvent, QObject, QSettings, QSize, Qt, QTimer
from PySide6.QtGui import QAction, QActionGroup, QFont, QKeySequence
from PySide6.QtWidgets import (QApplication, QComboBox, QDockWidget, QGraphicsItem, QFileDialog, QInputDialog, QLabel,
                               QListWidget, QMainWindow, QMessageBox,
                               QSplitter, QTableWidget, QTabWidget, QToolBar,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from codegen.fsm_codegen import generate
from examples import traffic_light
from hds.import_sm import import_sm
from model import ENCODINGS, LANGUAGES, STATE_DECLS, FsmView, State, Transition
from .code_view import CodeView
from .diagram import FsmGraphicsView, FsmScene, _BoxItem, apply_select_filter
from .icons import icon
from .menus import arrange_menus, fsm_menus
from .toolbars import FSM_KEYS, FSM_TOOLBAR, build_toolbar
from .props import PropertiesPanel
from .tables import ParametersTable, SignalsTable
from .undo import SnapshotUndo, load_view_state, save_view_state

MONO = QFont('Courier New', 9)
LANG_LABEL = {'systemverilog': 'SystemVerilog', 'verilog': 'Verilog 2005'}


class MainWindow(QMainWindow):
    """State machine editor. Standalone (files chosen by the user) or opened
    from the Design Manager with an EditorContext (library/unit/view)."""

    def __init__(self, view: FsmView | None = None, context=None):
        """Build the window. `view` is the FsmView to edit (the traffic light example when None);
        `context` is the EditorContext given by the Design Manager (None = standalone editor).
        """
        super().__init__()
        self.context = context
        self.view: FsmView = view or traffic_light()
        self.machine = self.view.machines[0]
        self.path: str | None = None
        self.dirty = False

        self.scene = FsmScene(self)
        self.canvas = FsmGraphicsView(self.scene)
        self.signals_tab = SignalsTable()
        self.params_tab = ParametersTable()
        self.code = CodeView()

        self.tabs = QTabWidget()
        self.tabs.addTab(self.canvas, 'State Diagram')
        self.tabs.addTab(self.signals_tab, 'Signals Table')
        self.tabs.addTab(self.params_tab, 'Parameters Table')
        # as in HDS one page at a time, reached from the Structure Navigator and the menus
        self.tabs.tabBar().hide()
        self.tabs.setDocumentMode(True)
        self.tabs.currentChanged.connect(lambda _i: self.update_title())
        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.tabs)
        code_box = QWidget(); cl = QVBoxLayout(code_box); cl.setContentsMargins(0, 0, 0, 0)
        self.code_title = QLabel()
        cl.addWidget(self.code_title); cl.addWidget(self.code)
        split.addWidget(code_box)
        split.setSizes([900, 600])
        code_box.hide()                 # HDS has no HDL pane in the diagram window (HDL > View Generated HDL)
        self.code_pane = code_box
        self.setCentralWidget(split)

        self.props = PropertiesPanel()
        dock = QDockWidget('Properties', self); dock.setWidget(self.props)
        dock.setObjectName('props')
        self.addDockWidget(Qt.LeftDockWidgetArea, dock)
        # Diagram Browser on the right with the Structure Navigator, as in HDS
        self.nav = QTreeWidget(); self.nav.setHeaderLabel('Structure Navigator')
        # Content (under the navigator, as in HDS): the objects of the machine by kind
        self.content = QTreeWidget(); self.content.setHeaderLabels(['Name', 'Concurrent Machine'])
        self.content.itemClicked.connect(self._content_clicked)
        browser = QSplitter(Qt.Vertical)
        browser.addWidget(self.nav)
        cbox = QWidget(); cl2 = QVBoxLayout(cbox); cl2.setContentsMargins(0, 0, 0, 0)
        cl2.addWidget(QLabel('Content')); cl2.addWidget(self.content)
        browser.addWidget(cbox)
        browser.setSizes([300, 250])
        nav_dock = QDockWidget('Diagram Browser', self); nav_dock.setWidget(browser)
        nav_dock.setObjectName('nav')
        self.addDockWidget(Qt.RightDockWidgetArea, nav_dock)
        self.nav_dock, self.props_dock = nav_dock, dock
        self.log = QListWidget(); self.log.setFont(MONO)
        log_dock = QDockWidget('Messages', self); log_dock.setWidget(self.log)
        log_dock.setObjectName('log')
        self.addDockWidget(Qt.BottomDockWidgetArea, log_dock)
        self.log_dock = log_dock
        self.resizeDocks([log_dock], [110], Qt.Vertical)
        self.resizeDocks([dock, nav_dock], [330, 230], Qt.Horizontal)
        # HDL Studio's own panels: kept, hidden at start so the window looks like HDS
        dock.hide()
        log_dock.hide()

        self.undo_stack = SnapshotUndo(lambda: self.view.to_json(), self._restore_snapshot, self)
        self._build_actions()
        self.undo_stack.changed.connect(self._update_undo_actions)
        for text, widget in (('Signals Table', self.signals_tab), ('Parameters Table', self.params_tab)):
            a = QAction(text, self)
            a.triggered.connect(lambda checked=False, w=widget: self.tabs.setCurrentWidget(w))
            self.addAction(a)
        about = QAction(f'About {APP_NAME}', self)
        about.triggered.connect(lambda: QMessageBox.about(self, APP_NAME, about_text('State machine editor')))
        self.addAction(about)
        self._build_menu_commands()
        arrange_menus(self, fsm_menus(standalone=self.context is None))
        self.statusBar().addWidget(QLabel('Ready'))      # as HDS when no message is shown
        self.regen_timer = QTimer(self); self.regen_timer.setSingleShot(True); self.regen_timer.setInterval(250)
        self.regen_timer.timeout.connect(self.regenerate)

        self.scene.changed_model.connect(self.model_changed)
        self.scene.selectionChanged.connect(self.on_selection)
        self.scene.edit_requested.connect(self.edit_object)
        self.scene.message.connect(lambda m: self.statusBar().showMessage(m, 5000))
        self.scene.condition_edit_requested.connect(self.edit_condition_inline)
        self.scene.rename_requested.connect(self.rename_state_inline)
        self.scene.text_edit_requested.connect(self.edit_text_inline)
        self.scene.popup_requested.connect(self.show_popup)
        # a double-click on a declaration block: the page where its text is edited
        self.scene.decl_edit_requested.connect(
            lambda key: self.tabs.setCurrentWidget(self.signals_tab) if key == 'status' else self.edit_decl_block(key))
        self.props.changed.connect(self.on_prop_changed)
        self.signals_tab.changed.connect(self.on_table_changed)
        self.params_tab.changed.connect(self.model_changed)
        self.nav.itemClicked.connect(self.on_nav)

        self.resize(1600, 950)
        self.load_view(self.view, None)
        if self.context is not None and self.context.readonly:
            for mode, a in self.mode_actions.items():
                a.setEnabled(mode == 'select')
            self.props.setEnabled(False)
            for t in (self.signals_tab, self.params_tab):
                t.table.setEditTriggers(QTableWidget.NoEditTriggers)
                t.setEnabled(True)
            self.scene.readonly = True
            self.statusBar().showMessage('Read-only: ' + self.context.readonly_reason)

    # -- actions --------------------------------------------------------------------
    def _build_actions(self):
        """The actions of the editor: file commands (different standalone / in a project), edit, view
        and zoom commands, one checkable action per tool (Select, Add State, ...), the toolbar
        (toolbars.build_toolbar) and the generation toolbar (language, state declaration, encoding).
        """
        mb = self.menuBar()
        fm = mb.addMenu('&File')
        self.act_open_generated = None
        if self.context is None:
            self._act(fm, '&New', self.new_file, QKeySequence.New)
            self._act(fm, '&Open...', self.open_file, QKeySequence.Open)
            self._act(fm, '&Import HDS state machine (.sm)...', self.import_file)
            fm.addSeparator()
            self.act_save = self._act(fm, '&Save', self.save_file, QKeySequence.Save, 'save')
            self._act(fm, 'Save &As...', self.save_as)
            self.act_generate = self._act(fm, '&Generate (export HDL)...', self.export_hdl, 'Shift+G', 'generate')
            fm.addSeparator()
            self._act(fm, 'E&xit', self.close)
        else:
            self.act_save = self._act(fm, '&Save', self.save_file, QKeySequence.Save, 'save')
            self.act_generate = self._act(fm, '&Generate HDL', self.generate_hdl, 'Shift+G', 'generate')
            self._act(fm, 'Save and Generate', lambda: (self.save_file(), self.generate_hdl()), 'Ctrl+Shift+G')
            self.act_open_generated = self._act(fm, 'Open generated HDL',
                                                lambda: self.context.open_generated(self.view), 'Ctrl+G',
                                                'generate_open')
            fm.addSeparator()
            self._act(fm, '&Close', self.close, QKeySequence.Close)
        em = mb.addMenu('&Edit')
        self.act_undo = self._act(em, '&Undo', self.undo_stack.undo, QKeySequence.Undo, 'undo')
        self.act_redo = self._act(em, '&Redo', self.undo_stack.redo, ['Ctrl+Y', 'Ctrl+Shift+Z'], 'redo')
        em.addSeparator()
        act_del = self._act(em, '&Delete', self.scene.delete_selected, None, 'delete')
        self.act_edit_text = self._act(em, 'Edit Selected &Text', lambda: self.edit_selection(focus_text=True))
        vm = mb.addMenu('&View')
        act_fit = self._act(vm, 'View All', self.canvas.fit, None, 'fit')
        act_zin = self._act(vm, 'Zoom in', lambda: self.canvas.zoom(1.2), None, 'zoom_in')
        act_zout = self._act(vm, 'Zoom out', lambda: self.canvas.zoom(1 / 1.2), None, 'zoom_out')
        act_zlast = self._act(vm, 'Zoom Last', self.canvas.zoom_last)
        act_area = self._act(vm, 'View Area', self.view_area)
        act_all = self._act(em, 'Select All', self.select_all)

        group = QActionGroup(self); group.setExclusive(True)
        self.mode_actions = {}
        for mode, text in [('select', 'Select'), ('select_text', 'Select Text'), ('select_shape', 'Select Shapes'),
                           ('pan', 'Panning'), ('state', 'Add State'), ('transition', 'Add Transition'),
                           ('junction_if', 'Add IF Junction'), ('junction_case', 'Add CASE Junction'),
                           ('link', 'Add Link'), ('interrupt', 'Add Interrupt Point'),
                           ('recovery', 'Add Recovery State Point'), ('reset', 'Add Reset Point'),
                           ('clock', 'Add Clock Point')]:
            a = QAction(icon(mode), text, self); a.setCheckable(True)
            a.triggered.connect(lambda checked, m=mode: self.set_mode(m))
            group.addAction(a)
            self.mode_actions[mode] = a
        self.mode_actions['select'].setChecked(True)
        act_props = QAction('Object Properties', self); act_props.triggered.connect(self.edit_selection)
        act_drc = QAction('Run Design Rule Checks', self); act_drc.triggered.connect(self.run_checks)
        self.toolbar_actions = {
            'save': self.act_save, 'undo': self.act_undo, 'redo': self.act_redo, 'object_props': act_props,
            'zoom_in': act_zin, 'zoom_out': act_zout, 'zoom_last': act_zlast, 'view_area': act_area,
            'fit': act_fit, 'drc': act_drc, 'generate': self.act_generate, 'delete': act_del,
            'select_all': act_all, 'edit_text': self.act_edit_text,
            **{k: v for k, v in self.mode_actions.items()},
        }
        if self.act_open_generated is not None:
            self.toolbar_actions['generate_open'] = self.act_open_generated
            self.toolbar_actions['generate_root'] = QAction('Generate through design root', self)
            self.toolbar_actions['generate_root'].triggered.connect(
                lambda: self.context.generate_hierarchy(self.view, self, 'root'))
        build_toolbar(self, self.toolbar_actions, FSM_TOOLBAR, FSM_KEYS)
        self.canvas.end_command.connect(lambda: self.set_mode('select'))
        self.canvas.tool_done.connect(lambda: self.set_mode(self._mode_before_area))
        self.canvas.nudged.connect(self.scene.changed_model.emit)
        self._mode_before_area = 'select'
        self._once = False
        self.select_filter = 'any'
        self.addAction(act_del)

        gt = QToolBar('Generation'); gt.setObjectName('gen')
        self.addToolBar(gt)
        self.tb_lang = QComboBox(); [self.tb_lang.addItem(LANG_LABEL[l], l) for l in LANGUAGES]
        self.tb_lang.setToolTip('Target language')
        gt.addWidget(self.tb_lang)
        self.tb_decl = QComboBox(); self.tb_decl.addItems(STATE_DECLS)
        self.tb_decl.setToolTip('State declaration: parameter / localparam / enum')
        gt.addWidget(self.tb_decl)
        self.tb_enc = QComboBox(); self.tb_enc.addItems(ENCODINGS)
        self.tb_enc.setToolTip('State encoding')
        gt.addWidget(self.tb_enc)
        for cb in (self.tb_lang, self.tb_decl, self.tb_enc):
            cb.currentIndexChanged.connect(self.on_toolbar_option)

    def _act(self, menu, text, slot, key=None, icon_name: str | None = None):
        """key may be one shortcut or a list (first one is shown in menus)."""
        a = QAction(text, self)
        if icon_name:
            a.setIcon(icon(icon_name))
        if key:
            keys = [QKeySequence(k) for k in (key if isinstance(key, (list, tuple)) else [key])]
            a.setShortcuts(keys)
            a.setToolTip(f'{text.replace("&", "")}  ({", ".join(k.toString() for k in keys)})')
        a.triggered.connect(slot)
        menu.addAction(a)
        return a

    def view_area(self):
        """View Area: drag a rectangle on the diagram to view that area."""
        if self.canvas.tool != 'area':
            self._mode_before_area = self.scene.mode if self.canvas.tool != 'pan' else 'pan'
        self.scene.set_mode('select')
        self.canvas.set_tool('area')
        self.statusBar().showMessage('Drag a rectangle around the area to view (Esc cancels)', 4000)

    def select_all(self):
        """Edit > Select All: select every selectable item of the diagram."""
        for it in self.scene.items():
            if it.flags() & QGraphicsItem.ItemIsSelectable:
                it.setSelected(True)

    def _is_text(self, item) -> bool:
        """True for the text items of the diagram (used by Select Text / Select Shapes)."""
        return isinstance(item, _BoxItem)

    def run_checks(self):
        """Design rule check: generator warnings plus a syntax check of the generated HDL."""
        from hdl.parser import check_text
        text, warnings = generate(self.view)
        self.log.clear()
        for w in warnings:
            self.log.addItem(f'warning: {w}')
        ext = 'sv' if self.view.language == 'systemverilog' else 'v'
        diags = [d for d in check_text(text, f'{self.view.unit}.{ext}') if d[1] == 'error']
        for line, _, msg in diags:
            self.log.addItem(f'error: generated HDL line {line}: {msg}')
        self.log.addItem(f'Design rule check: {len(diags)} error(s), {len(warnings)} warning(s)')

    def _build_menu_commands(self):
        """Commands of the HDS menu bar that the toolbar does not have (File, View, Diagram,
        Options, Window, Help), added to toolbar_actions under the keys fsm_menus() names."""
        from PySide6.QtWidgets import QApplication, QMenu, QToolBar
        mgr = self.context.manager if self.context is not None else None

        def act(key, text, slot=None, shortcut='', checkable=False, checked=False):
            """Create the action `key` in toolbar_actions: a check box action (`checkable`, slot gets the
            state) or a plain one; without a slot it is disabled.
            """
            a = QAction(text, self)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            if checkable:
                a.setCheckable(True); a.setChecked(checked)
                if slot is not None:
                    a.toggled.connect(slot)
            elif slot is not None:
                a.triggered.connect(slot)
            else:
                a.setEnabled(False)
            self.toolbar_actions[key] = a
            return a
        act('page_setup', 'Page Setup...', mgr.page_setup if mgr else None)
        act('close_window', 'Close Window', self.close)
        act('exit', 'Exit', QApplication.instance().closeAllWindows)
        act('refresh', 'Refresh', lambda: self.canvas.viewport().update(), 'F5')
        act('grid', 'Grid', lambda on: (setattr(self.canvas, 'show_grid', on), self.canvas.viewport().update()),
            checkable=True, checked=getattr(self.canvas, 'show_grid', True))
        tb = act('toolbars', 'Toolbars', lambda: None)
        menu = QMenu(self)
        menu.aboutToShow.connect(lambda: (menu.clear(), [menu.addAction(t.toggleViewAction())
                                                          for t in self.findChildren(QToolBar)]))
        tb.setMenu(menu)
        act('status_bar', 'Status Bar', lambda on: self.statusBar().setVisible(on), checkable=True, checked=True)
        a = act('diagram_browser', 'Diagram Browser', lambda on: self.nav_dock.setVisible(on),
                checkable=True, checked=True)
        self.nav_dock.visibilityChanged.connect(a.setChecked)
        act('signals_table', 'Signals Table', lambda: self.tabs.setCurrentWidget(self.signals_tab))
        act('compiler_directives', 'Compiler Directives...', self.compiler_directives)
        act('sm_props', 'State Machine Properties...', self.machine_properties)
        act('main_settings', 'Main...', mgr.main_settings if mgr else None)
        act('verilog_options', 'Verilog...', mgr.verilog_options if mgr else None)
        act('log_window', 'HDS Log Window', lambda: (self.log_dock.show(), self.log_dock.raise_()))
        act('design_manager', 'Design Manager',
            (lambda: (mgr.show(), mgr.raise_(), mgr.activateWindow())) if mgr else None)
        act('shortcuts_help', 'Keyboard Shortcuts', mgr._show_shortcuts if mgr else None)
        # F2 (edit the selected text) is in no HDS menu: keep its shortcut on the window
        self.addAction(self.act_edit_text)

    def edit_object(self, obj):
        """Double-click on an object. States and transitions: the HDS "SM Object Properties"
        dialog; other objects: HDL Studio's Properties panel (shown when hidden)."""
        from model import State, Transition
        if isinstance(obj, (State, Transition)) and not self.scene.readonly:
            from .sm_props_dialog import SmObjectPropertiesDialog
            dlg = SmObjectPropertiesDialog(self.machine, [obj], self)
            dlg.exec()
            if dlg.applied:
                self.scene.load(self.view, self.machine)
                self.scene.changed_model.emit()
            return
        self.props.show_object(obj, self.machine)
        self.props_dock.show()
        self.props_dock.raise_()

    # -- popup menus ---------------------------------------------------------------------
    def show_popup(self, item, screen_pos):
        """The right-click menus of the HDS 2021.1 state diagram, entry for entry as HDS shows
        them on gc_control_fsm (tests/hds_gui/out/pop_*.png). Transitions have their own
        (TransitionItem). Entries HDL Studio has no command for yet are disabled.

            diagram   Signals Table, Open Up | Undo, Redo | Paste | View Area, Zoom In, Zoom Out,
                      Zoom Last | View Page, Print Page... | Object Visibility... |
                      Update Where Used... | State Machine Properties...
            state     Cut, Copy, Paste, Paste Special >, Delete | Appearance..., Change Shape...,
                      Show Text, Re-level >, Object Properties...
            junction  Cut, Copy, Paste, Paste Special >, Delete | Appearance..., Object Properties...
            link, clock / reset / enable point
                      Rotate > | Cut ... Delete | Appearance..., Object Properties...
            interrupt point   the same without Object Properties...
            recovery point    Cut ... Delete | Appearance..., Hide
            text      Copy, Paste, Paste Special > | Appearance..., Hide Text, Send to Editor,
                      Finish Edit, Finish All Edits | Object Properties...
        """
        from PySide6.QtWidgets import QMenu
        from .diagram import DeclBlockItem, JunctionItem, LinkItem, PointItem, StateItem
        ro = self.scene.readonly
        acts = self.toolbar_actions
        m = QMenu(self)

        def add(text, slot=None, shortcut='', enabled=True):
            """Add an entry (disabled without a slot or when `enabled` is False) with its shortcut shown."""
            a = m.addAction(text)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
                a.setShortcutVisibleInContextMenu(True)
            a.setEnabled(bool(slot) and enabled)
            if slot:
                a.triggered.connect(slot)
            return a

        def sub(text, entries):
            """Add a sub-menu whose entries are all disabled (commands not available yet)."""
            sm = m.addMenu(text)
            for e in entries:
                sm.addAction(e).setEnabled(False)

        def edit_part(cut=True):
            """The Cut / Copy / Paste / Paste Special / Delete / Appearance part of an object menu."""
            if cut:
                add('Cut', shortcut='Ctrl+X')
                add('Copy', shortcut='Ctrl+C')
            add('Paste', shortcut='Ctrl+V')
            sub('Paste Special', ['Paste from system clipboard'])
            add('Delete', self.scene.delete_selected, 'Del', not ro)
            m.addSeparator()
            add('Appearance...')

        def props():
            """The Object Properties... entry of an object menu."""
            add('Object Properties...', lambda: self.edit_object(item.obj), 'Alt+Return')

        if item is None:
            up = acts.get('open_up')
            add('Signals Table', lambda: self.tabs.setCurrentWidget(self.signals_tab))
            add('Open Up', up.trigger if up is not None and up.isEnabled() else None, 'Ctrl+Shift+O')
            m.addSeparator()
            add('Undo', self.undo_stack.undo, 'Ctrl+Z', self.act_undo.isEnabled())
            add('Redo', self.undo_stack.redo, 'Ctrl+Y', self.act_redo.isEnabled())
            m.addSeparator()
            add('Paste', shortcut='Ctrl+V')
            m.addSeparator()
            add('View Area', self.view_area, 'Shift+Home')
            add('Zoom In', lambda: self.canvas.zoom(1.2), 'Shift+Up')
            add('Zoom Out', lambda: self.canvas.zoom(1 / 1.2), 'Shift+Down')
            add('Zoom Last', self.canvas.zoom_last)
            m.addSeparator()
            add('View Page')
            add('Print Page...')
            m.addSeparator()
            add('Object Visibility...')
            m.addSeparator()
            add('Update Where Used...')
            add('State Machine Properties...', self.machine_properties)
        elif isinstance(item, StateItem):
            edit_part()
            add('Change Shape...')
            add('Show Text')
            sub('Re-level', ['Add hierarchy', 'Remove hierarchy'])
            props()
        elif isinstance(item, JunctionItem):
            edit_part()
            props()
        elif isinstance(item, (LinkItem, PointItem)):
            kind = getattr(item.obj, 'kind', 'link')
            if kind != 'recovery':
                sub('Rotate', ['90', '180', '270'])
                m.addSeparator()
            edit_part()
            if kind == 'recovery':
                add('Hide')
            elif kind != 'interrupt':
                props()
        else:
            # a text: transition condition / actions, state actions, declaration block
            # Copy: the box's text (its sections one after the other) to the system clipboard
            secs = item.sections() if hasattr(item, 'sections') else []
            text = '\n'.join(line for _tag, lines in secs for line in lines)
            add('Copy', (lambda: QApplication.clipboard().setText(text)) if text else None, 'Ctrl+C')
            add('Paste', shortcut='Ctrl+V')
            sub('Paste Special', ['Paste from system clipboard'])
            m.addSeparator()
            add('Appearance...')
            add('Hide Text')
            add('Send to Editor')
            add('Finish Edit')
            add('Finish All Edits')
            m.addSeparator()
            if isinstance(item, DeclBlockItem):
                add('Object Properties...', lambda: self.edit_decl_block(item.key), 'Alt+Return')
            elif getattr(item, 'obj', None) is not None:
                props()
        m.exec(screen_pos)

    # -- machine-level dialogs ----------------------------------------------------------
    def _machine_dialog_done(self, dlg):
        """After a machine-level dialog: draw the diagram again (texts, hidden blocks) and
        record one undo step when something was applied."""
        if dlg.applied:
            self.scene.load(self.view, self.machine)
            self.sync_toolbar()
            self.scene.changed_model.emit()

    def machine_properties(self, page: str = 'generation'):
        """Diagram > State Machine Properties... (also the diagram popup menu): the HDS dialog,
        opened on `page` (a key of sm_machine_dialog.PAGES)."""
        from .sm_machine_dialog import StateMachinePropertiesDialog
        if self.machine is None:
            return
        dlg = StateMachinePropertiesDialog(self.view, self.machine, self, page=page if isinstance(page, str)
                                           else 'generation', readonly=self.scene.readonly)
        if dlg.exec() or dlg.applied:
            self._machine_dialog_done(dlg)

    def compiler_directives(self):
        """Diagram > Compiler Directives...: the Verilog Compiler Directives dialog."""
        from .sm_machine_dialog import CompilerDirectivesDialog
        dlg = CompilerDirectivesDialog(self.view, self, readonly=self.scene.readonly)
        dlg.exec()
        self._machine_dialog_done(dlg)

    def edit_decl_block(self, key: str):
        """A double-click on a declaration block, or its entry in the Structure Navigator: the
        dialog page where its text is edited."""
        if key == 'compdir':
            self.compiler_directives()
        else:
            self.machine_properties({'concurrent': 'statements', 'statereg': 'statements', 'global': 'statements',
                                     'module': 'declarations'}.get(key, 'generation'))

    def edit_text_inline(self, item, field: str):
        """Edit one text of the diagram in place, in a box over it, as HDS does on a
        double-click: a transition's condition / actions, a state's entry / state / exit actions,
        a link's target, a CASE junction's expression, a clock / enable expression, a text of
        the declaration blocks. Leaving the box (or Ctrl+Enter, Enter for one line) keeps the
        text; Esc drops the edit."""
        from PySide6.QtWidgets import QLineEdit, QPlainTextEdit
        from .diagram import DeclBlockItem, JunctionItem, LinkItem, PointItem
        view, sc = self.view, self.scene
        if isinstance(item, DeclBlockItem):
            target, attr = view, field
        elif isinstance(item, PointItem):
            target = next((s for s in view.signals if s.category == item.obj.kind), None)
            attr = 'expression'
            if target is None:
                return
        else:
            target, attr = item.obj, field
        multiline = not isinstance(item, (LinkItem, JunctionItem, PointItem)) and attr != 'cond'
        old = getattr(target, attr)
        r = item.mapToScene(item.boundingRect()).boundingRect()
        vp = self.canvas.viewport()
        ed = QPlainTextEdit(vp) if multiline else QLineEdit(vp)
        ed.setFont(QFont('Arial', 9))
        if multiline:
            ed.setPlainText(old)
            ed.setLineWrapMode(QPlainTextEdit.NoWrap)
        else:
            ed.setText(old)
            ed.selectAll()
        tl = self.canvas.mapFromScene(r.topLeft())
        br = self.canvas.mapFromScene(r.bottomRight())
        ed.setGeometry(tl.x(), tl.y(), max(160, br.x() - tl.x() + 40),
                       max(26, br.y() - tl.y() + (40 if multiline else 4)))
        ed.setStyleSheet('border: 1px solid #0080c0; background: white;')
        ed.show(); ed.setFocus()
        done = []

        def finish(keep: bool):
            """Close the edit box; with `keep`, write the new text into the model and redraw. Runs once."""
            if done:
                return
            done.append(1)
            new = ed.toPlainText() if multiline else ed.text().strip()
            ed.deleteLater()
            if keep and new != old:
                setattr(target, attr, new)
                sc.load(view, self.machine)
                sc.changed_model.emit()
                self.signals_tab.set_rows(view.signals)

        class _Focus(QObject):
            """Event filter of the edit box: focus out keeps the text, Esc drops it, Enter (Ctrl+Enter in a
            multi-line box) keeps it.
            """
            def eventFilter(self, obj, ev):
                """Qt callback for the edit box's events (see the class docstring)."""
                if ev.type() == QEvent.FocusOut:
                    finish(True)
                elif ev.type() == QEvent.KeyPress:
                    if ev.key() == Qt.Key_Escape:
                        finish(False)
                        return True
                    if ev.key() in (Qt.Key_Return, Qt.Key_Enter) and (
                            not multiline or ev.modifiers() & Qt.ControlModifier):
                        finish(True)
                        return True
                return False
        ed._filter = _Focus(ed)
        ed.installEventFilter(ed._filter)

    def rename_state_inline(self, item):
        """Edit a state name in place, in a box over the name (HDS: a double-click on the name).
        Enter or leaving the box renames the state, links to it follow; Esc keeps the old name.
        An empty name or the name of another state is refused."""
        from PySide6.QtWidgets import QLineEdit
        s = item.obj
        vp = self.canvas.viewport()
        ed = QLineEdit(vp)
        ed.setText(s.name); ed.selectAll()
        ed.setMinimumWidth(80); ed.adjustSize()
        p = self.canvas.mapFromScene(item.mapToScene(item.name_rect().center()))
        ed.move(p.x() - ed.width() // 2, p.y() - ed.height() // 2)
        ed.show(); ed.setFocus()
        done = []

        def finish(keep: bool):
            """Close the name box; with `keep`, rename the state (and the links to it) when the name is free."""
            if done:
                return
            done.append(1)
            new, old = ed.text().strip(), s.name
            ed.deleteLater()
            if not keep or not new or new == old:
                return
            if any(o.name == new for o in self.machine.states if o is not s):
                self.statusBar().showMessage(f'A state named {new} already exists', 5000)
                return
            item.prepareGeometryChange()            # the circle grows with the name
            s.name = new
            for lk in self.machine.links:
                if lk.target == old:
                    lk.target = new
            self.scene.load(self.view, self.machine)
            self.scene.changed_model.emit()

        ed.returnPressed.connect(lambda: finish(True))
        ed.editingFinished.connect(lambda: finish(True))
        esc = QAction(ed); esc.setShortcut(QKeySequence('Esc')); esc.setShortcutContext(Qt.WidgetShortcut)
        esc.triggered.connect(lambda: finish(False))
        ed.addAction(esc)

    def edit_condition_inline(self, t):
        """Type the condition of a new transition in place, in a box at the middle of the
        transition, as HDS 2021.1 opens one when a transition is drawn. Enter or leaving the
        box keeps the text; Esc leaves the condition empty."""
        from PySide6.QtWidgets import QLineEdit
        it = self.scene.trans_items.get(t.id)
        if it is None:
            return
        path = it.path()
        mid = it.mapToScene(path.pointAtPercent(0.5)) if path.length() > 0 else it.scenePos()
        vp = self.canvas.viewport()
        ed = QLineEdit(vp)
        ed.setPlaceholderText('value')                  # the hint HDS shows in its box
        ed.setText(t.cond)
        ed.setMinimumWidth(120)
        ed.adjustSize()
        p = self.canvas.mapFromScene(mid)
        ed.move(p.x() - ed.width() // 2, p.y() - ed.height() // 2)
        ed.show(); ed.setFocus()
        done = []

        def finish(keep: bool):
            """Close the condition box; with `keep`, store the condition and redraw the transitions."""
            if done:
                return
            done.append(1)
            if keep and ed.text().strip() != t.cond:
                t.cond = ed.text().strip()
                self.scene.refresh_transitions_from(t.src)
                self.scene.changed_model.emit()
            ed.deleteLater()

        ed.returnPressed.connect(lambda: finish(True))
        ed.editingFinished.connect(lambda: finish(True))
        esc = QAction(ed); esc.setShortcut(QKeySequence('Esc')); esc.setShortcutContext(Qt.WidgetShortcut)
        esc.triggered.connect(lambda: finish(False))
        ed.addAction(esc)

    def edit_selection(self, focus_text: bool = False):
        """Alt+Enter / F2: show the selected object in the Properties panel."""
        sel = self.scene.selectedItems()
        obj = getattr(sel[0], 'obj', None) if sel else None
        if obj is None:
            return
        self.props.show_object(obj, self.machine)
        self.props.parentWidget().show()
        self.props.parentWidget().raise_()
        if focus_text:
            self.props.focus_main_field()

    def set_mode(self, mode):
        """Select/Panning tools and the Add commands. Add commands repeat until
        Esc or the right button (Main Settings > Toolbar Buttons: Remain active); Ctrl while
        choosing one toggles that for the command."""
        from prefs import Prefs
        ctrl = bool(QApplication.keyboardModifiers() & Qt.ControlModifier)
        self._once = mode not in ('select', 'select_text', 'select_shape', 'pan') and \
            ctrl == Prefs.load().toolbar_remain_active
        self.canvas.set_tool('')
        if mode in ('select', 'select_text', 'select_shape'):
            self.select_filter = {'select': 'any', 'select_text': 'text', 'select_shape': 'shape'}[mode]
        self.scene.set_mode('select' if mode in ('select_text', 'select_shape', 'pan') else mode)
        apply_select_filter(self.scene, self.select_filter if mode != 'pan' else 'any', self._is_text)
        if mode == 'pan':
            self.canvas.set_tool('pan')
        self.mode_actions[mode].setChecked(True)
        self.tabs.setCurrentWidget(self.canvas)
        hints = {'state': 'Click on the canvas to add a state',
                 'transition': 'Click the source, then the destination',
                 'link': 'Click to place a link, then pick the target state',
                 'pan': 'Drag to move the diagram (Esc returns to Select)'}
        self.statusBar().showMessage(hints.get(mode, ''), 4000)

    def keyPressEvent(self, e):
        """Esc goes back to the Select tool."""
        if e.key() == Qt.Key_Escape:
            self.set_mode('select')
        super().keyPressEvent(e)

    # -- loading --------------------------------------------------------------------
    def load_view(self, view: FsmView, path: str | None):
        """Show `view` (read from `path`, None when not from a file): fill the scene, tables and
        navigator, regenerate, start a new undo history and restore the saved zoom / position.
        """
        self.view, self.path = view, path
        self.machine = view.machines[0] if view.machines else None
        self.scene.load(view, self.machine)
        apply_select_filter(self.scene, getattr(self, 'select_filter', 'any'), self._is_text)
        self.signals_tab.set_rows(view.signals)
        self.params_tab.set_rows(view.parameters)
        self.props.show_object(None)
        self.sync_toolbar()
        self.build_nav()
        self.dirty = False
        self.update_title()
        self.regenerate()
        self.undo_stack.reset()
        QTimer.singleShot(0, self._restore_view_position)

    # -- view position, undo ----------------------------------------------------------
    def _view_key(self) -> str:
        """Key under which the zoom / scroll of this diagram is remembered (its file path)."""
        if self.context is not None:
            return getattr(self.context, 'key', '') or self.context.view.path
        return self.path or ''

    def _restore_view_position(self):
        """Open where the user left the diagram: HDL Studio's own saved view first, then the view
        area HDS saved for the machine (at HDS's 100%, which is a zoom of 75/72 here, from its
        top-left corner), else the whole diagram."""
        if self.canvas.restore(load_view_state(self._view_key())):
            return
        va = self.machine.view_area if self.machine is not None else None
        if va:
            k = 75 / 72
            self.canvas.resetTransform()
            self.canvas.scale(k, k)
            vp = self.canvas.viewport()
            self.canvas.centerOn(va[0] + vp.width() / (2 * k), va[1] + vp.height() / (2 * k))
            return
        self.canvas.fit()

    def _save_view_position(self):
        """Remember the zoom / scroll of this diagram (on close)."""
        save_view_state(self._view_key(), self.canvas.state())

    def _restore_snapshot(self, text: str):
        """Put back an undo snapshot without moving the user's view."""
        st = self.canvas.state()
        view = FsmView.from_json(text)
        idx = self.view.machines.index(self.machine) if self.machine in self.view.machines else 0
        self.view = view
        self.machine = view.machines[min(idx, len(view.machines) - 1)]
        self.scene.load(view, self.machine)
        apply_select_filter(self.scene, getattr(self, 'select_filter', 'any'), self._is_text)
        self.signals_tab.set_rows(view.signals)
        self.params_tab.set_rows(view.parameters)
        self.props.show_object(None)
        self.sync_toolbar()
        self.build_nav()
        self.canvas.restore(st)
        # back on the saved state (e.g. undo of every edit since the last save): no '*'
        self.dirty = not self.undo_stack.is_clean(text)
        self.update_title()
        self.regen_timer.start()

    def _update_undo_actions(self):
        """Enable Undo / Redo according to the history."""
        self.act_undo.setEnabled(self.undo_stack.can_undo())
        self.act_redo.setEnabled(self.undo_stack.can_redo())

    def sync_toolbar(self):
        """Show the view's language, state declaration and encoding in the generation toolbar
        (without triggering on_toolbar_option).
        """
        for cb in (self.tb_lang, self.tb_decl, self.tb_enc):
            cb.blockSignals(True)
        self.tb_lang.setCurrentIndex(LANGUAGES.index(self.view.language))
        self.tb_decl.setCurrentText(self.machine.state_decl)
        self.tb_enc.setCurrentText(self.machine.encoding)
        for cb in (self.tb_lang, self.tb_decl, self.tb_enc):
            cb.blockSignals(False)

    def on_toolbar_option(self, *args):
        """A generation toolbar choice changed: store it in the model."""
        self.view.language = self.tb_lang.currentData()
        self.machine.state_decl = self.tb_decl.currentText()
        self.machine.encoding = self.tb_enc.currentText()
        self.model_changed()

    def build_nav(self):
        """Fill the Structure Navigator: tables, declaration blocks, machines and their states."""
        self.nav.clear()
        v = self.view
        QTreeWidgetItem(self.nav, ['Signals Table']).setData(0, Qt.UserRole, 'signals')
        QTreeWidgetItem(self.nav, ['Parameters Table']).setData(0, Qt.UserRole, 'params')
        unit = QTreeWidgetItem(self.nav, [v.unit]); unit.setData(0, Qt.UserRole, 'props')
        decl = QTreeWidgetItem(unit, ['Declarations/Statements']); decl.setData(0, Qt.UserRole, 'props')
        for t, k in (('Compiler Directives', 'compdir'), ('Concurrent Statements', 'concurrent'),
                     ('Global Actions', 'global')):
            QTreeWidgetItem(decl, [t]).setData(0, Qt.UserRole, f'props:{k}')
        machines = QTreeWidgetItem(unit, ['Concurrent Machines'])
        for m in v.machines:
            it = QTreeWidgetItem(machines, [m.name]); it.setData(0, Qt.UserRole, 'diagram')
            for s in m.states:
                QTreeWidgetItem(it, [s.name]).setData(0, Qt.UserRole, ('state', s.id))
        self.build_content()
        for k in range(self.nav.topLevelItemCount()):        # HDS shows the top entries in bold
            it = self.nav.topLevelItem(k)
            f = it.font(0); f.setBold(True); it.setFont(0, f)
        self.nav.expandToDepth(1)

    def on_nav(self, item, col):
        """A click in the Structure Navigator: show that page, open that block's dialog, or select and
        centre that state.
        """
        key = item.data(0, Qt.UserRole)
        if key == 'signals':
            self.tabs.setCurrentWidget(self.signals_tab)
        elif key == 'params':
            self.tabs.setCurrentWidget(self.params_tab)
        elif isinstance(key, str) and key.startswith('props'):
            self.edit_decl_block(key[6:] or 'machine')
        elif key == 'diagram':
            self.tabs.setCurrentWidget(self.canvas)
        elif isinstance(key, tuple):
            self.tabs.setCurrentWidget(self.canvas)
            it = self.scene.item_for(key[1])
            if it:
                self.scene.clearSelection(); it.setSelected(True)
                self.canvas.centerOn(it)

    # -- change handling ------------------------------------------------------------
    def build_content(self):
        """The Content pane: one group per kind of object of the machine, "(Items: n)", with
        the objects under it (name, machine), as HDS lists them. Only kinds present are shown."""
        if not hasattr(self, 'content'):
            return
        self.content.clear()
        m = self.machine
        if m is None:
            return
        # the kinds HDS 2021.1 lists there (junctions, links, recovery and interrupt points are
        # not listed; HDS also lists comment texts, which HDL Studio's state diagrams do not have)
        groups = [('state', [(s.name, s.id) for s in m.states])]
        for kind in ('clock', 'reset', 'enable'):
            groups.append((kind, [(p.kind, p.id) for p in m.points if p.kind == kind]))
        for kind, objs in groups:
            if not objs:
                continue
            top = QTreeWidgetItem(self.content, [f'(Items: {len(objs)})', ''])
            top.setIcon(0, icon(kind))
            for name, oid in objs:
                QTreeWidgetItem(top, [name, m.name]).setData(0, Qt.UserRole, oid)

    def _content_clicked(self, item, _col):
        """A click in the Content pane: select and centre that object."""
        oid = item.data(0, Qt.UserRole)
        if oid:
            it = self.scene.item_for(oid)
            if it is not None:
                self.tabs.setCurrentWidget(self.canvas)
                self.scene.clearSelection(); it.setSelected(True)
                self.canvas.centerOn(it)

    def model_changed(self):
        """Called after every edit of the model: dirty flag and title, Content pane, delayed
        regeneration, undo step. An Add command used "once" goes back to Select here.
        """
        if self._once and self.scene.mode != 'select' and self.scene._pending_src is None:
            self._once = False
            QTimer.singleShot(0, lambda: self.set_mode('select'))
        self.dirty = True
        self.update_title()
        self.build_content()
        self.regen_timer.start()
        self.undo_stack.note_change()
        self._update_undo_actions()

    def on_selection(self):
        """Show the single selected object in the Properties panel."""
        sel = self.scene.selectedItems()
        obj = sel[0].obj if len(sel) == 1 and hasattr(sel[0], 'obj') else None
        self.props.show_object(obj, self.machine)

    def on_prop_changed(self, obj):
        """The Properties panel edited `obj`: redraw it (and the navigator for a state rename)."""
        if isinstance(obj, State):
            self.scene.refresh_node(obj)
            self.build_nav()
        elif isinstance(obj, Transition):
            self.scene.refresh_transitions_from(obj.src)
        else:
            self.scene.refresh_node(obj)
        self.model_changed()

    def on_table_changed(self):
        """The Signals Table changed: redraw everything (names and texts may show signals)."""
        self.scene.refresh_all()
        self.model_changed()

    def regenerate(self):
        """Generate the HDL in memory and show it with the generator's warnings (never raises)."""
        self.log.clear()
        try:
            text, warnings = generate(self.view)
        except Exception as e:  # show generator problems instead of crashing the editor
            text, warnings = f'// Generation failed: {e}', [f'ERROR: {e}']
        self.code.set_code(text)
        ext = 'sv' if self.view.language == 'systemverilog' else 'v'
        self.code_title.setText(f'<b>Generated HDL</b> — {self.view.unit}.{ext} '
                                f'({LANG_LABEL[self.view.language]}, {self.machine.state_decl}, '
                                f'{self.machine.encoding}) — {text.count(chr(10))} lines')
        for w in warnings:
            self.log.addItem(w)
        if not warnings:
            self.log.addItem('Generation OK - no warnings')

    def update_title(self):
        """Window title as HDS writes it (project, library/unit/view, machine, '*', read-only)."""
        v = self.view
        star = ' *' if self.dirty else ''
        if self.context is not None:
            # HDS: "Project p: lib/unit/view [machine] (Read-only) (State Diagram)"; the '*' is
            # put after the names as in the block diagram title
            ro = ' (Read-only)' if self.context.readonly else ''
            self.setWindowTitle(f'Project {self.context.project_name}: {v.library}/{v.unit}/{v.view} '
                                f'[{self.machine.name}]{star}{ro} (State Diagram)')
            return
        name = os.path.basename(self.path) if self.path else 'untitled'
        self.setWindowTitle(f'{APP_NAME} — {v.library}/{v.unit}/{v.view} '
                            f'[{self.machine.name}] (State Diagram) — {name}{star}')

    def generate_hdl(self):
        """Tasks > Generate: generate this view through the project (in a project only)."""
        if self.context is not None:
            self.context.generate(self.view, self)

    # -- file operations ------------------------------------------------------------
    def _confirm_discard(self) -> bool:
        """Before losing unsaved changes: ask Save / Discard / Cancel. True when it is fine to go on."""
        if not self.dirty:
            return True
        r = QMessageBox.question(self, 'Unsaved changes',
                                 f'{self.view.unit}/{self.view.view} has been modified.\nSave the changes?',
                                 QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel, QMessageBox.Save)
        if r == QMessageBox.Save:
            self.save_file()
            return not self.dirty          # false if saving failed or was cancelled
        return r == QMessageBox.Discard

    def new_file(self):
        """File > New (standalone): start again from the example machine."""
        if self._confirm_discard():
            self.load_view(traffic_light(), None)

    def open_file(self):
        """File > Open... (standalone): open a .fsm.json file."""
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Open state machine', self._dir(),
                                              'State machine (*.fsm.json *.json)')
        if path:
            self._remember(path)
            self.load_view(FsmView.load(path), path)

    def import_file(self):
        """File > Import (standalone): open an HDS .sm file."""
        if not self._confirm_discard():
            return
        path, _ = QFileDialog.getOpenFileName(self, 'Import HDS state machine', self._dir(),
                                              'HDS state machine (*.sm)')
        if path:
            self._remember(path)
            self.open_path(path)

    def open_path(self, path: str):
        """Open a .sm (HDS) or .fsm.json file. A .sm outside a <library>/hds/<unit>/ folder asks for the
        library and unit names.
        """
        if path.endswith('.sm'):
            parts = os.path.normpath(os.path.abspath(path)).split(os.sep)
            unit = lib = None
            if not (len(parts) > 3 and parts[-3] == 'hds'):
                # loose file, not in <library>/hds/<unit>/: ask for the names
                text, ok = QInputDialog.getText(self, 'Import', 'Library.unit for this state machine:',
                                                text='work.' + os.path.splitext(parts[-1])[0])
                if not ok:
                    return
                lib, _, unit = text.strip().rpartition('.')
                lib = lib or 'work'
            view = import_sm(path, library=lib, unit=unit)
            self.load_view(view, path)          # saved back to the same .sm (HDS reads it too)
            self.statusBar().showMessage(f'Opened {path}', 5000)
        else:
            self.load_view(FsmView.load(path), path)

    def save_file(self):
        """File > Save: through the project (EditorContext.save) or, standalone, to the file the view
        came from (.sm written back with export_sm, else JSON). Clears the dirty flag.
        """
        if self.context is not None:
            if self.context.save(self.view, self, geometry=self.scene.hds_geometry):
                if self.context.view.legacy and self.context.view.path.endswith('.sm'):
                    self._reload_scene()
                self.dirty = False
                self.undo_stack.mark_clean()    # undo back to here shows no '*'
                self.update_title()
            return
        if not self.path:
            return self.save_as()
        if self.path.endswith('.sm'):
            # an HDS state diagram opened as a file: written back to it (HDS reads it too)
            from hds.export_sm import export_sm
            warn = export_sm(self.view, self.path, self.path, self.scene.hds_geometry)
            if warn:
                QMessageBox.warning(self, 'Saved with omissions',
                                    'Saved to the HDS file, but these changes could not be written yet:\n\n'
                                    + '\n'.join(warn[:15]))
            self._reload_scene()
        else:
            self.view.save(self.path)
        self.dirty = False
        self.undo_stack.mark_clean()
        self.update_title()
        self.statusBar().showMessage(f'Saved {self.path}', 4000)

    def _reload_scene(self):
        """After saving to an HDS .sm: the objects added in HDL Studio now have the ids of their
        labels in the file (hds.export_sm), so the scene is built again on them; the view
        stays where it is."""
        gv = self.scene.views()[0] if self.scene.views() else None
        center = gv.mapToScene(gv.viewport().rect().center()) if gv is not None else None
        self.scene.load(self.view, self.machine)
        if gv is not None:
            gv.centerOn(center)

    def save_as(self):
        """File > Save As... (standalone): save as a new .fsm.json file."""
        path, _ = QFileDialog.getSaveFileName(self, 'Save state machine',
                                              os.path.join(self._dir(), f'{self.view.unit}.fsm.json'),
                                              'State machine (*.fsm.json)')
        if path:
            self.path = path
            self._remember(path)
            self.save_file()

    def export_hdl(self):
        """Standalone Generate: write the generated HDL to a file chosen by the user."""
        ext = 'sv' if self.view.language == 'systemverilog' else 'v'
        path, _ = QFileDialog.getSaveFileName(self, 'Export HDL', os.path.join(self._dir(), f'{self.view.unit}.{ext}'),
                                              'Verilog/SystemVerilog (*.v *.sv)')
        if path:
            text, _ = generate(self.view)
            with open(path, 'w', encoding='utf-8', newline='\n') as f:
                f.write(text)
            self.statusBar().showMessage(f'Wrote {path}', 5000)

    def _dir(self) -> str:
        """Folder the file dialogs start in (the last one used)."""
        return QSettings('Vietsemi', 'HDL Studio').value('lastDir', os.getcwd())

    def _remember(self, path: str):
        """Remember the folder of `path` for the next file dialog."""
        QSettings('Vietsemi', 'HDL Studio').setValue('lastDir', os.path.dirname(path))

    def closeEvent(self, e):
        """Close only after unsaved changes were saved or discarded; then remember the view position
        and release the locks.
        """
        if self._confirm_discard():
            self._save_view_position()
            if self.context is not None:
                self.context.release()
            e.accept()
        else:
            e.ignore()
