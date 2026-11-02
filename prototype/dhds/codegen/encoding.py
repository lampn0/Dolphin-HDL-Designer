"""State encoding styles (values only; how they are declared is up to the generator)."""
from __future__ import annotations


def _bits_for(n: int) -> int:
    return max(1, (n - 1).bit_length())


def encode(names: list[str], style: str, manual: dict[str, str] | None = None) -> tuple[int, dict[str, str]]:
    """Return (width, {state: verilog literal}) for the given style."""
    n = len(names)
    if style == 'onehot':
        width = max(1, n)
        return width, {s: f"{width}'b{1 << i:0{width}b}" for i, s in enumerate(names)}
    if style == 'gray':
        width = _bits_for(n)
        return width, {s: f"{width}'b{i ^ (i >> 1):0{width}b}" for i, s in enumerate(names)}
    if style == 'johnson':
        width = max(1, (n + 1) // 2)
        vals = []
        v = 0
        for _ in range(n):
            vals.append(v)
            lsb_inverted = (v & 1) ^ 1
            v = (v >> 1) | (lsb_inverted << (width - 1))
        return width, {s: f"{width}'b{vals[i]:0{width}b}" for i, s in enumerate(names)}
    if style == 'manual' and manual:
        raw = {s: (manual.get(s) or '').strip() for s in names}
        width = max((len(v.replace('_', '')) for v in raw.values() if v), default=_bits_for(n))
        return width, {s: f"{width}'b{v}" if v else f"{width}'b{'x' * width}" for s, v in raw.items()}
    width = _bits_for(n)
    return width, {s: f"{width}'d{i}" for i, s in enumerate(names)}
