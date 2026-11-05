"""Reading HDL text: parser.py extracts design units (modules, interfaces, packages, programs),
their ports, parameters and instances from Verilog / SystemVerilog files, using the slang
compiler front end (pyslang) and a regex fallback when pyslang is not installed. It also
syntax-checks editor text (check_text).
"""
