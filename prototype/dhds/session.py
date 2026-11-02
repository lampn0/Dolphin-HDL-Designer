"""The working session, kept between runs in ~/.config/dolphin-hds:

- session.json: the open project, its library tabs and the editor windows
  (with their place on screen), so the tool reopens where the user left off;
- autosave/: unsaved editor contents, written every minute and removed when
  the editor is saved or closed normally, so work survives a crash.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass, field, fields

from .prefs import Prefs


def _dir() -> str:
    return os.path.dirname(Prefs.path())


@dataclass
class EditorState:
    kind: str                   # 'view' (state machine / block diagram) or 'text'
    library: str = ''
    unit: str = ''
    view: str = ''
    path: str = ''              # text files
    geometry: str = ''          # QMainWindow.saveGeometry(), base64
    tab: int = 0                # current tab of a diagram editor
    line: int = 0               # cursor line of a text editor


@dataclass
class Session:
    project: str = ''
    geometry: str = ''          # Design Manager window
    explorers: list[str] = field(default_factory=list)     # library tabs, in order
    current: str = ''           # library tab shown ('' = project page)
    editors: list[EditorState] = field(default_factory=list)
    hierarchies: dict[str, list[list[str]]] = field(default_factory=dict)   # library tab -> extra roots
    saved_at: float = 0.0

    @staticmethod
    def path() -> str:
        return os.path.join(_dir(), 'session.json')

    def save(self) -> None:
        self.saved_at = time.time()
        os.makedirs(_dir(), exist_ok=True)
        tmp = self.path() + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(asdict(self), f, indent=1)
        os.replace(tmp, self.path())        # never leave a half-written session

    @classmethod
    def load(cls) -> 'Session | None':
        try:
            with open(cls.path(), encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError):
            return None
        names = {f.name for f in fields(cls)}
        s = cls(**{k: v for k, v in data.items() if k in names and k != 'editors'})
        enames = {f.name for f in fields(EditorState)}
        for e in data.get('editors') or []:
            if isinstance(e, dict) and e.get('kind'):
                s.editors.append(EditorState(**{k: v for k, v in e.items() if k in enames}))
        return s


# -- autosave of unsaved work ---------------------------------------------------------
def _autosave_file(key: str) -> str:
    h = hashlib.sha1(os.path.normcase(os.path.abspath(key)).encode('utf-8')).hexdigest()[:16]
    return os.path.join(_dir(), 'autosave', h + '.json')


def write_autosave(key: str, kind: str, content: str) -> None:
    path = _autosave_file(key)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump({'key': key, 'kind': kind, 'saved_at': time.time(), 'content': content}, f)
    os.replace(tmp, path)


def read_autosave(key: str) -> dict | None:
    """Unsaved content kept for `key`, or None."""
    try:
        with open(_autosave_file(key), encoding='utf-8') as f:
            data = json.load(f)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) and 'content' in data else None


def drop_autosave(key: str) -> None:
    try:
        os.remove(_autosave_file(key))
    except OSError:
        pass
