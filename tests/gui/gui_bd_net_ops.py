"""Block diagram net operations with the real mouse, on a copy of the real project."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _env  # noqa: E402
HDP, CFG, OUT = _env.setup()
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox
from gui import bd_editor
from gui.design_manager import DesignManager

app = QApplication(sys.argv)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
dm = DesignManager(); dm.load_project(HDP)
lib = dm.project.library('protocol_controller'); lib.scan(dm.project.cache)
du = lib.units['pc_global_controller']
dm.open_view(du, du.graphic_view()); QTest.qWait(400)
w = [x for x in dm.editors.values() if isinstance(x, bd_editor.BdEditorWindow)][0]
w.resize(1600, 1000); w.show(); QTest.qWait(300)
sc, cv, vp = w.scene, w.canvas, w.canvas.viewport()
fails = 0


def ok(name, cond):
    """Count and print one check: PASS / FAIL and its name."""
    global fails
    fails += not cond
    print(('PASS ' if cond else 'FAIL ') + name, flush=True)


def ortho(pts):
    """True when every segment is horizontal or vertical."""
    return all(abs(a[0] - b[0]) < .01 or abs(a[1] - b[1]) < .01 for a, b in zip(pts, pts[1:]))


def drag(p0, p1, mods=Qt.NoModifier, steps=8):
    """Drag with the left button from the first point to the second, in small mouse moves."""
    QTest.mousePress(vp, Qt.LeftButton, mods, p0)
    for k in range(1, steps + 1):
        QTest.mouseMove(vp, p0 + (p1 - p0) * k / steps); QTest.qWait(5)
    QTest.mouseRelease(vp, Qt.LeftButton, mods, p1); QTest.qWait(50)


# 1. move a component: pin ends stay on pins, dangling connectors move along, routes stay orthogonal
inst = next(i for i in w.bd.instances if i.name == 'gc_control_fsm' or True)
inst = max(w.bd.instances, key=lambda i: sum(1 for p in i.pins if p.net))
cv.resetTransform(); cv.centerOn(inst.x + inst.w / 2, inst.y + inst.h / 2); QTest.qWait(100)
att = list(sc._attached(f'pin:{inst.id}'))
dangling = [wr for wr, which in att if not (wr.end if which == 'start' else wr.start)]
iy0 = inst.y
snap_before = {wr.id: [list(p) for p in wr.points] for wr in dangling}
c = cv.mapFromScene(inst.x + inst.w / 2, inst.y + inst.h / 2)
drag(c, c + QPoint(0, 100))
dy = 100 / cv.transform().m11()
moved_ok = all(all(abs(q[0] - p[0]) < .01 and abs(q[1] - p[1] - (inst.y - iy0)) < .01
                   for p, q in zip(snap_before[wr.id], wr.points)) for wr in dangling)
ok(f'component move: {len(dangling)} dangling nets moved along', moved_ok and dangling)
ok('component move: all attached routes orthogonal', all(ortho(wr.points) for wr, _ in att))
pins = {p.name: p for p in inst.pins}
ok('component move: pin ends still on pins', all(
    abs((wr.points[0] if which == 'start' else wr.points[-1])[1] - pins[getattr(wr, which).split(':', 2)[2]].y) < .01
    for wr, which in att))
w.act_undo.trigger(); QTest.qWait(100)

# 2. drag a whole net that has one dangling end
wr = next(x for x in w.bd.wires if bool(x.start) != bool(x.end) and len(x.points) == 2)
item = sc.wire_items[wr.id]
a, b = wr.points
mid = QPointF((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
cv.resetTransform(); cv.centerOn(mid); QTest.qWait(100)
fixed = list(wr.points[0] if wr.start else wr.points[-1])
free_before = list(wr.points[-1] if wr.start else wr.points[0])
drag(cv.mapFromScene(mid), cv.mapFromScene(mid) + QPoint(0, 40))
wr = next(x for x in w.bd.wires if x.id == wr.id)
fixed_after = wr.points[0] if wr.start else wr.points[-1]
free_after = wr.points[-1] if wr.start else wr.points[0]
moved = fixed_after[1] - fixed[1]
ok(f'net drag: the component port moved with the net ({moved:.0f})', moved >= 0 and abs(fixed_after[0] - fixed[0]) < 6)
ok(f'net drag: free end moved the same {free_before} -> {free_after}', abs(free_after[1] - free_before[1] - moved) < .01)
ok('net drag: route orthogonal', ortho(wr.points))
ok('net drag: undoable', w.act_undo.isEnabled() or moved == 0)

# 3. Alt+drag a middle segment of a multi-segment net
def alone(x, k):
    """True when segment k of net x is the topmost net under its middle (a press there is for this net)."""
    a, b = x.points[k], x.points[k + 1]
    m = QPointF((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
    # the press lands on this net: it is the topmost net there (names of nearby nets may overlap)
    ws = [i for i in sc.items(m) if isinstance(i, bd_editor.WireItem)]
    return bool(ws) and ws[0] is sc.wire_items[x.id] and not ws[0].label_rect().contains(m)
cands = [(x, j) for x in w.bd.wires for j in range(len(x.points) - 1) if alone(x, j)
         and (j > 0 or not x.start) and (j < len(x.points) - 2 or not x.end)]
cands += [(x, j) for x in w.bd.wires for j in (0,) if x.start and len(x.points) >= 3 and alone(x, 0)]
print('  candidates', len(cands))
if not cands:
    # The diagram has no multi-segment net with a free middle segment: give a net with a
    # dangling end a dog-leg route (its dangling end moves 40 units down), then use its middle.
    # Try nets until the new middle segment is not under another net.
    for wr in [x for x in w.bd.wires if bool(x.start) != bool(x.end) and len(x.points) == 2
               and abs(x.points[0][1] - x.points[1][1]) < .01]:
        if not wr.start:
            wr.points.reverse(); wr.start, wr.end = wr.end, wr.start
        (ax, ay), (bx, by) = wr.points
        mx = bd_editor._snap((ax + bx) / 2)
        old = wr.points
        wr.points = [[ax, ay], [mx, ay], [mx, ay + 40], [bx, ay + 40]]
        wr.show_text = False                # its name must not cover the segment to drag
        w._reload_scene(); QTest.qWait(50)
        if alone(wr, 1):
            cands = [(wr, 1)]
            break
        wr.points, wr.show_text = old, True
    w._reload_scene()
wr, k = cands[0]
a, b = wr.points[k], wr.points[k + 1]
vertical = abs(a[0] - b[0]) < .01
mid = QPointF((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
cv.resetTransform(); cv.centerOn(mid); QTest.qWait(100)
sc.clearSelection()
ends_before = (list(wr.points[0]), list(wr.points[-1]))
pm = cv.mapFromScene(mid)
print('  seg item at:', [type(i).__name__ + ':' + getattr(getattr(i,'obj',None),'id','') for i in cv.items(pm)][:4], 'wire', wr.id, wr.points)
drag(pm, pm + (QPoint(30, 0) if vertical else QPoint(0, 30)), Qt.AltModifier)
wr = next(x for x in w.bd.wires if x.id == wr.id)
ok('segment drag: attached ends unchanged', (not wr.start or wr.points[0] == ends_before[0]) and (not wr.end or wr.points[-1] == ends_before[1]))
print('  after', wr.points)
ok('segment drag: segment moved', any(abs(p[0] - a[0]) > 1 for p in wr.points[1:-1]) if vertical
   else any(abs(p[1] - a[1]) > 1 for p in wr.points))
ok('segment drag: orthogonal', ortho(wr.points))

# 4. double-click a net: in-place edit renames it
wr = next(x for x in w.bd.wires if x.start and x.end and len(x.points) == 2)
old = wr.net
a, b = wr.points
mid = QPointF((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
cv.resetTransform(); cv.centerOn(mid); QTest.qWait(100)
print('  dbl items at:', [type(i).__name__ + ':' + getattr(getattr(i,'obj',None),'id','') for i in cv.items(cv.mapFromScene(mid))][:4], 'wire', wr.id)
sc.edit_net_requested.connect(lambda n, pos: print('  signal', n, pos))
orig_fin = None
_sd = bd_editor.BdScene.mouseDoubleClickEvent
def sd(self, e):
    """Debug hook: print what is under a scene double-click, then do the normal handling."""
    print('  scene dbl', [type(i).__name__ for i in self.items(e.scenePos())][:3], 'grabber', self.mouseGrabberItem())
    _sd(self, e)
bd_editor.BdScene.mouseDoubleClickEvent = sd
_vd = w.canvas.mouseDoubleClickEvent
def vd(e):
    """Debug hook: print a view double-click, then do the normal handling."""
    print('  view dbl'); _vd(e)
w.canvas.mouseDoubleClickEvent = vd
QTest.mouseDClick(vp, Qt.LeftButton, Qt.NoModifier, cv.mapFromScene(mid)); QTest.qWait(100)
eds = [e for e in vp.findChildren(QLineEdit) if e.isVisible()]
print('  editors', [(e.text(), e.isVisible()) for e in vp.findChildren(QLineEdit)], 'focus', QApplication.focusWidget())
ok('double-click opens in-place editor', len(eds) == 1 and eds[0].text().startswith(old))
if eds:
    eds[0].setText(old + '_x'); QTest.keyClick(eds[0], Qt.Key_Return); QTest.qWait(100)
ok(f'in-place rename {old} -> {old}_x', any(x.net == old + '_x' for x in w.bd.wires)
   and not any(x.net == old for x in w.bd.wires) and any(s.name == old + '_x' for s in w.bd.signals))
text, _ = bd_editor.generate_bd(w.bd)
ok('generated HDL uses new name', f'{old}_x' in text)
w.dirty = False
_env.finish(fails)
