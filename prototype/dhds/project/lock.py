"""Edit locks compatible with the legacy tool: `<view file>.lck` holding
EDIT_LOCK / user / group / host / pid / time."""
from __future__ import annotations

import getpass
import os
import socket
from dataclasses import dataclass
from datetime import datetime


@dataclass
class LockInfo:
    user: str
    group: str
    host: str
    pid: int
    time: str

    def describe(self) -> str:
        return f'{self.user}@{self.host} (pid {self.pid}, since {self.time})'


def lock_path(view_file: str) -> str:
    return view_file + '.lck'


def _group() -> str:
    try:
        import grp  # Linux only
        return grp.getgrgid(os.getgid()).gr_name
    except Exception:
        return ''


def me() -> LockInfo:
    now = datetime.now()
    return LockInfo(getpass.getuser(), _group(), socket.gethostname(), os.getpid(),
                    now.strftime('%m/%d/%y-%H:%M:%S.') + f'{now.microsecond:06d}')


def read_lock(view_file: str) -> LockInfo | None:
    p = lock_path(view_file)
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding='utf-8', errors='replace') as f:
            lines = [l.rstrip('\n') for l in f]
    except OSError:
        return None
    if not lines or lines[0] != 'EDIT_LOCK':
        return None
    lines += [''] * 6
    pid = int(lines[4]) if lines[4].strip().isdigit() else 0
    return LockInfo(lines[1], lines[2], lines[3], pid, lines[5])


def is_mine(info: LockInfo) -> bool:
    m = me()
    return info.user == m.user and info.host == m.host and info.pid == m.pid


def _pid_running(pid: int) -> bool:
    if os.name == 'nt':
        # os.kill() on Windows terminates the process, so ask the OS instead
        import ctypes
        PROCESS_QUERY_LIMITED_INFORMATION, STILL_ACTIVE = 0x1000, 259
        k32 = ctypes.windll.kernel32
        h = k32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return False
        code = ctypes.c_ulong()
        ok = k32.GetExitCodeProcess(h, ctypes.byref(code))
        k32.CloseHandle(h)
        return bool(ok) and code.value == STILL_ACTIVE
    try:
        os.kill(pid, 0)          # signal 0: existence check only
    except ProcessLookupError:
        return False
    except OSError:
        return True              # exists but belongs to another user
    return True


def is_stale(info: LockInfo) -> bool:
    """True when the lock was taken on this host by a process that no longer runs."""
    if info.host != socket.gethostname() or info.pid <= 0:
        return False
    return not _pid_running(info.pid)


def acquire(view_file: str, force: bool = False) -> tuple[bool, LockInfo | None]:
    """Take the lock. Returns (ok, current holder if someone else has it)."""
    cur = read_lock(view_file)
    if cur is not None and not is_mine(cur) and not force:
        return False, cur
    m = me()
    try:
        with open(lock_path(view_file), 'w', encoding='utf-8', newline='\n') as f:
            f.write(f'EDIT_LOCK\n{m.user}\n{m.group}\n{m.host}\n{m.pid}\n{m.time}\n')
    except OSError:
        return False, cur
    return True, None


def release(view_file: str) -> None:
    cur = read_lock(view_file)
    if cur is not None and is_mine(cur):
        try:
            os.remove(lock_path(view_file))
        except OSError:
            pass
