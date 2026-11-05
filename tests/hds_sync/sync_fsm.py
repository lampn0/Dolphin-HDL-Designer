"""Working on one state diagram with both tools, through fsm.sm and symbol.sb: an edit saved
by one tool must be what the other reads, keeps and generates.

    python tests/hds_sync/sync_fsm.py [case ...]       # Dolphin -> HDS cases (all by default)

Direction Dolphin -> HDS. A scratch HDS project is made in tests/hds_sync/work/d2h
(library sync_lib), one design unit per case and base diagram: a copy of fsm.sm + symbol.sb of
uart_tx (examples/uart_hds, made in HDS 2021.1) and of gc_control_fsm (the real project).
For each unit:

  1. Dolphin: the diagram is opened in the editor window, the case's edit is made on it and
     it is saved the way File > Save does (hds.export_sm with the scene's geometry). The
     file read again must have the edit ("dolphin saved").
  2. HDS 2021.1, batch (hds_batch.py), on every unit in one run: open the view, save it,
     generate its HDL, check the symbol's ports.
  3. Checks:
       hds open / save / generate   no Tcl error, no error in HDS's log for the unit
       hds keeps the edit           the file HDS saved, read by Dolphin, is the diagram Dolphin
                                    saved (states, transitions, texts, signals, ...)
       same HDL                     HDS's generated HDL = Dolphin's for the file Dolphin saved
                                    (from "// State encoding" on; the header has dates)
       symbol ports                 the ports in symbol.sb = the ports of the diagram

Results: tests/hds_sync/results/d2h.md (one line per check), the diffs next to it.
"""
from __future__ import annotations

import difflib
import os
import re
import shutil
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'src'))
sys.path.insert(0, HERE)
from hds_batch import WORK, run_tcl  # noqa: E402

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

BASES = {
    # the HDS-made UART example of this repository (examples/uart_hds)
    'tx': os.path.join(os.path.dirname(os.path.dirname(HERE)), 'examples', 'uart_hds', 'uart_lib', 'hds',
                       'uart_tx'),
    'gc': r'D:\workspace\src\libs\protocol_controller\hds\gc_control_fsm',
}
LIB = 'sync_lib'
RESULTS = os.path.join(HERE, 'results')
MARK = '// State encoding'


# -- what a diagram is, for comparing two reads of it --------------------------------------
def snap(view) -> dict:
    """The content of a diagram both tools must agree on, independent of ids: states by name
    (position rounded to 1 unit, actions), transitions by end names, junction / link / point
    counts and texts, the declaration texts, signals, machine properties."""
    m = view.machines[0]

    def name(nid):
        """A name for node `nid` that does not depend on ids (state name, kind / link target)."""
        n = m.node(nid)
        if n is None:
            return '?'
        return getattr(n, 'name', None) or f'{type(n).__name__}:{getattr(n, "kind", "")}{getattr(n, "target", "")}' \
            f'@{round(n.x)},{round(n.y)}'
    return {
        'states': sorted((s.name, round(s.x), round(s.y), s.entry_actions.strip(), s.in_actions.strip(),
                          s.exit_actions.strip(), s.is_wait, s.hier) for s in m.states),
        'transitions': sorted((name(t.src), name(t.dst), t.cond.strip(), t.actions.strip(), t.priority)
                              for t in m.transitions),
        'junctions': sorted((j.kind, j.expr, round(j.x), round(j.y)) for j in m.junctions),
        'links': sorted((lk.target, round(lk.x), round(lk.y)) for lk in m.links),
        'points': sorted((p.kind, round(p.x), round(p.y)) for p in m.points),
        'signals': sorted((s.name, s.mode, s.type, s.bounds, s.category, s.expression, s.scheme, s.default,
                           s.reset, s.comment.strip()) for s in view.signals),
        'texts': {f: getattr(view, f).strip() for f in (
            'pre_module_directives', 'post_module_directives', 'end_module_directives',
            'concurrent_statements', 'state_register_statements', 'global_pre_actions',
            'global_post_actions', 'registered_affix', 'clocked_affix')},
        'machine': (m.name, m.current_state_name, m.next_state_name),
        'hidden': sorted(view.decl_hidden),
    }


