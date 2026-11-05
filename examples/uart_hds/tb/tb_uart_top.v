// Loopback test of uart_top: tx is fed back to rx; each byte sent must come back on rx_data
// with rx_valid. The same testbench runs on the HDS and the Dolphin HDS generated RTL.
`timescale 1ns/10ps
module tb_uart_top;
  reg        clk = 1'b0;
  reg        rst = 1'b0;          // active low (HDS default reset)
  reg        tx_start = 1'b0;
  reg  [7:0] tx_data = 8'h00;
  wire       tx, tx_busy, rx_valid;
  wire [7:0] rx_data;
  integer    errors = 0;
  integer    k;
  reg  [7:0] sent [0:2];

  uart_top dut (.clk(clk), .rst(rst), .rx(tx), .tx_data(tx_data), .tx_start(tx_start),
                .rx_data(rx_data), .rx_valid(rx_valid), .tx(tx), .tx_busy(tx_busy));

  always #5 clk = ~clk;

  initial begin
    sent[0] = 8'hA5; sent[1] = 8'h3C; sent[2] = 8'hFF;
    #23 rst = 1'b1;
    for (k = 0; k < 3; k = k + 1) begin
      @(negedge clk);
      wait (!tx_busy);
      @(negedge clk);
      tx_data  = sent[k];
      tx_start = 1'b1;
      @(negedge clk);
      tx_start = 1'b0;
      @(posedge rx_valid);
      @(negedge clk);
      if (rx_data !== sent[k]) begin
        $display("ERROR byte %0d: sent %h received %h", k, sent[k], rx_data);
        errors = errors + 1;
      end
      else
        $display("ok    byte %0d: %h", k, rx_data);
    end
    if (errors == 0) $display("TEST PASSED");
    else             $display("TEST FAILED (%0d errors)", errors);
    $finish;
  end

  initial begin
    #2000000 $display("TEST FAILED (timeout)");
    $finish;
  end
endmodule
