"""Survey: in what order does HDS write the internal signal declarations of a block diagram?

For every struct.bd of the reference, compares the names under "// Internal signal declarations"
in the HDS output with: alphabetical order, the "o" field of the signal table, and the display
row ("pos") of the table. Prints one line per diagram.
"""
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from dhds.hds.import_sm import _row_positions  # noqa: E402
from dhds.hds.sexpr import parse_file  # noqa: E402

REF = os.path.join(HERE, 'reference', 'src')
for bd in sorted(glob.glob(os.path.join(REF, '**', 'hds', '*', 'struct.bd'), recursive=True)):
    unit = os.path.basename(os.path.dirname(bd))
    vs = glob.glob(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(bd))), 'hdl', unit + '.v'))
    if not vs:
        continue
    text = open(vs[0], encoding='utf-8', errors='replace').read()
    m = re.search(r'// Internal signal declarations\n(.*?)\n\n', text, re.S)
    if not m:
        continue
    hds = [re.search(r'(\w+)\s*(\[[^\]]*\]\s*)?(=.*)?;', l).group(1) for l in m.group(1).split('\n')
           if l.strip() and not l.lstrip().startswith('//') and ';' in l]
    doc = parse_file(bd)
    pos = _row_positions(doc)
    info = {}
    for n in doc.walk():
        if n.type == 'LeafLogPort' and n.get('port').get('m') == 4:
            d = n.get('port').get('decl')
            info[d.get('n')] = (d.get('o') or 0, pos.get(n.label, 1 << 30))
    names = [h for h in hds if h in info]
    kinds = [k for k, key in (('alpha', lambda s: s), ('o', lambda s: info[s][0]), ('pos', lambda s: info[s][1]))
             if sorted(names, key=key) == names]
    print(f'{unit:32} {len(names):4}  {",".join(kinds) or "OTHER"}')
