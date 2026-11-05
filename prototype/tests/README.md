# Tests

Run everything from the `prototype/` folder.

| Kind | Command | What it checks | Needs |
|---|---|---|---|
| Unit tests | `python -m unittest discover -s tests` | projects, libraries, locks, FSM and block diagram generation | nothing |
| GUI tests | `python tests/gui/run_all.py` | the real application through the Design Manager and the editors, driven with real mouse and keyboard input | a display, the real project |
| Generation regression | `python tests/regress_hds_generation.py` | the HDL generated for every block diagram and state machine of a real project against the HDL files kept in that project | the real project |
| HDS comparison | `python tests/hds_compare/compare.py [fsm\|bd] [name]` | the HDL generated for every view against the HDL that HDS 2024.2 itself generates from the same diagrams | `tests/hds_compare/reference/` (made by `hds_reference.py`) |

## GUI tests (`tests/gui/`)

Each `gui_*.py` file opens the application with visible windows, works on it with mouse clicks,
drags and key presses, and prints one `PASS` or `FAIL` line per check. **Leave the mouse and
keyboard alone while they run** (about 3 minutes for all of them).

```
python tests/gui/run_all.py                    # all GUI tests, with a summary
python tests/gui/run_all.py bd_suite session    # only the files whose name contains one of these
python tests/gui/gui_bd_suite.py                # one file on its own
```

`_env.py` gives every test a temporary copy of part of a real HDS project (the `dynamo_core`
block diagram and the whole `protocol_controller` library) and its own configuration folder, so
a test never writes into the real project or into your preferences. Screenshots go to
`tests/gui/out/` (not in git).

A test never waits for a person: a dialog left open more than 20 seconds (a lock question, an
error box) is closed and reported as a `FAIL` line, and `run_all.py` stops a test after 5 minutes.
Lock files a test leaves (some tests simulate a crash) stay in its temporary copy, which
`run_all.py` deletes.

| Variable | Default | Meaning |
|---|---|---|
| `DHDS_TEST_SRC` | `D:\workspace\src` | the real project folder copied from (only read) |
| `DHDS_TEST_OUT` | `tests/gui/out` | where screenshots go |
| `DHDS_TEST_TMP` | a new temporary folder | where the project copy and config go (`run_all.py` makes and deletes one per test) |