def snap_diff(a: dict, b: dict) -> list[str]:
    """The differences between two snap() results, as readable lines."""
    out = []
    for k in a:
        if a[k] != b[k]:
            if isinstance(a[k], list):
                sa, sb = set(map(repr, a[k])), set(map(repr, b[k]))
                out += [f'{k} only Dolphin: {x}' for x in sorted(sa - sb)][:6]
                out += [f'{k} only HDS:     {x}' for x in sorted(sb - sa)][:6]
            else:
                out.append(f'{k}: Dolphin {a[k]!r} / HDS {b[k]!r}'[:400])
    return out


# -- the edits (each gets the editor window, returns what must be true after) ---------------
def _first_state_with_out(m):
    """The first state with a transition to another state."""
    ids = {s.id for s in m.states}
    return next(s for s in m.states if any(t.src == s.id and t.dst in ids for t in m.transitions))


def _names(view):
    """An input and a driven signal (output or local) of the diagram, so that the edits stay
    valid Verilog (HDS checks the HDL it generates)."""
    ins = [s.name for s in view.signals if s.mode == 'input' and s.category == 'data']
    outs = [s for s in view.signals if s.mode in ('output', 'local') and s.category == 'data']
    out = next((s for s in outs if s.scheme != 'none'), outs[0])
    return ins[0], out.name


def e_none(win):
    """Case "none": save without any change."""
    return 'nothing changed'


def e_move_rename(win):
    """Case: move a state and rename it (the links to it follow)."""
    m = win.machine
    s = _first_state_with_out(m)
    s.x += 40; s.y -= 20
    for lk in m.links:
        if lk.target == s.name:
            lk.target = s.name + '_R'
    s.name += '_R'
    return f'state {s.name} moved and renamed'


def e_add_state_transition(win):
    """Case: add a state and transitions to and from it."""
    m = win.machine
    from model import State, Transition
    a = _first_state_with_out(m)
    st = State(id=m.new_id('s'), name='ST_DOLPHIN_NEW', x=a.x + 160, y=a.y + 120)
    m.states.append(st)
    # after the conditional ways out, before the unconditional one (HDS wants it lowest)
    outs = [t for t in m.transitions if t.src == a.id]
    prio = 1 + max((t.priority for t in outs if t.cond.strip()), default=0)
    for t in outs:
        if t.priority >= prio:
            t.priority += 1
    m.transitions.append(Transition(id=m.new_id('t'), src=a.id, dst=st.id, cond=_names(win.view)[0],
                                    actions='', priority=prio))
    m.transitions.append(Transition(id=m.new_id('t'), src=st.id, dst=a.id, cond='', priority=1))
    return 'new state with a transition in and out'


def e_edit_transition(win):
    """Case: change the condition and the actions of a transition."""
    m = win.machine
    ids = {s.id for s in m.states}
    t = next(t for t in m.transitions if t.src in ids and t.dst in ids and t.cond)
    i, o = _names(win.view)
    t.cond = f'({t.cond}) & {i}'
    t.actions = (t.actions.rstrip() + '\n' if t.actions.strip() else '') + f'{o} = {o};'
    return 'condition and actions of a transition changed'


def e_state_actions(win):
    """Case: add a state action to a state."""
    m = win.machine
    s = _first_state_with_out(m)
    _i, o = _names(win.view)
    s.in_actions = (s.in_actions.rstrip() + '\n' if s.in_actions.strip() else '') + f'{o} = {o};'
    return f'state actions of {s.name} changed'


def e_delete(win):
    """Case: delete a transition between two states."""
    m = win.machine
    ids = {s.id for s in m.states}
    # a transition between two states, from a state with more than one way out
    between = [t for t in m.transitions if t.src in ids and t.dst in ids]
    t = next((t for t in between if sum(1 for o in m.transitions if o.src == t.src) > 1), between[-1])
    m.transitions.remove(t)
    return 'a transition deleted'


def e_machine_props(win):
    """Case: change statement blocks, directives and machine properties."""
    v, m = win.view, win.machine
    v.concurrent_statements = (v.concurrent_statements.rstrip() + '\n' if v.concurrent_statements.strip() else '') \
        + '// concurrent statement added by Dolphin'
    _i, o = _names(v)
    v.global_pre_actions = f'{o} = {o};'
    v.end_module_directives = '// end of module (dolphin)'
    m.next_state_name = 'next_st_q'
    return 'statement blocks, directives, next state name'


