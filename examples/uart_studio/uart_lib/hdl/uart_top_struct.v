//-----------------------------------------------------------------------------
//    Module uart_lib.uart_top.struct
//    Project: uart
//    Author: lampn0
//    Date: 09:04:21 - 11/03/26
//-----------------------------------------------------------------------------
module uart_top ( 
  // Port Declarations
  input   wire           clk, 
  input   wire           rst, 
  input   wire           rx, 
  input   wire    [7:0]  tx_data, 
  input   wire           tx_start, 
  output  wire    [7:0]  rx_data, 
  output  wire           rx_valid, 
  output  wire           tx, 
  output  wire           tx_busy
);

// Internal Declarations


// Local declarations

// Internal signal declarations
wire   baud_tick;


// Instances 
baud_gen u_baud( 
  .clk       (clk), 
  .rst_n     (rst), 
  .baud_tick (baud_tick)
); 

uart_rx u_rx( 
  .baud_tick (baud_tick), 
  .clk       (clk), 
  .rst       (rst), 
  .rx        (rx), 
  .rx_data   (rx_data), 
  .rx_valid  (rx_valid)
); 

uart_tx u_tx( 
  .baud_tick (baud_tick), 
  .clk       (clk), 
  .rst       (rst), 
  .tx_data   (tx_data), 
  .tx_start  (tx_start), 
  .tx        (tx), 
  .tx_busy   (tx_busy)
); 


endmodule // uart_top

