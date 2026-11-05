"""HDS -> HDL Studio: a state diagram edited and saved in HDS's own window, read by HDL Studio.

    python tests/hds_sync/check_h2d.py tx|gc <unit folder saved by HDS> <original fsm.sm>

The edits made in HDS 2021.1 (by hand or with hds_do.py) on uart_tx, checked here:
  state START renamed START_H; condition START_H -> DATA "baud_tick & tx_start"; a line
  "tx_busy = 1'b1;" added to START_H's state actions; state STOP moved; state s0 added with a
  transition s0 -> IDLE, condition tx_start, actions "tx_busy = 1'b0;"; input port h_in added
  in the Signals Table.

Checks:
  dolphin reads the edits     every edit above is in HDL Studio's reading of the file
  nothing else changed        the rest of the diagram is as in the original
  symbol ports                symbol.sb (written by HDS) has the diagram's ports
  same HDL                    HDS's generated HDL (batch HDS on a copy of the saved files) =
                              HDL Studio's for the same file (leading spaces apart)
  dolphin save unchanged      the file opened in HDL Studio's editor and saved without an edit is
                              byte for byte HDS's file (HDL Studio does not damage it)
  dolphin edit, HDS reads     a further edit in HDL Studio (s0's actions) saved; batch HDS opens
                              it, checks its integrity, generates
"""
from __future__ import annotations

import difflib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'src'))
sys.path.insert(0, HERE)
from hds_batch import WORK, run_tcl  # noqa: E402
from sync_fsm import LIB, hdl_from_mark, make_project, snap, symbol_ports  # noqa: E402

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

results = []


def check(name, ok, detail=''):
    """Record and print one check (PASS / FAIL, its name and a detail)."""
    results.append(ok)
    print(('PASS' if ok else 'FAIL'), f'{name:28}', str(detail)[:400], flush=True)


def _ends(m, t):
    """Names of the two ends of transition t (state names, link:<target>, or the node kind)."""
    def nm(n):
        """Name of node `n` for messages."""
        n = m.node(n)
        return getattr(n, 'name', None) or (f'link:{n.target}' if hasattr(n, 'target') else type(n).__name__.lower())
    return nm(t.src), nm(t.dst)


def edits_tx(v, o) -> set[str]:
    """uart_tx: the edits of the first HDS session (see the module docstring). Returns the
    state names the edits touched (left out of "nothing else changed")."""
    m, om = v.machines[0], o.machines[0]
    names = {s.name: s for s in m.states}
    by = {_ends(m, t): t for t in m.transitions}
    check('state renamed', 'START_H' in names and 'START' not in names, sorted(names))
    t = by.get(('START_H', 'DATA'))
    check('condition changed', t is not None and t.cond.strip() == 'baud_tick & tx_start', t and t.cond)
    s = names.get('START_H')
    check('state actions changed', s is not None and s.in_actions.split() == "tx = 1'b0; tx_busy = 1'b1;".split(),
          s and repr(s.in_actions))
    ostop = next(x for x in om.states if x.name == 'STOP')
    check('state moved', 'STOP' in names and abs(names['STOP'].x - ostop.x) > 5, (ostop.x, names.get('STOP') and names['STOP'].x))
    t = by.get(('s0', 'IDLE'))
    check('state + transition added', 's0' in names and t is not None and t.cond.strip() == 'tx_start'
          and t.actions.strip() == "tx_busy = 1'b0;", t and (t.cond, t.actions))
    h = v.signal('h_in')
    check('port added', h is not None and h.mode == 'input' and not h.bounds, h)
    return {'START', 'STOP'}


def edits_gc(v, o) -> set[str]:
    """gc_control_fsm, edited in HDS's window: ST_STOP renamed ST_STOP_H; its condition to the
    CASE junction "user_cmd_valid & reg_pom_dfien &" + a new line + "postponing"; a line
    "user_cmd_wait_done = 1'b0;" added to the actions of ST_STOP_H -> link ST_DRAIN; the CASE
    expression "user_cmd_opcode[USER_CMD_WIDTH-1:0]"; input port h_gc_in [15:0] added."""
    m = v.machines[0]
    names = {s.name: s for s in m.states}
    check('state renamed', 'ST_STOP_H' in names and 'ST_STOP' not in names, sorted(names)[:30])
    outs = [t for t in m.transitions if _ends(m, t)[0] == 'ST_STOP_H']
    t = next((t for t in outs if _ends(m, t)[1] == 'junction'), None)
    check('multi-line condition', t is not None and t.cond.split() == 'user_cmd_valid & reg_pom_dfien & postponing'.split()
          and '\n' in t.cond, t and repr(t.cond))
    t = next((t for t in outs if _ends(m, t)[1] == 'link:ST_DRAIN'), None)
    check('transition actions changed', t is not None and t.actions.strip().endswith("user_cmd_wait_done = 1'b0;"),
          t and repr(t.actions[-80:]))
    # gc has several CASE junctions on user_cmd_opcode: the one edited is the one with the new text
    j = next((j for j in m.junctions if j.kind == 'case' and '[USER_CMD_WIDTH-1:0]' in j.expr), None)
    check('CASE expression changed', j is not None and j.expr.strip() == 'user_cmd_opcode[USER_CMD_WIDTH-1:0]',
          j and j.expr)
    links = sorted(lk.target for lk in m.links if 'ST_STOP' in lk.target)
    check('links to the renamed state', True, f'link targets now: {links}')
    h = v.signal('h_gc_in')
    check('port added', h is not None and h.mode == 'input' and h.bounds == '[15:0]', h)
    return {'ST_STOP'}


