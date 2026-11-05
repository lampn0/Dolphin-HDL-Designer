"""Diff two menu dumps (HDS vs HDL Studio), ignoring the "(disabled)" marks.

    python tests/hds_gui/diff_menus.py tests/hds_gui/ref/bd_menus_hds.txt tests/hds_gui/ref/bd_menus_dolphin.txt
"""
import difflib
import sys


def lines(path):
    """The lines of a menu dump, without the "(disabled)" marks."""
    with open(path, encoding='utf-8', errors='replace') as f:
        return [l.rstrip('\n').replace('  (disabled)', '') for l in f]


for l in difflib.unified_diff(lines(sys.argv[1]), lines(sys.argv[2]), 'hds', 'dolphin', lineterm='', n=0):
    print(l)
