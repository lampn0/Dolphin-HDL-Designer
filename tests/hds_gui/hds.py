"""Drive the real HDS (HDL Designer) running on this Windows machine, to study its user
interface and compare HDL Studio against it.

One command per call, so that each step costs little:

    python tests/hds_gui/hds.py windows                 # top-level HDS windows (title, handle, rect)
    python tests/hds_gui/hds.py shot [name] [scale] [x0 y0 x1 y1]
                                                        # screenshot of the HDS main window (or a region
                                                        # of the screen) -> tests/hds_gui/out/<name>.png
    python tests/hds_gui/hds.py menus [title-part]      # menu tree of a window, as text
    python tests/hds_gui/hds.py menu "File->Open..." [title-part]   # pick a menu entry by path
    python tests/hds_gui/hds.py tree [title-part] [depth]           # controls of a window, as text
    python tests/hds_gui/hds.py click x y [right|double]            # mouse click at screen pixels
    python tests/hds_gui/hds.py drag x0 y0 x1 y1                    # mouse drag at screen pixels
    python tests/hds_gui/hds.py keys "^s"               # key strokes (pywinauto send_keys syntax)
    python tests/hds_gui/hds.py focus [title-part]      # bring a window to the front

Screenshots are saved in the workspace (tests/hds_gui/out/), scaled down by default (0.5)
because a full-screen image is expensive to read; pass a region to look at details.
"""
from __future__ import annotations

import os
import sys
import time

import pyautogui
from PIL import ImageGrab
from pywinauto import Application, Desktop
from pywinauto.keyboard import send_keys

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, 'out')
pyautogui.FAILSAFE = True          # moving the mouse to a screen corner stops a running action
pyautogui.PAUSE = 0.05


def _hds_windows():
    """Visible top-level windows of the hdldesigner process."""
    wins = []
    for w in Desktop(backend='win32').windows(visible_only=True):
        try:
            name = os.path.basename(w.process_id() and _exe(w.process_id()) or '')
        except Exception:
            name = ''
        if name.lower().startswith('hdldesigner'):
            wins.append(w)
    return wins


def _exe(pid: int) -> str:
    """Executable name of process `pid` ('' when it cannot be read)."""
    import ctypes
    from ctypes import wintypes
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)    # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return ''
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        ctypes.windll.kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
        return buf.value
    finally:
        ctypes.windll.kernel32.CloseHandle(h)


def _window(part: str | None):
    """The HDS window whose title contains `part` (the largest one when not given)."""
    wins = _hds_windows()
    if part:
        wins = [w for w in wins if part.lower() in w.window_text().lower()]
    if not wins:
        sys.exit(f'no HDS window matching {part!r}')
    return max(wins, key=lambda w: w.rectangle().width() * w.rectangle().height())


def cmd_windows(*_):
    """windows: list the windows of HDS (handle, rectangle, class, title)."""
    for w in _hds_windows():
        r = w.rectangle()
        print(f'{w.handle:>10}  ({r.left},{r.top})-({r.right},{r.bottom})  {w.class_name():24} {w.window_text()}')


def cmd_shot(name='shot', scale='0.5', *region):
    """shot [name] [scale] [x0 y0 x1 y1]: screenshot of the HDS main window, or of a screen
    region, into out/.
    """
    os.makedirs(OUT, exist_ok=True)
    # whole main window: bring it to the front first, other windows (e.g. the Claude app)
    # may cover it; for a region the caller focuses the right window ("focus" command)
    if len(region) != 4:
        try:
            _window(None).set_focus()
            time.sleep(0.3)
        except Exception:
            pass
    if len(region) == 4:
        box = tuple(int(v) for v in region)
    else:
        r = _window(None).rectangle()
        box = (r.left, r.top, r.right, r.bottom)
    img = ImageGrab.grab(bbox=box, all_screens=True)
    s = float(scale)
    if s != 1:
        img = img.resize((max(1, int(img.width * s)), max(1, int(img.height * s))))
    path = os.path.join(OUT, f'{name}.png')
    img.save(path)
    # the scale and origin are needed to turn image pixels back into screen pixels
    print(f'{path}  origin=({box[0]},{box[1]}) scale={s}')


