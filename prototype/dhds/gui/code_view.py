"""Read-only HDL view with simple Verilog/SystemVerilog highlighting."""
from __future__ import annotations

import re

from PySide6.QtGui import QColor, QFont, QSyntaxHighlighter, QTextCharFormat
from PySide6.QtWidgets import QPlainTextEdit

KEYWORDS = ('module endmodule input output inout wire reg logic parameter localparam typedef enum '
            'always always_comb always_ff begin end if else case casex casez endcase default assign '
            'posedge negedge or signed unique priority').split()


def _fmt(color: str, bold=False, italic=False) -> QTextCharFormat:
    f = QTextCharFormat()
    f.setForeground(QColor(color))
    if bold:
        f.setFontWeight(QFont.Bold)
    f.setFontItalic(italic)
    return f


class VerilogHighlighter(QSyntaxHighlighter):
    RULES = [
        (re.compile(r'\b(' + '|'.join(KEYWORDS) + r')\b'), _fmt('#0000c0', bold=True)),
        (re.compile(r"\b\d+'[bdhoBDHO][0-9a-fA-FxXzZ_]+|\b\d+\b"), _fmt('#a0522d')),
        (re.compile(r'`\w+'), _fmt('#8b008b')),
        (re.compile(r'//[^\n]*'), _fmt('#008000', italic=True)),
    ]

    def highlightBlock(self, text: str):
        for rx, fmt in self.RULES:
            for m in rx.finditer(text):
                self.setFormat(m.start(), m.end() - m.start(), fmt)


class CodeView(QPlainTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont('Courier New', 9))
        self.setLineWrapMode(QPlainTextEdit.NoWrap)
        self.highlighter = VerilogHighlighter(self.document())

    def set_code(self, text: str):
        bar = self.verticalScrollBar()
        pos = bar.value()
        self.setPlainText(text)
        bar.setValue(pos)
