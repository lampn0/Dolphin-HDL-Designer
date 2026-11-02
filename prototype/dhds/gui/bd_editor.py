"""Block diagram editor.

Select and drag components, embedded blocks and ports (attached wires follow
and stay orthogonal), add components from the project, draw wires between
pins/ports, add ports and embedded HDL blocks, rename nets, delete, undo/redo.
"""
from __future__ import annotations

import os
import re

from PySide6.QtCore import QEvent, QLineF, QPoint, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QAction, QActionGroup, QBrush, QColor, QFont, QKeySequence, QPainter, QPainterPath,
                           QPainterPathStroker, QPen, QPolygonF)
from PySide6.QtWidgets import (QApplication, QGraphicsSimpleTextItem, QComboBox, QDialog, QDialogButtonBox, QDockWidget, QFormLayout, QGraphicsItem,
                               QGraphicsPathItem, QGraphicsScene, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
                               QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QToolBar, QVBoxLayout, QWidget)

from ..bd_model import BdEmbedded, BdFrame, BdInstance, BdPin, BdPortIo, BdWire, BlockDiagram
from ..codegen.bd_codegen import generate_bd
from ..model import LANGUAGES, Parameter, Signal as Sig
from .bd_dialogs import PortIoPropertiesDialog, port_label
from .bd_dialogs import ComponentPicker, ComponentPropertiesDialog, SignalPropertiesDialog, library_of_file
from .code_view import CodeView
from .diagram import FsmGraphicsView
from .icons import icon
from .menus import BD_MENUS, arrange_menus
from .toolbars import BD_KEYS, BD_TOOLBAR, build_toolbar
from .tables import ParametersTable, SignalsTable
from .undo import SnapshotUndo, load_view_state, save_view_state

MONO = QFont('Courier New', 8)
BOLD = QFont('Courier New', 8, QFont.Bold)
LANG_LABEL = {'systemverilog': 'SystemVerilog', 'verilog': 'Verilog 2005'}
BLOCK_FILL = QColor(0, 230, 0)
EMB_FILL = QColor(255, 255, 160)
SEL_PEN = QPen(QColor(255, 120, 0), 2.5)
PIN_GRAB = 6.0
from .diagram import GRID      # the legacy grid (1000 database units), shared with the state diagram
PORT_EDGE = GRID    # half width of a PortIO: body + stub span two grid squares, nets attach at the stub end
HANDLE_PX = 6.0     # selection handles keep this size on screen, whatever the zoom
PIN_HALF = 0.375 * GRID     # a component port is a triangle 0.75 grid long, from the body edge outward
_OUT = {'left': (-1, 0), 'right': (1, 0), 'top': (0, -1), 'bottom': (0, 1)}


def pin_end(pin) -> list[float]:
    """Where a net meets a component port: the outer end of its triangle (base or apex)."""
    o = _OUT[pin.side]
    return [pin.x + o[0] * PIN_HALF, pin.y + o[1] * PIN_HALF]


def _px(painter_or_view) -> float:
    """Scene units per screen pixel for a painter (item paint) or a view."""
    t = painter_or_view.worldTransform() if hasattr(painter_or_view, 'worldTransform') \
        else painter_or_view.transform()
    return 1.0 / max(abs(t.m11()), 1e-6)


def _scene_px(scene) -> float:
    views = scene.views() if scene is not None else []
    return _px(views[0]) if views else 1.0
PIN_STEP = GRID     # spacing of pins on new components, one grid apart as in the legacy editor


def _pen(color: str, width: float, style: str) -> QPen:
    if width <= 0:
        return QPen(Qt.NoPen)
    return QPen(QColor(color), width, {'dash': Qt.DashLine, 'dot': Qt.DotLine}.get(style, Qt.SolidLine))


_FILL = {'solid': Qt.SolidPattern, 'dense': Qt.Dense3Pattern, 'medium': Qt.Dense5Pattern,
         'sparse': Qt.Dense7Pattern, 'horizontal': Qt.HorPattern, 'vertical': Qt.VerPattern, 'cross': Qt.CrossPattern,
         'diagonal': Qt.BDiagPattern, 'diagonal cross': Qt.DiagCrossPattern}


def _fill(p: QPainter, rect: QRectF, fg: str, bg: str, style: str):
    """Fill pattern: foreground pattern over the background colour; 'none' is transparent."""
    if style == 'none':
        return
    if style != 'solid':
        p.fillRect(rect, QColor(bg))
    p.fillRect(rect, QBrush(QColor(fg), _FILL.get(style, Qt.SolidPattern)))


def _snap(v: float) -> float:
    return round(v / GRID) * GRID


# ---------------------------------------------------------------------------
# Items
# ---------------------------------------------------------------------------
class _Movable(QGraphicsItem):
    kind = ''

    def __init__(self, scene: 'BdScene', obj):
        super().__init__()
        self.bd_scene = scene
        self.obj = obj
        self.setPos(obj.x, obj.y)       # before ItemSendsGeometryChanges: no snapping on load
        self.setFlags(QGraphicsItem.ItemIsSelectable | QGraphicsItem.ItemIsMovable |
                      QGraphicsItem.ItemSendsGeometryChanges)
        self.setZValue(2)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionChange:
            if self.bd_scene.readonly:
                return self.pos()
            if self.bd_scene.following or self.bd_scene.group:
                return value                # carried along by another object: keep its offset
            return QPointF(_snap(value.x()), _snap(value.y()))
        if change == QGraphicsItem.ItemPositionHasChanged:
            dx, dy = self.pos().x() - self.obj.x, self.pos().y() - self.obj.y
            if dx or dy:
                self.obj.x, self.obj.y = self.pos().x(), self.pos().y()
                if not self.bd_scene.following:
                    self.bd_scene.object_moved(self, dx, dy)
        return super().itemChange(change, value)

    def mouseReleaseEvent(self, event):
        moved = event.buttonDownScenePos(Qt.LeftButton) != event.scenePos()
        super().mouseReleaseEvent(event)
        if self.kind == 'pio':
            self.bd_scene.end_routing()
        if moved:
            if self.kind == 'pio':
                self.bd_scene.port_dropped.emit(self.obj)
            self.bd_scene.changed_model.emit()


class InstanceItem(_Movable):
    """Component instance. A click on one of its ports selects that port; dragging the
    port slides it along the edge of the component, and its net follows."""
    kind = 'inst'

    def __init__(self, scene, obj):
        super().__init__(scene, obj)
        self._pin_drag = None       # (pin, press position, original x, y) while moving a port

    def boundingRect(self):
        extra = len(self.obj.params) * 10 + 4 if self.obj.show_params else 0
        return QRectF(-90, -6, self.obj.w + 180, self.obj.h + 12 + extra)

    def shape(self):
        p = QPainterPath()
        p.addRect(QRectF(0, 0, self.obj.w, self.obj.h))
        for pin in self.obj.pins:               # the ports stick out of the body: make them clickable
            p.addRect(QRectF(pin.x - self.obj.x - PIN_GRAB, pin.y - self.obj.y - PIN_GRAB, 2 * PIN_GRAB, 2 * PIN_GRAB))
        return p

    def pin_at(self, pos: QPointF) -> BdPin | None:
        return next((pin for pin in self.obj.pins
                     if abs(pin.x - pos.x()) <= PIN_GRAB and abs(pin.y - pos.y()) <= PIN_GRAB), None)

    def pin_target(self, pin: BdPin, x0: float, y0: float, side0: str, dx: float, dy: float
                   ) -> tuple[float, float, str]:
        """Where a port dragged by (dx, dy) from (x0, y0) lands: on the nearest edge of the body
        (any of the four), on the grid, keeping its distance outside the edge."""
        o = self.obj
        gap = {'left': o.x - x0, 'right': x0 - (o.x + o.w), 'top': o.y - y0, 'bottom': y0 - (o.y + o.h)}[side0]
        px, py = _snap(x0 + dx), _snap(y0 + dy)
        inside_x = min(max(px, o.x + 4), o.x + o.w - 4)
        inside_y = min(max(py, o.y + 4), o.y + o.h - 4)
        dist = {'left': abs(px - o.x), 'right': abs(px - (o.x + o.w)), 'top': abs(py - o.y),
                'bottom': abs(py - (o.y + o.h))}
        side = min(dist, key=lambda k: (dist[k], k != side0))
        if side == 'left':
            return o.x - gap, inside_y, side
        if side == 'right':
            return o.x + o.w + gap, inside_y, side
        if side == 'top':
            return inside_x, o.y - gap, side
        return inside_x, o.y + o.h + gap, side

    def mousePressEvent(self, e):
        sc = self.bd_scene
        pin = self.pin_at(e.scenePos()) if e.button() == Qt.LeftButton and sc.mode == 'select' else None
        if pin is None:
            return super().mousePressEvent(e)
        sc.clearSelection()
        sc.select_pin(self, pin)
        if not sc.readonly:
            self._pin_drag = (pin, e.scenePos(), pin.x, pin.y, pin.side)
        e.accept()

    def mouseMoveEvent(self, e):
        if self._pin_drag is None:
            return super().mouseMoveEvent(e)
        pin, p0, x0, y0, side0 = self._pin_drag
        d = e.scenePos() - p0
        if e.modifiers() & Qt.ShiftModifier:
            d = QPointF(d.x(), 0) if abs(d.x()) >= abs(d.y()) else QPointF(0, d.y())
        self.bd_scene.move_pin(self, pin, *self.pin_target(pin, x0, y0, side0, d.x(), d.y()))

    def mouseReleaseEvent(self, e):
        if self._pin_drag is None:
            return super().mouseReleaseEvent(e)
        pin, _, x0, y0, _ = self._pin_drag
        self._pin_drag = None
        if (pin.x, pin.y) != (x0, y0):
            self.bd_scene.changed_model.emit()

    def paint(self, p: QPainter, opt, widget=None):
        o = self.obj
        _fill(p, QRectF(0, 0, o.w, o.h), o.fg, o.bg, o.fill_style)
        p.setBrush(Qt.NoBrush)
        p.setPen(SEL_PEN if self.isSelected() else _pen(o.line_color, 1.5 * o.line_width, o.line_style))
        p.drawRect(QRectF(0, 0, o.w, o.h))
        p.setFont(BOLD)
        p.setPen(Qt.black)
        y = 3
        if o.show_library:
            p.drawText(QRectF(0, y, o.w, 11), Qt.AlignHCenter, o.library)
            y += 10
        p.drawText(QRectF(0, y, o.w, 11), Qt.AlignHCenter, o.unit)
        if o.show_instance:
            p.drawText(QRectF(0, y + 10, o.w, 11), Qt.AlignHCenter, o.name)
        p.setFont(MONO)
        fm = p.fontMetrics()
        if o.show_params and o.params:
            p.setPen(QColor(0, 0, 160))
            for k, prm in enumerate(o.params):
                p.drawText(QPointF(4, o.h + 10 + k * 10), f'{prm.name} = {prm.value}')
            p.setPen(Qt.black)
        for pin in o.pins:
            lx, ly = pin.x - o.x, pin.y - o.y
            p.setPen(QPen(QColor(0, 100, 0), 1))
            p.setBrush(QColor(0, 160, 0) if pin.net else QColor(255, 255, 255))
            if pin.side in ('left', 'right'):
                inward = 1 if pin.side == 'left' else -1
                d = inward if (pin.mode == 'input') == (pin.side == 'left') else -inward
                t = PIN_HALF
                p.drawPolygon(QPolygonF([QPointF(lx - t * d, ly - t), QPointF(lx + t * d, ly),
                                         QPointF(lx - t * d, ly + t)]))
                p.setPen(Qt.black)
                text = port_label(pin.name, 'wire', False, pin.bounds, '', o)
                if pin.side == 'left':
                    p.drawText(QPointF(lx + t + 2, ly + 3), text)
                else:
                    p.drawText(QPointF(lx - t - 2 - fm.horizontalAdvance(text), ly + 3), text)
            else:
                inward = 1 if pin.side == 'top' else -1
                d = inward if pin.mode == 'input' else -inward
                t = PIN_HALF
                p.drawPolygon(QPolygonF([QPointF(lx - t, ly - t * d), QPointF(lx, ly + t * d),
                                         QPointF(lx + t, ly - t * d)]))
                p.setPen(Qt.black)
                text = port_label(pin.name, 'wire', False, pin.bounds, '', o)
                p.save()                        # names of top/bottom ports run along the port, inside the body
                if pin.side == 'top':
                    p.translate(lx + 3, ly + 7); p.rotate(90)
                else:
                    p.translate(lx + 3, ly - 7); p.rotate(-90)
                p.drawText(QPointF(0, 0), text)
                p.restore()
        sel = self.bd_scene.selected_pin
        if sel is not None and sel[0] == o.id:
            pin = next((q for q in o.pins if q.name == sel[1]), None)
            if pin is not None:
                px = _px(p)
                p.setPen(QPen(Qt.black, 0)); p.setBrush(Qt.white)
                lx, ly = pin.x - o.x, pin.y - o.y
                d, s = 6 * px, 4 * px
                for cx, cy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
                    p.drawRect(QRectF(lx + cx * d - s / 2, ly + cy * d - s / 2, s, s))


class FrameItem(_Movable):
    """Generate frame (FOR / IF / ELSE): dashed box with its title; picked by its border
    or title so the objects inside stay clickable. Moving it moves what is inside."""
    kind = 'frame'

    HANDLE = 5.0

    def __init__(self, scene, obj):
        super().__init__(scene, obj)
        self.setZValue(0)
        self._resize = None         # (handle, original rect, press position) while resizing

    def _handles(self) -> dict[str, QPointF]:
        w, h = self.obj.w, self.obj.h
        return {'tl': QPointF(0, 0), 't': QPointF(w / 2, 0), 'tr': QPointF(w, 0), 'r': QPointF(w, h / 2),
                'br': QPointF(w, h), 'b': QPointF(w / 2, h), 'bl': QPointF(0, h), 'l': QPointF(0, h / 2)}

    def _handle_at(self, pos: QPointF) -> str | None:
        if not self.isSelected():
            return None
        tol = (HANDLE_PX / 2 + 2) * _scene_px(self.scene())
        for k, c in self._handles().items():
            if abs(c.x() - pos.x()) <= tol and abs(c.y() - pos.y()) <= tol:
                return k
        return None

    def mousePressEvent(self, e):
        k = self._handle_at(e.pos()) if e.button() == Qt.LeftButton and not self.bd_scene.readonly else None
        if k is None:
            return super().mousePressEvent(e)
        self._resize = (k, QRectF(self.obj.x, self.obj.y, self.obj.w, self.obj.h), e.scenePos())
        e.accept()

    def mouseMoveEvent(self, e):
        if self._resize is None:
            return super().mouseMoveEvent(e)
        k, r0, p0 = self._resize
        dx, dy = _snap(e.scenePos().x() - p0.x()), _snap(e.scenePos().y() - p0.y())
        left, top, right, bottom = r0.left(), r0.top(), r0.right(), r0.bottom()
        if 'l' in k:
            left = min(left + dx, right - 40)
        if 'r' in k:
            right = max(right + dx, left + 40)
        if k.startswith('t'):
            top = min(top + dy, bottom - 30)
        if k.startswith('b'):
            bottom = max(bottom + dy, top + 30)
        self.prepareGeometryChange()
        o = self.obj
        o.w, o.h = right - left, bottom - top
        self.bd_scene.following = True          # resizing moves the frame, not what is inside
        try:
            self.setPos(left, top)
        finally:
            self.bd_scene.following = False
        o.x, o.y = left, top
        self.update()

    def mouseReleaseEvent(self, e):
        if self._resize is None:
            return super().mouseReleaseEvent(e)
        r0 = self._resize[1]
        self._resize = None
        if QRectF(self.obj.x, self.obj.y, self.obj.w, self.obj.h) != r0:
            self.bd_scene.changed_model.emit()

    def _title_rect(self) -> QRectF:
        return QRectF(0, -16, max(80.0, len(self.obj.title) * 7.0 + 10), 15)

    def boundingRect(self):
        o = self.obj
        return QRectF(-6, -18, max(o.w, self._title_rect().width()) + 12, o.h + 24)

    def shape(self):
        path = QPainterPath()
        if self.obj.show_label:
            path.addRect(self._title_rect())
        if self.isSelected():
            for c in self._handles().values():
                path.addRect(QRectF(c.x() - self.HANDLE, c.y() - self.HANDLE, 2 * self.HANDLE, 2 * self.HANDLE))
        stroke = QPainterPathStroker()
        stroke.setWidth(8)
        rect = QPainterPath()
        rect.addRect(QRectF(0, 0, self.obj.w, self.obj.h))
        return path.united(stroke.createStroke(rect))

    def paint(self, p: QPainter, opt, widget=None):
        o = self.obj
        color = {'for': QColor(70, 70, 70), 'if': QColor(0, 90, 170), 'else': QColor(150, 60, 0)}.get(o.kind)
        p.setPen(QPen(color, 1.6, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(0, 0, o.w, o.h))
        if o.show_number:
            p.setPen(Qt.black)
            p.setBrush(Qt.white)
            p.drawRect(QRectF(4, 4, 12, 12))
            p.setFont(MONO)
            p.drawText(QRectF(4, 4, 12, 12), Qt.AlignCenter, str(o.number))
        if o.show_label:
            p.setFont(BOLD)
            p.setPen(color)
            p.drawText(QPointF(1, -4), o.title)
        if self.isSelected():                   # black handles, as in the legacy editor
            p.setPen(Qt.NoPen)
            p.setBrush(Qt.black)
            r = HANDLE_PX * _px(p) / 2
            for c in self._handles().values():
                p.drawRect(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r))

    def mouseDoubleClickEvent(self, e):
        self.bd_scene.frame_edit_requested.emit(self.obj)


