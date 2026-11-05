"""Verilog Options Style/Headers/Directives/Packages: python -u vo_test.py <hdp> <cfg> <out>"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _env  # noqa: E402
HDP, CFG, OUT = _env.setup()
from PySide6.QtWidgets import QApplication
app = QApplication(sys.argv)
from dhds.gui.design_manager import DesignManager
from dhds.gui.dm_options import VerilogOptionsDialog
from dhds.gui.context import generation_header
from dhds.project import generate
from dhds.project.templates import new_module
from dhds.model import FsmView
from dhds.bd_model import BlockDiagram

out = OUT
dm = DesignManager(); dm.load_project(HDP)
fails = 0


def check(ok, what):
    global fails
    fails += not ok
    print('PASS' if ok else 'FAIL', what)


vo = VerilogOptionsDialog(dm.prefs, dm, dm.project)
vo.show()
for k in range(vo.tabs.count()):
    vo.tabs.setCurrentIndex(k); app.processEvents()
    vo.grab().save(os.path.join(out, f'vo_{k}.png'))

w = vo.style_widgets
check(not w['blank_before'].isEnabled(), 'Before greyed until blank lines checked')
w['blank_lines'].setChecked(True); check(w['blank_before'].isEnabled(), 'Before enabled with blank lines')
check(not w['label_suffix'].isEnabled(), 'suffix greyed without block label')
w['block_label'].setChecked(True); w['use_suffix'].setChecked(True)
check(w['label_suffix'].isEnabled(), 'suffix enabled with label + use suffix')
check(not w['mw_nonblocking_delay'].isEnabled(), 'non-blocking delay greyed with Blocking')
check(not vo.gen_status.isEnabled(), 'signal status greyed until generation properties')

# packages of a library
names = [vo.lib_list.item(k).text() for k in range(vo.lib_list.count())]
print('libraries:', len(names))
found = None
for n in names:
    vo.lib_list.setCurrentRow(names.index(n))
    if vo.pkg_list.count():
        found = (n, vo.pkg_list.item(0).text()); break
print('first library with packages:', found)
if found:
    vo.pkg_list.setCurrentRow(0)
    check(vo.preview.text() == f'import {found[1]}::*;', 'package preview')
vo.preview.setText('import my_pkg::*;'); vo._add_package()

# apply: tab width 4, a state diagram header, directives
vo.tab_width.setValue(4)
vo.header_type.setCurrentText('State Diagram'); vo.header.setPlainText('// SM %(unit)')
vo.header_type.setCurrentText('Block Diagram')
vo.gen_props.setChecked(True)
vo.directives['pre_module'].setPlainText('`timescale 1ns/1ps')
vo.directives['end_module'].setPlainText('// end')
vo.directives['post_module'].setPlainText('wrong')
check('not a compiler directive' in vo.validate(), 'directive syntax checked')
vo.directives['post_module'].setPlainText('// comment is fine')
check(vo.validate() == '', 'comment lines not checked')
from dhds.gui.dm_options import PragmaSetupDialog
pd = PragmaSetupDialog({})
check(pd.preview.text() == '// pragma synthesis_off', 'pragma preview default')
pd.keyword.setCurrentText('synopsys'); pd.translate.setChecked(True)
check(pd.preview.text() == '// synopsys translate_off', 'pragma preview follows')
pd.show(); app.processEvents(); pd.grab().save(os.path.join(out, 'pragma.png'))
vo.pragma = pd.values()
check(vo.apply(), 'apply')
dm._apply_verilog_options()
p = dm.prefs
check(p.view_headers == {'State Diagram': '// SM %(unit)'}, 'only the changed header is stored')
from dhds.gui import text_editor
check(text_editor.TAB_WIDTH == 4, 'tab width live for text views')
ed = text_editor.CodeEditor(); ed.show()
from PySide6.QtTest import QTest
from PySide6.QtCore import Qt
ed.insertPlainText('a'); QTest.keyClick(ed, Qt.Key_Tab)
check(ed.toPlainText() == 'a   ', 'Tab inserts spaces to the next stop')
fsm = FsmView(library='L', unit='u', view='fsm', language='systemverilog')
h = generation_header(p, 'L', 'u', 'fsm', 'P', fsm)
check(h.startswith('// SM u') and 'Generation properties' in h, 'state diagram header + properties')
h = generation_header(p, 'L', 'u', 'struct', 'P', BlockDiagram())
check(h.startswith(p.header_template[:20]), 'block diagram header falls back to the default')
pre = dm._pre_module('systemverilog')
check(pre == '`timescale 1ns/1ps\nimport my_pkg::*;', 'pre-module + packages for SV')
check(dm._pre_module('verilog') == '`timescale 1ns/1ps', 'no packages for Verilog')
text = new_module('u', [('input', '', 'a')], 'systemverilog', '// h', pre, p.post_module, p.end_module)
lines = text.split('\n')
check(lines[1:4] == ['`timescale 1ns/1ps', 'import my_pkg::*;', 'module u ('], 'directives before module')
check(lines[-3:] == ['endmodule // u', '// end', ''], 'end-module directive after endmodule')
p2 = type(p).load()
check(p2.verilog_style.get('tab_width') == 4 and p2.package_refs.endswith('import my_pkg::*;'), 'saved')
check(p2.pragma.get('keyword') == 'synopsys', 'pragma saved')
dm.resize(900, 700); dm.show(); dm.tabs.setCurrentIndex(0); app.processEvents()
check(dm.left_title.text() == 'Project' and dm.left_pages.currentIndex() == 1, 'Project page with Project tab')
dm.grab().save(os.path.join(out, 'dm_project.png'))
dm.explore(dm.project.library('protocol_controller')); app.processEvents()
check(dm.left_title.text() == 'Main' and dm.left_pages.currentIndex() == 0, 'Main page with a library tab')
check(dm.left_pages.count() == 2, 'no Explore / Tasks pages')
dm.grab().save(os.path.join(out, 'dm_lib.png'))
print('FAILS', fails)
_env.finish(fails)
