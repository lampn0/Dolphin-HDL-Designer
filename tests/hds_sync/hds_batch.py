"""Run the local HDS 2021.1 in batch mode (no window) on a project, with a Tcl script.

    from hds_batch import run_tcl
    log, out = run_tcl(hdp, ['::HdsApi::runGenerate lib unit fsm', ...])

HDS is started as

    hdldesigner.com -hdpfile <hdp> -user_home <home> -team_home <team> -tcl <script>

with its own copy of your HDS preferences (tests/hds_sync/work/home, team), so a batch run
never changes the preferences of the HDS you use. Each Tcl command of the list is run in a
catch: its result (or error) is written to an output file as one line

    OK|ERR <command> => <result>

which run_tcl returns parsed as a list of (ok, command, result), with HDS's own log text.
The script always ends with `exit` (HDS answers its "Exit?" question itself in batch mode).
"""
from __future__ import annotations

import os
import shutil
import subprocess

HDS_EXE = os.environ.get('DHDS_LOCAL_HDS', r'C:\MentorGraphics\HDS_2021.1\bin\hdldesigner.com')
HERE = os.path.dirname(os.path.abspath(__file__))
WORK = os.path.join(HERE, 'work')
PREFS = os.path.join(os.environ.get('APPDATA', ''), 'HDL Designer Series')


def _homes() -> tuple[str, str]:
    """Copies of the user's HDS user / team preference folders (made once)."""
    home, team = os.path.join(WORK, 'home'), os.path.join(WORK, 'team')
    for src, dst in ((os.path.join(PREFS, 'hds_user'), home), (os.path.join(PREFS, 'hds_team'), team)):
        if not os.path.isdir(dst):
            if os.path.isdir(src):
                shutil.copytree(src, dst)
            else:
                os.makedirs(dst)
    return home, team


def _tcl_quote(s: str) -> str:
    """A string as a Tcl braced word."""
    return '{' + s + '}'


def run_tcl(hdp: str, commands: list[str], timeout: int = 600) -> tuple[str, list[tuple[bool, str, str]]]:
    """Run HDS in batch mode on project `hdp` with the Tcl `commands` (see the module docstring).
    Returns (HDS log text, [(ok, command, result), ...]).
    """
    os.makedirs(WORK, exist_ok=True)
    home, team = _homes()
    out = os.path.join(WORK, 'batch.out').replace('\\', '/')
    script = os.path.join(WORK, 'batch.tcl')
    if os.path.exists(out):
        os.remove(out)
    lines = [f'set __f [open {_tcl_quote(out)} w]',
             'fconfigure $__f -encoding utf-8']
    for c in commands:
        # one line per command: OK / ERR, the command, its result (newlines flattened)
        lines.append(f'if {{[catch {{{c}}} __r]}} {{set __s ERR}} else {{set __s OK}}')
        lines.append(f'puts $__f "$__s {_esc(c)} => [string map {{"\\n" " | "}} $__r]"')
        lines.append('flush $__f')
    lines += ['close $__f', 'exit']
    with open(script, 'w', encoding='utf-8', newline='\n') as f:
        f.write('\n'.join(lines) + '\n')
    p = subprocess.run([HDS_EXE, '-hdpfile', hdp, '-user_home', home, '-team_home', team, '-tcl', script],
                       capture_output=True, text=True, timeout=timeout, errors='replace')
    log = (p.stdout or '') + (p.stderr or '')
    results = []
    if os.path.exists(out):
        for line in open(out, encoding='utf-8', errors='replace'):
            status, _, rest = line.rstrip('\n').partition(' ')
            cmd, _, res = rest.partition(' => ')
            results.append((status == 'OK', cmd, res))
    return log, results


def _esc(s: str) -> str:
    """A command shown inside a Tcl double-quoted string, without being run again."""
    return s.replace('\\', '\\\\').replace('"', '\\"').replace('[', '\\[').replace(']', '\\]').replace('$', '\\$')
