"""Block diagrams (struct.bd) in both tools.

    python tests/hds_sync/sync_bd.py read [library ...]      # HDS -> HDL Studio: reading HDS's files

read: every block diagram of a library of the real project (default: protocol_controller), on
a copy in tests/hds_sync/work/bd_read: HDS 2021.1 (batch) opens each struct.bd, checks its
integrity and generates its HDL; HDL Studio reads the same struct.bd and generates. The HDL is
compared from "// Internal Declarations" on, exactly: HDL Studio generates with this HDS's Verilog
style options (LOCAL_STYLE: tab width 3, positional parameter mapping).
In the copy, the HDL of units with a graphical view is moved aside (HDS does not generate over
HDL it takes for source) and HDL Studio's own .json views are removed (HDL Studio must read the HDS
file). Diffs: results/bd_read_<unit>.diff, report results/bd_read.md.
"""
from __future__ import annotations

import difflib
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'src'))
sys.path.insert(0, HERE)
from hds_batch import WORK, run_tcl  # noqa: E402

SRC = r'D:\workspace\src'
RESULTS = os.path.join(HERE, 'results')
MARK = '// Internal Declarations'
GRAPHIC = ('.bd', '.sm', '.fc', '.tt', '.asm')


def from_mark(text: str) -> str:
    """HDL text from the comparison mark ("// Internal Declarations") on, with LF line endings."""
    text = text.replace('\r\n', '\n')
    return text[text.index(MARK):] if MARK in text else text


def make_copy(root: str, libs: list[str]) -> str:
    """The libraries (hds + hdl) and the include folder of the real project, in a project of
    their own; generated HDL and HDL Studio's json views out of the way."""
    if os.path.isdir(root):
        shutil.rmtree(root)
    os.makedirs(root)
    shutil.copytree(os.path.join(SRC, 'include'), os.path.join(root, 'include'))
    lines = {'hdl': [], 'hds': [], 'library_type': [], 'includes_search_path': []}
    for lib in libs:
        dst = os.path.join(root, 'libs', lib)
        shutil.copytree(os.path.join(SRC, 'libs', lib), dst,
                        ignore=shutil.ignore_patterns('*.lck', '.xrf', '.hdlsidedata', '*.cache.dat', '*.json'))
        hdl, hds = os.path.join(dst, 'hdl'), os.path.join(dst, 'hds')
        for unit in os.listdir(hds):
            u = os.path.join(hds, unit)
            if os.path.isdir(u) and any(f.endswith(GRAPHIC) for f in os.listdir(u)):
                for f in os.listdir(hdl):
                    if f.split('.')[0] == unit or f.startswith(unit + '_'):
                        os.makedirs(os.path.join(root, 'aside', lib), exist_ok=True)
                        shutil.move(os.path.join(hdl, f), os.path.join(root, 'aside', lib, f))
        lines['hdl'].append(f'{lib} = $HDS_PROJECT_DIR/libs/{lib}/hdl')
        lines['hds'].append(f'{lib} = $HDS_PROJECT_DIR/libs/{lib}/hds')
        lines['library_type'].append(f'{lib} = regular')
        lines['includes_search_path'].append(f'{lib} = $HDS_PROJECT_DIR/include')
    hdp = os.path.join(root, 'sync_bd.hdp')
    with open(hdp, 'w', newline='\n') as f:
        for sec in ('hdl', 'hds'):
            f.write(f'[{sec}]\n' + '\n'.join(lines[sec]) + '\n')
        f.write(f'[hds_settings]\ndefault_library = {libs[0]}\nversion = 3\n')
        for sec in ('includes_search_path', 'library_type'):
            f.write(f'[{sec}]\n' + '\n'.join(lines[sec]) + '\n')
        f.write('[shared]\nothers = $HDS_TEAM_HOME/shared.hdp\n')
    return hdp


# HDS 2021.1's Options > Verilog > Style on this machine (read from its dialog): HDL Studio
# generates with the same, so the HDL is compared exactly, indentation included
LOCAL_STYLE = {'tab_width': 3, 'param_mapping': 'Positional', 'implicit_event': False}


def all_libs() -> list[str]:
    """The libraries of the real project that have a graphics (hds) folder."""
    return sorted(d for d in os.listdir(os.path.join(SRC, 'libs')) if os.path.isdir(os.path.join(SRC, 'libs', d, 'hds')))


