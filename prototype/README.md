# Dolphin HDS – prototype v0.2

A working version written in **Python + PySide6 (Qt 6)**. It supports the three core functions: **managing HDL designs, generating code and maintaining code**. It opens `.hdp` projects and the graphics files of the old tool.

## Installing and running

Windows:
```
pip install -r requirements.txt
python run_hds.py                         # Design Manager
python run_hds.py D:/path/dti_hbm.hdp     # open a project directly
```

CentOS Stream 9:
```
sudo dnf install -y python3-pip libxkbcommon-x11 xcb-util-wm xcb-util-image xcb-util-keysyms xcb-util-renderutil
pip3 install --user -r requirements.txt
python3 run_hds.py /path/to/dti_hbm.hdp
```
- If you see the error "Could not load the Qt platform plugin xcb", also install `xcb-util-cursor` (from EPEL).
- A project uses environment variables such as `$HDS_TEAM_HOME` and `$dti_axi_sw`. **Set these variables before running**, as you do for the old tool.

`python run_fsm_editor.py` still opens the standalone FSM editor (no project needed).

## Workflow

| Task | How to do it |
|---|---|
| Open an existing project | File > Open Project (`.hdp`), or File > Recent Projects. Libraries are grouped into Regular/Protected. Errors such as an unset variable or a missing folder are shown in red and in the Log |
| Create a new project | File > New Project: name, location, default library. Creates `<name>/<name>.hdp` and `<lib>/hdl`, `<lib>/hds` |
| Add a library | File > New Library. It is written to the `.hdp` file in the same format as the old tool |
| Browse a library | Double-click a library. You get 3 panes: **Design Units** (Component/Module, language, time stamp, views), **Files** (red = parse error), **Design Hierarchy** (expandable, with generate blocks `FOR : x`; a unit that is not found is shown in red). Select a unit to see the hierarchy below it |
| Create a design unit | File > New Design Content: **State Machine**, **SystemVerilog module** or **Verilog module**, entering the port list |
| Edit an FSM | Double-click the view. Saving writes `hds/<unit>/<view>.fsm.json`. The old tool's `.sm` file is **only read, never written** |
| FSM diagram | Icon toolbar: Save, **Generate (Ctrl+G)**, open generated file, Undo/Redo, then the tools for State/Transition/Junction/Link/Interrupt/Recovery/Reset/Clock. The condition/action box has a **line between the condition and the actions** and can be dragged anywhere. **Drag a transition line** to create a bend point, drag the dot at either end to change where it attaches to the state, double-click a bend point to remove it. The state action box (en/in/ex) can also be dragged. When drawing a new transition, click empty space to add bend points |
| Edit a block diagram | **Drag** a component, embedded block or port (HDS rules): everything attached moves with it — nets, dangling net connectors and the ports at the other end of its nets — except nets going to another component or embedded block, which stretch and stay horizontal/vertical (10-unit grid). Port icons touch their nets. **Nets:** drag a net to move it (ends on pins/ports stay), **Alt+drag** moves one segment, a selected net shows square handles to drag its route points, Shift constrains to horizontal/vertical. **Connect by dragging:** drop a free port on a net connector and it connects and takes the net name; drop a dangling net end on a port (or a free pin) and it connects, the net taking the port name. **Double-click a net** to edit its name in place (`name[7:0]` changes bus bounds); Enter applies, Esc or clicking elsewhere cancels. Net names are shown where the legacy diagram put them. **Right-click a net / port** gives the HDS popup menus (Add Route, Remove Route, Remove All Routes, Add Port I/O, Goto Destination, Disconnect, Highlight Net, Change Style, Show Text, Comments, Object Properties / Change Mode, Show Text, Disconnect, Object Properties; simulation and appearance entries are greyed). Toolbar: **Add Component (C)** (pick a library.unit from the project), **Add Signal (S/F7)** (click a pin/port → click empty space for bends → click a pin/port; double-click empty space to end on a named net connector), **Input/Output Port (I/O)**, **Embedded Block (E)**, Delete, rename a net (double-click the net, or F2 for a dialog). Edit instance parameters and the embedded block code in the Properties panel. **Open Down** (Ctrl+D or double-click an instance) opens the sub-module |
| Right-click in a block diagram | **Component:** Open Down, Cut/Copy/Paste/Delete, **Add Signal Stubs** (a named net on every unconnected pin), **Add PortIO** (a module port for every unconnected pin), Disconnect, Equidistant Ports, **Update Interface** (re-read ports from the HDL), **Generics/Parameters...** and **Object Properties...** (Library / Component / Instance name, parameter list with Add, Add All, Remove, Clear, show parameter values). **Wire/port:** Object Properties (type, signed, vector and array bounds, initial value, delay, expansion, trireg charge strength, comment), Rename. **Empty space:** Paste, Add Component/Port/Embedded block. **Add Component** has a **From HDL file (.v/.sv)** button that reads the ports and parameters straight from a file |
| FSM extras | Each condition/action box and state action box has a **dashed line** to its owner (red when selected). The **priority number** can be dragged along the transition. Closing a modified window asks **Save / Discard / Cancel** |
| Shortcuts (HDS defaults) | Taken from the HDS Graphical Editors manual. Common: **Shift+G** generate, **Ctrl+G** view generated HDL, Ctrl+S, Ctrl+Z/Ctrl+Y, Ctrl+A select all, Del/Backspace, **Alt+Enter** object properties, **F2** edit text/rename, **Home** view all, **Shift+Home** view area, **Shift+Up/Down** zoom, **Ctrl+arrow** move the selection one grid step, **Esc** back to Select. State diagram: **F3/S** state, **Shift+F2/H** hierarchical state, **F4/L** link, **F7/T** transition, **F8/W** wait state, **I** interrupt, **J** junction. Block diagram: **Ctrl+F3/B** block, **F3/C** component, **F4/E** embedded block, **F7/S** signal, **Shift+F7/U** bus, **Ctrl+F7/N** bundle, **F8/I** input port, **F9/O** output port, **F11/T** inout, **F5/G** global connector, **F6 / Shift+F6 / Alt+F6** FOR / IF / ELSE frame, **Ctrl+F10** signal stubs, **Shift+F10** stubs + PortIO, **Shift+Alt+C** disconnect, **Ctrl+D** open down. Commands not built yet are greyed out but keep their keys reserved |
| Commands (HDS behaviour) | Every menu item and toolbar button uses the HDS name, tooltip and status-bar description. **Add commands repeat** until Esc or the **right mouse button**; hold **Ctrl** while choosing one to add a single object. **View Area**: drag a rectangle to view it, then you are back in Select. **Zoom Last** returns to the previous zoom. **Panning**: left-drag moves the diagram until Esc. **Select / Select Text / Select Shapes** (state diagram: text = condition/action boxes). **Generate**: Single, Through Blocks (children in the same library), Through Components (every child with a graphical view), Through Design Root (from `design_root` in the .hdp) |
| Common to both diagrams | **Ctrl+Z / Ctrl+Y** undo/redo, Ctrl+wheel zoom, **Shift+wheel horizontal scroll**, middle mouse to pan. **Each view remembers its zoom and position** when reopened |
| Edit HDL text | Double-click a `.v`/`.sv` file: line numbers, find/replace, go to line, **syntax check with slang (F7)**. Click an error to jump to that line. You can switch to gvim/emacs in Options > Preferences |
| Generate | Ctrl+G in the editor, or select units in the Design Explorer and press Ctrl+G, or right-click a library > Generate whole library. The file goes to the library's `hdl` folder, named by the rule `%(unit).%(ext)` |
| Preferences | Default language (SystemVerilog), state declaration, encoding, file naming rule, **header template**, external editor |

