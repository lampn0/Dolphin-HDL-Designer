"""Read and write back every HDS graphics file (.sm, .bd, .sb) under the given folders and check
that the text written is byte for byte the file read (hds.sexpr parse / write).

    python tests/hds_compare/roundtrip_files.py [folder ...]     (default: the HDS projects in D:/workspace and examples/uart_hds)

The files are only read. Prints one line per file that differs (first differing line).
"""
import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'src'))
from hds.sexpr import parse, write  # noqa: E402

EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'examples')
folders = sys.argv[1:] or ['D:/workspace/src', os.path.join(EXAMPLES, 'uart_hds'), 'D:/workspace/hds_reference']
same = diff = 0
for folder in folders:
    for ext in ('sm', 'bd', 'sb'):
        for path in sorted(glob.glob(os.path.join(folder, '**', f'*.{ext}'), recursive=True)):
            with open(path, 'rb') as f:
                raw = f.read().decode('utf-8', 'replace')
            out = write(parse(raw))
            if out == raw:
                same += 1
                continue
            diff += 1
            a, b = raw.splitlines(), out.splitlines()
            k = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y), min(len(a), len(b)))
            print(f'DIFF {path}: line {k + 1}: {a[k] if k < len(a) else "<end>"!r} -> '
                  f'{b[k] if k < len(b) else "<end>"!r}')
print(f'identical: {same}, different: {diff}')
sys.exit(1 if diff else 0)
