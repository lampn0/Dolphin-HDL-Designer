"""Extract design units (modules, interfaces, packages), their ports and
instances from Verilog/SystemVerilog source files.

Uses slang (pyslang) for a real parse; falls back to a regex scan when
pyslang is not installed so the explorer still works.
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

try:
    import pyslang
    from pyslang import parsing, syntax
    HAVE_SLANG = True
except ImportError:  # pragma: no cover - exercised only without pyslang
    HAVE_SLANG = False

HDL_EXTENSIONS = ('.v', '.sv', '.vlg', '.verilog', '.vo')
HEADER_EXTENSIONS = ('.vh', '.svh', '.h', '.inc')


@dataclass
class HdlPort:
    """A port of a design unit: name, direction (input / output / inout / ref) and declared type."""
    name: str
    direction: str
    type: str = ''


@dataclass
class HdlInstance:
    """An instance found in a unit: the module instantiated, the instance name, the generate
    blocks around it (outermost first, e.g. ["FOR : g_loop"]) and its parameter assignment text.
    """
    module: str
    name: str
    generate: list[str] = field(default_factory=list)   # e.g. ["FOR : g_loop"]
    params: str = ''


@dataclass
class HdlUnit:
    """A design unit declared in a file, with the line of its name."""
    name: str
    kind: str                    # module | interface | package | program
    file: str
    line: int
    language: str
    ports: list[HdlPort] = field(default_factory=list)
    instances: list[HdlInstance] = field(default_factory=list)
    params: list[tuple[str, str]] = field(default_factory=list)   # overridable parameters and defaults


@dataclass
class HdlFile:
    """The result of parsing one file: its units, errors (the file shows red in the Design Manager)
    and warnings (for example an include file that was not found). `mtime` lets callers cache.
    """
    path: str
    mtime: float
    units: list[HdlUnit] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """True when the file parsed without errors."""
        return not self.errors


def language_of(path: str) -> str:
    """'SystemVerilog' for .sv / .svh files, else 'Verilog 2005' (the language column of the DM)."""
    return 'SystemVerilog' if path.lower().endswith(('.sv', '.svh')) else 'Verilog 2005'


_KIND = {}
if HAVE_SLANG:
    _KIND = {
        syntax.SyntaxKind.ModuleDeclaration: 'module',
        syntax.SyntaxKind.InterfaceDeclaration: 'interface',
        syntax.SyntaxKind.PackageDeclaration: 'package',
        syntax.SyntaxKind.ProgramDeclaration: 'program',
    }
# diagnostics that only mean "an include file or macro was not found"
_SOFT_DIAGS = ('CouldNotOpenIncludeFile', 'UnknownDirective', 'ExpectedExpression', 'UndefinedMacro')


def parse_file(path: str, include_dirs: list[str] | None = None, defines: dict[str, str] | None = None) -> HdlFile:
    """Parse one HDL file and return its units, ports, parameters and instances.

    `include_dirs` and `defines` are passed to the preprocessor (the file's own folder is always
    searched for includes). Diagnostics caused only by a missing include file or macro are
    reported as warnings, not errors, because a library file often depends on defines of the
    whole project.
    """
    mtime = os.path.getmtime(path) if os.path.exists(path) else 0.0
    if not HAVE_SLANG:
        return _regex_parse(path, mtime)
    sm = pyslang.SourceManager()
    po = parsing.PreprocessorOptions()
    po.additionalIncludePaths = list(include_dirs or []) + [os.path.dirname(path)]
    if defines:
        po.predefines = [f'{k}={v}' if v else k for k, v in defines.items()]
    tree = syntax.SyntaxTree.fromFile(path, sm, pyslang.Bag([po]))
    result = HdlFile(path, mtime)
    soft = any('CouldNotOpenIncludeFile' in str(d.code) for d in tree.diagnostics)
    for d in tree.diagnostics:
        code = str(d.code).replace('DiagCode(', '').rstrip(')')
        loc = sm.getLineNumber(d.location) if d.location else 0
        msg = f'{os.path.basename(path)}:{loc}: {code}'
        if code == 'CouldNotOpenIncludeFile' or (soft and code in _SOFT_DIAGS):
            result.warnings.append(msg)
        elif d.isError():
            result.errors.append(msg)
    lang = language_of(path)
    for member in tree.root.members:
        kind = _KIND.get(member.kind)
        if kind is None:
            continue
        hdr = member.header
        unit = HdlUnit(hdr.name.valueText, kind, path, sm.getLineNumber(hdr.name.location), lang)
        unit.ports = _ports(member)
        unit.instances = _instances(member)
        unit.params = _params(member, path)
        result.units.append(unit)
    return result


def _ports(member) -> list[HdlPort]:
    """Ports of a module from its header: an ANSI port list (direction carried over to the next
    ports when omitted, as the language says) or, for a non-ANSI header, the port declarations in
    the body.
    """
    ports = []
    plist = member.header.ports
    if plist is None:
        return ports
    if plist.kind == syntax.SyntaxKind.AnsiPortList:
        last_dir = 'inout'
        for p in plist.ports:
            if p.kind != syntax.SyntaxKind.ImplicitAnsiPort:
                continue
            h = p.header
            direction = getattr(h, 'direction', None)
            d = direction.valueText if direction is not None and direction.valueText else last_dir
            last_dir = d
            typ = ' '.join(x for x in (_tok(getattr(h, 'netType', None)), _text(getattr(h, 'dataType', None))) if x)
            ports.append(HdlPort(p.declarator.name.valueText, d, typ))
    else:
        for m in member.members:
            if m.kind == syntax.SyntaxKind.PortDeclaration:
                h = m.header
                d = h.direction.valueText if getattr(h, 'direction', None) is not None else 'inout'
                typ = ' '.join(x for x in (_tok(getattr(h, 'netType', None)), _text(getattr(h, 'dataType', None))) if x)
                for decl in m.declarators:
                    if not isinstance(decl, syntax.SyntaxNode):
                        continue
                    ports.append(HdlPort(decl.name.valueText, d, typ))
    return ports


def _params(member, path: str = '') -> list[tuple[str, str]]:
    """Parameters a user may override: #( parameter ... ) or, without that list, body `parameter`s."""
    out: list[tuple[str, str]] = []

    def take(decl, kw: str) -> str:
        """Collect the declarators of one parameter declaration (`kw` = keyword inherited from the
        previous declaration of the list); localparams are skipped. Returns the keyword in effect.
        """
        kw = decl.keyword.valueText or kw
        if kw != 'localparam':
            for d in decl.declarators:
                if not isinstance(d, syntax.SyntaxNode):
                    continue        # separator token
                out.append((d.name.valueText, _text(d.initializer.expr) if d.initializer else ''))
        return kw
    plist = member.header.parameters
    if plist is not None:
        kw = 'parameter'
        for d in plist.declarations:
            if isinstance(d, syntax.SyntaxNode) and d.kind == syntax.SyntaxKind.ParameterDeclaration:
                kw = take(d, kw)
    else:
        for m in member.members:
            if m.kind == syntax.SyntaxKind.ParameterDeclarationStatement and                     m.parameter.kind == syntax.SyntaxKind.ParameterDeclaration:
                take(m.parameter, 'parameter')
    if path:
        # the syntax tree has macros expanded (`CFG_X -> 16): show defaults as declared in the source
        try:
            with open(path, encoding='utf-8', errors='replace') as f:
                src = f.read()
        except OSError:
            src = ''
        start = src.find(member.header.name.valueText) if src else -1
        for i, (n, v) in enumerate(out):
            text = _declared_default(src, n, max(start, 0)) if src else ''
            if text:
                out[i] = (n, text)
    return out


