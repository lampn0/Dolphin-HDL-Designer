//-----------------------------------------------------------------------------
//    Module uart_lib.uart_tx.fsm
//    Project: uart
//    Author: lampn0
//    Date: 09:04:18 - 11/03/26
//-----------------------------------------------------------------------------
module uart_tx ( 
  // Port Declarations
  input   wire           baud_tick, 
  input   wire           clk, 
  input   wire           rst, 
  input   wire    [7:0]  tx_data, 
  input   wire           tx_start, 
  output  reg            tx, 
  output  reg            tx_busy
);

// Internal Declarations


// Module Declarations
reg [2:0] bit_cnt;
reg [7:0] shift_reg;

// State encoding
parameter 
          IDLE  = 2'd0,
          START = 2'd1,
          DATA  = 2'd2,
          STOP  = 2'd3;

reg [1:0] current_state, next_state;

//-----------------------------------------------------------------
// Next State Block for machine csm
//-----------------------------------------------------------------
always @(
  baud_tick, 
  bit_cnt, 
  current_state, 
  tx_start
)
begin : next_state_block_proc
  case (current_state) 
    IDLE: begin
      if (tx_start)
        next_state = START;
      else
        next_state = IDLE;
    end
    START: begin
      if (baud_tick)
        next_state = DATA;
      else
        next_state = START;
    end
    DATA: begin
      if (baud_tick & (bit_cnt == 3'd7))
        next_state = STOP;
      else
        next_state = DATA;
    end
    STOP: begin
      if (baud_tick)
        next_state = IDLE;
      else
        next_state = STOP;
    end
    default: 
      next_state = IDLE;
  endcase
end // Next State Block

//-----------------------------------------------------------------
// Output Block for machine csm
//-----------------------------------------------------------------
always @(
  current_state, 
  shift_reg
)
begin : output_block_proc
  // Default Assignment
  tx = 1'b1;
  tx_busy = 1'b1;

  // Combined Actions
  case (current_state) 
    IDLE: begin
      tx = 1'b1;
      tx_busy = 1'b0;
    end
    START: begin
      tx = 1'b0;
    end
    DATA: begin
      tx = shift_reg[0];
    end
    STOP: begin
      tx = 1'b1;
    end
  endcase
end // Output Block

//-----------------------------------------------------------------
// Clocked Block for machine csm
//-----------------------------------------------------------------
always @(
  posedge clk, 
  negedge rst
) 
begin : clocked_block_proc
  if (!rst) begin
    current_state <= IDLE;
    // Reset Values
    bit_cnt <= 3'd0;
    shift_reg <= 8'd0;
  end
  else 
  begin
    current_state <= next_state;

    // Combined Actions
    case (current_state) 
      IDLE: begin
        if (tx_start) begin
          shift_reg <= tx_data;
          bit_cnt <= 3'd0;
        end
      end
      DATA: begin
        if (baud_tick) begin
          shift_reg <= shift_reg >> 1;
          bit_cnt <= bit_cnt + 3'd1;
        end
      end
    endcase
  end
end // Clocked Block

endmodule // uart_tx
