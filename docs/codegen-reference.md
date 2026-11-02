# Tham chiếu sinh code: Verilog (tool cũ) và SystemVerilog (tool mới)

Tài liệu này gồm 3 phần:
1. Phong cách code mà tool cũ đang sinh, rút ra từ 2 file mẫu. Tool mới phải sinh được **y hệt** ở chế độ Verilog.
2. Quy tắc sinh **SystemVerilog**, chế độ mặc định mà người dùng ưu tiên.
3. Cách kiểm tra.

File mẫu:
- `pc_global_controller.v`: sinh từ block diagram `struct`, 333 dòng.
- `gc_control_fsm.v`: sinh từ state machine `fsm`, 1051 dòng.

> Theo *Graphical Editors User Manual* của tool cũ: tool này chỉ hỗ trợ SystemVerilog **ở mức text**. View đồ họa chỉ sinh được Verilog. Khi instantiate component SystemVerilog, kiểu port bị ép về kiểu Verilog-95 (`reg`/`wire`), và các kiểu `enum`, `struct`, port nhiều chiều bị từ chối. Sinh SystemVerilog từ view đồ họa vì vậy là điểm tool mới làm được mà tool cũ không làm được.

---

## 1. Cấu trúc chung (cả block diagram và FSM)

```
<header từ template của view>            // khối comment "//----", có Module lib.unit.view, Author, Date
`include "dti_global_defines.vh"         // Compiler Directives: Pre-module
module <unit> #(
  parameter <NAME> = <value>,            // ANSI-C, căn cột theo tên dài nhất
  ...
)
(
  // Port Declarations
  input   wire    [<bounds>]  <name>,    // <comment>
  ...                                    // input trước, output sau; mỗi nhóm sắp theo alphabet
  output  reg     ...                    // reg nếu tín hiệu được gán trong always
);

`include "dti_global_params.vh"          // Compiler Directives: Post-module
// Internal Declarations
...
endmodule // <unit>                      // End-module directives nằm trước dòng này
```

Quy tắc định dạng:
- Thụt lề 2 dấu cách, theo Tab width = 2 trong preference.
- Cột kiểu, bounds, tên và comment được **căn thẳng hàng**.
- Comment cuối dòng lấy từ cột *Comment* của Signals Table.
- Tên parameter, port, net và instance giữ nguyên chữ hoa/thường như trong sơ đồ.

## 2. Block diagram → Verilog (`pc_global_controller.v`)

| Phần | Nội dung |
|---|---|
| `// Local declarations` | Khai báo thêm của người dùng (để trống trong mẫu) |
| `// Internal signal declarations` | `wire [bounds] name; // comment` cho mọi net nội bộ, sắp theo alphabet |
| `// Instances` | `<component> <instance>( .port (net), … );`. Gán port theo tên (Named), **thứ tự theo symbol của component**. Có gán parameter nếu instance ghi đè |
| `// HDL Embedded Text Block <n> <name>` | Chép nguyên văn code của embedded block |

Port được nối với net khác tên (ví dụ `.t_rfc_done (t_rfc_done_gc)`) là trường hợp thường gặp, cần giữ đúng.

## 3. State machine → Verilog (`gc_control_fsm.v`)

Thứ tự các khối:

| # | Khối | Nội dung |
|---|---|---|
| 1 | `// Declare any pre-registered internal signals` | `reg <name>_cld;` cho mỗi tín hiệu scheme **Clocked** |
| 2 | `// Module Declarations` | Chép nguyên văn phần Module Declarations |
| 3 | `// State encoding` | `parameter ST_A = 5'd0, ST_B = 5'd1, …;` (mã nhị phân tuần tự), `reg [4:0] current_state, next_state;` |
| 4 | **Next State Block** `always @ * begin : next_state_block_proc` | Điều kiện interrupt bọc ngoài cùng: `if (<interrupt>) next_state = <đích>; else case (current_state) …`. Transition kiểu IF thành chuỗi `if / else if` theo priority. Junction CASE thành `case (expr)` lồng bên trong, có `default`. Nhánh `default:` của case ngoài cùng là **recovery state** (`ST_IDLE`) |
| 5 | **Output Block** `always @ * begin : output_block_proc` | `// Default Assignment`: gán giá trị Default cho mọi tín hiệu **Combinatorial**. Sau đó `// Interrupts`, `// Combined Actions`: case theo state, chứa action của state và transition dành cho tín hiệu comb (gán `=`). Các state không có action được gộp vào một nhánh rỗng. Nhánh `default` gán lại giá trị Default |
| 6 | **Clocked Block** `always @(posedge clk, negedge reset_n) begin : clocked_block_proc` | Khi reset: `current_state <= <reset state>` và `// Reset Values` cho mọi tín hiệu Clocked/Registered/local có giá trị Reset. Ngoài reset: `current_state <= next_state;`, interrupt, `// Combined Actions` gán `<=` vào `_cld` và tín hiệu local. Nhánh `default`: giữ nguyên giá trị |
| 7 | `// Concurrent Statements` → `// Clocked output assignments` `always @ * begin : clocked_output_proc` | `<name> = <name>_cld;` cho mỗi tín hiệu Clocked |
| 8 | Concurrent Statements của người dùng | Chép nguyên văn |

Quan sát thêm:
- Clock và reset lấy từ *Clock point* (`posedge clk`) và *Reset point* (`!reset_n`, async, về `ST_IDLE`). Sensitivity list ngăn cách bằng dấu phẩy (theo preference).
- Interrupt `~reg_channel_enable` xuất hiện ở **cả 3 khối**: next state, output và clocked.
- Tên khối `next_state_block_proc`, `output_block_proc`, `clocked_block_proc`, `clocked_output_proc` là cố định.
- Mẫu này không có wait state thật. Trường `wait` của các state chỉ là text ẩn mặc định.