class EmbeddedItem(_Movable):
    kind = 'emb'

    def boundingRect(self):
        return QRectF(0, 0, max(self.obj.w, 60), max(self.obj.h, 30))

    def paint(self, p: QPainter, opt, widget=None):
        r = self.boundingRect()
        p.setBrush(EMB_FILL)
        p.setPen(SEL_PEN if self.isSelected() else QPen(QColor(0, 0, 120), 1.2))
        p.drawRect(r)
        p.setFont(BOLD)
        p.setPen(Qt.black)
        p.drawText(QPointF(4, 11), f'{self.obj.name}  ({self.obj.number})')
        p.setFont(MONO)
        y = 25
        for line in self.obj.text.strip('\n').split('\n'):
            if y > r.height() - 3:
                break
            p.drawText(QPointF(8, y), line)
            y += 10


class PortIoItem(_Movable):
    kind = 'pio'

    def boundingRect(self):
        return QRectF(-260, -9, 520, 18)

    def shape(self):
        p = QPainterPath()
        h = 0.375 * GRID
        p.addRect(QRectF(-PORT_EDGE, -h, 2 * PORT_EDGE, 2 * h))
        return p

    def paint(self, p: QPainter, opt, widget=None):
        o = self.obj
        p.setBrush(QColor(255, 120, 0) if self.isSelected() else
                   QBrush(QColor(o.fg), _FILL[o.fill_style]) if o.fill_style in _FILL else Qt.NoBrush)
        p.setPen(Qt.NoPen if o.line_color == '#000000' and o.fill_style == 'solid'
                 else _pen(o.line_color, o.line_width, o.line_style))
        e, h = PORT_EDGE, 0.375 * GRID
        side = self.bd_scene.port_side(o)           # the net is on this side: the stub points to it
        body_l, body_r = (-e, e / 2) if side > 0 else (-e / 2, e)
        p.drawPolygon(QPolygonF([QPointF(body_l, -h), QPointF(body_r - h, -h), QPointF(body_r, 0),
                                 QPointF(body_r - h, h), QPointF(body_l, h)]))
        stub = QPen(QColor(o.line_color), 1)
        stub.setCosmetic(True)
        p.setPen(stub)
        p.drawLine(QPointF(e / 2 * side, 0), QPointF(e * side, 0))
        sig = next((s for s in self.bd_scene.bd.signals if s.name == o.name), None)
        text = port_label(o.name, sig.type if sig else 'wire', bool(sig and sig.signed), sig.bounds if sig else '',
                          sig.delay if sig else '', dict(text_name=o.show_text, text_type=o.text_type,
                                                         text_type_name=o.text_type_name,
                                                         text_signed=o.text_signed, text_value=o.text_value))
        if not text:
            return
        p.setPen(Qt.black)
        p.setFont(MONO)
        w = p.fontMetrics().horizontalAdvance(text)
        # the name goes on the side away from the net
        if self.bd_scene.port_side(o) > 0:
            p.drawText(QPointF(-e - 3 - w, 3), text)
        else:
            p.drawText(QPointF(e + 3, 3), text)


class WireItem(QGraphicsPathItem):
    """One net segment chain. As in the legacy editor: drag moves the net (ends
    attached to pins/ports stay and the route stretches), Alt+drag moves only
    the segment under the cursor, and the square handles of a selected net move
    its route points. Double-click edits the net name in place."""

    def __init__(self, scene: 'BdScene', w: BdWire):
        super().__init__()
        self.bd_scene = scene
        self.obj = w
        self.setFlags(QGraphicsItem.ItemIsSelectable)
        self.setZValue(1)
        self._drag = None           # (kind, index, original points, press position)
        self._end_origin = None     # port under a dragged net end: (pin or None, x, y, side)
        self._net_ends = None       # component ports of a dragged net, with their start positions
        self._pio_start: dict[str, tuple[float, float]] = {}
        self.refresh()

    def refresh(self):
        self.prepareGeometryChange()
        path = QPainterPath()
        pts = self.obj.points
        if pts:
            path.moveTo(*pts[0])
            for x, y in pts[1:]:
                path.lineTo(x, y)
        self.setPath(path)
        self.setToolTip(self.obj.net)

    def shape(self):
        s = QPainterPathStroker()
        s.setWidth(8)
        return s.createStroke(self.path())

    def boundingRect(self):
        m = max(10.0, HANDLE_PX * _scene_px(self.scene()))
        return super().boundingRect().adjusted(-120, -m, 120, m)

    def paint(self, p: QPainter, opt, widget=None):
        bus = self.bd_scene.is_bus(self.obj.net)
        if self.bd_scene.highlight and self.obj.net == self.bd_scene.highlight:
            pen = QPen(QColor(255, 0, 200), 3)
        elif self.isSelected():
            pen = QPen(Qt.black, 2 if bus else 1)         # a selected net shows its handles, as in HDS
        else:
            pen = QPen(Qt.black, 2 if bus else 1)
        pen.setCosmetic(True)                   # widths in screen pixels, like the legacy editor
        p.setPen(pen)
        p.drawPath(self.path())
        pts = self.obj.points
        if not pts:
            return
        p.setFont(MONO)
        for end, ref in ((pts[0], self.obj.start), (pts[-1], self.obj.end)):
            if not ref:
                # dangling end: net connector
                p.setPen(QPen(QColor(220, 0, 0), 1))
                p.setBrush(Qt.white)
                p.drawEllipse(QPointF(*end), 3, 3)
        if self.obj.show_text:
            p.setPen(Qt.black)
            p.drawText(self.label_pos(p.fontMetrics().horizontalAdvance(self.obj.net)), self.obj.net)

        if self.isSelected():
            # route point handles (black squares, as in the legacy editor)
            p.setPen(Qt.NoPen)
            p.setBrush(Qt.black)
            r = HANDLE_PX * _px(p) / 2
            for x, y in pts:
                p.drawRect(QRectF(x - r, y - r, 2 * r, 2 * r))

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemSelectedHasChanged:
            self.setZValue(6 if value else 1)   # a selected net's handles win over objects under them
        return super().itemChange(change, value)

    def label_pos(self, text_w: float) -> QPointF:
        """Baseline of the net name: stored offset, else next to a dangling end, else near the start."""
        pts = self.obj.points
        if self.obj.label is not None:
            return QPointF(pts[0][0] + self.obj.label[0], pts[0][1] + self.obj.label[1])
        for end, ref, nxt in ((pts[0], self.obj.start, pts[1] if len(pts) > 1 else pts[0]),
                              (pts[-1], self.obj.end, pts[-2] if len(pts) > 1 else pts[-1])):
            if not ref:
                return QPointF(end[0] + (4 if end[0] < nxt[0] else -4 - text_w), end[1] - 3)
        a, b = pts[0], pts[1] if len(pts) > 1 else pts[0]
        return QPointF(min(a[0], b[0]) + 8, a[1] - 3)

    # dragging --------------------------------------------------------------------
    def _handle_at(self, pos: QPointF) -> int | None:
        if not self.isSelected():
            return None
        tol = (HANDLE_PX / 2 + 2) * _scene_px(self.scene())
        for k, (x, y) in enumerate(self.obj.points):
            if abs(x - pos.x()) <= tol and abs(y - pos.y()) <= tol:
                return k
        return None

    def _segment_at(self, pos: QPointF) -> int:
        best, idx = 1e9, 0
        for k, (a, b) in enumerate(zip(self.obj.points, self.obj.points[1:])):
            d = QLineF(QPointF(*a), QPointF(*b))
            if d.length() < 1e-6:
                continue
            t = max(0.0, min(1.0, QPointF.dotProduct(pos - d.p1(), d.p2() - d.p1()) / d.length() ** 2))
            dist = QLineF(pos, d.pointAt(t)).length()
            if dist < best:
                best, idx = dist, k
        return idx

    def mousePressEvent(self, e):
        super().mousePressEvent(e)
        if e.button() != Qt.LeftButton or self.bd_scene.readonly or self.bd_scene.mode != 'select' \
                or e.modifiers() & Qt.ControlModifier or len(self.obj.points) < 2:
            return
        pos = e.scenePos()
        k = self._handle_at(pos)
        if k is not None:
            kind = 'point'
        elif e.modifiers() & Qt.AltModifier:
            kind, k = 'segment', self._segment_at(pos)
        else:
            kind = 'net'
        self._drag = (kind, k, [list(q) for q in self.obj.points], pos)

    def mouseMoveEvent(self, e):
        if self._drag is None:
            return super().mouseMoveEvent(e)
        kind, k, orig, start = self._drag
        dx, dy = _snap(e.scenePos().x() - start.x()), _snap(e.scenePos().y() - start.y())
        if e.modifiers() & Qt.ShiftModifier:       # constrain to horizontal or vertical
            dx, dy = (dx, 0.0) if abs(dx) >= abs(dy) else (0.0, dy)
        w = self.obj
        if kind == 'point':
            pts = [list(q) for q in orig]
            ref = w.start if k == 0 else w.end if k == len(pts) - 1 else ''
            if ref:
                self._move_attached_end(ref, k, dx, dy)
                return
            pts[k] = [_snap(orig[k][0] + dx), _snap(orig[k][1] + dy)]
            w.points = pts
        elif kind == 'segment':
            w.points = _move_segment(orig, k, dx, dy, bool(w.start), bool(w.end))
        else:
            ends = self._component_ends() if self._net_ends is None else self._net_ends
            self._net_ends = ends
            if ends:
                # the net is moved through the component ports it is on, as when moving those ports
                for owner, pin, x0, y0, side0 in ends:
                    self.bd_scene.move_pin(owner, pin, *owner.pin_target(pin, x0, y0, side0, dx, dy), carry=True)
            else:
                w.points = [[x + dx, y + dy] for x, y in orig]       # PortIOs and connectors only
                for ref in (w.start, w.end):
                    owner = self.bd_scene.owner_of(ref) if ref else None
                    if owner is not None:
                        ox, oy = self._pio_origin(owner)
                        self.bd_scene.following = True
                        try:
                            owner.setPos(QPointF(ox + dx, oy + dy))
                        finally:
                            self.bd_scene.following = False
        self.refresh()

    def _move_attached_end(self, ref: str, k: int, dx: float, dy: float):
        """Dragging the end of a net that sits on a component port or a PortIO moves that port."""
        sc = self.bd_scene
        owner = sc.owner_of(ref)
        if owner is None:
            return
        if self._end_origin is None:
            pin = next((q for q in owner.obj.pins if f'pin:{owner.obj.id}:{q.name}' == ref), None) \
                if isinstance(owner, InstanceItem) else None
            self._end_origin = (pin, pin.x, pin.y, pin.side) if pin is not None else \
                (None, owner.obj.x, owner.obj.y, '')
        pin, x0, y0, side0 = self._end_origin
        if pin is not None:
            sc.move_pin(owner, pin, *owner.pin_target(pin, x0, y0, side0, dx, dy))
        else:
            owner.setPos(QPointF(x0 + dx, y0 + dy))     # a PortIO: its nets follow it

    def _component_ends(self) -> list[tuple['InstanceItem', BdPin, float, float, str]]:
        sc, out = self.bd_scene, []
        for ref in (self.obj.start, self.obj.end):
            owner = sc.owner_of(ref) if ref.startswith('pin:') else None
            pin = next((q for q in owner.obj.pins if f'pin:{owner.obj.id}:{q.name}' == ref), None) if owner else None
            if pin is not None:
                out.append((owner, pin, pin.x, pin.y, pin.side))
        return out

    def _pio_origin(self, owner) -> tuple[float, float]:
        return self._pio_start.setdefault(owner.obj.id, (owner.obj.x, owner.obj.y))

    def mouseReleaseEvent(self, e):
        drag, self._drag = self._drag, None
        self._end_origin = None
        self._net_ends = None
        self._pio_start = {}
        super().mouseReleaseEvent(e)
        if drag is None or self.obj.points == drag[2]:
            return
        self.obj.points = _simplify(self.obj.points)
        self.refresh()
        if drag[0] == 'point':
            self.bd_scene.end_dropped.emit(self.obj)
        self.bd_scene.changed_model.emit()



