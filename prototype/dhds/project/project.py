"""Project, libraries and design units.

A Library maps a logical name to HDL directories (source files) and one
graphics directory (`hds/<unit>/<view>.<ext>`). Scanning a library yields
DesignUnits, each with its views (state machine, block diagram, symbol,
HDL text)."""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field

from ..hdl.parser import HDL_EXTENSIONS, HEADER_EXTENSIONS, HdlFile, HdlUnit, parse_file

_ALLOWED: tuple[str, ...] = ()        # Options > Verilog > File: Allowed Extensions (empty: built-in list)


def set_allowed_extensions(text: str) -> None:
    global _ALLOWED
    _ALLOWED = tuple('.' + e.lstrip('.').lower() for e in text.split() if e.strip('.'))


def hdl_extensions() -> tuple[str, ...]:
    return _ALLOWED or HDL_EXTENSIONS
from .hdp import HdpFile, expand_path, read_hdp, type_from_hdp, type_to_hdp, write_hdp

VIEW_KINDS = {
    '.fsm.json': ('fsm', 'State Machine'),
    '.bd.json': ('bd', 'Block Diagram'),
    '.sm': ('fsm', 'State Machine'),
    '.bd': ('bd', 'Block Diagram'),
    '.sb': ('symbol', 'Symbol'),
    '.tt': ('other', 'Truth Table'),
    '.fc': ('other', 'Flow Chart'),
    '.ibd': ('other', 'IBD'),
    '.asm': ('other', 'ASM Chart'),
}
GRAPHIC_KINDS = ('fsm', 'bd')
DEFAULT_VIEWS_FILE = '.dhds_default_views.json'    # in a library's hds folder: unit -> "view|kind"


@dataclass
class View:
    name: str
    kind: str                 # fsm | bd | symbol | text | other
    label: str                # "State Machine", "Block Diagram", "Module", ...
    path: str
    language: str = ''
    legacy: bool = False      # read from a legacy .sm/.bd file (saved as .json by this tool)

    @property
    def mtime(self) -> float:
        return os.path.getmtime(self.path) if os.path.exists(self.path) else 0.0


@dataclass
class DesignUnit:
    name: str
    library: 'Library'
    views: list[View] = field(default_factory=list)
    hdl: HdlUnit | None = None
    file_errors: list[str] = field(default_factory=list)

    @property
    def type(self) -> str:
        if any(v.kind in ('symbol',) + GRAPHIC_KINDS for v in self.views):
            return 'Component'
        return {'package': 'Package', 'interface': 'Interface'}.get(self.hdl.kind if self.hdl else '', 'Module')

    @property
    def language(self) -> str:
        if self.hdl:
            return self.hdl.language
        g = self.graphic_view()
        return g.language if g else ''

    def graphic_view(self) -> View | None:
        return next((v for v in self.views if v.kind in GRAPHIC_KINDS), None)

    def text_view(self) -> View | None:
        return next((v for v in self.views if v.kind == 'text'), None)

    def default_view(self) -> View | None:
        """The view chosen with Set Default View, else the graphical view, else the HDL text."""
        chosen = self.library.default_views.get(self.name)
        if chosen:
            v = next((v for v in self.views if f'{v.name}|{v.kind}' == chosen), None)
            if v is not None:
                return v
        return self.graphic_view() or self.text_view() or \
            next((v for v in self.views if v.kind != 'symbol'), self.views[0] if self.views else None)

    def is_default(self, view: View) -> bool:
        d = self.default_view()
        return d is not None and d.name == view.name and d.kind == view.kind

    @property
    def mtime(self) -> float:
        return max((v.mtime for v in self.views), default=0.0)


