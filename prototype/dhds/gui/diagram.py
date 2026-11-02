"""State diagram canvas: graphics items for states, junctions, links,
special points and transitions, plus the scene that edits a Machine.

Geometry follows the legacy tool: a transition leaves/enters a node at a
stored angle on the node outline and may bend through stored points; its
condition/action box and each state's action box sit where they were put.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QLineF, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPainterPathStroker, QPen,
                           QPolygonF)
from PySide6.QtWidgets import (QGraphicsItem, QGraphicsPathItem, QGraphicsScene, QGraphicsView, QInputDialog,
                               QRubberBand)

from ..hds.import_sm import SCALE
from ..model import Junction, Link, Machine, Point, State, Transition

# The legacy editors' grid: 1000 database units. Everything placed or moved lands on it.
GRID = 1000 * SCALE


def snap(v: float) -> float:
    return round(v / GRID) * GRID


def snap_point(p: QPointF) -> QPointF:
    return QPointF(snap(p.x()), snap(p.y()))

STATE_R = 28
STATE_FILL = QColor(0, 230, 255)
LINK_FILL = QColor(255, 235, 0)
JUNCTION_FILL = QColor(230, 120, 230)
BOX_PEN = QPen(QColor(0, 120, 220), 1)
SEL_PEN = QPen(QColor(255, 120, 0), 2.5)
TEXT_FONT = QFont('Courier New', 8)
NAME_FONT = QFont('Courier New', 8, QFont.Bold)
GRAB = 6.0          # pick distance for bend points, in scene units


def _fm() -> QFontMetricsF:
    return QFontMetricsF(TEXT_FONT)


def _lines(text: str) -> list[str]:
    return [l.rstrip() for l in text.strip('\n').split('\n')] if text.strip() else []


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------
class NodeItem(QGraphicsItem):
    """Base for every node that transitions can attach to."""

    def __init__(self, scene: 'FsmScene', obj):
        super().__init__()
        self.fsm_scene = scene
        self.obj = obj
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable |
                      QGraphicsItem.ItemSendsGeometryChanges)
        self.setPos(obj.x, obj.y)
        self.setZValue(3)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange:
            return self.pos() if self.fsm_scene.readonly else snap_point(value)
        if change == QGraphicsItem.ItemPositionHasChanged:
            dx, dy = self.pos().x() - self.obj.x, self.pos().y() - self.obj.y
            self.obj.x, self.obj.y = self.pos().x(), self.pos().y()
            self.fsm_scene.node_moved(self, dx, dy)
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event):
        moved = event.buttonDownScenePos(Qt.LeftButton) != event.scenePos()
        super().mouseReleaseEvent(event)
        if moved:
            self.fsm_scene.changed_model.emit()

    def boundary(self, angle: float) -> QPointF:
        """Point on the outline in direction `angle` (radians, scene coordinates)."""
        r = self.radius()
        c = self.scenePos()
        return QPointF(c.x() + math.cos(angle) * r, c.y() + math.sin(angle) * r)

    def anchor(self, toward: QPointF) -> QPointF:
        c = self.scenePos()
        return self.boundary(math.atan2(toward.y() - c.y(), toward.x() - c.x()))

    def radius(self) -> float:
        return 10.0


class StateItem(NodeItem):
    def radius(self):
        # grow the circle so long state names stay inside
        return max(STATE_R, QFontMetricsF(NAME_FONT).horizontalAdvance(self.obj.name) / 2 + 7)

    def boundingRect(self):
        r = self.radius() + 3
        return QRectF(-r, -r, 2 * r, 2 * r)

    def paint(self, p: QPainter, opt, widget=None):
        r = self.radius()
        p.setRenderHint(QPainter.Antialiasing)
        p.setBrush(STATE_FILL)
        p.setPen(SEL_PEN if self.isSelected() else QPen(QColor(0, 90, 160), 1.2))
        p.drawEllipse(QPointF(0, 0), r, r)
        p.setFont(NAME_FONT)
        p.setPen(Qt.black)
        p.drawText(QRectF(-r, -10, 2 * r, 20), Qt.AlignCenter | Qt.TextDontClip, self.obj.name)


class JunctionItem(NodeItem):
    def radius(self):
        return 9

    def boundary(self, angle):
        # diamond outline: |x| + |y| = r
        r = self.radius()
        c, s = math.cos(angle), math.sin(angle)
        k = r / (abs(c) + abs(s) or 1)
        return self.scenePos() + QPointF(c * k, s * k)

    def boundingRect(self):
        return QRectF(-40, -12, 220, 40) if self.obj.kind == 'case' else QRectF(-12, -12, 24, 24)

    def paint(self, p: QPainter, opt, widget=None):
        p.setRenderHint(QPainter.Antialiasing)
        poly = QPolygonF([QPointF(0, -9), QPointF(9, 0), QPointF(0, 9), QPointF(-9, 0)])
        p.setBrush(JUNCTION_FILL)
        p.setPen(SEL_PEN if self.isSelected() else QPen(Qt.black, 1))
        p.drawPolygon(poly)
        p.setFont(TEXT_FONT)
        p.setPen(Qt.black)
        if self.obj.kind == 'case':
            p.drawText(QPointF(-30, 21), f'CASE: {self.obj.expr}')


class LinkItem(NodeItem):
    """Yellow flag pointing right; transitions enter at its back (left) end."""

    def boundingRect(self):
        w = QFontMetricsF(NAME_FONT).horizontalAdvance(self.obj.target) + 22
        return QRectF(-14, -9, w + 14, 18)

    def paint(self, p: QPainter, opt, widget=None):
        p.setRenderHint(QPainter.Antialiasing)
        poly = QPolygonF([QPointF(-12, -6), QPointF(6, -6), QPointF(12, 0), QPointF(6, 6), QPointF(-12, 6)])
        p.setBrush(LINK_FILL)
        p.setPen(SEL_PEN if self.isSelected() else QPen(Qt.black, 1))
        p.drawPolygon(poly)
        p.setFont(NAME_FONT)
        p.setPen(Qt.black)
        p.drawText(QPointF(16, 4), self.obj.target)

    def boundary(self, angle):
        return self.scenePos() + QPointF(-12, 0)


class PointItem(NodeItem):
    """Reset, clock, interrupt, recovery and enable points."""

    def boundingRect(self):
        return QRectF(-14, -24, 130, 38)

    def paint(self, p: QPainter, opt, widget=None):
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(SEL_PEN if self.isSelected() else QPen(Qt.black, 1))
        kind = self.obj.kind
        if kind == 'recovery':
            p.setBrush(QColor(230, 30, 30))
            p.drawEllipse(QPointF(0, 0), 10, 10)
            p.setPen(QPen(Qt.white, 2))
            p.drawLine(QPointF(-5, -5), QPointF(5, 5))
            p.drawLine(QPointF(-5, 5), QPointF(5, -5))
            return
        flag = QPolygonF([QPointF(-12, -7), QPointF(6, -7), QPointF(12, 0), QPointF(6, 7), QPointF(-12, 7)])
        p.setBrush(LINK_FILL if kind != 'interrupt' else QColor(255, 210, 0))
        p.drawPolygon(flag)
        p.setPen(QPen(QColor(200, 0, 0), 1.6))
        p.setFont(NAME_FONT)
        if kind == 'interrupt':
            bolt = QPolygonF([QPointF(-4, -6), QPointF(2, -1), QPointF(-2, 0), QPointF(4, 6),
                              QPointF(-3, 1), QPointF(1, 0)])
            p.setBrush(QColor(220, 0, 0))
            p.drawPolygon(bolt)
        else:
            p.drawText(QRectF(-12, -7, 18, 14), Qt.AlignCenter, {'reset': 'R', 'clock': 'C', 'enable': 'E'}[kind])
        p.setPen(Qt.black)
        sig = self.fsm_scene.point_caption(kind)
        if sig:
            p.drawText(QPointF(-12, -10), sig)

    def boundary(self, angle):
        if self.obj.kind == 'recovery':
            return super().boundary(angle)
        return self.scenePos() + QPointF(12, 0)      # flags start at their tip


# ---------------------------------------------------------------------------
# Text boxes
# ---------------------------------------------------------------------------
class _BoxItem(QGraphicsItem):
    """Movable text box made of sections separated by horizontal lines."""

    def __init__(self, scene: 'FsmScene'):
        super().__init__()
        self.fsm_scene = scene
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable |
                      QGraphicsItem.ItemSendsGeometryChanges)
        self.setZValue(4)
        self._size = QRectF()

    def sections(self) -> list[tuple[str, list[str]]]:
        return []

    def update_size(self):
        self.prepareGeometryChange()
        fm = _fm()
        w, h = 20.0, 4.0
        for tag, lines in self.sections():
            for l in lines or ['']:
                w = max(w, fm.horizontalAdvance(l) + 10 + (16 if tag else 0))
            h += fm.height() * max(1, len(lines)) + 4
        self._size = QRectF(0, 0, w, h)

    def boundingRect(self):
        return self._size.adjusted(-2, -2, 2, 2)

    def paint(self, p: QPainter, opt, widget=None):
        secs = self.sections()
        if not secs:
            return
        fm = _fm()
        p.setPen(SEL_PEN if self.isSelected() else BOX_PEN)
        p.setBrush(QColor(255, 255, 255, 230))
        p.drawRect(self._size)
        y = 2.0
        p.setFont(TEXT_FONT)
        for i, (tag, lines) in enumerate(secs):
            if i:
                p.setPen(BOX_PEN)
                p.drawLine(QPointF(0, y), QPointF(self._size.width(), y))
                y += 2
            x = 5.0
            if tag:
                p.setPen(QColor(150, 150, 150))
                p.drawText(QPointF(3, y + fm.ascent()), tag)
                x += 16
            p.setPen(Qt.black)
            for l in lines or ['']:
                p.drawText(QPointF(x, y + fm.ascent()), l)
                y += fm.height()
            y += 2

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange:
            return self.pos() if self.fsm_scene.readonly else snap_point(value)
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.store()
            self.fsm_scene.update_leader(self)
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event):
        moved = event.buttonDownScenePos(Qt.LeftButton) != event.scenePos()
        super().mouseReleaseEvent(event)
        if moved:
            self.fsm_scene.changed_model.emit()

    def store(self):
        pass

    def owner_point(self) -> QPointF | None:
        """Point on the owning state/transition that the dashed leader line goes to."""
        return None

    def owner_item(self) -> QGraphicsItem | None:
        return None


class TransitionLabel(_BoxItem):
    """Condition above a line, actions below it."""

    def __init__(self, scene, owner: 'TransitionItem'):
        super().__init__(scene)
        self.owner = owner
        self.obj = owner.obj

    def sections(self):
        cond, acts = _lines(self.obj.cond), _lines(self.obj.actions)
        if not cond and not acts:
            return []
        return [('', cond or [''])] + ([('', acts)] if acts else [])

    def store(self):
        self.obj.label_x, self.obj.label_y = self.pos().x(), self.pos().y()

    def owner_point(self):
        return self.owner.nearest_point(self.sceneBoundingRect().center())

    def owner_item(self):
        return self.owner

    def mouseDoubleClickEvent(self, e):
        self.fsm_scene.edit_requested.emit(self.obj)


class StateActionsBox(_BoxItem):
    """Entry / in / exit actions of a state."""

    def __init__(self, scene, state_item: StateItem):
        super().__init__(scene)
        self.state_item = state_item
        self.obj = state_item.obj

    def sections(self):
        s = self.obj
        return [(tag, _lines(t)) for tag, t in (('en', s.entry_actions), ('in', s.in_actions), ('ex', s.exit_actions))
                if t.strip()]

    def store(self):
        self.obj.actions_x, self.obj.actions_y = self.pos().x(), self.pos().y()

    def owner_point(self):
        return self.state_item.anchor(self.sceneBoundingRect().center())

    def owner_item(self):
        return self.state_item

    def mouseDoubleClickEvent(self, e):
        self.fsm_scene.edit_requested.emit(self.obj)


# ---------------------------------------------------------------------------
# Transitions
# ---------------------------------------------------------------------------
class TransitionItem(QGraphicsPathItem):
    def __init__(self, scene: 'FsmScene', t: Transition):
        super().__init__()
        self.fsm_scene = scene
        self.obj = t
        self.setFlags(QGraphicsItem.ItemIsSelectable)
        self.setZValue(1)
        self.arrow = QPolygonF()
        self.ends = (QPointF(), QPointF())
        self.prio_pos = QPointF()
        self.show_prio = False
        self.label = TransitionLabel(scene, self)
        self._drag: int | None = None       # index into obj.points, or -1 start / -2 end
        self.refresh()

    # geometry ----------------------------------------------------------------
    def shape(self):
        s = QPainterPathStroker()
        s.setWidth(10)
        path = s.createStroke(self.path())
        if self.show_prio:
            path.addEllipse(self.prio_pos, 8, 8)
        return path

    def boundingRect(self):
        return super().boundingRect().adjusted(-12, -12, 12, 12)

    def _endpoints(self, a: NodeItem, b: NodeItem) -> tuple[QPointF, QPointF]:
        t = self.obj
        pts = [QPointF(*p) for p in t.points]
        first = pts[0] if pts else b.scenePos()
        last = pts[-1] if pts else a.scenePos()
        start = a.boundary(t.start_angle) if t.start_angle is not None else a.anchor(first)
        end = b.boundary(t.end_angle) if t.end_angle is not None else b.anchor(last)
        return start, end

    def refresh(self):
        sc = self.fsm_scene
        a, b = sc.item_for(self.obj.src), sc.item_for(self.obj.dst)
        if a is None or b is None:
            return
        self.prepareGeometryChange()
        t = self.obj
        path = QPainterPath()
        pts = [QPointF(*p) for p in t.points]
        if a is b and not pts and t.start_angle is None:
            r = a.radius()
            pa = a.scenePos()
            start, end = pa + QPointF(-r * 0.6, -r * 0.8), pa + QPointF(r * 0.6, -r * 0.8)
            path.moveTo(start)
            path.cubicTo(pa + QPointF(-r * 1.6, -r * 3), pa + QPointF(r * 1.6, -r * 3), end)
            before, mid = pa + QPointF(r * 1.6, -r * 3), pa + QPointF(0, -r * 2.4)
        else:
            start, end = self._endpoints(a, b)
            path.moveTo(start)
            if not pts and sc.has_reverse(t) and t.start_angle is None:
                n = QLineF(start, end).normalVector().unitVector()
                off = QPointF(n.dx() * 30, n.dy() * 30)
                ctrl = (start + end) / 2 + off
                path.quadTo(ctrl, end)
                before, mid = ctrl, (start + end) / 2 + off / 2
            else:
                for p in pts:
                    path.lineTo(p)
                path.lineTo(end)
                before = pts[-1] if pts else start
                seg = [start] + pts + [end]
                k = len(seg) // 2
                mid = (seg[k - 1] + seg[k]) / 2
        self.setPath(path)
        self.ends = (start, end)
        ang = math.atan2(end.y() - before.y(), end.x() - before.x())
        self.arrow = QPolygonF([end, end - QPointF(math.cos(ang - 0.4) * 8, math.sin(ang - 0.4) * 8),
                                end - QPointF(math.cos(ang + 0.4) * 8, math.sin(ang + 0.4) * 8)])
        # priority circle: where the user put it, else a little way along the first segment
        self.show_prio = len(sc.machine.outgoing(t.src)) > 1
        if t.prio_at is not None:
            self.prio_pos = path.pointAtPercent(path.percentAtLength(path.length() * min(1.0, max(0.0, t.prio_at))))
        else:
            nxt = pts[0] if pts else end
            d = QLineF(start, nxt)
            d.setLength(min(14.0, d.length() / 2))
            self.prio_pos = d.p2()
        # condition / action box
        self.label.update_size()
        if t.label_x is not None:
            self.label.setPos(t.label_x, t.label_y)
        else:
            self._auto_label(start, end, mid)
        cond, acts = t.cond.strip(), t.actions.strip()
        self.setToolTip(f'<b>{cond or "(always)"}</b><pre>{acts}</pre>' if acts else (cond or '(always)'))
        self.update()
        sc.update_leader(self.label)

    def _fraction_at(self, pos: QPointF) -> tuple[float, QPointF]:
        """Closest point of the path to `pos`, as (fraction of length, point)."""
        path = self.path()
        best, best_f, best_p = 1e18, 0.0, QPointF()
        for i in range(101):
            f = i / 100
            pt = path.pointAtPercent(path.percentAtLength(path.length() * f))
            d = QLineF(pt, pos).length()
            if d < best:
                best, best_f, best_p = d, f, pt
        return best_f, best_p

    def nearest_point(self, pos: QPointF) -> QPointF:
        return self._fraction_at(pos)[1]

    def _auto_label(self, start, end, mid):
        br = self.label.boundingRect()
        n = QLineF(start, end).normalVector().unitVector()
        nx, ny = n.dx(), n.dy()
        if ny > 0:
            nx, ny = -nx, -ny
        pos = mid + QPointF(nx * 8, ny * 8)
        if nx < 0:
            pos -= QPointF(br.width(), 0)
        if ny < -0.3:
            pos -= QPointF(0, br.height())
        self.label.setFlag(QGraphicsItem.ItemSendsGeometryChanges, False)
        self.label.setPos(pos)
        self.label.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)

    def paint(self, p: QPainter, opt, widget=None):
        p.setRenderHint(QPainter.Antialiasing)
        pen = SEL_PEN if self.isSelected() else QPen(Qt.black, 1.1)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(self.path())
        p.setBrush(pen.color())
        p.drawPolygon(self.arrow)
        if self.show_prio:
            p.setBrush(Qt.white)
            p.setPen(QPen(Qt.black, 0.8))
            p.drawEllipse(self.prio_pos, 6, 6)
            p.setFont(QFont('Arial', 6))
            p.drawText(QRectF(self.prio_pos.x() - 6, self.prio_pos.y() - 6, 12, 12), Qt.AlignCenter,
                       str(self.obj.priority))
        if self.isSelected():
            p.setBrush(QColor(255, 120, 0))
            p.setPen(Qt.NoPen)
            for x, y in self.obj.points:
                p.drawRect(QRectF(x - 3, y - 3, 6, 6))
            for e in self.ends:
                p.drawEllipse(e, 3, 3)

    # editing ---------------------------------------------------------------------
    def _hit(self, pos: QPointF) -> int | None:
        if self.show_prio and QLineF(pos, self.prio_pos).length() <= 7:
            return -3
        for i, (x, y) in enumerate(self.obj.points):
            if abs(pos.x() - x) <= GRAB and abs(pos.y() - y) <= GRAB:
                return i
        for k, e in ((-1, self.ends[0]), (-2, self.ends[1])):
            if QLineF(pos, e).length() <= GRAB:
                return k
        return None

    def _segment_at(self, pos: QPointF) -> int:
        """Index in obj.points where a new bend point at `pos` belongs."""
        seg = [self.ends[0]] + [QPointF(*p) for p in self.obj.points] + [self.ends[1]]
        best, idx = 1e18, 0
        for i in range(len(seg) - 1):
            ln = QLineF(seg[i], seg[i + 1])
            if ln.length() == 0:
                continue
            u = ((pos.x() - seg[i].x()) * ln.dx() + (pos.y() - seg[i].y()) * ln.dy()) / ln.length() ** 2
            u = max(0.0, min(1.0, u))
            proj = seg[i] + QPointF(ln.dx() * u, ln.dy() * u)
            d = QLineF(pos, proj).length()
            if d < best:
                best, idx = d, i
        return idx

    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        if e.button() != Qt.LeftButton or self.fsm_scene.readonly or self.fsm_scene.mode != 'select':
            return
        self._freeze_label()
        hit = self._hit(e.scenePos())
        self._inserted = hit is None
        if hit is None:
            i = self._segment_at(e.scenePos())
            p = snap_point(e.scenePos())
            self.obj.points.insert(i, [p.x(), p.y()])
            hit = i
        self._drag = hit
        self._moved = False

    def _freeze_label(self):
        if self.obj.label_x is None:
            self.obj.label_x, self.obj.label_y = self.label.pos().x(), self.label.pos().y()

    def mouseMoveEvent(self, e):
        if self._drag is None:
            return super().mouseMoveEvent(e)
        pos = e.scenePos()
        self._moved = True
        if self._drag == -3:
            self.obj.prio_at = self._fraction_at(pos)[0]
        elif self._drag >= 0:
            p = snap_point(pos)
            self.obj.points[self._drag] = [p.x(), p.y()]
        else:
            node = self.fsm_scene.item_for(self.obj.src if self._drag == -1 else self.obj.dst)
            c = node.scenePos()
            ang = math.atan2(pos.y() - c.y(), pos.x() - c.x())
            if self._drag == -1:
                self.obj.start_angle = ang
            else:
                self.obj.end_angle = ang
        self.refresh()

    def mouseReleaseEvent(self, e):
        if self._drag is not None:
            if not self._moved and self._inserted and 0 <= self._drag < len(self.obj.points):
                # a plain click on the line must not leave a new bend point behind
                del self.obj.points[self._drag]
            self._drag = None
            self.refresh()
            if self._moved:
                self.fsm_scene.changed_model.emit()
        super().mouseReleaseEvent(e)

    def mouseDoubleClickEvent(self, e):
        hit = self._hit(e.scenePos())
        if hit is not None and hit >= 0 and not self.fsm_scene.readonly:
            del self.obj.points[hit]
            self.refresh()
            self.fsm_scene.changed_model.emit()
        else:
            self.fsm_scene.edit_requested.emit(self.obj)


# ---------------------------------------------------------------------------
# Scene
# ---------------------------------------------------------------------------
class FsmScene(QGraphicsScene):
    """Edits one Machine. Emits changed_model whenever the model changes."""
    changed_model = Signal()
    message = Signal(str)
    edit_requested = Signal(object)
    MODES = ('select', 'state', 'transition', 'junction_if', 'junction_case', 'link',
             'interrupt', 'recovery', 'reset', 'clock')

    def __init__(self, parent=None):
        super().__init__(parent)
        self.machine = Machine()
        self.view_model = None
        self.mode = 'select'
        self.readonly = False
        self.items_by_id: dict[str, NodeItem] = {}
        self.trans_items: dict[str, TransitionItem] = {}
        self.action_boxes: dict[str, StateActionsBox] = {}
        self._pending_src: NodeItem | None = None
        self._rubber: QGraphicsPathItem | None = None
        self.setBackgroundBrush(QColor(252, 252, 252))
        self.leaders: dict[int, object] = {}
        self.selectionChanged.connect(self.update_all_leaders)

    # -- building -----------------------------------------------------------
    def load(self, view_model, machine: Machine):
        self.clear()
        self.leaders = {}
        self.view_model = view_model
        self.machine = machine
        self.items_by_id.clear()
        self.trans_items.clear()
        self.action_boxes.clear()
        for s in machine.states:
            self._add_node_item(StateItem(self, s))
        for j in machine.junctions:
            self._add_node_item(JunctionItem(self, j))
        for l in machine.links:
            self._add_node_item(LinkItem(self, l))
        for pt in machine.points:
            self._add_node_item(PointItem(self, pt))
        for t in machine.transitions:
            self._add_transition_item(t)
        r = self.itemsBoundingRect().adjusted(-400, -400, 400, 400)
        self.setSceneRect(r)
        self.update_all_leaders()

    def _add_node_item(self, item: NodeItem):
        self.addItem(item)
        self.items_by_id[item.obj.id] = item
        if isinstance(item, StateItem):
            self._sync_action_box(item)

    def _sync_action_box(self, item: StateItem):
        s = item.obj
        box = self.action_boxes.get(s.id)
        has = any(t.strip() for t in (s.entry_actions, s.in_actions, s.exit_actions))
        if not has:
            if box is not None:
                self.removeItem(box)
                del self.action_boxes[s.id]
            return
        if box is None:
            box = StateActionsBox(self, item)
            self.addItem(box)
            self.action_boxes[s.id] = box
        box.update_size()
        if s.actions_x is None:
            r = item.radius()
            s.actions_x, s.actions_y = s.x + r + 12, s.y - box.boundingRect().height() / 2
        box.setFlag(QGraphicsItem.ItemSendsGeometryChanges, False)
        box.setPos(s.actions_x, s.actions_y)
        box.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        box.update()
        self.update_leader(box)

    # dashed lines from each text box to the state/transition it belongs to
    def update_leader(self, box: '_BoxItem'):
        if not hasattr(self, 'leaders'):
            self.leaders = {}
        line = self.leaders.get(id(box))
        target = box.owner_point() if box.scene() is self else None
        if target is None or not box.isVisible() or not box.sections():
            if line is not None:
                line.hide()
            return
        if line is None:
            line = self.addLine(QLineF(), QPen(QColor(170, 170, 170), 0.8, Qt.DashLine))
            line.setZValue(0.5)
            self.leaders[id(box)] = line
        r = box.sceneBoundingRect()
        c = r.center()
        # leave the box from the side facing the owner
        start = QPointF(min(max(target.x(), r.left()), r.right()), min(max(target.y(), r.top()), r.bottom()))
        if r.contains(target):
            start = c
        line.setLine(QLineF(start, target))
        owner = box.owner_item()
        sel = box.isSelected() or (owner is not None and owner.isSelected())
        line.setPen(QPen(QColor(220, 0, 0) if sel else QColor(170, 170, 170), 1 if sel else 0.8, Qt.DashLine))
        line.show()

    def update_all_leaders(self):
        for box in list(self.action_boxes.values()) + [t.label for t in self.trans_items.values()]:
            self.update_leader(box)

    def _add_transition_item(self, t: Transition):
        if t.src in self.items_by_id and t.dst in self.items_by_id:
            it = TransitionItem(self, t)
            self.addItem(it)
            self.addItem(it.label)
            self.trans_items[t.id] = it
            self.update_leader(it.label)

    def item_for(self, node_id: str) -> NodeItem | None:
        return self.items_by_id.get(node_id)

    def has_reverse(self, t: Transition) -> bool:
        return any(o.src == t.dst and o.dst == t.src for o in self.machine.transitions)

    def point_caption(self, kind: str) -> str:
        vm = self.view_model
        if vm is None:
            return ''
        if kind in ('clock', 'reset'):
            s = next((s for s in vm.signals if s.category == kind), None)
            return s.expression if s else ''
        return ''

    # -- updates ----------------------------------------------------------------
    def node_moved(self, item: NodeItem, dx: float = 0.0, dy: float = 0.0):
        box = self.action_boxes.get(item.obj.id)
        if box is not None and (dx or dy):
            s = item.obj
            s.actions_x, s.actions_y = s.actions_x + dx, s.actions_y + dy
            box.setFlag(QGraphicsItem.ItemSendsGeometryChanges, False)
            box.setPos(s.actions_x, s.actions_y)
            box.setFlag(QGraphicsItem.ItemSendsGeometryChanges, True)
        if box is not None:
            self.update_leader(box)
        for t in self.machine.transitions:
            if item.obj.id in (t.src, t.dst) and t.id in self.trans_items:
                self.trans_items[t.id].refresh()

    def _reset_leaders(self):
        for line in self.leaders.values():
            self.removeItem(line)
        self.leaders = {}
        self.update_all_leaders()

    def refresh_all(self):
        for it in self.items_by_id.values():
            if isinstance(it, StateItem):
                self._sync_action_box(it)
            it.prepareGeometryChange()
            it.update()
        for it in self.trans_items.values():
            it.refresh()
        self._reset_leaders()

    def refresh_node(self, obj):
        it = self.items_by_id.get(obj.id)
        if it:
            it.prepareGeometryChange()
            if isinstance(it, StateItem):
                self._sync_action_box(it)
            it.update()
            self.node_moved(it)

    def refresh_transitions_from(self, node_id: str):
        for t in self.machine.transitions:
            if t.src == node_id and t.id in self.trans_items:
                self.trans_items[t.id].refresh()

    # -- editing ------------------------------------------------------------------
    def set_mode(self, mode: str):
        self.mode = mode
        self._cancel_pending()
        for v in self.views():
            v.setDragMode(QGraphicsView.RubberBandDrag if mode == 'select' else QGraphicsView.NoDrag)
            v.viewport().setCursor(Qt.ArrowCursor if mode == 'select' else Qt.CrossCursor)

    def _cancel_pending(self):
        self._pending_src = None
        if self._rubber is not None:
            self.removeItem(self._rubber)
            self._rubber = None

    def node_at(self, pos: QPointF) -> NodeItem | None:
        for it in self.items(pos):
            if isinstance(it, NodeItem):
                return it
        return None

    def mousePressEvent(self, event):
        if self.mode == 'select' or event.button() != Qt.LeftButton or self.readonly:
            return super().mousePressEvent(event)
        pos = snap_point(event.scenePos())
        m = self.machine
        if self.mode == 'state':
            s = State(id=m.new_id('s'), name=self._unique_state_name(), x=pos.x(), y=pos.y())
            m.states.append(s)
            self._add_node_item(StateItem(self, s))
        elif self.mode in ('junction_if', 'junction_case'):
            kind = 'case' if self.mode == 'junction_case' else 'if'
            j = Junction(id=m.new_id('j'), kind=kind, expr='expr' if kind == 'case' else '', x=pos.x(), y=pos.y())
            m.junctions.append(j)
            self._add_node_item(JunctionItem(self, j))
        elif self.mode == 'link':
            names = [s.name for s in m.states]
            target, ok = QInputDialog.getItem(None, 'Link', 'Link to state:', names or [''], 0, True)
            if not ok:
                return
            lk = Link(id=m.new_id('l'), target=target, x=pos.x(), y=pos.y())
            m.links.append(lk)
            self._add_node_item(LinkItem(self, lk))
        elif self.mode in ('interrupt', 'recovery', 'reset', 'clock'):
            if self.mode in ('recovery', 'reset', 'clock') and m.point(self.mode) is not None:
                self.message.emit(f'Only one {self.mode} point per machine')
                return
            pt = Point(id=m.new_id('p'), kind=self.mode, x=pos.x(), y=pos.y())
            m.points.append(pt)
            self._add_node_item(PointItem(self, pt))
        elif self.mode == 'transition':
            node = self.node_at(pos)
            if node is None:
                if self._pending_src is not None and self._rubber is not None:
                    # clicking on empty canvas while drawing adds a bend point
                    self._pending_pts.append([pos.x(), pos.y()])     # (already on the grid)
                return
            if self._pending_src is None:
                if isinstance(node, LinkItem):
                    return  # links are destinations only
                self._pending_src = node
                self._pending_pts: list[list[float]] = []
                self._rubber = QGraphicsPathItem()
                self._rubber.setPen(QPen(QColor(120, 120, 120), 1, Qt.DashLine))
                self.addItem(self._rubber)
                return
            src, pts = self._pending_src, list(self._pending_pts)
            self._cancel_pending()
            if isinstance(node, PointItem):
                self.message.emit('Reset, clock, interrupt and recovery points can only start a transition')
                return
            prio = len(m.outgoing(src.obj.id)) + 1
            t = Transition(id=m.new_id('t'), src=src.obj.id, dst=node.obj.id, priority=prio, points=pts)
            m.transitions.append(t)
            self._add_transition_item(t)
            self.refresh_transitions_from(src.obj.id)
            self.clearSelection()
            self.trans_items[t.id].setSelected(True)
        self.changed_model.emit()

    def mouseMoveEvent(self, event):
        if self._pending_src is not None and self._rubber is not None:
            path = QPainterPath(self._pending_src.scenePos())
            for x, y in self._pending_pts:
                path.lineTo(x, y)
            path.lineTo(event.scenePos())
            self._rubber.setPath(path)
        super().mouseMoveEvent(event)

    def _unique_state_name(self) -> str:
        names = {s.name for s in self.machine.states}
        i = len(names)
        while f'S{i}' in names:
            i += 1
        return f'S{i}'

    def delete_selected(self):
        if self.readonly:
            return
        m = self.machine
        ids = set()
        for it in self.selectedItems():
            if isinstance(it, TransitionItem):
                m.transitions = [t for t in m.transitions if t.id != it.obj.id]
                self.removeItem(it.label)
                self.removeItem(it)
                self.trans_items.pop(it.obj.id, None)
            elif isinstance(it, NodeItem):
                ids.add(it.obj.id)
        if ids:
            for t in [t for t in m.transitions if t.src in ids or t.dst in ids]:
                m.transitions.remove(t)
                if t.id in self.trans_items:
                    ti = self.trans_items.pop(t.id)
                    self.removeItem(ti.label)
                    self.removeItem(ti)
            for coll in ('states', 'junctions', 'links', 'points'):
                setattr(m, coll, [n for n in getattr(m, coll) if n.id not in ids])
            for i in ids:
                box = self.action_boxes.pop(i, None)
                if box:
                    self.removeItem(box)
                it = self.items_by_id.pop(i, None)
                if it:
                    self.removeItem(it)
        self.refresh_all()
        self.changed_model.emit()


def apply_select_filter(scene: QGraphicsScene, what: str, is_text) -> None:
    """Select mode of the legacy editors: 'any' object, 'text' only or 'shape' only."""
    for it in scene.items():
        if not (it.flags() & QGraphicsItem.ItemIsMovable or isinstance(it, QGraphicsPathItem)):
            continue
        ok = what == 'any' or (what == 'text') == bool(is_text(it))
        it.setFlag(QGraphicsItem.ItemIsSelectable, ok)
        if not ok:
            it.setSelected(False)


class FsmGraphicsView(QGraphicsView):
    """Diagram canvas shared by the editors.

    Mouse and keys follow the legacy editors: Ctrl+wheel zoom, Shift+wheel
    horizontal scroll, middle-button pan, a View Area tool (drag a rectangle
    to view), a Panning tool (left-drag moves the diagram), Zoom Last,
    Ctrl+arrow nudges the selection one grid step, and the right button ends
    the current add command."""
    tool_done = Signal()            # the View Area drag finished
    end_command = Signal()          # right button while adding objects or using a view tool
    nudged = Signal()               # selection moved with Ctrl+arrow

    def __init__(self, scene: QGraphicsScene, parent=None):
        super().__init__(scene, parent)
        self.setRenderHints(QPainter.Antialiasing | QPainter.TextAntialiasing)
        self.setDragMode(QGraphicsView.RubberBandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self._pan = None
        self.tool = ''              # '' | 'area' | 'pan'
        self.grid = GRID
        self._zooms: list[tuple] = []
        self._band: QRubberBand | None = None
        self._band_from = None
        self._eat_menu = False
        self.show_grid = True

    # tools ---------------------------------------------------------------------
    def set_tool(self, tool: str):
        self.tool = tool
        self._band_from = None
        cursor = {'area': Qt.CrossCursor, 'pan': Qt.OpenHandCursor}.get(tool)
        if cursor is not None:
            self.setDragMode(QGraphicsView.NoDrag)
            self.viewport().setCursor(cursor)

    def _remember(self):
        c = self.mapToScene(self.viewport().rect().center())
        self._zooms = (self._zooms + [(self.transform(), c)])[-20:]

    def zoom(self, factor: float):
        self._remember()
        self.scale(factor, factor)

    def zoom_last(self):
        if self._zooms:
            t, c = self._zooms.pop()
            self.setTransform(t)
            self.centerOn(c)

    def view_rect(self, r: QRectF):
        if r.width() > 2 and r.height() > 2:
            self._remember()
            self.fitInView(r, Qt.KeepAspectRatio)

    # events --------------------------------------------------------------------
    def drawBackground(self, p: QPainter, rect: QRectF):
        super().drawBackground(p, rect)
        if self.transform().m11() < 0.35:
            return
        step = self.grid
        while step * self.transform().m11() < 6:      # keep the dots apart when zoomed out
            step *= 2
        p.setPen(QPen(QColor(200, 200, 200), 0))
        x0 = math.floor(rect.left() / step) * step
        y0 = math.floor(rect.top() / step) * step
        nx, ny = int((rect.right() - x0) / step) + 2, int((rect.bottom() - y0) / step) + 2
        if self.show_grid and nx * ny < 200000:
            p.drawPoints([QPointF(x0 + i * step, y0 + j * step) for i in range(nx) for j in range(ny)])

    def wheelEvent(self, event):
        mods = event.modifiers()
        delta = event.angleDelta().y() or event.angleDelta().x()
        if mods & Qt.ControlModifier:
            self.zoom(1.15 if delta > 0 else 1 / 1.15)
        elif mods & Qt.ShiftModifier:
            bar = self.horizontalScrollBar()
            bar.setValue(bar.value() - delta)
        else:
            super().wheelEvent(event)

    def _adding(self) -> bool:
        return getattr(self.scene(), 'mode', 'select') not in ('select', '')

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton or (event.button() == Qt.LeftButton and self.tool == 'pan'):
            self._pan = event.position()
            self.viewport().setCursor(Qt.ClosedHandCursor)
            return
        if event.button() == Qt.LeftButton and self.tool == 'area':
            self._band_from = event.position().toPoint()
            if self._band is None:
                self._band = QRubberBand(QRubberBand.Rectangle, self.viewport())
            self._band.setGeometry(QRect(self._band_from, QSize()))
            self._band.show()
            return
        if event.button() == Qt.RightButton and (self.tool or self._adding()):
            self._eat_menu = True
            self.end_command.emit()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._pan is not None:
            d = event.position() - self._pan
            self._pan = event.position()
            self.horizontalScrollBar().setValue(int(self.horizontalScrollBar().value() - d.x()))
            self.verticalScrollBar().setValue(int(self.verticalScrollBar().value() - d.y()))
            return
        if self._band_from is not None:
            self._band.setGeometry(QRect(self._band_from, event.position().toPoint()).normalized())
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._pan is not None and event.button() in (Qt.MiddleButton, Qt.LeftButton):
            self._pan = None
            self.viewport().setCursor(Qt.OpenHandCursor if self.tool == 'pan' else
                                      Qt.CrossCursor if self._adding() else Qt.ArrowCursor)
            return
        if self._band_from is not None and event.button() == Qt.LeftButton:
            r = QRect(self._band_from, event.position().toPoint()).normalized()
            self._band_from = None
            self._band.hide()
            self.view_rect(self.mapToScene(r).boundingRect())
            self.tool_done.emit()
            return
        super().mouseReleaseEvent(event)

    def contextMenuEvent(self, event):
        if self._eat_menu:
            self._eat_menu = False
            return
        super().contextMenuEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Z and not event.modifiers() and hasattr(self.scene(), 'cycle_route_mode') \
                and self.scene().cycle_route_mode():
            return                              # routing mode changed while dragging a PortIO
        steps = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0), Qt.Key_Up: (0, -1), Qt.Key_Down: (0, 1)}
        if event.key() in steps and event.modifiers() == Qt.ControlModifier:
            sel = [it for it in self.scene().selectedItems() if it.flags() & QGraphicsItem.ItemIsMovable]
            if sel and not getattr(self.scene(), 'readonly', False):
                dx, dy = steps[event.key()]
                for it in sel:
                    it.moveBy(dx * self.grid, dy * self.grid)
                self.nudged.emit()
                return
        super().keyPressEvent(event)

    def fit(self):
        r = self.scene().itemsBoundingRect().adjusted(-40, -40, 40, 40)
        if r.isValid():
            self._remember()
            self.fitInView(r, Qt.KeepAspectRatio)

    # zoom/scroll position, saved per view between sessions
    def state(self) -> dict:
        c = self.mapToScene(self.viewport().rect().center())
        return {'zoom': self.transform().m11(), 'cx': c.x(), 'cy': c.y()}

    def restore(self, st: dict | None) -> bool:
        try:
            z, cx, cy = float(st['zoom']), float(st['cx']), float(st['cy'])
        except (TypeError, KeyError, ValueError):
            return False
        self.resetTransform()
        self.scale(z, z)
        self.centerOn(cx, cy)
        return True
