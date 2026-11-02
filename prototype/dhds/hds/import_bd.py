"""Import a legacy HDS block diagram (.bd) into a BlockDiagram."""
from __future__ import annotations

import os

import re

from ..bd_model import BdEmbedded, BdFrame, BdInstance, BdPin, BdPortIo, BdWire, BlockDiagram
from ..model import Parameter
from .import_sm import SCALE, _labelled_texts, _parameters, _signals, _text, _walk
from .sexpr import Node, Ref, parse_file

_MODE = {None: 'input', 1: 'output', 2: 'inout', 3: 'buffer'}


def _rect(node) -> tuple[float, float, float, float]:
    """(x, y, w, h) in scene units from the first xt of a node's shape."""
    for n in _walk(node.get('shape') if isinstance(node, Node) else None):
        xt = n.get('xt')
        if isinstance(xt, str) and xt.count(',') == 3:
            x1, y1, x2, y2 = (float(v) * SCALE for v in xt.split(','))
            return x1, y1, x2 - x1, y2 - y1
    return 0.0, 0.0, 0.0, 0.0


def _extent(node) -> tuple[float, float, float, float]:
    """(x, y, w, h) of everything drawn in a node's shape (a PortIO is a body plus a stub)."""
    boxes = []
    for n in _walk(node.get('shape') if isinstance(node, Node) else None):
        xt = n.get('xt')
        if isinstance(xt, str) and xt.count(',') == 3:
            boxes.append([float(v) * SCALE for v in xt.split(',')])
    if not boxes:
        return 0.0, 0.0, 0.0, 0.0
    x1, y1 = min(b[0] for b in boxes), min(b[1] for b in boxes)
    x2, y2 = max(b[2] for b in boxes), max(b[3] for b in boxes)
    return x1, y1, x2 - x1, y2 - y1