def e_add_port(win):
    """Case: add an input and a clocked output port (the symbol must follow)."""
    from model import Signal
    v = win.view
    v.signals.append(Signal(name='dolphin_in', mode='input'))
    v.signals.append(Signal(name='dolphin_out', mode='output', bounds='[3:0]', type='reg', scheme='clocked',
                            default="4'b0", reset="4'b0"))
    return 'an input and an output port added (signals table -> symbol)'


def e_change_ports(win):
    """Bounds of a vector input changed, comment of an output changed, an input that no text
    uses deleted (when there is one)."""
    v, m = win.view, win.machine
    done = []
    vec = next((s for s in v.signals if s.mode == 'input' and s.bounds), None)
    if vec is not None:
        hi = int(vec.bounds.strip('[]').split(':')[0]) if vec.bounds.strip('[]').split(':')[0].isdigit() else 7
        vec.bounds = f'[{hi + 8}:0]'
        done.append(f'{vec.name} {vec.bounds}')
    out = next(s for s in v.signals if s.mode == 'output')
    out.comment = 'comment changed by Dolphin'
    done.append(f'{out.name} comment')
    texts = ' '.join([v.concurrent_statements, v.state_register_statements, v.global_pre_actions,
                      v.global_post_actions] + [t.cond + ' ' + t.actions for t in m.transitions] +
                     [s.entry_actions + s.in_actions + s.exit_actions for s in m.states] +
                     [j.expr for j in m.junctions] + [x.expression for x in v.signals])
    unused = next((s for s in v.signals if s.mode == 'input' and s.category == 'data'
                   and not re.search(rf'\b{re.escape(s.name)}\b', texts)), None)
    if unused is not None:
        v.signals.remove(unused)
        done.append(f'{unused.name} deleted')
    return 'ports changed: ' + ', '.join(done)


CASES = {'none': e_none, 'move_rename': e_move_rename, 'add': e_add_state_transition,
         'transition': e_edit_transition, 'state_actions': e_state_actions, 'delete': e_delete,
         'props': e_machine_props, 'port': e_add_port, 'port_change': e_change_ports}


# -- the scratch project --------------------------------------------------------------------
def make_project(root: str, units: dict[str, str]) -> str:
    """A scratch HDS project in `root` with one library holding a copy of each base diagram under
    the unit names of `units`; returns the .hdp path.
    """
    if os.path.isdir(root):
        shutil.rmtree(root)
    for sub in ('hds', 'hdl'):
        os.makedirs(os.path.join(root, LIB, sub))
    for unit, src in units.items():
        d = os.path.join(root, LIB, 'hds', unit)
        os.makedirs(d)
        for f in ('fsm.sm', 'symbol.sb'):
            shutil.copy(os.path.join(src, f), d)
    hdp = os.path.join(root, 'sync.hdp')
    with open(hdp, 'w', newline='\n') as f:
        f.write(f'[hdl]\n{LIB} = $HDS_PROJECT_DIR/{LIB}/hdl\n[hds]\n{LIB} = $HDS_PROJECT_DIR/{LIB}/hds\n'
                f'[hds_settings]\ndefault_library = {LIB}\nversion = 3\n[library_type]\n{LIB} = regular\n'
                f'[shared]\nothers = $HDS_TEAM_HOME/shared.hdp\n')
    return hdp


def symbol_ports(path: str) -> list[tuple[str, str]]:
    """(name, mode) of the ports of a symbol.sb: its LogicalPort declarations, both the
    interface table's and the drawn ports', each once; the templates HDS keeps for new ports
    (fields named default...) are not ports."""
    from hds.sexpr import Node, parse_file
    modes = {None: 'input', 1: 'output', 2: 'inout'}
    out = set()

    def walk(v, skip=False):
        """Collect the LogicalPort declarations under `v` (skipping the copies inside drawn ports when
        `skip`).
        """
        if isinstance(v, Node):
            if v.type == 'LogicalPort' and not skip:
                decl = v.get('decl')
                nm = decl.get('n') if isinstance(decl, Node) else None
                if nm:
                    out.add((nm, modes.get(v.get('m'), str(v.get('m')))))
            for k, x in v.fields:
                walk(x, skip or k.startswith('default'))
        elif isinstance(v, list):
            for x in v:
                walk(x, skip)
    doc = parse_file(path)
    for k, v in doc.fields if hasattr(doc, 'fields') else []:
        walk(v, k.startswith('default'))
    return sorted(out)


