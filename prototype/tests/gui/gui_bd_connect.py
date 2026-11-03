"""Ports follow components, port/net connection by dragging, inline edit cancel, popup menus."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _env  # noqa: E402
HDP, CFG, OUT = _env.setup()
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QMenu, QMessageBox
from dhds.gui import bd_editor
from dhds.gui.design_manager import DesignManager
from dhds.bd_model import BdPortIo

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
    global fails
    fails += not cond
    print(('PASS ' if cond else 'FAIL ') + name, flush=True)
ortho = lambda pts: all(abs(a[0] - b[0]) < .01 or abs(a[1] - b[1]) < .01 for a, b in zip(pts, pts[1:]))


def drag(p0, p1, mods=Qt.NoModifier, steps=8):
    QTest.mousePress(vp, Qt.LeftButton, mods, p0)
    for k in range(1, steps + 1):
        QTest.mouseMove(vp, p0 + (p1 - p0) * k / steps); QTest.qWait(5)
    QTest.mouseRelease(vp, Qt.LeftButton, mods, p1); QTest.qWait(80)


def end_of(wr, which):
    return wr.points[0] if which == 'start' else wr.points[-1]


# 0. port icons touch their nets
gaps = [(p.name, end_of(wr, which), sc.port_edge(p)) for p in w.bd.port_ios for wr, which in sc._attached(f'pio:{p.id}')
        if abs(end_of(wr, which)[0] - sc.port_edge(p)[0]) > .01 or abs(end_of(wr, which)[1] - p.y) > .01]
ok(f'port icons touch their nets ({len(w.bd.port_ios)} ports, gaps: {gaps[:2]})', not gaps)

# 1. move a component: ports on its nets and dangling connectors come along; nets to other components stretch
inst = max(w.bd.instances, key=lambda i: sum(1 for wr, which in sc._attached(f'pin:{i.id}')
                                             if (wr.end if which == 'start' else wr.start).startswith('pio:')))
att = list(sc._attached(f'pin:{inst.id}'))
ports = {sc.owner_of(wr.end if which == 'start' else wr.start).obj.id: None for wr, which in att
         if (wr.end if which == 'start' else wr.start).startswith('pio:')}
pos0 = {p.id: (p.x, p.y) for p in w.bd.port_ios if p.id in ports}
others = [(wr, which) for wr, which in att if (wr.end if which == 'start' else wr.start).startswith(('pin:', 'emb:'))]
cv.resetTransform(); cv.centerOn(inst.x + inst.w / 2, inst.y + inst.h / 2); QTest.qWait(100)
sc.clearSelection(); iy0 = inst.y
c = cv.mapFromScene(inst.x + inst.w / 2, inst.y + inst.h / 2)
drag(c, c + QPoint(0, 60))
moved = {pid: (p.x - pos0[pid][0], p.y - pos0[pid][1]) for p in w.bd.port_ios for pid in [p.id] if pid in pos0}
ok(f'component move: {len(moved)} ports moved along {set(moved.values())}', moved and all(abs(dx) < 1e-6 and abs(dy - (inst.y - iy0)) < 1e-6 for dx, dy in moved.values()))
ok('component move: port nets still touch the ports', all(
    abs(end_of(wr, wh)[0] - sc.port_edge(p)[0]) < .01 and abs(end_of(wr, wh)[1] - p.y) < .01
    for p in w.bd.port_ios if p.id in ports for wr, wh in sc._attached(f'pio:{p.id}')))
ok(f'component move: {len(others)} nets to other components stretch, orthogonal', all(ortho(wr.points) for wr, _ in others))
w.act_undo.trigger(); QTest.qWait(100)
ok('undo puts ports back', all((p.x, p.y) == pos0[p.id] for p in w.bd.port_ios if p.id in pos0))

# 2. inline edit: Esc cancels, clicking elsewhere cancels, Enter applies
wr = next(x for x in w.bd.wires if x.start and x.end and len(x.points) == 2 and not x.start.startswith('pio'))
old = wr.net
mid = QPointF((wr.points[0][0] + wr.points[1][0]) / 2, wr.points[0][1])
cv.resetTransform(); cv.centerOn(mid); QTest.qWait(100)
pm = cv.mapFromScene(mid)


def open_editor():
    QTest.mouseDClick(vp, Qt.LeftButton, Qt.NoModifier, pm); QTest.qWait(100)
    return next((e for e in vp.findChildren(QLineEdit) if e.isVisible()), None)


ed = open_editor()
ed.setText('zz_esc'); QTest.keyClick(ed, Qt.Key_Escape); QTest.qWait(100)
ok('inline edit: Esc cancels', any(x.net == old for x in w.bd.wires) and not any(x.net == 'zz_esc' for x in w.bd.wires)
   and not [e for e in vp.findChildren(QLineEdit) if e.isVisible()])
ed = open_editor()
ed.setText('zz_click'); cv.setFocus(); QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, pm + QPoint(0, 200)); QTest.qWait(100)
ok('inline edit: clicking elsewhere cancels', not any(x.net == 'zz_click' for x in w.bd.wires)
   and not [e for e in vp.findChildren(QLineEdit) if e.isVisible()])
ed = open_editor()
ed.setText(old + '_y'); QTest.keyClick(ed, Qt.Key_Return); QTest.qWait(100)
ok('inline edit: Enter applies', any(x.net == old + '_y' for x in w.bd.wires))

# 3. drag a free port onto a dangling net end: connects and takes the net name
dang = next(x for x in w.bd.wires if bool(x.start) != bool(x.end) and len(x.points) == 2
            and abs(x.points[0][1] - x.points[1][1]) < .01)
which = 'end' if not dang.end else 'start'
k = -1 if which == 'end' else 0
e = list(dang.points[k]); nxt = dang.points[k + 1 if k == 0 else -2]
side = 1 if nxt[0] > e[0] else -1
free = BdPortIo(w._new_id('p'), 'free_port', 'output', e[0] - side * 80, e[1] + 100)
w.bd.port_ios.append(free); w._ensure_port('free_port', 'output'); w._reload_scene()
cv.resetTransform(); cv.centerOn(e[0], e[1] + 50); QTest.qWait(100)
target = QPointF(e[0] - side * bd_editor.PORT_EDGE, e[1])
drag(cv.mapFromScene(free.x, free.y), cv.mapFromScene(target))
dang = next(x for x in w.bd.wires if x.id == dang.id)
ok(f'port dropped on net: connected ({getattr(dang, which)})', getattr(dang, which) == f'pio:{free.id}')
ok(f'port dropped on net: renamed to net ({free.name} == {dang.net})', free.name == dang.net)
ok('port dropped on net: free_port signal removed', not any(s.name == 'free_port' for s in w.bd.signals))
ok('port dropped on net: net is now a module port', next(s for s in w.bd.signals if s.name == dang.net).mode == 'output')

# 4. drag a dangling net end onto a free port: connects, net takes the port name
dang = next(x for x in w.bd.wires if bool(x.start) != bool(x.end) and len(x.points) == 2
            and abs(x.points[0][1] - x.points[1][1]) < .01 and x.id != dang.id)
which = 'end' if not dang.end else 'start'
k = -1 if which == 'end' else 0
e = list(dang.points[k]); nxt = dang.points[k + 1 if k == 0 else -2]
side = 1 if nxt[0] > e[0] else -1
port = BdPortIo(w._new_id('p'), 'new_port_in', 'input', e[0] + side * 60, e[1])
w.bd.port_ios.append(port); w._ensure_port('new_port_in', 'input'); w._reload_scene()
cv.resetTransform(); cv.centerOn(e[0], e[1]); QTest.qWait(100)
sc.clearSelection(); sc.wire_items[dang.id].setSelected(True); QTest.qWait(50)
old_net = dang.net
drag(cv.mapFromScene(e[0], e[1]), cv.mapFromScene(port.x - side * 3, port.y))
dang = next(x for x in w.bd.wires if x.id == dang.id)
ok(f'net end dropped on port: connected ({getattr(dang, which)})', getattr(dang, which) == f'pio:{port.id}')
ok(f'net end dropped on port: net renamed {old_net} -> {dang.net}', dang.net == 'new_port_in'
   and not any(x.net == old_net for x in w.bd.wires))
ok('net end dropped on port: end touches the port', abs(end_of(dang, which)[0] - sc.port_edge(port)[0]) < .01)
text, _ = bd_editor.generate_bd(w.bd)
ok('generated HDL has the new input port', 'new_port_in' in text.split(');')[0])

# 5. popup menus
wr_item = sc.wire_items[w.bd.wires[0].id]
m = QMenu(); w._net_menu(m, wr_item, QPointF(*w.bd.wires[0].points[0]), False)
print('  net menu :', ' | '.join(a.text().replace('&', '') or '-' for a in m.actions()))
m = QMenu(); w._port_menu(m, sc.items_by_id[w.bd.port_ios[0].id], QPointF(0, 0), False)
print('  port menu:', ' | '.join(a.text().replace('&', '') or '-' for a in m.actions()))
w.dirty = False
_env.finish(fails)