---

## 4. Quy tắc sinh SystemVerilog

Bố cục và thứ tự khối **giữ như Verilog** để dễ so sánh. Chỉ thay đổi các cấu trúc ngôn ngữ:

| Thành phần | Verilog (tool cũ) | SystemVerilog (tool mới) | Có tùy chọn? |
|---|---|---|---|
| Đuôi file | `.v` | `.sv` | Theo PREF-4 |
| Kiểu port | `input wire`, `output reg`, `output wire` | `input logic`, `output logic` | Có thể giữ `wire` cho input |
| Tín hiệu nội bộ | `wire` / `reg` | `logic` | |
| Khai báo state | `parameter ST_X = 5'd0, …` + `reg [4:0] current_state, next_state;` | Một trong ba kiểu, xem bảng ngay dưới | **Người dùng chọn** (GEN-19) |
| Khối tổ hợp | `always @ *` | `always_comb` | |
| Khối tuần tự | `always @(posedge clk, negedge reset_n)` | `always_ff @(posedge clk or negedge reset_n)` | Dấu phẩy hoặc `or` |
| Clocked output assignments | `always @ * begin x = x_cld; … end` | `assign x = x_cld;` hoặc `always_comb` | Có |
| `case` của FSM | `case` | `case`, `unique case` hoặc `priority case` | Mặc định `case`, để giữ nguyên hành vi |
| Gán port instance | `.port (net)` | `.port (net)`. Có thể rút gọn `.port` khi tên trùng, hoặc dùng `.*` | Mặc định viết đầy đủ |
| Parameter | `parameter` trong `#( … )` | Giữ nguyên. Hằng nội bộ dùng `localparam` | |
| Port kiểu SV | Không hỗ trợ | Cho phép `interface`/`modport`, `struct`/`enum` packed, mảng nhiều chiều | |
| Code người dùng (action, embedded block, concurrent statements, declarations) | Chép nguyên văn | **Chép nguyên văn, không tự chuyển đổi** | |

### Kiểu khai báo state (người dùng chọn)

| Kiểu | Verilog | SystemVerilog |
|---|---|---|
| `parameter` (mặc định) | `parameter ST_RUN = 5'd0, …;`<br>`reg [4:0] current_state, next_state;` | `parameter ST_RUN = 5'd0, …;`<br>`logic [4:0] current_state, next_state;` |
| `localparam` | `localparam ST_RUN = 5'd0, …;`<br>`reg [4:0] current_state, next_state;` | `localparam logic [4:0] ST_RUN = 5'd0, …;`<br>`logic [4:0] current_state, next_state;` |
| `enum` | Không dùng được | `typedef enum logic [4:0] {`<br>`  ST_RUN = 5'd0, …`<br>`} dram_control_fsm_state_t;`<br>`dram_control_fsm_state_t current_state, next_state;` |

Ghi chú:
- Giá trị mã hóa luôn ghi tường minh, theo kiểu mã hóa FSMG-4.
- Với `parameter`, state có thể bị ghi đè từ bên ngoài qua `#( … )` nếu đặt trong danh sách parameter của module. Generator luôn đặt state ở phần thân module, như tool cũ.
- Với `enum`, tên kiểu là `<tên_máy>_state_t`. Một module có nhiều máy song song thì mỗi máy có một kiểu riêng.
- Với mã hóa One-Hot dạng chỉ số bit (`current_state[ST_X]`), `enum` không phù hợp. Generator báo lỗi và đề nghị đổi sang `parameter` hoặc `localparam`.

Lưu ý khi sinh SystemVerilog:
- `always_comb` và `always_ff` yêu cầu **mỗi biến chỉ có một khối gán**. Generator phải kiểm tra trước khi sinh và báo lỗi rõ ràng, ví dụ khi một tín hiệu vừa có action trong FSM vừa bị gán trong Concurrent Statements.
- `always_comb` không cho đọc biến trước khi gán trong cùng khối nếu biến đó được gán ở nơi khác. Phần Default Assignment ở đầu Output Block giúp tránh latch.
- Header và compiler directives giữ nguyên như bản Verilog.

## 5. Kiểm tra

1. **Chế độ Verilog**: sinh lại `pc_global_controller.v` và `gc_control_fsm.v` từ file `.bd`/`.sm` đã import. So sánh `diff` với file mẫu, bỏ qua header (header do người dùng tự đặt). Mục tiêu là giống hệt.
2. **Chế độ SystemVerilog**:
   - Parse bằng slang và lint bằng Verilator, không có lỗi.
   - Kiểm tra **tương đương** với bản Verilog bằng một trong hai cách: so sánh hình thức (formal equivalence), hoặc mô phỏng cùng một testbench ngẫu nhiên và so sánh output từng chu kỳ.
3. Đưa 2 file mẫu này vào bộ test hồi quy (golden files) của tool.

## 6. Ghi chú

- **Header** do người dùng tự đặt trong preference (PREF-6). Tool chỉ thay biến và chèn vào đầu file, không quy định nội dung. Khi so sánh với file golden luôn bỏ qua header.
- Code FSM mẫu tương ứng với các thuộc tính: 3 khối always, kiểu Case, phép gán Mixed, mã hóa Sequential, interrupt dạng if-then-else (xem FSMG-1 đến FSMG-6 trong requirements.md). Các tổ hợp thuộc tính khác cần thêm file mẫu để làm golden test.
- Kiểu khai báo state do người dùng chọn (`parameter`, `localparam`, `enum`), mặc định `parameter` (GEN-19).
