"""The HDS file formats.

    sexpr.py      reader / writer of the S-expression text HDS uses in .sm, .bd, .sb files
    import_sm.py  HDS state diagram (.sm) -> FsmView
    export_sm.py  FsmView -> .sm (writes the edits back into the original file)
    import_bd.py  HDS block diagram (.bd) -> BdView
    export_sb.py  symbol (.sb) writer: the ports of a unit, kept in step with its diagram

docs/hds-file-format.md describes the formats.
"""