def read(libs: list[str]) -> int:
    """HDS -> HDL Studio: batch HDS generates every block diagram of `libs`, HDL Studio generates the
    same files with the same style; compare and write results/bd_read.md. Returns the exit code.
    """
    from codegen.common import set_style
    from project.generate import generate_text, load_view
    from project.project import open_project
    set_style(**LOCAL_STYLE)
    root = os.path.join(WORK, 'bd_read')
    hdp = make_copy(root, all_libs())     # every library: components come from all of them
    units = []
    for lib in libs:
        hds = os.path.join(root, 'libs', lib, 'hds')
        units += [(lib, u) for u in sorted(os.listdir(hds)) if os.path.exists(os.path.join(hds, u, 'struct.bd'))]
    cmds = []
    for lib, u in units:
        cmds += [f'set d_{u} [::HdsApi::openGraphicalView {lib} {u} struct.bd]', f'[$d_{u} model] checkDataIntegrity',
                 f'::HdsApi::runGenerate {lib} {u} struct.bd']
    log, res = run_tcl(hdp, cmds, timeout=1800)
    open(os.path.join(root, 'hds.log'), 'w', encoding='utf-8').write(log)
    r = {c: (ok, x) for ok, c, x in res}
    import re
    # "Cannot read document from file ...": the ones written by a newer HDS than this one
    unreadable = set()
    for path in re.findall(r'Cannot read document from file "([^"]+)"', log):
        head = open(path, encoding='utf-8', errors='replace').read(2000) if os.path.exists(path) else ''
        m = re.search(r'appVersion "(\d{4})', head)
        if m and int(m.group(1)) > 2021:
            unreadable.add(os.path.relpath(path, os.path.join(root, 'libs')).replace('\\', '/'))
    project = open_project(hdp)
    rows = []
    os.makedirs(RESULTS, exist_ok=True)
    for lib, u in units:
        ok, x = r.get(f'[$d_{u} model] checkDataIntegrity', (False, 'not run'))
        integ = ok and x.strip() == '1'
        hdl = os.path.join(root, 'libs', lib, 'hdl')
        gen = [os.path.join(hdl, f) for f in os.listdir(hdl) if f in (f'{u}_struct.v', f'{u}.v', f'{u}_struct.sv')]
        L = next(x for x in project.libraries if x.name == lib)
        L.scan(project.cache)
        du = L.units.get(u)
        try:
            text, _ = generate_text(load_view(L, du, du.graphic_view()))
        except Exception as e:
            rows.append((u, integ, f'DOLPHIN ERROR {e!r}'[:200]))
            continue
        if not gen or os.path.getsize(gen[0]) == 0:
            # files saved by a newer HDS (the server's 2024.2) are not readable by 2021.1: not
            # a difference between HDL Studio and HDS
            if unreadable:
                rows.append((u, integ, 'SKIP: HDS 2021.1 cannot read files saved by HDS 2024.2 ('
                             + ', '.join(sorted(unreadable)) + ')'))
            else:
                rows.append((u, integ, 'HDS wrote no HDL'))
            continue
        a, b = from_mark(open(gen[0], encoding='utf-8', errors='replace').read()), from_mark(text)
        diff = list(difflib.unified_diff(a.split('\n'), b.split('\n'), f'HDS {u}', f'HDL Studio {u}', lineterm='', n=2))
        if diff:
            open(os.path.join(RESULTS, f'bd_read_{u}.diff'), 'w', encoding='utf-8', newline='\n').write('\n'.join(diff) + '\n')
        n = sum(1 for l in diff if l[:1] in '+-' and l[:3] not in ('+++', '---'))
        rows.append((u, integ, 'MATCH' if not diff else f'{n} lines differ'))
    with open(os.path.join(RESULTS, 'bd_read.md'), 'w', encoding='utf-8', newline='\n') as f:
        f.write('# HDS -> HDL Studio: block diagrams read from struct.bd\n\n| Unit | HDS integrity | HDL |\n|---|---|---|\n')
        for u, integ, res_ in rows:
            f.write(f'| {u} | {"1" if integ else "FAIL"} | {res_} |\n')
    for u, integ, res_ in rows:
        print(('PASS' if integ and res_ == 'MATCH' else 'FAIL'), f'{u:28} integrity {"1" if integ else "0"}  {res_}')
    good = sum(1 for _, i, x in rows if i and x == 'MATCH')
    print(f'{good}/{len(rows)} match')
    return 0 if good == len(rows) else 1


# HDS -> HDL Studio: edits made by HDS itself, with its Block Diagram Tcl API (BDAPI, HDS Tcl API
# reference, "Block Diagram Commands"; batch mode: openBDBatch ... saveBDBatch closeBDBatch).
# BDAPI only adds, connects and sets: there is no command to move, rename or delete.
H2D_EDITS = {
    ('protocol_controller', 'bc_auto_refresh'): [
        '::BDAPI::setCptGenParam dti_bicnt_dwn_t_rfc_b WIDTH MC_COUNTER_WIDTH',
        '::BDAPI::addCmpInst h_cnt dti_lib dti_bicnt_dwn',
        '::BDAPI::setCptGenParam h_cnt WIDTH MC_W_COUNTER_WIDTH',
        '::BDAPI::addNet h_done "" wire',
        '::BDAPI::addNet h_flag "" wire',
        '::BDAPI::addNet h_bus "\\[3:0\\]" wire',
        '::BDAPI::connectCmpPortToNet h_cnt clk clk',
        '::BDAPI::connectCmpPortToNet h_cnt reset_n reset_n',
        '::BDAPI::connectCmpPortToNet h_cnt load_en t_rfcsb_load',
        '::BDAPI::connectCmpPortToNet h_cnt count_en t_rfcsb_cnt_en',
        '::BDAPI::connectCmpPortToNet h_cnt count_num reg_dfi_freq_ratio',
        '::BDAPI::connectCmpPortToNet h_cnt count_to reg_t_rfcsb',
        '::BDAPI::connectCmpPortToNet h_cnt done h_done',
        '::BDAPI::addPortIO output h_done',
        '::BDAPI::addPortIO output h_flag',
        '::BDAPI::addPortIO output h_bus',
        '::BDAPI::addGenParam H_PARAM 4 "added by HDS batch"',
        '::BDAPI::createEmbeddedBlock "assign h_flag = h_done;\\nassign h_bus = 4\'d0;"',
    ],
}


