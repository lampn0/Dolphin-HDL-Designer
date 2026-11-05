"""Component Browser: the small floating window HDS 2021.1 opens on Add > Component (F3).

It lists the libraries of the project and their design units (the diagram's own library first
and expanded). As in HDS a component is instantiated by dragging a unit onto a block diagram;
the hint at the bottom says so. The drag carries "library/unit" under MIME_TYPE; BdScene
accepts it and the editor places the component where it is dropped.
"""
from __future__ import annotations

from PySide6.QtCore import QMimeData, Qt
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QLabel, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

MIME_TYPE = 'application/x-dolphin-hds-component'
HINT = 'To instance a component, drag onto a diagram.'


class _UnitTree(QTreeWidget):
    """The library / unit tree; a drag of a unit starts a component drag."""

    def startDrag(self, actions):
        it = self.currentItem()
        data = it.data(0, Qt.UserRole) if it is not None else None
        if not data:
            return                              # a library line: nothing to instantiate
        mime = QMimeData()
        mime.setData(MIME_TYPE, f'{data[0]}/{data[1]}'.encode())
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.CopyAction)


class ComponentBrowser(QWidget):
    def __init__(self, project, current_library: str, parent=None):
        # a tool window: stays above its editor, does not take the editor's place
        super().__init__(parent, Qt.Tool)
        self.setWindowTitle('Component Browser')
        self.resize(300, 340)
        self.tree = _UnitTree()
        self.tree.setHeaderHidden(True)
        self.tree.setDragEnabled(True)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.addWidget(self.tree, 1)
        hint = QLabel(HINT)
        hint.setWordWrap(True)
        hint.setStyleSheet('QLabel { background: white; border: 1px solid #a0a0a0; padding: 4px; }')
        lay.addWidget(hint)
        self.fill(project, current_library)

    def fill(self, project, current_library: str):
        self.tree.clear()
        if project is None:
            return
        libs = sorted(project.libraries, key=lambda lib: (lib.name != current_library, lib.name))
        for lib in libs:
            if not lib.scanned:
                lib.scan(project.cache)
            top = QTreeWidgetItem(self.tree, [lib.name])
            for u in sorted(lib.units.values(), key=lambda u: u.name):
                if u.type == 'Package':
                    continue
                it = QTreeWidgetItem(top, [u.name])
                it.setData(0, Qt.UserRole, (lib.name, u.name))
            top.setExpanded(lib.name == current_library)
