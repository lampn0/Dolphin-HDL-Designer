"""Import a legacy HDS state machine view (.sm) into an FsmView."""
from __future__ import annotations

import math
import os
import re
from typing import Any, Iterator

from ..model import (FsmView, Junction, Link, Machine, Parameter, Point, Signal,
                     State, Transition)
from .sexpr import Document, Node, Ref, parse_file

# HDS coordinates are ~75 units per screen pixel at 100% zoom.
SCALE = 1.0 / 75.0

_MODE = {None: 'input', 1: 'output', 2: 'inout', 4: 'local'}
_SCHEME = {0: 'comb', 1: 'clocked', 2: 'registered'}
_POINT = {'SmResetPoint': 'reset', 'SmClockPoint': 'clock', 'InterruptPoint': 'interrupt',
          'SmRecoveryStatePoint': 'recovery', 'SmEnablePoint': 'enable'}


def _walk(value: Any) -> Iterator[Node]:
    stack = [value]
    while stack:
        v = stack.pop()
        if isinstance(v, Node):
            yield v
            stack.extend(val for _, val in reversed(v.fields))
        elif isinstance(v, list):
            stack.extend(reversed(v))


def _text(node: Any) -> str:
    """First `st` string found in a node subtree."""
    for n in _walk(node):
        st = n.get('st')
        if isinstance(st, str):
            return st
    return ''


def _center(node: Any) -> tuple[float, float]:
    for n in _walk(node.get('shape') if isinstance(node, Node) else None):
        xt = n.get('xt')
        if isinstance(xt, str) and xt.count(',') == 3:
            x1, y1, x2, y2 = (float(v) for v in xt.split(','))
            return (x1 + x2) / 2 * SCALE, (y1 + y2) / 2 * SCALE
    return 0.0, 0.0


def _top_left(node: Node) -> tuple[float, float] | None:
    shape = node.get('shape')
    xt = shape.get('xt') if isinstance(shape, Node) else None
    if isinstance(xt, str) and xt.count(',') == 3:
        x1, y1, _, _ = (float(v) for v in xt.split(','))
        return x1 * SCALE, y1 * SCALE
    return None


def _transition_geometry(t: Transition, n: Node, m: Machine) -> None:
    """Bend points, attach angles and label position as drawn in the legacy tool."""
    shape = n.get('shape')
    pts = shape.get('pts') if isinstance(shape, Node) else None
    if isinstance(pts, list) and len(pts) >= 2:
        xy = [[float(v) * SCALE for v in str(p).split(',')] for p in pts]
        a, b = m.node(t.src), m.node(t.dst)
        if a is not None:
            t.start_angle = math.atan2(xy[0][1] - a.y, xy[0][0] - a.x)
        if b is not None:
            t.end_angle = math.atan2(xy[-1][1] - b.y, xy[-1][0] - b.x)
        t.points = xy[1:-1]
    tb = n.get('tb')
    if isinstance(tb, Node):
        corner = _top_left(tb)
        if corner:
            t.label_x, t.label_y = corner


def _labelled_texts(doc: Document) -> dict[str, str]:
    """Map caption -> text for caption/text pairs ("Pre Actions:" -> "...")."""
    out: dict[str, str] = {}
    for n in doc.walk():
        if n.type == 'BiTextGroup':
            out[_text(n.get('first'))] = n.get('second').get('st') or ''
        vec = n.get('textVec')
        if isinstance(vec, list):
            for a, b in zip(vec, vec[1:]):
                if isinstance(a, Node) and isinstance(b, Node) and a.type == 'Text' and b.type == 'MLText':
                    out.setdefault(a.get('st') or '', b.get('st') or '')
    return out


def _signals(doc: Document) -> list[Signal]:
    group_of: dict[int, str] = {}
    for n in doc.walk():
        if n.type == 'LGroup':
            for child in n.get('optionalChildren') or []:
                if isinstance(child, Node):
                    group_of[id(child)] = n.get('name') or ''
    sigs = []
    for n in doc.walk():
        if n.type != 'LeafLogPort':
            continue
        port = n.get('port')
        decl = port.get('decl')
        mode = _MODE.get(port.get('m'), 'input')
        expr = n.get('expr') or ''
        category = 'data'
        if n.get('cat') is not None:
            category = 'clock' if 'edge' in expr else 'reset'
        if mode in ('output', 'local'):
            scheme = 'none' if n.get('ass') == '<none>' else _SCHEME.get(n.get('scheme'), 'comb')
        else:
            scheme = 'none'
        sigs.append(Signal(
            name=decl.get('n'), mode=mode, type=decl.get('t') or 'wire', bounds=decl.get('b') or '',
            signed=bool(decl.get('s')), group=group_of.get(id(n), ''), category=category,
            expression=expr, scheme=scheme, default=n.get('defVal') or '', reset=n.get('rstVal') or '',
            comment=re.sub(r'^\s*//\s*', '', decl.get('eolc') or ''),
            value=decl.get('iv') or '', array=decl.get('ub') or ''))
    return sigs


def _row_positions(doc: Document) -> dict[int, int]:
    """Display row of each table entry (MRCItem litem &N pos P)."""
    pos = {}
    for n in doc.walk():
        if n.type == 'MRCItem' and isinstance(n.get('litem'), Ref) and isinstance(n.get('pos'), int):
            pos.setdefault(n.get('litem').label, n.get('pos'))
    return pos


