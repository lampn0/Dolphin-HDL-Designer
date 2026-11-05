"""Check writing state diagrams back to HDS .sm files (hds.export_sm).

    python tests/hds_compare/sm_write.py [root ...]

1. Every fsm .sm under the roots, written back without changes, must be byte for byte the
   file read.
2. A diagram (gc_control_fsm, else the first found) is edited in the model (a state moved
   and renamed, a condition and actions changed, a box moved, a transition deleted), written,
   and read again: the edits must be there and nothing else changed.
Outputs go to tests/hds_compare/out. The source files are only read.
"""
import copy
import glob
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), 'src'))
from hds.export_sm import export_sm  # noqa: E402
from hds.import_sm import import_sm  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'out')
roots = sys.argv[1:] or ['D:/workspace/src', 'D:/workspace/hds_reference']
os.makedirs(OUT, exist_ok=True)
files = sorted(f for r in roots for f in glob.glob(os.path.join(r, '**', '*.sm'), recursive=True))
bad = 0
for f in files:
    out = os.path.join(OUT, 'same.sm')
    try:
        warn = export_sm(import_sm(f), f, out)
    except Exception as e:                      # noqa: BLE001 - report and go on
        print('ERROR', f, e)
        bad += 1
        continue
    if open(f, 'rb').read() != open(out, 'rb').read() or warn:
        print('DIFF', f, warn)
        bad += 1
print(f'unchanged: {len(files) - bad}/{len(files)} identical')

# -- edits ----------------------------------------------------------------------------------
src = next((f for f in files if 'gc_control_fsm' in f), files[0])
view = import_sm(src)
before = copy.deepcopy(view)
m = view.machines[0]
st = next(s for s in m.states if s.actions_x is not None)
st.x += 20
st.y += 10
st.actions_x += 20
st.actions_y += 10
st.name = st.name + '_X'
t = next(t for t in m.transitions if t.label_x is not None and t.src != st.id and t.dst != st.id and t.cond)
t.cond = 'new_cond & other'
t.actions = 'a <= 1;\nb <= 0;'
t.label_x += 8
gone = next(x for x in m.transitions if x is not t and x.src != st.id and x.dst != st.id)
m.transitions.remove(gone)
dst = os.path.join(OUT, 'edited.sm')
print('warnings:', export_sm(view, src, dst))
again = import_sm(dst)
a = again.machines[0]
s2 = next(s for s in a.states if s.id == st.id)
t2 = next(x for x in a.transitions if x.id == t.id)
checks = [
    ('state moved', abs(s2.x - st.x) < 0.02 and abs(s2.y - st.y) < 0.02),
    ('state renamed', s2.name == st.name),
    ('actions moved', abs(s2.actions_x - st.actions_x) < 0.02),
    ('condition', t2.cond == t.cond),
    ('actions', t2.actions == t.actions),
    ('box moved', abs(t2.label_x - t.label_x) < 0.02),
    ('transition deleted', all(x.id != gone.id for x in a.transitions)),
    ('others kept', len(a.transitions) == len(before.machines[0].transitions) - 1),
]
for name, ok in checks:
    print(('ok  ' if ok else 'FAIL'), name)
    bad += not ok

# -- new objects ----------------------------------------------------------------------------
from model import Junction, Link, State, Transition  # noqa: E402

view = import_sm(src)
m = view.machines[0]
base = max(s.x for s in m.states) + 200          # right of everything
# (each added before the next id is asked for, as the editor does: new_id looks at the model)
ns = State(id=m.new_id('s'), name='ST_NEW', x=base, y=0, entry_actions='a <= 1;', in_actions='b = 2;')
m.states.append(ns)
ns2 = State(id=m.new_id('s'), name='ST_NEW2', x=base + 200, y=0, in_actions='c = 3;')
m.states.append(ns2)
nj = Junction(id=m.new_id('j'), kind='case', expr='sel', x=base + 100, y=100)
m.junctions.append(nj)
nl = Link(id=m.new_id('l'), target=m.states[0].name, x=base + 100, y=200)
m.links.append(nl)
nts = []
for src_, dst_, cond_, acts_ in ((ns.id, ns2.id, 'go & ready', 'x <= 0;'), (ns.id, nj.id, 'other', ''),
                                 (nj.id, nl.id, "2'b01", ''), (m.states[0].id, ns.id, 'enter_new', '')):
    nts.append(Transition(id=m.new_id('t'), src=src_, dst=dst_, cond=cond_, actions=acts_))
    m.transitions.append(nts[-1])
dst = os.path.join(OUT, 'added.sm')
print('warnings:', export_sm(view, src, dst))
again = import_sm(dst).machines[0]
names = {s.name: s for s in again.states}
checks = [
    ('new states read back', 'ST_NEW' in names and 'ST_NEW2' in names),
    ('new state where it was put', 'ST_NEW' in names and abs(names['ST_NEW'].x - base) < 0.1),
    ('new state actions', 'ST_NEW' in names and names['ST_NEW'].entry_actions == 'a <= 1;'
     and names['ST_NEW'].in_actions == 'b = 2;'),
    ('new junction', any(j.kind == 'case' and j.expr == 'sel' for j in again.junctions)),
    ('new link', any(abs(l.x - nl.x) < 0.1 and l.target == nl.target for l in again.links)),
    ('new transitions', all(any(x.cond == t.cond for x in again.transitions) for t in nts)),
    ('new transition actions', any(x.cond == 'go & ready' and x.actions == 'x <= 0;' for x in again.transitions)),
    ('ids renamed to labels', all(x.id.startswith('n') for x in (ns, ns2, nj, nl, *nts))),
    ('in the state order', [s.name for s in again.states][-2:] == ['ST_NEW', 'ST_NEW2']),
]
# saving the same view again changes nothing more
dst2 = os.path.join(OUT, 'added2.sm')
export_sm(view, dst, dst2)
checks.append(('second save identical', open(dst, 'rb').read() == open(dst2, 'rb').read()))
for name, ok in checks:
    print(('ok  ' if ok else 'FAIL'), name)
    bad += not ok
sys.exit(1 if bad else 0)
