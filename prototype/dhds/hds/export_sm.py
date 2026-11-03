"""Write a state diagram back to an HDS .sm file, so HDS and Dolphin HDS both read and write the
same file.

The file is not generated from scratch: the .sm the diagram was read from is parsed again and
only what was changed in Dolphin is changed in it (positions, texts, end points of transitions,
deleted objects). Everything Dolphin does not model (HDS settings, colours, fonts, uids, ...)
is written back exactly as it was; a diagram saved without changes is byte for byte the file
that was read (see hds.sexpr).

    export_sm(view, src, dst, geometry=None) -> list of warnings

`geometry` (optional, given by the editor) has what only the drawing knows: for each
transition id, 'pts' (the line as drawn: start, route points, end; scene units) and 'prio'
(the centre of its priority circle).

Objects added in Dolphin are made from the templates HDS keeps in the file (model >
defaultState, defaultTransition, ...), with new uids and labels; their ids in the view are
changed to the labels they got ('n<label>'), as if read from the file.

Not written yet (reported as warnings): hierarchical states added in Dolphin, changes of the
signal / declaration tables.
"""
from __future__ import annotations

import copy
from typing import Any, Callable, Iterator

from ..model import FsmView, Machine
from .import_sm import SCALE, _geo_sig, import_sm
from .sexpr import Atom, Document, Node, Ref, parse_file, write_file

U = 1 / SCALE                 # HDS units per scene unit
CHAR_W, LINE_H = 500, 900     # HDS's estimate of a courier 8 character / text line


# -- low level ------------------------------------------------------------------------------
def _set(node: Node, key: str, value: Any) -> None:
    """Set a field of an object (the first one of that name), or add it at the end."""
    for i, (k, _) in enumerate(node.fields):
        if k == key:
            node.fields[i] = (k, value)
            return
    node.fields.append((key, value))


def _drop(node: Node, key: str) -> None:
    node.fields[:] = [(k, v) for k, v in node.fields if k != key]


def _nums(s: str) -> list[int]:
    return [int(round(float(v))) for v in s.split(',')]


def _join(vals) -> str:
    return ','.join(str(int(round(v))) for v in vals)


def _shift(value: Any, dx: int, dy: int, skip: tuple[str, ...] = ()) -> None:
    """Move an object and everything inside it by (dx, dy) HDS units: every extent ("xt"),
    text baseline ("blo") and point list ("pts"). Fields named in `skip` are left alone
    (e.g. a state's action block, which has a place of its own)."""
    if not (dx or dy):
        return
    stack = [value]
    while stack:
        v = stack.pop()
        if isinstance(v, list):
            stack.extend(v)
            continue
        if not isinstance(v, Node):
            continue
        for i, (k, x) in enumerate(v.fields):
            if k in skip:
                continue
            if k == 'xt' and isinstance(x, str) and x.count(',') == 3:
                a = _nums(x)
                v.fields[i] = (k, _join([a[0] + dx, a[1] + dy, a[2] + dx, a[3] + dy]))
            elif k == 'blo' and isinstance(x, str) and x.count(',') == 1:
                a = _nums(x)
                v.fields[i] = (k, _join([a[0] + dx, a[1] + dy]))
            elif k == 'pts' and isinstance(x, list):
                v.fields[i] = (k, [_join([a[0] + dx, a[1] + dy]) if (a := _nums(p) if isinstance(p, str) else None)
                                   else p for p in x])
            elif isinstance(x, (Node, list)):
                stack.append(x)


def _text_node(node: Any) -> Node | None:
    """The Text / MLText holding the string of a text field (directly, or in a TextAssociate)."""
    if not isinstance(node, Node):
        return None
    if isinstance(node.get('st'), str):
        return node
    for k in ('text', 'cond'):
        t = _text_node(node.get(k))
        if t is not None:
            return t
    return None


