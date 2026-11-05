"""Set the State Actions of one state of the open HDS state diagram (SM Object Properties).

    python tests/hds_gui/hds_state.py x y "actions"      (\n in the text = new line)

A click on the state (screen pixels), Alt+Enter, the State Actions tab, the text, OK."""
import sys
import time

import pyautogui
from pywinauto import Application, Desktop
from pywinauto.keyboard import send_keys

x, y = int(sys.argv[1]), int(sys.argv[2])
acts = sys.argv[3].replace(chr(92) + 'n', '\r\n')     # a typed "\n" (backslash, n): new line
pyautogui.click(x, y); time.sleep(0.4)
send_keys('%{ENTER}'); time.sleep(1.5)
w = [w for w in Desktop(backend='win32').windows(visible_only=True) if 'SM Object Properties' in w.window_text()]
if not w:
    sys.exit('no properties dialog')
d = Application(backend='uia').connect(handle=w[0].handle).window(handle=w[0].handle)
print(w[0].window_text())
if 'States' not in w[0].window_text():
    [b for b in d.descendants(control_type='Button') if b.window_text() == 'Cancel'][0].click()
    sys.exit('not a state')
tab = [t for t in d.descendants(control_type='TabItem') if t.window_text() == 'State Actions']
if tab:
    tab[0].select(); time.sleep(0.4)
# the actions box: the largest visible multi-line edit
eds = [e for e in d.descendants(control_type='Edit') if e.is_visible()]
box = max(eds, key=lambda e: e.rectangle().height())
box.set_edit_text(acts)
time.sleep(0.3)
[b for b in d.descendants(control_type='Button') if b.window_text() == 'OK'][0].click()
time.sleep(0.8)
