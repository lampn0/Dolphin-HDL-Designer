"""Add one transition in the open HDS state diagram and fill it through SM Object Properties.

    python tests/hds_gui/hds_trans.py x0 y0 x1 y1 "condition" ["actions"]

F7, a click on the source and on the target state (screen pixels), then Esc (closes HDS's
in-place condition box), Alt+Enter (Object Properties of the new, selected transition), and the
condition / actions typed into the dialog's text fields."""
import sys
import time

import pyautogui
from pywinauto import Application, Desktop
from pywinauto.keyboard import send_keys

x0, y0, x1, y1 = (int(v) for v in sys.argv[1:5])
cond = sys.argv[5]
acts = sys.argv[6] if len(sys.argv) > 6 else ''
send_keys('{F7}'); time.sleep(0.3)
pyautogui.click(x0, y0); time.sleep(0.3)
pyautogui.click(x1, y1); time.sleep(0.8)
send_keys('{ESC}'); time.sleep(0.3)
send_keys('%{ENTER}'); time.sleep(1.5)
w = [w for w in Desktop(backend='win32').windows(visible_only=True) if 'SM Object Properties' in w.window_text()]
if not w:
    sys.exit('no properties dialog')
d = Application(backend='uia').connect(handle=w[0].handle).window(handle=w[0].handle)
print(w[0].window_text())
if 'Transitions' not in w[0].window_text():
    # the transition was not made (Alt+Enter showed another object): change nothing
    [b for b in d.descendants(control_type='Button') if b.window_text() == 'Cancel'][0].click()
    sys.exit('no new transition')
eds = sorted(d.descendants(control_type='Edit'), key=lambda c: c.rectangle().top)
eds[0].set_edit_text(cond)
if acts:
    eds[2].set_edit_text(acts.replace(chr(92) + 'n', '\r\n'))     # a typed "\n": new line
time.sleep(0.3)
[b for b in d.descendants(control_type='Button') if b.window_text() == 'OK'][0].click()
time.sleep(0.8)
send_keys('{ESC}')
