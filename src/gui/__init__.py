"""Qt user interface (PySide6).

Windows:
    design_manager.py   the Design Manager (project tree, libraries, design units, files,
                        hierarchy) - the main window of the application
    main_window.py      the state diagram editor window (canvas from diagram.py)
    bd_editor.py        the block diagram editor window (canvas, items, commands)
    text_editor.py      the HDL text editor (line numbers, find, syntax check)

Shared pieces: menus.py / toolbars.py / command_names.py (HDS command names, shortcuts and
tool tips), context.py (popup menus), undo.py, icons.py / dm_icons.py (icons drawn in code),
dialogs and property panels (dialogs.py, bd_dialogs.py, sm_props_dialog.py,
sm_machine_dialog.py, dm_options.py, main_settings.py, props.py, tables.py).
"""