def hdl_from_mark(text: str, indent: bool = True) -> str:
    """The generated HDL from MARK on; indent=False: each line without its leading spaces
    (the indent width is an HDS preference: 3 on this HDS 2021.1, 2 on the server's 2024.2)."""
    text = text.replace('\r\n', '\n')
    text = text[text.index(MARK):] if MARK in text else text
    return text if indent else '\n'.join(l.lstrip(' ') for l in text.split('\n'))


def unit_log(log: str, unit: str) -> list[str]:
    """HDS's log lines about one unit: those naming it, and its generation section (from the
    line "sync_lib/<unit>" to the next "Generation completed")."""
    out, inside = [], False
    for line in log.splitlines():
        s = line.strip()
        if s == f'{LIB}/{unit}':
            inside = True
        elif inside and s.startswith('Generation completed'):
            out.append(s)
            inside = False
        if inside or unit in line:
            out.append(s)
    return out


def main() -> int:
    """Run the selected cases: edit and save in Dolphin, then open / check / save / generate in
    batch HDS and compare. Returns the exit code.
    """
    names = [a for a in sys.argv[1:] if a in CASES] or list(CASES)
    root = os.path.join(WORK, 'd2h')
    units = {f'{b}_{c}': BASES[b] for c in names for b in BASES}
    hdp = make_project(root, units)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    from gui.main_window import MainWindow
    from hds.export_sm import export_sm
    from hds.import_sm import import_sm
    from project.generate import generate_text

    rows, expect, dol_ports = [], {}, {}

    def row(unit, check, ok, detail=''):
        """Record and print one result row (unit, check, PASS / FAIL, detail)."""
        rows.append((unit, check, ok, detail))
        print(('PASS' if ok else 'FAIL'), f'{unit:22} {check:24} {detail[:150]}', flush=True)

    # 1. Dolphin edits and saves
    for unit in units:
        case = unit.split('_', 1)[1]
        path = os.path.join(root, LIB, 'hds', unit, 'fsm.sm')
        win = MainWindow()
        win.open_path(path)
        win.show()
        QTest.qWait(150)
        what = CASES[case](win)
        win.scene.load(win.view, win.machine)
        win.scene.changed_model.emit()
        QTest.qWait(50)
        warn = export_sm(win.view, path, path, win.scene.hds_geometry)
        intended = snap(win.view)
        win.dirty = False
        win.close()
        saved = import_sm(path, library=LIB, unit=unit)
        d = snap_diff(intended, snap(saved))
        row(unit, 'dolphin saved', not d and not warn, f'{what}; ' + '; '.join(warn + d))
        text, _ = generate_text(saved)
        expect[unit] = (snap(saved), text, path)
        dol_ports[unit] = symbol_ports(os.path.join(os.path.dirname(path), 'symbol.sb'))
        shutil.copy(path, os.path.join(root, unit + '.dolphin.sm'))     # what Dolphin wrote
        shutil.copy(os.path.join(os.path.dirname(path), 'symbol.sb'), os.path.join(root, unit + '.dolphin.sb'))

    # 2. HDS reads, saves, generates
    cmds = []
    for unit in units:
        sym = os.path.join(root, LIB, 'hds', unit, 'symbol.sb').replace('\\', '/')
        # batch HDS opens a view read-only: made writable so that it saves (it then writes
        # fsm.sm and symbol.sb, as the editor's File > Save does)
        cmds += [f'set s_{unit} [::HdsApi::openGraphicalView {LIB} {unit} symbol.sb]',
                 f'[$s_{unit} model] checkDataIntegrity',
                 f'set d_{unit} [::HdsApi::openGraphicalView {LIB} {unit} fsm.sm]',
                 f'$d_{unit} configure readOnly 0',
                 f'[$d_{unit} model] checkDataIntegrity',
                 f'::HdsApi::saveGraphicalView {LIB} {unit} fsm.sm 0 0',
                 f'::HdsApi::runGenerate {LIB} {unit} fsm.sm',
                 f'::SymbolWindow::checkPorts {{{sym}}}']
    t0 = time.time()
    log, res = run_tcl(hdp, cmds)
    with open(os.path.join(root, 'hds.log'), 'w', encoding='utf-8') as f:
        f.write(log)
    print(f'HDS batch {time.time() - t0:.0f} s, {len(res)} commands', flush=True)
    by_cmd = {c: (ok, r) for ok, c, r in res}
    os.makedirs(RESULTS, exist_ok=True)

    # 3. checks
    for unit, (dsnap, dtext, path) in expect.items():
        for step, c in (('hds open symbol', f'set s_{unit} [::HdsApi::openGraphicalView {LIB} {unit} symbol.sb]'),
                        ('hds symbol integrity', f'[$s_{unit} model] checkDataIntegrity'),
                        ('hds open', f'set d_{unit} [::HdsApi::openGraphicalView {LIB} {unit} fsm.sm]'),
                        ('hds data integrity', f'[$d_{unit} model] checkDataIntegrity'),
                        ('hds save', f'::HdsApi::saveGraphicalView {LIB} {unit} fsm.sm 0 0'),
                        ('hds generate', f'::HdsApi::runGenerate {LIB} {unit} fsm.sm')):
            ok, r = by_cmd.get(c, (False, 'not run'))
            if step in ('hds data integrity', 'hds symbol integrity'):
                ok = ok and r.strip() == '1'
            # HDS checks the HDL it wrote; the include files of the real project are not in
            # the scratch project, so their errors are not the diagram's
            errs = [l for l in unit_log(log, unit) if re.search(r'\bError\b|ERROR', l)
                    and 'cannot open include file' not in l]
            if step == 'hds save':
                rewritten = open(path, 'rb').read() != open(os.path.join(root, unit + '.dolphin.sm'), 'rb').read()
                ok = ok and rewritten
                r = r + ('' if rewritten else ' (file not rewritten)')
            row(unit, step, ok and not (step == 'hds generate' and errs), (r + ' ' + ' | '.join(errs))[:300])
        hsnap = snap(import_sm(path, library=LIB, unit=unit))
        d = snap_diff(dsnap, hsnap)
        row(unit, 'hds keeps the edit', not d, '; '.join(d))
        hdl_dir = os.path.join(root, LIB, 'hdl')
        gen = [os.path.join(hdl_dir, f) for f in os.listdir(hdl_dir) if f in (f'{unit}_fsm.v', f'{unit}.v')]
        if not gen:
            row(unit, 'same HDL', False, 'HDS wrote no HDL')
        else:
            hds_text = open(gen[0], encoding='utf-8', errors='replace').read()
            a, b = hdl_from_mark(hds_text, False), hdl_from_mark(dtext, False)
            diff = list(difflib.unified_diff(a.split('\n'), b.split('\n'), f'HDS {unit}', f'Dolphin {unit}',
                                             lineterm='', n=2))
            if diff:
                with open(os.path.join(RESULTS, f'd2h_{unit}.diff'), 'w', encoding='utf-8', newline='\n') as f:
                    f.write('\n'.join(diff) + '\n')
            n = sum(1 for l in diff if l[:1] in '+-' and l[:3] not in ('+++', '---'))
            row(unit, 'same HDL', not diff, f'{n} lines differ (results/d2h_{unit}.diff)' if diff else
                ('indent differs only' if hdl_from_mark(hds_text) != hdl_from_mark(dtext) else ''))
        sym = os.path.join(root, LIB, 'hds', unit, 'symbol.sb')
        ports = sorted((s[0], s[1]) for s in dsnap['signals'] if s[1] in ('input', 'output', 'inout'))
        for check, sp in (('symbol (dolphin saved)', dol_ports[unit]), ('symbol (hds saved)', symbol_ports(sym))):
            row(unit, check, sp == ports, '' if sp == ports else
                f'only diagram {sorted(set(ports) - set(sp))}, only symbol {sorted(set(sp) - set(ports))}')

    with open(os.path.join(RESULTS, 'd2h.md'), 'w', encoding='utf-8', newline='\n') as f:
        f.write('# Dolphin -> HDS: state diagrams through fsm.sm / symbol.sb\n\n| Unit | Check | Result | Detail |\n'
                '|---|---|---|---|\n')
        for unit, check, ok, detail in rows:
            f.write(f'| {unit} | {check} | {"PASS" if ok else "FAIL"} | {detail.replace("|", "/")[:300]} |\n')
    bad = sum(1 for r in rows if not r[2])
    print(f'{len(rows) - bad}/{len(rows)} passed; report {os.path.join(RESULTS, "d2h.md")}')
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main())
