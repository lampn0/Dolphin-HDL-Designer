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
    name), '!text' for a disabled placeholder, or the text of another action the
    window has (a disabled placeholder when there is none)."""
    actions: dict[str, QAction] = {}
    for a in win.findChildren(QAction):
        # actions owned by the old menus die with them when the menu bar is cleared below
        if a.text() and not a.isSeparator() and not isinstance(a.parent(), QMenu):
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
            elif it.startswith('!'):
                # '!text': a placeholder only, even when another action has the same name
                # (e.g. Diagram > Panels > Print... is not the diagram's Print...)
                a = QAction(it[1:], win)
                a.setEnabled(False)
                a.setToolTip('Not available in this version')
                menu.addAction(a)
            else:
                a = commands.get(it[1:]) if it.startswith('@') else actions.get(_key(it))
                if a is None:
                    label = COMMANDS.get(it[1:], ('', it[1:], ''))[0] or it[1:] if it.startswith('@') else it
                    a = QAction(label, win)
                    a.setEnabled(False)
                    a.setToolTip('Not available in this version')
                menu.addAction(a)

    for title, items in spec:
        menu = mb.addMenu(title)
        fill(menu, items)
        # entries that act on the selection are enabled when their menu opens
        if hasattr(win, 'update_menu_states'):
            menu.aboutToShow.connect(win.update_menu_states)


NOT_AVAILABLE = ['(not available in Dolphin HDS)']

_EDIT = ['@undo', '@redo', '-', '@cut', '@copy', '@paste', '@delete', '-', '@select_all', '-', '@find', '@replace',
         '-', '@object_props', '@edit_text']
_VIEW = ['@back', '@forward', '@open_up', '-', '@zoom_in', '@zoom_out', '@zoom_last', '@view_area', '@fit', '-',
         ('Select Mode', ['@select', '@select_text', '@select_shape']), '@pan']

def fsm_menus(standalone: bool = False) -> list:
    """The state diagram editor menus, entry for entry as HDS 2021.1 shows them (read from the
    running HDS, saved in tests/hds_gui/ref/fsm_menus_hds.txt); VHDL-only entries and the
    third-party tool flows are left out, as for BD_MENUS. Outside a project (standalone) the
    File menu also has Dolphin's own New / Open / Import commands."""
    own = ['-', 'New', 'Open...', 'Import HDS state machine (.sm)...'] if standalone else []
    return [
        ('&File', [('&New', ['Design Content...', 'Test Bench...']),
                   ('&Open', ['@open_up', '!Interface', '!Down']),
                   '@save', 'Save As...', 'Save Title Block', '-', 'Refresh Page Boundaries', '-', '@page_setup',
                   'Print Window...', '@print', '-',
                   ('Document And Visualize', ['Single Level', 'Hierarchy Through Components',
                                               'Through Design Root'])] + own + ['-', '@close_window', '@exit']),
        ('&Edit', ['@undo', '@redo', '-', '@cut', '@copy', '@paste',
                   ('Paste Special', ['Paste from system clipboard']), '@delete', '-', '@select_all', '-', '@find',
                   '-', 'Appearance...',
                   ('Align', ['Align Left', 'Align Center', 'Align Right', 'Align Top', 'Align Middle',
                              'Align Bottom', '-', 'Distribute Horizontally', 'Distribute Vertically']),
                   ('Group', ['Group', 'UnGroup']), ('Rotate', ['90', '180', '270']),
                   ('Flip', ['Vertical', 'Horizontal']), '-', 'Expression Builder', '@object_props']),
        ('&View', ['@fit', '@view_area', '@refresh', 'View Panel', '@zoom_in', '@zoom_out', '@zoom_last', '-',
                   '@grid', 'Snap to Grid', '-', '@toolbars', '@status_bar', 'Object Tips', '@diagram_browser',
                   '@signals_table']),
        ('&HDL', ['@generate_open', 'Black box for Synthesis']),
        ('&Diagram', ['Copy Picture', '@compiler_directives', '-', 'Reverse Direction',
                      ('Change To', ['!State', '!Hierarchical State', '!Junction', '!Interrupt Point',
                                     '!Entry Point', '!Link', '!Exit Point']),
                      ('Text', ['Show Text', 'Hide Text', 'Send to Editor', 'Finish Edit', 'Finish All Edits',
                                ('Allow Visual Change', ['Yes', 'No'])]),
                      ('Comment Graphics', ['Hide', 'Show All']),
                      ('Panels', ['Delete Panel', 'Show Panel', '!Print...', 'Protect All Panels',
                                  '!Object Properties']),
                      '-', ('Re-level', ['Add hierarchy', 'Remove hierarchy']), 'Rename Concurrent Machine...',
                      '@sm_props']),
        ('&Tasks', ['Set Generate Always', '-', ('&Generate', ['@generate', '@generate_root'])]),
        ('&Add', ['Input Port', 'Output Port', 'InOut Port', 'Local Signal', 'Concurrent State Machine', '-',
                  '@clock', '@reset', '@recovery', '@enable', '-', '@state', '@transition', '@interrupt',
                  '@link', '@junction_if', '@junction_case', '@hier_state', '@wait_state', '-',
                  '!Comment Text', '@panel',
                  ('Comment Graphics', ['Line', 'Polyline', 'Polygon', 'Arc', 'Rectangle', 'Ellipse', 'Circle',
                                        'Bitmap...']),
                  'Title Block']),
        ('&Simulate', NOT_AVAILABLE),           # HDS puts Add before Simulate in this window
        ('A&nimation', NOT_AVAILABLE),
        ('&Options', ['@main_settings', '@verilog_options', 'Diagram Preferences...',
                      ('Master Preferences', ['Apply to New Objects', 'Apply to New and Existing Objects',
                                              'Update from Diagram'])]),
        ('&Window', ['@log_window', 'Task Log Window', '@design_manager', 'Component Browser']),
        ('&Help', ['@shortcuts_help', '-', 'About Dolphin HDS']),
    ]