def _set_text(t: Node, s: str) -> None:
    """Change the string of a Text / MLText. Its extent is estimated as HDS does (500 units a
    character, 900 a line, for courier 8; HDS lays the text out again when it reads it),
    keeping the side it is justified on (ju 0 centre, 2 right, else left) and its top."""
    if t.get('st') == s:
        return
    _set(t, 'st', s)
    xt = t.get('xt')
    if not (isinstance(xt, str) and xt.count(',') == 3):
        return
    x0, y0, x1, y1 = _nums(xt)
    lines = s.split('\n')
    w = CHAR_W * max(len(l) for l in lines)
    old_lines = max(1, len(str(t.get('st')).split('\n')))
    lh = (y1 - y0) // old_lines if y1 > y0 else LINE_H
    h = max(LINE_H, lh) * len(lines)
    ju = t.get('ju')
    if ju == 0:
        cx = (x0 + x1) // 2
        x0, x1 = cx - w // 2, cx + w - w // 2
    elif ju == 2:
        x0 = x1 - w
    else:
        x1 = x0 + w
    _set(t, 'xt', _join([x0, y0, x1, y0 + h]))


def _hide(t: Node, hidden: bool) -> None:
    """Show or hide a text (its VaSet isHidden)."""
    va = t.get('va')
    if not isinstance(va, Node):
        if not hidden:
            return
        va = Node('VaSet', [])
        t.fields.insert(1 if t.fields and t.fields[0][0] == 'uid' else 0, ('va', va))
    if hidden:
        _set(va, 'isHidden', 1)
    else:
        _drop(va, 'isHidden')


def _labelled(diagram: Node) -> Iterator[Node]:
    """The labelled objects of a diagram, depth first (states inside hierarchical ones too)."""
    stack = [diagram]
    while stack:
        v = stack.pop()
        if isinstance(v, list):
            stack.extend(reversed(v))
        elif isinstance(v, Node):
            if v.label is not None:
                yield v
            stack.extend(x for _, x in reversed(v.fields))


def _remove(doc: Document, labels: set[int]) -> None:
    """Remove the objects with these labels from the lists holding them, and every reference
    to them (e.g. the state order of the machine)."""
    stack: list[Any] = [v for _, v in doc.fields]
    while stack:
        v = stack.pop()
        if isinstance(v, list):
            v[:] = [x for x in v if not ((isinstance(x, Node) and x.label in labels) or
                                         (isinstance(x, Ref) and x.label in labels))]
            stack.extend(v)
        elif isinstance(v, Node):
            stack.extend(x for _, x in v.fields)
    for lab in labels:
        doc.labels.pop(lab, None)


def _label(oid: str) -> int | None:
    """The file label of an object id read from a .sm ('n<label>'), else None (new object)."""
    return int(oid[1:]) if oid.startswith('n') and oid[1:].isdigit() else None


# -- objects --------------------------------------------------------------------------------
def _delta(new: float, old: float) -> int:
    return int(round((new - old) * U))


def _update_state(n: Node, s, o, warn: list[str]) -> None:
    """A state (o: as read, s: now): place, name, actions and their block's place."""
    dx, dy = _delta(s.x, o.x), _delta(s.y, o.y)
    _shift(n, dx, dy, skip=('actionBlk', 'childDiagram'))
    if s.name != o.name:
        t = _text_node(n.get('name'))
        if t is not None:
            _set_text(t, s.name)
    blk = n.get('actionBlk')
    if isinstance(blk, Node):
        if s.actions_x is not None and o.actions_x is not None:
            _shift(blk, _delta(s.actions_x, o.actions_x), _delta(s.actions_y, o.actions_y))
        else:
            _shift(blk, dx, dy)
        if (s.entry_actions, s.in_actions, s.exit_actions) != (o.entry_actions, o.in_actions, o.exit_actions):
            x0, y0, _, _ = _xt(blk.get('shape')) or [int(s.x * U) + 4000, int(s.y * U) + 3000, 0, 0]
            _layout_actions(blk, x0, y0, s.entry_actions, s.in_actions, s.exit_actions)
    elif (s.entry_actions, s.in_actions, s.exit_actions) != (o.entry_actions, o.in_actions, o.exit_actions):
        warn.append(f'state {s.name}: actions not written (the file has no action block for it)')


