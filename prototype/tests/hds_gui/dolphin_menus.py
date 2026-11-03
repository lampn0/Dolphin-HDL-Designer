"""Dump the menus of a Dolphin HDS editor window as text, in the format hds.py uses for HDS, so
the two can be compared with diff.

    python tests/hds_gui/dolphin_menus.py bd [struct.bd]  > tests/hds_gui/ref/bd_menus_dolphin.txt
    python tests/hds_gui/dolphin_menus.py fsm [fsm.sm]    > tests/hds_gui/ref/fsm_menus_dolphin.txt

Default diagrams come from the sample project D:/workspace/hds_reference.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

SAMPLE = 'D:/workspace/hds_reference'


def dump(menu: QMenu, depth: int, out: list):
    """Menu entries one per line, indented two spaces per level; shortcut after a tab and
    "(disabled)" as hds.py prints them; separators are skipped (win32 menus hide them too)."""
    for a in menu.actions():
        if a.isSeparator() or not a.text():
            continue
        text = a.text().replace('&', '')
        sc = a.shortcut().toString()
        line = '  ' * depth + text + (f'\t{sc}' if sc else '')
        if not a.isEnabled():
            line += '  (disabled)'
        out.append(line)
        if a.menu() is not None:
            dump(a.menu(), depth + 1, out)


def main():
    kind = sys.argv[1] if len(sys.argv) > 1 else 'bd'
    app = QApplication(sys.argv[:1])  # noqa: F841
    if kind == 'bd':
        from dhds.gui import bd_editor
        from dhds.hds.import_bd import import_bd
        path = sys.argv[2] if len(sys.argv) > 2 else f'{SAMPLE}/hds/dynamo_core/struct.bd'
        win = bd_editor.BdEditorWindow(import_bd(path))
    else:
        from dhds.gui import main_window
        from dhds.hds.import_sm import import_sm
        path = sys.argv[2] if len(sys.argv) > 2 else None
        win = main_window.MainWindow(import_sm(path)) if path else main_window.MainWindow()
    out = []
    for a in win.menuBar().actions():
        out.append(a.text().replace('&', ''))
        if a.menu() is not None:
            dump(a.menu(), 1, out)
    sys.stdout.write('\n'.join(out) + '\n')


if __name__ == '__main__':
    main()
