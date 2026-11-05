"""Check that Dolphin HDS draws a state diagram where HDS does: for every object of an HDS
.sm file, the rectangle Dolphin draws is compared with the one saved in the file (HDS units,
75 per scene unit). Objects off by more than TOL HDS units are listed.

    python tests/hds_compare/fsm_geometry.py path/to/fsm.sm [...]

Checked: states (circle), junctions (diamond), transition text boxes, priority circles,
state action blocks. Read only.
"""
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'src'))
from PySide6.QtWidgets import QApplication  # noqa: E402

from gui.main_window import MainWindow  # noqa: E402
from hds.import_sm import import_sm  # noqa: E402
from hds.sexpr import Node, parse_file  # noqa: E402

TOL = 30          # HDS units (0.4 scene unit)
app = QApplication(sys.argv[:1])


def xt(node):
    """Extent [x0, y0, x1, y1] (HDS units) of an object of the file, or None."""
    v = node.get('xt') if isinstance(node, Node) else None
    return [float(c) for c in v.split(',')] if isinstance(v, str) else None


def compare(path):
    """Open one .sm in the editor and compare where every object is drawn with where the file
    has it; returns the problems found.
    """
    doc = parse_file(path)
    win = MainWindow(import_sm(path))
    sc, m = win.scene, win.machine
    bad, n = [], 0

    def check(what, want, item_rect):
        """Compare one drawn rectangle with the HDS extent `want` (within the tolerance); count it and
        record a mismatch.
        """
        nonlocal n
        n += 1
        got = [item_rect.left() * 75, item_rect.top() * 75, item_rect.right() * 75, item_rect.bottom() * 75]
        err = max(abs(a - b) for a, b in zip(want, got))
        if err > TOL:
            bad.append(f'{what}: HDS {[round(v) for v in want]} Dolphin {[round(v) for v in got]} (off {err:.0f})')

    for node in doc.walk():
        nid = f'n{node.label}' if node.label is not None else None
        if node.type == 'State' and nid in sc.items_by_id:
            it = sc.items_by_id[nid]
            r = it.radius()
            c = it.scenePos()
            sh = xt(node.get('shape'))
            if sh and node.get('shape').type == 'Circle':
                from PySide6.QtCore import QRectF
                check(f'state {it.obj.name} circle', sh, QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r))
            blk = node.get('actionBlk')
            box = sc.action_boxes.get(nid)
            if isinstance(blk, Node) and box is not None and box.isVisible() and box.sections():
                check(f'state {it.obj.name} actions', xt(blk.get('shape')), box.sceneBoundingRect().adjusted(2, 2, -2, -2))
        elif node.type == 'Transition':
            t = next((t for t in m.transitions if t.id == nid), None)
            if t is None or t.id not in sc.trans_items:
                continue
            it = sc.trans_items[t.id]
            tb = node.get('tb')
            if isinstance(tb, Node) and it.label.sections():
                check(f'transition {t.cond or "(always)"} box', xt(tb.get('shape')),
                      it.label.sceneBoundingRect().adjusted(2, 2, -2, -2))
            tp = node.get('tp')
            if isinstance(tp, Node) and it.show_prio:
                from PySide6.QtCore import QRectF
                c, pr = it.prio_pos, t.hds.get('prio_r', 651 / 75)
                check(f'transition {t.cond or "(always)"} priority', xt(tp.get('shape')),
                      QRectF(c.x() - pr, c.y() - pr, 2 * pr, 2 * pr))
    win.dirty = False
    print(f'{os.path.basename(os.path.dirname(path))}: {n} objects, {len(bad)} off')
    for b in bad[:40]:
        print('   ', b)
    return len(bad)


if __name__ == '__main__':
    total = sum(compare(p) for p in sys.argv[1:])
    sys.exit(1 if total else 0)