def _layout_actions(blk: Node, x0: int, y0: int, entry: str, inner: str, exit_: str) -> None:
    """Lay a state's action block out at (x0, y0) for these texts, as HDS 2021.1 draws it:
    the entry actions, a line, the state actions, a line, the exit actions, 100 units around
    each; a framed box (light blue, width 2) when there are entry or exit actions, the blue
    triangles at the left of the entry (pointing in) and exit texts; state actions alone: the
    text only."""
    framed = bool(entry.strip() or exit_.strip())
    parts = [('entryActions', entry, 'tline'), ('inActions', inner, 'bline'), ('exitActions', exit_, None)]
    w = max([CHAR_W * max(len(l) for l in t.split('\n')) for _, t, _ in parts if t.strip()] or [CHAR_W])
    y = y0 + 100
    for k, (field, text, line) in enumerate(parts):
        t = _text_node(blk.get(field)) or blk.get(field)
        if isinstance(t, Node):
            _set(t, 'st', text)
            h = LINE_H * len(text.split('\n')) if text.strip() else 0
            _set(t, 'xt', _join([x0 + 100, y, x0 + 100 + w, y + max(h, 1)]))
            _hide(t, not text.strip())
            y += h
        ln = blk.get(line) if line else None
        if isinstance(ln, Node):
            # the line under the entry (tline) / state (bline) actions: shown in a framed
            # block when something comes after it
            show = framed and bool(text.strip()) and any(x.strip() for _, x, _ in parts[k + 1:])
            y += 100
            _set(ln, 'xt', _join([x0 + 100, y, x0 + 100 + w, y]))
            _set(ln, 'pts', [_join([x0 + 100, y]), _join([x0 + 100 + w, y])])
            _hide(ln, not show)
            y += 100 if show else 0
    box = blk.get('shape')
    if isinstance(box, Node):
        _set(box, 'xt', _join([x0, y0, x0 + w + 200, y + 100]))
        _hide(box, not framed)
        va = box.get('va')
        if isinstance(va, Node):
            _set(va, 'lineWidth', 2 if framed else -1)
    for tri, field, text in (('ttri', 'entryActions', entry), ('btri', 'exitActions', exit_)):
        tr, t = blk.get(tri), blk.get(field)
        if isinstance(tr, Node) and _xt(t):
            ty = _xt(t)[1] + LINE_H // 2
            _set(tr, 'xt', _join([x0 - 350, ty - 175, x0, ty + 175]))
            _hide(tr, not text.strip())


def _update_node(n: Node, obj, old) -> None:
    """A junction, link or state point: place and texts."""
    _shift(n, _delta(obj.x, old.x), _delta(obj.y, old.y), skip=('childDiagram',))
    if hasattr(obj, 'expr') and obj.expr != old.expr:
        t = _text_node(n.get('caseExpr'))
        if t is not None:
            _set_text(t, f'CASE: {obj.expr}')
    if hasattr(obj, 'target') and obj.target != old.target:
        t = _text_node(n.get('name'))
        if t is not None:
            _set_text(t, obj.target)


