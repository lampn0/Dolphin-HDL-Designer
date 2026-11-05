"""Transitions of the state diagram editor as in HDS 2021.1 (watched on the real HDS with
tests/hds_gui/hds.py): a drag on the line itself moves nothing; route points come from the
right-click menu (Add Route / Remove Route / Remove All Routes / Reverse Direction) and the
line is a smooth curve through them; an end handle dropped on another state reconnects the
transition there; the line from a text box to its transition shows only while the box is
selected. Runs on the UART diagram made with HDS (D:/workspace/uart_hds), read only."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _env  # noqa: E402
HDP, CFG, OUT = _env.setup()
from PySide6.QtCore import QPointF, Qt  # noqa: E402
from PySide6.QtGui import QPainterPath  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402
from dhds.gui.main_window import MainWindow  # noqa: E402
from dhds.hds.import_sm import import_sm  # noqa: E402

SM = os.environ.get('DHDS_UART_SM', 'D:/workspace/uart_hds/uart_lib/hds/uart_tx/fsm.sm')
app = QApplication(sys.argv)
fails = 0


def ok(name, cond):
    global fails
    fails += not cond
    print(('PASS ' if cond else 'FAIL ') + name, flush=True)


win = MainWindow(import_sm(SM)); win.resize(1400, 900); win.show(); QTest.qWait(300)
sc, cv, vp = win.scene, win.canvas, win.canvas.viewport()
m = win.machine
by = {s.name: s for s in m.states}
t = next(x for x in m.transitions if x.src == by['START'].id and x.dst == by['DATA'].id)
it = sc.trans_items[t.id]


def drag(a: QPointF, b: QPointF):
    cv.centerOn(a); QTest.qWait(30)
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, cv.mapFromScene(a))
    for k in range(1, 7):
        QTest.mouseMove(vp, cv.mapFromScene(a + (b - a) * (k / 6))); QTest.qWait(10)
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, cv.mapFromScene(b)); QTest.qWait(80)


# 1. a drag on the middle of the line: nothing moves, no route point appears
a, b = it.ends
mid = (a + b) / 2 + QPointF(-25, 0)
drag(mid, mid + QPointF(0, 60))
ok('a drag on the line adds no route point', t.points == [])

# 2. Add Route, then the route point moves and the line is a curve through it
it = sc.trans_items[t.id]
it.add_route(mid)
ok('Add Route adds a route point', len(t.points) == 1)
it = sc.trans_items[t.id]; it.setSelected(True)
rp = QPointF(*t.points[0])
drag(rp, rp + QPointF(0, 60))
it = sc.trans_items[t.id]
ok(f'the route point is dragged ({t.points})', t.points and t.points[0][1] > rp.y() + 30)
el = [it.path().elementAt(k).type for k in range(it.path().elementCount())]
ok('the line is a curve through it (cubic segments)', QPainterPath.ElementType.CurveToElement in el)
it.remove_all_routes()
ok('Remove All Routes', t.points == [])

# 3. the end handle dropped on STOP reconnects the transition there
it = sc.trans_items[t.id]
sc.clearSelection(); it.setSelected(True)
end = it.ends[1]
stop = QPointF(by['STOP'].x, by['STOP'].y)
drag(end, stop)
ok(f'the end dropped on STOP reconnects it ({t.dst == by["STOP"].id})', t.dst == by['STOP'].id)

# 4. Reverse Direction swaps source and destination
it = sc.trans_items[t.id]
it.reverse()
ok('Reverse Direction', t.src == by['STOP'].id and t.dst == by['START'].id)

# 5. the line from a box to its transition only while the box is selected
lab = sc.trans_items[t.id].label
sc.clearSelection(); sc.update_leader(lab)
line = sc.leaders.get(id(lab))
ok('no line from an unselected box', line is None or not line.isVisible())
lab.setSelected(True); sc.update_leader(lab)
line = sc.leaders.get(id(lab))
ok('a red line from the selected box', line is not None and line.isVisible())

# 6. the declaration blocks are on the diagram
from dhds.gui.diagram import DeclBlockItem  # noqa: E402
blocks = {i.key for i in sc.items() if isinstance(i, DeclBlockItem)}
ok(f'declaration blocks drawn ({sorted(blocks)})', blocks == set(DeclBlockItem.KEYS))
status = next(i for i in sc.items() if isinstance(i, DeclBlockItem) and i.key == 'status')
rows = [r[1] for r in status.rows()]
ok('Signal Status lists the clocked locals', any(r.startswith('shift_reg') and 'CLKD' in r for r in rows))
cv.grab().save(os.path.join(OUT, 'fsm_transitions.png'))
print('FAILS', fails)
win.dirty = False
win.close()
sys.exit(1 if fails else 0)
