"""Screenshot of a HDL Studio block diagram editor window (rendered by Qt, no screen needed),
to compare with the same diagram in HDS.

    python tests/hds_gui/dolphin_shot.py <name> [scale] [x0 y0 x1 y1] [--diagram struct.bd | fsm.sm]

The window is 1617x826, the size of the HDS block diagram window on this machine; the
optional region is in window pixels. Saved as tests/hds_gui/out/<name>.png.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'src'))
from PySide6.QtCore import QRect  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'out')
args = sys.argv[1:]
diagram = 'D:/workspace/hds_reference/hds/dynamo_core/struct.bd'
if '--diagram' in args:
    k = args.index('--diagram')
    diagram = args[k + 1]
    del args[k:k + 2]
name = args[0] if args else 'dolphin'
scale = float(args[1]) if len(args) > 1 else 0.55
region = [int(v) for v in args[2:6]] if len(args) >= 6 else None

app = QApplication(sys.argv[:1])
from gui import bd_editor  # noqa: E402
from hds.import_bd import import_bd  # noqa: E402

if diagram.endswith('.sm'):
    from gui.main_window import MainWindow  # noqa: E402
    from hds.import_sm import import_sm  # noqa: E402
    win = MainWindow(import_sm(diagram))
else:
    win = bd_editor.BdEditorWindow(import_bd(diagram))
win.resize(1617, 826)
win.show()
QTest.qWait(400)
img = win.grab(QRect(*region[:2], region[2] - region[0], region[3] - region[1])) if region else win.grab()
if scale != 1:
    img = img.scaled(int(img.width() * scale), int(img.height() * scale))
os.makedirs(OUT, exist_ok=True)
path = os.path.join(OUT, name + '.png')
img.save(path)
print(path)