def _update_transition(n: Node, t, o, geo: dict | None, m: Machine) -> None:
    """A transition: its ends, its line, its text block (place, condition, actions) and its
    priority. The line and the priority circle are kept as in the file while nothing they
    depend on moved (the drawing of an unchanged line may differ from HDS's by a unit)."""
    if t.hds.get('geo_sig') == _geo_sig(t, m) and t.src == o.src and t.dst == o.dst:
        geo = None
    for key, new, old in (('start', t.src, o.src), ('end', t.dst, o.dst)):
        if new != old and _label(new) is not None:
            _set(n, key, Ref(_label(new)))
    shape = n.get('shape')
    if geo and geo.get('pts') and isinstance(shape, Node):
        pts = [[x * U, y * U] for x, y in geo['pts']]
        old = [_nums(p) for p in shape.get('pts') or [] if isinstance(p, str)]
        new = [[int(round(x)), int(round(y))] for x, y in pts]
        if new != old:
            _set(shape, 'pts', [_join(p) for p in new])
            xs, ys = [p[0] for p in new], [p[1] for p in new]
            _set(shape, 'xt', _join([min(xs), min(ys), max(xs), max(ys)]))
    tb = n.get('tb')
    if isinstance(tb, Node):
        if t.label_x is not None and o.label_x is not None:
            _shift(tb, _delta(t.label_x, o.label_x), _delta(t.label_y, o.label_y))
        if t.cond != o.cond or t.actions != o.actions:
            before = _block_layout(tb)
            if t.cond != o.cond:
                _set(n, 'cond', t.cond)
                c = _text_node(tb.get('condition'))
                if c is not None:
                    _set_text(c, t.cond)
                    _hide(c, not t.cond.strip())
            if t.actions != o.actions:
                a = _text_node(tb.get('actions'))
                if a is not None:
                    _set_text(a, t.actions if t.actions.strip() else '< Automatic >')
                    _hide(a, not t.actions.strip())
            _fit_block(tb, before)
    tp = n.get('tp')
    if isinstance(tp, Node):
        pr = _text_node(tp.get('pr'))
        if pr is not None and t.priority != o.priority:
            _set_text(pr, str(t.priority))
        circle = tp.get('shape')
        if geo and geo.get('prio') and isinstance(circle, Node) and isinstance(circle.get('xt'), str):
            x0, y0, x1, y1 = _nums(circle.get('xt'))
            cx, cy = geo['prio'][0] * U, geo['prio'][1] * U
            _shift(tp, int(round(cx - (x0 + x1) / 2)), int(round(cy - (y0 + y1) / 2)))


def _shown(t: Node | None) -> bool:
    va = t.get('va') if t is not None else None
    return t is not None and not (isinstance(va, Node) and va.get('isHidden') == 1)


def _xt(t: Any) -> list[int] | None:
    xt = t.get('xt') if isinstance(t, Node) else None
    return _nums(xt) if isinstance(xt, str) and xt.count(',') == 3 else None


def _block_layout(tb: Node) -> dict:
    """The layout of a transition's text block before its texts change: extents of the box,
    the condition, the line and the actions, and which texts are shown."""
    cond, acts = _text_node(tb.get('condition')), _text_node(tb.get('actions'))
    return {'box': _xt(tb.get('shape')), 'cond': _xt(cond), 'acts': _xt(acts),
            'line': _xt(tb.get('lineShape')), 'cond_shown': _shown(cond), 'acts_shown': _shown(acts)}


