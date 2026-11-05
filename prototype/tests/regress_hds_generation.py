"""Generation regression against HDS: for every graphical view (block diagram, state machine) of a
real HDS project, generate the HDL in memory and compare it with the HDL that HDS generated (the
unit's text view), from the first line after the header ("// Internal Declarations" for a block
diagram, "// State encoding" for a state machine). Read only: nothing is written.

    python tests/regress_hds_generation.py [project.hdp]      # default D:/workspace/src/dti_hbm.hdp

Exit code 1 when a view fails to load or generate, or when the generated body differs from HDS.
"""
from __future__ import annotations

import difflib
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))

from dhds.project.generate import generate_text, load_view  # noqa: E402
from dhds.project.project import open_project  # noqa: E402

HDP = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.environ.get('DHDS_TEST_SRC', r'D:\workspace\src'),
                                                         'dti_hbm.hdp')


def main() -> int:
    t0 = time.time()
    p = open_project(HDP)
    print('open', round(time.time() - t0, 2), 's; libs', len(p.libraries), 'errors', len(p.errors))
    for e in p.errors[:6]:
        print('  ERR', e)
    stats = {'match': 0, 'body_diff': 0, 'no_golden': 0, 'fail': 0}
    details = []
    t0 = time.time()
    for lib in p.libraries:
        if lib.type == 'regular':
            lib.scan(p.cache)
    print('scan', round(time.time() - t0, 2), 's; units', sum(len(l.units) for l in p.libraries))
    for lib in p.libraries:
        for du in lib.units.values():
            g = du.graphic_view()
            if g is None:
                continue
            try:
                m = load_view(lib, du, g)
                text, _ = generate_text(m)
            except Exception as e:                  # a view that cannot be read or generated
                stats['fail'] += 1
                details.append((lib.name, du.name, g.kind, 'FAIL ' + repr(e)[:150]))
                continue
            tv = du.text_view()
            if tv is None:
                stats['no_golden'] += 1             # no HDS-generated HDL to compare with
                continue
            gold = open(tv.path, encoding='utf-8', errors='replace').read().replace('\r\n', '\n')
            # the header (dates, user) differs by nature: compare from the first body marker
            cut = '// State encoding' if g.kind == 'fsm' else '// Internal Declarations'
            if cut not in gold or cut not in text:
                stats['body_diff'] += 1
                details.append((lib.name, du.name, g.kind, f'no "{cut}" marker'))
                continue
            a, b = gold[gold.index(cut):], text[text.index(cut):]
            if a == b:
                stats['match'] += 1
                continue
            stats['body_diff'] += 1
            d = [l for l in difflib.unified_diff(a.split('\n'), b.split('\n'), lineterm='', n=0)
                 if l[:1] in '+-' and l[:3] not in ('+++', '---')]
            details.append((lib.name, du.name, g.kind, f'{len(d)} lines differ; first: ' + ' | '.join(d[:4])[:300]))
    print(stats)
    for d in details:
        print(' ', d)
    return 1 if stats['fail'] or stats['body_diff'] else 0


if __name__ == '__main__':
    sys.exit(main())