def _declared_default(src: str, name: str, start: int = 0) -> str:
    """Text after `name =` in a parameter declaration, up to the ',' ';' or ')' that ends it."""
    code = re.sub(r'//[^\n]*|/\*.*?\*/', lambda m: ' ' * len(m.group(0)), src, flags=re.S)
    m = re.compile(r'\b' + re.escape(name) + r'\s*=(?!=)').search(code, start)
    if m is None:
        return ''
    depth, i = 0, m.end()
    while i < len(code):
        c = code[i]
        if c in '([{':
            depth += 1
        elif c in ')]}':
            if depth == 0:
                break
            depth -= 1
        elif c in ',;' and depth == 0:
            break
        i += 1
    return ' '.join(src[m.end():i].split())


def _instances(member) -> list[HdlInstance]:
    """Every instance in a module (recursively, through generate blocks)."""
    found: list[HdlInstance] = []

    def visit(n):
        """Syntax-tree visitor: record each HierarchyInstantiation with the generate blocks above it."""
        if isinstance(n, syntax.SyntaxNode) and n.kind == syntax.SyntaxKind.HierarchyInstantiation:
            gen = []
            q = n.parent
            while q is not None and q is not member:
                if q.kind == syntax.SyntaxKind.GenerateBlock and q.beginName is not None:
                    parent = q.parent
                    tag = 'FOR' if parent is not None and parent.kind == syntax.SyntaxKind.LoopGenerate else \
                        'IF' if parent is not None and parent.kind == syntax.SyntaxKind.IfGenerate else 'BLOCK'
                    gen.insert(0, f'{tag} : {q.beginName.name.valueText}')
                q = q.parent
            params = _text(n.parameters)
            for inst in n.instances:
                if inst.decl is not None:
                    found.append(HdlInstance(n.type.valueText, inst.decl.name.valueText, gen, params))
    member.visit(visit)
    return found