@dataclass
class Library:
    name: str
    hdl_dirs: list[str] = field(default_factory=list)
    hds_dir: str = ''
    type: str = 'regular'                 # regular | protected | downstream
    include_dirs: list[str] = field(default_factory=list)
    inclusion: str = 'all'
    origin: str = 'user'                  # user | shared
    errors: list[str] = field(default_factory=list)
    units: dict[str, DesignUnit] = field(default_factory=dict)
    files: dict[str, HdlFile] = field(default_factory=dict)
    scanned: bool = False
    default_views: dict[str, str] = field(default_factory=dict)

    def _default_views_path(self) -> str:
        return os.path.join(self.hds_dir, DEFAULT_VIEWS_FILE) if self.hds_dir else ''

    def load_default_views(self) -> None:
        try:
            with open(self._default_views_path(), encoding='utf-8') as f:
                data = json.load(f)
            self.default_views = {k: v for k, v in data.items() if isinstance(v, str)}
        except (OSError, ValueError, AttributeError):
            self.default_views = {}

    def set_default_view(self, unit: str, view: View) -> None:
        """Remember the view opened by default for a design unit (Set Default View)."""
        if not self.writable:
            raise PermissionError(f'library {self.name} is {self.type}')
        if not self.hds_dir:
            raise OSError(f'library {self.name} has no graphics (hds) folder')
        self.default_views[unit] = f'{view.name}|{view.kind}'
        os.makedirs(self.hds_dir, exist_ok=True)
        with open(self._default_views_path(), 'w', encoding='utf-8') as f:
            json.dump(self.default_views, f, indent=1, sort_keys=True)

    @property
    def writable(self) -> bool:
        return self.type == 'regular'

    @property
    def main_hdl_dir(self) -> str:
        return self.hdl_dirs[0] if self.hdl_dirs else ''

    def hdl_files(self) -> list[str]:
        out = []
        for d in self.hdl_dirs:
            if not os.path.isdir(d):
                continue
            for f in sorted(os.listdir(d)):
                p = os.path.join(d, f)
                if os.path.isfile(p) and f.lower().endswith(hdl_extensions() + HEADER_EXTENSIONS):
                    out.append(p)
        return out

    def unparsed_count(self) -> int:
        return sum(1 for f in self.files.values() if f.errors)

    def scan(self, cache: dict[str, HdlFile] | None = None) -> None:
        """(Re)build the design unit list from disk."""
        cache = {} if cache is None else cache
        self.units = {}
        self.files = {}
        for path in self.hdl_files():
            if path.lower().endswith(HEADER_EXTENSIONS):
                continue
            mtime = os.path.getmtime(path)
            parsed = cache.get(path)
            if parsed is None or parsed.mtime != mtime:
                parsed = parse_file(path, self.include_dirs)
                cache[path] = parsed
            self.files[path] = parsed
            for u in parsed.units:
                du = self.units.setdefault(u.name, DesignUnit(u.name, self))
                du.hdl = u
                du.file_errors = parsed.errors
                # the Type column shows what the text describes, as in the legacy Design Explorer
                du.views.append(View(os.path.splitext(os.path.basename(path))[0], 'text',
                                     (u.kind or 'module').capitalize(), path, u.language))
        if self.hds_dir and os.path.isdir(self.hds_dir):
            for unit in sorted(os.listdir(self.hds_dir)):
                udir = os.path.join(self.hds_dir, unit)
                if unit.startswith('.') or not os.path.isdir(udir):
                    continue
                views = _graphic_views(udir)
                if not views:
                    continue
                du = self.units.setdefault(unit, DesignUnit(unit, self))
                du.views = views + du.views
        self.load_default_views()
        self.scanned = True

    def unit_dir(self, unit: str) -> str:
        return os.path.join(self.hds_dir, unit)


def _graphic_views(udir: str) -> list[View]:
    found: dict[tuple[str, str], View] = {}
    for f in sorted(os.listdir(udir)):
        p = os.path.join(udir, f)
        if not os.path.isfile(p) or f.endswith('.lck'):
            continue
        for ext, (kind, label) in VIEW_KINDS.items():
            if f.endswith(ext):
                name = f[:-len(ext)]
                key = (name, kind)
                legacy = not ext.endswith('.json')
                # a view with both an HDS file and this tool's .json: a state diagram is
                # saved back to its .sm (both tools edit the same file), so the one saved
                # last is the view; for other kinds the tool's own .json wins
                if key not in found:
                    found[key] = View(name, kind, label, p, '', legacy)
                elif kind == 'fsm' and found[key].legacy != legacy:
                    if os.path.getmtime(p) > os.path.getmtime(found[key].path):
                        found[key] = View(name, kind, label, p, '', legacy)
                elif found[key].legacy and not legacy:
                    found[key] = View(name, kind, label, p, '', legacy)
                break
    order = {'fsm': 0, 'bd': 0, 'other': 1, 'symbol': 2}
    return sorted(found.values(), key=lambda v: (order.get(v.kind, 3), v.name))


