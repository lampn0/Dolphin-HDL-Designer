"""Design Hierarchy pane: fixed library top, Show Hierarchy appends, Hide removes, session keeps them."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _env  # noqa: E402
if len(sys.argv) < 2:                       # no step given: run them all, one process each
    sys.exit(_env.run_steps(__file__, ['1', '2']))
step = sys.argv[1]
HDP, CFG, OUT = _env.setup()
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QPainter
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu
from gui.design_manager import DesignManager
from session import Session

app = QApplication(sys.argv)
fails = 0


def ok(name, cond):
    """Count and print one check: PASS / FAIL and its name."""
    global fails
    fails += not cond
    print(('PASS ' if cond else 'FAIL ') + name, flush=True)
dm = DesignManager(); dm.resize(1600, 900); dm.show()
if step == '1':
    dm.load_project(HDP)
    dm.explore(dm.project.library('protocol_controller')); QTest.qWait(300)
    ex = dm.explorers['protocol_controller']
    h = ex.hier
    tops = [h.topLevelItem(i).text(0) for i in range(h.topLevelItemCount())]
    ok(f'only the library top is shown: {tops}', tops == ['protocol_controller'])
    row = h.topLevelItem(0).child(0)
    kids = [(row.child(k).text(0), row.child(k).text(1), row.child(k).text(3), row.child(k).text(4)) for k in range(row.childCount())]
    print('  children:', kids[:8])
    # selecting another unit no longer replaces the pane
    item = next(ex.units.topLevelItem(i) for i in range(ex.units.topLevelItemCount())
                if ex.units.topLevelItem(i).text(0) == 'bc_refresh_controller')
    ex.units.setCurrentItem(item); QTest.qWait(100)
    ok('selecting a unit keeps the pane', h.topLevelItemCount() == 1)
    # Show Hierarchy appends
    du = item.data(0, Qt.UserRole)[1]
    ex.show_hierarchy(du); ex.show_hierarchy(du)
    tops = [h.topLevelItem(i).text(0) for i in range(h.topLevelItemCount())]
    ok(f'Show Hierarchy appends once: {tops}', tops == ['protocol_controller', 'bc_refresh_controller'])
    m = QMenu(); ex._menu  # popup content for a root
    # Expand All on the fixed root
    ex.expand_all(h.topLevelItem(0))
    n = 0; todo = [h.topLevelItem(0)]
    while todo:
        it = todo.pop(); n += 1; todo += [it.child(k) for k in range(it.childCount())]
    ok(f'Expand All opened {n} rows', n > 10)
    ex.collapse_all(h.topLevelItem(0))
    ok('Collapse All', not h.topLevelItem(0).isExpanded())
    ex.expand_all(h.topLevelItem(0)); ex.collapse_all(h.topLevelItem(0))
    h.topLevelItem(0).setExpanded(True); h.topLevelItem(0).child(0).setExpanded(True)
    ex.show_hierarchy(dm.project.find_unit('gc_control_fsm'))
    QTest.qWait(200)
    for c in range(h.columnCount()):
        h.resizeColumnToContents(c)
    # screenshot with the root popup menu
    root2 = h.topLevelItem(1)
    m = QMenu()
    for text in ('Expand All', 'Collapse All', None, 'Hide Hierarchy'):
        m.addSeparator() if text is None else m.addAction(text)
    shot = h.grab()
    m.popup(h.viewport().mapToGlobal(h.visualItemRect(root2).center())); QTest.qWait(150)
    mp = m.grab(); m.hide()
    pm = QPixmap(shot.width(), shot.height()); pm.fill(Qt.white)
    p = QPainter(pm); p.drawPixmap(0, 0, shot); r = h.visualItemRect(root2)
    p.drawPixmap(r.left() + 60, r.bottom() + 30, mp); p.end(); pm.save(os.path.join(OUT, 'dm_hierarchy.png'))
    # Hide removes an added root, never the fixed one
    ex.hide_hierarchy(h.topLevelItem(0))
    ok('fixed root cannot be hidden', h.topLevelItem(0).text(0) == 'protocol_controller')
    ex.hide_hierarchy(h.topLevelItem(2))
    tops = [h.topLevelItem(i).text(0) for i in range(h.topLevelItemCount())]
    ok(f'Hide Hierarchy removes it: {tops}', tops == ['protocol_controller', 'bc_refresh_controller'])
    dm.save_session()
    s = Session.load()
    ok(f'session keeps added hierarchies {s.hierarchies}', s.hierarchies.get('protocol_controller') == [['protocol_controller', 'bc_refresh_controller']])
    dm._session_quiet = True
else:
    dm.restore_session(); QTest.qWait(300)
    h = dm.explorers['protocol_controller'].hier
    tops = [h.topLevelItem(i).text(0) for i in range(h.topLevelItemCount())]
    ok(f'restored hierarchies: {tops}', tops == ['protocol_controller', 'bc_refresh_controller'])
    dm._session_quiet = True
_env.finish(fails)
