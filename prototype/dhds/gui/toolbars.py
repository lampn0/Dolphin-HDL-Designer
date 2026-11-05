"""Main toolbars laid out in the legacy tool's order. Each entry refers to an
action the editor already has (by key); missing ones are shown disabled.
Entries given as a list become a button with a drop-down menu (first = default)."""
from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import QMainWindow, QMenu, QToolBar, QToolButton

from .command_names import COMMANDS
from .icons import icon

FSM_TOOLBAR = [
    ('new', 'New'), ('back', 'Back'), ('forward', 'Forward'), ('open_up', 'Open Up'), ('save', 'Save'),
    ('print', 'Print'), '|', ('cut', 'Cut'), ('copy', 'Copy'), ('paste', 'Paste'), '|', ('undo', 'Undo'),
    ('redo', 'Redo'), '|', ('find', 'Find'), ('object_props', 'Object Properties'), '|', ('zoom_in', 'Zoom In'),
    ('zoom_out', 'Zoom Out'), ('view_area', 'View Area'), ('fit', 'View All'), '|',
    [('select', 'Select'), ('select_text', 'Select Text'), ('select_shape', 'Select Shape')], ('pan', 'Panning'), '|',
    ('clock', 'Add Clock'), ('reset', 'Add Reset'), ('recovery', 'Add Recovery State Point'), ('enable', 'Add Enable'),
    '|', ('state', 'Add State'), ('transition', 'Add Transition'), ('interrupt', 'Add Interrupt Point'),
    ('link', 'Add Link'), [('junction_if', 'Add Junction (IF)'), ('junction_case', 'Add Junction (CASE)')], '|',
    ('hier_state', 'Add Hierarchical State'), ('wait_state', 'Add Wait State'), ('comment', 'Add Comment Text'),
    ('panel', 'Add Panel'), '|', ('generate_open', 'View Generated HDL'), ('drc', 'Run Design Rule Checks'), '|',
    [('generate', 'Generate (single)'), ('generate_root', 'Generate (through design root)')],
]

BD_TOOLBAR = [
    ('new', 'New'), ('back', 'Back'), ('forward', 'Forward'), ('open_up', 'Open Up'), ('save', 'Save'),
    ('print', 'Print'), '|', ('cut', 'Cut'), ('copy', 'Copy'), ('paste', 'Paste'), '|', ('undo', 'Undo'),
    ('redo', 'Redo'), '|', ('find', 'Find'), ('object_props', 'Object Properties'), '|', ('zoom_in', 'Zoom In'),
    ('zoom_out', 'Zoom Out'), ('view_area', 'View Area'), ('fit', 'View All'), '|',
    [('select', 'Select'), ('select_text', 'Select Text'), ('select_shape', 'Select Shape')], ('pan', 'Panning'), '|',
    [('highlight', 'Highlight Net (in diagram)'), ('highlight_hier', 'Highlight Net (in hierarchy)')],
    ('clear_highlight', 'Clear Net Highlighting'), '|',
    ('block', 'Add Block'), ('component', 'Add Component'), ('moduleware', 'Add ModuleWare'),
    ('external_ip', 'Add External IP'), ('embedded', 'Add Embedded Block'),
    [('frame', 'Add Frame (FOR)'), ('frame_if', 'Add Frame (IF)'), ('frame_else', 'Add Frame (ELSE)')], '|',
    [('wire', 'Add Signal'), ('wire_port', 'Add Signal with a Port')],
    [('bus', 'Add Bus'), ('bus_port', 'Add Bus with a Port'), ('bus_ripper', 'Add Bus with a Ripper')],
    [('bundle', 'Add Bundle'), ('bundle_ripper', 'Add Bundle with a Ripper')],
    [('port_in', 'Add Port In'), ('port_out', 'Add Port Out'), ('port_inout', 'Add Port Inout'),
     ('port_buffer', 'Add Port Buffer'), ('port_master', 'Add Port Master'), ('port_slave', 'Add Port Slave')],
    ('global_connector', 'Add Global Connector'), '|', ('comment', 'Add Comment Text'), ('panel', 'Add Panel'), '|',
    ('generate_open', 'View Generated HDL'), ('drc', 'Run Design Rule Checks'), '|',
    [('generate', 'Generate (single)'), ('generate_blocks', 'Generate (through blocks)'),
     ('generate_components', 'Generate (through components)'), ('generate_root', 'Generate (through design root)')],
]