def cmd_menus(part=None):
    """menus [window]: dump the menu bar of an HDS window as an indented text tree."""
    app = Application(backend='win32').connect(handle=_window(part).handle)
    menu = app.window(handle=_window(part).handle).menu()
    if menu is None:
        print('no win32 menu')
        return

    def walk(items, depth):
        """Print the entries of one menu level (and recurse into the sub-menus)."""
        for it in items:
            text = it.text().replace('&', '')
            if not text:
                continue
            state = '' if it.is_enabled() else '  (disabled)'
            print('  ' * depth + text + state)
            sub = it.sub_menu()
            if sub is not None and depth < 3:
                walk(sub.items(), depth + 1)
    walk(menu.items(), 0)


def cmd_menu(path, part=None):
    """menu "File->Save" [window]: pick a menu entry of an HDS window."""
    w = _window(part)
    app = Application(backend='win32').connect(handle=w.handle)
    app.window(handle=w.handle).menu_select(path)


def cmd_tree(part=None, depth='3'):
    """tree [window] [depth]: print the UI Automation control tree of an HDS window."""
    w = _window(part)
    app = Application(backend='uia').connect(handle=w.handle)
    app.window(handle=w.handle).print_control_identifiers(depth=int(depth))


def _owner_exe(hwnd: int) -> str:
    """Executable name of the process owning window `hwnd`."""
    import ctypes
    from ctypes import wintypes
    pid = wintypes.DWORD()
    ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return os.path.basename(_exe(pid.value)).lower()


def ensure_hds(x: int | None = None, y: int | None = None):
    """Refuse to send input unless HDS gets it: the foreground window, and the window under
    (x, y) when given, must belong to hdldesigner. The person may be using the same desktop
    (another application can come to the front at any time); input meant for HDS must never
    reach another program."""
    import ctypes
    from ctypes import wintypes
    u = ctypes.windll.user32
    fg = u.GetForegroundWindow()
    if not _owner_exe(fg).startswith('hdldesigner'):
        sys.exit(f'refused: the foreground window is not HDS ({_owner_exe(fg) or "?"})')
    if x is not None:
        hw = u.WindowFromPoint(wintypes.POINT(int(x), int(y)))
        if not _owner_exe(hw).startswith('hdldesigner'):
            sys.exit(f'refused: ({x}, {y}) is on another program ({_owner_exe(hw) or "?"})')


def cmd_click(x, y, kind='left'):
    """click x y [left|right|...]: click at a screen point, only when it is on an HDS window."""
    x, y = int(x), int(y)
    ensure_hds(x, y)
    if kind == 'right':
        pyautogui.rightClick(x, y)
    elif kind == 'double':
        pyautogui.doubleClick(x, y)
    else:
        pyautogui.click(x, y)


def cmd_drag(x0, y0, x1, y1):
    """drag x0 y0 x1 y1: drag with the left button, only from a point on an HDS window."""
    ensure_hds(x0, y0)
    pyautogui.moveTo(int(x0), int(y0))
    pyautogui.dragTo(int(x1), int(y1), duration=0.4, button='left')


def cmd_keys(keys):
    """keys "...": type keys (pywinauto send_keys syntax), only while HDS has the focus."""
    ensure_hds()
    send_keys(keys, pause=0.02, with_spaces=True)    # spaces are dropped otherwise


def cmd_focus(part=None):
    """focus [window]: give the HDS window the keyboard focus."""
    w = _window(part)
    w.set_focus()
    time.sleep(0.2)


if __name__ == '__main__':
    if len(sys.argv) < 2:
        sys.exit(__doc__)
    globals()['cmd_' + sys.argv[1]](*sys.argv[2:])
