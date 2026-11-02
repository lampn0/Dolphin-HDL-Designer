"""User preferences, stored as JSON in ~/.config/dolphin-hds/prefs.json."""
from __future__ import annotations

import getpass
import json
import os
from dataclasses import asdict, dataclass, field, fields
from datetime import datetime

DEFAULT_HEADER = """//-----------------------------------------------------------------------------
//    Module %(library).%(unit).%(view)
//    Project: %(project_name)
//    Author: %(user)
//    Date: %(time) - %(date)
//-----------------------------------------------------------------------------"""


@dataclass
class Prefs:
    default_language: str = 'systemverilog'
    default_state_decl: str = 'parameter'
    default_encoding: str = 'sequential'
    generated_name_rule: str = '%(unit).%(ext)'
    generated_lowercase: bool = True
    header_template: str = DEFAULT_HEADER
    use_external_editor: bool = False
    external_editor: str = 'gvim +{line} {file}'
    recent_projects: list[str] = field(default_factory=list)
    restore_session: bool = True     # reopen the last project and its windows at start-up
    # Options > Main... (Main Settings)
    downcase_names: bool = False                 # General: downcase design unit / view names when entered
    toolbar_remain_active: bool = True           # General: Add commands repeat (else they act once)
    temp_dir: str = '/tmp'
    text_language: str = 'systemverilog'         # General: default language of new text views
    text_extensions: str = 'txt ini tcl dcs edn edf edif'
    autosave_enabled: bool = True                # Save: automatically save recovery file
    autosave_minutes: int = 1                    # Save: every N minutes
    create_backup: bool = False                  # Save: keep <file>.bak when a view is saved
    user_variables: dict[str, str] = field(default_factory=dict)
    # Options > Verilog... (Verilog Options > File)
    verilog_extensions: str = 'v vlg verilog vo sv svh'
    source_ext: str = 'v'                        # Source Verilog (default)
    generated_ext: str = 'v'                     # Generated Verilog
    sv_ext: str = 'sv'                           # System Verilog (default), source and generated
    source_rule: str = '%(module_name).%(ext)'
    source_case: str = 'Preserve case'
    search_path: str = ''
    # File > Page Setup...
    page_setup: dict = field(default_factory=dict)

    @staticmethod
    def path() -> str:
        base = os.environ.get('XDG_CONFIG_HOME') or os.path.join(os.path.expanduser('~'), '.config')
        return os.path.join(base, 'dolphin-hds', 'prefs.json')

    @classmethod
    def load(cls) -> 'Prefs':
        try:
            with open(cls.path(), encoding='utf-8') as f:
                data = json.load(f)
        except (OSError, ValueError):
            return cls()
        names = {f.name for f in fields(cls)}
        return cls(**{k: v for k, v in data.items() if k in names})

    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path()), exist_ok=True)
        with open(self.path(), 'w', encoding='utf-8') as f:
            json.dump(asdict(self), f, indent=2)

    def add_recent(self, path: str) -> None:
        path = os.path.abspath(path)
        self.recent_projects = [path] + [p for p in self.recent_projects if p != path][:9]
        self.save()


def expand_header(template: str, library: str, unit: str, view: str, project_name: str) -> str:
    now = datetime.now()
    values = {
        'library': library, 'unit': unit, 'view': view, 'project_name': project_name,
        'user': getpass.getuser(), 'graphical_source_author': getpass.getuser(),
        'date': now.strftime('%m/%d/%y'), 'graphical_source_date': now.strftime('%m/%d/%y'),
        'time': now.strftime('%H:%M:%S'), 'graphical_source_time': now.strftime('%H:%M:%S'),
        'year': now.strftime('%Y'),
    }
    out = template
    for k, v in values.items():
        out = out.replace(f'%({k})', v)
    return out