| File | Covers |
|---|---|
| `gui_bd_suite.py` | Block diagram editing as in HDS: nets and buses (default names `sig0`/`dbus0`, two-click drawing, joining a net, name placement, Change Style, in-place edit, undo, "with a Port"), ports (preview, auto-connection by the port's wire end, unnamed free ports, Change Mode, inout), components (preview, placement, nets from component ports, moving), embedded blocks (Create Embedded View, Text view move/resize, input/output by net direction, Change Mode), save/reload and generated HDL |
| `gui_bd_add_items.py` | Port preview and attach, new embedded block and its Text view, a net to the block |
| `gui_bd_component_name.py` | Component name lines: select, drag, double-click edit; undo clears the title `*` |
| `gui_bd_name_text.py` | The same on the legacy `dynamo_core` diagram, outside the Design Manager |
| `gui_bd_inline_edit.py` | In-place edit of nets and ports (`name : type[bounds]`), dragging a net name |
| `gui_bd_embedded_nets.py` | Dragging nets attached to an embedded block (the block stays) |
| `gui_bd_embedded_drag.py` | Sliding a net end along an embedded block edge |
| `gui_bd_comp_to_comp.py` | A net between two components |
| `gui_bd_connect.py` | Ports follow components, connection by dragging, popup menus |
| `gui_bd_net_ops.py` | Moving components and nets, Alt+drag of a segment, in-place rename |
| `gui_bd_pin_drag.py`, `gui_bd_pin_move.py`, `gui_bd_pin_net_drag.py` | Moving component ports and their nets |
| `gui_bd_grid.py`, `gui_bd_handles.py` | Grid snapping, handle sizes |
| `gui_bd_frames.py`, `gui_bd_frame_props.py` | Generate frames |
| `gui_bd_component_props.py`, `gui_bd_params.py` | Component popup menus, Object Properties, parameters |
| `gui_bd_route_modes.py` | PortIO drag routing modes |
| `gui_canvas_ops.py` | Zoom, pan, view area and other canvas operations of both editors |
| `gui_dm_menu_states.py` | Design Manager menus: which entries are enabled for each selection |
| `gui_dm_units.py` | Design unit list, default views, double-click |
| `gui_dm_hierarchy.py` | Design Hierarchy pane (two runs: the hierarchy kept by the session) |
| `gui_dm_session.py` | Session restore and crash recovery (three runs) |
| `gui_dm_verilog_options.py` | Options > Verilog dialog and its effect |
| `gui_fsm_transitions.py` | State diagram transitions: boxes, route points, leaders, declaration blocks |
| `gui_fsm_save_sm.py fsm.sm [--keep]` | Editor save back to the HDS `.sm`: a state dragged by the mouse, a condition changed, File > Save, the file read again (on a copy unless `--keep`) |

## Driving the real HDS (`tests/hds_gui/`)

Tools to study the user interface of the HDS installed on this Windows machine (HDS 2021.1, on
the sample project `D:/workspace/hds_reference`) and compare Dolphin HDS with it. One short
command per step; screenshots go to `tests/hds_gui/out/` (not in git), reference dumps to
`tests/hds_gui/ref/`.

| Script | Does |
|---|---|
| `hds.py` | list HDS windows, screenshot a window or region, dump a menu bar as text, pick a menu entry, click / drag / type. See its docstring. |
| `dolphin_menus.py` | dump a Dolphin editor's menus in the same text format |
| `diff_menus.py` | diff two menu dumps (HDS vs Dolphin) |
| `dolphin_shot.py`, `dolphin_net_shot.py`, `dolphin_port_shot.py` | the same views / actions in Dolphin, for side-by-side screenshots |
| `dolphin_fsm_region.py fsm.sm name x0 y0 x1 y1 [px/unit]` | a region of a state diagram (HDS units) as Dolphin draws it, to put next to an HDS screenshot |

Behaviour read from HDS 2021.1 this way (and now followed by Dolphin): the block diagram menus;
the window layout (Diagram Browser with the Structure Navigator on the right, one page at a
time, "Ready" in the status bar, the view saved in the diagram); net drawing (a click in open
space adds a corner, a double-click ends, a click on an object ends and connects; the new net is
selected, its name 2000 units from the start); a net name selected on its own; Add Port and Add
Embedded Block (outline preview, cursor on the port's wire end / the block's bottom-left corner,
the new object selected, the command stays active).

## Generation regression

`regress_hds_generation.py` opens the whole project (read only), generates every graphical view in
memory and compares the body (from `// Internal Declarations` or `// State encoding`) with the
HDL file kept in the project. Those files were written by an older HDS with other options (for
example `always @ *`), so many differences are expected: the HDS comparison below is the reference.

## HDS comparison (`tests/hds_compare/`)

Compares Dolphin HDS with what HDS 2024.2 really generates today, with the same diagrams and
the same user settings.

1. `python tests/hds_compare/hds_reference.py` copies the project to `/tmp/dolphin_hds_check` on
   the Linux server where HDS is installed (the real project is only read), runs HDS in batch
   mode to generate every library, and downloads the result to `tests/hds_compare/reference/`.
   The docstring of the script lists the settings (host, project, HDS home, license, ssh key).
2. `python tests/hds_compare/compare.py` generates every view with Dolphin in memory and writes
   `results/report.md` (one line per view) and `results/diffs/<lib>.<unit>.diff` (HDS = `-`,
   Dolphin = `+`) for each view that differs.

`reference/` and `results/` hold the project's design content and are not in git.

Reading and writing `.sm` files (both tools edit the same file):

| Script | Checks |
|---|---|
| `roundtrip_files.py` | every .sm / .bd / .sb parsed and written back is byte for byte the same |
| `fsm_geometry.py fsm.sm ...` | Dolphin draws each state, action block, transition box and priority circle where the HDS file has it (within 30 HDS units) |
| `sm_write.py [root ...]` | `export_sm`: every .sm written back unchanged is identical; edits (move, rename, condition, actions, delete) and new objects (states with actions, junction, link, transitions) are read back; a second save changes nothing |

The files written by `export_sm` were opened in HDS 2021.1 (gc_control_fsm): moved / renamed
objects, changed texts and added objects show as written.
State of `dti_hbm`: all 20 state machines and 45 of 46 block diagrams identical to HDS. The one
left, `pb_upsize_wdata`, is the only diagram where HDS does not declare the internal signals in
alphabetical order (`survey_decl_order.py` and `survey_instance_order.py` survey these orders).
HDS writes 6 other files empty: it refuses to generate a diagram whose component instances are
out of date with their symbols ("Use Update Interface"), so there is nothing to compare there.
