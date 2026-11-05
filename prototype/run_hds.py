"""Start the Dolphin HDS Design Manager.

    python run_hds.py                      # reopen the last session (project and windows)
    python run_hds.py path/to/project.hdp  # open a project (its last windows too, if it was the last one)
    python run_hds.py --new                # start empty, without the last session
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from dhds.gui.design_manager import DesignManager  # noqa: E402


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName('Dolphin HDS')
    dm = DesignManager()
    dm.show()
    args = [a for a in sys.argv[1:] if not a.startswith('--')]

    def start():
        if '--new' in sys.argv or not dm.prefs.restore_session:
            if args:
                dm.load_project(args[0])
        else:
            dm.restore_session(args[0] if args else '')
    QTimer.singleShot(0, start)          # paint the window first, then open the project
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