CASES = {'tx': edits_tx, 'gc': edits_gc}


def main() -> int:
    """Run the checks of one case (see the module docstring) on the diagram HDS saved. Returns
    the exit code.
    """
    case, saved_dir, orig_sm = sys.argv[1], sys.argv[2], sys.argv[3]
    app = QApplication.instance() or QApplication(sys.argv[:1])  # noqa: F841
    from gui.main_window import MainWindow
    from hds.export_sm import export_sm
    from hds.import_sm import import_sm
    from project.generate import generate_text

    # a copy of what HDS saved, in a batch project of its own (HDS's window keeps its locks)
    root = os.path.join(WORK, f'h2d_check_{case}')
    U, D = f'{case}_hds', f'{case}_dol'
    hdp = make_project(root, {U: saved_dir, D: saved_dir})
    path = os.path.join(root, LIB, 'hds', U, 'fsm.sm')
    v, o = import_sm(path, library=LIB, unit=U), import_sm(orig_sm)
    touched = CASES[case](v, o)
    # the rest as it was
    a, b = snap(o), snap(v)
    rest = []
    for key in ('texts', 'machine', 'hidden'):
        if a[key] != b[key]:
            rest.append(key)
    keep = {x for x in a['states'] if x[0] not in touched}
    if not keep <= set(b['states']):
        rest.append('states: ' + str(sorted(keep - set(b['states']))[:3]))
    if {x for x in a['signals']} - set(b['signals']):
        rest.append('signals: ' + str(sorted(set(a['signals']) - set(b['signals']))[:3]))
    check('nothing else changed', not rest, rest)
    ports = sorted((x.name, x.mode) for x in v.signals if x.mode in ('input', 'output', 'inout'))
    sp = symbol_ports(os.path.join(root, LIB, 'hds', U, 'symbol.sb'))
    check('symbol ports', sp == ports, f'only diagram {sorted(set(ports) - set(sp))}, only symbol {sorted(set(sp) - set(ports))}')

    # HDL Studio: open in the editor, save without an edit; then make one edit and save
    dpath = os.path.join(root, LIB, 'hds', D, 'fsm.sm')
    before = open(dpath, 'rb').read()
    win = MainWindow()
    win.open_path(dpath)
    win.show()
    QTest.qWait(200)
    warn = export_sm(win.view, dpath, dpath, win.scene.hds_geometry)
    check('dolphin save unchanged', open(dpath, 'rb').read() == before and not warn, warn)
    target = win.machine.states[-1]                 # a further edit made in HDL Studio
    target.in_actions = (target.in_actions.rstrip() + '\n' if target.in_actions.strip() else '') + '// dolphin'
    win.scene.load(win.view, win.machine)
    warn = export_sm(win.view, dpath, dpath, win.scene.hds_geometry)
    win.dirty = False
    win.close()
    check('dolphin edit saved', not warn and import_sm(dpath).machines[0].state_by_name(target.name).in_actions.strip()
          .endswith('// dolphin'), warn)

    # HDS batch: generate both; integrity of HDL Studio's edit
    cmds = []
    for unit in (U, D):
        cmds += [f'set d_{unit} [::HdsApi::openGraphicalView {LIB} {unit} fsm.sm]',
                 f'[$d_{unit} model] checkDataIntegrity', f'::HdsApi::runGenerate {LIB} {unit} fsm.sm']
    log, res = run_tcl(hdp, cmds)
    r = {c: (ok, x) for ok, c, x in res}
    for unit in (U, D):
        ok, x = r.get(f'[$d_{unit} model] checkDataIntegrity', (False, 'not run'))
        check(f'hds integrity {unit}', ok and x.strip() == '1', x)
        gen = os.path.join(root, LIB, 'hdl', f'{unit}_fsm.v')
        if not os.path.exists(gen) or os.path.getsize(gen) == 0:
            check(f'same HDL {unit}', False, 'HDS wrote no HDL: ' + ' | '.join(
                l for l in log.splitlines() if 'rror' in l and 'include file' not in l)[:300])
            continue
        mine, _ = generate_text(import_sm(os.path.join(root, LIB, 'hds', unit, 'fsm.sm'), library=LIB, unit=unit))
        x, y = hdl_from_mark(open(gen, encoding='utf-8').read(), False), hdl_from_mark(mine, False)
        diff = list(difflib.unified_diff(x.split('\n'), y.split('\n'), 'HDS', 'HDL Studio', lineterm='', n=2))
        out = os.path.join(HERE, 'results', f'h2d_{unit}.diff')
        os.makedirs(os.path.dirname(out), exist_ok=True)
        if diff:
            open(out, 'w', encoding='utf-8', newline='\n').write('\n'.join(diff) + '\n')
        check(f'same HDL {unit}', not diff, f'{len(diff)} diff lines: {out}' if diff else '')
    print(f'{sum(results)}/{len(results)} passed')
    return 0 if all(results) else 1


if __name__ == '__main__':
    sys.exit(main())
