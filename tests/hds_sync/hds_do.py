"""Gentle HDS GUI driver: a sequence of real mouse / keyboard steps in one call, so that no
other window takes the focus in between. Nothing forces a window to the front: a click is
made only where the screen shows an HDS window (the window under the point belongs to
hdldesigner.exe), and that click is what brings HDS forward, as for a user; keys are sent only
while HDS has the focus. (Forcing HDS's window to the front with an Alt key event,
ShowWindow and SetForegroundWindow crashed HDS 2021.1 once.)

    python tests/hds_sync/hds_do.py  c 642 253  d 642 253  r 642 253  k "text{ENTER}"  w 0.5  s name 0.6
                                     drag x0 y0 x1 y1

    c / d / r x y   left click / double click / right click at screen pixels
    k "keys"        pywinauto send_keys syntax ({ENTER}, ^s, ...), spaces kept
    w sec           wait
    s name scale    full-screen screenshot -> tests/hds_gui/out/<name>.png
    drag x0 y0 x1 y1
Stops at the first refused step (exit code 2) and says why.
"""
import ctypes
import os
import sys
import time

import pyautogui
from PIL import ImageGrab
from pywinauto.keyboard import send_keys

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'hds_gui', 'out')
user32 = ctypes.windll.user32
pyautogui.FAILSAFE = True
pyautogui.PAUSE = 0.05


def _exe_of(hwnd) -> str:
    """Executable name of the process owning window `hwnd`."""
    pid = ctypes.c_ulong()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    h = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid.value)
    if not h:
        return ''
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = ctypes.c_ulong(1024)
        ctypes.windll.kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size))
        return os.path.basename(buf.value).lower()
    finally:
        ctypes.windll.kernel32.CloseHandle(h)


def _hds_at(x, y) -> bool:
    """True when screen point (x, y) is on an HDS window."""
    hwnd = user32.WindowFromPoint(ctypes.wintypes.POINT(int(x), int(y)))
    return _exe_of(hwnd).startswith('hdldesigner')


def _hds_focused() -> bool:
    """True when HDS has the keyboard focus."""
    return _exe_of(user32.GetForegroundWindow()).startswith('hdldesigner')


def refuse(msg):
    """Stop with exit code 2 and a message (an action that would touch another program)."""
    print('refused:', msg)
    sys.exit(2)


import ctypes.wintypes  # noqa: E402

args = sys.argv[1:]
i = 0
while i < len(args):
    op = args[i]
    if op in ('c', 'd', 'r'):
        x, y = int(args[i + 1]), int(args[i + 2])
        if not _hds_at(x, y):
            refuse(f'({x},{y}) is not on an HDS window')
        {'c': pyautogui.click, 'd': pyautogui.doubleClick, 'r': pyautogui.rightClick}[op](x, y)
        time.sleep(0.25)
        i += 3
    elif op == 'drag':
        x0, y0, x1, y1 = map(int, args[i + 1:i + 5])
        if not _hds_at(x0, y0):
            refuse(f'({x0},{y0}) is not on an HDS window')
        pyautogui.moveTo(x0, y0)
        pyautogui.mouseDown()
        for k in range(1, 11):
            pyautogui.moveTo(x0 + (x1 - x0) * k / 10, y0 + (y1 - y0) * k / 10, duration=0.03)
        pyautogui.mouseUp()
        time.sleep(0.25)
        i += 5
    elif op == 'k':
        if not _hds_focused():
            refuse('HDS does not have the focus: click on it first')
        send_keys(args[i + 1], pause=0.03, with_spaces=True)
        time.sleep(0.2)
        i += 2
    elif op == 'w':
        time.sleep(float(args[i + 1]))
        i += 2
    elif op == 's':
        name = args[i + 1]
        scale = float(args[i + 2])
        img = ImageGrab.grab(all_screens=False)
        if scale != 1:
            img = img.resize((int(img.width * scale), int(img.height * scale)))
        os.makedirs(OUT, exist_ok=True)
        img.save(os.path.join(OUT, name + '.png'))
        print(os.path.join(OUT, name + '.png'))
        i += 3
    else:
        refuse(f'unknown step {op!r}')