def _parameters(doc: Document) -> list[Parameter]:
    rows = _row_positions(doc)
    found = []
    for n in doc.walk():
        if n.type == 'LogGeneric':
            g = n.get('generic')
            found.append((rows.get(n.label, 1 << 30),
                          Parameter(name=g.get('name'), value=g.get('value') or '', type=g.get('type') or '')))
    return [p for _, p in sorted(found, key=lambda x: x[0])]


def symbol_parameters(path: str) -> list[tuple[str, str]]:
    """(name, default declaration) rows of a legacy symbol's Parameters table, in table order."""
    return [(p.name, p.value) for p in _parameters(parse_file(path))]


def _machine(doc: Document, csm: Node, header_machine: Node | None) -> Machine:
    m = Machine(name=csm.get('name') or 'fsm')
    if header_machine is not None and header_machine.get('stateSignalName'):
        m.current_state_name = header_machine.get('stateSignalName')
    ids: dict[int, str] = {}
    diagram = csm.get('topDiagram')
    order = {}
    for i, ref in enumerate(csm.get('stateOrder') or []):
        if isinstance(ref, Ref):
            order[ref.label] = i
    for n in _walk(diagram):
        if n.label is None:
            continue
        x, y = _center(n)
        nid = f'n{n.label}'
        if n.type == 'State':
            st = State(id=nid, name=_text(n.get('name')), x=x, y=y, encoding=_text(n.get('encoding')))
            blk = n.get('actionBlk')
            if isinstance(blk, Node):
                st.entry_actions = _text(blk.get('entryActions'))
                st.in_actions = _text(blk.get('inActions'))
                st.exit_actions = _text(blk.get('exitActions'))
                corner = _top_left(blk)
                if corner:
                    st.actions_x, st.actions_y = corner
            m.states.append(st)
        elif n.type == 'Junction':
            expr = _text(n.get('caseExpr'))
            if expr.startswith('CASE:'):
                expr = expr[5:].strip()
            m.junctions.append(Junction(id=nid, kind='case' if n.get('jType') == 1 else 'if', expr=expr, x=x, y=y))
        elif n.type == 'Link':
            m.links.append(Link(id=nid, target=_text(n.get('name')), x=x, y=y))
        elif n.type in _POINT:
            m.points.append(Point(id=nid, kind=_POINT[n.type], x=x, y=y))
        else:
            continue
        ids[n.label] = nid
    m.states.sort(key=lambda s: order.get(int(s.id[1:]), 1 << 30))
    for n in _walk(diagram):
        if n.type != 'Transition':
            continue
        src, dst = n.get('start'), n.get('end')
        if not (isinstance(src, Ref) and isinstance(dst, Ref)) or src.label not in ids or dst.label not in ids:
            continue
        tb, tp = n.get('tb'), n.get('tp')
        actions = _text(tb.get('actions')) if isinstance(tb, Node) else ''
        if actions.strip() == '< Automatic >':
            actions = ''
        prio = _text(tp.get('pr')) if isinstance(tp, Node) else ''
        t = Transition(
            id=f'n{n.label}' if n.label is not None else m.new_id('t'), src=ids[src.label], dst=ids[dst.label],
            cond=n.get('cond') or '', actions=actions, priority=int(prio) if prio.isdigit() else 1)
        _transition_geometry(t, n, m)
        m.transitions.append(t)
    for i, t in enumerate(m.transitions):
        if t.id in ids.values() or any(o.id == t.id for o in m.transitions[:i]):
            t.id = m.new_id('t')
    return m


def import_sm(path: str, library: str | None = None, unit: str | None = None) -> FsmView:
    doc = parse_file(path)
    parts = os.path.normpath(os.path.abspath(path)).split(os.sep)
    view_name = os.path.splitext(parts[-1])[0]
    unit = unit or (parts[-2] if len(parts) > 1 else 'unit')
    if library is None:
        library = parts[-4] if len(parts) > 3 and parts[-3] == 'hds' else 'work'
    model = doc.get('model')
    lang = model.get('LanguageMgr') or ''
    texts = _labelled_texts(doc)
    view = FsmView(
        library=library, unit=unit, view=view_name,
        language='systemverilog' if 'SystemVerilog' in lang else 'verilog',
        signals=_signals(doc), parameters=_parameters(doc), machines=[],
        pre_module_directives=texts.get('Pre-module directives:', ''),
        post_module_directives=texts.get('Post-module directives:', ''),
        end_module_directives=texts.get('End-module directives:', ''),
        concurrent_statements=texts.get('Concurrent Statements', ''),
        state_register_statements=texts.get('State Register Statements', ''),
        global_pre_actions=texts.get('Pre Actions:', ''),
        global_post_actions=texts.get('Post Actions:', ''),
        registered_affix=model.get('signalSuffix') or '_r',
        clocked_affix=model.get('clockSuffix') or '_cld',
    )
    header = doc.get('Header')
    header_machines = []
    if isinstance(header, Node) and isinstance(header.get('machine'), Node):
        header_machines = [c for c in header.get('machine').get('children') or [] if isinstance(c, Node)]
    for i, csm in enumerate(n for n in doc.walk() if n.type == 'ConcurrentSM'):
        view.machines.append(_machine(doc, csm, header_machines[i] if i < len(header_machines) else None))
    return view
