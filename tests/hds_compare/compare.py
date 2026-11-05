"""Compare the HDL Dolphin HDS generates with the HDL HDS generated from the same diagrams
(tests/hds_compare/reference/, made by hds_reference.py).

    python tests/hds_compare/compare.py            # all graphical views HDS generated
    python tests/hds_compare/compare.py fsm        # only state machines (or: bd)
    python tests/hds_compare/compare.py fsm gc_zqlat_fsm    # only units whose name contains this

For every unit with a block diagram or state machine that HDS generated, Dolphin generates in
memory and the two files are compared from the first line after the header ("// Internal
Declarations" for a block diagram, "// State encoding" for a state machine; the header holds
dates and user names). Results:
  results/report.md          one line per view: MATCH, or the number of differing lines
  results/diffs/<lib>.<unit>.diff   a unified diff (HDS = "-", Dolphin = "+") for each mismatch
Exit code 1 when a view differs or fails.
"""
from __future__ import annotations

import collections
import difflib
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(HERE)), 'src'))

from project.generate import generate_text, load_view  # noqa: E402
from project.project import open_project  # noqa: E402

REF = os.path.join(HERE, 'reference')
RESULTS = os.path.join(HERE, 'results')
MARK = {'fsm': '// State encoding', 'bd': '// Internal Declarations'}


def main() -> int:
    """Generate every view (or those named on the command line) and compare it with the HDS
    reference; writes results/report.md and the diffs. Returns the exit code.
    """
    args = sys.argv[1:]
    kinds = [a for a in args if a in MARK] or list(MARK)
    names = [a for a in args if a not in MARK]
    listing = os.path.join(REF, 'hds_generated.txt')
    if not os.path.exists(listing):
        raise SystemExit('no HDS reference yet: run  python tests/hds_compare/hds_reference.py')
    fresh = {os.path.normcase(os.path.normpath(os.path.join(REF, l.strip())))
             for l in open(listing) if l.strip()}
    hdp = next(os.path.join(REF, 'src', f) for f in os.listdir(os.path.join(REF, 'src')) if f.endswith('.hdp'))
    project = open_project(hdp)

    diffs_dir = os.path.join(RESULTS, 'diffs')
    os.makedirs(diffs_dir, exist_ok=True)
    for old in os.listdir(diffs_dir):           # the diffs of the previous run
        os.remove(os.path.join(diffs_dir, old))
    counts, rows = collections.Counter(), []
    for lib in project.libraries:
        if lib.type != 'regular':
            continue
        lib.scan(project.cache)
        for du in lib.units.values():
            g = du.graphic_view()
            if g is None or g.kind not in kinds or (names and not any(n in du.name for n in names)):
                continue
            # the file HDS wrote for this unit, if it generated it
            hds_file = next((f for f in (os.path.join(lib.main_hdl_dir, du.name + e) for e in ('.v', '.sv'))
                             if os.path.normcase(os.path.normpath(f)) in fresh), None)
            if hds_file is None:
                continue
            key = f'{lib.name}.{du.name}'
            try:
                text, _ = generate_text(load_view(lib, du, g))
            except Exception as e:                   # Dolphin cannot read or generate the view
                counts['dolphin error'] += 1
                rows.append((key, g.kind, 'DOLPHIN ERROR ' + repr(e)[:200]))
                continue
            hds = open(hds_file, encoding='utf-8', errors='replace').read().replace('\r\n', '\n')
            mark = MARK[g.kind]
            if mark not in hds or mark not in text:
                counts['no marker'] += 1
                rows.append((key, g.kind, f'no "{mark}" in {"HDS" if mark not in hds else "Dolphin"} output'))
                continue
            a, b = hds[hds.index(mark):], text[text.index(mark):]
            if a == b:
                counts['match'] += 1
                rows.append((key, g.kind, 'MATCH'))
                continue
            diff = list(difflib.unified_diff(a.split('\n'), b.split('\n'), f'HDS {key}', f'Dolphin {key}',
                                             lineterm='', n=3))
            changed = sum(1 for l in diff if l[:1] in '+-' and l[:3] not in ('+++', '---'))
            counts['differ'] += 1
            rows.append((key, g.kind, f'{changed} lines differ'))
            with open(os.path.join(diffs_dir, key + '.diff'), 'w', encoding='utf-8', newline='\n') as f:
                f.write('\n'.join(diff) + '\n')

    rows.sort(key=lambda r: (r[2] != 'MATCH', r[1], r[0]))
    summary = ', '.join(f'{k}: {v}' for k, v in sorted(counts.items()))
    with open(os.path.join(RESULTS, 'report.md'), 'w', encoding='utf-8', newline='\n') as f:
        f.write(f'# Dolphin HDS vs HDS generation ({" ".join(kinds)}{" " + " ".join(names) if names else ""})\n\n')
        f.write(f'{summary}\n\n| View | Kind | Result |\n|---|---|---|\n')
        for key, kind, result in rows:
            f.write(f'| {key} | {kind} | {result} |\n')
    print(summary)
    for key, kind, result in rows:
        print(f'  {result[:60]:60} {kind:3} {key}')
    print('report:', os.path.join(RESULTS, 'report.md'))
    return 0 if counts['match'] == len(rows) else 1


if __name__ == '__main__':
    sys.exit(main())
