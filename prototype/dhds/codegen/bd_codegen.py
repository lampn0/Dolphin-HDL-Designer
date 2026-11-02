"""Generate structural Verilog / SystemVerilog from a BlockDiagram.

Layout follows the legacy tool: header, directives, ANSI parameters and
ports, internal signal declarations, instances (named port mapping in
symbol order, sorted by instance name), embedded text blocks.
"""
from __future__ import annotations

from ..bd_model import BlockDiagram
from ..model import Signal
from .common import IND, drivers, port_lines, sv_net_type, text_lines


class BdGenerator:
    def __init__(self, bd: BlockDiagram, language: str | None = None):
        self.bd = bd
        self.sv = (language or bd.language) == 'systemverilog'
        self.warnings: list[str] = []

    def _procedural(self) -> set[str]:
        if not hasattr(self, '_proc'):
            self._proc = drivers('\n'.join(e.text for e in self.bd.embedded))[1]
        return self._proc

    def _port_type(self, s: Signal) -> str:
        if self.sv:
            return sv_net_type(s.name, self._procedural())
        if s.mode in ('input', 'inout'):
            return 'wire'
        return s.type if s.type in ('wire', 'reg') else 'wire'

    def _ports(self) -> list[str]:
        order = {'input': 0, 'inout': 1, 'output': 2}
        ports = sorted((s for s in self.bd.signals if s.mode in order), key=lambda s: (order[s.mode], s.name))
        return port_lines([(s.mode, self._port_type(s) + (' signed' if s.signed else ''), s.bounds, s.name,
                            s.comment) for s in ports])

    def _internal(self) -> list[str]:
        port_names = {s.name for s in self.bd.signals if s.mode != 'local'}
        nets = sorted((s for s in self.bd.signals if s.mode == 'local' and s.name not in port_names),
                      key=lambda s: s.name)
        if not nets:
            return []
        types = {}
        for s in nets:
            if self.sv and s.type in ('wire', 'reg', 'logic', ''):
                t = sv_net_type(s.name, self._procedural())
            else:
                t = s.type if s.type else 'wire'     # wire / reg / tri / supply0 / ... as declared
            if s.strength and t == 'trireg':
                t += f' ({s.strength})'
            if s.expansion and t not in ('reg', 'logic', 'integer', 'time', 'real', 'realtime'):
                t += f' {s.expansion}'
            if s.signed:
                t += ' signed'
            types[s.name] = t
        wt = max(6, max(len(t) + 1 for t in types.values()))
        wb = max(len(s.bounds) for s in nets) + 1
        extra = any(s.array or s.value or s.delay for s in nets)
        wname = max(len(s.name) for s in nets) + 2
        out = []
        for s in nets:
            delay = f'#{s.delay} ' if s.delay else ''
            if extra:
                tail = (f'{s.name:<{wname}}{s.array + " " if s.array else ""}'
                        f'{"= " + s.value if s.value else ""}').rstrip()
            else:
                tail = s.name
            # Verilog order: type [range] [#delay] name
            head = f'{s.bounds + " " if s.bounds else ""}{delay}' if delay else f'{s.bounds:<{wb}}'
            line = f'{types[s.name]:<{wt}}{head}{tail};'
            if s.comment:
                width = wt + wb + (wname + 12 if extra else max(len(n.name) + 1 for n in nets) + 3)
                line = f'{line:<{width}}// {s.comment}'
            out.append(line)
        return out

    def _instance(self, inst, array: str = '') -> list[str]:
        known = {s.name for s in self.bd.signals}
        head = inst.unit
        if inst.params:
            # legacy layout: named mapping on one line, no spaces
            head += ' #(' + ','.join(f'.{p.name}({p.value})' for p in inst.params) + ')'
        out = [l.rstrip() for l in inst.attributes.strip('\n').split('\n')] if inst.attributes.strip() else []
        out.append(f'{head} {inst.name}{array}( ')
        explicit = _port_map(inst.portmap_text) if inst.portmap_frame else {}
        pins = sorted(inst.pins, key=lambda p: p.order)
        w = max((len(p.name) for p in pins), default=0) + 1
        for i, p in enumerate(pins):
            sep = ', ' if i < len(pins) - 1 else ''
            actual = p.net or explicit.get(p.name, '')
            out.append(f'{IND}.{p.name:<{w}}({actual}){sep}')
            if p.net and p.net.split('[')[0] not in known:
                self.warnings.append(f'{inst.name}.{p.name}: net "{p.net}" is not declared')
            if not actual and p.mode != 'output':
                self.warnings.append(f'{inst.name}.{p.name}: input is not connected')
        out.append('); ')
        return out

    def _instances(self) -> list[str]:
        """Instances outside frames, and instance arrays for those in a FOR frame
        (as the legacy tool writes them: unit inst[left:right](...))."""
        out = []
        for inst in sorted(self.bd.instances, key=lambda i: i.name):
            frame = self.bd.frame_of(inst)
            if frame is not None and frame.kind != 'for':
                continue
            array = '[{}:{}]'.format(*frame.range()) if frame is not None else ''
            out += self._instance(inst, array) + ['']
        return out

    @staticmethod
    def _embedded(eb, indent: str = '') -> list[str]:
        return [f'{indent}// HDL Embedded Text Block {eb.number} {eb.name}'] + [indent + l for l in text_lines(eb.text)]

    def _frame_body(self, frame, indent: str) -> list[str]:
        out = []
        for inst in sorted((i for i in self.bd.instances if self.bd.frame_of(i) is frame), key=lambda i: i.name):
            out += [indent + l for l in self._instance(inst)]
        for eb in sorted((e for e in self.bd.embedded if self.bd.frame_of(e) is frame), key=lambda e: e.number):
            out += self._embedded(eb, indent)
        return out

    def _if_frames(self) -> list[str]:
        """IF frames (with their ELSE frame): `ifdef blocks or generate-if blocks."""
        out = []
        frames = sorted(self.bd.frames, key=lambda f: f.number)
        for f in (f for f in frames if f.kind == 'if'):
            other = next((e for e in frames if e.kind == 'else' and e.name == f.name), None)
            cond = f.spec.strip()
            if cond.startswith('`'):
                out.append(cond)
                out += self._frame_body(f, IND)
                if other is not None:
                    out.append('`else')
                    out += self._frame_body(other, IND)
                out += ['`endif', '']
            else:
                cond = cond if cond.startswith('(') and cond.endswith(')') else f'({cond})'
                out += ['generate', f'{IND}if {cond} begin : {f.name}']
                out += self._frame_body(f, IND * 2)
                out.append(f'{IND}end')
                if other is not None:
                    out.append(f'{IND}else begin : {f.name}_else')
                    out += self._frame_body(other, IND * 2)
                    out.append(f'{IND}end')
                out += ['endgenerate', '']
        for f in (f for f in frames if f.kind == 'else'):
            if not any(i.kind == 'if' and i.name == f.name for i in frames):
                self.warnings.append(f'ELSE frame {f.name} has no IF frame of the same name')
        return out

    def _for_embedded(self) -> list[str]:
        """Embedded blocks inside a FOR frame: a generate loop over the frame range."""
        out = []
        for f in sorted((f for f in self.bd.frames if f.kind == 'for'), key=lambda f: f.number):
            blocks = [e for e in self.bd.embedded if self.bd.frame_of(e) is f]
            if not blocks:
                continue
            left, right = f.range()
            out += [f'genvar {f.name};', 'generate',
                    f'{IND}for ({f.name} = {right}; {f.name} <= {left}; {f.name} = {f.name} + 1) begin : {f.name}_gen']
            for eb in sorted(blocks, key=lambda e: e.number):
                out += self._embedded(eb, IND * 2)
            out += [f'{IND}end', 'endgenerate', '']
        return out

    def generate(self) -> str:
        bd = self.bd
        lines = (bd.header or f'// Module {bd.library}.{bd.unit}.{bd.view}\n'
                 f'// Generated by Dolphin HDS (prototype) - {"SystemVerilog" if self.sv else "Verilog"}').split('\n')
        if bd.pre_module_directives.strip():
            lines += bd.pre_module_directives.rstrip('\n').split('\n')
        if bd.parameters:
            lines.append(f'module {bd.unit} #(')
            w = max(len(p.name) for p in bd.parameters)
            for i, p in enumerate(bd.parameters):
                lines.append(f'{IND}parameter {p.name:<{w}} = {p.value}' + (',' if i < len(bd.parameters) - 1 else ''))
            lines += [')', '( ']
        else:
            lines.append(f'module {bd.unit} ( ')
        lines.append(f'{IND}// Port Declarations')
        lines += self._ports()
        lines += [');', '']
        if bd.post_module_directives.strip():
            lines += bd.post_module_directives.rstrip('\n').split('\n')
        lines += ['// Internal Declarations', '', '', '// Local declarations', '', '// Internal signal declarations']
        lines += self._internal()
        lines += ['', '', '// Instances ']
        lines += self._instances()
        lines += self._if_frames()
        for eb in sorted(bd.embedded, key=lambda e: e.number):
            if bd.frame_of(eb) is None:
                lines += self._embedded(eb) + ['']
        lines += self._for_embedded()
        if bd.end_module_directives.strip():
            lines += bd.end_module_directives.rstrip('\n').split('\n')
        lines += [f'endmodule // {bd.unit}', '', '']
        return '\n'.join(lines)


def _port_map(text: str) -> dict[str, str]:
    """".a(expr), .b(x[3])" from a port map frame -> {port: expression}."""
    out, i = {}, 0
    while True:
        i = text.find('.', i)
        if i < 0:
            return out
        j = text.find('(', i)
        if j < 0:
            return out
        name, depth, k = text[i + 1:j].strip(), 1, j + 1
        while k < len(text) and depth:
            depth += {'(': 1, ')': -1}.get(text[k], 0)
            k += 1
        if name.replace('_', '').replace('$', '').isalnum():
            expr = text[j + 1:k - 1].strip()
            if expr:
                out[name] = expr
        i = k


def generate_bd(bd: BlockDiagram, language: str | None = None) -> tuple[str, list[str]]:
    g = BdGenerator(bd, language)
    return g.generate(), g.warnings