def _fit_block(tb: Node, before: dict) -> None:
    """Lay a transition's text block out again after its texts changed, keeping the margins
    it had (they differ between files and HDS versions): the texts centred, the box grows or
    shrinks to the widest one, the line and the actions move down / up by the change of the
    condition's height, the box's bottom follows. Its top-left stays. HDS lays the block out again when
    it reads the file; this keeps the file close to what it will show."""
    box = tb.get('shape')
    b = before['box']
    if not isinstance(box, Node) or b is None:
        return
    bx0, by0, bx1, by1 = b
    cond, acts, line = _text_node(tb.get('condition')), _text_node(tb.get('actions')), tb.get('lineShape')
    oc, oa, ol = before['cond'], before['acts'], before['line']
    olds = [x for x, shown in ((oc, before['cond_shown']), (oa, before['acts_shown'])) if x and shown]
    # HDS centres the texts in the box, the widest one `pad` from each side
    pad = ((bx1 - bx0) - max([x[2] - x[0] for x in olds] or [0])) // 2
    pad = pad if pad > 0 else 500
    news = [t for t in (cond, acts) if _shown(t) and _xt(t)]
    w = max([_xt(t)[2] - _xt(t)[0] for t in news] or [CHAR_W])
    cx = bx0 + pad + w // 2                                          # the new centre line

    def left(t):
        return cx - (_xt(t)[2] - _xt(t)[0]) // 2
    # the condition: its height change moves everything under it
    dh = 0
    if cond is not None and _xt(cond) and oc:
        c = _xt(cond)
        _shift(cond, left(cond) - c[0], oc[1] - c[1])
        dh = ((c[3] - c[1]) if _shown(cond) else 0) - ((oc[3] - oc[1]) if before['cond_shown'] else 0)
    ly = None
    if isinstance(line, Node) and ol:
        ly = ol[1] + dh
        _set(line, 'xt', _join([bx0 + pad, ly, bx0 + pad + w, ly]))
        _set(line, 'pts', [_join([bx0 + pad, ly]), _join([bx0 + pad + w, ly])])
    bottom = by1 + dh
    if acts is not None and _xt(acts):
        a = _xt(acts)
        if _shown(acts):
            if before['acts_shown'] and oa:
                top = oa[1] + dh
                below = by1 - oa[3]                                  # margin under the actions
            else:
                # newly shown: as far under the line as the line is under the condition
                gap = (ol[1] - oc[3]) if (ol and oc) else 400
                top = (ly if ly is not None else (oc[3] + dh if oc else by0 + pad)) + gap
                below = 500
            _shift(acts, left(acts) - a[0], top - a[1])
            bottom = top + (a[3] - a[1]) + below
        elif before['acts_shown'] and oa:
            # actions now hidden: the box ends under the line as far as the line is under the condition
            bottom = (ly if ly is not None else by1) + ((ol[1] - oc[3]) if (ol and oc) else 400)
    _set(box, 'xt', _join([bx0, by0, bx0 + 2 * pad + w, bottom]))


# -- new objects ----------------------------------------------------------------------------
class _Alloc:
    """New labels (*N) and uids for objects added to a file: after the largest in use. The
    file's lastUid is kept up to date (HDS counts on from it)."""

    def __init__(self, doc: Document):
        self.doc = doc
        self.label = max(doc.labels or [0])
        self.holder = next((n for n in doc.walk() if isinstance(n.get('lastUid'), str)), None)
        self.uid = int(str(self.holder.get('lastUid')).split(',')[0]) if self.holder is not None else 0
        for n in doc.walk():
            u = n.get('uid')
            if isinstance(u, str) and u.split(',')[0].isdigit():
                self.uid = max(self.uid, int(u.split(',')[0]))

    def new_label(self) -> int:
        self.label += 1
        return self.label

    def give_uids(self, node: Node) -> None:
        """A uid for the object and every part of it that has one in HDS files (all but the
        attribute sets VaSet and CaseSettings), placed first as HDS writes it."""
        stack = [node]
        while stack:
            v = stack.pop()
            if isinstance(v, list):
                stack.extend(v)
            elif isinstance(v, Node):
                if v.type not in ('VaSet', 'CaseSettings') and v.get('uid') is None:
                    self.uid += 1
                    v.fields.insert(0, ('uid', Atom(f'{self.uid},0')))
                stack.extend(x for _, x in v.fields)
        if self.holder is not None:
            _set(self.holder, 'lastUid', Atom(f'{self.uid},0'))


def _template(doc: Document, key: str) -> Node | None:
    """A copy of one of the object templates HDS keeps in the file's model."""
    model = doc.get('model')
    t = model.get(key) if isinstance(model, Node) else None
    return copy.deepcopy(t) if isinstance(t, Node) else None


def _walk_nodes(v: Any) -> Iterator[Node]:
    stack = [v]
    while stack:
        x = stack.pop()
        if isinstance(x, list):
            stack.extend(reversed(x))
        elif isinstance(x, Node):
            yield x
            stack.extend(y for _, y in reversed(x.fields))


def _shape_center(n: Node) -> tuple[int, int]:
    for x in _walk_nodes(n.get('shape')):
        a = _xt(x)
        if a:
            return (a[0] + a[2]) // 2, (a[1] + a[3]) // 2
    return 0, 0


