# resources

Files that are not source code.

| Folder | Holds |
|---|---|
| `images/screenshots/` | screenshots of HDLDesigner used by the README and the docs |
| `drawings/` | diagrams of the documentation, as plain SVG (edit them by hand or in Inkscape) |
| `scripts/` | build and packaging scripts: `HDLDesigner.spec` (PyInstaller), `build_windows.ps1`, `build_linux.sh`; `check_docs.py` (docstrings and doc links check) |

Icons of the application are drawn in code (`src/gui/icons.py`, `dm_icons.py`), so there
are no icon files to ship. Do not copy HDS's own bitmaps here: they belong to Siemens EDA.
