"""State encoding styles (values only; how they are declared is up to the generator)."""
from __future__ import annotations


def _bits_for(n: int) -> int:
    """Number of bits for a binary count of n states (at least 1)."""
    return max(1, (n - 1).bit_length())


def encode(names: list[str], style: str, manual: dict[str, str] | None = None) -> tuple[int, dict[str, str]]:
    """Return (width, {state name: Verilog literal}) for the state encoding `style`.

        sequential (default)  binary count 0, 1, 2 ...         width = ceil(log2 n), literals N'd<i>
        gray                  Gray code of the index i         same width, N'b...
        onehot                bit i set for state i            width = n
        johnson               twisted-ring counter sequence    width = ceil(n / 2)
        manual                the values typed by the user     `manual` maps state -> bit string;
                                                               width = longest value; a state
                                                               without value gets all 'x'
    """
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
