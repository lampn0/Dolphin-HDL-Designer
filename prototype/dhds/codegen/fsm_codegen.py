"""Generate Verilog-2005 or SystemVerilog from an FsmView.

Style follows the legacy tool's "3 always blocks / Case / Mixed assignment"
output (docs/codegen-reference.md): a next-state block, an output block for
combinatorial signals, a clocked block, then the clocked output assignments
and the user's concurrent statements.

Action semantics: a transition that ends in a state runs the source state's
exit actions, the destination's entry actions, then the transition's own
actions. Actions on transitions into a junction run before the junction's
decision. A state's in-actions run every cycle before its transitions are
evaluated. Each statement goes to the output block or the clocked block
depending on the signal it assigns.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from ..model import FsmView, Machine, Signal, State
from .common import drivers, port_lines, sv_net_type, text_lines
from .encoding import encode

IND = '  '


# --------------------------------------------------------------------------
# Statement splitting and classification
# --------------------------------------------------------------------------
_OPEN_KW = {'begin', 'case', 'casex', 'casez', 'fork'}
_CLOSE_KW = {'end', 'endcase', 'join'}


def split_statements(text: str) -> list[str]:
    """Split HDL action text into top-level statements, keeping comments."""
    out: list[str] = []
    buf: list[str] = []
    depth = 0
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if text.startswith('//', i):
            j = text.find('\n', i)
            j = n if j < 0 else j
            buf.append(text[i:j])
            i = j
            continue
        if text.startswith('/*', i):
            j = text.find('*/', i + 2)
            j = n if j < 0 else j + 2
            buf.append(text[i:j])
            i = j
            continue
        if c.isalpha() or c == '_':
            m = re.match(r'[A-Za-z_]\w*', text[i:])
            word = m.group()
            if word in _OPEN_KW:
                depth += 1
            elif word in _CLOSE_KW:
                depth -= 1
                if depth == 0:
                    buf.append(word)
                    i += len(word)
                    out.append(''.join(buf))
                    buf = []
                    continue
            buf.append(word)
            i += len(word)
            continue
        buf.append(c)
        i += 1
        if c == ';' and depth == 0:
            # keep a trailing comment on the same line with its statement
            m = re.match(r'[ \t]*//[^\n]*', text[i:])
            if m:
                buf.append(m.group())
                i += m.end()
            out.append(''.join(buf))
            buf = []
    tail = ''.join(buf)
    if tail.strip():
        out.append(tail)
    stmts: list[str] = []
    for s in out:
        s = s.strip('\n')
        if not s.strip():
            continue
        if stmts and re.match(r'\s*else\b', s):
            stmts[-1] += '\n' + s
        else:
            stmts.append(s)
    return [_dedent(s) for s in stmts]


def _dedent(s: str) -> str:
    lines = s.split('\n')
    first = lines[0].lstrip()
    rest = lines[1:]
    pad = min((len(l) - len(l.lstrip()) for l in rest if l.strip()), default=0)
    return '\n'.join([first] + [l[pad:] for l in rest])


_ASSIGN_RE = re.compile(r'(\{[^}]*\}|[A-Za-z_]\w*)\s*(\[[^\]]*\])?\s*(<=|=)(?!=)')


def assignment_target(stmt: str) -> tuple[str | None, str | None]:
    """Return (signal name, operator) of the first assignment in a statement."""
    s = re.sub(r'//[^\n]*|/\*.*?\*/', ' ', stmt, flags=re.S).strip()
    # skip "if (...)" / "case (...)" headers so comparisons are not taken for assignments
    while True:
        m = re.match(r'(if|else\s+if|case[xz]?|for|while)\s*\(', s)
        if not m:
            m2 = re.match(r'(else|begin)\b', s)
            if m2:
                s = s[m2.end():].lstrip()
                continue
            break
        depth, j = 0, m.end() - 1
        while j < len(s):
            if s[j] == '(':
                depth += 1
            elif s[j] == ')':
                depth -= 1
                if depth == 0:
                    break
            j += 1
        s = s[j + 1:].lstrip()
    m = _ASSIGN_RE.search(s)
    if not m:
        return None, None
    lhs = m.group(1)
    if lhs.startswith('{'):
        ids = re.findall(r'[A-Za-z_]\w*', lhs)
        lhs = ids[0] if ids else None
    return lhs, m.group(3)


# --------------------------------------------------------------------------
# Decision tree built from the diagram
# --------------------------------------------------------------------------
@dataclass
class Leaf:
    dest: str | None                 # state name, None = stay in source state
    actions: list[str] = field(default_factory=list)


@dataclass
class Branch:
    cond: str | None                 # if-condition / case label; None = else / default
    pre: list[str]                   # actions of the edge into a junction
    body: object                     # Leaf | Chain | Case


@dataclass
class Chain:
    branches: list[Branch]


@dataclass
class Case:
    expr: str
    branches: list[Branch]


class GenError(Exception):
    pass


class FsmGenerator:
    def __init__(self, view: FsmView, language: str | None = None):
        self.v = view
        self.sv = (language or view.language) == 'systemverilog'
        self.warnings: list[str] = []
        self.sig = {s.name: s for s in view.signals}
        ca, ra = view.clocked_affix, view.registered_affix
        self.clocked_out = [s for s in view.signals if s.mode == 'output' and s.scheme == 'clocked']
        self.registered_out = [s for s in view.signals if s.mode == 'output' and s.scheme == 'registered']
        self.block_of: dict[str, str] = {}
        for s in view.signals:
            if s.mode not in ('output', 'local', 'inout'):
                continue
            if s.scheme == 'comb':
                self.block_of[s.name] = 'out'
            elif s.scheme == 'clocked':
                self.block_of[s.name + ca if s.mode == 'output' else s.name] = 'clk'
            elif s.scheme == 'registered':
                self.block_of[s.name + ra] = 'out'

    # -- helpers ---------------------------------------------------------
    def block(self, stmt: str) -> str:
        target, op = assignment_target(stmt)
        if target in self.block_of:
            return self.block_of[target]
        return 'clk' if op == '<=' else 'out'

    def only(self, stmts: list[str], blk: str) -> list[str]:
        return [s for s in stmts if self.block(s) == blk]

    def kw(self, verilog: str, sv: str) -> str:
        return sv if self.sv else verilog

    # -- tree building ----------------------------------------------------
    def _target_state(self, m: Machine, node_id: str) -> State | None:
        node = m.node(node_id)
        if isinstance(node, State):
            return node
        if node is not None and hasattr(node, 'target'):
            st = m.state_by_name(node.target)
            if st is None:
                self.warnings.append(f'Link to unknown state "{node.target}"')
            return st
        return None

    def build(self, m: Machine, src: State, node_id: str, seen: frozenset = frozenset()) -> Chain:
        if node_id in seen:
            raise GenError(f'Loop through junctions at {node_id}')
        seen = seen | {node_id}
        node = m.node(node_id)
        is_case = getattr(node, 'kind', '') == 'case'
        branches = []
        for t in m.outgoing(node_id):
            body = self.edge_body(m, src, t, seen)
            pre = split_statements(t.actions) if not isinstance(body, Leaf) else []
            branches.append(Branch(t.cond.strip() or None, pre, body))
        # put unconditional branches last; keep only the first one
        cond = [b for b in branches if b.cond is not None]
        other = [b for b in branches if b.cond is None]
        if len(other) > 1:
            self.warnings.append(f'{src.name}: more than one unconditional transition, extra ones ignored')
        branches = cond + other[:1]
        if not other:
            branches.append(Branch(None, [], Leaf(None)))
        if is_case:
            return Case(node.expr, branches)  # type: ignore[return-value]
        return Chain(branches)

    def edge_body(self, m: Machine, src: State, t, seen):
        dst_node = m.node(t.dst)
        if getattr(dst_node, 'kind', None) in ('if', 'case'):
            return self.build(m, src, t.dst, seen)
        st = self._target_state(m, t.dst)
        if st is None:
            self.warnings.append(f'{src.name}: transition {t.id} has no destination state')
            return Leaf(None)
        acts = split_statements(src.exit_actions) + split_statements(st.entry_actions) + split_statements(t.actions)
        return Leaf(st.name, acts)

    # -- rendering ----------------------------------------------------------
    @staticmethod
    def _indent(lines: list[str], level: int) -> list[str]:
        out = []
        for l in lines:
            for sub in l.split('\n'):
                out.append(IND * level + sub if sub.strip() else '')
        return out

    def render_ns(self, body, ns: str, src: str) -> list[str]:
        if isinstance(body, Leaf):
            return [f'{ns} = {body.dest or src};']
        if isinstance(body, Case):
            lines = [f'case ({body.expr}) ']
            for b in body.branches:
                lines.append(f'{b.cond if b.cond is not None else "default"} : ')
                lines += self._indent(self.render_ns(b.body, ns, src), 1)
            lines.append('endcase')
            return lines
        brs = body.branches
        if len(brs) == 1 and brs[0].cond is None:
            return self.render_ns(brs[0].body, ns, src)
        lines = []
        for i, b in enumerate(brs):
            head = 'if' if i == 0 else 'else if'
            head = f'{head} ({b.cond})' if b.cond is not None else 'else'
            inner = self.render_ns(b.body, ns, src)
            wrap = isinstance(b.body, Chain) and i > 0
            if wrap:
                lines += [head + ' begin'] + self._indent(inner, 1) + ['end']
            else:
                lines += [head] + self._indent(inner, 1)
        return lines

    def render_act(self, body, blk: str) -> list[str] | None:
        """Lines for one block ('out' or 'clk'); None when nothing is assigned."""
        if isinstance(body, Leaf):
            stmts = self.only(body.actions, blk)
            return stmts or None
        rendered = []
        for b in body.branches:
            inner = self.render_act(b.body, blk)
            pre = self.only(b.pre, blk)
            if pre:
                inner = pre + (inner or [])
            rendered.append((b, inner))
        if all(r is None for _, r in rendered):
            return None
        if isinstance(body, Case):
            lines = [f'case ({body.expr}) ']
            for b, inner in rendered:
                label = b.cond if b.cond is not None else 'default'
                lines += self._item(f'{label} :', inner, 0)
            lines.append('endcase')
            return lines
        while rendered and rendered[-1][1] is None:
            rendered.pop()
        if len(rendered) == 1 and rendered[0][0].cond is None:
            return rendered[0][1]
        if (len(rendered) == 2 and rendered[0][1] is None and rendered[1][0].cond is None):
            # "if (c) <nothing> else <acts>"  ->  "if (!(c)) <acts>"
            return self._stmt(f'if (!({rendered[0][0].cond}))', rendered[1][1], single_ok=False)
        lines = []
        for i, (b, inner) in enumerate(rendered):
            head = 'if' if i == 0 else 'else if'
            head = f'{head} ({b.cond})' if b.cond is not None else 'else'
            if b.cond is None and i > 0 and rendered[i - 1][0].cond is not None:
                head = 'else'
            last = i == len(rendered) - 1
            lines += self._stmt(head, inner, single_ok=last or not self._is_if(inner))
        return lines

    @staticmethod
    def _is_if(lines: list[str] | None) -> bool:
        return bool(lines) and lines[0].lstrip().startswith('if')

    def _stmt(self, head: str, inner: list[str] | None, single_ok: bool) -> list[str]:
        if inner and single_ok and (self._is_single_line(inner) or self._is_single_construct(inner)):
            return [head] + self._indent(inner, 1)
        return [head.rstrip() + ' begin'] + self._indent(inner or [], 1) + ['end']

    @staticmethod
    def _is_single_line(lines: list[str]) -> bool:
        return len(lines) == 1 and '\n' not in lines[0]

    @staticmethod
    def _is_single_construct(lines: list[str]) -> bool:
        """True when the lines form one statement: a case...endcase or an if/else chain."""
        if not lines:
            return False
        if lines[0].startswith('case') and lines[-1] == 'endcase':
            return True
        if not lines[0].startswith('if'):
            return False
        top = [l for l in '\n'.join(lines).split('\n') if l and not l.startswith(' ')]
        return all(l.startswith(('if', 'else', 'end')) for l in top) and not top[-1].startswith('endcase')

    def _item(self, label: str, inner: list[str] | None, level: int, always_block: bool = False) -> list[str]:
        if inner and not always_block and (self._is_single_line(inner) or self._is_single_construct(inner)):
            return [label + ' '] + self._indent(inner, level + 1)
        return [label + ' begin'] + self._indent(inner or [], level + 1) + [IND * level + 'end']

    # -- declarations ---------------------------------------------------------
    def _procedural(self) -> set[str]:
        """Signals assigned inside always blocks (FSM actions or user procedural code)."""
        if not hasattr(self, '_proc'):
            v = self.v
            proc = set(self.block_of)
            proc |= {s.name for s in v.signals if s.mode in ('output', 'local', 'inout') and s.scheme != 'none'}
            for m in v.machines:
                for t in m.transitions:
                    proc |= {assignment_target(x)[0] for x in split_statements(t.actions)}
                for st in m.states:
                    for txt in (st.entry_actions, st.in_actions, st.exit_actions):
                        proc |= {assignment_target(x)[0] for x in split_statements(txt)}
            user = '\n'.join((v.concurrent_statements, v.state_register_statements, v.global_pre_actions,
                              v.global_post_actions))
            proc |= drivers(user)[1]
            self._proc = proc - {None}
        return self._proc

    def _type(self, s: Signal, in_port: bool) -> str:
        if self.sv:
            return sv_net_type(s.name, self._procedural())
        if in_port and s.mode in ('input', 'inout'):
            return 'wire'
        if s.scheme in ('comb', 'clocked', 'registered') or s.mode == 'local':
            return 'reg'
        return s.type or 'wire'

    def _port_lines(self) -> list[str]:
        order = {'input': 0, 'inout': 1, 'output': 2}
        ports = sorted((s for s in self.v.signals if s.mode in order), key=lambda s: (order[s.mode], s.name))
        return port_lines([(s.mode, self._type(s, True) + (' signed' if s.signed else ''), s.bounds, s.name,
                            s.comment) for s in ports])

    def _decl_lines(self, sigs: list[tuple[str, str, str]]) -> list[str]:
        """sigs: (type+bounds, name, comment) aligned into declarations."""
        if not sigs:
            return []
        w = max(len(t) for t, _, _ in sigs) + 1
        wn = max(len(n) for _, n, _ in sigs) + 2
        out = []
        for t, n, c in sigs:
            line = f'{t:<{w}}{n};'
            if c:
                line = f'{line:<{w + wn}}// {c}'
            out.append(line)
        return out

    def _sig_type(self, s: Signal, name: str | None = None) -> str:
        base = sv_net_type(name or s.name, self._procedural()) if self.sv else 'reg'
        return f'{base} {s.bounds}'.strip()

    # -- whole module -----------------------------------------------------------
    def generate(self) -> str:
        v = self.v
        lines: list[str] = []
        hdr = v.header or (f'// Module {v.library}.{v.unit}.{v.view}\n'
                           f'// Generated by Dolphin HDS (prototype) - '
                           f'{"SystemVerilog" if self.sv else "Verilog"}')
        lines += hdr.rstrip('\n').split('\n')
        if v.pre_module_directives.strip():
            lines += v.pre_module_directives.rstrip('\n').split('\n')
        if v.parameters:
            lines.append(f'module {v.unit} #(')
            w = max(len(p.name) for p in v.parameters)
            for i, p in enumerate(v.parameters):
                sep = ',' if i < len(v.parameters) - 1 else ''
                lines.append(f'{IND}parameter {p.name:<{w}} = {p.value}{sep}')
            lines.append(')')
            lines.append('( ')
        else:
            lines.append(f'module {v.unit} ( ')
        lines.append(f'{IND}// Port Declarations')
        lines += self._port_lines()
        lines.append(');')
        lines.append('')
        if v.post_module_directives.strip():
            lines += v.post_module_directives.rstrip('\n').split('\n')
        lines.append('// Internal Declarations')
        lines.append('')
        pre_reg = [(self._sig_type(s, s.name + v.clocked_affix), s.name + v.clocked_affix, '') for s in sorted(self.clocked_out, key=lambda s: s.name)]
        pre_reg += [(self._sig_type(s, s.name + v.registered_affix), s.name + v.registered_affix, '') for s in sorted(self.registered_out, key=lambda s: s.name)]
        if pre_reg:
            lines.append('')
            lines.append('// Declare any pre-registered internal signals')
            lines += self._decl_lines(pre_reg)
        locals_ = sorted((s for s in v.signals if s.mode == 'local'), key=lambda s: s.name)
        if locals_:
            lines.append('')
            lines.append('// Module Declarations')
            lines += self._decl_lines([(self._sig_type(s), s.name, s.comment) for s in locals_])
        multi = len(v.machines) > 1
        for m in v.machines:
            lines += self.machine(m, prefix=f'{m.name}_' if multi else '')
        lines.append('')
        lines.append('// Concurrent Statements')
        if self.clocked_out:
            lines.append('// Clocked output assignments')
            lines.append(self.kw('always @ *', 'always_comb'))
            lines.append('begin : clocked_output_proc')
            for s in sorted(self.clocked_out, key=lambda s: s.name):
                lines.append(f'{IND}{s.name} = {s.name}{v.clocked_affix};')
            lines.append('end')
        if v.concurrent_statements.strip():
            lines += v.concurrent_statements.rstrip('\n').split('\n')
        if v.end_module_directives.strip():
            lines += v.end_module_directives.rstrip('\n').split('\n')
        lines.append(f'endmodule // {v.unit}')
        lines.append('')
        if self.sv:
            self.check_single_driver(v)
        return '\n'.join(lines)

    def check_single_driver(self, v: FsmView) -> None:
        targets_out, targets_clk = set(), set()
        for m in v.machines:
            for t in m.transitions:
                for s in split_statements(t.actions):
                    (targets_out if self.block(s) == 'out' else targets_clk).add(assignment_target(s)[0])
            for st in m.states:
                for txt in (st.entry_actions, st.in_actions, st.exit_actions):
                    for s in split_statements(txt):
                        (targets_out if self.block(s) == 'out' else targets_clk).add(assignment_target(s)[0])
        both = sorted(n for n in targets_out & targets_clk if n)
        for n in both:
            self.warnings.append(f'SystemVerilog: "{n}" is assigned in both always_comb and always_ff '
                                 f'(mixed "=" and "<="); fix the actions or the signal scheme')

    def machine(self, m: Machine, prefix: str) -> list[str]:
        v = self.v
        cs, ns = prefix + m.current_state_name, prefix + m.next_state_name
        names = [s.name for s in m.states]
        if not names:
            self.warnings.append(f'Machine {m.name} has no states')
            return []
        width, codes = encode(names, m.encoding, {s.name: s.encoding for s in m.states})
        rng = f'[{width - 1}:0]'
        decl = m.state_decl if (self.sv or m.state_decl != 'enum') else 'parameter'
        if m.state_decl == 'enum' and not self.sv:
            self.warnings.append('State declaration "enum" needs SystemVerilog; using parameter for Verilog')
        lines = ['', '// State encoding']
        w = max(len(n) for n in names)
        if decl == 'enum':
            tname = f'{m.name}_state_t'
            lines.append(f'typedef enum logic {rng} {{')
            for i, n in enumerate(names):
                lines.append(f'{IND}{n:<{w}} = {codes[n]}' + (',' if i < len(names) - 1 else ''))
            lines.append(f'}} {tname};')
            lines.append('')
            lines.append(f'{tname} {cs}, {ns};')
        else:
            kw = decl if not (self.sv and decl == 'localparam') else f'localparam logic {rng}'
            lines.append(f'{kw} ')
            for i, n in enumerate(names):
                lines.append(f'{IND * 5}{n:<{w}} = {codes[n]}' + (',' if i < len(names) - 1 else ';'))
            lines.append('')
            lines.append(f'{"logic" if self.sv else "reg"} {rng} {cs}, {ns};')

        trees = {st.name: self.build(m, st, st.id) for st in m.states}
        interrupts = []
        for p in m.points_of('interrupt'):
            for t in m.outgoing(p.id):
                dst = self._target_state(m, t.dst)
                if dst is not None and t.cond.strip():
                    interrupts.append((t.cond.strip(), dst.name, split_statements(t.actions)))
        recovery = None
        rp = m.point('recovery')
        if rp is not None:
            out = m.outgoing(rp.id)
            if out:
                dst = self._target_state(m, out[0].dst)
                recovery = (dst.name if dst else None, split_statements(out[0].actions))
        reset_dest = None
        rst = m.point('reset')
        if rst is not None and m.outgoing(rst.id):
            d = self._target_state(m, m.outgoing(rst.id)[0].dst)
            reset_dest = d.name if d else None

        # ---- next state block
        title = f'machine {m.name}'
        lines += ['', '//' + '-' * 65, f'// Next State Block for {title}', '//' + '-' * 65,
                  self.kw('always @ *', 'always_comb'), 'begin : ' + prefix + 'next_state_block_proc']
        body = [f'case ({cs}) ']
        for st in m.states:
            inner = self.render_ns(trees[st.name], ns, st.name)
            body += self._item(f'{IND}{st.name}:', inner, 1, always_block=True)
        body.append(f'{IND}default: ')
        body.append(f'{IND * 2}{ns} = {recovery[0] if recovery and recovery[0] else cs};')
        body.append('endcase')
        body = self._wrap_interrupts(interrupts, body, lambda acts, dst: [f'{ns} = {dst};'])
        lines += self._indent(body, 1)
        lines.append('end // Next State Block')

        # ---- output block
        defaults = sorted((s for s in v.signals if s.mode in ('output', 'local') and s.scheme == 'comb' and s.default),
                          key=lambda s: s.name)
        defaults_r = sorted((s for s in self.registered_out if s.default), key=lambda s: s.name)
        out_lines = []
        if defaults or defaults_r:
            out_lines.append('// Default Assignment')
            out_lines += [f'{s.name} = {s.default};' for s in defaults]
            out_lines += [f'{s.name}{v.registered_affix} = {s.default};' for s in defaults_r]
        out_lines += self.only(split_statements(v.global_pre_actions), 'out')
        case_out = self._action_case(m, cs, trees, recovery, 'out')
        out_lines += self._wrap_interrupts(interrupts, case_out, lambda acts, dst: self.only(acts, 'out'),
                                           action_block=True)
        out_lines += self.only(split_statements(v.global_post_actions), 'out')
        lines += ['', '//' + '-' * 65, f'// Output Block for {title}', '//' + '-' * 65,
                  self.kw('always @ *', 'always_comb'), 'begin : ' + prefix + 'output_block_proc']
        lines += self._indent(out_lines, 1)
        lines.append('end // Output Block')

        # ---- clocked block
        clk = next((s for s in v.signals if s.category == 'clock'), None)
        rst_sig = next((s for s in v.signals if s.category == 'reset'), None)
        if clk is None:
            self.warnings.append('No clock signal: set Category = clock in the Signals table')
            clk_expr = 'posedge clk'
        else:
            clk_expr = clk.expression or f'posedge {clk.name}'
        sens = [clk_expr]
        rst_cond = None
        if rst_sig is not None:
            rst_cond = rst_sig.expression or f'!{rst_sig.name}'
            neg = rst_cond.lstrip().startswith(('!', '~'))
            sens.append(f'{"negedge" if neg else "posedge"} {rst_sig.name}')
        sep = ' or ' if self.sv else ', '
        if self.sv:
            lines += ['', '//' + '-' * 65, f'// Clocked Block for {title}', '//' + '-' * 65,
                      f'always_ff @({sep.join(sens)})']
        else:
            lines += ['', '//' + '-' * 65, f'// Clocked Block for {title}', '//' + '-' * 65,
                      'always @(', ', \n'.join(f'{IND}{s}' for s in sens) + '\n) ']
        lines.append('begin : ' + prefix + 'clocked_block_proc')
        run = []
        if v.state_register_statements.strip():
            run += split_statements(v.state_register_statements)
        else:
            run.append(f'{cs} <= {ns};')
        run += [f'{s.name} <= {s.name}{v.registered_affix};' for s in sorted(self.registered_out, key=lambda s: s.name)]
        run += self.only(split_statements(v.global_pre_actions), 'clk')
        if not interrupts:
            run.append('')
        case_clk = self._action_case(m, cs, trees, recovery, 'clk')
        run += self._wrap_interrupts(interrupts, case_clk, lambda acts, dst: self.only(acts, 'clk'),
                                     action_block=True)
        run += self.only(split_statements(v.global_post_actions), 'clk')
        if rst_cond is not None:
            resets = [f'{cs} <= {reset_dest or names[0]};', '// Reset Values']
            resets += [f'{s.name}{v.clocked_affix} <= {s.reset};' for s in sorted(self.clocked_out, key=lambda s: s.name) if s.reset]
            resets += [f'{s.name} <= {s.reset};' for s in sorted(self.registered_out, key=lambda s: s.name) if s.reset]
            resets += [f'{s.name} <= {s.reset};' for s in sorted(v.signals, key=lambda s: s.name)
                       if s.mode == 'local' and s.scheme == 'clocked' and s.reset]
            if reset_dest is None:
                self.warnings.append('No reset point: reset goes to the first state')
            blk = [f'if ({rst_cond}) begin'] + self._indent(resets, 1) + ['end', 'else ', 'begin'] + \
                self._indent(run, 1) + ['end']
        else:
            blk = run
        lines += self._indent(blk, 1)
        lines.append('end // Clocked Block')
        return lines

    def _action_case(self, m: Machine, cs: str, trees, recovery, blk: str) -> list[str]:
        lines = ['// Combined Actions', f'case ({cs}) ']
        empty = []
        for st in m.states:
            inner = self.only(split_statements(st.in_actions), blk)
            r = self.render_act(trees[st.name], blk)
            if r:
                inner += r
            if inner:
                lines += self._item(f'{IND}{st.name}:', inner, 1, always_block=True)
            else:
                empty.append(st.name)
        rec = self.only(recovery[1], blk) if recovery else []
        if rec and empty:
            # list states without actions so they do not fall into the recovery branch
            lines.append(IND + (',\n' + IND).join(empty) + ': begin')
            lines.append(IND + 'end')
        lines += self._item(f'{IND}default:', rec, 1) if rec else []
        lines.append('endcase')
        if len(lines) == 3 and not rec:
            return []
        return lines

    def _wrap_interrupts(self, interrupts, body: list[str], action_of, action_block: bool = False) -> list[str]:
        if not interrupts:
            return body
        out = []
        for i, (cond, dst, acts) in enumerate(interrupts):
            head = 'if' if i == 0 else 'else if'
            inner = action_of(acts, dst)
            out += self._stmt(f'{head} ({cond}) ' if action_block else f'{head} ({cond})', inner,
                              single_ok=action_block)
        if action_block:
            out = ['', '// Interrupts'] + out
        out += ['else begin'] + ([''] if action_block else []) + self._indent(body, 1) + ['end']
        return out


def generate(view: FsmView, language: str | None = None) -> tuple[str, list[str]]:
    g = FsmGenerator(view, language)
    text = g.generate()
    return text, g.warnings
