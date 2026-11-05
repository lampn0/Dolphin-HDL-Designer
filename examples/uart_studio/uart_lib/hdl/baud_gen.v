// baud_gen: one-cycle tick every CLK_DIV clock cycles (the UART bit rate)
module baud_gen #(
  parameter CLK_DIV = 16
) (
  input  wire clk,
  input  wire rst_n,
  output reg  baud_tick
);

reg [15:0] cnt;

always @(posedge clk or negedge rst_n) begin
  if (!rst_n) begin
    cnt       <= 16'd0;
    baud_tick <= 1'b0;
  end
  else if (cnt == CLK_DIV - 1) begin
    cnt       <= 16'd0;
    baud_tick <= 1'b1;
  end
  else begin
    cnt       <= cnt + 16'd1;
    baud_tick <= 1'b0;
  end
end

endmodule
