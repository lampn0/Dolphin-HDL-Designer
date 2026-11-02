"""Start the state machine editor prototype.

    python run_fsm_editor.py                 # opens the example FSM
    python run_fsm_editor.py path/to/fsm.sm  # imports a legacy HDS state machine
    python run_fsm_editor.py my.fsm.json     # opens a saved prototype file
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from PySide6.QtWidgets import QApplication  # noqa: E402

from dhds.gui.main_window import MainWindow  # noqa: E402


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName('Dolphin HDS prototype')
    win = MainWindow()
    if len(sys.argv) > 1:
        win.open_path(sys.argv[1])
    win.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
