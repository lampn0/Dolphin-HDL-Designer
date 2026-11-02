# Ghi chú định dạng dữ liệu của tool cũ (HDS)

Tài liệu này ghi lại những gì quan sát được từ các file mẫu của project `dti_hbm`. Mục đích là để **import** dữ liệu cũ vào tool mới. Những chỗ còn là phỏng đoán được đánh dấu *(chưa chắc)*.

File mẫu đã phân tích:

| File | Nội dung | Kích thước |
|---|---|---|
| `dti_hbm.hdp` | Project | 83 dòng |
| `protocol_controller/hds/gc_control_fsm/fsm.sm` | State machine `dram_control_fsm` | 26.218 dòng |
| `protocol_controller/hds/gc_control_fsm/symbol.sb` | Symbol (interface) của `gc_control_fsm` | 5.736 dòng |
| `protocol_controller/hds/gc_control_timer/struct.bd` | Block diagram của `gc_control_timer` | 10.829 dòng |
| `protocol_controller/hds/gc_control_fsm/fsm.sm.lck` | Khóa chỉnh sửa | 6 dòng |

---

## 1. Cấu trúc thư mục

```
src/
├── dti_hbm.hdp                 # project chính
├── hdl/  hds/  include/  encrypt/
└── libs/
    └── protocol_controller/
        ├── protocol_controller.hdp   # library cũng có file .hdp riêng
        ├── hdl/                      # source Verilog/SV (.v, .sv)
        └── hds/
            ├── .hdlsidedata/  .xrf/  .cache.dat   # dữ liệu nội bộ, cache
            ├── gc_control_fsm/       # một thư mục cho mỗi design unit
            │   ├── fsm.sm            # view state machine (tên view = "fsm")
            │   ├── fsm.sm.lck        # khóa khi có người đang sửa
            │   └── symbol.sb         # symbol / interface
            └── gc_control_timer/
                ├── struct.bd         # view block diagram (tên view = "struct")
                └── symbol.sb
```

Quy tắc: `hds/<design_unit>/<view>.<ext>`.
- `.sm` = state machine
- `.bd` = block diagram
- `.sb` = symbol
- `.lck` = lock

Design unit có thư mục trong `hds/` được tool hiển thị là **Component**. Design unit chỉ có file trong `hdl/` được hiển thị là **Module**.

## 2. Cú pháp chung (`.sm`, `.bd`, `.sb`)

Định dạng text giống **S-expression**:

```
DocumentHdrVersion "1.1"
Header (DocumentHdr  version 2  language 1  dialect 5  ... )
version "27.1"
appVersion "2020.2 Built on 12 Apr 2020 at 11:28:22"
model (StateMachine | BlockDiag | Symbol
  ...
)
```

- `(TypeName key value key value …)` là một đối tượng. Mỗi `key value` nằm trên một dòng.
- Giá trị có thể là: chuỗi `"..."` (có thể nhiều dòng), số, cặp số `uid 7713,0`, danh sách `[ … ]`, hoặc một đối tượng lồng nhau.
- `*N (Type …)` định nghĩa đối tượng mang **số tham chiếu N**. `&N` là **tham chiếu tới** đối tượng đó. Ví dụ transition dùng `start &6  end &20`.
- `uid a,b` là định danh duy nhất trong file.
- Tọa độ dùng đơn vị nội bộ (khoảng 1/1000 điểm), dạng `xt "x1,y1,x2,y2"` cho hình bao và `pts [ "x,y" … ]` cho đường.
- `VExpander`/`vvMap` lưu giá trị các biến tại lần lưu cuối: đường dẫn tuyệt đối, user, host, ngày giờ. **Khi import phải bỏ qua** vì đường dẫn trỏ tới workspace của người khác (ví dụ `/data6/workspace/huylq0/...`).
- Phần lớn file là thông tin hiển thị: `VaSet` (màu, font), `MRCItem` và `PVME` (kích thước ô bảng). Dữ liệu logic chỉ chiếm phần nhỏ.

### Khai báo tín hiệu (dùng chung)
```
(Decl  n "dram_cmd"  t "reg"  b "[MC_CMD_WIDTH-1:0]"  eolc "DRAM Command Bus"  o 43 )
```
`n` = tên, `t` = kiểu, `b` = bounds, `eolc` = comment cuối dòng, `o` = thứ tự trong khai báo.

`LogicalPort` có `m` là hướng port: không có `m` = input, `m 1` = output, `m 4` = local *(đã khớp với Signals Table trong ảnh chụp. Giá trị của inout chưa gặp)*.

Tín hiệu được gom nhóm bằng `(LGroup name "dram_if" …)`, đây chính là cột *Group* của Signals Table.

## 3. State machine (`.sm`)