# ---------------------------------------------------------------------------
# Scene
# ---------------------------------------------------------------------------
class BdScene(QGraphicsScene):
    changed_model = Signal()
    message = Signal(str)
    rename_net_requested = Signal(str)
    edit_net_requested = Signal(str, QPointF)      # in-place edit of a net name at a scene position
    port_dropped = Signal(object)                  # a port was moved (may land on a net end)
    frame_edit_requested = Signal(object)          # double-click on a frame title
    end_dropped = Signal(object)                   # a dangling net end was moved (may land on a pin/port)
    place_requested = Signal(QPointF)
    context_requested = Signal(object, object, QPointF)     # item (or None), screen pos, scene pos

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setBackgroundBrush(QColor(252, 252, 252))
        self.bd = BlockDiagram()
        self.highlight = ''          # net drawn highlighted
        self.following = False       # True while objects are carried along by a move
        self.group: set = set()      # objects moved together with a frame
        self.selected_pin: tuple[str, str] | None = None   # (instance id, port) selected on a component
        self.route_mode = ROUTE_MODES[0]     # routing of the nets of a dragged PortIO ('z' changes it)
        self._routing: dict[str, tuple[BdWire, str, BdPortIo]] = {}
        self._hint = None
        self.readonly = False
        self.mode = 'select'
        self.items_by_id: dict[str, _Movable] = {}
        self.wire_items: dict[str, WireItem] = {}
        self._wire_start: tuple[str, QPointF] | None = None
        self._wire_pts: list[list[float]] = []
        self._rubber: QGraphicsPathItem | None = None

    # building ------------------------------------------------------------------
    def load(self, bd: BlockDiagram):
        self.clear()
        self._hint = None
        self._routing = {}
        self._rubber = None
        self.bd = bd
        self.items_by_id.clear()
        self.wire_items.clear()
        for w in bd.wires:
            self._add_wire(w)
        for inst in bd.instances:
            self._add(InstanceItem(self, inst))
        for eb in bd.embedded:
            self._add(EmbeddedItem(self, eb))
        for pio in bd.port_ios:
            self._add(PortIoItem(self, pio))
        for fr in bd.frames:
            self._add(FrameItem(self, fr))
        self._attach_port_ends()
        self.setSceneRect(self.itemsBoundingRect().adjusted(-600, -600, 600, 600))

    def _add(self, item: _Movable):
        self.addItem(item)
        self.items_by_id[item.obj.id] = item

    def _add_wire(self, w: BdWire):
        it = WireItem(self, w)
        self.addItem(it)
        self.wire_items[w.id] = it

    def is_bus(self, net: str) -> bool:
        return any(s.name == net and s.bounds for s in self.bd.signals)

    # geometry helpers ------------------------------------------------------------
    def _ref_of(self, item: _Movable) -> str:
        # wires reference instance pins as "pin:<instance id>:<pin>"
        return f'{"pin" if item.kind == "inst" else item.kind}:{item.obj.id}'

    def _attached(self, ref_prefix: str):
        for w in self.bd.wires:
            for which in ('start', 'end'):
                r = getattr(w, which)
                if r == ref_prefix or r.startswith(ref_prefix + ':'):
                    yield w, which

    # ports ---------------------------------------------------------------------
    def port_side(self, pio: BdPortIo) -> int:
        """+1 when the port's net leaves to the right, -1 to the left (no net: by mode)."""
        for w, which in self._attached(f'pio:{pio.id}'):
            pts = w.points
            if len(pts) > 1:
                nxt = pts[1] if which == 'start' else pts[-2]
                if abs(nxt[0] - pio.x) > 0.01:
                    return 1 if nxt[0] > pio.x else -1
        return 1 if pio.mode == 'input' else -1

    def port_edge(self, pio: BdPortIo, side: int | None = None) -> list[float]:
        side = self.port_side(pio) if side is None else side
        return [pio.x + side * PORT_EDGE, pio.y]

    def _attach_port_ends(self):
        """Net ends attached to a port touch the port icon, and those on a component port
        touch the port (legacy diagrams leave a small gap). Done once, when the diagram is loaded."""
        for inst in self.bd.instances:
            for pin in inst.pins:
                for w, which in list(self._attached(f'pin:{inst.id}:{pin.name}')):
                    end = w.points[0] if which == 'start' else w.points[-1]
                    tip = pin_end(pin)
                    dx, dy = tip[0] - end[0], tip[1] - end[1]
                    if (abs(dx) > 0.01 or abs(dy) > 0.01) and abs(dx) + abs(dy) <= 3 * GRID:
                        _shift_end(w, which, dx, dy)
                        w.points = _simplify(w.points)
                        if which == 'start' and w.label is not None:
                            w.label = [w.label[0] - dx, w.label[1] - dy]
                        if w.id in self.wire_items:
                            self.wire_items[w.id].refresh()
        for pio in self.bd.port_ios:
            edge = self.port_edge(pio)
            for w, which in list(self._attached(f'pio:{pio.id}')):
                end = w.points[0] if which == 'start' else w.points[-1]
                dx, dy = edge[0] - end[0], edge[1] - end[1]
                if abs(dx) > 0.01 or abs(dy) > 0.01:
                    _shift_end(w, which, dx, dy)
                    w.points = _simplify(w.points)
                    if which == 'start' and w.label is not None:
                        w.label = [w.label[0] - dx, w.label[1] - dy]
                    if w.id in self.wire_items:
                        self.wire_items[w.id].refresh()

    def _carry(self, item: _Movable, dx: float, dy: float, skip: BdWire):
        """Move an object along with another; its other nets stretch."""
        self.following = True
        try:
            item.setPos(item.pos() + QPointF(dx, dy))
        finally:
            self.following = False
        for w, which in list(self._attached(self._ref_of(item))):
            if w is not skip:
                _shift_end(w, which, dx, dy)
                if w.id in self.wire_items:
                    self.wire_items[w.id].refresh()

    def _move_frame_contents(self, frame: 'FrameItem', dx: float, dy: float):
        """Objects (and free nets) that were inside the frame move with it."""
        o = frame.obj
        old = QRectF(o.x - dx, o.y - dy, o.w, o.h)
        inside = [it for it in self.items_by_id.values() if it is not frame and not it.isSelected()
                  and old.contains(QPointF(it.obj.x + getattr(it.obj, 'w', 0) / 2,
                                           it.obj.y + getattr(it.obj, 'h', 0) / 2))]
        free = [w for w in self.bd.wires if not w.start and not w.end
                and all(old.contains(QPointF(*q)) for q in w.points)]
        self.group = set(inside) | {frame}
        try:
            for it in inside:
                it.setPos(it.pos() + QPointF(dx, dy))
        finally:
            self.group = set()
        for w in free:
            w.points = [[x + dx, y + dy] for x, y in w.points]
            if w.id in self.wire_items:
                self.wire_items[w.id].refresh()

    def select_pin(self, item: 'InstanceItem | None', pin: BdPin | None):
        old = self.selected_pin
        self.selected_pin = (item.obj.id, pin.name) if item is not None and pin is not None else None
        for iid in {old[0] if old else None, self.selected_pin[0] if self.selected_pin else None} - {None}:
            if iid in self.items_by_id:
                self.items_by_id[iid].update()

    def move_pin(self, item: 'InstanceItem', pin: BdPin, x: float, y: float, side: str | None = None,
                 carry: bool = False):
        """Put a component port at (x, y) on an edge of the body.
        Moving the port itself (carry=False) moves only the port: its nets stretch, keeping right
        angles, and leave a new edge straight out. Moving a net (carry=True) takes the PortIO or
        dangling connector at its other end along; nets to another component still stretch."""
        side = side or pin.side
        if (x, y, side) == (pin.x, pin.y, pin.side):
            return
        if any(q is not pin and abs(q.x - x) < 0.01 and abs(q.y - y) < 0.01 for q in item.obj.pins):
            return                              # another port is already there
        dx, dy = x - pin.x, y - pin.y
        turned = side != pin.side
        pin.x, pin.y, pin.side = x, y, side
        for w, which in list(self._attached(f'pin:{item.obj.id}:{pin.name}')):
            other = w.end if which == 'start' else w.start
            owner = self.owner_of(other)
            free = not other or (owner is not None and owner.kind == 'pio')
            if carry and free and turned:
                self._turn_net(w, which, pin, owner)
            elif carry and free:
                w.points = [[px + dx, py + dy] for px, py in w.points]
                if owner is not None:
                    self._carry(owner, dx, dy, w)
            else:
                self._route_from_pin(w, which, item.obj, pin)
            if w.id in self.wire_items:
                self.wire_items[w.id].refresh()
        item.prepareGeometryChange()
        item.update()

    def _route_from_pin(self, w: BdWire, which: str, inst: BdInstance, pin: BdPin):
        """Lay a net out from a component port: straight out of the edge (behind the arrow),
        right angles, round the component when the other end is behind it, into the other end
        from behind. Constant work per call, so dragging stays light."""
        far_ref = w.end if which == 'start' else w.start
        far = w.points[-1] if which == 'start' else w.points[0]
        owner = self.owner_of(far_ref) if far_ref else None
        db = None
        if isinstance(owner, InstanceItem):
            fp = next((q for q in owner.obj.pins if f'pin:{owner.obj.id}:{q.name}' == far_ref), None)
            if fp is not None:
                far, db = pin_end(fp), _OUT[fp.side]
        elif isinstance(owner, PortIoItem):
            side = 1 if pin.x >= owner.obj.x else -1
            far, db = [owner.obj.x + side * PORT_EDGE, owner.obj.y], (side, 0)
        route = _pin_route(pin_end(pin), _OUT[pin.side], far, db,
                           QRectF(inst.x, inst.y, inst.w, inst.h))
        w.points = route if which == 'start' else list(reversed(route))

    def _turn_net(self, w: BdWire, which: str, pin: BdPin, owner: '_Movable | None'):
        """A port moved to another edge: its net to a PortIO or connector is laid straight out of
        the new edge, as long as it was, with the PortIO at its end."""
        a, b = w.points[0], w.points[-1]
        length = max(abs(a[0] - b[0]) + abs(a[1] - b[1]), 4 * GRID)
        out = {'left': (-1, 0), 'right': (1, 0), 'top': (0, -1), 'bottom': (0, 1)}[pin.side]
        tip = pin_end(pin)
        end = [tip[0] + out[0] * length, tip[1] + out[1] * length]
        pts = [tip, end]
        w.points = pts if which == 'start' else list(reversed(pts))
        if owner is not None:                   # the PortIO touches the net end with its edge
            side = -1 if out[0] > 0 or out[0] == 0 else 1
            target = QPointF(end[0] - side * PORT_EDGE, end[1])
            d = target - owner.pos()
            self._carry(owner, d.x(), d.y(), w)

    # interactive routing while a PortIO is dragged --------------------------------------
    def _route_pio_net(self, w: BdWire, which: str, pio: BdPortIo, dx: float, dy: float):
        self._routing[w.id] = (w, which, pio)
        if self.route_mode == 'River':
            _shift_end(w, which, dx, dy)        # keep the route, stretch it (loops allowed)
        else:
            self._reroute(w, which, pio)
        self._show_hint(pio)

    def _reroute(self, w: BdWire, which: str, pio: BdPortIo):
        fixed = w.points[-1] if which == 'start' else w.points[0]
        fixed_ref = w.end if which == 'start' else w.start
        side = 1 if fixed[0] >= pio.x else -1
        moving = [pio.x + side * PORT_EDGE, pio.y]
        route = route_net(self.route_mode, fixed, self._exit_dir(fixed_ref, fixed, moving), moving, (side, 0),
                          self._obstacles(fixed_ref, pio))
        w.points = list(reversed(route)) if which == 'start' else route

    def _exit_dir(self, ref: str, at: list[float], toward: list[float]) -> tuple[int, int]:
        """Direction a net leaves its fixed end: out of a component edge, else toward the other end."""
        owner = self.owner_of(ref) if ref else None
        if isinstance(owner, InstanceItem):
            pin = next((q for q in owner.obj.pins if f'pin:{owner.obj.id}:{q.name}' == ref), None)
            if pin is not None:
                return {'left': (-1, 0), 'right': (1, 0), 'top': (0, -1), 'bottom': (0, 1)}[pin.side]
        if abs(toward[0] - at[0]) >= abs(toward[1] - at[1]):
            return (1 if toward[0] >= at[0] else -1, 0)
        return (0, 1 if toward[1] >= at[1] else -1)

    def _obstacles(self, fixed_ref: str, pio: BdPortIo) -> list[QRectF]:
        out = []
        for it in self.items_by_id.values():
            o = it.obj
            if isinstance(it, (InstanceItem, EmbeddedItem)):
                out.append(QRectF(o.x, o.y, o.w, o.h))
            elif isinstance(it, PortIoItem) and o is not pio:
                out.append(QRectF(o.x - PORT_EDGE, o.y - 5, 2 * PORT_EDGE, 10))
        return out

    def cycle_route_mode(self) -> bool:
        """'z' while dragging a PortIO: next routing mode, applied at once."""
        if not self._routing:
            return False
        self.route_mode = ROUTE_MODES[(ROUTE_MODES.index(self.route_mode) + 1) % len(ROUTE_MODES)]
        for w, which, pio in self._routing.values():
            if self.route_mode != 'River':
                self._reroute(w, which, pio)
            if w.id in self.wire_items:
                self.wire_items[w.id].refresh()
        self._show_hint(next(iter(self._routing.values()))[2])
        return True

    def _show_hint(self, pio: BdPortIo):
        if self._hint is None:
            self._hint = QGraphicsSimpleTextItem()
            self._hint.setBrush(QColor(220, 0, 0))
            self._hint.setFont(QFont('Courier New', 7, QFont.Bold))
            self._hint.setZValue(100)
            self._hint.setFlag(QGraphicsItem.ItemIgnoresTransformations)
            self.addItem(self._hint)
        # the legacy wording (strings.vrf: tempInteractiveRoutingString)
        self._hint.setText(f"Press 'z' to change routing\nCurrent mode: {self.route_mode}")
        self._hint.setPos(pio.x + 40, pio.y + 15)
        self._hint.show()

    def end_routing(self):
        for w, _, _ in self._routing.values():
            w.points = _simplify(w.points)
            if w.id in self.wire_items:
                self.wire_items[w.id].refresh()
        self._routing = {}
        if self._hint is not None:
            self._hint.hide()

    def owner_of(self, ref: str) -> _Movable | None:
        """Item a wire end is attached to ("pin:<inst>:<pin>", "pio:<id>", "emb:<id>")."""
        parts = ref.split(':')
        return self.items_by_id.get(parts[1]) if len(parts) > 1 else None

    def object_moved(self, item: _Movable, dx: float, dy: float):
        """Everything attached moves with the object (nets, net connectors and
        the ports at their other end), except nets whose other end is on another
        component or embedded block that stays: those stretch, keeping right angles."""
        if isinstance(item, InstanceItem):
            for pin in item.obj.pins:
                pin.x += dx
                pin.y += dy
        if isinstance(item, FrameItem):
            if not self.group:
                self._move_frame_contents(item, dx, dy)
            return
        moving = lambda it: it.isSelected() or it in self.group
        for w, which in list(self._attached(self._ref_of(item))):
            other = w.end if which == 'start' else w.start
            owner = self.owner_of(other)
            together = owner is not None and moving(item) and moving(owner)
            carry_port = owner is not None and owner.kind == 'pio' and not together and item.kind != 'pio'
            if together and which == 'end':
                continue                        # moved once already, from its start end
            if not other or together or carry_port:
                w.points = [[x + dx, y + dy] for x, y in w.points]
                if carry_port:
                    self._carry(owner, dx, dy, w)
            elif item.kind == 'pio' and not self.following:
                self._route_pio_net(w, which, item.obj, dx, dy)   # interactive routing (Press 'z')
            else:
                _shift_end(w, which, dx, dy)
            if w.id in self.wire_items:
                self.wire_items[w.id].refresh()


    def pin_at(self, pos: QPointF) -> tuple[str, QPointF, BdPin | None, BdPortIo | None] | None:
        """Connection point under the cursor: (ref, point, pin, port)."""
        for inst in self.bd.instances:
            for pin in inst.pins:
                if abs(pin.x - pos.x()) <= PIN_GRAB and abs(pin.y - pos.y()) <= PIN_GRAB:
                    return f'pin:{inst.id}:{pin.name}', QPointF(*pin_end(pin)), pin, None
        for pio in self.bd.port_ios:
            if abs(pio.x - pos.x()) <= PORT_EDGE + 3 and abs(pio.y - pos.y()) <= 7:
                attached = any(True for _ in self._attached(f'pio:{pio.id}'))
                side = self.port_side(pio) if attached else (1 if pos.x() >= pio.x else -1)
                return f'pio:{pio.id}', QPointF(*self.port_edge(pio, side)), None, pio
        return None

    # modes -----------------------------------------------------------------------
    def set_mode(self, mode: str):
        self.mode = mode
        self._cancel_wire()
        for v in self.views():
            v.setDragMode(FsmGraphicsView.RubberBandDrag if mode == 'select' else FsmGraphicsView.NoDrag)
            v.viewport().setCursor(Qt.ArrowCursor if mode == 'select' else Qt.CrossCursor)

    def _cancel_wire(self):
        self._wire_start = None
        self._wire_pts = []
        if self._rubber is not None:
            self.removeItem(self._rubber)
            self._rubber = None

    def mousePressEvent(self, e):
        if self.selected_pin is not None and e.button() == Qt.LeftButton:
            self.select_pin(None, None)         # a port click selects it again below
        if self.mode == 'select' or e.button() != Qt.LeftButton or self.readonly:
            return super().mousePressEvent(e)
        pos = QPointF(_snap(e.scenePos().x()), _snap(e.scenePos().y()))
        if self.mode in ('component', 'port_in', 'port_out', 'embedded', 'frame', 'frame_if', 'frame_else'):
            self.place_requested.emit(pos)
            return
        if self.mode == 'wire':
            hit = self.pin_at(e.scenePos())
            if self._wire_start is None:
                if hit is None:
                    self.message.emit('Start a wire on a component pin or a port')
                    return
                self._wire_start = (hit[0], hit[1])
                self._wire_pts = []
                self._rubber = QGraphicsPathItem()
                self._rubber.setPen(QPen(QColor(120, 120, 120), 1, Qt.DashLine))
                self.addItem(self._rubber)
                return
            if hit is None:
                self._wire_pts.append([pos.x(), pos.y()])   # bend point
                return
            self.finish_wire(hit)

    def contextMenuEvent(self, e):
        item = None
        for it in self.items(e.scenePos()):
            if isinstance(it, (_Movable, WireItem)):
                item = it
                break
        if item is not None and not item.isSelected():
            self.clearSelection()
            item.setSelected(True)
        self.context_requested.emit(item, e.screenPos(), e.scenePos())

    def mouseDoubleClickEvent(self, e):
        if self.mode == 'wire' and self._wire_start is not None and self.pin_at(e.scenePos()) is None:
            # double-click in empty space ends the wire with a named net connector
            pos = QPointF(_snap(e.scenePos().x()), _snap(e.scenePos().y()))
            if self._wire_pts and self._wire_pts[-1] == [pos.x(), pos.y()]:
                self._wire_pts.pop()
            self.finish_wire(('', pos, None, None))
            return
        if self.mode == 'select' and e.button() == Qt.LeftButton:
            # Qt only gives a double-click to the item that took the first press; nets are
            # edited in place whichever net is under the cursor
            wire = next((it for it in self.items(e.scenePos()) if isinstance(it, WireItem)), None)
            top = next(iter(self.items(e.scenePos())), None)
            if wire is not None and (top is wire or not isinstance(top, _Movable)):
                self.edit_net_requested.emit(wire.obj.net, e.scenePos())
                return
        super().mouseDoubleClickEvent(e)

    def mouseMoveEvent(self, e):
        if self._wire_start is not None and self._rubber is not None:
            path = QPainterPath(self._wire_start[1])
            for x, y in self._wire_pts:
                path.lineTo(x, y)
            path.lineTo(e.scenePos())
            self._rubber.setPath(path)
        super().mouseMoveEvent(e)

    def finish_wire(self, end_hit):
        start_ref, start_pt = self._wire_start
        bends = list(self._wire_pts)
        self._cancel_wire()
        end_ref, end_pt = end_hit[0], end_hit[1]
        if end_ref and end_ref == start_ref:
            return
        self.wire_finished.emit(start_ref, end_ref, [start_pt.x(), start_pt.y()], bends, [end_pt.x(), end_pt.y()])

    wire_finished = Signal(str, str, list, list, list)

    # deletion ----------------------------------------------------------------------
    def delete_selected(self) -> bool:
        if self.readonly:
            return False
        bd = self.bd
        sel = self.selectedItems()
        if not sel:
            return False
        dead_wires = {i.obj.id for i in sel if isinstance(i, WireItem)}
        dead_objs = {i.obj.id: i for i in sel if isinstance(i, _Movable)}
        for oid, it in dead_objs.items():
            for w, _ in self._attached(self._ref_of(it)):
                dead_wires.add(w.id)
        touched_pins = set()
        for w in bd.wires:
            if w.id in dead_wires:
                touched_pins.update(r for r in (w.start, w.end) if r.startswith('pin:'))
        bd.wires = [w for w in bd.wires if w.id not in dead_wires]
        bd.instances = [i for i in bd.instances if i.id not in dead_objs]
        bd.embedded = [e for e in bd.embedded if e.id not in dead_objs]
        bd.port_ios = [p for p in bd.port_ios if p.id not in dead_objs]
        bd.frames = [f for f in bd.frames if f.id not in dead_objs]
        # a pin keeps its net only while a wire is still attached to it
        still = {r for w in bd.wires for r in (w.start, w.end)}
        for inst in bd.instances:
            for pin in inst.pins:
                if f'pin:{inst.id}:{pin.name}' in touched_pins and f'pin:{inst.id}:{pin.name}' not in still:
                    pin.net = ''
        self.load(bd)
        self.changed_model.emit()
        return True


