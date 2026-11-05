"""Real app path, visible window: moving a net attached to an embedded block must not move the block."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _env  # noqa: E402
HDP, CFG, OUT = _env.setup()
from PySide6.QtCore import Qt, QPoint, QPointF
from PySide6.QtWidgets import QApplication
from PySide6.QtTest import QTest
app = QApplication(sys.argv)
from gui.design_manager import DesignManager
dm = DesignManager(); dm.show(); dm.load_project(HDP); app.processEvents()
lib = dm.project.library('dti_hbm'); lib.scan(dm.project.cache)
du = lib.units['dynamo_core']; dm.open_view(du, du.graphic_view()); app.processEvents()
win = next(iter(dm.editors.values())); win.resize(1400, 900); win.raise_(); win.activateWindow(); app.processEvents()
sc = win.scene; vp = win.canvas.viewport()
fails = 0
def check(ok, what):
    """Count and print one check: PASS / FAIL and its name."""
    global fails; fails += not ok; print('PASS' if ok else 'FAIL', what)
# a net with one end on an embedded block, and that block's other nets
w = next(w for w in win.bd.wires if w.start.startswith('emb:') != w.end.startswith('emb:') and len(w.points) >= 2)
which = 'start' if w.start.startswith('emb:') else 'end'
eid = (w.start if which == 'start' else w.end).split(':')[1]
eb = sc.items_by_id[eid].obj
others = {o.id: [list(q) for q in o.points] for o in win.bd.wires if o is not w and f'emb:{eid}' in (o.start, o.end)}
print('net', w.net, 'end on block', eb.name, 'other nets on block:', len(others))
def drag(p, delta):
    """Drag from viewport point p by delta, in small moves."""
    QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, p)
    for k in range(1, 6):
        QTest.mouseMove(vp, p + delta * k / 5); QTest.qWait(20)
    QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, p + delta); QTest.qWait(200)
win.canvas.resetTransform(); win.canvas.scale(2, 2)
# 1) drag the net by a point on its segment next to the block (not the end itself)
pts = w.points if which == 'start' else list(reversed(w.points))
a, b = QPointF(*pts[0]), QPointF(*pts[1])
mid = a + (b - a) * 0.5
win.canvas.centerOn(mid); app.processEvents(); QTest.qWait(200)
bx, by = eb.x, eb.y
vertical_edge = abs(a.y() - b.y()) < 0.01              # horizontal segment: the end is on a left/right edge
drag(win.canvas.mapFromScene(mid), QPoint(0, 24) if vertical_edge else QPoint(24, 0))
end = w.points[0] if which == 'start' else w.points[-1]
check((eb.x, eb.y) == (bx, by), 'dragging the net leaves the embedded block in place')
check((w.start if which == 'start' else w.end) == f'emb:{eid}', 'the net is still attached to the block')
item = sc.items_by_id[eid]
check(item.body().adjusted(-8, -8, 8, 8).contains(QPointF(*end)) and not item.body().adjusted(4, 4, -4, -4).contains(QPointF(*end)),
      f'the net end is on the block edge {end}')
check(all(o.points == others[o.id] for o in win.bd.wires if o.id in others), 'the other nets of the block did not move')
# 2) select the net and drag its end handle
sc.clearSelection(); sc.wire_items[w.id].setSelected(True); app.processEvents()
end = w.points[0] if which == 'start' else w.points[-1]
win.canvas.centerOn(QPointF(*end)); app.processEvents(); QTest.qWait(200)
bx, by = eb.x, eb.y
drag(win.canvas.mapFromScene(QPointF(*end)), QPoint(0, 24) if vertical_edge else QPoint(24, 0))
check((eb.x, eb.y) == (bx, by), 'dragging the end handle leaves the block in place')
check(all(o.points == others[o.id] for o in win.bd.wires if o.id in others), 'the other nets still did not move')
win.canvas.grab().save(os.path.join(OUT, 'embedded_nets.png'))
print('FAILS', fails)
_env.finish(fails)
