# uart_top block diagram, built with the HDS Tcl API (Block Diagram commands) in the running HDS (namespace BDAPI at the console):
# baud_gen + uart_tx + uart_rx sharing clk / rst and the baud tick.
BDAPI::createBD uart_lib uart_top VERILOG_2001

BDAPI::addCmpInst u_baud uart_lib baud_gen
BDAPI::addCmpInst u_tx   uart_lib uart_tx
BDAPI::addCmpInst u_rx   uart_lib uart_rx

BDAPI::addNet clk       "" wire
BDAPI::addNet rst       "" wire
BDAPI::addNet baud_tick "" wire
BDAPI::addNet tx_start  "" wire
BDAPI::addNet tx_data   "\[7:0\]" wire
BDAPI::addNet tx        "" wire
BDAPI::addNet tx_busy   "" wire
BDAPI::addNet rx        "" wire
BDAPI::addNet rx_data   "\[7:0\]" wire
BDAPI::addNet rx_valid  "" wire

BDAPI::connectCmpPortToNet u_baud clk       clk
BDAPI::connectCmpPortToNet u_baud rst_n     rst
BDAPI::connectCmpPortToNet u_baud baud_tick baud_tick

BDAPI::connectCmpPortToNet u_tx clk       clk
BDAPI::connectCmpPortToNet u_tx rst       rst
BDAPI::connectCmpPortToNet u_tx baud_tick baud_tick
BDAPI::connectCmpPortToNet u_tx tx_start  tx_start
BDAPI::connectCmpPortToNet u_tx tx_data   tx_data
BDAPI::connectCmpPortToNet u_tx tx        tx
BDAPI::connectCmpPortToNet u_tx tx_busy   tx_busy

BDAPI::connectCmpPortToNet u_rx clk       clk
BDAPI::connectCmpPortToNet u_rx rst       rst
BDAPI::connectCmpPortToNet u_rx baud_tick baud_tick
BDAPI::connectCmpPortToNet u_rx rx        rx
BDAPI::connectCmpPortToNet u_rx rx_data   rx_data
BDAPI::connectCmpPortToNet u_rx rx_valid  rx_valid

BDAPI::addPortIO in  clk
BDAPI::addPortIO in  rst
BDAPI::addPortIO in  tx_start
BDAPI::addPortIO in  tx_data
BDAPI::addPortIO out tx
BDAPI::addPortIO out tx_busy
BDAPI::addPortIO in  rx
BDAPI::addPortIO out rx_data
BDAPI::addPortIO out rx_valid

BDAPI::layoutDiagram
BDAPI::save
