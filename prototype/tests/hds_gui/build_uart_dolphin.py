"""Build the UART of D:/workspace/uart_hds (made with HDS 2021.1) again with Dolphin HDS, in
D:/workspace/uart_dolphin, through the Design Manager and the editors, then generate it.

    python tests/hds_gui/build_uart_dolphin.py

Same design as in HDS: uart_tx and uart_rx state machines (IDLE, START, DATA, STOP), the text
module baud_gen, and the block diagram uart_top joining them. Each step uses the command a
user would: New Design Content, Add State / Add Transition clicks on the canvas, the SM Object
Properties dialog for names and actions, the Signals Table rows, the Component Browser drop
and Add Signal for the top level. Run offscreen (QT_QPA_PLATFORM=offscreen) the in-place boxes
get no keyboard focus, so their text is set on the box itself before Enter is pressed.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from PySide6.QtCore import QPointF, Qt, QTimer  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLineEdit  # noqa: E402

PROJECT = 'D:/workspace/uart_dolphin/uart.hdp'
app = QApplication(sys.argv)
from dhds.gui import bd_editor  # noqa: E402
from dhds.gui.design_manager import DesignManager  # noqa: E402
from dhds.gui.dialogs import NewUnitDialog  # noqa: E402
from dhds.gui.sm_props_dialog import SmObjectPropertiesDialog  # noqa: E402
from dhds.model import Signal, State, Transition  # noqa: E402

dm = DesignManager()
# name and extension of generated files as HDS 2021.1 writes them (for this run only, the
# preferences file is not changed)
dm.prefs.generated_name_rule, dm.prefs.generated_ext = '%(unit)_%(view).%(ext)', 'v'
dm.show()
dm.load_project(PROJECT)
from dhds.project import generate as _gen  # noqa: E402
_gen.GENERATED_EXT['verilog'] = 'v'          # the Design Manager copies the extension from the preferences
QTest.qWait(300)


def new_unit(unit: str, kind: str, ports: str):
    """File > New > Design Content, answered like a user would."""
    def answer():
        d = next((w for w in QApplication.topLevelWidgets() if isinstance(w, NewUnitDialog) and w.isVisible()), None)
        if d is None:
            QTimer.singleShot(50, answer)
            return
        d.kind.setCurrentIndex(d.kind.findData(kind))
        d.unit.setText(unit)
        d.language.setCurrentIndex(d.language.findData('verilog'))     # Verilog 2005, as in HDS
        d.ports.setPlainText(ports)
        d.accept()
    QTimer.singleShot(50, answer)
    dm.new_unit()
    QTest.qWait(400)
    return next(w for w in dm.editors.values() if w.isVisible() and f'/{unit}/' in w.windowTitle())


def click(win, x, y):
    vp = win.canvas.viewport()
    win.canvas.centerOn(x, y)
    QTest.mouseClick(vp, Qt.LeftButton, Qt.NoModifier, win.canvas.mapFromScene(QPointF(x, y)))
    QTest.qWait(60)


def props(win, obj, **fields):
    """SM Object Properties of one state / transition, fields typed in and OK."""
    d = SmObjectPropertiesDialog(win.machine, [obj], win)
    if 'name' in fields:
        d.name.setText(fields['name'])
    if 'state_actions' in fields:
        d.action_boxes['in_actions'].setPlainText(fields['state_actions'])
    if 'cond' in fields:
        d.cond.setPlainText(fields['cond'])
    if 'actions' in fields:
        d.actions.setPlainText(fields['actions'])
    assert d.apply(), fields
    win.scene.load(win.view, win.machine)
    win.scene.changed_model.emit()


def fsm(unit, signals, states, transitions):
    win = new_unit(unit, 'fsm', 'input clk\ninput rst')
    m = win.machine
    first = m.states[0]
    props(win, first, name=states[0][0], state_actions=states[0][1])
    # Add State: one click per state, to the right / below the first one (Add State stays on)
    win.set_mode('state')
    for k, (name, acts) in enumerate(states[1:]):
        x, y = first.x + (240 if k < 2 else 0) * (k + 1 if k < 2 else 1), first.y + (200 if k == 2 else 0)
        click(win, x, y)
        props(win, m.states[-1], name=name, state_actions=acts)
    win.set_mode('select')
    by = {s.name: s for s in m.states}
    # Add Transition: source then target; the condition goes in the box that opens at once
    for src, dst, cond, acts in transitions:
        win.set_mode('transition')
        click(win, by[src].x, by[src].y)
        click(win, by[dst].x, by[dst].y)
        ed = next((e for e in win.canvas.viewport().findChildren(QLineEdit) if e.isVisible()), None)
        if ed is not None:
            ed.setText(cond)
            QTest.keyClick(ed, Qt.Key_Return)
            QTest.qWait(50)
        t = m.transitions[-1]
        if acts:
            props(win, t, cond=t.cond, actions=acts)
    win.set_mode('select')
    # Signals Table rows (mode, type, bounds, scheme, default, reset)
    for name, mode, typ, bounds, scheme, default, reset in signals:
        win.view.signals.append(Signal(name, mode, typ, bounds, scheme=scheme, default=default, reset=reset))
    win.signals_tab.set_rows(win.view.signals)
    win.model_changed()
    win.save_file()
    win.generate_hdl()
    QTest.qWait(300)
    return win


fsm('uart_tx',
    [('baud_tick', 'input', 'wire', '', 'none', '', ''),
     ('tx_start', 'input', 'wire', '', 'none', '', ''),
     ('tx_data', 'input', 'wire', '[7:0]', 'none', '', ''),
     ('tx', 'output', 'reg', '', 'comb', "1'b1", ''),
     ('tx_busy', 'output', 'reg', '', 'comb', "1'b1", ''),
     ('shift_reg', 'local', 'reg', '[7:0]', 'clocked', '', "8'd0"),
     ('bit_cnt', 'local', 'reg', '[2:0]', 'clocked', '', "3'd0")],
    [('IDLE', "tx = 1'b1;\ntx_busy = 1'b0;"), ('START', "tx = 1'b0;"),
     ('DATA', "tx = shift_reg[0];\nif (baud_tick) begin\n  shift_reg <= shift_reg >> 1;\n"
              "  bit_cnt <= bit_cnt + 3'd1;\nend"),
     ('STOP', "tx = 1'b1;")],
    [('IDLE', 'START', 'tx_start', "shift_reg <= tx_data;\nbit_cnt <= 3'd0;"),
     ('START', 'DATA', 'baud_tick', ''),
     ('DATA', 'STOP', "baud_tick & (bit_cnt == 3'd7)", ''),
     ('STOP', 'IDLE', 'baud_tick', '')])

fsm('uart_rx',
    [('baud_tick', 'input', 'wire', '', 'none', '', ''),
     ('rx', 'input', 'wire', '', 'none', '', ''),
     ('rx_data', 'output', 'reg', '[7:0]', 'comb', 'shift_reg', ''),
     ('rx_valid', 'output', 'reg', '', 'comb', "1'b0", ''),
     ('shift_reg', 'local', 'reg', '[7:0]', 'clocked', '', "8'd0"),
     ('bit_cnt', 'local', 'reg', '[2:0]', 'clocked', '', "3'd0")],
    [('IDLE', "bit_cnt <= 3'd0;"), ('START', ''),
     ('DATA', "if (baud_tick) begin\n  shift_reg <= {rx, shift_reg[7:1]};\n  bit_cnt <= bit_cnt + 3'd1;\nend"),
     ('STOP', 'rx_valid = baud_tick & rx;')],
    [('IDLE', 'START', '!rx', ''),
     ('START', 'DATA', 'baud_tick', ''),
     ('DATA', 'STOP', "baud_tick & (bit_cnt == 3'd7)", ''),
     ('STOP', 'IDLE', 'baud_tick', '')])

# -- uart_top: a new block diagram, the three components from the Component Browser, nets --
top = new_unit('uart_top', 'bd', '')
G = bd_editor.GRID
for k, unit in enumerate(('baud_gen', 'uart_tx', 'uart_rx')):
    top._component_dropped('uart_lib', unit, QPointF((20 + 30 * k) * G, 40 * G))
insts = {i.unit: i for i in top.bd.instances}
for unit, name in (('baud_gen', 'u_baud'), ('uart_tx', 'u_tx'), ('uart_rx', 'u_rx')):
    insts[unit].name = name


def pin(unit, name):
    i = insts[unit]
    p = next(p for p in i.pins if p.name == name)
    return f'pin:{i.id}:{p.name}', [p.x, p.y]


def wire(a, b, mode='wire'):
    """Add Signal from one component port to another (a net joins them)."""
    top.scene.mode = mode
    (ra, pa), (rb, pb) = a, b
    top.add_wire(ra, rb, pa, [], pb)


wire(pin('baud_gen', 'baud_tick'), pin('uart_tx', 'baud_tick'))
wire(pin('baud_gen', 'baud_tick'), pin('uart_rx', 'baud_tick'))
# Add PortIO (Diagram menu) on the two FSM components: a port for each of their free ports
top.add_port_ios(insts['uart_tx'])
top.add_port_ios(insts['uart_rx'])
# baud_gen's clock and reset join the clk / rst nets of uart_tx (Add Signal, pin to pin)
wire(pin('baud_gen', 'clk'), pin('uart_tx', 'clk'))
wire(pin('baud_gen', 'rst_n'), pin('uart_tx', 'rst'))
top.scene.mode = 'select'
top.save()
top.generate()
QTest.qWait(300)
print('built:', sorted(os.listdir('D:/workspace/uart_dolphin/uart_lib/hdl')))
for w in list(dm.editors.values()):
    w.dirty = False
