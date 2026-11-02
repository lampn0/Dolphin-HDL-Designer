"""Read and write HDS project files (.hdp) – an INI-like format where a
section may repeat a key (one library with several HDL directories)."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field

LIB_SECTIONS = ('hdl', 'hds', 'includes_search_path', 'library_files_inclusion', 'library_type',
                'protected_library_traversal')
# the type name HDS writes for protected (read-only) libraries
_TYPE_IN = {'regular': 'regular', 'standard': 'protected', 'protected': 'protected',
            'downstream_only': 'downstream', 'downstream': 'downstream'}
_TYPE_OUT = {'regular': 'regular', 'protected': 'standard', 'downstream': 'downstream_only'}


@dataclass
class HdpFile:
    """Raw content: ordered (section, key, value) entries."""
    path: str
    entries: list[tuple[str, str, str]] = field(default_factory=list)

    def values(self, section: str, key: str) -> list[str]:
        return [v for s, k, v in self.entries if s == section and k == key]

    def first(self, section: str, key: str, default: str = '') -> str:
        vals = self.values(section, key)
        return vals[0] if vals else default

    def keys(self, section: str) -> list[str]:
        seen = []
        for s, k, _ in self.entries:
            if s == section and k not in seen:
                seen.append(k)
        return seen

    def sections(self) -> list[str]:
        seen = []
        for s, _, _ in self.entries:
            if s not in seen:
                seen.append(s)
        return seen


def read_hdp(path: str) -> HdpFile:
    hdp = HdpFile(path)
    section = ''
    with open(path, encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(('#', ';')):
                continue
            m = re.fullmatch(r'\[(.+)\]', line)
            if m:
                section = m.group(1).strip()
                continue
            if '=' in line:
                k, v = line.split('=', 1)
                hdp.entries.append((section, k.strip(), v.strip()))
    return hdp


def write_hdp(hdp: HdpFile) -> None:
    lines = []
    for sec in hdp.sections():
        lines.append(f'[{sec}]')
        lines += [f'{k} = {v}' for s, k, v in hdp.entries if s == sec]
    tmp = hdp.path + '.tmp'
    with open(tmp, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')
    os.replace(tmp, hdp.path)


def expand_path(raw: str, project_dir: str, extra: dict[str, str] | None = None) -> tuple[str, list[str]]:
    """Expand $HDS_PROJECT_DIR, $VAR and ${VAR}. Returns (path, names of unset variables)."""
    env = dict(os.environ)
    env['HDS_PROJECT_DIR'] = project_dir
    if extra:
        env.update(extra)
    missing = []

    def sub(m):
        name = m.group(1) or m.group(2)
        if name in env:
            return env[name]
        missing.append(name)
        return m.group(0)
    out = re.sub(r'\$\{(\w+)\}|\$(\w+)', sub, raw)
    if not missing:
        out = os.path.normpath(os.path.join(project_dir, out))
    return out, missing


def type_from_hdp(value: str) -> str:
    return _TYPE_IN.get(value.strip().lower(), 'regular')


def type_to_hdp(value: str) -> str:
    return _TYPE_OUT.get(value, 'regular')