def import_bd(path: str, library: str | None = None, unit: str | None = None) -> BlockDiagram:
    doc = parse_file(path)
    parts = os.path.normpath(os.path.abspath(path)).split(os.sep)
    unit = unit or (parts[-2] if len(parts) > 1 else 'unit')
    if library is None:
        library = parts[-4] if len(parts) > 3 and parts[-3] == 'hds' else 'work'
    model = doc.get('model')
    lang = model.get('LanguageMgr') or ''
    texts = _labelled_texts(doc)
    bd = BlockDiagram(
        library=library, unit=unit, view=os.path.splitext(parts[-1])[0],
        language='systemverilog' if 'SystemVerilog' in lang else 'verilog',
        signals=_signals(doc), parameters=_parameters(doc),
        pre_module_directives=texts.get('Pre-module directives:', ''),
        post_module_directives=texts.get('Post-module directives:', ''),
        end_module_directives=texts.get('End-module directives:', ''))

    # net name of each Net object
    net_name = {}
    for n in doc.walk():
        if n.type == 'Net' and n.label is not None:
            net_name[n.label] = n.get('decl').get('n')

    # which net each pin / port-io / embedded block touches
    touches: dict[int, str] = {}
    wire_ends: list = []
    refs: dict[int, str] = {}         # legacy object label -> our attachment reference
    for n in doc.walk():
        if n.type != 'Wire':
            continue
        on = n.get('on')
        net = net_name.get(on.label) if isinstance(on, Ref) else None
        if not net:
            continue
        pts = []
        shape = n.get('shape')
        if isinstance(shape, Node) and isinstance(shape.get('pts'), list):
            for p in shape.get('pts'):
                x, y = (float(v) * SCALE for v in str(p).split(','))
                pts.append([x, y])
        w = BdWire(f'w{n.label or len(bd.wires)}', net, pts)
        name_text = next((t for t in _walk(n.get('tg')) if t.type == 'Text' and t.get('tm') == 'WireNameMgr'), None)
        if name_text is not None and pts:
            va = name_text.get('va')
            w.show_text = not (isinstance(va, Node) and va.get('isHidden') == 1)
            blo = name_text.get('blo')
            if isinstance(blo, str) and ',' in blo:
                bx, by = (float(v) * SCALE for v in blo.split(','))
                w.label = [bx - pts[0][0], by - pts[0][1]]
        bd.wires.append(w)
        ends = []
        for end in ('start', 'end'):
            r = n.get(end)
            if isinstance(r, Ref):
                touches[r.label] = net
            ends.append(r.label if isinstance(r, Ref) else None)
        wire_ends.append((w, ends))

    # objects under model.default* are templates for new objects, not diagram content
    templates = set()
    for k, v in model.fields:
        if k.startswith('default'):
            templates.update(id(n) for n in _walk(v))

    header = doc.get('Header')
    header_insts = {}
    if isinstance(header, Node):
        for inst in header.get('instances') or []:
            header_insts[inst.get('uid')] = inst

    for sa in (n for n in doc.walk() if n.type == 'SaComponent' and id(n) not in templates):
        hi = header_insts.get(sa.get('uid'))
        labels = {}
        for t in _walk(sa.get('ttg')):
            if t.type == 'Text' and t.get('tm'):
                labels[t.get('tm')] = t.get('st') or ''
        x, y, w, h = _rect(sa)
        inst = BdInstance(
            id=f'i{sa.label}', name=(hi.get('name') if hi else labels.get('InstanceNameMgr', '')),
            library=(hi.get('duLibraryName') if hi else labels.get('BdLibraryNameMgr', '')),
            unit=(hi.get('duName') if hi else labels.get('CptNameMgr', '')), x=x, y=y, w=w, h=h)
        if hi:
            inst.params = [Parameter(e.get('name'), e.get('value') or '') for e in hi.get('elements') or []]
        for c in sa.get('optionalChildren') or []:
            if not (isinstance(c, Node) and c.type == 'CptPort'):
                continue
            lp = c.get('thePort')
            decl = lp.get('decl')
            px, py, pw, ph = _rect(c)
            cx, cy = px + pw / 2, py + ph / 2
            side = min((('left', abs(cx - x)), ('right', abs(cx - (x + w))),
                        ('top', abs(cy - y)), ('bottom', abs(cy - (y + h)))), key=lambda s: s[1])[0]
            inst.pins.append(BdPin(decl.get('n'), _MODE.get(lp.get('m'), 'input'),
                                   touches.get(c.label, ''), decl.get('o') or 0, cx, cy, side, decl.get('b') or ''))
            refs[c.label] = f'pin:{inst.id}:{decl.get("n")}'
        bd.instances.append(inst)

    emb_names = [(n.get('name'), n.get('number')) for n in doc.walk() if n.type == 'EmbeddedInstance']
    for i, ht in enumerate(n for n in doc.walk() if n.type == 'HdlText' and id(n) not in templates):
        et = next((c for c in ht.get('optionalChildren') or [] if isinstance(c, Node) and c.type == 'EmbeddedText'), None)
        text = ''
        if et is not None:
            ct = et.get('commentText')
            text = _text(ct.get('text')) if isinstance(ct, Node) and isinstance(ct.get('text'), Node) else _text(ct)
        name, number = emb_names[i] if i < len(emb_names) else (f'eb{i + 1}', str(i + 1))
        x, y, w, h = _rect(ht)
        bd.embedded.append(BdEmbedded(f'e{ht.label}', name or f'eb{i + 1}', int(number or i + 1), text, x, y, w, h))
        refs[ht.label] = f'emb:e{ht.label}'

    for n in doc.walk():
        if n.type in ('PortIoIn', 'PortIoOut', 'PortIoInOut') and id(n) not in templates:
            x, y, w, h = _extent(n)
            name = touches.get(n.label) or _text(n.get('tg'))
            mode = {'PortIoIn': 'input', 'PortIoOut': 'output'}.get(n.type, 'inout')
            bd.port_ios.append(BdPortIo(f'p{n.label}', name, mode, x + w / 2, y + h / 2))
            refs[n.label] = f'pio:p{n.label}'
    # generate frames: FOR (no style), IF (style 1), ELSE (style 2); title "name: spec"
    for i, n in enumerate(n for n in doc.walk() if n.type == 'Frame' and id(n) not in templates):
        title = next((t.get('st') for t in _walk(n.get('title')) if isinstance(t.get('st'), str)), '')
        m = re.match(r'\s*([\w$]+)\s*:\s*(.*)$', title, re.S)
        name, spec = (m.group(1), m.group(2).strip()) if m else (title.strip() or f'g{i}', '')
        kind = {1: 'if', 2: 'else'}.get(n.get('style'), 'for')
        if kind == 'for' and not spec.startswith('[') and n.get('lb') is not None:
            spec = f'[{n.get("lb")}:{n.get("rb") or 0}]'
        num = next((t.get('st') for t in _walk(n.get('seqNum')) if isinstance(t.get('st'), str)), '')
        x, y, w, h = _rect(n)
        bd.frames.append(BdFrame(f'f{n.label or i}', kind, name, spec, int(num) if num.isdigit() else i + 1,
                                 x, y, w, h))
    for w, (a, b) in wire_ends:
        w.start, w.end = refs.get(a, ''), refs.get(b, '')
    return bd