**Session and unsaved work**
- **Reopen where you left off:** starting the tool (`python run_hds.py`) reopens the last project, its library tabs and every editor window (place on screen, current tab, text cursor line). The session is kept in `~/.config/dolphin-hds/session.json` and updated as windows open and close. `python run_hds.py project.hdp` opens that project (with its last windows if it was the last one); `--new` starts empty; Options > Preferences can turn this off.
- **Crash protection:** every 30 s, unsaved diagrams and HDL text are copied to `~/.config/dolphin-hds/autosave/`. The copy is removed when the editor is saved or closed normally. If the tool stopped abnormally, opening the view again asks whether to recover the unsaved changes.

**Protection**
- **Edit lock:** opening a view to edit creates `<file>.lck` in the same format as the old tool. If someone else is editing, you can open it read-only or reset the lock.
- **Overwrite protection:** the tool asks before overwriting an HDL file that was edited by hand or generated by another tool.
- **Protected libraries** are always opened read-only.

## Check against the old tool (tests)
```
python -m unittest discover tests -v        # 14 tests
```
- `gc_control_fsm` (state machine): the generated code matches the old tool's file **character for character**, from `// State encoding` to the end.
- `pc_global_controller` (block diagram): matches **character for character** from `// Internal Declarations` to the end.
- The header and port lists differ only because the sample `.sm`/`.bd` files are a different version from the `.v` files (the `.v` files have an extra `PS_CHAN_NUM`).

Set `DHDS_SAMPLES` to point at the folder holding `fsm.sm`, `struct.bd`, `gc_control_fsm.v` and `pc_global_controller.v` (default `D:/workspace`).

**SystemVerilog declaration rule:** a signal assigned in a procedural block (`always`, FSM actions) is declared `logic`. Anything else (inputs, signals driven by `assign`, nets between instances) is declared `wire`.

## Not done yet (next rounds)
- Block diagram: buses/rippers, generate frames, instance arrays, resizing blocks. Some operations may differ from HDS (screenshots needed).
- Matching the old tool's output across the whole real project: of 88 views that have an existing `.v` file, 7 now match exactly and 12 differ by fewer than 10 lines. Remaining differences: block names in upper case, explicit sensitivity lists, `#(...)` written on one line or positionally, instance arrays, nets with an initial value.
- FSM: 1 or 2 always blocks, If/One-Hot styles, pragmas, wait states, hierarchical states. Undo/redo.
- Writing back to the old tool's `.sm`/`.bd` format. Symbols (`.sb`), truth tables, flow charts, IBD.
- When the language of a view is changed, the old `.v`/`.sv` file is not deleted automatically (only a warning in the Log).
- Git, ModuleWare.

Screenshots are in the `screenshots/` folder.
