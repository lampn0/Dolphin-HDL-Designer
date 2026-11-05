"""Render a region of an HDS state diagram as HDL Studio draws it, to compare with HDS.

    python tests/hds_gui/dolphin_fsm_region.py fsm.sm name x0 y0 x1 y1 [px_per_unit]

The region is in HDS units (as in the .sm file); px_per_unit defaults to 1/72 (HDS 100%
zoom on this machine). Saved as tests/hds_gui/out/<name>.png. Read only.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'src'))
from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QImage, QPainter  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv[:1])
from gui.main_window import MainWindow  # noqa: E402
from hds.import_sm import import_sm  # noqa: E402

path, name = sys.argv[1], sys.argv[2]
x0, y0, x1, y1 = (float(v) for v in sys.argv[3:7])
ppu = float(sys.argv[7]) if len(sys.argv) > 7 else 1 / 72
win = MainWindow(import_sm(path))
src = QRectF(x0 / 75, y0 / 75, (x1 - x0) / 75, (y1 - y0) / 75)
img = QImage(int((x1 - x0) * ppu), int((y1 - y0) * ppu), QImage.Format_RGB32)
img.fill(Qt.white)
p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing)
p.setRenderHint(QPainter.TextAntialiasing)
win.scene.render(p, QRectF(img.rect()), src)
p.end()
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'out', name + '.png')
img.save(out)
win.dirty = False
print(out)