def _tok(t) -> str:
    """Text of a token, '' when the token is missing or empty."""
    return t.valueText if t is not None and getattr(t, 'valueText', '') else ''


def _text(node) -> str:
    """Source text of a syntax node with runs of white space collapsed to one space."""
    return re.sub(r'\s+', ' ', str(node)).strip() if node is not None else ''


def check_text(text: str, name: str, include_dirs: list[str] | None = None) -> list[tuple[int, str, str]]:
    """Syntax-check source text. Returns (line, severity, message) tuples."""
    if not HAVE_SLANG:
        return [(0, 'warning', 'pyslang not installed: syntax check unavailable')]
    sm = pyslang.SourceManager()
    po = parsing.PreprocessorOptions()
    po.additionalIncludePaths = list(include_dirs or []) + ([os.path.dirname(name)] if os.path.dirname(name) else [])
    tree = syntax.SyntaxTree.fromText(text, sm, os.path.basename(name), name, pyslang.Bag([po]))
    out = []
    soft = any('CouldNotOpenIncludeFile' in str(d.code) for d in tree.diagnostics)
    for d in tree.diagnostics:
        code = str(d.code).replace('DiagCode(', '').rstrip(')')
        line = sm.getLineNumber(d.location) if d.location else 0
        msg = pyslang.DiagnosticEngine.reportAll(sm, [d]).strip().split('\n')[0]
        msg = re.sub(r'^.*?:\d+:\d+:\s*', '', msg)
        msg = re.sub(r'^(error|warning|note):\s*', '', msg)
        sev = 'warning' if code == 'CouldNotOpenIncludeFile' or (soft and code in _SOFT_DIAGS) or not d.isError() \
            else 'error'
        out.append((line, sev, msg or code))
    return out


# ---------------------------------------------------------------------------
_UNIT_RE = re.compile(r'^\s*(module|interface|package|program)\s+(?:automatic\s+|static\s+)?(\w+)', re.M)


def _regex_parse(path: str, mtime: float) -> HdlFile:
    """Fallback without pyslang: find unit names only (no ports or instances), with a warning."""
    res = HdlFile(path, mtime)
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            text = f.read()
    except OSError as e:
        res.errors.append(str(e))
        return res
    for m in _UNIT_RE.finditer(text):
        res.units.append(HdlUnit(m.group(2), m.group(1), path, text.count('\n', 0, m.start()) + 1, language_of(path)))
    res.warnings.append('pyslang not installed: ports and instances are not extracted')
    return res