def h2d() -> int:
    """For each diagram of H2D_EDITS, on a fresh copy: HDS applies the edits and saves
    (struct.bd and symbol.sb), checks the file's integrity, generates; HDL Studio reads the file:
    the edits are there, and its HDL is HDS's, exactly."""
    from codegen.common import set_style
    from hds.import_bd import import_bd
    from project.generate import generate_text
    set_style(**LOCAL_STYLE)
    root = os.path.join(WORK, 'bd_h2d')
    hdp = make_copy(root, all_libs())
    cmds = []
    for (lib, u), edits in H2D_EDITS.items():
        cmds += [f'::BDAPI::openBDBatch {lib} {u}'] + edits + ['::BDAPI::saveBDBatch', '::BDAPI::closeBDBatch',
                                                               f'set d_{u} [::HdsApi::openGraphicalView {lib} {u} struct.bd]',
                                                               f'[$d_{u} model] checkDataIntegrity',
                                                               f'::HdsApi::runGenerate {lib} {u} struct.bd']
    log, res = run_tcl(hdp, cmds)
    open(os.path.join(root, 'hds.log'), 'w', encoding='utf-8').write(log)
    bad = 0

    def check(name, ok, detail=''):
        """Count and print one check (PASS / FAIL, its name and a detail)."""
        nonlocal bad
        bad += not ok
        print(('PASS' if ok else 'FAIL'), f'{name:36}', str(detail)[:300])
    for ok, c, r in res:
        if not ok:
            check(f'HDS: {c[:40]}', False, r)
    for (lib, u), edits in H2D_EDITS.items():
        r = {c: x for ok, c, x in res if ok}
        check(f'{u}: HDS integrity', r.get(f'[$d_{u} model] checkDataIntegrity', '').strip() == '1')
        bd = import_bd(os.path.join(root, 'libs', lib, 'hds', u, 'struct.bd'), lib, u)
        inst = {i.name: i for i in bd.instances}
        for e in edits:
            w = e.split()
            if w[0].endswith('setCptGenParam'):
                i = inst.get(w[1])
                check(f'{u}: {w[1]}.{w[2]} = {w[3]}', i is not None and any(
                    p.name == w[2] and p.value.strip() == w[3] for p in i.params), i and i.params)
            elif w[0].endswith('connectCmpPortToNet'):
                i = inst.get(w[1])
                check(f'{u}: {w[1]}.{w[2]} -> {w[3]}', i is not None and any(
                    p.name == w[2] and p.net == w[3] for p in i.pins))
            elif w[0].endswith('addPortIO'):
                s = bd.signal(w[2]) if hasattr(bd, 'signal') else next((x for x in bd.signals if x.name == w[2]), None)
                check(f'{u}: port {w[2]} {w[1]}', s is not None and s.mode == w[1], s and s.mode)
            elif w[0].endswith('addGenParam'):
                check(f'{u}: parameter {w[1]}', any(p.name == w[1] and p.value == w[2] for p in bd.parameters))
            elif w[0].endswith('createEmbeddedBlock'):
                check(f'{u}: embedded block', any('assign h_flag = h_done;' in eb.text for eb in bd.embedded))
        text, warn = generate_text(bd)
        hdl = os.path.join(root, 'libs', lib, 'hdl', f'{u}_struct.v')
        hds = open(hdl, encoding='utf-8', errors='replace').read() if os.path.exists(hdl) else ''
        diff = list(difflib.unified_diff(from_mark(hds).split('\n'), from_mark(text).split('\n'), 'HDS', 'HDL Studio',
                                         lineterm='', n=2))
        if diff:
            os.makedirs(RESULTS, exist_ok=True)
            open(os.path.join(RESULTS, f'bd_h2d_{u}.diff'), 'w', encoding='utf-8', newline='\n').write('\n'.join(diff))
        check(f'{u}: same HDL as HDS', bool(hds) and not diff, f'results/bd_h2d_{u}.diff' if diff else '')
    print('all passed' if not bad else f'{bad} failed')
    return 1 if bad else 0


if __name__ == '__main__':
    args = sys.argv[1:]
    if not args or args[0] == 'read':
        sys.exit(read(args[1:] or ['protocol_controller']))
    if args[0] == 'h2d':
        sys.exit(h2d())
    sys.exit(f'unknown phase {args[0]!r}')
