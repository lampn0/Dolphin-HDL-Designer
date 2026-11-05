//-----------------------------------------------------------------------------
//    Module uart_lib.uart_rx.fsm
//    Project: uart
//    Author: lampn0
//    Date: 09:47:50 - 11/03/26
//-----------------------------------------------------------------------------
module uart_rx ( 
  // Port Declarations
  input   wire           baud_tick, 
  input   wire           clk, 
  input   wire           rst, 
  input   wire           rx, 
  output  logic   [7:0]  rx_data, 
  output  logic          rx_valid
);

// Internal Declarations


// Module Declarations
logic [2:0] bit_cnt;
logic [7:0] shift_reg;

// State encoding
typedef enum logic [1:0] {
  IDLE  = 2'd0,
  START = 2'd1,
  DATA  = 2'd2,
  STOP  = 2'd3
} csm_state_t;

csm_state_t current_state, next_state;

//-----------------------------------------------------------------
// Next State Block for machine csm
//-----------------------------------------------------------------
always_comb
begin : next_state_block_proc
  case (current_state) 
    IDLE: begin
      if (!rx)
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
always_comb
begin : output_block_proc
  // Default Assignment
  rx_data = shift_reg;
  rx_valid = 1'b0;

  // Combined Actions
  case (current_state) 
    STOP: begin
      rx_valid = baud_tick & rx;
    end
  endcase
end // Output Block

//-----------------------------------------------------------------
// Clocked Block for machine csm
//-----------------------------------------------------------------
always_ff @(posedge clk or negedge rst)
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
        bit_cnt <= 3'd0;
      end
      DATA: begin
        if (baud_tick) begin
          shift_reg <= {rx, shift_reg[7:1]};
          bit_cnt <= bit_cnt + 3'd1;
        end
      end
    endcase
  end
end // Clocked Block

endmodule // uart_rx