| Đối tượng | Số lượng trong mẫu | Ý nghĩa và trường chính |
|---|---|---|
| `Machine` | 1 | `name "dram_control_fsm"`, `stateSignalName "current_state"` |
| `ConcurrentSM` | 1 | Nhóm các máy chạy song song |
| `State` | 23 | `name` (Text), `wait` (text ẩn mặc định `"wait 2"`, **chỉ có hiệu lực khi state là wait state**; mẫu này không có), `encoding`, `actionBlk (SmStateActionsBlock st "…")` = state action |
| `Transition` | 61 | `start &N`, `end &M`, `cond "…"`, `tb (TransitionBlock condition … actions …)`, `tp (TransitionPriority … pr (Text st "2"))` = số ưu tiên |
| `Junction` | 11 | Điểm rẽ nhánh. `st "case"` + `caseExpr "CASE: user_cmd_opcode"` |
| `Link` | 24 | Cờ vàng trỏ tới state theo tên (`st "ST_RUN"`) |
| `SmClockPoint` | 1 | Clock (`clk`, cạnh lên) |
| `SmResetPoint` | 1 | Reset, có `cond (SmControlCondition …)` = `!reset_n` |
| `InterruptPoint` | 1 | **Interrupt**: icon tia sét đỏ-vàng trên sơ đồ |
| `SmRecoveryStatePoint` | 1 | **Recovery state**: hình tròn đỏ có dấu X, state chuyển tới khi FSM rơi vào trạng thái không hợp lệ |
| `LeafLogPort` | 80 | Một dòng của Signals Table: `port (LogicalPort …)`, `scheme` (clocked/comb), `defVal`, reset value |
| `LogGeneric` | 9 | Một dòng của Parameters Table |
| `SmGenChar` | 1 | Tùy chọn sinh code: `casePragma`, `nextStateClocking`, `encoding (Encoding scheme … encodingStyles […])` |

Các khối text khác: State Register Statements, Global Actions (Pre/Post), Module Declarations, Concurrent Statements, Compiler Directives. `includeRefs` liệt kê file `` `include ``.

## 4. Block diagram (`.bd`)

| Đối tượng | Ý nghĩa |
|---|---|
| `Instance` (trong Header) | Danh sách instance: `name`, `duLibraryName`, `duName`, `elements [GiElement name value]` = gán parameter |
| `paramInstances [Parameter name val]` | `localparam` của module |
| `SaComponent` | Hình khối của instance trên sơ đồ, chứa các `CptPort` (port, hướng mũi tên, vị trí) |
| `Net` | Tín hiệu: `decl (Decl …)` |
| `Wire` | Đoạn dây nối, gắn với net và các điểm đầu/cuối |
| `PortIoIn` / `PortIoOut` | Port vào/ra của module trên sơ đồ (hình ngũ giác) |
| `LanguageMgr "Verilog2001LangMgr"` | Ngôn ngữ của view |

Mẫu thứ hai: `pc_global_controller/struct.bd`, 28.531 dòng:

| Đối tượng | Số lượng | Ý nghĩa |
|---|---|---|
| `SaComponent` + `Instance` | 4 + 4 | `gc_final_mux`, `gc_control_timer`, `gc_control_fsm`, `gc_auto_refresh` |
| `EmbeddedInstance` → `HdlText` → `EmbeddedText` | 1 | Embedded block `global_assignments`. Code nằm trong `text (MLText st "…")` |
| `Net` / `Wire` | 112 / 155 | `Wire` có `start &N  end &M` (đối tượng ở hai đầu), nhãn net trong `tg (WTG … st "clk")` |
| `PortIoIn` / `PortIoOut` | 44 / 37 | Port của module |
| `CptPort` | 144 | Port trên các component instance |
| `LogGeneric` | 17 | Parameter |

## 5. Symbol (`.sb`)

- `LogPort` gồm danh sách port, nhóm theo `LGroup`, cùng các cột Group, Name, Mode, Type, Signed, Bounds, Init, Comment.
- `LogGeneric` là parameter. Ví dụ `USER_CMD_WIDTH = `` `CFG_USER_CMD_WIDTH ``.
- `SymbolBody` và `CptPort` là hình vẽ của symbol.

## 6. File khóa (`.lck`)

```
EDIT_LOCK
lampn0                         # user
dti_desver                     # group
dt25-linux                     # host
2300139                        # PID
10/30/26-11:00:51.105832       # thời điểm khóa
```
Đây là cơ chế khóa nhiều người dùng: ai mở view để sửa thì tạo file `.lck`, người khác chỉ được mở ở chế độ chỉ đọc. User guide xác nhận: file `.lck` được tạo khi mở view đồ họa và xóa khi đóng. Nếu view đang bị khóa hoặc chưa đóng đúng cách, tool hỏi người dùng gỡ khóa hay mở chỉ đọc. Mẫu thứ hai `struct.bd.lck` có cùng PID `2300139`, tức một tiến trình có thể giữ nhiều khóa cùng lúc.
