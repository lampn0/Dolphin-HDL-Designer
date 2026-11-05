"""Survey: in what order does HDS write the instances of a block diagram?

For every struct.bd of the reference with an HDS output, lists the instances in the order HDS
wrote them with their library, whether they sit in a frame, and flags the diagrams where the
order is not alphabetical.
"""
import glob
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(os.path.dirname(HERE)))
from dhds.hds.import_bd import import_bd  # noqa: E402

REF = os.path.join(HERE, 'reference', 'src')
for path in sorted(glob.glob(os.path.join(REF, '**', 'hds', '*', 'struct.bd'), recursive=True)):
    unit = os.path.basename(os.path.dirname(path))
    vs = glob.glob(os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(path))), 'hdl', unit + '.v'))
    if not vs:
        continue
    text = open(vs[0], encoding='utf-8', errors='replace').read()
    hds = re.findall(r'^\S[^\n]*?\b(\w+)\s*(?:\[[^\n]*\])?\( $', text, re.M)
    bd = import_bd(path)
    by = {i.name: i for i in bd.instances}
    names = [h for h in hds if h in by]
    if names == sorted(names):
        continue
    print(f'{unit} (library {bd.library})')
    for n in names:
        i = by[n]
        print(f'    {n:32} {i.library:24} {"frame" if bd.frame_of(i) else ""}')
