# UART (HDS 2021.1 project)

Open `uart.hdp` in HDL Designer. Library `uart_lib`:

| Unit | View | Made with | Generated RTL |
|---|---|---|---|
| `uart_tx` | state diagram `hds/uart_tx/fsm.sm` | HDS editor: states, transitions, SM Object Properties, Signals Table | `hdl/uart_tx_fsm.v` |
| `uart_rx` | state diagram `hds/uart_rx/fsm.sm` | same | `hdl/uart_rx_fsm.v` |
| `baud_gen` | Verilog text `hdl/baud_gen.v` | written by hand | (source) |
| `uart_top` | block diagram `hds/uart_top/struct.bd` | HDS Tcl API in the HDS console (`make_top.tcl`, `BDAPI::` commands) | `hdl/uart_top_struct.v` |

Design: 8 data bits, no parity, 1 stop bit, LSB first. `baud_gen` gives one `baud_tick` every
`CLK_DIV` (16) clocks; `rst` is active low.

- `uart_tx`: IDLE (`tx = 1`, not busy) -> START on `tx_start` (loads `shift_reg`, clears `bit_cnt`),
  `tx = 0` -> DATA on `baud_tick`, `tx = shift_reg[0]`, shifts on each tick -> STOP after 8 bits,
  `tx = 1` -> IDLE on `baud_tick`.
- `uart_rx`: IDLE -> START on `!rx` -> DATA on `baud_tick`, shifts `rx` in on each tick -> STOP after
  8 bits; in STOP `rx_valid = baud_tick & rx`; `rx_data = shift_reg`.

Test: `tb/tb_uart_top.v` loops `tx` back to `rx` and sends A5, 3C, FF. It passes with Xcelium
23.03 (`xrun -sv -timescale 1ns/10ps uart_lib/hdl/*.v tb/tb_uart_top.v -top tb_uart_top`), on this
RTL and on the RTL Dolphin HDS generates for the same design (`examples/uart_dolphin`).