FSM_MENUS = fsm_menus()

_BD_GENERATE = ['@generate', '@generate_blocks', '@generate_components', '@generate_root']

# The block diagram editor menus, entry for entry as HDS 2021.1 shows them (read from the
# running HDS with tests/hds_gui/hds.py, saved in tests/hds_gui/ref/bd_menus_hds.txt).
# VHDL-only entries and the third-party tool flows (ModelSim, Precision, DesignChecker,
# SVAssistant) are left out: Dolphin HDS is for Verilog / SystemVerilog only. Entries Dolphin
# cannot do yet are plain text: they are shown greyed out at their HDS place.
_ON_OFF = ['On', 'Off']
_SHOW_HIDE_EDIT = ['Show', 'Hide', 'Edit...']
BD_MENUS = [
    ('&File', [('&New', ['Design Content...', 'Test Bench...']),
               ('&Open', ['@open_up', '!Interface']),
               '@save', 'Save Title Block', '-', 'Refresh Page Boundaries', '-', '@page_setup', 'Print Window...',
               '@print', '-', ('Document And Visualize', ['Single Level', 'Hierarchy Through Components',
                                                          'Through Design Root']),
               '-', '@close_window', '@exit']),
    ('&Edit', ['@undo', '@redo', '-', '@cut', '@copy', '@paste',
               ('Paste Special', ['Paste from system clipboard']), '@delete', '-', '@select_all', '-', '@find',
               '@replace', '-', 'Appearance...',
               ('Align', ['Align Left', 'Align Center', 'Align Right', 'Align Top', 'Align Middle', 'Align Bottom',
                          '-', 'Distribute Horizontally', 'Distribute Vertically']),
               ('Group', ['Group', 'UnGroup']), ('Rotate', ['90', '180', '270']),
               ('Flip', ['Vertical', 'Horizontal']), '-', '@object_props']),
    ('&View', ['@fit', '@view_area', '@refresh', '@view_panel', '@zoom_in', '@zoom_out', '@zoom_last', '-', '@grid',
               '-', '@toolbars', '@status_bar', '@object_tips', '@diagram_browser', '@signals_table', '-',
               '@page_break']),
    ('&HDL', ['@generate_open', 'Black box for Synthesis']),
    ('&Diagram', ['Copy Picture', '@compiler_directives', '-',
                  ('Ports', [('Change Mode', ['@port_mode_in', '@port_mode_out', '@port_mode_inout']),
                             ('Clock', _ON_OFF), ('Not', _ON_OFF), ('Ordering', ['Automatic', 'Manual']),
                             ('Attributes', _SHOW_HIDE_EDIT), ('Comments', _SHOW_HIDE_EDIT),
                             '@equidistant']),
                  ('Signals', [('Ordering', ['Automatic', 'Manual']),
                               ('Comments', ['Show', 'Hide', '@net_comment']), ('Attributes', _SHOW_HIDE_EDIT),
                               ('Highlight Net', ['@net_highlight', '!Hierarchical...', '-', '@net_clear_highlight']),
                               ('Insert Net', ['Single Level Up...', 'Single Level Down...', 'Hierarchical...']),
                               ('Remove Net', ['Single Level Up...', 'Single Level Down...', 'Hierarchical...']),
                               ('Scope For Changes', ['Joined Wires in this diagram', 'Entire Net in diagram',
                                                      'Entire Net in hierarchy']),
                               '@net_change_style', '@net_add_port_io']),
                  ('Text', ['@text_show', '@text_hide', ('Rotate Text', ['90', '180', '270']), 'Send to Editor',
                            'Finish Edit', 'Finish All Edits', ('Allow Visual Change', ['Yes', 'No'])]),
                  ('Comment Graphics', ['Hide', 'Show All']),
                  ('Panels', ['Delete Panel', 'Show Panel', '!Print...', 'Protect All Panels',
                              '!Object Properties']),
                  '-', '@connect', '@disconnect', '@add_stubs', '@add_stubs_ports', 'Automatic Instance Names',
                  ('Port Map Frame', ['@portmap_enable', '@portmap_disable', '@portmap_edit']),
                  ('Shape', ['Editing Shape', 'Autowhisker', 'Autoshapes...']),
                  ('Autoroute', ['Autoconnect', 'Autobundle', 'Connect By Name', '!Autoroute',
                                 'Autoroute Options...']),
                  'Layout Diagram', 'Layout/Routing Options...', '-',
                  ('Update', ['@update_interface', 'Interface and Graphics', 'From Symbol', 'Graphics To Symbol']),
                  ('Re-level', ['Remove Hierarchy...', 'Add Hierarchy...']), '-', '@check_design',
                  'Design Checking Options...']),
    ('&Tasks', ['Set Generate Always', '-', ('&Generate', _BD_GENERATE)]),
    ('&Simulate', NOT_AVAILABLE),
    ('&Add', ['@block', '@component', '@moduleware', '@external_ip', '@embedded',
              ('&Frame', ['@frame', '@frame_if', '@frame_else']), '-', '@wire', '@bus', '@bundle',
              '@global_connector', '-', '@port_in', '@port_out', '@port_inout', '-', '!Comment Text', '@panel',
              ('Comment Graphics', ['Line', 'Polyline', 'Polygon', 'Arc', 'Rectangle', 'Ellipse', 'Circle',
                                    'Bitmap...']),
              'Title Block']),
    ('&Options', ['@main_settings', '@verilog_options', 'Diagram Preferences...',
                  ('Master Preferences', ['Apply to New Objects', 'Apply to New and Existing Objects',
                                          'Update from Diagram'])]),
    ('&Window', ['@log_window', 'Task Log Window', '@design_manager', 'Component Browser']),
    ('&Help', ['@shortcuts_help', '-', 'About Dolphin HDS']),
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
