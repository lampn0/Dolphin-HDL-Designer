"""Checks the legacy-style canvas operations in both editors."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _env  # noqa: E402
HDP, CFG, OUT = _env.setup()
from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox
from dhds.gui.main_window import MainWindow
from PySide6.QtWidgets import QGraphicsItem
from dhds.gui.design_manager import DesignManager

app = QApplication(sys.argv)
QMessageBox.question = staticmethod(lambda *a, **k: QMessageBox.Yes)
w = MainWindow(); w.resize(1400, 900); w.show(); QTest.qWait(200)
vp = w.canvas.viewport()
fails = 0


def ok(name, cond):
    global fails
    fails += not cond
    print(('PASS ' if cond else 'FAIL ') + name, flush=True)

# View Area: drag a rectangle -> zoom into it, then back to Select; Zoom Last restores
w.canvas.fit(); z0 = w.canvas.transform().m11()
w.toolbar_actions['view_area'].trigger()
QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, QPoint(300, 300))
QTest.mouseMove(vp, QPoint(420, 380))
QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, QPoint(420, 380))
z1 = w.canvas.transform().m11()
ok(f'view area zooms in ({z0:.2f} -> {z1:.2f})', z1 > z0 * 2)
ok('view area returns to select', w.canvas.tool == '' and w.mode_actions['select'].isChecked())
w.toolbar_actions['zoom_last'].trigger()
ok('zoom last restores', abs(w.canvas.transform().m11() - z0) < 1e-6)

# Panning: left-drag moves the view, no selection
w.mode_actions['pan'].trigger()
h0 = w.canvas.horizontalScrollBar().value()
w.canvas.zoom(3)
h0 = w.canvas.horizontalScrollBar().value()
QTest.mousePress(vp, Qt.LeftButton, Qt.NoModifier, QPoint(600, 400))
QTest.mouseMove(vp, QPoint(500, 400))
QTest.mouseRelease(vp, Qt.LeftButton, Qt.NoModifier, QPoint(500, 400))
ok('panning moves view', w.canvas.horizontalScrollBar().value() != h0)
QTest.keyClick(w, Qt.Key_Escape)
ok('Esc leaves panning', w.canvas.tool == '' and w.scene.mode == 'select')

# Add State repeats; right button ends the command
w.canvas.fit(); QTest.qWait(50)
n = len(w.machine.states)
w.set_mode('state')
for x in (100, 160):
    QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, QPoint(x, 80))
ok('add state repeats', len(w.machine.states) == n + 2 and w.scene.mode == 'state')
QTest.mousePress(vp, Qt.RightButton, Qt.NoModifier, QPoint(200, 80))
QTest.mouseRelease(vp, Qt.RightButton, Qt.NoModifier, QPoint(200, 80))
ok('right button ends add command', w.scene.mode == 'select')

# Ctrl+toolbar: single add
QTest.keyPress(w, Qt.Key_Control)
app.keyboardModifiers  # noqa
orig = QApplication.keyboardModifiers
QApplication.keyboardModifiers = staticmethod(lambda: Qt.ControlModifier)
w.toolbar_actions['state'].trigger()
QApplication.keyboardModifiers = orig
QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, QPoint(250, 80)); QTest.qWait(50)
ok('Ctrl+Add State adds once', len(w.machine.states) == n + 3 and w.scene.mode == 'select')

# Ctrl+arrow nudges the selection one grid step
st = w.scene.items_by_id[w.machine.states[0].id]
w.scene.clearSelection(); st.setSelected(True); x0 = w.machine.states[0].x
w.canvas.setFocus()
QTest.keyClick(w.canvas, Qt.Key_Right, Qt.ControlModifier)
ok('Ctrl+Right nudges', abs(w.machine.states[0].x - x0 - w.canvas.grid) < 1e-6)
ok('nudge is undoable', w.act_undo.isEnabled())

# Select Text: only action/condition boxes are selectable
w.mode_actions['select_text'].trigger()
from dhds.gui.diagram import _BoxItem, NodeItem
nodes = [i for i in w.scene.items() if isinstance(i, NodeItem)]
boxes = [i for i in w.scene.items() if isinstance(i, _BoxItem)]
ok('select text: nodes not selectable', all(not (i.flags() & QGraphicsItem.ItemIsSelectable) for i in nodes))
ok('select text: boxes selectable', all(i.flags() & QGraphicsItem.ItemIsSelectable for i in boxes))
w.mode_actions['select_shape'].trigger()
ok('select shapes: boxes not selectable', all(not (i.flags() & QGraphicsItem.ItemIsSelectable) for i in boxes))
w.mode_actions['select'].trigger()
ok('select: all selectable', all(i.flags() & QGraphicsItem.ItemIsSelectable for i in nodes + boxes))
ok('status tip from legacy names', w.toolbar_actions['view_area'].statusTip().startswith('Views a specified'))
w.dirty = False; w.close()

# Block diagram: generate through components from the editor
dm = DesignManager(); dm.load_project(HDP)
lib = dm.project.library('protocol_controller')
du = lib.units['pc_global_controller'] if lib.units else None
if du is None:
    lib.scan(dm.project.cache); du = lib.units['pc_global_controller']
dm.open_view(du, du.graphic_view()); QTest.qWait(400)
bd = [x for x in dm.editors.values() if type(x).__name__ == 'BdEditorWindow']
if bd:
    b = bd[0]
    ok('bd: select text has no objects', not b.toolbar_actions['select_text'].isEnabled())
    for key in ('generate_blocks', 'generate_components', 'generate_root'):
        ok(f'bd: {key} available', b.toolbar_actions[key].isEnabled())
    before = dm.log_widget.count() if hasattr(dm, 'log_widget') else 0
    b.toolbar_actions['generate_components'].trigger(); QTest.qWait(200)
    logs=[]
    dm.log = lambda msg, *a, **k: logs.append(msg)
    b.toolbar_actions['generate_components'].trigger(); QTest.qWait(200)
    print('bd generate through components:', len(logs), 'messages'); [print('   ', l) for l in logs[:12]]
    b.dirty = False; b.close()
else:
    print('SKIP bd checks (no open helper)')
_env.finish(fails)
