"""(QTest.mouseMove moves the real cursor, which another window may take: the preview is
updated directly.) Add Port In in an empty Dolphin diagram like the HDS check: the preview under the cursor,
then the port placed with a click (and the preview again at another place)."""
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
c = p(21, 12)
box = QRect(c.x() - 180, c.y() - 55, 360, 110)
win.set_mode('port_in')
QTest.mouseMove(vp, p(15, 10)); win.scene._update_ghost(QPointF(15 * G, 10 * G)); QTest.qWait(100)
vp.grab(box).save(os.path.join(OUT, 'dolphin_port_ghost.png'))
QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, p(15, 10)); QTest.qWait(100)
QTest.mouseMove(vp, p(25, 14)); win.scene._update_ghost(QPointF(25 * G, 14 * G)); QTest.qWait(100)
vp.grab(box).save(os.path.join(OUT, 'dolphin_port_placed.png'))
print('mode', win.scene.mode, 'selected', [type(i).__name__ for i in win.scene.selectedItems()],
      'names', [x.name for x in win.bd.port_ios])
win.dirty = False
