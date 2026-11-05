# examples

Example projects, in the HDS project layout (`<project>.hdp` next to its libraries). Open one
with File > Open Project, or `python bin/hdldesigner.py examples/uart_hds/uart.hdp`.

| Project | What it is |
|---|---|
| `uart_hds/` | a UART made with HDS 2021.1: two state diagrams (`uart_tx`, `uart_rx`, `.sm`), a hand-written `baud_gen.v`, a block diagram `uart_top` (`.bd`) and a testbench (`tb/`). See its README. |
| `uart_dolphin/` | the same UART built again with HDLDesigner by `tests/hds_gui/build_uart_dolphin.py` (views saved as `.fsm.json` / `.bd.json`). Running that script rebuilds this folder. |

Both `.hdp` files name a shared project `$HDS_TEAM_HOME/shared.hdp`; when the variable is not
set the Design Manager only reports it in the Log.

The tests use `uart_hds` as a read-only sample (`tests/gui/gui_fsm_transitions.py`, the round
trip and HDS sync tests); they work on copies and never write into it.