def _shift_end(w: BdWire, which: str, dx: float, dy: float):
    """Move one end of a wire and keep its first/last segment horizontal or vertical."""
    pts = w.points
    if not pts:
        return
    i, j = (0, 1) if which == 'start' else (len(pts) - 1, len(pts) - 2)
    if len(pts) == 1:
        pts[0] = [pts[0][0] + dx, pts[0][1] + dy]
        return
    p, q = pts[i], pts[j]
    horizontal = abs(p[1] - q[1]) < 0.01
    vertical = abs(p[0] - q[0]) < 0.01
    pts[i] = [p[0] + dx, p[1] + dy]
    if len(pts) == 2:
        a, b = pts
        if abs(a[0] - b[0]) > 0.01 and abs(a[1] - b[1]) > 0.01:
            if horizontal or not vertical:
                mx = _snap((a[0] + b[0]) / 2)
                w.points = [a, [mx, a[1]], [mx, b[1]], b]
            else:
                my = _snap((a[1] + b[1]) / 2)
                w.points = [a, [a[0], my], [b[0], my], b]
        return
    if horizontal:
        pts[j] = [q[0], q[1] + dy]
    elif vertical:
        pts[j] = [q[0] + dx, q[1]]


def _leave_edge(w: BdWire, which: str, pin: BdPin):
    """Route a net end so that it leaves its port straight out of the component edge."""
    out = {'left': (-1, 0), 'right': (1, 0), 'top': (0, -1), 'bottom': (0, 1)}[pin.side]
    pts = w.points if which == 'start' else list(reversed(w.points))
    end = [pin.x, pin.y]
    stub = [pin.x + out[0] * 2 * GRID, pin.y + out[1] * 2 * GRID]
    rest = pts[1:] if len(pts) > 1 else [stub]
    route = _simplify(_orthogonal([end, stub] + rest))
    w.points = route if which == 'start' else list(reversed(route))


ROUTE_MODES = ['River', 'Avoidance', 'Diagonal', 'Dog Leg']   # legacy order; River is the default


def route_net(mode: str, a: list[float], da: tuple[int, int], b: list[float], db: tuple[int, int],
              obstacles: list[QRectF]) -> list[list[float]]:
    """Route from a (leaving in direction da) to b (entered from direction db).
    Diagonal: a straight line. Dog Leg: one corner, crossing objects if need be. Avoidance:
    right angles around components and ports. (River keeps the existing route: see _shift_end.)"""
    if mode == 'Diagonal':
        return [list(a), list(b)]
    if mode == 'Dog Leg':
        corner = [b[0], a[1]] if da[0] else [a[0], b[1]]
        return _simplify([list(a), corner, list(b)])
    path = _avoid(a, da, b, db, obstacles)
    return path if path else route_net('Dog Leg', a, da, b, db, obstacles)


def _avoid(a, da, b, db, obstacles: list[QRectF], limit: int = 40000) -> list[list[float]] | None:
    """Shortest right-angle route on the grid that keeps off the obstacles (few bends preferred)."""
    g = GRID
    sa = (round((a[0] + da[0] * 2 * g) / g), round((a[1] + da[1] * 2 * g) / g))     # leave a stub at each end
    sb = (round((b[0] + db[0] * 2 * g) / g), round((b[1] + db[1] * 2 * g) / g))
    blocked = [QRectF(r.x() - g, r.y() - g, r.width() + 2 * g, r.height() + 2 * g) for r in obstacles]
    lo_x, hi_x = min(sa[0], sb[0]) - 40, max(sa[0], sb[0]) + 40
    lo_y, hi_y = min(sa[1], sb[1]) - 40, max(sa[1], sb[1]) + 40

    def free(c):
        x, y = c[0] * g, c[1] * g
        return lo_x <= c[0] <= hi_x and lo_y <= c[1] <= hi_y and not any(r.contains(QPointF(x, y)) for r in blocked)

    import heapq
    start = (sa, None)
    best = {start: 0}
    prev = {}
    heap = [(0, 0, sa, None)]
    count = 0
    while heap and count < limit:
        f, cost, c, d = heapq.heappop(heap)
        count += 1
        if c == sb:
            node, cells = (c, d), [c]
            while node in prev:
                node = prev[node]
                cells.append(node[0])
            cells.reverse()
            pts = [list(a)] + [[x * g, y * g] for x, y in cells] + [list(b)]
            return _simplify(_orthogonal(pts))
        for nd in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            n = (c[0] + nd[0], c[1] + nd[1])
            if n != sb and not free(n):
                continue
            nc = cost + 1 + (4 if d is not None and nd != d else 0)
            key = (n, nd)
            if nc < best.get(key, 1 << 30):
                best[key] = nc
                prev[key] = (c, d)
                heapq.heappush(heap, (nc + abs(n[0] - sb[0]) + abs(n[1] - sb[1]), nc, n, nd))
    return None


def _pin_route(a: list[float], da: tuple[int, int], b: list[float], db: tuple[int, int] | None,
               body: QRectF) -> list[list[float]]:
    """Right-angle route from port a (leaving along da) to b (entered along -db when given),
    going round the component body when b lies behind the port."""
    m = 2 * GRID
    sa = [a[0] + da[0] * m, a[1] + da[1] * m]
    sb = [b[0] + db[0] * m, b[1] + db[1] * m] if db else list(b)
    pts = [list(a), sa]
    ahead = (sb[0] - sa[0]) * da[0] + (sb[1] - sa[1]) * da[1]
    if ahead < 0:
        # the other end is behind the port: go round the body, on the side nearer to it
        if da[0]:
            y = body.top() - m if sb[1] < body.center().y() else body.bottom() + m
            pts += [[sa[0], y], [sb[0], y]]
        else:
            x = body.left() - m if sb[0] < body.center().x() else body.right() + m
            pts += [[x, sa[1]], [x, sb[1]]]
    elif da[0]:
        mx = _snap((sa[0] + sb[0]) / 2) if db and db[0] else sb[0]
        pts += [[mx, sa[1]], [mx, sb[1]]]
    else:
        my = _snap((sa[1] + sb[1]) / 2) if db and db[1] else sb[1]
        pts += [[sa[0], my], [sb[0], my]]
    pts += [sb, list(b)]
    return _simplify(_orthogonal(pts))


def _join(a: list[float], b: list[float]) -> list[list[float]]:
    """Corner points that join a to b with horizontal/vertical segments."""
    if abs(a[0] - b[0]) < 0.01 or abs(a[1] - b[1]) < 0.01:
        return []
    mx = _snap((a[0] + b[0]) / 2)
    return [[mx, a[1]], [mx, b[1]]]


def _orthogonal(pts: list[list[float]]) -> list[list[float]]:
    out = [pts[0]]
    for q in pts[1:]:
        out += _join(out[-1], q) + [q]
    return out


def _simplify(pts: list[list[float]]) -> list[list[float]]:
    """Drop repeated points and route points that lie in line with their neighbours
    (a route point dragged into line with the next ones merges into the straight run)."""
    out: list[list[float]] = []
    for q in pts:
        if out and abs(out[-1][0] - q[0]) < 0.01 and abs(out[-1][1] - q[1]) < 0.01:
            continue
        if len(out) >= 2:
            a, b = out[-2], out[-1]
            cross = (b[0] - a[0]) * (q[1] - a[1]) - (b[1] - a[1]) * (q[0] - a[0])
            span = max(abs(q[0] - a[0]) + abs(q[1] - a[1]), 1.0)
            if abs(cross) / span < 0.5:         # b is on the line a-q
                out[-1] = q
                continue
        out.append(q)
    return out if len(out) >= 2 else [list(p) for p in pts[:1]] + [list(p) for p in pts[-1:]]


def _move_net(orig: list[list[float]], dx: float, dy: float, fixed_start: bool, fixed_end: bool):
    """Move a whole net; ends attached to pins/ports stay and are joined orthogonally."""
    moved = [[x + dx, y + dy] for x, y in orig]
    if fixed_start:
        moved[0] = list(orig[0])
    if fixed_end:
        moved[-1] = list(orig[-1])
    return _orthogonal(moved)


def _move_segment(orig: list[list[float]], k: int, dx: float, dy: float, fixed_start: bool, fixed_end: bool):
    """Move segment k across its direction; connected segments stretch."""
    pts = [list(q) for q in orig]
    a, b = pts[k], pts[k + 1]
    if abs(a[1] - b[1]) < 0.01:
        dx = 0.0                    # horizontal segment moves up/down
    elif abs(a[0] - b[0]) < 0.01:
        dy = 0.0                    # vertical segment moves left/right
    na, nb = [a[0] + dx, a[1] + dy], [b[0] + dx, b[1] + dy]
    head, tail = pts[:k], pts[k + 2:]
    if k == 0 and fixed_start:
        head = [a]
    if k + 1 == len(pts) - 1 and fixed_end:
        tail = [b]
    return _orthogonal(head + [na, nb] + tail)


def _route(a: list[float], bends: list[list[float]], b: list[float]) -> list[list[float]]:
    """Orthogonal polyline from a through the bend points to b."""
    pts = [a]
    for p in bends + [b]:
        last = pts[-1]
        if abs(last[0] - p[0]) > 0.01 and abs(last[1] - p[1]) > 0.01:
            if p is b and not bends:
                mx = _snap((last[0] + p[0]) / 2)
                pts += [[mx, last[1]], [mx, p[1]]]
            else:
                pts.append([p[0], last[1]])
        pts.append(p)
    return pts


# ---------------------------------------------------------------------------
# Side panels and dialogs
# ---------------------------------------------------------------------------
class InstanceParamsPanel(QWidget):
    """Equivalent of "BD Object Properties - Component Parameters"."""

    def __init__(self, on_change):
        super().__init__()
        self.on_change = on_change
        self.inst: BdInstance | None = None
        lay = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.editingFinished.connect(self._renamed)
        self.title = QLabel('<b>Select a component instance</b>')
        lay.addWidget(self.title)
        form.addRow('Instance name', self.name)
        lay.addLayout(form)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(['Parameter', 'Value (override)'])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.itemChanged.connect(self._changed)
        lay.addWidget(self.table)
        row = QHBoxLayout()
        b = QPushButton('Add'); b.clicked.connect(self._add); row.addWidget(b)
        b = QPushButton('Remove'); b.clicked.connect(self._remove); row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        lay.addWidget(QLabel('<small>Only parameters listed here are written as <tt>#( … )</tt>.</small>'))
        self._loading = False
        self.setEnabled(False)

    def show_instance(self, inst: BdInstance | None):
        self.inst = inst
        self.setEnabled(inst is not None)
        self._loading = True
        self.table.setRowCount(0)
        self.name.setText(inst.name if inst else '')
        self.title.setText(f'<b>{inst.library}.{inst.unit}</b>' if inst else '<b>Select a component instance</b>')
        for prm in (inst.params if inst else []):
            r = self.table.rowCount()
            self.table.insertRow(r)
            self.table.setItem(r, 0, QTableWidgetItem(prm.name))
            self.table.setItem(r, 1, QTableWidgetItem(prm.value))
        self._loading = False

    def _renamed(self):
        if self.inst and self.name.text().strip() and self.name.text().strip() != self.inst.name:
            self.inst.name = self.name.text().strip()
            self.on_change()

    def _changed(self, *_):
        if self._loading or not self.inst:
            return
        self.inst.params = []
        for r in range(self.table.rowCount()):
            n = self.table.item(r, 0).text().strip() if self.table.item(r, 0) else ''
            v = self.table.item(r, 1).text().strip() if self.table.item(r, 1) else ''
            if n:
                self.inst.params.append(Parameter(n, v))
        self.on_change()

    def _add(self):
        self._loading = True
        r = self.table.rowCount()
        self.table.insertRow(r)
        self.table.setItem(r, 0, QTableWidgetItem('PARAM'))
        self.table.setItem(r, 1, QTableWidgetItem('0'))
        self._loading = False
        self._changed()

    def _remove(self):
        for r in sorted({i.row() for i in self.table.selectedIndexes()}, reverse=True):
            self.table.removeRow(r)
        self._changed()