@dataclass
class Project:
    path: str
    hdp: HdpFile
    libraries: list[Library] = field(default_factory=list)
    shared_path: str = ''
    default_library: str = ''
    design_root: str = ''
    errors: list[str] = field(default_factory=list)
    cache: dict[str, HdlFile] = field(default_factory=dict)

    @property
    def dir(self) -> str:
        return os.path.dirname(os.path.abspath(self.path))

    @property
    def name(self) -> str:
        return os.path.splitext(os.path.basename(self.path))[0]

    def library(self, name: str) -> Library | None:
        return next((l for l in self.libraries if l.name == name), None)

    def find_unit(self, name: str, prefer: Library | None = None) -> DesignUnit | None:
        libs = ([prefer] if prefer else []) + [l for l in self.libraries if l is not prefer]
        for lib in libs:
            if not lib.scanned:
                lib.scan(self.cache)
            if name in lib.units:
                return lib.units[name]
        return None

    # -- editing (writes the user .hdp) -------------------------------------------
    def add_library(self, name: str, root: str, lib_type: str = 'regular') -> Library:
        rel = os.path.relpath(root, self.dir).replace('\\', '/')
        base = '$HDS_PROJECT_DIR' if rel == '.' else f'$HDS_PROJECT_DIR/{rel}'
        self.hdp.entries += [('hdl', name, f'{base}/hdl'), ('hds', name, f'{base}/hds'),
                             ('library_type', name, type_to_hdp(lib_type)),
                             ('library_files_inclusion', name, 'all')]
        write_hdp(self.hdp)
        for sub in ('hdl', 'hds'):
            os.makedirs(os.path.join(root, sub), exist_ok=True)
        lib = Library(name, [os.path.join(root, 'hdl')], os.path.join(root, 'hds'), lib_type)
        self.libraries.append(lib)
        return lib

    def design_root_unit(self) -> 'DesignUnit | None':
        """Design unit named by design_root, e.g. "lib.unit(unit)unit/struct.bd" or "lib.unit"."""
        m = re.match(r'\s*([\w$]+)\s*[.\s]\s*([\w$]+)', self.design_root)
        if m is None:
            return self.find_unit(self.design_root.strip()) if self.design_root.strip() else None
        return self.find_unit(m.group(2), prefer=self.library(m.group(1)))

    def set_design_root(self, unit: 'DesignUnit') -> None:
        """Write design_root in the legacy form lib.unit(unit)unit/<view file>."""
        v = unit.default_view()
        tail = f'{unit.name}/{os.path.basename(v.path)}' if v is not None and v.kind != 'text' else ''
        value = f'{unit.library.name}.{unit.name}({unit.name}){tail}'
        self.hdp.entries = [e for e in self.hdp.entries if not (e[0] == 'hds_settings' and e[1] == 'design_root')]
        self.hdp.entries.append(('hds_settings', 'design_root', value))
        write_hdp(self.hdp)
        self.design_root = value

    def set_default_library(self, name: str) -> None:
        self.hdp.entries = [e for e in self.hdp.entries if not (e[0] == 'hds_settings' and e[1] == 'default_library')]
        self.hdp.entries.append(('hds_settings', 'default_library', name))
        write_hdp(self.hdp)
        self.default_library = name


def unit_ports(du: DesignUnit) -> list[tuple[str, str, str]]:
    """(name, mode, bounds) of a design unit's interface, from its HDL or its graphical view."""
    import re
    if du.hdl is not None and du.hdl.ports:
        out = []
        for p in du.hdl.ports:
            m = re.search(r'(\[[^\]]*\])', p.type)
            out.append((p.name, p.direction, m.group(1) if m else ''))
        return out
    g = du.graphic_view()
    if g is not None:
        from .generate import load_view
        try:
            model = load_view(du.library, du, g)
        except Exception:
            return []
        return [(s.name, s.mode, s.bounds) for s in model.signals if s.mode in ('input', 'output', 'inout')]
    return []


def _libraries_from(hdp: HdpFile, origin: str) -> tuple[list[Library], list[str]]:
    pdir = os.path.dirname(os.path.abspath(hdp.path))
    errors = []
    libs = []
    names = []
    for sec in ('hdl', 'hds', 'library_type'):
        for k in hdp.keys(sec):
            if k not in names:
                names.append(k)
    for name in names:
        lib = Library(name, origin=origin)
        for raw in hdp.values('hdl', name):
            p, missing = expand_path(raw, pdir)
            if missing:
                lib.errors.append(f'{name}: variable(s) {", ".join("$" + m for m in missing)} not set in "{raw}"')
            elif not os.path.isdir(p):
                lib.errors.append(f'{name}: HDL directory not found: {p}')
            lib.hdl_dirs.append(p)
        raw = hdp.first('hds', name)
        if raw:
            p, missing = expand_path(raw, pdir)
            if missing:
                lib.errors.append(f'{name}: variable(s) {", ".join("$" + m for m in missing)} not set in "{raw}"')
            lib.hds_dir = p
        lib.type = type_from_hdp(hdp.first('library_type', name, 'regular'))
        for raw in hdp.values('includes_search_path', name):
            p, missing = expand_path(raw, pdir)
            if not missing:
                lib.include_dirs.append(p)
        lib.inclusion = hdp.first('library_files_inclusion', name, 'all')
        errors += lib.errors
        libs.append(lib)
    return libs, errors


def open_project(path: str) -> Project:
    hdp = read_hdp(path)
    proj = Project(path, hdp)
    proj.libraries, proj.errors = _libraries_from(hdp, 'user')
    proj.default_library = hdp.first('hds_settings', 'default_library')
    proj.design_root = hdp.first('hds_settings', 'design_root')
    shared_raw = hdp.first('shared', 'others')
    if shared_raw:
        sp, missing = expand_path(shared_raw, proj.dir)
        if missing:
            proj.errors.append(f'Shared project: variable(s) {", ".join("$" + m for m in missing)} not set')
        elif os.path.exists(sp):
            proj.shared_path = sp
            shared_libs, errs = _libraries_from(read_hdp(sp), 'shared')
            proj.errors += errs
            user_names = {l.name for l in proj.libraries}
            proj.libraries += [l for l in shared_libs if l.name not in user_names]
        else:
            proj.errors.append(f'Shared project file not found: {sp}')
    return proj


def create_project(path: str, default_library: str) -> Project:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    hdp = HdpFile(path, [('hds_settings', 'default_library', default_library), ('hds_settings', 'version', '2')])
    write_hdp(hdp)
    proj = open_project(path)
    proj.add_library(default_library, os.path.join(proj.dir, default_library))
    return open_project(path)
