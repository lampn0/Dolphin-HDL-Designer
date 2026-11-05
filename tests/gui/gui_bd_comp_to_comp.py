"""A net between two components: both ports slide when the net is dragged; components stay."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _env  # noqa: E402
HDP, CFG, OUT = _env.setup()
from PySide6.QtCore import QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from bd_model import BlockDiagram, BdInstance, BdPin, BdWire
from model import Signal
from gui import bd_editor
app = QApplication(sys.argv)
fails = 0


def ok(name, cond):
    """Count and print one check: PASS / FAIL and its name."""
    global fails
    fails += not cond
    print(('PASS ' if cond else 'FAIL ') + name, flush=True)
bd = BlockDiagram(unit='t')
a = BdInstance('i1', 'u_a', 'work', 'a', x=0, y=0, w=120, h=200, pins=[BdPin('o', 'output', 'n', 0, 120, 60, 'right')])
b = BdInstance('i2', 'u_b', 'work', 'b', x=400, y=0, w=120, h=200, pins=[BdPin('i', 'input', 'n', 0, 400, 100, 'left')])
bd.instances = [a, b]; bd.signals = [Signal('n', 'local', 'wire')]
bd.wires = [BdWire('w1', 'n', [[120, 60], [260, 60], [260, 100], [400, 100]], 'pin:i1:o', 'pin:i2:i')]
w = bd_editor.BdEditorWindow(bd); w.resize(1200, 800); w.show(); QTest.qWait(300)
cv, vp = w.canvas, w.canvas.viewport()
cv.resetTransform(); cv.centerOn(260, 80); QTest.qWait(100)
p0 = cv.mapFromScene(QPointF(190, 60)); p1 = cv.mapFromScene(QPointF(190, 100))
QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, p0)
for k in range(1, 9):
    QTest.mouseMove(vp, p0 + (p1 - p0) * k / 8); QTest.qWait(5)
QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, p1); QTest.qWait(80)
wr = w.bd.wires[0]
print('  pins', a.pins[0].y, b.pins[0].y, wr.points)
ok(f'both ports moved down onto the grid ({a.pins[0].y:.1f}, {b.pins[0].y:.1f})', a.pins[0].y > 60 and b.pins[0].y > 100)
ok('components stayed', (a.y, b.y) == (0, 0))
ok('net joins both ports, orthogonal', wr.points[0] == bd_editor.pin_end(a.pins[0]) and wr.points[-1] == bd_editor.pin_end(b.pins[0])
   and all(abs(p[0] - q[0]) < .01 or abs(p[1] - q[1]) < .01 for p, q in zip(wr.points, wr.points[1:])))
w.dirty = False
_env.finish(fails)
