"""Real app path, visible window: embedded block look and in-place net / port editing."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _env  # noqa: E402
HDP, CFG, OUT = _env.setup()
from PySide6.QtCore import Qt, QPoint, QPointF
from PySide6.QtGui import QFontMetricsF
from PySide6.QtWidgets import QApplication, QLineEdit
from PySide6.QtTest import QTest
app = QApplication(sys.argv)
from gui.design_manager import DesignManager
from gui.bd_editor import MONO, PortIoItem
dm = DesignManager(); dm.show(); dm.load_project(HDP); app.processEvents()
lib = dm.project.library('dti_hbm'); lib.scan(dm.project.cache)
du = lib.units['dynamo_core']; dm.open_view(du, du.graphic_view()); app.processEvents()
win = next(iter(dm.editors.values())); win.resize(1400, 900); win.raise_(); win.activateWindow(); app.processEvents()
sc = win.scene; vp = win.canvas.viewport(); out = OUT
fails = 0
def check(ok, what):
    """Count and print one check: PASS / FAIL and its name."""
    global fails; fails += not ok; print('PASS' if ok else 'FAIL', what)
# 1) the embedded block with the brif_* nets (outputs of the block)
w = next(w for w in win.bd.wires if w.net == 'brif_bank_occp_pc' and 'emb:' in w.start + w.end)
eid = (w.start if w.start.startswith('emb:') else w.end).split(':')[1]
item = sc.items_by_id[eid]
print('text_box', item.obj.text_box, 'show_name', item.obj.show_name)
win.canvas.resetTransform(); win.canvas.scale(1.5, 1.5)
end = w.points[0] if w.start.startswith('emb:') else w.points[-1]
win.canvas.centerOn(QPointF(*end)); app.processEvents(); QTest.qWait(300)
win.canvas.grab().save(out + '/emb_look.png')
# 2) double-click on a net name: in-place box "name : wire[bounds]"
w2 = next(x for x in win.bd.wires if x.net == 'rc_write_enable_rt' and x.show_text)
it2 = sc.wire_items[w2.id]
lp = it2.label_rect().center()
win.canvas.centerOn(lp); app.processEvents(); QTest.qWait(200)
QTest.mouseDClick(vp, Qt.LeftButton, Qt.NoModifier, win.canvas.mapFromScene(lp)); QTest.qWait(300)
ed = next((x for x in vp.findChildren(QLineEdit) if x.isVisible()), None)
print('net editor text:', ed.text() if ed else None)
check(ed is not None and ed.text().startswith('rc_write_enable_rt : wire['), 'net double-click shows "name : wire[bounds]"')
win.canvas.grab().save(out + '/net_edit.png')
if ed:
    ed.setText('rc_write_enable_rt : reg[3:0]'); QTest.keyClick(ed, Qt.Key_Return); QTest.qWait(300)
sig = next(s for s in win.bd.signals if s.name == 'rc_write_enable_rt')
check((sig.type, sig.bounds) == ('reg', '[3:0]'), f'type and bounds applied ({sig.type}{sig.bounds})')
# 3) double-click on a port
pio = next(i for i in sc.items() if isinstance(i, PortIoItem))
pp = pio.mapToScene(QPointF(0, 0))
win.canvas.centerOn(pp); app.processEvents(); QTest.qWait(200)
QTest.mouseDClick(vp, Qt.LeftButton, Qt.NoModifier, win.canvas.mapFromScene(pp)); QTest.qWait(300)
ed = next((x for x in vp.findChildren(QLineEdit) if x.isVisible()), None)
print('port editor text:', ed.text() if ed else None)
check(ed is not None and ed.text().startswith(pio.obj.name + ' : '), 'port double-click edits its net in place')
if ed:
    QTest.keyClick(ed, Qt.Key_Escape)
# 4) dragging a net name moves the name only
w3 = next(x for x in win.bd.wires if x.net == 'rc_write_ptr_rt' and x.show_text)
it3 = sc.wire_items[w3.id]; pts0 = [list(q) for q in w3.points]; lab0 = w3.label
c = it3.label_rect().center(); win.canvas.centerOn(c); app.processEvents(); QTest.qWait(200)
pc = win.canvas.mapFromScene(c)
QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, pc)
for k in range(1, 6):
    QTest.mouseMove(vp, pc + QPoint(6 * k, -6 * k)); QTest.qWait(20)
QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, pc + QPoint(30, -30)); QTest.qWait(200)
check(w3.points == pts0 and w3.label != lab0, 'dragging the name moves the name, not the net')
win.canvas.grab().save(out + '/label_drag.png')
print('FAILS', fails)
_env.finish(fails)
