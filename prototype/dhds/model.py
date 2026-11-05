"""Data model for a state machine view (one design unit view with one or
more concurrent machines). Saved as JSON; graphics positions are kept
next to the logic so the diagram reopens as it was drawn."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from typing import Any

MODES = ('input', 'output', 'inout', 'local')
SCHEMES = ('comb', 'registered', 'clocked', 'none')
CATEGORIES = ('data', 'clock', 'reset', 'enable')
LANGUAGES = ('systemverilog', 'verilog')
STATE_DECLS = ('parameter', 'localparam', 'enum')
ENCODINGS = ('sequential', 'gray', 'onehot', 'johnson', 'manual')
POINT_KINDS = ('reset', 'clock', 'interrupt', 'recovery', 'enable', 'entry', 'exit')


@dataclass
class Signal:
    name: str
    mode: str = 'input'              # MODES
    type: str = 'wire'
    bounds: str = ''                 # e.g. "[7:0]"
    signed: bool = False
    group: str = ''
    category: str = 'data'           # CATEGORIES
    expression: str = ''             # clock/reset/enable expression, e.g. "posedge clk"
    scheme: str = 'none'             # SCHEMES, outputs/locals only
    default: str = ''
    reset: str = ''
    comment: str = ''
    value: str = ''                  # initial value of a net declaration: wire x = <value>;
    array: str = ''                  # unpacked dimension, e.g. [0:3]
    delay: str = ''
    expansion: str = ''              # Verilog net expansion: '' | scalared | vectored
    strength: str = ''               # trireg charge strength: '' | small | medium | large
    @property
    def is_driven(self) -> bool:
        return self.mode in ('output', 'local') and self.scheme != 'none'


@dataclass
class Parameter:
    name: str
    value: str = ''
    type: str = ''
    group: str = ''
    comment: str = ''


@dataclass
class State:
    id: str
    name: str
    x: float = 0.0
    y: float = 0.0
    entry_actions: str = ''          # run on every transition into the state
    in_actions: str = ''             # run every clock cycle while in the state
    exit_actions: str = ''           # run on every transition out of the state
    encoding: str = ''               # manual encoding value
    actions_x: float | None = None   # top-left of the action box on the diagram (None = automatic)
    actions_y: float | None = None
    radius: float | None = None      # circle radius saved by HDS (None = Dolphin's default)
    is_wait: bool = False            # a wait state (HDS: circle in an octagon)
    wait: str = ''                   # its wait text, e.g. "wait 2"
    hier: bool = False               # a hierarchical state (HDS CompositeState): its states are inside
    # geometry read from an HDS file, drawn as it is (scene units, offsets from the action
    # block's top-left): act_size [w, h], tline / bline (y of the lines between the entry,
    # state and exit actions; None = hidden), entry / in / exit [x, y] of each text
    hds: dict = field(default_factory=dict)
    parent: str = ''                 # id of the hierarchical state this one is inside ('' = top level)


@dataclass
class Junction:
    id: str
    kind: str = 'if'                 # 'if' | 'case'
    expr: str = ''                   # case expression
    symbol: str = ''                 # text drawn in the diamond (HDS: "&" when new, "if" ...)
    parent: str = ''                 # id of the hierarchical state it is inside ('' = top level)
    x: float = 0.0
    y: float = 0.0
    # geometry read from an HDS file (scene units, relative to the node's centre): 'shape'
    # [x0, y0, x1, y1] and its texts by key, each [x0, y0, x1, y1, justify, baseline]
    hds: dict = field(default_factory=dict)


@dataclass
class Link:
    id: str
    target: str = ''                 # state name
    x: float = 0.0
    y: float = 0.0
    parent: str = ''                 # id of the hierarchical state it is inside ('' = top level)
    # geometry read from an HDS file (scene units, relative to the node's centre): 'shape'
    # [x0, y0, x1, y1] and its texts by key, each [x0, y0, x1, y1, justify, baseline]
    hds: dict = field(default_factory=dict)


@dataclass
class Point:
    id: str
    kind: str                        # POINT_KINDS
    x: float = 0.0
    y: float = 0.0
    parent: str = ''                 # entry / exit points: the hierarchical state they belong to
    # geometry read from an HDS file (scene units, relative to the node's centre): 'shape'
    # [x0, y0, x1, y1] and its texts by key, each [x0, y0, x1, y1, justify, baseline]
    hds: dict = field(default_factory=dict)


@dataclass
class Transition:
    id: str
    src: str                         # node id
    dst: str                         # node id
    cond: str = ''                   # empty = unconditional / "others"
    actions: str = ''
    priority: int = 1
    points: list[list[float]] = field(default_factory=list)  # bend points between the two nodes
    start_angle: float | None = None  # where the line leaves / enters the node outline (radians)
    end_angle: float | None = None
    label_x: float | None = None      # top-left of the condition/action box (None = automatic)
    label_y: float | None = None
    prio_at: float | None = None      # where the priority number sits, as a fraction of the line length
    # geometry read from an HDS file, drawn as it is (scene units, offsets from the box's
    # top-left): box_size [w, h], cond / acts [x, y] of the texts, line (y of the line between
    # them, None = hidden), prio_shown (the priority circle visible)
    hds: dict = field(default_factory=dict)


@dataclass
class Machine:
    name: str = 'fsm'
    states: list[State] = field(default_factory=list)
    junctions: list[Junction] = field(default_factory=list)
    links: list[Link] = field(default_factory=list)
    points: list[Point] = field(default_factory=list)
    transitions: list[Transition] = field(default_factory=list)
    current_state_name: str = 'current_state'
    next_state_name: str = 'next_state'
    encoding: str = 'sequential'     # ENCODINGS
    state_decl: str = 'parameter'    # STATE_DECLS
    # Legacy generation property "nextStateClocking" (SmGenChar of the state machine): HDS then
    # labels the clocked actions "Transition Actions for internal signals only"
    next_state_clocking: bool = False
    # visible area when HDS last saved the diagram (scene units x0, y0, x1, y1): the editor
    # opens there, as HDS does, when it has no view of its own for the diagram
    view_area: list[float] | None = None

    # -- lookup helpers -------------------------------------------------
    def node(self, node_id: str) -> Any:
        for coll in (self.states, self.junctions, self.links, self.points):
            for n in coll:
                if n.id == node_id:
                    return n
        return None

    def state_by_name(self, name: str) -> State | None:
        return next((s for s in self.states if s.name == name), None)

    def outgoing(self, node_id: str) -> list[Transition]:
        return sorted((t for t in self.transitions if t.src == node_id), key=lambda t: t.priority)

    def point(self, kind: str) -> Point | None:
        return next((p for p in self.points if p.kind == kind), None)

    def points_of(self, kind: str) -> list[Point]:
        return [p for p in self.points if p.kind == kind]

    def new_id(self, prefix: str) -> str:
        used = {n.id for coll in (self.states, self.junctions, self.links, self.points, self.transitions)
                for n in coll}
        i = 1
        while f'{prefix}{i}' in used:
            i += 1
        return f'{prefix}{i}'


@dataclass
class FsmView:
    library: str = 'work'
    unit: str = 'my_fsm'
    view: str = 'fsm'
    language: str = 'systemverilog'  # LANGUAGES
    signals: list[Signal] = field(default_factory=list)
    parameters: list[Parameter] = field(default_factory=list)
    machines: list[Machine] = field(default_factory=lambda: [Machine()])
    pre_module_directives: str = ''
    post_module_directives: str = ''
    end_module_directives: str = ''
    concurrent_statements: str = ''
    state_register_statements: str = ''
    global_pre_actions: str = ''
    global_post_actions: str = ''
    registered_affix: str = '_r'
    clocked_affix: str = '_cld'
    # name of a new state, from the diagram's default-state template ('' = Dolphin's S<n>)
    default_state_name: str = ''
    # text of a new junction, from the diagram's default-junction template (HDS: "&")
    default_junction_symbol: str = ''
    # where the declaration blocks are drawn on the diagram (scene units, top-left of each title):
    # global, concurrent, module, status, statereg, compdir; missing = Dolphin's default layout
    decl_pos: dict = field(default_factory=dict)
    # the declaration blocks hidden on the diagram (HDS: their title text has isHidden 1)
    decl_hidden: list = field(default_factory=list)
    header: str = ''

    def signal(self, name: str) -> Signal | None:
        return next((s for s in self.signals if s.name == name), None)

    # -- persistence ----------------------------------------------------
    def to_json(self) -> str:
        return json.dumps({'format': 'dolphin-hds-fsm', 'version': 1, 'view': asdict(self)}, indent=2)

    @classmethod
    def from_json(cls, text: str) -> 'FsmView':
        data = json.loads(text)
        return _build(cls, data['view'])

    def save(self, path: str) -> None:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(self.to_json())

    @classmethod
    def load(cls, path: str) -> 'FsmView':
        with open(path, encoding='utf-8') as f:
            return cls.from_json(f.read())


_LIST_TYPES = {
    'signals': Signal, 'parameters': Parameter, 'machines': Machine, 'states': State,
    'junctions': Junction, 'links': Link, 'points': Point, 'transitions': Transition,
}


def _build(cls, data: dict) -> Any:
    names = {f.name for f in fields(cls)}
    kwargs = {}
    for k, v in data.items():
        if k not in names:
            continue
        # Transition.points is a plain list of [x, y]; Machine.points holds Point objects
        if k in _LIST_TYPES and not (cls is Transition and k == 'points'):
            v = [_build(_LIST_TYPES[k], item) for item in v]
        kwargs[k] = v
    return cls(**kwargs)
