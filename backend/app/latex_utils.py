"""LaTeX token post-processing: repair, normalize, validate.

Port of the reference repair rules in `ink-on` (Apache-2.0), adapted for the
backend so both engines share one place.
"""

from __future__ import annotations

from typing import Iterable

NEEDS_ARGS = {"\\sum", "\\int", "\\sin", "\\cos", "\\tan", "\\log", "\\lim", "\\sqrt", "\\frac"}


def _balance_braces(tokens: list[str]) -> list[str]:
    out: list[str] = []
    depth = 0
    for t in tokens:
        if t == "{":
            depth += 1
            out.append(t)
        elif t == "}":
            if depth > 0:
                depth -= 1
                out.append(t)
        else:
            out.append(t)
    while depth > 0:
        out.append("}")
        depth -= 1
    return out


def _collect_group(tokens: list[str], i: int) -> tuple[list[str], int]:
    """Collect a braced group starting at tokens[i] == '{'. Returns (group, next_i)."""
    group = []
    depth = 0
    while i < len(tokens):
        t = tokens[i]
        group.append(t)
        if t == "{":
            depth += 1
        elif t == "}":
            depth -= 1
            if depth == 0:
                return group, i + 1
        i += 1
    return group, i


def _fix_args(tokens: list[str], command: str, want: int) -> list[str]:
    out: list[str] = []
    i = 0
    n = len(tokens)
    while i < n:
        if tokens[i] != command:
            out.append(tokens[i])
            i += 1
            continue
        out.append(command)
        i += 1
        groups = 0
        while i < n and groups < want:
            if tokens[i] == "{":
                group, i = _collect_group(tokens, i)
                out.extend(group)
                groups += 1
            else:
                out.append(tokens[i])
                i += 1
                groups += 1
        # drop extra braced groups
        while i < n and tokens[i] == "{":
            _, i = _collect_group(tokens, i)
    return out


def repair(tokens: list[str]) -> list[str]:
    tokens = _balance_braces(tokens)
    tokens = _fix_args(tokens, "\\frac", 2)
    tokens = _fix_args(tokens, "\\sqrt", 1)
    return tokens


def _count_braced_groups(tokens: list[str]) -> int:
    groups = 0
    i = 0
    n = len(tokens)
    while i < n:
        if tokens[i] != "{":
            break
        _, i = _collect_group(tokens, i)
        groups += 1
    return groups


def is_complete(tokens: list[str]) -> bool:
    if not tokens:
        return False
    if len(tokens) == 1 and tokens[0] in NEEDS_ARGS:
        return False
    for i, t in enumerate(tokens):
        if t == "\\frac" and _count_braced_groups(tokens[i + 1 :]) < 2:
            return False
        if t == "\\sqrt" and _count_braced_groups(tokens[i + 1 :]) < 1:
            return False
    return True


def is_balanced(tokens: list[str]) -> bool:
    depth = 0
    for t in tokens:
        if t == "{":
            depth += 1
        elif t == "}":
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def tokens_to_latex(tokens: Iterable[str]) -> str:
    """Join model tokens. Multi-char commands keep a space after them for safety."""
    parts = [t for t in tokens if t]
    return " ".join(parts)


def normalize(latex: str) -> str:
    """Light normalization; keeps tokens readable for editing."""
    import re

    s = " ".join(latex.split())
    s = re.sub(r"\\left(?![a-zA-Z])", "", s)
    s = re.sub(r"\\right(?![a-zA-Z])", "", s)
    s = s.replace("\\dfrac", "\\frac").replace("\\tfrac", "\\frac")
    s = s.replace("\\displaystyle", "")
    return " ".join(s.split())


def to_display(latex: str) -> str:
    return f"\\[ {latex} \\]"
