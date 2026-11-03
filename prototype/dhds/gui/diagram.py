"""State diagram canvas: graphics items for states, junctions, links,
special points and transitions, plus the scene that edits a Machine.

Geometry follows the legacy tool: a transition leaves/enters a node at a
stored angle on the node outline and may bend through stored points; its
condition/action box and each state's action box sit where they were put.
"""
from __future__ import annotations

import math

from PySide6.QtCore import QLineF, QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import (QTransform, QColor, QFont, QFontMetricsF, QPainter, QPainterPath, QPainterPathStroker, QPen,
                           QPolygonF)
from PySide6.QtWidgets import (QGraphicsEllipseItem, QGraphicsItem, QGraphicsPathItem, QGraphicsPolygonItem, QGraphicsScene, QGraphicsView, QInputDialog,
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
STATE_FILL = QColor(0, 255, 255)        # HDS 0,65535,65535
LINK_FILL = QColor(255, 255, 0)         # HDS 65535,65535,0
LINK_TIP = 18       # a new link: its stub tip (where HDS puts the cursor) this far left of its centre
JUNCTION_FILL = QColor(234, 156, 255)    # HDS 59904,39936,65280
BOX_PEN = QPen(QColor(0, 120, 220), 1)
TRANS_BOX_COLOR = QColor(0, 128, 192)   # border of a transition's text box (HDS)
ACTION_CELL = QColor(153, 217, 234)     # cells of entry / state / exit actions (HDS)
ACTION_BORDER = QColor(156, 222, 255)   # border of a state's action block (HDS 39936,56832,65280)
HDS_LINE = 900 / 75                     # one text line of an HDS diagram (900 units, courier / Arial 8)
PRIO_R = 651 / 75                       # radius of a transition priority circle (HDS)
ACTION_COLOR = QColor(0, 0, 0)          # transition / state action text: black (HDS)
SEL_PEN = QPen(QColor(255, 120, 0), 2.5)
# diagram text in Arial, as HDS on Windows draws its "courier" diagram fonts (see bd_editor)
TEXT_FONT = QFont('Arial', 8)
NAME_FONT = QFont('Arial', 8, QFont.Bold)
GRAB = 6.0          # pick distance for bend points, in scene units


def _fm() -> QFontMetricsF:
    return QFontMetricsF(TEXT_FONT)


# HDS 2021.1 sizes (HDS units / 75): state radius 3000, junction diamond 3300, the arrow
# (pentagon) of links and points 2250 x 1000 with a 500 stub, recovery circle radius 900
HDS_STATE_R = 3000 / 75
JUNCTION_HALF = 3300 / 75 / 2
PENT_W, PENT_H, STUB = 2250 / 75, 1000 / 75, 500 / 75
REC_R = 900 / 75
STATE_LINE = QColor(0, 128, 192)
HIER_FILL = QColor(117, 156, 255)        # hierarchical state (HDS 29952,39936,65280)
HIER_LINE = QColor(0, 0, 128)
STATE_NAME_FONT = QFont('Arial', 10, QFont.Bold)
LABEL_FONT = QFont('Arial', 8)
LABEL_BOLD_FONT = QFont('Arial', 8, QFont.Bold)


def _pentagon() -> QPolygonF:
    """The yellow arrow of links and points, pointing right, centred on the origin."""
    w, h, t = PENT_W / 2, PENT_H / 2, PENT_H / 2
    return QPolygonF([QPointF(-w, -h), QPointF(w - t, -h), QPointF(w, 0), QPointF(w - t, h), QPointF(-w, h)])


def _geo_rect(g: list | None) -> QRectF | None:
    """A rectangle of an HDS geometry entry ([x0, y0, x1, y1, ...], relative to the node)."""
    return QRectF(QPointF(g[0], g[1]), QPointF(g[2], g[3])) if g else None


def _draw_geo_text(p: QPainter, g: list, text: str, font: QFont) -> None:
    """Draw a text where HDS had it: on its saved baseline, left / centred / right in its
    saved extent as HDS justified it (the font differs from HDS's courier, so the justified
    edge is what stays where HDS put it)."""
    fm = QFontMetricsF(font)
    x0, y0, x1, y1, ju, base = g
    p.setFont(font)
    for k, line in enumerate(text.split('\n')):
        w = fm.horizontalAdvance(line)
        x = (x0 + x1 - w) / 2 if ju == 0 else x1 - w if ju == 2 else x0
        y = (base if base is not None else y0 + 700 / 75) + k * HDS_LINE
        p.drawText(QPointF(x, y), line)


def _handles(p: QPainter, r: QRectF) -> None:
    """Small black squares at the corners of a selected object (HDS)."""
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(Qt.black)
    for c in (r.topLeft(), r.topRight(), r.bottomLeft(), r.bottomRight()):
        p.drawRect(QRectF(c.x() - 2.5, c.y() - 2.5, 5, 5))
    p.restore()


def _geo_sig(t, m) -> list:
    """See dhds.hds.import_sm._geo_sig: the line of a transition as read from the file."""
    from ..hds.import_sm import _geo_sig as sig
    return sig(t, m)


def _spline(path: QPainterPath, pts: list[QPointF]) -> None:
    """Continue `path` (at pts[0]) as a smooth curve through the points (Catmull-Rom spline as
    cubic Beziers), the way HDS draws a transition with route points; two points: a line."""
    if len(pts) < 3:
        path.lineTo(pts[-1])
        return
    for i in range(len(pts) - 1):
        p0 = pts[i - 1] if i > 0 else pts[i]
        p1, p2 = pts[i], pts[i + 1]
        p3 = pts[i + 2] if i + 2 < len(pts) else pts[i + 1]
        c1 = p1 + (p2 - p0) / 6
        c2 = p2 - (p3 - p1) / 6
        path.cubicTo(c1, c2, p2)


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
            if self.fsm_scene.readonly:
                return self.pos()
            # on the grid only while the user drags it: a place read from a file stays exact
            return snap_point(value) if self.fsm_scene.mouseGrabberItem() is self else value
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
    """A state as HDS 2021.1 draws it: a cyan circle with a blue outline (radius as saved by
    HDS, 3000 units by default), the name in Arial 10 bold. A wait state is the circle inside
    an octagon, with its wait text ("wait 2") above the name."""

    def _font(self) -> QFont:
        """The name font: bold, at the size the HDS file gives (10 for a new state)."""
        f = QFont(STATE_NAME_FONT)
        f.setPointSizeF(self.obj.hds.get('font', 10))
        return f

    def radius(self):
        if self.obj.radius:
            return self.obj.radius          # as HDS saved it (it sizes the circle itself)
        # a new state: HDS's default radius, grown so a long name stays inside
        return max(HDS_STATE_R, QFontMetricsF(self._font()).horizontalAdvance(self.obj.name) / 2 + 7)

    def _outer(self) -> float:
        """Half size of the octagon around a wait state (HDS: 7058 units for a 3000 circle)."""
        return self.radius() * 7058 / 6000

    def boundary(self, angle):
        if self.obj.is_wait:
            r = self._outer()
            c = self.scenePos()
            return QPointF(c.x() + math.cos(angle) * r, c.y() + math.sin(angle) * r)
        return super().boundary(angle)

    def boundingRect(self):
        r = (self._outer() if self.obj.is_wait else self.radius()) + 3
        return QRectF(-r, -r, 2 * r, 2 * r)

    def name_rect(self) -> QRectF:
        """The state name, in item coordinates (centred in the circle, below the wait text)."""
        fm = QFontMetricsF(self._font())
        w = fm.horizontalAdvance(self.obj.name) + 4
        dy = fm.height() / 2 if self.obj.is_wait else 0
        return QRectF(-w / 2, -fm.height() / 2 + dy, w, fm.height())

    def mouseDoubleClickEvent(self, e):
        # As HDS 2021.1: a double-click on the name edits it in place; elsewhere on the state
        # it opens the state's properties
        if self.name_rect().contains(e.pos()) and not self.fsm_scene.readonly:
            self.fsm_scene.rename_requested.emit(self)
        else:
            self.fsm_scene.edit_requested.emit(self.obj)

    def paint(self, p: QPainter, opt, widget=None):
        r = self.radius()
        p.setRenderHint(QPainter.Antialiasing)
        if self.obj.is_wait:
            o = self._outer()
            k = o * math.tan(math.pi / 8)
            p.setBrush(Qt.white)
            p.setPen(QPen(QColor(90, 90, 90), 0))
            p.drawPolygon(QPolygonF([QPointF(-k, -o), QPointF(k, -o), QPointF(o, -k), QPointF(o, k),
                                     QPointF(k, o), QPointF(-k, o), QPointF(-o, k), QPointF(-o, -k)]))
        if self.obj.hier:
            # a hierarchical state: three circles, blue (HDS TripleCircle)
            p.setBrush(HIER_FILL)
            p.setPen(QPen(HIER_LINE, 2))
            for k in (1.0, 0.85, 0.7):
                p.drawEllipse(QPointF(0, 0), r * k, r * k)
        else:
            p.setBrush(STATE_FILL)
            p.setPen(QPen(STATE_LINE, 2))
            p.drawEllipse(QPointF(0, 0), r, r)
        p.setFont(self._font())
        p.setPen(Qt.black)
        if self.obj.is_wait:
            fm = QFontMetricsF(self._font())
            p.drawText(QRectF(-r, -fm.height(), 2 * r, fm.height()), Qt.AlignCenter | Qt.TextDontClip,
                       self.obj.wait or 'wait')
        p.drawText(self.name_rect(), Qt.AlignCenter | Qt.TextDontClip, self.obj.name)
        if self.isSelected():
            _handles(p, self.boundingRect().adjusted(3, 3, -3, -3))


class JunctionItem(NodeItem):
    """A junction as HDS draws it: a lilac diamond (3300 units) with its symbol in the middle,
    "&" (AND), "if" or "case"; a CASE junction shows its expression below."""

    def radius(self):
        s = self.obj.hds.get('shape')
        return (s[2] - s[0]) / 2 if s else JUNCTION_HALF

    def boundary(self, angle):
        # diamond outline: |x| + |y| = r
        r = self.radius()
        c, s = math.cos(angle), math.sin(angle)
        k = r / (abs(c) + abs(s) or 1)
        return self.scenePos() + QPointF(c * k, s * k)

    def _symbol(self) -> str:
        if self.obj.symbol:
            return self.obj.symbol
        return 'case' if self.obj.kind == 'case' else 'if'

    def _expr_rect(self) -> QRectF:
        """Where the CASE expression is: as saved by HDS, else centred under the diamond."""
        g = self.obj.hds.get('expr')
        if g:
            fm = QFontMetricsF(LABEL_BOLD_FONT)
            w = fm.horizontalAdvance(f'CASE: {self.obj.expr}')
            return QRectF(g[0], g[1], max(w, g[2] - g[0]), g[3] - g[1])
        return QRectF(-60, self.radius(), 120, 14)

    def boundingRect(self):
        r = self.radius() + 3
        b = QRectF(-r, -r, 2 * r, 2 * r)
        if self.obj.kind == 'case':
            b = b.united(self._expr_rect().adjusted(-2, -2, 2, 2))
        return b

    def paint(self, p: QPainter, opt, widget=None):
        p.setRenderHint(QPainter.Antialiasing)
        h = self.radius()
        p.setBrush(JUNCTION_FILL)
        p.setPen(QPen(Qt.black, 0))
        p.drawPolygon(QPolygonF([QPointF(0, -h), QPointF(h, 0), QPointF(0, h), QPointF(-h, 0)]))
        p.setPen(Qt.black)
        g = self.obj.hds
        if g.get('symbol'):
            _draw_geo_text(p, g['symbol'], self._symbol(), LABEL_BOLD_FONT)
        else:
            p.setFont(STATE_NAME_FONT)
            p.drawText(QRectF(-h, -h, 2 * h, 2 * h), Qt.AlignCenter, self._symbol())
        if self.obj.kind == 'case':
            if g.get('expr'):
                _draw_geo_text(p, g['expr'], f'CASE: {self.obj.expr}', LABEL_BOLD_FONT)
            else:
                p.setFont(LABEL_BOLD_FONT)
                p.drawText(self._expr_rect(), Qt.AlignHCenter | Qt.AlignTop, f'CASE: {self.obj.expr}')
        if self.isSelected():
            _handles(p, QRectF(-h, -h, 2 * h, 2 * h))

    def mouseDoubleClickEvent(self, e):
        # the CASE expression is edited in place; elsewhere the junction's properties
        if self.obj.kind == 'case' and self._expr_rect().contains(e.pos()) and not self.fsm_scene.readonly:
            self.fsm_scene.text_edit_requested.emit(self, 'expr')
        else:
            self.fsm_scene.edit_requested.emit(self.obj)


class LinkItem(NodeItem):
    """A link as HDS draws it: a yellow arrow (pentagon) with a short stub on its back, where
    transitions arrive, and the target state's name in bold on its right."""

    def _name_geo(self) -> list:
        """The target name's place: as saved by HDS, else 250 units right of the arrow."""
        g = self.obj.hds.get('name')
        if g:
            return g
        x0 = PENT_W / 2 + 250 / 75
        return [x0, -450 / 75, x0 + QFontMetricsF(LABEL_BOLD_FONT).horizontalAdvance(self.obj.target),
                450 / 75, None, 250 / 75]

    def _turn(self) -> QTransform:
        """The arrow's direction: drawn pointing right, turned as HDS saved it ("ro" 270 is
        right; 180 up, 90 left, 0 down, i.e. Qt's clockwise rotation ro - 270)."""
        return QTransform().rotate(self.obj.hds.get('ro', 270) - 270)

    def _name_rect(self) -> QRectF:
        g = self._name_geo()
        w = QFontMetricsF(LABEL_BOLD_FONT).horizontalAdvance(self.obj.target)
        x0 = g[2] - w if g[4] == 2 else (g[0] + g[2] - w) / 2 if g[4] == 0 else g[0]
        return QRectF(min(x0, g[0]), g[1], max(w, g[2] - g[0]), g[3] - g[1])

    def boundingRect(self):
        arrow = self._turn().mapRect(QRectF(-PENT_W / 2 - STUB, -PENT_H / 2, PENT_W + STUB, PENT_H))
        return arrow.united(self._name_rect()).adjusted(-2, -2, 2, 2)

    def paint(self, p: QPainter, opt, widget=None):
        p.setRenderHint(QPainter.Antialiasing)
        p.save()
        p.setTransform(self._turn(), True)
        p.setPen(QPen(Qt.black, 0))
        p.drawLine(QPointF(-PENT_W / 2 - STUB, 0), QPointF(-PENT_W / 2, 0))
        p.setBrush(LINK_FILL)
        p.drawPolygon(_pentagon())
        if self.isSelected():
            _handles(p, QRectF(-PENT_W / 2, -PENT_H / 2, PENT_W, PENT_H))
        p.restore()
        p.setPen(Qt.black)
        _draw_geo_text(p, self._name_geo(), self.obj.target, LABEL_BOLD_FONT)

    def boundary(self, angle):
        # transitions arrive at the end of the stub on the arrow's back
        return self.scenePos() + self._turn().map(QPointF(-PENT_W / 2 - STUB, 0))

    def mouseDoubleClickEvent(self, e):
        # the target name is edited in place (HDS); elsewhere the link's properties
        if self._name_rect().contains(e.pos()) and not self.fsm_scene.readonly:
            self.fsm_scene.text_edit_requested.emit(self, 'target')
        else:
            self.fsm_scene.edit_requested.emit(self.obj)


class PointItem(NodeItem):
    """Clock, reset, enable, interrupt and recovery state points, as HDS draws them: a yellow
    arrow (pentagon) with a symbol in it (clock edge / reset / enable), the signal name on the
    left; the interrupt point is red with a flash; the recovery point is a red circle with an X."""

    def boundingRect(self):
        if self.obj.kind == 'recovery':
            return QRectF(-REC_R - 2, -REC_R - 2, 2 * REC_R + 4, 2 * REC_R + 4)
        cap = self.fsm_scene.point_name(self.obj.kind)
        r = QRectF(-PENT_W / 2 - 2, -PENT_H / 2 - 2, PENT_W + STUB + 4, PENT_H + 4)
        if cap:
            g = self._name_geo(cap)
            w = QFontMetricsF(LABEL_FONT).horizontalAdvance(cap)
            r = r.united(QRectF(min(g[0], g[2] - w) - 2, g[1] - 2, max(w, g[2] - g[0]) + 4, g[3] - g[1] + 4))
        if self.obj.kind in ('clock', 'enable') and self.fsm_scene.point_caption(self.obj.kind):
            r = r.united(self._expr_rect().adjusted(-1, -1, 1, 1))
        return r

    def paint(self, p: QPainter, opt, widget=None):
        p.setRenderHint(QPainter.Antialiasing)
        kind = self.obj.kind
        if kind == 'recovery':
            p.setBrush(QColor(255, 0, 0))
            p.setPen(QPen(Qt.black, 0))
            p.drawEllipse(QPointF(0, 0), REC_R, REC_R)
            d = REC_R * 0.6
            p.drawLine(QPointF(-d, -d), QPointF(d, d))
            p.drawLine(QPointF(-d, d), QPointF(d, -d))
            if self.isSelected():
                _handles(p, QRectF(-REC_R, -REC_R, 2 * REC_R, 2 * REC_R))
            return
        p.setPen(QPen(Qt.black, 0))
        p.setBrush(QColor(255, 0, 0) if kind == 'interrupt' else LINK_FILL)
        p.drawPolygon(_pentagon())
        x0, w, h = -PENT_W / 2, PENT_W, PENT_H
        if kind == 'interrupt':
            p.drawLine(QPointF(w / 2, 0), QPointF(w / 2 + STUB, 0))
            p.setBrush(QColor(255, 255, 0))
            p.drawPolygon(QPolygonF([QPointF(x0 + 3, -1), QPointF(x0 + 11, -4), QPointF(x0 + 10, -1),
                                     QPointF(x0 + 22, -2), QPointF(x0 + 13, 3), QPointF(x0 + 14, 0)]))
        else:
            # the small clock wave (clock / reset / enable) and the mark of each kind
            pen = QPen(Qt.black, 0)
            p.setPen(pen)
            y_lo, y_hi = h * 0.3, -h * 0.3
            xa = x0 + w * 0.4
            p.drawPolyline(QPolygonF([QPointF(xa, y_lo), QPointF(xa + 4, y_lo), QPointF(xa + 4, y_hi),
                                      QPointF(xa + 8, y_hi)]))
            if kind == 'clock':
                p.drawArc(QRectF(x0 + 2.5, -2.7, 4.4, 5.4), 90 * 16, 180 * 16)
            elif kind == 'reset':
                p.drawLine(QPointF(x0 + 3.3, -2.3), QPointF(x0 + 3.3, 2.3))
                p.drawLine(QPointF(x0 + 3.3, -2.3), QPointF(x0 + 4.6, -2.3))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(QPointF(xa + 2, 0), 2, 2)
            elif kind == 'enable':
                p.drawArc(QRectF(x0 + 2.6, -2.3, 4.7, 4.8), 90 * 16, 180 * 16)
                p.drawLine(QPointF(x0 + 2.8, -1.4), QPointF(x0 + 6.9, -1.4))
        cap = self.fsm_scene.point_name(kind)
        if cap:
            # the signal name, right-justified 850 units left of the arrow (HDS)
            p.setPen(Qt.black)
            _draw_geo_text(p, self._name_geo(cap), cap, LABEL_FONT)
        expr = self.fsm_scene.point_caption(kind) if kind in ('clock', 'enable') else ''
        if expr:
            # the clock / enable expression in a box at the tip, as HDS shows "posedge clk"
            r = self._expr_rect()
            p.setBrush(Qt.white)
            p.setPen(QPen(TRANS_BOX_COLOR, 0))
            p.drawRect(r)
            p.setPen(Qt.black)
            g = self.obj.hds.get('cond')
            if g:
                _draw_geo_text(p, g, expr, LABEL_FONT)
            else:
                _draw_geo_text(p, [r.left() + 100 / 75, r.top() + 100 / 75, r.right(), r.bottom(), None,
                                   r.top() + 800 / 75], expr, LABEL_FONT)
        if self.isSelected():
            _handles(p, QRectF(x0, -h / 2, w, h))

    def _name_geo(self, cap: str) -> list:
        """The signal name's place: as saved by HDS, else right-justified 850 units left of
        the arrow, on the arrow's middle."""
        g = self.obj.hds.get('name')
        if g:
            return g
        x1 = -PENT_W / 2 - 850 / 75
        return [x1 - QFontMetricsF(LABEL_FONT).horizontalAdvance(cap), -600 / 75, x1, 300 / 75, 2, 100 / 75]

    def _expr_rect(self) -> QRectF:
        """The clock / enable expression box: as saved by HDS, else on the arrow's tip,
        1200 units high, wide enough for the text."""
        expr = self.fsm_scene.point_caption(self.obj.kind)
        w = QFontMetricsF(LABEL_FONT).horizontalAdvance(expr) + 200 / 75
        g = _geo_rect(self.obj.hds.get('cond_box'))
        if g:
            return QRectF(g.left(), g.top(), max(w, g.width()), g.height())
        return QRectF(PENT_W / 2, -600 / 75, w, 1200 / 75)

    def mouseDoubleClickEvent(self, e):
        # the clock / enable expression is edited in place (HDS); elsewhere the properties
        if self.obj.kind in ('clock', 'enable') and self.fsm_scene.point_caption(self.obj.kind)                 and self._expr_rect().contains(e.pos()) and not self.fsm_scene.readonly:
            self.fsm_scene.text_edit_requested.emit(self, 'expression')
        else:
            self.fsm_scene.edit_requested.emit(self.obj)

    def boundary(self, angle):
        if self.obj.kind == 'recovery':
            return self.scenePos() + QPointF(math.cos(angle) * REC_R, math.sin(angle) * REC_R)
        tip = PENT_W / 2 + (STUB if self.obj.kind == 'interrupt' else 0)
        return self.scenePos() + QPointF(tip, 0)      # transitions leave from the tip


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
            if self.fsm_scene.readonly:
                return self.pos()
            # on the grid only while the user drags it: a place read from a file stays exact
            return snap_point(value) if self.fsm_scene.mouseGrabberItem() is self else value
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

    def section_at(self, y: float) -> int:
        """Index of the section (as sections() lists them) under item y."""
        fm = _fm()
        top = 2.0
        secs = self.sections()
        for i, (_tag, lines) in enumerate(secs):
            bottom = top + fm.height() * max(1, len(lines)) + 4
            if y < bottom:
                return i
            top = bottom
        return max(0, len(secs) - 1)

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
        # As HDS: a double-click on the condition or on the actions edits that text in place
        if self.fsm_scene.readonly:
            return self.fsm_scene.edit_requested.emit(self.obj)
        field = 'actions' if self.obj.actions.strip() and self.section_at(e.pos().y()) == 1 else 'cond'
        self.fsm_scene.text_edit_requested.emit(self, field)

    def _hds(self) -> dict:
        """The geometry HDS saved for this box, while its texts are still the ones it was
        saved with (else Dolphin lays the box out)."""
        g = self.obj.hds
        return g if g.get('box_size') and g.get('sig') == [self.obj.cond, self.obj.actions] else {}

    def update_size(self):
        g = self._hds()
        if g:
            self.prepareGeometryChange()
            self._size = QRectF(0, 0, *g['box_size'])
        else:
            super().update_size()

    def paint(self, p: QPainter, opt, widget=None):
        """As HDS 2021.1 draws a transition's text: a white box with a blue border, the
        condition centred, a line, then the actions. With the geometry of an HDS file, each
        text and the line are where HDS put them. Selected: red border with corner handles."""
        secs = self.sections()
        if not secs:
            return
        g = self._hds()
        if g:
            r = self._size
            sel = self.isSelected()
            p.setBrush(Qt.white)
            p.setPen(QPen(QColor(220, 0, 0) if sel else TRANS_BOX_COLOR, 0))
            p.drawRect(r)
            p.setFont(TEXT_FONT)
            fm = _fm()
            p.setPen(Qt.black)
            for key, text in (('cond', self.obj.cond), ('acts', self.obj.actions)):
                if key in g and text.strip():
                    x, y = g[key]
                    for k, l in enumerate(_lines(text)):
                        p.drawText(QPointF(x, y + fm.ascent() + k * HDS_LINE), l)
            if g.get('line') is not None:
                p.setPen(QPen(Qt.black, 0))
                p.drawLine(QPointF(3, g['line']), QPointF(r.width() - 3, g['line']))
            if sel:
                p.setPen(Qt.NoPen); p.setBrush(QColor(220, 0, 0))
                for c in (r.topLeft(), r.topRight(), r.bottomLeft(), r.bottomRight()):
                    p.drawRect(QRectF(c.x() - 2, c.y() - 2, 4, 4))
            return
        fm = _fm()
        r = self._size
        sel = self.isSelected()
        p.setBrush(Qt.white)
        p.setPen(QPen(QColor(220, 0, 0) if sel else TRANS_BOX_COLOR, 0))
        p.drawRect(r)
        p.setFont(TEXT_FONT)
        y = 2.0
        for i, (_tag, lines) in enumerate(secs):
            if i:
                p.setPen(QPen(Qt.black, 0))
                p.drawLine(QPointF(3, y), QPointF(r.width() - 3, y))
                y += 2
            for l in lines or ['']:
                if i == 0:
                    p.setPen(Qt.black)
                    p.drawText(QRectF(0, y, r.width(), fm.height()), Qt.AlignHCenter | Qt.AlignTop, l)
                else:
                    p.setPen(ACTION_COLOR)
                    p.drawText(QPointF(5, y + fm.ascent()), l)
                y += fm.height()
            y += 2
        if sel:
            p.setPen(Qt.NoPen); p.setBrush(QColor(220, 0, 0))
            for c in (r.topLeft(), r.topRight(), r.bottomLeft(), r.bottomRight()):
                p.drawRect(QRectF(c.x() - 2, c.y() - 2, 4, 4))


class StateActionsBox(_BoxItem):
    """Entry / in / exit actions of a state."""

    def __init__(self, scene, state_item: StateItem):
        super().__init__(scene)
        self.state_item = state_item
        self.obj = state_item.obj

    def store(self):
        self.obj.actions_x, self.obj.actions_y = self.pos().x(), self.pos().y()

    def owner_point(self):
        return self.state_item.anchor(self.sceneBoundingRect().center())

    def owner_item(self):
        return self.state_item

    def mouseDoubleClickEvent(self, e):
        # the entry / state / exit actions under the cursor are edited in place (HDS)
        if self.fsm_scene.readonly:
            return self.fsm_scene.edit_requested.emit(self.obj)
        secs = self.sections()
        tag = secs[self.section_at(e.pos().y())][0] if secs else ''
        field = {'en': 'entry_actions', 'ex': 'exit_actions'}.get(tag, 'in_actions')
        self.fsm_scene.text_edit_requested.emit(self, field)

    def sections(self):
        # the state actions are shown as they are; entry / exit actions keep a small tag
        s = self.obj
        return [(tag, _lines(t)) for tag, t in (('en', s.entry_actions), ('', s.in_actions),
                                                ('ex', s.exit_actions)) if t.strip()]

    def _hds(self) -> dict:
        s = self.obj
        g = s.hds
        return g if g.get('act_size') and g.get('sig') == [s.entry_actions, s.in_actions, s.exit_actions] else {}

    def update_size(self):
        g = self._hds()
        if g:
            self.prepareGeometryChange()
            self._size = QRectF(0, 0, *g['act_size'])
        else:
            super().update_size()

    def _paint_hds(self, p: QPainter, g: dict):
        """The action block exactly as HDS saved it: with entry / exit actions a white box with
        a light blue border (width 2), the lines between the parts where they were, and the
        blue triangles on the left of the entry (pointing in) and exit (pointing out) texts;
        state actions alone: the text only."""
        s = self.obj
        r = self._size
        framed = bool(s.entry_actions.strip() or s.exit_actions.strip())
        fm = _fm()
        if framed:
            p.setBrush(Qt.white)
            p.setPen(QPen(ACTION_BORDER, 2))
            p.drawRect(r)
            for key in ('tline', 'bline'):
                if g.get(key) is not None:
                    p.drawLine(QPointF(1, g[key]), QPointF(r.width() - 1, g[key]))
        p.setFont(TEXT_FONT)
        for key, text in (('entry', s.entry_actions), ('in', s.in_actions), ('exit', s.exit_actions)):
            if key not in g or not text.strip():
                continue
            x, y = g[key]
            p.setPen(Qt.black)
            for k, l in enumerate(_lines(text)):
                p.drawText(QPointF(x + 1, y + fm.ascent() + k * HDS_LINE), l)
            if key != 'in':
                # the triangle just outside the box, at the first line of the text
                cy = y + HDS_LINE / 2
                t = 350 / 75
                tri = ([QPointF(-t, cy - t / 2), QPointF(0, cy), QPointF(-t, cy + t / 2)] if key == 'entry' else
                       [QPointF(0, cy - t / 2), QPointF(-t, cy), QPointF(0, cy + t / 2)])
                p.setPen(Qt.NoPen); p.setBrush(STATE_LINE)
                p.drawPolygon(QPolygonF(tri))
        if self.isSelected():
            p.setPen(QPen(QColor(220, 0, 0), 0)); p.setBrush(Qt.NoBrush)
            p.drawRect(r)

    def paint(self, p: QPainter, opt, widget=None):
        """As HDS 2021.1 draws a state's actions. State actions alone: plain black text next to
        the state. With entry and / or exit actions: one light blue cell per kind (entry, state,
        exit, in that order), the entry and exit cells marked by a small tick on their left.
        Selected: a red border."""
        secs = self.sections()
        if not secs:
            return
        g = self._hds()
        if g:
            return self._paint_hds(p, g)
        fm = _fm()
        p.setFont(TEXT_FONT)
        cells = any(tag for tag, _ in secs)
        w = self._size.width()
        y = 2.0
        for tag, lines in secs:
            top = y - 1
            x = 18.0 if cells else 5.0
            p.setPen(ACTION_COLOR)
            for l in lines or ['']:
                p.drawText(QPointF(x, y + fm.ascent()), l)
                y += fm.height()
            if cells:
                p.setPen(QPen(ACTION_CELL, 0)); p.setBrush(Qt.NoBrush)
                p.drawRect(QRectF(14, top, w - 14, y - top + 1))
                if tag:
                    # the tick of an entry / exit cell (HDS)
                    p.setPen(QPen(STATE_LINE, 0))
                    my = top + fm.height() / 2 + 1
                    p.drawLine(QPointF(7, my - 2), QPointF(11, my))
                    p.drawLine(QPointF(7, my + 2), QPointF(11, my))
            y += 2
        if self.isSelected():
            p.setPen(QPen(QColor(220, 0, 0), 0)); p.setBrush(Qt.NoBrush)
            p.drawRect(self._size)


# ---------------------------------------------------------------------------
# Declaration blocks (top of an HDS state diagram)
# ---------------------------------------------------------------------------
DECL_TITLE = QFont('Arial', 8, QFont.Bold)
DECL_TEXT = QFont('Arial', 8)
DECL_MONO = QFont('Courier New', 8)
DECL_COLOR = QColor(0, 0, 0)            # the user text of the blocks: black (HDS)
# where HDS puts the titles of a new diagram, in HDS units from the Global Actions title
_DECL_OFFSETS = {'global': (0, 0), 'concurrent': (9200, 0), 'module': (22100, 0), 'status': (35600, 0),
                 'statereg': (44300, 0), 'compdir': (0, 4000)}


class DeclBlockItem(QGraphicsItem):
    """One of the text blocks HDS draws at the top of a state diagram: Global Actions (Pre /
    Post Actions), Concurrent Statements, Module Declarations (Pre / Post Decls), Signal Status
    (the outputs and locals with their default, reset and scheme), State Register Statements,
    Compiler Directives (Pre- / Post- / End-module directives). Each has a bold title and its
    text below; it can be moved (its place is kept in the view), a double-click opens the
    page where its text is edited."""
    KEYS = ('global', 'concurrent', 'module', 'status', 'statereg', 'compdir')
    TITLES = {'global': 'Global Actions', 'concurrent': 'Concurrent Statements',
              'module': 'Module Declarations', 'status': 'Signal Status',
              'statereg': 'State Register Statements', 'compdir': 'Compiler Directives'}

    def __init__(self, scene: 'FsmScene', view, key: str):
        super().__init__()
        self.fsm_scene, self.view, self.key = scene, view, key
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemIsSelectable |
                      QGraphicsItem.ItemSendsGeometryChanges)
        self.setZValue(3)
        self.setPos(QPointF(*self._place()))

    def _place(self) -> tuple[float, float]:
        if self.key in self.view.decl_pos:
            return tuple(self.view.decl_pos[self.key])
        # no place yet (a diagram made by Dolphin): HDS's layout, above the diagram content
        m = self.fsm_scene.machine
        nodes = list(m.states) + list(m.points) + list(m.junctions) + list(m.links)
        x0 = min((n.x for n in nodes), default=0.0) - 120
        y0 = min((n.y for n in nodes), default=0.0) - 220
        dx, dy = _DECL_OFFSETS[self.key]
        return x0 + dx / 75, y0 + dy / 75

    def rows(self) -> list[tuple[str, str]]:
        """(kind, text) lines: kind 'title' / 'label' (bold, black), 'text' (blue), 'mono'."""
        v = self.view
        out = [('title', self.TITLES[self.key])]

        def part(label, text):
            if label:
                out.append(('label', label))
            out.extend(('text', l) for l in _lines(text))
        if self.key == 'global':
            part('Pre Actions:', v.global_pre_actions)
            part('Post Actions:', v.global_post_actions)
        elif self.key == 'concurrent':
            part('', v.concurrent_statements)
        elif self.key == 'module':
            part('Pre Decls', '')
            part('Post Decls', '')
        elif self.key == 'statereg':
            part('', v.state_register_statements)
        elif self.key == 'compdir':
            part('Pre-module directives:', v.pre_module_directives)
            part('Post-module directives:', v.post_module_directives)
            part('End-module directives:', v.end_module_directives)
        elif self.key == 'status':
            scheme = {'comb': 'COMB', 'clocked': 'CLKD', 'registered': 'REG'}
            rows = [(s.name, s.mode, s.default, s.reset, scheme.get(s.scheme, ''), s.comment)
                    for s in v.signals if s.mode in ('output', 'local') and s.scheme in scheme]
            head = ('SIGNAL', 'MODE', 'DEFAULT', 'RESET', 'SCHEME', 'COMMENT')
            w = [max(len(str(r[k])) for r in rows + [head]) + 1 for k in range(6)]
            for r in [head] + rows:
                out.append(('mono', ''.join(str(c).ljust(w[k]) for k, c in enumerate(r)).rstrip()))
        return out

    def _font(self, kind: str) -> QFont:
        return {'title': DECL_TITLE, 'label': DECL_TITLE, 'mono': DECL_MONO}.get(kind, DECL_TEXT)

    def boundingRect(self):
        w, h = 0.0, 0.0
        for kind, text in self.rows():
            fm = QFontMetricsF(self._font(kind))
            w = max(w, fm.horizontalAdvance(text))
            h += fm.height()
        return QRectF(-2, -2, w + 4, h + 4)

    def paint(self, p: QPainter, opt, widget=None):
        y = 0.0
        for kind, text in self.rows():
            f = self._font(kind)
            fm = QFontMetricsF(f)
            p.setFont(f)
            p.setPen(Qt.black if kind in ('title', 'label') else DECL_COLOR)
            p.drawText(QPointF(0, y + fm.ascent()), text)
            y += fm.height()
        if self.isSelected():
            p.setPen(QPen(QColor(220, 0, 0), 0)); p.setBrush(Qt.NoBrush)
            p.drawRect(self.boundingRect().adjusted(1, 1, -1, -1))

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange:
            if self.fsm_scene.readonly:
                return self.pos()
            # on the grid only while the user drags it: a place read from a file stays exact
            return snap_point(value) if self.fsm_scene.mouseGrabberItem() is self else value
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.view.decl_pos[self.key] = [self.pos().x(), self.pos().y()]
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, e):
        moved = e.buttonDownScenePos(Qt.LeftButton) != e.scenePos()
        super().mouseReleaseEvent(e)
        if moved:
            self.fsm_scene.changed_model.emit()

    FIELDS = {'global': ['global_pre_actions', 'global_post_actions'], 'concurrent': ['concurrent_statements'],
              'statereg': ['state_register_statements'],
              'compdir': ['pre_module_directives', 'post_module_directives', 'end_module_directives']}

    def field_at(self, y: float) -> str:
        """The view field of the text under item y: the part whose label is above it."""
        fields = self.FIELDS.get(self.key, [])
        if not fields:
            return ''
        k, top = -1, 0.0
        for kind, _text in self.rows():
            h = QFontMetricsF(self._font(kind)).height()
            if kind == 'label' or (kind == 'title' and len(fields) == 1):
                k += 1
            if y < top + h:
                break
            top += h
        return fields[min(max(k, 0), len(fields) - 1)]

    def mouseDoubleClickEvent(self, e):
        # a text block is edited in place (HDS); the Signal Status is edited in the table
        field = self.field_at(e.pos().y())
        if field and not self.fsm_scene.readonly:
            self.fsm_scene.text_edit_requested.emit(self, field)
        else:
            self.fsm_scene.decl_edit_requested.emit(self.key)


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
            path.addEllipse(self.prio_pos, PRIO_R + 1, PRIO_R + 1)
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

    def hds_geometry(self) -> dict:
        """What an HDS file needs of the line as drawn (dhds.hds.export_sm): its points
        (start, route points, end) and the centre of its priority circle, scene units."""
        s, e = self.ends
        return {'pts': [(s.x(), s.y()), *[tuple(p) for p in self.obj.points], (e.x(), e.y())],
                'prio': (self.prio_pos.x(), self.prio_pos.y())}

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
                # HDS draws a transition as a spline: a smooth curve through its route points
                _spline(path, [start] + pts + [end])
                before = pts[-1] if pts else start
                seg = [start] + pts + [end]
                k = len(seg) // 2
                mid = (seg[k - 1] + seg[k]) / 2
        self.setPath(path)
        self.ends = (start, end)
        ang = math.atan2(end.y() - before.y(), end.x() - before.x())
        self.arrow = QPolygonF([end, end - QPointF(math.cos(ang - 0.4) * 8, math.sin(ang - 0.4) * 8),
                                end - QPointF(math.cos(ang + 0.4) * 8, math.sin(ang + 0.4) * 8)])
        # priority circle: shown as the HDS file says (else when the source has several
        # transitions), where it was (HDS keeps it at a percentage of the line), else a little
        # way along the first segment
        self.show_prio = t.hds['prio_shown'] if 'prio_shown' in t.hds else len(sc.machine.outgoing(t.src)) > 1
        exact = 'prio_center' in t.hds and t.hds.get('geo_sig') == _geo_sig(t, sc.machine)
        if t.prio_at is None and 'prio_center' in t.hds:
            self.setPath(path)
            t.prio_at = self._fraction_at(QPointF(*t.hds['prio_center']))[0]
        if exact:
            # the line is still as HDS saved it: its priority circle exactly where HDS had it
            self.prio_pos = QPointF(*t.hds['prio_center'])
        elif t.prio_at is not None:
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
        pen = QPen(Qt.black, 1.1)        # HDS: a selected transition keeps its colour, it gets handles
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawPath(self.path())
        p.setBrush(pen.color())
        p.drawPolygon(self.arrow)
        if self.show_prio:
            # HDS: a white circle (radius 651, or as saved) with the priority in it
            pr = self.obj.hds.get('prio_r', PRIO_R)
            p.setBrush(Qt.white)
            p.setPen(QPen(Qt.black, 0))
            p.drawEllipse(self.prio_pos, pr, pr)
            p.setFont(TEXT_FONT)
            p.drawText(QRectF(self.prio_pos.x() - pr, self.prio_pos.y() - pr, 2 * pr, 2 * pr), Qt.AlignCenter,
                       str(self.obj.priority))
        if self.isSelected():
            # black square handles on the two ends and on each route point
            p.setBrush(Qt.black)
            p.setPen(Qt.NoPen)
            for q in [QPointF(x, y) for x, y in self.obj.points] + list(self.ends):
                p.drawRect(QRectF(q.x() - 3, q.y() - 3, 6, 6))

    # editing ---------------------------------------------------------------------
    def _hit(self, pos: QPointF) -> int | None:
        if self.show_prio and QLineF(pos, self.prio_pos).length() <= PRIO_R + 1:
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
        hit = self._hit(e.scenePos())
        # As HDS 2021.1: only the handles move (route points, the two ends, the priority);
        # a drag on the line itself does nothing. Route points are added from the right-click
        # menu (Add Route).
        self._inserted = False
        self._drag = hit
        self._moved = False
        if hit is not None:
            self._freeze_label()

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
            drag, self._drag = self._drag, None
            if self._moved and drag in (-1, -2) and self._reconnect(drag, e.scenePos()):
                return
            self.refresh()
            if self._moved:
                self.fsm_scene.changed_model.emit()
        super().mouseReleaseEvent(e)

    def itemChange(self, change, value):
        # a selected transition comes above the states: its end handles lie on a state edge
        # and must take the press (as in HDS) rather than the state under them
        if change == QGraphicsItem.ItemSelectedHasChanged:
            self.setZValue(5 if value else 1)
        return super().itemChange(change, value)

    def _reconnect(self, which: int, pos: QPointF) -> bool:
        """An end handle dropped on another node moves that end there (HDS: the transition is
        reconnected, drawn straight again with its text in the middle). The start can go to
        anything a transition may start from, the end to anything it may end on."""
        sc = self.fsm_scene
        node = next((it for it in sc.items(pos) if isinstance(it, NodeItem)), None)
        t = self.obj
        current = t.src if which == -1 else t.dst
        if node is None or node.obj.id == current:
            return False
        if which == -1 and isinstance(node, LinkItem):
            return False                        # a link only ends transitions
        if which == -2 and isinstance(node, PointItem):
            return False                        # clock / reset / recovery points only start them
        if which == -1:
            t.src, t.start_angle = node.obj.id, None
        else:
            t.dst, t.end_angle = node.obj.id, None
        t.points, t.label_x, t.label_y, t.prio_at = [], None, None, None
        sc.load(sc.view_model, sc.machine)
        sc.changed_model.emit()
        return True

    def contextMenuEvent(self, e):
        """The HDS transition menu: Add Route / Remove Route / Remove All Routes / Reverse
        Direction, Delete, Object Properties."""
        from PySide6.QtWidgets import QMenu
        sc = self.fsm_scene
        if not self.isSelected():
            sc.clearSelection()
            self.setSelected(True)
        pos = e.scenePos()
        hit = self._hit(pos)
        ro = sc.readonly
        m = QMenu()
        a = m.addAction('Add Route', lambda: self.add_route(pos)); a.setEnabled(not ro)
        a = m.addAction('Remove Route', lambda: self.remove_route(hit))
        a.setEnabled(not ro and hit is not None and hit >= 0)
        a = m.addAction('Remove All Routes', self.remove_all_routes); a.setEnabled(not ro and bool(self.obj.points))
        a = m.addAction('Reverse Direction', self.reverse); a.setEnabled(not ro)
        m.addSeparator()
        a = m.addAction('Delete', sc.delete_selected); a.setEnabled(not ro)
        m.addSeparator()
        m.addAction('Object Properties...', lambda: sc.edit_requested.emit(self.obj))
        m.exec(e.screenPos())

    def add_route(self, pos: QPointF):
        p = snap_point(pos)
        self.obj.points.insert(self._segment_at(pos), [p.x(), p.y()])
        self.refresh()
        self.fsm_scene.changed_model.emit()

    def remove_route(self, k: int | None):
        if k is not None and 0 <= k < len(self.obj.points):
            del self.obj.points[k]
            self.refresh()
            self.fsm_scene.changed_model.emit()

    def remove_all_routes(self):
        self.obj.points = []
        self.refresh()
        self.fsm_scene.changed_model.emit()

    def reverse(self):
        """Diagram > Reverse Direction: source and destination swap, route points reversed."""
        t = self.obj
        t.src, t.dst = t.dst, t.src
        t.start_angle, t.end_angle = t.end_angle, t.start_angle
        t.points = list(reversed(t.points))
        sc = self.fsm_scene
        sc.load(sc.view_model, sc.machine)
        sc.changed_model.emit()

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
    condition_edit_requested = Signal(object)    # a new transition: type its condition in place
    rename_requested = Signal(object)            # a StateItem: edit its name in place
    decl_edit_requested = Signal(str)            # a declaration block (DeclBlockItem.KEYS)
    text_edit_requested = Signal(object, str)    # (item, field): edit a text in place
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
        self.setBackgroundBrush(QColor(255, 255, 255))      # HDS canvas: pure white
        self.leaders: dict[int, object] = {}
        self.selectionChanged.connect(self.update_all_leaders)

    # -- building -----------------------------------------------------------
    def load(self, view_model, machine: Machine):
        # forget the old items first: clear() deletes them and emits selectionChanged, whose
        # update_all_leaders would otherwise reach the deleted action boxes
        self.items_by_id.clear()
        self.trans_items.clear()
        self.action_boxes.clear()
        self.leaders = {}
        self.clear()
        self._state_ghost = None                    # removed by clear()
        self.view_model = view_model
        self.machine = machine
        # the top level of the machine: what is inside a hierarchical state is drawn in its own
        # diagram (HDS), so it is left out here, with the transitions between its nodes
        for s in machine.states:
            if not s.parent:
                self._add_node_item(StateItem(self, s))
        for j in machine.junctions:
            if not j.parent:
                self._add_node_item(JunctionItem(self, j))
        for l in machine.links:
            if not l.parent:
                self._add_node_item(LinkItem(self, l))
        for pt in machine.points:
            if not pt.parent:
                self._add_node_item(PointItem(self, pt))
        for t in machine.transitions:
            self._add_transition_item(t)
        if view_model is not None:
            for key in DeclBlockItem.KEYS:
                if key not in view_model.decl_hidden:     # hidden in HDS: not drawn either
                    self.addItem(DeclBlockItem(self, view_model, key))
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
        # as HDS: the line from a text box to its state / transition shows only while the box
        # is selected
        if target is None or not box.isVisible() or not box.sections() or not box.isSelected():
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
        line.setPen(QPen(QColor(220, 0, 0), 0))
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

    def point_name(self, kind: str) -> str:
        """Name of the signal of a clock / reset / enable point (shown on its left, as HDS)."""
        vm = self.view_model
        if vm is None or kind not in ('clock', 'reset', 'enable'):
            return ''
        s = next((s for s in vm.signals if s.category == kind), None)
        return s.name if s else ''

    def point_caption(self, kind: str) -> str:
        vm = self.view_model
        if vm is None:
            return ''
        if kind in ('clock', 'reset', 'enable'):
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

    def hds_geometry(self, tid: str) -> dict | None:
        """The drawn line of a transition, for writing an HDS file (None: not on this scene)."""
        it = self.trans_items.get(tid)
        return it.hds_geometry() if it is not None and getattr(it, 'ends', None) else None

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
        self._clear_state_ghost()
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
            item = StateItem(self, s)
            self._add_node_item(item)
            # as HDS 2021.1: the new state is selected (Add State stays active)
            self.clearSelection()
            item.setSelected(True)
        elif self.mode in ('junction_if', 'junction_case'):
            kind = 'case' if self.mode == 'junction_case' else 'if'
            j = Junction(id=m.new_id('j'), kind=kind, expr='expr' if kind == 'case' else '', x=pos.x(), y=pos.y(),
                         symbol=getattr(self.view_model, 'default_junction_symbol', ''))
            m.junctions.append(j)
            item = JunctionItem(self, j)
            self._add_node_item(item)
            self.clearSelection(); item.setSelected(True)       # as HDS: the new junction is selected
        elif self.mode == 'link':
            # As HDS 2021.1: no question asked, the link shows "Link" until its target state is
            # set (Object Properties / double-click); the cursor is on its stub tip
            lk = Link(id=m.new_id('l'), target='Link', x=pos.x() + LINK_TIP, y=pos.y())
            m.links.append(lk)
            item = LinkItem(self, lk)
            self._add_node_item(item)
            self.clearSelection(); item.setSelected(True)
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
                self._rubber.setPen(QPen(Qt.black, 0))      # HDS: a thin solid line
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
            # as HDS 2021.1: the condition is typed in place right away
            self.condition_edit_requested.emit(t)
            return
        self.changed_model.emit()

    def _clear_state_ghost(self):
        g = getattr(self, '_state_ghost', None)
        if g is not None:
            self.removeItem(g)
            self._state_ghost = None

    def _update_state_ghost(self, pos: QPointF):
        """While adding a state, a junction or a link, its outline (no fill) follows the cursor
        on the grid, as HDS shows it: a circle / diamond centred on the cursor, a link with the
        tip of its stub on it. Not part of the model; set_mode() removes it."""
        kind = self.mode if self.mode in ('state', 'junction_if', 'junction_case', 'link') else None
        if kind == 'junction_case':
            kind = 'junction_if'
        g = getattr(self, '_state_ghost', None)
        if kind is None or self.readonly:
            self._clear_state_ghost()
            return
        if g is not None and g.data(0) != kind:
            self._clear_state_ghost()
            g = None
        if g is None:
            if kind == 'state':
                g = QGraphicsEllipseItem(-STATE_R, -STATE_R, 2 * STATE_R, 2 * STATE_R)
            elif kind == 'junction_if':
                g = QGraphicsPolygonItem(QPolygonF([QPointF(0, -9), QPointF(9, 0), QPointF(0, 9), QPointF(-9, 0)]))
            else:                       # the link body (as LinkItem) with its stub on the left
                path = QPainterPath()
                path.addPolygon(QPolygonF([QPointF(-12, -6), QPointF(6, -6), QPointF(12, 0), QPointF(6, 6),
                                           QPointF(-12, 6), QPointF(-12, -6)]))
                path.moveTo(-12, 0); path.lineTo(-LINK_TIP, 0)
                g = QGraphicsPathItem(path)
            g.setData(0, kind)
            g.setPen(QPen(Qt.black, 0)); g.setBrush(Qt.NoBrush)
            g.setAcceptedMouseButtons(Qt.NoButton)
            g.setZValue(50)
            self.addItem(g)
            self._state_ghost = g
        p = snap_point(pos)
        if kind == 'link':
            p = QPointF(p.x() + LINK_TIP, p.y())   # the stub tip on the cursor
        self._state_ghost.setPos(p)

    def mouseMoveEvent(self, event):
        self._update_state_ghost(event.scenePos())
        if self._pending_src is not None and self._rubber is not None:
            path = QPainterPath(self._pending_src.scenePos())
            for x, y in self._pending_pts:
                path.lineTo(x, y)
            path.lineTo(event.scenePos())
            self._rubber.setPath(path)
        super().mouseMoveEvent(event)

    def _unique_state_name(self) -> str:
        """Name of a new state, as HDS 2021.1 names it from the diagram's default-state template:
          - a template ending in a number ("s0", the template of a new HDS diagram): its prefix
            and the smallest free number from there ("s0", "s1", ...; "s0" again once renamed);
          - another template ("ST_"): the template itself, then "ST_1", "ST_2", ...;
          - no template (diagrams made by Dolphin): as a new HDS diagram, "s0", "s1", ..."""
        import re
        names = {s.name for s in self.machine.states}
        base = getattr(getattr(self, 'view_model', None), 'default_state_name', '') or 's0'
        m = re.fullmatch(r'(.*?)(\d+)', base)
        if m:
            prefix, i = m.group(1), int(m.group(2))
            while f'{prefix}{i}' in names:
                i += 1
            return f'{prefix}{i}'
        if base not in names:
            return base
        i = 1
        while f'{base}{i}' in names:
            i += 1
        return f'{base}{i}'

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
        p.setPen(QPen(QColor(103, 103, 103), 0))      # HDS grid dots: one dark grey pixel
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