# Shortcuts and mnemonic keys of the legacy editors (Graphical Editors User Manual,
# "Diagram View Editing", "State Diagram" and "Block Diagram" command tables).
COMMON_KEYS = {
    'save': ['Ctrl+S'], 'print': ['Ctrl+P'], 'open_up': ['Ctrl+Shift+O'], 'cut': ['Ctrl+X'], 'copy': ['Ctrl+C'],
    'paste': ['Ctrl+V'], 'delete': ['Del', 'Backspace'], 'select_all': ['Ctrl+A'], 'undo': ['Ctrl+Z'],
    'redo': ['Ctrl+Y'], 'find': ['Ctrl+F'], 'replace': ['Ctrl+H'], 'object_props': ['Alt+Return'],
    'edit_text': ['F2'], 'zoom_in': ['Shift+Up', 'Ctrl++'], 'zoom_out': ['Shift+Down', 'Ctrl+-'],
    'view_area': ['Shift+Home'], 'fit': ['Home'], 'select': ['Esc'], 'generate_open': ['Ctrl+G'],
    'generate': ['Shift+G'],
}
FSM_KEYS = {
    **COMMON_KEYS, 'state': ['F3', 'S'], 'hier_state': ['Shift+F2', 'H'], 'interrupt': ['I'],
    'link': ['F4', 'L'], 'junction_if': ['J'], 'transition': ['F7', 'T'],
    'wait_state': ['Ctrl+F3', 'W'],          # as HDS 2021.1 shows it in Add (F8 is Input Port there)
}
BD_KEYS = {
    **COMMON_KEYS, 'block': ['Ctrl+F3', 'B'], 'component': ['F3', 'C'], 'embedded': ['F4', 'E'],
    'wire': ['F7', 'S'], 'bus': ['Shift+F7', 'U'], 'bundle': ['Ctrl+F7', 'N'], 'port_in': ['F8', 'I'],
    # Port Out / Port InOut keys as HDS 2021.1 shows them in its Add menu; Global Connector has
    # no function key there (F5 is View > Refresh)
    'port_out': ['Shift+F8', 'O'], 'port_inout': ['F9', 'T'], 'port_buffer': ['F'],
    'global_connector': ['G'], 'frame': ['F6'], 'frame_if': ['Shift+F6'], 'frame_else': ['Alt+F6'],
    'add_stubs': ['Ctrl+F10'], 'add_stubs_ports': ['Shift+F10'], 'disconnect': ['Shift+Alt+C'],
    'open_down': ['Ctrl+D'],
}

# menu labels that must tell drop-down entries apart
_LABELS = {'junction_if': 'Junction (&IF)', 'junction_case': 'Junction (&CASE)', 'generate': '&Single',
           'generate_blocks': 'Through &Blocks', 'generate_components': 'Through &Components',
           'generate_root': 'Through Design &Root', 'highlight': 'Highlight Net (in &diagram)',
           'highlight_hier': 'Highlight Net (in &hierarchy)', 'clear_highlight': 'Clear Net &Highlighting'}


def apply_names(actions: dict[str, QAction], keys: dict[str, list[str]]) -> None:
    """Give every action its legacy menu label, tooltip, status-bar text and shortcuts."""
    for key, a in actions.items():
        menu, tip, desc = COMMANDS.get(key, ('', '', ''))
        label = _LABELS.get(key) or menu or tip
        if label:
            a.setText(label)
        if key in keys:
            a.setShortcuts([QKeySequence(k) for k in keys[key]])
        tip = tip or label.replace('&', '').replace('...', '')
        shortcut = ', '.join(QKeySequence(k).toString(QKeySequence.NativeText) for k in keys.get(key, []))
        if a.isEnabled():
            a.setToolTip(f'{tip} ({shortcut})' if shortcut else tip)
        if desc:
            a.setStatusTip(desc)


# icon to draw for keys that reuse another key's picture
_ICON_ALIAS = {'select_text': 'select', 'select_shape': 'select', 'highlight_hier': 'highlight',
               'frame_if': 'frame', 'frame_else': 'frame', 'wire_port': 'wire', 'bus_port': 'bus',
               'bus_ripper': 'bus', 'bundle_ripper': 'bundle', 'port_inout': 'port_in', 'port_buffer': 'port_out',
               'port_master': 'port_out', 'port_slave': 'port_in', 'generate_root': 'generate',
               'generate_blocks': 'generate', 'generate_components': 'generate'}


def _action(win: QMainWindow, actions: dict[str, QAction], key: str, text: str) -> QAction:
    a = actions.get(key)
    if a is None:
        a = QAction(text, win)
        a.setEnabled(False)
        a.setToolTip(f'{text} (not available in this version)')
        a.setStatusTip(f'{text}: not available in this version')
        actions[key] = a
    a.setIcon(icon(_ICON_ALIAS.get(key, key)))
    if not a.toolTip() or a.toolTip() == a.text():
        a.setToolTip(text)
    return a


def build_toolbar(win: QMainWindow, actions: dict[str, QAction], spec: list,
                  keys: dict[str, list[str]] | None = None) -> QToolBar:
    tb = QToolBar('Main')
    tb.setObjectName('main_toolbar')
    tb.setIconSize(QSize(20, 20))
    win.addToolBar(tb)
    for entry in spec:
        if entry == '|':
            tb.addSeparator()
        elif isinstance(entry, list):
            items = [_action(win, actions, k, t) for k, t in entry]
            btn = QToolButton()
            menu = QMenu(btn)
            for a in items:
                menu.addAction(a)
            btn.setMenu(menu)
            btn.setPopupMode(QToolButton.MenuButtonPopup)
            btn.setDefaultAction(items[0])
            # the button shows the last item picked from its menu, as in the legacy tool
            menu.triggered.connect(btn.setDefaultAction)
            tb.addWidget(btn)
        else:
            tb.addAction(_action(win, actions, *entry))
    apply_names(actions, keys or COMMON_KEYS)
    return tb
