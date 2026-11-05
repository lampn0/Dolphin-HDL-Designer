"""Version and product identity of Vietsemi HDL Studio, and a map of src/.

src/ is the top level of the application: bin/ puts it on sys.path, so its modules and
packages are imported by their own names (`from model import FsmView`, `from gui.bd_editor
import BdEditorWindow`). From the bottom layer up:

    model.py, bd_model.py   in-memory data model of a state diagram (FsmView) and of a block
                            diagram (BlockDiagram), with their JSON persistence (.fsm.json / .bd.json)
    hds/                    readers and writers of the HDS file formats (.sm, .bd, .sb, .epf):
                            S-expression parser (sexpr), importers, exporters
    hdl/                    Verilog / SystemVerilog parser (pyslang: ports, parameters, instances)
    codegen/                HDL generation from the data model (FSM and block diagram), with
                            the exact text layout HDS produces
    project/                .hdp projects, libraries, design units, locks, generation records
    prefs.py, session.py    user preferences and the saved working session (~/.config/vietsemi-hdl-studio)
    gui/                    the Qt (PySide6) user interface: Design Manager, editors, dialogs

The launchers in bin/ put src/ on sys.path and start gui.design_manager.DesignManager
(or gui.main_window.MainWindow for the stand-alone FSM editor).
"""

__version__ = '1.0.0'          # shown in Help > About and used in release archive names

# Product identity. Every user-visible name of the tool comes from here.
VENDOR = 'Vietsemi'
VENDOR_URL = 'https://vietsemi.org'
APP_NAME = 'Vietsemi HDL Studio'   # full product name: About boxes, window titles, generated headers
APP_SHORT = 'HDL Studio'           # short form for menus and messages
APP_ID = 'vietsemi-hdl-studio'     # folder of the user configuration (~/.config/<APP_ID>)
LEGACY_APP_ID = 'dolphin-hds'      # configuration folder of the prototype, moved to APP_ID on first run


def about_text(part: str = '') -> str:
    """Text of the Help > About box; `part` names the window it is shown from (e.g. 'Block diagram editor')."""
    head = f'{APP_NAME} {__version__}' + (f' - {part}' if part else '')
    return '\n'.join((
        head,
        'RTL design and verification (testbench, RAL) for Verilog / SystemVerilog.',
        '',
        f'(c) {VENDOR} - {VENDOR_URL}',
        '',
        'HDL Designer Series (HDS) is a product of Siemens EDA. '
        f'{APP_NAME} is independent and not affiliated with Siemens; '
        'it reads and writes HDS project files for compatibility.'))
