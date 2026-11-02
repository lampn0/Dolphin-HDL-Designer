"""Reader for the S-expression text format used by legacy HDS graphics files
(.sm state machines, .bd block diagrams, .sb symbols).

Format summary (see docs/hds-file-format.md):
    (TypeName key value key value ...)
values are strings, numbers, "a,b" pairs, [lists], nested objects,
`*N (obj)` labelled objects and `&N` references to them.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterator

_TOKEN_RE = re.compile(
    r'''
    (?P<ws>\s+)
  | (?P<str>"(?:[^"\\]|\\.)*")
  | (?P<label>\*\d+)
  | (?P<ref>&\d+)
  | (?P<lparen>\()
  | (?P<rparen>\))
  | (?P<lbrack>\[)
  | (?P<rbrack>\])
  | (?P<atom>[^\s()\[\]"]+)
    ''',
    re.VERBOSE | re.DOTALL,
)


@dataclass
class Ref:
    """Reference `&N` to a labelled object."""
    label: int


@dataclass
class Node:
    """One `(TypeName key value ...)` object."""
    type: str
    fields: list[tuple[str, Any]] = field(default_factory=list)
    label: int | None = None

    def get(self, key: str, default: Any = None) -> Any:
        for k, v in self.fields:
            if k == key:
                return v
        return default

    def get_all(self, key: str) -> list[Any]:
        return [v for k, v in self.fields if k == key]

    def __repr__(self) -> str:
        lab = f"*{self.label} " if self.label is not None else ""
        return f"{lab}({self.type} …{len(self.fields)} fields)"


@dataclass
class Document:
    """A parsed file: top-level key/value pairs plus the label table."""
    fields: list[tuple[str, Any]]
    labels: dict[int, Node]

    def get(self, key: str, default: Any = None) -> Any:
        for k, v in self.fields:
            if k == key:
                return v
        return default

    def resolve(self, value: Any) -> Any:
        if isinstance(value, Ref):
            return self.labels.get(value.label)
        return value

    def walk(self) -> Iterator[Node]:
        """Yield every Node in document order (depth first)."""
        stack: list[Any] = [v for _, v in reversed(self.fields)]
        while stack:
            v = stack.pop()
            if isinstance(v, Node):
                yield v
                stack.extend(val for _, val in reversed(v.fields))
            elif isinstance(v, list):
                stack.extend(reversed(v))


class ParseError(ValueError):
    pass


def _unescape(s: str) -> str:
    return re.sub(r'\\(.)', r'\1', s[1:-1])


def _convert_atom(text: str) -> Any:
    if re.fullmatch(r'-?\d+', text):
        return int(text)
    return text


class _Parser:
    def __init__(self, text: str):
        self.tokens = [(m.lastgroup, m.group()) for m in _TOKEN_RE.finditer(text)
                       if m.lastgroup != 'ws']
        self.pos = 0
        self.labels: dict[int, Node] = {}

    def peek(self) -> tuple[str, str] | None:
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def next(self) -> tuple[str, str]:
        tok = self.peek()
        if tok is None:
            raise ParseError("unexpected end of file")
        self.pos += 1
        return tok

    def parse_value(self) -> Any:
        kind, text = self.next()
        if kind == 'str':
            return _unescape(text)
        if kind == 'atom':
            return _convert_atom(text)
        if kind == 'ref':
            return Ref(int(text[1:]))
        if kind == 'label':
            node = self.parse_value()
            if not isinstance(node, Node):
                raise ParseError(f"label {text} not followed by an object")
            node.label = int(text[1:])
            self.labels[node.label] = node
            return node
        if kind == 'lparen':
            return self.parse_node()
        if kind == 'lbrack':
            items = []
            while self.peek() and self.peek()[0] != 'rbrack':
                items.append(self.parse_value())
            self.next()
            return items
        raise ParseError(f"unexpected token {text!r} at token {self.pos}")

    def parse_node(self) -> Node:
        kind, text = self.next()
        if kind != 'atom':
            raise ParseError(f"expected type name, got {text!r}")
        node = Node(text)
        while True:
            tok = self.peek()
            if tok is None:
                raise ParseError(f"unterminated ({node.type}")
            if tok[0] == 'rparen':
                self.next()
                return node
            kind, key = self.next()
            if kind != 'atom':
                raise ParseError(f"expected key in ({node.type}, got {key!r}")
            node.fields.append((key, self.parse_value()))

    def parse_document(self) -> Document:
        fields = []
        while self.peek():
            kind, key = self.next()
            if kind != 'atom':
                raise ParseError(f"expected top-level key, got {key!r}")
            fields.append((key, self.parse_value()))
        return Document(fields, self.labels)


def parse(text: str) -> Document:
    return _Parser(text).parse_document()


def parse_file(path: str) -> Document:
    with open(path, encoding='utf-8', errors='replace') as f:
        return parse(f.read())
