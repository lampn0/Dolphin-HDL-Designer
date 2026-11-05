# Developing and maintaining Vietsemi HDL Studio

Everything needed to change the code safely: set-up, layout, conventions, tests, packaging.

## 1. Set-up

Python 3.12 (3.10 or later works) with the packages of `requirements.txt`:

```
python -m venv .venv
.venv\Scripts\activate                 # Windows   (CentOS: source .venv/bin/activate)
pip install -r requirements.txt
```

* **PySide6** (Qt 6) - the user interface.
* **pyslang** - parsing of HDL files (ports, instances) and the syntax check. Without it the
  tool still runs, but the Design Manager only finds unit names in HDL files.

CentOS Stream 9 also needs the Qt xcb libraries:
`sudo dnf install -y libxkbcommon-x11 xcb-util-wm xcb-util-image xcb-util-keysyms xcb-util-renderutil`
(and `xcb-util-cursor` from EPEL when Qt reports "Could not load the Qt platform plugin xcb").

Run from the repository root:

```
python bin/hdlstudio.py [project.hdp] [--new]
python bin/fsm_editor.py [file.sm | file.fsm.json]
```

Projects use environment variables such as `$HDS_TEAM_HOME`: set them as for HDS before
starting the tool.

## 2. Repository layout

The layout follows the HDS installation (`bin`, `docs`, `examples`, `resources`, libraries):

| Folder | Holds |
|---|---|
| `bin/` | launchers: `hdlstudio.py` (Design Manager), `fsm_editor.py`, and shell wrappers |
| `src/` | the application code; top-level modules and sub-packages (see [architecture.md](architecture.md)) |
| `libs/` | HDL libraries shipped with the tool, in the HDS library layout (`<lib>/hdl`, `<lib>/hds`) |
| `resources/` | images (screenshots), drawings (diagrams of the docs), scripts (packaging) |
| `examples/` | example HDS projects (`.hdp` + libraries) to try the tool on |
| `tests/` | unit tests, GUI tests, comparisons with HDS (see `tests/README.md`) |
| `docs/` | requirements, design, file formats, HDS observations, guides |

Not in git (see `.gitignore`): `.venv/`, `build/`, `dist/`, release archives, test output.

## 3. Coding conventions

* **Comments and docstrings in English.** Every module, class and function has a docstring
  saying what it is for (and, for the complex ones, how it works); non-obvious blocks have a
  comment saying why. Keep them true when changing the code.
* **Follow HDS.** When HDS behaves in a particular way, write the behaviour down where it is
  implemented ("as HDS 2021.1 does: ...") and, for anything observed on the real tool, in
  [hds-observations.md](hds-observations.md).
* **Generated text is a contract.** Any change in `codegen/` or `hds/export_*` must keep the
  comparison tests passing (generated HDL identical to HDS's, files written back byte for byte
  when unchanged).
* **No Qt below `gui/`.** The model, readers / writers, generators and project code must stay
  usable from scripts.
* **Preferences are additive.** New fields of `Prefs` / `Session` get defaults so old files
  still load.
* Line length about 110, 4-space indentation, `from __future__ import annotations`.
* `python resources/scripts/check_docs.py` lists any module / class / function without a
  docstring and any broken link in the Markdown files (exit code 1 when there is one).

## 4. Tests

All test commands run from the repository root; see [tests/README.md](../tests/README.md) for
what each covers and the environment variables.

```
python -m unittest discover -s tests          # unit tests (seconds)
python tests/gui/run_all.py                    # GUI tests, real windows: leave mouse and keyboard alone
python tests/hds_compare/compare.py            # generated HDL vs HDS 2024.2 (needs reference/)
python tests/hds_sync/sync_fsm.py              # HDL Studio -> HDS 2021.1 round trips (local HDS)
```

Several tests read a real HDS project (default `D:\workspace\src`, read only) or the sample
files of `DHDS_SAMPLES`; tests that write work on temporary copies.

## 5. Packaging

`resources/scripts/HDLStudio.spec` is the PyInstaller recipe. With PyInstaller installed:

```
powershell -ExecutionPolicy Bypass -File resources\scripts\build_windows.ps1     # Windows
bash resources/scripts/build_linux.sh                                            # CentOS 9
```

Both build `dist/HDLStudio/` and pack it as `dist/HDLStudio-<version>-<os>-x64.zip|tar.gz`
(the version is `__version__` in `src/version.py`).

## 6. Releasing a change

1. Make the change, with docstrings / comments updated.
2. Run the unit tests, and the GUI tests or comparisons of the area you changed.
3. Update `docs/` when behaviour, formats or the roadmap change.
4. Bump `__version__` in `src/version.py` for a release.