def _place_new(n: Node, x: float, y: float, alloc: _Alloc) -> Node:
    """A template made a real object: uids, a label, its shape centred on (x, y) (scene units)."""
    cx, cy = _shape_center(n)
    _shift(n, int(round(x * U)) - cx, int(round(y * U)) - cy)
    alloc.give_uids(n)
    n.label = alloc.new_label()
    alloc.doc.labels[n.label] = n
    return n


def _center_text(t: Node | None, s: str, cx: int, cy: int, char_w: int = CHAR_W, h: int = LINE_H) -> None:
    """Put a one-line text centred on (cx, cy)."""
    if not isinstance(t, Node):
        return
    w = char_w * max(1, len(s))
    _set(t, 'st', s)
    _set(t, 'xt', _join([cx - w // 2, cy - h // 2, cx + w - w // 2, cy + h - h // 2]))
    if t.get('blo') is not None:
        _set(t, 'blo', _join([cx, cy + h // 2 - 200]))


_POINT_TEMPLATES = {'clock': 'defaultClk', 'reset': 'defaultRst', 'enable': 'defaultEnable',
                    'interrupt': 'defaultInterruptPoint', 'recovery': 'defaultRecStatePt',
                    'entry': 'defaultEntryPoint', 'exit': 'defaultExitPoint'}


def _new_node(doc: Document, obj, alloc: _Alloc, warn: list[str]) -> Node | None:
    """An HDS object for a state, junction, link or point added in Dolphin."""
    from ..model import Junction, Link, Point, State
    if isinstance(obj, State):
        if obj.hier:
            warn.append(f'new hierarchical state {obj.name} not written (not supported yet)')
            return None
        n = _template(doc, 'defaultWaitState' if obj.is_wait else 'defaultState')
        if n is None:
            return None
        _place_new(n, obj.x, obj.y, alloc)
        cx, cy = _shape_center(n)
        if obj.radius:
            r = int(round(obj.radius * U))
            sh = n.get('shape')
            _set(sh, 'xt', _join([cx - r, cy - r, cx + r, cy + r]))
            if sh.get('radius') is not None:
                _set(sh, 'radius', r)
        _center_text(_text_node(n.get('name')), obj.name, cx, cy, 600, 1000)
        if obj.is_wait and obj.wait:
            t = _text_node(n.get('wait'))
            if t is not None:
                _set(t, 'st', obj.wait)
        blk = n.get('actionBlk')
        if isinstance(blk, Node) and (obj.entry_actions or obj.in_actions or obj.exit_actions):
            r = int(round((obj.radius or 40) * U))
            x0 = int(round(obj.actions_x * U)) if obj.actions_x is not None else cx + r + 500
            y0 = int(round(obj.actions_y * U)) if obj.actions_y is not None else cy - r
            _layout_actions(blk, x0, y0, obj.entry_actions, obj.in_actions, obj.exit_actions)
        return n
    if isinstance(obj, Junction):
        n = _template(doc, 'defaultJunction')
        if n is None:
            return None
        _place_new(n, obj.x, obj.y, alloc)
        cx, cy = _shape_center(n)
        sym = obj.symbol or ('case' if obj.kind == 'case' else '&')
        _center_text(_text_node(n.get('symbol')), sym, cx, cy, 600, 1000)
        if obj.kind == 'case':
            _set(n, 'jType', 1)
            t = _text_node(n.get('caseExpr'))
            if t is not None:
                _set_text(t, f'CASE: {obj.expr}')
                _hide(t, False)
        return n
    if isinstance(obj, Link):
        n = _template(doc, 'defaultLink')
        if n is None:
            return None
        _place_new(n, obj.x, obj.y, alloc)
        t = _text_node(n.get('name'))
        if t is not None:
            _set_text(t, obj.target)
        return n
    if isinstance(obj, Point):
        n = _template(doc, _POINT_TEMPLATES.get(obj.kind, ''))
        if n is None:
            return None
        return _place_new(n, obj.x, obj.y, alloc)
    return None


def _new_transition(doc: Document, t, m: Machine, labels: dict[str, int], geo: dict | None,
                    alloc: _Alloc) -> Node | None:
    """An HDS transition for one added in Dolphin: its ends, line, text block and priority."""
    n = _template(doc, 'defaultTransition')
    a, b = labels.get(t.src), labels.get(t.dst)
    if n is None or a is None or b is None:
        return None
    src, dst = m.node(t.src), m.node(t.dst)
    pts = (geo or {}).get('pts') or [(src.x, src.y), *[tuple(p) for p in t.points], (dst.x, dst.y)]
    pts = [[int(round(x * U)), int(round(y * U))] for x, y in pts]
    alloc.give_uids(n)
    n.label = alloc.new_label()
    doc.labels[n.label] = n
    # the ends, after the line, as HDS writes them
    k = next(i for i, (key, _) in enumerate(n.fields) if key == 'shape') + 1
    n.fields[k:k] = [('start', Ref(a)), ('end', Ref(b))]
    sh = n.get('shape')
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    _set(sh, 'pts', [_join(p) for p in pts])
    k = next(i for i, (key, _) in enumerate(sh.fields) if key == 'pts')
    sh.fields.insert(k, ('xt', _join([min(xs), min(ys), max(xs), max(ys)])))
    _set(n, 'cond', t.cond)
    tb = n.get('tb')
    if isinstance(tb, Node):
        c, acts, line = _text_node(tb.get('condition')), tb.get('actions'), tb.get('lineShape')
        before = _block_layout(tb)
        before['acts_shown'] = False             # the template's actions are an empty point
        if c is not None:
            _set_text(c, t.cond or ' ')
            _hide(c, not t.cond.strip())
        if isinstance(acts, Node):
            _set_text(acts, t.actions if t.actions.strip() else '< Automatic >')
            _hide(acts, not t.actions.strip())
        if isinstance(line, Node):
            _hide(line, False)
        _fit_block(tb, before)
        # the block where Dolphin has it, else beside the middle of the line
        box = _xt(tb.get('shape'))
        if box:
            if t.label_x is not None:
                tx, ty = int(round(t.label_x * U)), int(round(t.label_y * U))
            else:
                mx, my = (pts[0][0] + pts[-1][0]) // 2, (pts[0][1] + pts[-1][1]) // 2
                tx, ty = mx + 500, my - (box[3] - box[1]) - 500
            _shift(tb, tx - box[0], ty - box[1])
    tp = n.get('tp')
    if isinstance(tp, Node):
        pr = _text_node(tp.get('pr'))
        if pr is not None:
            _set(pr, 'st', str(t.priority))
        c = _xt(tp.get('shape'))
        if c:
            if geo and geo.get('prio'):
                px, py = int(round(geo['prio'][0] * U)), int(round(geo['prio'][1] * U))
            else:
                px, py = (pts[0][0] * 4 + pts[1][0]) // 5, (pts[0][1] * 4 + pts[1][1]) // 5
            _shift(tp, px - (c[0] + c[2]) // 2, py - (c[1] + c[3]) // 2)
            shown = len(m.outgoing(t.src)) > 1
            _hide(tp.get('shape'), not shown)
            if pr is not None:
                _hide(pr, not shown)
    return n


def _container(diagram: Node, parent_label: int | None, by_label: dict[int, Node]) -> list:
    """The list a new object goes into: the diagram's objects, or those of the hierarchical
    state it is inside."""
    if parent_label is not None and parent_label in by_label:
        child = by_label[parent_label].get('childDiagram')
        diagram = child if isinstance(child, Node) else diagram
    lst = diagram.get('optionalChildren')
    if not isinstance(lst, list):
        lst = []
        _set(diagram, 'optionalChildren', lst)
    return lst


def _renamed(m: Machine, ids: dict[str, str]) -> None:
    """Give the objects added to the file the ids of their labels ('n<label>') in the view,
    with every reference to them, as if they had been read from the file."""
    for x in (*m.states, *m.junctions, *m.links, *m.points, *m.transitions):
        if x.id in ids:
            x.id = ids[x.id]
        if getattr(x, 'parent', '') in ids:
            x.parent = ids[x.parent]
    for t in m.transitions:
        t.src, t.dst = ids.get(t.src, t.src), ids.get(t.dst, t.dst)


# -- the file -------------------------------------------------------------------------------
def _machine_nodes(doc: Document) -> list[Node]:
    return [n for n in doc.walk() if n.type == 'ConcurrentSM']


def export_sm(view: FsmView, src: str, dst: str,
              geometry: Callable[[str], dict] | dict | None = None) -> list[str]:
    """Write `view` to `dst` as the .sm `src` (the file it was read from) changed by what was
    edited since. Returns warnings for what could not be written."""
    doc = parse_file(src)
    orig = import_sm(src, library=view.library, unit=view.unit)
    warn: list[str] = []
    get_geo = geometry if callable(geometry) else (lambda tid: (geometry or {}).get(tid))
    removed: set[int] = set()
    alloc = _Alloc(doc)
    for csm, m, o in zip(_machine_nodes(doc), view.machines, orig.machines):
        diagram = csm.get('topDiagram')
        by_label = {n.label: n for n in _labelled(diagram)}
        added: dict[str, str] = {}               # Dolphin id -> 'n<label>' of the objects added
        new_ids = {x.id for x in (*m.states, *m.junctions, *m.links, *m.points, *m.transitions)}
        olds = {x.id: x for x in (*o.states, *o.junctions, *o.links, *o.points, *o.transitions)}
        for oid in olds:
            if oid not in new_ids and _label(oid) is not None:
                removed.add(_label(oid))
        order = csm.get('stateOrder')
        state_ids = {s.id for s in m.states}
        for obj in (*m.states, *m.junctions, *m.links, *m.points):
            n, old = by_label.get(_label(obj.id)), olds.get(obj.id)
            if n is not None and old is not None:
                if obj.id in state_ids:
                    _update_state(n, obj, old, warn)
                else:
                    _update_node(n, obj, old)
                continue
            n = _new_node(doc, obj, alloc, warn)
            if n is None:
                warn.append(f'new {type(obj).__name__.lower()} {getattr(obj, "name", "")} not written')
                continue
            parent = getattr(obj, 'parent', '')
            parent = added.get(parent, parent)
            _container(diagram, _label(parent) if parent else None, by_label).append(n)
            by_label[n.label] = n
            added[obj.id] = f'n{n.label}'
            if obj.id in state_ids and isinstance(order, list):
                order.append(Ref(n.label))
        labels = {x.id: _label(added.get(x.id, x.id))
                  for x in (*m.states, *m.junctions, *m.links, *m.points)}
        for t in m.transitions:
            n, old = by_label.get(_label(t.id)), olds.get(t.id)
            if n is not None and old is not None:
                _update_transition(n, t, old, get_geo(t.id), m)
                continue
            n = _new_transition(doc, t, m, labels, get_geo(t.id), alloc)
            if n is None:
                warn.append(f'new transition {t.cond or "(always)"} not written')
                continue
            src = m.node(t.src)
            parent = getattr(src, 'parent', '') if src is not None else ''
            parent = added.get(parent, parent)
            _container(diagram, _label(parent) if parent else None, by_label).append(n)
            added[t.id] = f'n{n.label}'
        _renamed(m, added)
    if len(view.machines) != len(orig.machines):
        warn.append('added / removed concurrent state machines not written')
    for f in ('signals', 'parameters', 'pre_module_directives', 'post_module_directives',
              'end_module_directives', 'concurrent_statements', 'state_register_statements',
              'global_pre_actions', 'global_post_actions'):
        if getattr(view, f) != getattr(orig, f):
            warn.append(f'{f.replace("_", " ")}: changes not written yet')
    _remove(doc, removed)
    write_file(doc, dst)
    return warn
