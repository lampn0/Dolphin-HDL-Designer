"""Rebuild a window's menu bar in the legacy tool's order from the actions it
already has. Entries that do not exist yet appear disabled, so the layout
matches even where the feature is not implemented."""
from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMainWindow, QMenu

from .command_names import COMMANDS


def _key(text: str) -> str:
    return text.replace('&', '').replace('...', '').strip().lower()


def arrange_menus(win: QMainWindow, spec: list[tuple[str, list]]) -> None:
    """spec: [(menu title, [item | '-' | (submenu title, [...])])]. An item is
    '@key' for a command of the window's toolbar_actions (shown under its legacy
    name) or the text of another action the window has."""
    actions: dict[str, QAction] = {}
    for a in win.findChildren(QAction):
        if a.text() and not a.isSeparator():
            actions.setdefault(_key(a.text()), a)
    commands = getattr(win, 'toolbar_actions', {})
    mb = win.menuBar()
    mb.clear()

    def fill(menu: QMenu, items: list):
        for it in items:
            if it == '-':
                menu.addSeparator()
            elif isinstance(it, tuple):
                fill(menu.addMenu(it[0]), it[1])
            else:
                a = commands.get(it[1:]) if it.startswith('@') else actions.get(_key(it))
                if a is None:
                    label = COMMANDS.get(it[1:], ('', it[1:], ''))[0] or it[1:] if it.startswith('@') else it
                    a = QAction(label, win)
                    a.setEnabled(False)
                    a.setToolTip('Not available in this version')
                menu.addAction(a)

    for title, items in spec:
        fill(mb.addMenu(title), items)


NOT_AVAILABLE = ['(not available in Dolphin HDS)']

_EDIT = ['@undo', '@redo', '-', '@cut', '@copy', '@paste', '@delete', '-', '@select_all', '-', '@find', '@replace',
         '-', '@object_props', '@edit_text']
_VIEW = ['@back', '@forward', '@open_up', '-', '@zoom_in', '@zoom_out', '@zoom_last', '@view_area', '@fit', '-',
         ('Select Mode', ['@select', '@select_text', '@select_shape']), '@pan']

FSM_MENUS = [
    ('&File', ['&New', '&Open', '&Import HDS state machine (.sm)', '-', '@save', 'Save &As', 'Save and Generate',
               '-', '@print', '-', '&Close', 'E&xit']),
    ('&Edit', _EDIT),
    ('&View', _VIEW + ['-', 'Structure Navigator', 'Properties', 'Messages']),
    ('&HDL', ['@generate_open', '@drc', '-', ('&Generate', ['@generate', '@generate_root'])]),
    ('&Diagram', ['State Machine Properties', 'Signals Table', 'Parameters Table']),
    ('&Tasks', [('&Generate', ['@generate', '@generate_root'])]),
    ('&Add', ['@state', '@hier_state', '@wait_state', '@junction_if', '@junction_case', '@link', '@transition',
              '-', '@clock', '@reset', '@enable', '@recovery', '@interrupt', '-', '@comment', '@panel']),
    ('&Simulate', NOT_AVAILABLE),
    ('A&nimation', NOT_AVAILABLE),
    ('&Options', ['Main Settings', 'Preferences']),
    ('&Window', ['Structure Navigator', 'Properties', 'Messages']),
    ('&Help', ['About Dolphin HDS']),
]

_BD_GENERATE = ['@generate', '@generate_blocks', '@generate_components', '@generate_root']
BD_MENUS = [
    ('&File', ['@save', '-', '@print', '-', '&Close']),
    ('&Edit', _EDIT + ['-', '@add_stubs', '@add_stubs_ports', '@disconnect']),
    # the legacy block diagram View menu
    ('&View', ['@fit', '@view_area', '@refresh', '@view_panel', '@zoom_in', '@zoom_out', '@zoom_last', '-', '@grid',
               '-', '@toolbars', '@status_bar', '@object_tips', '@diagram_browser', '@signals_table', '-',
               '@page_break']),
    ('&HDL', ['@generate_open', '@drc', '-', ('&Generate', _BD_GENERATE)]),
    ('&Diagram', ['Signal Table', 'Parameters Table', 'Compiler Directives', '-', '@open_down', '@open_up', '@back',
                  '@forward', '-', ('Highlight N&et', ['@highlight', '@highlight_hier']), '@clear_highlight', '-',
                  ('Select Mode', ['@select', '@select_text', '@select_shape']), '@pan']),
    ('&Tasks', [('&Generate', _BD_GENERATE)]),
    ('&Simulate', NOT_AVAILABLE),
    ('&Add', ['@block', '@component', '@moduleware', '@external_ip', '@embedded', '-', '@wire', '@wire_port',
              '@bus', '@bus_port', '@bus_ripper', '@bundle', '@bundle_ripper', '-',
              ('&Port', ['@port_in', '@port_out', '@port_inout', '@port_buffer', '@port_master', '@port_slave']),
              '@global_connector', '-', ('&Frame', ['@frame', '@frame_if', '@frame_else']), '-', '@comment',
              '@panel']),
    ('&Options', ['Main Settings', 'Preferences']),
    ('&Window', ['Properties', 'Messages']),
    ('&Help', ['About Dolphin HDS']),
]

DM_MENUS = [
    ('&File', ['New &Project', '&Open Project', 'Recent Projects', '-', 'New &Library', '&New Design Content',
               'Open HDL &File', '-', '&Close Project', 'E&xit']),
    ('&Edit', ['Cut', 'Copy', 'Paste', 'Delete', '-', 'Select All', 'Find']),
    ('&View', ['&Refresh', 'Re&load (re-read every file)', 'Explore &Library']),
    ('&HDL', ['View generated / source &HDL', '&Generate selected']),
    ('&Tasks', ['&Generate selected', 'Generate whole &library']),
    ('&Tools', ['DesignPad', 'Component Browser', 'Find']),
    ('&Options', ['&Preferences']),
    ('&Window', ['Log']),
    ('&Help', ['&About']),
]
