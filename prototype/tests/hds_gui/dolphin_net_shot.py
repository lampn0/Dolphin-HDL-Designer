"""Draw sig0 in an empty Dolphin block diagram like the HDS check (F7, click, double-click) and
save the selected and unselected looks, at the HDS 100% scale, for comparison with HDS."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from PySide6.QtCore import QPointF, QRect, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

app = QApplication(sys.argv)
from dhds.bd_model import BlockDiagram  # noqa: E402
from dhds.gui import bd_editor  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'out')
win = bd_editor.BdEditorWindow(BlockDiagram(language='verilog'))
win.resize(1200, 800); win.show(); QTest.qWait(300)
cv, vp = win.canvas, win.canvas.viewport()
k = 75 / 72
cv.resetTransform(); cv.scale(k, k); cv.centerOn(300, 200); QTest.qWait(50)
G = bd_editor.GRID
p = lambda x, y: cv.mapFromScene(QPointF(x * G, y * G))  # noqa: E731
win.set_mode('wire')
QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, p(15, 12)); QTest.qWait(40)
QTest.mouseDClick(vp, Qt.LeftButton, Qt.NoModifier, p(27, 12)); QTest.qWait(150)
c = p(21, 12)
box = QRect(c.x() - 180, c.y() - 50, 360, 100)
vp.grab(box).save(os.path.join(OUT, 'dolphin_net_sel.png'))
win.set_mode('select'); win.scene.clearSelection(); QTest.qWait(100)
vp.grab(box).save(os.path.join(OUT, 'dolphin_net.png'))
print('selected after drawing:', [type(i).__name__ for i in win.scene.selectedItems()])
win.dirty = False
