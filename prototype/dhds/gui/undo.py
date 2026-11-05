"""Snapshot-based undo/redo: the whole model is serialized after each burst
of edits; undo restores the previous snapshot."""
from __future__ import annotations

import json

from PySide6.QtCore import QObject, QSettings, Qt, QTimer, Signal
from PySide6.QtGui import QGuiApplication


class SnapshotUndo(QObject):
    changed = Signal()

    def __init__(self, snapshot, restore, parent=None, delay_ms: int = 400, limit: int = 200):
        super().__init__(parent)
        self._snapshot, self._restore = snapshot, restore
        self._undo: list[str] = []
        self._redo: list[str] = []
        self._limit = limit
        self._restoring = False
        # The snapshot that matches the file on disk (taken when the view is opened and after
        # each save). Undo / redo landing on it means "no unsaved changes", so the editor can
        # drop its '*'. None: no snapshot matches the disk (e.g. recovered unsaved changes).
        self.clean: str | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(delay_ms)
        self._timer.timeout.connect(self._on_timer)

    def reset(self):
        """Start a fresh history from the model as it is now, which is taken as saved."""
        self._timer.stop()
        self._undo, self._redo = [self._snapshot()], []
        self.clean = self._undo[0]
        self.changed.emit()

    def mark_clean(self):
        """The model was just saved: its current state is the one on disk."""
        self.flush()
        self.clean = self._undo[-1] if self._undo else self._snapshot()

    def is_clean(self, snap: str) -> bool:
        """Whether a snapshot (e.g. the one undo just restored) equals the saved state."""
        return self.clean is not None and snap == self.clean

    def note_change(self):
        """Call after every model edit; consecutive edits are merged into one step."""
        if not self._restoring:
            self._timer.start()

    def _on_timer(self):
        # never record the model in the middle of a mouse drag: wait for the release, so one
        # drag is always one undo step even when the machine is slow
        if QGuiApplication.mouseButtons() != Qt.NoButton:
            self._timer.start()
            return
        self._take()

    def _take(self):
        snap = self._snapshot()
        if self._undo and snap == self._undo[-1]:
            return
        self._undo.append(snap)
        del self._undo[:-self._limit]
        self._redo.clear()
        self.changed.emit()

    def flush(self):
        if self._timer.isActive():
            self._timer.stop()
            self._take()

    def undo(self):
        self.flush()
        if len(self._undo) < 2:
            return
        self._redo.append(self._undo.pop())
        self._apply(self._undo[-1])

    def redo(self):
        self.flush()
        if not self._redo:
            return
        snap = self._redo.pop()
        self._undo.append(snap)
        self._apply(snap)

    def _apply(self, snap: str):
        self._restoring = True
        try:
            self._restore(snap)
        finally:
            self._restoring = False
        self.changed.emit()

    def can_undo(self) -> bool:
        return len(self._undo) > 1 or self._timer.isActive()

    def can_redo(self) -> bool:
        return bool(self._redo)


_SETTINGS = ('Dolphin', 'HDS')


def save_view_state(key: str, state: dict) -> None:
    if key:
        QSettings(*_SETTINGS).setValue('viewstate/' + key.replace('\\', '/'), json.dumps(state))


def load_view_state(key: str) -> dict | None:
    if not key:
        return None
    raw = QSettings(*_SETTINGS).value('viewstate/' + key.replace('\\', '/'))
    try:
        return json.loads(raw) if raw else None
    except (TypeError, ValueError):
        return None
