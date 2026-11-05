# Roadmap: state of the work and what is not done yet

Requirement ids (PRJ, GEN, FSM, BD, ...) refer to [requirements.md](requirements.md).
Last reviewed: 2026-11-05.

## Where the tool stands

| Area | State |
|---|---|
| Projects (`.hdp`), libraries, design units, Design Manager panes | working, same file formats as HDS |
| Text editor (DesignPad), slang syntax check | working |
| State diagram editor | working; reads **and writes back** the HDS `.sm` (both tools edit the same file) |
| Block diagram editor | working; reads the HDS `.bd`, **saves as `struct.bd.json`** (no `.bd` write-back yet) |
| Symbols (`.sb`) | ports kept in step with the state diagram's ports when it is saved |
| HDL generation | state machines and block diagrams; on the real project `dti_hbm` all 20 state machines and 45 of 46 block diagrams are identical to what HDS 2024.2 generates (`tests/hds_compare/`) |
| Session restore, autosave / crash recovery, edit locks | working |
| Packaging | PyInstaller recipe for Windows (`resources/scripts/`); CentOS 9 runs from source |

## Open items

### Block diagram
- Write the diagram back to the HDS `.bd` (as `export_sm` does for `.sm`), so HDS can open
  diagrams edited here (BD, VM).
- Add Block, bundles, global connectors, buffer / master / slave ports: menu entries exist,
  greyed out.
- Rotate / flip, align / distribute, appearance of nets, comment graphics, panels.
- Autoroute / Connect By Name / Layout Diagram.
- Copy / paste of nets and ports (only components and frames are copied today).
- `pb_upsize_wdata`: the only diagram of `dti_hbm` where HDS does not declare internal
  signals alphabetically; its order is not reproduced yet.

### State diagram
- Generation styles other than "3 always blocks / case": 1 or 2 always blocks, If / One-Hot,
  output encoded, pragmas (State Machine Properties > Generation is shown greyed).
- Writing back to the `.sm`: hierarchical states added in HDL Studio, added / removed
  concurrent machines, parameter table changes (reported as warnings when saved).
- Copy / paste of diagram objects; Change To; Re-level (add / remove hierarchy).

### Generation and project
- When the language of a view changes, the old `.v` / `.sv` file is not deleted (a warning is
  logged).
- Other view kinds: truth tables, flow charts, ASM charts, IBD (listed greyed in the Design
  Manager).
- ModuleWare: only the basic gates are generated (and, or, xor, inv, buff, assignment...).
- Version management (Git) from the Design Manager (VM).
- Printing (Page Setup is stored, nothing is printed).

### Platform
- Run the full GUI test suite on CentOS Stream 9 (the main target); today it is run on Windows.
- A CentOS 9 package (the PyInstaller recipe works on Linux too; untested).
