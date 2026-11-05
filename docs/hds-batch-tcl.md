# Driving HDS 2021.1 from scripts (batch Tcl and GUI)

Notes for the tests that check HDLDesigner against the real HDS installed on the Windows
machine (`C:\MentorGraphics\HDS_2021.1`): `tests/hds_sync/` and `tests/hds_gui/`. Learned the
hard way; keep this up to date.

## Batch mode

```
C:\MentorGraphics\HDS_2021.1\bin\hdldesigner.com -hdpfile X.hdp -user_home H -team_home T -tcl script.tcl
```

* End the script with `exit`. `tests/hds_sync/hds_batch.py` (`run_tcl`) wraps each command in
  a `catch` and returns its result or error.
* Give HDS its own copies of the user / team preference folders (`-user_home`, `-team_home`):
  a batch run must not rewrite the preferences of the HDS the user works with.
* The view name of a state diagram is `fsm.sm` (`::HdsApi::openGraphicalView lib unit fsm.sm`);
  `fsm` alone fails.
* `openGraphicalView` returns a document opened read-only: `$d configure readOnly 0` before
  `::HdsApi::saveGraphicalView lib unit fsm.sm 0 0`. Saving also rewrites `symbol.sb`.
* Integrity check: `[$d model] checkDataIntegrity` returns 1 when the diagram is sound.
  Generation: `::HdsApi::runGenerate lib unit fsm.sm`. Symbol ports: `::SymbolWindow::checkPorts file`.
* Block diagrams can be edited in batch with the `::BDAPI::` commands: `openBDBatch lib unit`,
  `addCmpInst`, `addNet name bounds type`, `connectCmpPortToNet`, `addPortIO mode net`,
  `setCptGenParam`, `addGenParam`, `createEmbeddedBlock`, `enablePortMapFrame`, `saveBDBatch`
  (undocumented), `closeBDBatch`. Only add / connect / set: nothing moves, renames or deletes.
* No Tcl command edits states or transitions; edits on the HDS side of a state diagram need
  the GUI.
* Reference: `C:\MentorGraphics\HDS_2021.1\docs\pdfdocs\hds_tcl_api_ref.pdf` (Block Diagram
  Commands, pages 69-86) and `help\api_help`.

## Settings that differ between HDS versions

* The local HDS 2021.1 uses Options > Verilog > Style tab width 3 and Instance Parameters
  Mapping "Positional"; the server's HDS 2024.2 (and HDLDesigner's defaults) use 2 / "Named".
  Compare outputs with the same style (`codegen.common.set_style`).
* Files saved by HDS 2024.2 cannot be read by 2021.1.

## The HDS window (GUI)

* `hdldesigner.exe` is single-instance: a second launch exits. Only the HDS window the user
  has open can be driven: switch it to a scratch project (File > Open > Project...) and back.
* Never force HDS to the front (Alt key event + ShowWindow + SetForegroundWindow crashed it
  once). `tests/hds_sync/hds_do.py` only clicks on HDS pixels (which gives it the focus) and
  types only while HDS has the focus; run a click and its keys in one call.
* In HDS cell editors Ctrl+A does nothing (use End + Backspace). A double-click on the actions
  text of a state opens SM Object Properties.