# ---------------------------------------------------------------------------
# Window
# ---------------------------------------------------------------------------
class BdEditorWindow(QMainWindow):
    def __init__(self, bd: BlockDiagram, context=None):
        super().__init__()
        self.bd = bd
        self.context = context
        self.dirty = False
        self._pending_component: dict | None = None
        self._clipboard: list[dict] = []
        self.scene = BdScene(self)
        self.canvas = FsmGraphicsView(self.scene)
        self.signals_tab = SignalsTable()
        self.params_tab = ParametersTable()
        self.code = CodeView()
        self.emb_edit = QPlainTextEdit(); self.emb_edit.setFont(QFont('Courier New', 9))
        self.emb_edit.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.emb_title = QLabel('<b>Select an embedded block</b>')
        emb_box = QWidget(); el = QVBoxLayout(emb_box); el.addWidget(self.emb_title); el.addWidget(self.emb_edit)
        self.emb_edit.setEnabled(False)
        self.emb: BdEmbedded | None = None
        self.emb_edit.textChanged.connect(self._emb_changed)

        directives = QWidget(); f = QFormLayout(directives)
        self.dir_edits = {}
        for label, attr in (('Pre-module directives', 'pre_module_directives'),
                            ('Post-module directives', 'post_module_directives'),
                            ('End-module directives', 'end_module_directives')):
            w = QPlainTextEdit(); w.setFont(QFont('Courier New', 9)); w.setMaximumHeight(90)
            w.textChanged.connect(lambda w=w, a=attr: self._directive_changed(a, w))
            self.dir_edits[attr] = w
            f.addRow(label, w)

        self.tabs = QTabWidget()
        self.tabs.addTab(self.canvas, 'Block Diagram')
        self.tabs.addTab(self.signals_tab, 'Signal Table')
        self.tabs.addTab(self.params_tab, 'Parameters Table')
        self.tabs.addTab(directives, 'Compiler Directives')
        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.tabs)
        cb = QWidget(); cl = QVBoxLayout(cb); cl.setContentsMargins(0, 0, 0, 0)
        self.code_title = QLabel(); cl.addWidget(self.code_title); cl.addWidget(self.code)
        split.addWidget(cb)
        split.setSizes([1050, 550])
        self.setCentralWidget(split)

        self.inst_panel = InstanceParamsPanel(self.changed)
        side = QTabWidget()
        side.addTab(self.inst_panel, 'Component')
        side.addTab(emb_box, 'Embedded Block')
        self.side_tabs = side
        d = QDockWidget('Properties', self); d.setWidget(side); self.addDockWidget(Qt.LeftDockWidgetArea, d)
        self.browser_dock = d
        self.log = QListWidget(); self.log.setFont(QFont('Courier New', 9))
        ld = QDockWidget('Messages', self); ld.setWidget(self.log); self.addDockWidget(Qt.BottomDockWidgetArea, ld)
        self.resizeDocks([ld], [90], Qt.Vertical)
        self.resizeDocks([d], [330], Qt.Horizontal)

        self.undo_stack = SnapshotUndo(lambda: self.bd.to_json(), self._restore_snapshot, self)
        self._build_actions()
        self.undo_stack.changed.connect(self._update_undo)
        for k, text in enumerate(('Block Diagram', 'Signal Table', 'Parameters Table', 'Compiler Directives')):
            a = QAction(text, self)
            a.triggered.connect(lambda checked=False, k=k: self.tabs.setCurrentIndex(k))
            self.addAction(a)
        about = QAction('About Dolphin HDS', self)
        about.triggered.connect(lambda: QMessageBox.about(self, 'Dolphin HDS', 'Dolphin HDS - block diagram editor'))
        self.addAction(about)
        arrange_menus(self, BD_MENUS)

        self.timer = QTimer(self); self.timer.setSingleShot(True); self.timer.setInterval(250)
        self.timer.timeout.connect(self.regenerate)
        self.scene.selectionChanged.connect(self.on_selection)
        self.scene.changed_model.connect(self.on_scene_changed)
        self.scene.message.connect(lambda m: self.statusBar().showMessage(m, 5000))
        self.scene.place_requested.connect(self.place_at)
        self.scene.wire_finished.connect(self.add_wire)
        self.scene.rename_net_requested.connect(self.rename_net)
        self.scene.edit_net_requested.connect(self.edit_net_inline)
        self.scene.port_dropped.connect(self.port_dropped)
        self.scene.frame_edit_requested.connect(self.frame_properties)
        self.scene.end_dropped.connect(self.end_dropped)
        self.scene.context_requested.connect(self.context_menu)
        self.signals_tab.changed.connect(self.changed)
        self.params_tab.changed.connect(self.changed)
        self.canvas.mouseDoubleClickEvent = self._double_click

        self._load(bd)
        if context is not None and context.readonly:
            self.scene.readonly = True
            for m, a in self.mode_actions.items():
                a.setEnabled(m == 'select')
            for t in (self.signals_tab, self.params_tab):
                t.table.setEditTriggers(QTableWidget.NoEditTriggers)
            self.inst_panel.setEnabled(False)
            self.emb_edit.setReadOnly(True)
            for w in self.dir_edits.values():
                w.setReadOnly(True)
        self.undo_stack.reset()
        self.update_title()
        self.resize(1700, 1000)
        QTimer.singleShot(0, self._restore_view_position)

    # -- actions --------------------------------------------------------------------
    def _act(self, menu, text, slot, key=None, icon_name=None):
        """key may be one shortcut or a list (first one is shown in menus)."""
        a = QAction(text, self)
        if icon_name:
            a.setIcon(icon(icon_name))
        if key:
            keys = [QKeySequence(k) for k in (key if isinstance(key, (list, tuple)) else [key])]
            a.setShortcuts(keys)
            a.setToolTip(f'{text.replace("&", "")}  ({", ".join(k.toString() for k in keys)})')
        a.triggered.connect(slot)
        if menu is not None:
            menu.addAction(a)
        return a

    def _build_actions(self):
        fm = self.menuBar().addMenu('&File')
        a_save = self._act(fm, '&Save', self.save, QKeySequence.Save, 'save')
        a_gen = self._act(fm, '&Generate HDL', self.generate, 'Shift+G', 'generate')
        a_open = self._act(fm, 'Open generated HDL', self.open_generated, 'Ctrl+G', 'generate_open')
        fm.addSeparator()
        self._act(fm, '&Close', self.close, QKeySequence.Close)
        em = self.menuBar().addMenu('&Edit')
        self.act_undo = self._act(em, '&Undo', self.undo_stack.undo, QKeySequence.Undo, 'undo')
        self.act_redo = self._act(em, '&Redo', self.undo_stack.redo, ['Ctrl+Y', 'Ctrl+Shift+Z'], 'redo')
        em.addSeparator()
        a_del = self._act(em, '&Delete', self.delete_selected, None, 'delete')
        self._act(em, 'Cu&t', self.cut, QKeySequence.Cut)
        self._act(em, '&Copy', self.copy, QKeySequence.Copy)
        self._act(em, '&Paste', lambda: self.paste(), QKeySequence.Paste)
        em.addSeparator()
        a_stubs = self._act(em, 'Add Signal Stubs', lambda: self._for_selected(self.add_signal_stubs))
        a_stubs_pio = self._act(em, 'Add Signal Stubs and PortIOs', lambda: self._for_selected(self.add_port_ios))
        a_disc = self._act(em, 'Disconnect', lambda: self._for_selected(self.disconnect))
        a_rename = self._act(em, 'Rename &net...', lambda: self.rename_net(self._selected_net()))
        a_all = self._act(em, 'Select All', self.select_all)
        vm = self.menuBar().addMenu('&View')
        a_fit = self._act(vm, 'View All', self.canvas.fit, None, 'fit')
        a_zin = self._act(vm, 'Zoom in', lambda: self.canvas.zoom(1.2), None, 'zoom_in')
        a_zout = self._act(vm, 'Zoom out', lambda: self.canvas.zoom(1 / 1.2), None, 'zoom_out')
        a_zlast = self._act(vm, 'Zoom Last', self.canvas.zoom_last)
        a_area = self._act(vm, 'View Area', self.view_area)
        a_down = self._act(vm, 'Open Down', self.open_down, None, 'open_down')

        group = QActionGroup(self); group.setExclusive(True)
        self.mode_actions = {}
        for mode, text in (('select', 'Select'), ('select_shape', 'Select Shapes'), ('pan', 'Panning'),
                           ('component', 'Add Component...'), ('wire', 'Add Signal'),
                           ('port_in', 'Add Input Port'), ('port_out', 'Add Output Port'),
                           ('embedded', 'Add Embedded Block'), ('frame', 'Add Frame (FOR)'),
                           ('frame_if', 'Add Frame (IF)'), ('frame_else', 'Add Frame (ELSE)')):
            a = QAction(icon(mode), text, self); a.setCheckable(True)
            a.triggered.connect(lambda checked, m=mode: self.set_mode(m))
            group.addAction(a)
            self.mode_actions[mode] = a
        self.mode_actions['select'].setChecked(True)
        a_props = QAction('Object Properties', self); a_props.triggered.connect(self.properties_of_selection)
        a_hl = QAction('Highlight Net (in diagram)', self); a_hl.triggered.connect(self.highlight_net)
        a_clr = QAction('Clear Net Highlighting', self); a_clr.triggered.connect(lambda: self.highlight_net(clear=True))
        a_drc = QAction('Run Design Rule Checks', self); a_drc.triggered.connect(self.run_checks)
        by_text = {x.text().replace('&', ''): x for x in self.findChildren(QAction)}
        self.toolbar_actions = {
            'save': a_save, 'cut': by_text.get('Cut'), 'copy': by_text.get('Copy'), 'paste': by_text.get('Paste'),
            'delete': a_del, 'select_all': a_all, 'edit_text': a_rename, 'undo': self.act_undo,
            'redo': self.act_redo, 'object_props': a_props, 'zoom_in': a_zin, 'zoom_out': a_zout,
            'zoom_last': a_zlast, 'view_area': a_area, 'fit': a_fit, 'open_down': a_down, 'highlight': a_hl,
            'clear_highlight': a_clr, 'generate_open': a_open, 'drc': a_drc, 'generate': a_gen,
            'add_stubs': a_stubs, 'add_stubs_ports': a_stubs_pio, 'disconnect': a_disc,
            **self.mode_actions,
        }
        if self.context is not None:
            for key, scope in (('generate_blocks', 'blocks'), ('generate_components', 'components'),
                               ('generate_root', 'root')):
                a = QAction(key, self)
                a.triggered.connect(lambda checked=False, sc=scope: self.context.generate_hierarchy(self.bd, self, sc))
                self.toolbar_actions[key] = a
        self.toolbar_actions = {k: v for k, v in self.toolbar_actions.items() if v is not None}
        build_toolbar(self, self.toolbar_actions, BD_TOOLBAR, BD_KEYS)
        # this version draws net names and labels as part of their objects: no separate text objects
        self.toolbar_actions['select_text'].setToolTip('Select Text (no separate text objects in this version)')
        for a in (a_down, a_del):
            self.addAction(a)
        self.canvas.end_command.connect(lambda: self.set_mode('select'))
        self.canvas.tool_done.connect(lambda: self.set_mode(self._mode_before_area))
        self.canvas.nudged.connect(self.scene.changed_model.emit)
        self.canvas.grid = GRID
        self._mode_before_area = 'select'
        self._once = False
        self._build_view_actions()
        gt = QToolBar('Generation'); self.addToolBar(gt)
        self.lang = QComboBox(); [self.lang.addItem(LANG_LABEL[l], l) for l in LANGUAGES]
        self.lang.setToolTip('Target language')
        self.lang.currentIndexChanged.connect(self._lang_changed)
        gt.addWidget(self.lang)

    def view_area(self):
        """View Area: drag a rectangle on the diagram to view that area."""
        if self.canvas.tool != 'area':
            self._mode_before_area = 'pan' if self.canvas.tool == 'pan' else 'select'
        self.scene.set_mode('select')
        self.canvas.set_tool('area')
        self.statusBar().showMessage('Drag a rectangle around the area to view (Esc cancels)', 4000)

    def select_all(self):
        for it in self.scene.items():
            if it.flags() & QGraphicsItem.ItemIsSelectable:
                it.setSelected(True)

    def highlight_net(self, clear: bool = False):
        """Highlight every wire of the selected net (or clear the highlight)."""
        net = '' if clear else self._selected_net()
        if not clear and not net:
            self.statusBar().showMessage('Select a wire to highlight its net', 4000)
            return
        self.scene.highlight = net
        self.scene.update()

    def run_checks(self):
        """Design rule check: connection warnings plus a syntax check of the generated HDL."""
        from ..hdl.parser import check_text
        text, warnings = generate_bd(self.bd)
        self.log.clear()
        for w in warnings:
            self.log.addItem(f'warning: {w}')
        ext = 'sv' if self.bd.language == 'systemverilog' else 'v'
        errors = [d for d in check_text(text, f'{self.bd.unit}.{ext}', self._include_dirs()) if d[1] == 'error']
        for line, _, msg in errors:
            self.log.addItem(f'error: generated HDL line {line}: {msg}')
        self.log.addItem(f'Design rule check: {len(errors)} error(s), {len(warnings)} warning(s)')

    def set_mode(self, mode: str):
        """Select/Panning tools and the Add commands. Add commands repeat until
        Esc or the right button (Main Settings > Toolbar Buttons: Remain active); Ctrl while
        choosing one toggles that for the command."""
        from ..prefs import Prefs
        ctrl = bool(QApplication.keyboardModifiers() & Qt.ControlModifier)
        self._once = mode not in ('select', 'select_shape', 'pan') and \
            ctrl == Prefs.load().toolbar_remain_active
        if mode == 'component':
            choice = self._pick_component()
            if choice is None:
                return self.set_mode('select')
            self._pending_component = choice
            self.statusBar().showMessage(f'Click on the diagram to place {choice["library"]}.{choice["unit"]}')
        self.canvas.set_tool('')
        self.scene.set_mode('select' if mode in ('select_shape', 'pan') else mode)
        if mode == 'pan':
            self.canvas.set_tool('pan')
        self.mode_actions[mode].setChecked(True)
        self.tabs.setCurrentWidget(self.canvas)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.set_mode('select')
        super().keyPressEvent(e)

    # -- model <-> view ---------------------------------------------------------------
    def _load(self, bd: BlockDiagram):
        self.bd = bd
        self.scene.load(bd)
        self.signals_tab.set_rows(bd.signals)
        self.params_tab.set_rows(bd.parameters)
        for attr, w in self.dir_edits.items():
            w.blockSignals(True); w.setPlainText(getattr(bd, attr)); w.blockSignals(False)
        self.lang.blockSignals(True); self.lang.setCurrentIndex(LANGUAGES.index(bd.language)); self.lang.blockSignals(False)
        self.on_selection()
        self.regenerate()

    def _restore_snapshot(self, text: str):
        st = self.canvas.state()
        self._load(BlockDiagram.from_json(text))
        self.canvas.restore(st)
        self.dirty = True
        self.update_title()

    def _update_undo(self):
        self.act_undo.setEnabled(self.undo_stack.can_undo())
        self.act_redo.setEnabled(self.undo_stack.can_redo())

    def _view_key(self) -> str:
        if self.context is not None:
            return getattr(self.context, 'key', '') or self.context.view.path
        return ''

    def _restore_view_position(self):
        if not self.canvas.restore(load_view_state(self._view_key())):
            self.canvas.fit()

    def on_scene_changed(self):
        self.signals_tab.set_rows(self.bd.signals)
        self.changed()

    def changed(self):
        if self._once and self.scene.mode != 'select' and self.scene._wire_start is None:
            self._once = False
            QTimer.singleShot(0, lambda: self.set_mode('select'))
        self.dirty = True
        self.update_title()
        self.timer.start()
        self.undo_stack.note_change()
        self._update_undo()

    def _directive_changed(self, attr, w):
        setattr(self.bd, attr, w.toPlainText())
        self.changed()

    def _lang_changed(self, _):
        self.bd.language = self.lang.currentData()
        self.changed()

    def on_selection(self):
        sel = self.scene.selectedItems()
        inst = next((i.obj for i in sel if isinstance(i, InstanceItem)), None)
        emb = next((i.obj for i in sel if isinstance(i, EmbeddedItem)), None)
        self.inst_panel.show_instance(inst)
        if inst:
            self.side_tabs.setCurrentIndex(0)
        self.emb = emb
        self.emb_edit.blockSignals(True)
        self.emb_edit.setPlainText(emb.text if emb else '')
        self.emb_edit.blockSignals(False)
        self.emb_edit.setEnabled(emb is not None)
        self.emb_title.setText(f'<b>Embedded block {emb.number}: {emb.name}</b>' if emb else
                               '<b>Select an embedded block</b>')
        if emb:
            self.side_tabs.setCurrentIndex(1)

    def _emb_changed(self):
        if self.emb is not None:
            self.emb.text = self.emb_edit.toPlainText()
            self.scene.update()
            self.changed()

    # -- editing operations ----------------------------------------------------------------
    # -- components --------------------------------------------------------------------
    def _project(self):
        return self.context.project if self.context is not None else None

    def _pick_component(self) -> dict | None:
        """Ask for a component; returns {library, unit, ports, params} or None."""
        proj = self._project()
        entries = []
        if proj is not None:
            for lib in proj.libraries:
                if not lib.scanned:
                    lib.scan(proj.cache)
                for u in sorted(lib.units.values(), key=lambda u: u.name):
                    if u.type != 'Package':
                        entries.append((lib.name, u.name, u.type))
        start = ''
        if proj is not None and proj.library(self.bd.library) is not None:
            start = proj.library(self.bd.library).main_hdl_dir
        dlg = ComponentPicker(entries, start, self)
        if not dlg.exec():
            return None
        if dlg.file_choice:
            return self._component_from_file(dlg.file_choice)
        choice = dlg.choice()
        if choice is None:
            return None
        lib, unit = choice
        du = proj.find_unit(unit, prefer=proj.library(lib)) if proj else None
        return self._component_info(lib, unit, du)

    def _component_info(self, lib: str, unit: str, du) -> dict:
        from ..project.project import unit_ports
        params = du.hdl.params if du is not None and du.hdl is not None else []
        return {'library': lib, 'unit': unit, 'ports': unit_ports(du) if du else [], 'params': params}

    def _component_from_file(self, path: str) -> dict | None:
        from ..hdl.parser import parse_file
        parsed = parse_file(path, self._include_dirs())
        units = [u for u in parsed.units if u.kind in ('module', 'interface', 'program')]
        if not units:
            QMessageBox.warning(self, 'Add component', f'No module found in {path}.\n' + '\n'.join(parsed.errors[:5]))
            return None
        unit = units[0]
        if len(units) > 1:
            name, ok = QInputDialog.getItem(self, 'Add component', 'Module:', [u.name for u in units], 0, False)
            if not ok:
                return None
            unit = next(u for u in units if u.name == name)
        ports = []
        for prt in unit.ports:
            m = re.search(r'(\[[^\]]*\])', prt.type)
            ports.append((prt.name, prt.direction, m.group(1) if m else ''))
        lib = library_of_file(self._project(), path, self.bd.library)
        if parsed.errors:
            self.log.addItem(f'{os.path.basename(path)}: {len(parsed.errors)} parse error(s); ports may be incomplete')
        return {'library': lib, 'unit': unit.name, 'ports': ports, 'params': unit.params, 'source': path}

    def _include_dirs(self) -> list[str]:
        proj = self._project()
        lib = proj.library(self.bd.library) if proj else None
        return lib.include_dirs if lib else []

    def _interface(self, inst: BdInstance) -> dict | None:
        """Ports and parameters of an instance's module: from the project, else from its source file."""
        proj = self._project()
        du = proj.find_unit(inst.unit, prefer=proj.library(inst.library)) if proj else None
        if du is not None:
            return self._component_info(inst.library, inst.unit, du)
        if inst.source and os.path.exists(inst.source):
            from ..hdl.parser import parse_file
            u = next((u for u in parse_file(inst.source, self._include_dirs()).units if u.name == inst.unit), None)
            if u is not None:
                ports = [(p.name, p.direction, (re.search(r'(\[[^\]]*\])', p.type) or [''])[0]) for p in u.ports]
                return {'library': inst.library, 'unit': u.name, 'ports': ports, 'params': u.params,
                        'source': inst.source}
        return None

    def _symbol_params(self, inst: BdInstance) -> dict[str, list[tuple[str, str]]]:
        """{'symbol': the symbol's Parameters table, 'all': every parameter the module declares},
        each with its default declaration as written."""
        info = self._interface(inst)
        all_params = list(info['params']) if info else []
        symbol = []
        du = self._unit_of(inst)
        sym = next((v for v in du.views if v.kind == 'symbol'), None) if du is not None else None
        if sym is not None and sym.path.endswith('.sb'):
            try:
                from ..hds.import_sm import symbol_parameters
                symbol = symbol_parameters(sym.path)
            except Exception:
                symbol = []
        known = {n for n, _ in all_params}
        all_params += [p for p in symbol if p[0] not in known]
        return {'symbol': symbol or all_params, 'all': all_params}

    def place_at(self, pos: QPointF):
        mode = self.scene.mode
        bd = self.bd
        if mode == 'component' and self._pending_component:
            self._add_component(self._pending_component, pos)
        elif mode in ('port_in', 'port_out'):
            name, ok = QInputDialog.getText(self, 'Add port', 'Port name:')
            name = name.strip()
            if not ok or not name:
                return
            pmode = 'input' if mode == 'port_in' else 'output'
            self._ensure_port(name, pmode)
            bd.port_ios.append(BdPortIo(self._new_id('p'), name, pmode, pos.x(), pos.y()))
        elif mode in ('frame', 'frame_if', 'frame_else'):
            if not self._add_frame(mode, pos):
                return
        elif mode == 'embedded':
            n = max((e.number for e in bd.embedded), default=0) + 1
            bd.embedded.append(BdEmbedded(self._new_id('e'), f'eb{n}', n, '// HDL code\n', pos.x(), pos.y(), 240, 90))
        else:
            return
        self._reload_scene()
        self.set_mode('select')

    def _add_frame(self, mode: str, pos: QPointF) -> bool:
        """New generate frame at pos. FOR: "name: [left:right]" (instances inside become
        instance arrays); IF: "name: `ifdef MACRO" or "name: (expression)"; ELSE: pairs with
        an IF frame of the same name."""
        bd = self.bd
        n = max((f.number for f in bd.frames), default=0) + 1
        if mode == 'frame_else':
            names = [f.name for f in bd.frames if f.kind == 'if'
                     and not any(e.kind == 'else' and e.name == f.name for e in bd.frames)]
            if not names:
                QMessageBox.information(self, 'Add Frame (ELSE)', 'Add an IF frame first: an ELSE frame '
                                        'is the alternative of the IF frame with the same name.')
                return False
            name, ok = QInputDialog.getItem(self, 'Add Frame (ELSE)', 'Alternative of IF frame:', names, 0, False)
            if not ok:
                return False
            bd.frames.append(BdFrame(self._new_id('f'), 'else', name, '`else' if next(
                f for f in bd.frames if f.kind == 'if' and f.name == name).spec.startswith('`') else '',
                n, pos.x(), pos.y()))
            return True
        default = f'g{n - 1}: [7:0]' if mode == 'frame' else f'g{n - 1}: `ifdef MACRO'
        text, ok = QInputDialog.getText(self, 'Add Frame (FOR)' if mode == 'frame' else 'Add Frame (IF)',
                                        'Frame title (name: range)' if mode == 'frame'
                                        else 'Frame title (name: `ifdef MACRO or name: (condition))', text=default)
        parsed = self._parse_frame_title(text) if ok else None
        if parsed is None:
            return False
        bd.frames.append(BdFrame(self._new_id('f'), 'for' if mode == 'frame' else 'if', parsed[0], parsed[1], n,
                                 pos.x(), pos.y()))
        return True

    def _parse_frame_title(self, text: str) -> tuple[str, str] | None:
        m = re.match(r'\s*([A-Za-z_][\w$]*)\s*:\s*(.*\S)\s*$', text or '')
        if m is None:
            self.statusBar().showMessage('A frame title is "name: range" or "name: condition"', 5000)
            return None
        return m.group(1), m.group(2)

    def frame_properties(self, fr: BdFrame):
        """BD Object Properties - Frames (double-click the title, Alt+Enter or the popup menu)."""
        from .bd_dialogs import FramePropertiesDialog
        if_names = [f.name for f in self.bd.frames if f.kind == 'if' and f is not fr]
        dlg = FramePropertiesDialog(fr, if_names, self, apply=lambda v: self._apply_frame(fr, v))
        if dlg.exec() and not self.scene.readonly:
            self._apply_frame(fr, dlg.values())

    def _apply_frame(self, fr: BdFrame, v: dict):
        if self.scene.readonly:
            return
        if not re.fullmatch(r'[A-Za-z_][\w$]*', v['name']):
            QMessageBox.warning(self, 'Frames', f'"{v["name"]}" is not a valid label')
            return
        if v['kind'] == 'if' and not v['spec']:
            QMessageBox.warning(self, 'Frames', 'An IF frame needs a condition')
            return
        if v['kind'] == 'else' and not any(f.kind == 'if' and f.name == v['name'] for f in self.bd.frames):
            QMessageBox.warning(self, 'Frames', f'No IF frame labelled "{v["name"]}" for this ELSE frame')
            return
        old = (fr.kind, fr.name)
        if v['kind'] == 'else':                 # an ELSE follows its IF frame's form
            twin = next(f for f in self.bd.frames if f.kind == 'if' and f.name == v['name'])
            v['spec'] = '`else' if twin.spec.startswith('`') else ''
        if all(getattr(fr, k) == val for k, val in v.items()):
            return
        for k, val in v.items():
            setattr(fr, k, val)
        if old[0] == 'if':                      # keep the ELSE frame paired with its IF frame
            for e in self.bd.frames:
                if e.kind == 'else' and e.name == old[1]:
                    e.name = fr.name
        self._reload_scene()
        self.changed()

    def edit_frame(self, fr: BdFrame):
        if self.scene.readonly:
            return
        text, ok = QInputDialog.getText(self, 'Frame', 'Frame title:', text=fr.title)
        parsed = self._parse_frame_title(text) if ok else None
        if parsed is None or parsed == (fr.name, fr.spec):
            return
        old = fr.name
        fr.name, fr.spec = parsed
        for e in self.bd.frames:                # keep the ELSE frame paired with its IF frame
            if fr.kind == 'if' and e.kind == 'else' and e.name == old:
                e.name = fr.name
        self._reload_scene()
        self.changed()

    def _ensure_port(self, name: str, mode: str, bounds: str = ''):
        sig = next((s for s in self.bd.signals if s.name == name), None)
        if sig is None:
            self.bd.signals.append(Sig(name, mode, 'wire', bounds))
        else:
            sig.mode = mode
            sig.bounds = sig.bounds or bounds

    def _reload_scene(self):
        self.scene.load(self.bd)
        self.signals_tab.set_rows(self.bd.signals)
        self.changed()
        self.undo_stack.flush()        # each command is its own undo step

    def _add_component(self, info: dict, pos: QPointF) -> BdInstance:
        unit, ports = info['unit'], info['ports']
        names = {i.name for i in self.bd.instances}
        name, k = unit, 0
        while name in names:
            k += 1
            name = f'{unit}_{k}'
        inst = BdInstance(self._new_id('i'), name, info['library'], unit, x=pos.x(), y=pos.y(),
                          source=info.get('source', ''))
        self._layout_pins(inst, ports)
        if not ports:
            self.log.addItem(f'{info["library"]}.{unit}: interface not found, the instance has no pins')
        self.bd.instances.append(inst)
        return inst

    @staticmethod
    def _layout_pins(inst: BdInstance, ports: list[tuple[str, str, str]]):
        """Inputs/inouts on the left, outputs on the right, 10 units apart."""
        ins = [p for p in ports if p[1] != 'output']
        outs = [p for p in ports if p[1] == 'output']
        longest = max([len(p[0]) for p in ports] + [len(inst.unit), 8])
        inst.w = _snap(max(140, longest * 12 + 40))
        inst.h = _snap(max(len(ins), len(outs)) * PIN_STEP + 3 * GRID)
        old = {p.name: p for p in inst.pins}
        inst.pins = []
        for side, group in (('left', ins), ('right', outs)):
            for i, (pname, mode, bounds) in enumerate(group):
                x = inst.x - PIN_HALF if side == 'left' else inst.x + inst.w + PIN_HALF
                prev = old.get(pname)
                inst.pins.append(BdPin(pname, mode, prev.net if prev else '', len(inst.pins) + 1, x,
                                       inst.y + 2 * GRID + i * PIN_STEP, side, bounds))

    # -- right-click menu ------------------------------------------------------------------
    def context_menu(self, item, screen_pos, scene_pos):
        m = QMenu(self)
        ro = self.scene.readonly
        if isinstance(item, InstanceItem):
            self._component_menu(m, item.obj, scene_pos, ro)
        elif isinstance(item, WireItem):
            self._net_menu(m, item, scene_pos, ro)
        elif isinstance(item, PortIoItem):
            self._port_menu(m, item, scene_pos, ro)
        elif isinstance(item, FrameItem):
            fr = item.obj
            for text, fn, key in (('Cu&t', self.cut, 'Ctrl+X'), ('&Copy', self.copy, 'Ctrl+C'),
                                  ('&Paste', lambda: self.paste(scene_pos), 'Ctrl+V'),
                                  ('&Delete', self.delete_selected, 'Del')):
                a = m.addAction(text, fn)
                a.setShortcut(QKeySequence(key)); a.setShortcutVisibleInContextMenu(True)
                a.setEnabled(text == '&Copy' or (not ro and (text != '&Paste' or bool(self._clipboard))))
            m.addSeparator()
            m.addAction('&Appearance...').setEnabled(False)
            m.addSeparator()
            a = m.addAction('&Object Properties...', lambda: self.frame_properties(fr))
            a.setShortcut(QKeySequence('Alt+Return')); a.setShortcutVisibleInContextMenu(True)
        elif isinstance(item, EmbeddedItem):
            eb = item.obj
            m.addAction('Edit Code', lambda: (self.side_tabs.setCurrentIndex(1), self.emb_edit.setFocus()))
            m.addAction('Rename...', lambda: self.rename_embedded(eb)).setEnabled(not ro)
            m.addSeparator()
            m.addAction('Delete', self.delete_selected).setEnabled(not ro)
        else:
            m.addAction('Paste', lambda: self.paste(scene_pos)).setEnabled(bool(self._clipboard) and not ro)
            m.addSeparator()
            for mode, text in (('component', 'Add Component...'), ('port_in', 'Add Input Port'),
                               ('port_out', 'Add Output Port'), ('embedded', 'Add Embedded Block')):
                m.addAction(icon(mode), text, lambda mode=mode: self._add_here(mode, scene_pos)).setEnabled(not ro)
            m.addSeparator()
            m.addAction('Fit diagram', self.canvas.fit)
        m.exec(screen_pos)

    # -- component popup menu (same entries and order as the legacy editor) -------------
    def _component_menu(self, m: QMenu, inst: BdInstance, pos: QPointF, ro: bool):
        du = self._unit_of(inst)
        views = [v for v in du.views if v.kind != 'symbol'] if du is not None else []
        open_as = m.addMenu('Open &As')
        for v in views:
            open_as.addAction(f'{v.name}  ({v.label})', lambda v=v: self.context.manager.open_view(du, v))
        open_as.setEnabled(bool(views) and self.context is not None)
        cdv = m.addMenu('Change Default &View')
        for v in views:
            a = cdv.addAction(f'{v.name}  ({v.label})', lambda v=v: self._change_default_view(du, v))
            a.setCheckable(True)
            a.setChecked(du.is_default(v))
        cdv.setEnabled(len(views) > 1 and du is not None and du.library.writable)
        m.addMenu('&Rotate').setEnabled(False)
        m.addMenu('&Flip').setEnabled(False)
        m.addSeparator()
        self._edit_items(m, pos, ro, can_copy=True)
        m.addSeparator()
        self._menu_item(m, 'C&onnect', None, 'Alt+C')
        self._menu_item(m, 'Disconnect', lambda: self.disconnect(inst), 'Shift+Alt+C', not ro)
        m.addMenu('A&utoroute').setEnabled(False)
        self._menu_item(m, 'Add Signal Stu&bs...', lambda: self.add_signal_stubs(inst), 'Ctrl+F10', not ro)
        self._menu_item(m, 'Add Port&IO...', lambda: self.add_port_ios(inst), 'Shift+F10', not ro)
        self._menu_item(m, '&Equidistant Ports', lambda: self.equidistant(inst), enabled=not ro)
        pmf = m.addMenu('Port &Map Frame')
        a = pmf.addAction('&Enable', lambda: self._set_portmap(inst, not inst.portmap_frame))
        a.setCheckable(True); a.setChecked(inst.portmap_frame); a.setEnabled(not ro)
        pmf.addAction('&Edit...', lambda: self.component_properties(inst, 'portmap'))
        m.addSeparator()
        m.addMenu('S&hape').setEnabled(False)
        self._menu_item(m, 'Appea&rance...', lambda: self.component_properties(inst, 'appearance'))
        self._menu_item(m, 'Show Te&xt', lambda: self._show_component_text(inst), enabled=not ro)
        self._menu_item(m, 'Port Visibilit&y...', lambda: self.component_properties(inst, 'visibility'))
        m.addSeparator()
        gp = m.addMenu('&Generics/Parameters')
        gp.addAction('&Edit...', lambda: self.component_properties(inst, 'parameters'))
        a = gp.addAction('&Show Values', lambda: self._toggle_param_values(inst))
        a.setCheckable(True); a.setChecked(inst.show_params); a.setEnabled(not ro)
        m.addMenu('Re-&level').setEnabled(False)
        up = m.addMenu('&Update')
        up.addAction('&Interface (re-read ports from the HDL)', lambda: self.update_interface(inst)).setEnabled(not ro)
        a = m.addAction('&Object Properties...', lambda: self.component_properties(inst, 'component'))
        a.setShortcut(QKeySequence('Alt+Return')); a.setShortcutVisibleInContextMenu(True)

    def _unit_of(self, inst: BdInstance):
        p = self._project()
        return p.find_unit(inst.unit, prefer=p.library(inst.library)) if p is not None else None

    def _change_default_view(self, du, view):
        try:
            du.library.set_default_view(du.name, view)
        except OSError as e:
            QMessageBox.warning(self, 'Change Default View', str(e))
            return
        self.statusBar().showMessage(f'{du.name}: default view is now {view.name} ({view.label})', 5000)
        if self.context is not None:
            for ex in self.context.manager.explorers.values():
                ex.refresh()

    def _set_portmap(self, inst: BdInstance, on: bool):
        inst.portmap_frame = on
        self._reload_scene(); self.changed()

    def _show_component_text(self, inst: BdInstance):
        inst.show_library = inst.show_instance = inst.text_name = True
        self._reload_scene(); self.changed()

    def _toggle_param_values(self, inst: BdInstance):
        inst.show_params = not inst.show_params
        self._reload_scene(); self.changed()

    def port_properties(self, pio: BdPortIo, page: str = 'mode'):
        dlg = PortIoPropertiesDialog(pio, page, self)
        dlg.exec()
        if dlg.applied and not self.scene.readonly:
            if dlg.mode() != pio.mode:
                self.change_port_mode(pio, dlg.mode())
            else:
                self._reload_scene(); self.changed()

    # -- net / port popup menus (same entries and order as the legacy editor) -----------
    def _menu_item(self, m: QMenu, text: str, fn=None, key: str = '', enabled: bool = True):
        a = m.addAction(text)
        if fn is not None:
            a.triggered.connect(fn)
        if key:
            a.setShortcut(QKeySequence(key))
            a.setShortcutVisibleInContextMenu(True)
        a.setEnabled(enabled and fn is not None)
        return a

    def _edit_items(self, m: QMenu, scene_pos: QPointF, ro: bool, can_copy: bool):
        self._menu_item(m, 'Cu&t', self.cut if can_copy else None, 'Ctrl+X', not ro)
        self._menu_item(m, '&Copy', self.copy if can_copy else None, 'Ctrl+C')
        self._menu_item(m, '&Paste', lambda: self.paste(scene_pos), 'Ctrl+V', bool(self._clipboard) and not ro)
        self._menu_item(m, '&Delete', self.delete_selected, 'Del', not ro)

    def _net_menu(self, m: QMenu, item: 'WireItem', pos: QPointF, ro: bool):
        w = item.obj
        net = w.net
        k = item._segment_at(pos)
        near = min(range(len(w.points)), key=lambda i: QLineF(pos, QPointF(*w.points[i])).length())
        interior = 0 < near < len(w.points) - 1 and QLineF(pos, QPointF(*w.points[near])).length() <= GRID
        self._menu_item(m, 'Add &Route', lambda: self.add_route(w, k, pos), enabled=not ro)
        self._menu_item(m, 'Re&move Route', lambda: self.remove_route(w, near), enabled=not ro and interior)
        self._menu_item(m, 'Remove &All Routes', lambda: self.remove_all_routes(w),
                        enabled=not ro and len(w.points) > 2)
        self._menu_item(m, 'Add Port &I/O', lambda: self.add_port_io_for(w), enabled=not ro and not (w.start and w.end))
        self._menu_item(m, '&Goto Destination ...', lambda: self.goto_destination(net))
        m.addSeparator()
        self._edit_items(m, pos, ro, can_copy=False)
        m.addSeparator()
        self._menu_item(m, 'C&onnect', None, 'Alt+C')
        self._menu_item(m, 'Disconnect', lambda: self.disconnect_wire(w), 'Shift+Alt+C',
                        enabled=not ro and bool(w.start or w.end))
        for title in ('&Breakpoints', '&Probes', 'A&utoroute'):
            m.addMenu(title).setEnabled(False)
        hl = m.addMenu('Highlight N&et')
        self._menu_item(hl, '&Single Level', lambda: self._highlight(net))
        self._menu_item(hl, '&Hierarchical...', None)
        hl.addSeparator()
        self._menu_item(hl, '&Clear', lambda: self._highlight(''))
        self._menu_item(hl, 'Clear &All', lambda: self._highlight(''))
        for title in ('&Insert Net', 'Remo&ve Net'):
            m.addMenu(title).setEnabled(False)
        m.addSeparator()
        bus = self.scene.is_bus(net)
        self._menu_item(m, 'Change St&yle', lambda: self.change_style(net), enabled=not ro).setToolTip(
            'Signal <-> Bus' if bus else 'Signal -> Bus')
        self._menu_item(m, 'Hide Te&xt' if w.show_text else 'Show Te&xt', lambda: self.toggle_net_text(w),
                        enabled=not ro)
        self._menu_item(m, 'Signal Visibilit&y...', None)
        self._menu_item(m, 'Appeara&nce...', None)
        m.addSeparator()
        scope = m.addMenu('Scope For Chan&ges')
        for text, on in (('Joined Wires in this diagram', False), ('Entire Net in diagram', True),
                         ('Entire Net in hierarchy', False)):
            a = scope.addAction(text)
            a.setCheckable(True)
            a.setChecked(on)
            a.setEnabled(on)
        self._menu_item(m, 'Co&mments...', lambda: self.net_comment(net), enabled=not ro)
        self._menu_item(m, 'A&ttributes...', None)
        self._menu_item(m, 'Object &Properties...', lambda: self.signal_properties(net), 'Alt+Return')

    def _port_menu(self, m: QMenu, item: 'PortIoItem', pos: QPointF, ro: bool):
        pio = item.obj
        cm = m.addMenu('Change &Mode')
        for text, mode in (('&In', 'input'), ('&Out', 'output'), ('In&Out', 'inout'), ('&Buffer', 'buffer')):
            a = cm.addAction(text, lambda mode=mode: self.change_port_mode(pio, mode))
            a.setCheckable(True)
            a.setChecked(pio.mode == mode)
            a.setEnabled(not ro and mode != 'buffer')     # buffer ports are VHDL only
        m.addMenu('&Rotate Port').setEnabled(False)
        self._menu_item(m, 'PortIO Text &Visibility...', lambda: self.port_properties(pio, 'visibility'))
        self._menu_item(m, 'Hide Te&xt' if pio.show_text else 'Show Te&xt', lambda: self.toggle_port_text(pio),
                        enabled=not ro)
        m.addSeparator()
        self._edit_items(m, pos, ro, can_copy=False)
        m.addSeparator()
        self._menu_item(m, 'C&onnect', None, 'Alt+C')
        attached = [w for w, _ in self.scene._attached(f'pio:{pio.id}')]
        self._menu_item(m, 'Disconnect', lambda: [self.disconnect_wire(w, only=f'pio:{pio.id}') for w in attached],
                        'Shift+Alt+C', enabled=not ro and bool(attached))
        m.addSeparator()
        self._menu_item(m, 'Appeara&nce...', lambda: self.port_properties(pio, 'appearance'))
        m.addSeparator()
        self._menu_item(m, 'Object &Properties...', lambda: self.port_properties(pio), 'Alt+Return')

    # net / port commands
    def add_route(self, w: BdWire, k: int, pos: QPointF):
        a, b = w.points[k], w.points[k + 1]
        if abs(a[1] - b[1]) < 0.01:
            q = [_snap(pos.x()), a[1]]
        elif abs(a[0] - b[0]) < 0.01:
            q = [a[0], _snap(pos.y())]
        else:
            q = [_snap(pos.x()), _snap(pos.y())]
        w.points.insert(k + 1, q)          # a handle that can be dragged to reshape the net
        self._net_edited(w)

    def remove_route(self, w: BdWire, i: int):
        del w.points[i]
        w.points = _simplify(_orthogonal(w.points))
        self._net_edited(w)

    def remove_all_routes(self, w: BdWire):
        w.points = _simplify(_orthogonal([w.points[0], w.points[-1]]))
        self._net_edited(w)

    def _net_edited(self, w: BdWire):
        if w.id in self.scene.wire_items:
            self.scene.wire_items[w.id].refresh()
        self.scene.changed_model.emit()

    def add_port_io_for(self, w: BdWire):
        """Port at the dangling end of a net, named after the net, direction from its drivers."""
        which, k = ('end', -1) if not w.end else ('start', 0)
        drivers = [p for i in self.bd.instances for p in i.pins if p.net == w.net and p.mode == 'output']
        mode = 'output' if drivers else 'input'
        end, nxt = w.points[k], w.points[k + 1 if k == 0 else -2]
        side = -1 if nxt[0] > end[0] else 1           # the port sits beyond the end, its edge on the net
        pio = BdPortIo(self._new_id('p'), w.net, mode, end[0] - side * PORT_EDGE, end[1])
        self.bd.port_ios.append(pio)
        setattr(w, which, f'pio:{pio.id}')
        self._ensure_port(w.net, mode)
        self._reload_scene()
        self.changed()

    def goto_destination(self, net: str):
        targets = []
        for inst in self.bd.instances:
            for p in inst.pins:
                if p.net == net:
                    targets.append((f'{inst.name}.{p.name} ({p.mode})', self.scene.items_by_id[inst.id]))
        for pio in self.bd.port_ios:
            if pio.name == net:
                targets.append((f'port {pio.name} ({pio.mode})', self.scene.items_by_id[pio.id]))
        if not targets:
            return
        names = [t[0] for t in targets]
        choice, ok = QInputDialog.getItem(self, 'Goto Destination', f'Net {net} connects to:', names, 0, False)
        if ok:
            it = targets[names.index(choice)][1]
            self.scene.clearSelection()
            it.setSelected(True)
            self.canvas.centerOn(it)

    def disconnect_wire(self, w: BdWire, only: str = ''):
        for which in ('start', 'end'):
            ref = getattr(w, which)
            if not ref or (only and ref != only):
                continue
            pin = self._pin(ref)
            if pin is not None and not any(x is not w and ref in (x.start, x.end) for x in self.bd.wires):
                pin.net = ''
            setattr(w, which, '')
        self._reload_scene()
        self.changed()

    def _highlight(self, net: str):
        self.scene.highlight = net
        self.scene.update()

    def change_style(self, net: str):
        sig = next((s for s in self.bd.signals if s.name == net), None)
        if sig is None:
            return
        if sig.bounds:
            sig.bounds = ''
        else:
            bounds, ok = QInputDialog.getText(self, 'Change Style', f'Bus bounds for {net}:', text='[7:0]')
            if not ok or not bounds.strip():
                return
            sig.bounds = bounds.strip()
        self._reload_scene()
        self.changed()

    def toggle_net_text(self, w: BdWire):
        w.show_text = not w.show_text
        self._net_edited(w)

    def toggle_port_text(self, pio: BdPortIo):
        pio.show_text = not pio.show_text
        self.scene.items_by_id[pio.id].update()
        self.scene.changed_model.emit()

    def net_comment(self, net: str):
        sig = next((s for s in self.bd.signals if s.name == net), None)
        if sig is None:
            return
        text, ok = QInputDialog.getText(self, 'Comments', f'Comment for {net}:', text=sig.comment)
        if ok:
            sig.comment = text.strip()
            self.changed()

    def change_port_mode(self, pio: BdPortIo, mode: str):
        pio.mode = mode
        self._ensure_port(pio.name, mode)
        self._reload_scene()
        self.changed()

    def _for_selected(self, fn):
        for it in [i for i in self.scene.selectedItems() if isinstance(i, InstanceItem)]:
            fn(it.obj)

    def properties_of_selection(self):
        sel = self.scene.selectedItems()
        if not sel:
            return
        it = sel[0]
        if isinstance(it, InstanceItem):
            self.component_properties(it.obj, 'component')
        elif isinstance(it, WireItem):
            self.signal_properties(it.obj.net)
        elif isinstance(it, PortIoItem):
            self.port_properties(it.obj)
        elif isinstance(it, FrameItem):
            self.frame_properties(it.obj)

    def _add_here(self, mode: str, pos: QPointF):
        self.set_mode(mode)
        if self.scene.mode == mode:
            self.place_at(QPointF(_snap(pos.x()), _snap(pos.y())))

    def component_properties(self, inst: BdInstance, page: str):
        libs = [l.name for l in self._project().libraries] if self._project() else [inst.library]
        old = (inst.library, inst.unit)
        conns = [(p.name, p.net) for p in sorted(inst.pins, key=lambda p: p.order) if p.net]
        dlg = ComponentPropertiesDialog(inst, libs, self._symbol_params(inst), page, self, conns)
        dlg.exec()
        if dlg.applied and not self.scene.readonly:
            if (inst.library, inst.unit) != old and QMessageBox.question(
                    self, 'Component changed',
                    f'Read the interface of {inst.library}.{inst.unit} and update the pins?') == QMessageBox.Yes:
                self.update_interface(inst)
            self._reload_scene()
            self.changed()

    def rename_embedded(self, eb: BdEmbedded):
        name, ok = QInputDialog.getText(self, 'Rename embedded block', 'Name:', text=eb.name)
        if ok and name.strip():
            eb.name = name.strip()
            self._reload_scene()

    def signal_properties(self, net: str):
        sig = next((s for s in self.bd.signals if s.name == net), None)
        dlg = SignalPropertiesDialog(sig or Sig(net, 'local', 'wire'), self)
        if not dlg.exec() or self.scene.readonly:
            return
        if sig is None:
            sig = dlg.sig
            self.bd.signals.append(sig)
        v = dlg.values()
        new_name = v.pop('name')
        for k, val in v.items():
            setattr(sig, k, val)
        if new_name and new_name != net:
            self._rename(net, new_name)
        self._reload_scene()

    # pins without a wire get a short stub (named net) or a port of the module
    def _free_pins(self, inst: BdInstance) -> list[BdPin]:
        attached = {r for w in self.bd.wires for r in (w.start, w.end)}
        return [p for p in inst.pins if f'pin:{inst.id}:{p.name}' not in attached]

    def add_signal_stubs(self, inst: BdInstance):
        n = 0
        for pin in self._free_pins(inst):
            net = pin.net or pin.name
            pin.net = net
            if not any(s.name == net for s in self.bd.signals):
                self.bd.signals.append(Sig(net, 'local', 'wire', pin.bounds))
            tip, out = pin_end(pin), _OUT[pin.side]
            self.bd.wires.append(BdWire(self._new_id('w'), net, [tip, [_snap(tip[0] + out[0] * 4 * GRID),
                                                                      _snap(tip[1] + out[1] * 4 * GRID)]],
                                        f'pin:{inst.id}:{pin.name}', ''))
            n += 1
        self.statusBar().showMessage(f'Added {n} signal stub(s)', 4000)
        self._reload_scene()

    def add_port_ios(self, inst: BdInstance):
        n = 0
        for pin in self._free_pins(inst):
            net = pin.net or pin.name
            pin.net = net
            mode = pin.mode if pin.mode in ('input', 'output', 'inout') else 'input'
            self._ensure_port(net, mode, pin.bounds)
            tip, out = pin_end(pin), _OUT[pin.side]
            pio = BdPortIo(self._new_id('p'), net, mode, _snap(tip[0] + out[0] * 8 * GRID),
                           _snap(tip[1] + out[1] * 8 * GRID))
            self.bd.port_ios.append(pio)
            px = pio.x - out[0] * PORT_EDGE if out[0] else pio.x - PORT_EDGE
            self.bd.wires.append(BdWire(self._new_id('w'), net, _orthogonal([tip, [px, pio.y]]),
                                        f'pin:{inst.id}:{pin.name}', f'pio:{pio.id}'))
            n += 1
        self.statusBar().showMessage(f'Added {n} port(s)', 4000)
        self._reload_scene()

    def disconnect(self, inst: BdInstance):
        refs = {f'pin:{inst.id}:{p.name}' for p in inst.pins}
        self.bd.wires = [w for w in self.bd.wires if w.start not in refs and w.end not in refs]
        for p in inst.pins:
            p.net = ''
        self._reload_scene()

    def equidistant(self, inst: BdInstance):
        for side in ('left', 'right'):
            pins = sorted((p for p in inst.pins if p.side == side), key=lambda p: p.y)
            if not pins:
                continue
            step = max(PIN_STEP, _snap((inst.h - 40) / (len(pins) - 1))) if len(pins) > 1 else PIN_STEP
            for i, p in enumerate(pins):
                dy = inst.y + 30 + i * step - p.y
                if dy:
                    ref = f'pin:{inst.id}:{p.name}'
                    for w in self.bd.wires:
                        for which in ('start', 'end'):
                            if getattr(w, which) == ref:
                                _shift_end(w, which, 0, dy)
                    p.y += dy
        self._reload_scene()

    def update_interface(self, inst: BdInstance):
        info = self._interface(inst)
        if not info or not info['ports']:
            QMessageBox.warning(self, 'Update interface', f'Interface of {inst.library}.{inst.unit} not found.')
            return
        before = {p.name for p in inst.pins}
        self._layout_pins(inst, info['ports'])
        after = {p.name for p in inst.pins}
        gone = {f'pin:{inst.id}:{n}' for n in before - after}
        self.bd.wires = [w for w in self.bd.wires if w.start not in gone and w.end not in gone]
        # wires still attached follow their pin to its new place
        pos = {f'pin:{inst.id}:{p.name}': (p.x, p.y) for p in inst.pins}
        for w in self.bd.wires:
            for which, idx in (('start', 0), ('end', -1)):
                r = getattr(w, which)
                if r in pos and w.points:
                    ex, ey = w.points[idx]
                    _shift_end(w, which, pos[r][0] - ex, pos[r][1] - ey)
        self.log.addItem(f'{inst.name}: {len(after - before)} pin(s) added, {len(before - after)} removed')
        self._reload_scene()

    # -- clipboard -------------------------------------------------------------------------
    def copy(self):
        from dataclasses import asdict
        sel = self.scene.selectedItems()
        self._clipboard = [asdict(i.obj) for i in sel if isinstance(i, InstanceItem)] + \
            [dict(asdict(i.obj), _kind='frame') for i in sel if isinstance(i, FrameItem)]
        self.statusBar().showMessage(f'Copied {len(self._clipboard)} object(s)', 3000)

    def cut(self):
        self.copy()
        self.delete_selected()

    def paste(self, at: QPointF | None = None):
        from ..bd_model import _build
        if not self._clipboard or self.scene.readonly:
            return
        ox = at.x() - min(c['x'] for c in self._clipboard) if at is not None else 40.0
        oy = at.y() - min(c['y'] for c in self._clipboard) if at is not None else 40.0
        names = {i.name for i in self.bd.instances}
        for data in self._clipboard:
            if data.get('_kind') == 'frame':
                fr = _build(BdFrame, {k: v for k, v in data.items() if k != '_kind'})
                fr.id = self._new_id('f')
                fr.number = max((f.number for f in self.bd.frames), default=0) + 1
                taken = {f.name for f in self.bd.frames}
                base, k = fr.name, 0
                while fr.kind != 'else' and fr.name in taken:
                    k += 1
                    fr.name = f'{base}_{k}'
                fr.x, fr.y = _snap(fr.x + ox), _snap(fr.y + oy)
                self.bd.frames.append(fr)
                continue
            inst = _build(BdInstance, data)
            inst.id = self._new_id('i')
            base, k = inst.name, 0
            while inst.name in names:
                k += 1
                inst.name = f'{base}_{k}'
            names.add(inst.name)
            dx, dy = _snap(inst.x + ox) - inst.x, _snap(inst.y + oy) - inst.y
            inst.x, inst.y = inst.x + dx, inst.y + dy
            for p in inst.pins:
                p.x, p.y, p.net = p.x + dx, p.y + dy, ''
            self.bd.instances.append(inst)
        self._reload_scene()

    def _new_id(self, prefix: str) -> str:
        used = {i.id for i in self.bd.instances} | {e.id for e in self.bd.embedded} | \
               {p.id for p in self.bd.port_ios} | {w.id for w in self.bd.wires} | {f.id for f in self.bd.frames}
        k = 1
        while f'{prefix}n{k}' in used:
            k += 1
        return f'{prefix}n{k}'

    def _pin(self, ref: str) -> BdPin | None:
        if not ref.startswith('pin:'):
            return None
        _, iid, pname = ref.split(':', 2)
        inst = next((i for i in self.bd.instances if i.id == iid), None)
        return next((p for p in inst.pins if p.name == pname), None) if inst else None

    def _pio(self, ref: str) -> BdPortIo | None:
        if not ref.startswith('pio:'):
            return None
        return next((p for p in self.bd.port_ios if p.id == ref[4:]), None)

    def add_wire(self, start_ref: str, end_ref: str, a: list, bends: list, b: list):
        bd = self.bd
        ends = [self._pin(start_ref), self._pin(end_ref)]
        pios = [self._pio(start_ref), self._pio(end_ref)]
        nets = {p.net for p in ends if p and p.net} | {p.name for p in pios if p}
        if len(nets) > 1:
            QMessageBox.warning(self, 'Add wire', f'The two ends are already on different nets: {", ".join(sorted(nets))}')
            return
        if nets:
            net = nets.pop()
        else:
            first = next((p for p in ends if p), None)
            net, ok = QInputDialog.getText(self, 'New net', 'Net name:', text=first.name if first else 'net')
            net = net.strip()
            if not ok or not net:
                return
        for p in ends:
            if p:
                p.net = net
        if not any(s.name == net for s in bd.signals):
            bounds = next((p.bounds for p in ends if p and p.bounds), '')
            bd.signals.append(Sig(net, 'local', 'wire', bounds))
        bd.wires.append(BdWire(self._new_id('w'), net, _route(a, bends, b), start_ref, end_ref))
        self.scene.load(bd)
        self.signals_tab.set_rows(bd.signals)
        self.changed()

    def _selected_net(self) -> str:
        w = next((i.obj for i in self.scene.selectedItems() if isinstance(i, WireItem)), None)
        return w.net if w else ''

    def edit_net_inline(self, net: str, pos: QPointF):
        """Edit the net name (and bus bounds, as name[msb:lsb]) in a box on the diagram."""
        if not net or self.scene.readonly:
            return
        sig = next((s for s in self.bd.signals if s.name == net), None)
        ed = QLineEdit(net + (sig.bounds if sig is not None and sig.bounds else ''), self.canvas.viewport())
        ed.setFont(QFont('Courier New', 9))
        ed.setMinimumWidth(max(160, ed.fontMetrics().horizontalAdvance(ed.text()) + 30))
        ed.adjustSize()
        ed.move(self.canvas.mapFromScene(pos) - QPoint(10, ed.height() // 2))
        ed.selectAll()
        done = []

        def finish(apply: bool):
            if done:
                return
            done.append(1)
            text = ed.text().strip()
            ed.deleteLater()
            if apply and text:
                QTimer.singleShot(0, lambda: self.apply_net_text(net, text))

        ed.returnPressed.connect(lambda: finish(True))
        ed.installEventFilter(self)
        self.canvas.viewport().installEventFilter(self)     # a click on the diagram cancels
        self._inline_editor = (ed, finish)
        ed.show()
        ed.setFocus()

    def _build_view_actions(self):
        """Entries of the legacy View menu that are not toolbar commands."""
        def act(key, text, slot=None, shortcut='', checkable=False, checked=False):
            a = QAction(text, self)
            if shortcut:
                a.setShortcut(QKeySequence(shortcut))
            if checkable:
                a.setCheckable(True); a.setChecked(checked)
                if slot is not None:
                    a.toggled.connect(slot)
            elif slot is not None:
                a.triggered.connect(slot)
            else:
                a.setEnabled(False)
            self.toolbar_actions[key] = a
            return a
        act('refresh', '&Refresh', self._refresh_view, 'F5').setStatusTip('Redraws the active diagram')
        act('view_panel', 'View &Panel')                     # no panels in this version
        act('grid', '&Grid', self._show_grid, checkable=True, checked=True)
        tb = act('toolbars', '&Toolbars', lambda: None)
        menu = QMenu(self)
        menu.aboutToShow.connect(lambda: (menu.clear(), [menu.addAction(t.toggleViewAction())
                                                          for t in self.findChildren(QToolBar)]))
        tb.setMenu(menu)
        act('status_bar', '&Status Bar', lambda on: self.statusBar().setVisible(on), checkable=True, checked=True)
        self.object_tips = True
        act('object_tips', 'Object &Tips', lambda on: setattr(self, 'object_tips', on), checkable=True, checked=True)
        act('diagram_browser', '&Diagram Browser', lambda on: self.browser_dock.setVisible(on),
            checkable=True, checked=True)
        self.browser_dock.visibilityChanged.connect(self.toolbar_actions['diagram_browser'].setChecked)
        act('signals_table', 'Signals Table', lambda: self.tabs.setCurrentIndex(1))
        act('page_break', 'Page Break Preview')
        self.canvas.viewport().installEventFilter(self)

    def _refresh_view(self):
        self._reload_scene()
        self.canvas.viewport().update()

    def _show_grid(self, on: bool):
        self.canvas.show_grid = on
        self.canvas.viewport().update()

    def eventFilter(self, obj, e):
        if obj is self.canvas.viewport() and e.type() == QEvent.ToolTip and not getattr(self, 'object_tips', True):
            return True                         # Object Tips off
        ie = getattr(self, '_inline_editor', None)
        if ie and obj is self.canvas.viewport() and e.type() == QEvent.MouseButtonPress:
            ie[1](False)
            self._inline_editor = None
        if ie and obj is ie[0]:
            if e.type() == QEvent.ShortcutOverride and e.key() == Qt.Key_Escape:
                e.accept()              # Esc belongs to the editor, not to the window's Select shortcut
                return True
            if e.type() == QEvent.KeyPress and e.key() == Qt.Key_Escape:
                ie[1](False)
                return True
            if e.type() == QEvent.FocusOut:
                ie[1](False)            # clicking elsewhere cancels, as in the legacy editor
        return super().eventFilter(obj, e)

    # -- connecting by dragging -------------------------------------------------------
    def port_dropped(self, pio: BdPortIo):
        """A free port dropped on a net connector connects to that net and takes its name."""
        if any(True for _ in self.scene._attached(f'pio:{pio.id}')):
            return
        best = None
        for w in self.bd.wires:
            for which, k in (('start', 0), ('end', -1)):
                if getattr(w, which):
                    continue
                end = w.points[k]
                d = min(abs(end[0] - (pio.x + s * PORT_EDGE)) for s in (1, -1)) + abs(end[1] - pio.y)
                if abs(end[1] - pio.y) <= 8 and abs(end[0] - pio.x) <= PORT_EDGE + 12 and (best is None or d < best[0]):
                    best = (d, w, which, k)
        if best is None:
            return
        _, w, which, k = best
        nxt = w.points[1] if k == 0 else w.points[-2]
        side = 1 if nxt[0] > pio.x else -1
        edge = [pio.x + side * PORT_EDGE, pio.y]
        _shift_end(w, which, edge[0] - w.points[k][0], edge[1] - w.points[k][1])
        w.points = _simplify(w.points)
        setattr(w, which, f'pio:{pio.id}')
        self._port_takes_net(pio, w.net)
        self.statusBar().showMessage(f'Port connected to net {w.net}', 4000)
        QTimer.singleShot(0, self._reload_scene)

    def end_dropped(self, w: BdWire):
        """A dangling net end dropped on a free pin or on a port connects to it.
        On a port, the net takes the port's name."""
        for which, k in (('start', 0), ('end', -1)):
            if getattr(w, which):
                continue
            hit = self.scene.pin_at(QPointF(*w.points[k]))
            if hit is None:
                continue
            ref, pt, pin, pio = hit
            if pin is not None:
                if pin.net not in ('', w.net):
                    self.statusBar().showMessage(f'Pin {pin.name} is already on net {pin.net}', 5000)
                    continue
                pin.net = w.net
            setattr(w, which, ref)
            w.points[k] = [pt.x(), pt.y()]
            w.points = _simplify(_orthogonal(w.points))
            if pio is not None and pio.name != w.net:
                self._rename(w.net, pio.name)
                self._ensure_port(pio.name, pio.mode)
            QTimer.singleShot(0, self._reload_scene)

    def _port_takes_net(self, pio: BdPortIo, net: str):
        """Rename a port to the net it is connected to; the net becomes a port of the module."""
        old = pio.name
        pio.name = net
        sig = next((s for s in self.bd.signals if s.name == net), None)
        old_sig = next((s for s in self.bd.signals if s.name == old), None)
        if sig is None:
            self._ensure_port(net, pio.mode, old_sig.bounds if old_sig else '')
        else:
            sig.mode = pio.mode
        if old != net and not any(p.name == old for p in self.bd.port_ios) \
                and not any(w.net == old for w in self.bd.wires):
            self.bd.signals = [s for s in self.bd.signals if s.name != old]

    def apply_net_text(self, old: str, text: str):
        """Text typed for a net: "name" or "name[msb:lsb]" (bounds change the signal to a bus)."""
        m = re.fullmatch(r'\s*([A-Za-z_][\w$]*)\s*(\[[^\]]*\])?\s*', text)
        if m is None:
            self.statusBar().showMessage(f'"{text}" is not a valid net name', 5000)
            return
        new, bounds = m.group(1), m.group(2)
        sig = next((s for s in self.bd.signals if s.name == old), None)
        changed = False
        if bounds is not None and sig is not None and sig.bounds != bounds:
            sig.bounds = bounds
            changed = True
        if new != old:
            if any(s.name == new for s in self.bd.signals) and not QMessageBox.question(
                    self, 'Rename net', f'A signal "{new}" already exists. Connect the two nets?') == QMessageBox.Yes:
                return
            self._rename(old, new)
            changed = True
        if changed:
            self._reload_scene()

    def rename_net(self, old: str):
        if not old or self.scene.readonly:
            return
        new, ok = QInputDialog.getText(self, 'Rename net', f'New name for net "{old}":', text=old)
        new = new.strip()
        if not ok or not new or new == old:
            return
        if any(s.name == new for s in self.bd.signals) and not QMessageBox.question(
                self, 'Rename net', f'A signal "{new}" already exists. Connect the two nets?') == QMessageBox.Yes:
            return
        self._rename(old, new)
        self._reload_scene()

    def _rename(self, old: str, new: str):
        """Rename a net everywhere: wires, pins, ports and the signal table."""
        bd = self.bd
        for w in bd.wires:
            if w.net == old:
                w.net = new
        for inst in bd.instances:
            for p in inst.pins:
                if p.net == old:
                    p.net = new
        for p in bd.port_ios:
            if p.name == old:
                p.name = new
        if any(s.name == new for s in bd.signals):
            bd.signals = [s for s in bd.signals if s.name != old]
        else:
            for s in bd.signals:
                if s.name == old:
                    s.name = new

    def delete_selected(self):
        if self.scene.delete_selected():
            self.signals_tab.set_rows(self.bd.signals)

    def _double_click(self, e):
        item = self.canvas.itemAt(e.position().toPoint())
        if isinstance(item, InstanceItem) and self.scene.mode == 'select':
            self.open_instance(item.obj)
            return
        FsmGraphicsView.mouseDoubleClickEvent(self.canvas, e)

    def open_down(self):
        inst = next((i.obj for i in self.scene.selectedItems() if isinstance(i, InstanceItem)), None)
        if inst:
            self.open_instance(inst)

    def open_instance(self, inst: BdInstance):
        if self.context is not None:
            self.context.manager.open_unit_by_name(inst.unit, inst.library)

    # -- output ------------------------------------------------------------------------
    def regenerate(self):
        self.log.clear()
        text, warnings = generate_bd(self.bd)
        self.code.set_code(text)
        ext = 'sv' if self.bd.language == 'systemverilog' else 'v'
        self.code_title.setText(f'<b>Generated HDL</b> — {self.bd.unit}.{ext} ({LANG_LABEL[self.bd.language]}) '
                                f'— {len(self.bd.instances)} instances, {text.count(chr(10))} lines')
        for w in warnings:
            self.log.addItem(w)
        if not warnings:
            self.log.addItem('Generation OK - no warnings')

    def update_title(self):
        b = self.bd
        ro = ' [read-only]' if self.context is not None and self.context.readonly else ''
        proj = f'Project {self.context.project_name}: ' if self.context is not None else ''
        self.setWindowTitle(f'{proj}{b.library}/{b.unit}/{b.view} (Block Diagram){ro}{" *" if self.dirty else ""}')

    def save(self):
        if self.context is not None and self.context.save(self.bd, self):
            self.dirty = False
            self.update_title()

    def generate(self):
        if self.context is not None:
            self.context.generate(self.bd, self)

    def open_generated(self):
        if self.context is not None:
            self.context.open_generated(self.bd)

    def closeEvent(self, e):
        if self.dirty:
            r = QMessageBox.question(self, 'Unsaved changes', 'Save changes to this block diagram?',
                                     QMessageBox.Save | QMessageBox.Discard | QMessageBox.Cancel)
            if r == QMessageBox.Cancel:
                e.ignore()
                return
            if r == QMessageBox.Save:
                self.save()
        save_view_state(self._view_key(), self.canvas.state())
        if self.context is not None:
            self.context.release()
        e.accept()
