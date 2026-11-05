"""Version of HDLDesigner, and a map of src/.

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
    prefs.py, session.py    user preferences and the saved working session (~/.config/dolphin-hds)
    gui/                    the Qt (PySide6) user interface: Design Manager, editors, dialogs

The launchers in bin/ put src/ on sys.path and start gui.design_manager.DesignManager
(or gui.main_window.MainWindow for the stand-alone FSM editor).
"""

__version__ = '1.0.0'          # shown in Help > About and used in release archive names
