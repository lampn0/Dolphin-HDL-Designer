# UART made with HDS 2021.1 and with HDL Studio: what differed

HDS project: `examples/uart_hds` (built in the HDS GUI on this machine, top level with the
HDS Tcl API). HDL Studio project: `examples/uart_studio`, built by
`tests/hds_gui/build_uart_studio.py` through HDL Studio's Design Manager and editors. Same design,
same testbench (`examples/uart_hds/tb/tb_uart_top.v`): both pass in Xcelium.

## Generated RTL

After the fixes below the three generated files are the same as HDS's except for layout that
depends on the HDS version / preferences: HDS 2021.1 indents by 3, writes `module x(` without a
space and two spaces after `reg [2:0] bit_cnt;`; HDS 2024.2 (the server, which HDL Studio follows)
does not.

## Fixed in HDL Studio

| Difference | HDS 2021.1 | HDL Studio before |
|---|---|---|
| New block diagram | File > New > Design Content > Block Diagram | disabled ("not editable yet") |
| Language of a new view | asked by the wizard (Verilog 2005, SystemVerilog, ...) | always the preference |
| Generated file name | `<unit>_<view>.v` (`uart_tx_fsm.v`) | the rule could not use the view: `%(view)` added |
| Reset of a new state diagram | `rst`, Reset (Async Low), `!rst` | active high unless named `*_n` |
| Machine of a new state diagram | `csm` | `<unit>_fsm` |
| Scene reload after editing a state | | crashed on stale action boxes (fixed) |
| Name of a new state | template `s0`: smallest free number (`s0`, `s1`, ...; `s0` again once renamed) | `S<n>` counted from the number of states |

## Not changed (noted)

| Difference | HDS 2021.1 | HDL Studio |
|---|---|---|
| New state diagram content | clock `clk`, reset `rst`, recovery point, links to the first state `s0`, title block, directives `` `resetall `` / `` `timescale 1ns/10ps `` | clock / reset from the ports typed in the dialog, transitions straight to `ST_IDLE`, directives from the preferences |
| Signals Table: new output / local | Type `wire` (the generated `output wire tx` assigned in an always block is not legal Verilog until Type is set to `reg`), scheme Comb / Clocked | Type `reg` for outputs |
| HDS console | the Block Diagram API is in namespace `BDAPI::`; dialect `VERILOG_2001` (not `VERILOG_2005`) | no console |
