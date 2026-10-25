"""Just enough Markdown parsing for specs and feature docs: headings, pipe tables and front matter."""

from __future__ import annotations

import re

import yaml

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")


def _lines_outside_fences(text: str):
    fenced = False
    for line in text.splitlines():
        if FENCE_RE.match(line):
            fenced = not fenced
            yield line, True
            continue
        yield line, fenced


def title(text: str) -> str | None:
    for line, fenced in _lines_outside_fences(text):
        m = HEADING_RE.match(line)
        if m and not fenced and len(m[1]) == 1:
            return m[2].strip()
    return None


def sections(text: str, level: int = 2) -> dict[str, str]:
    """Map each heading of the given level (lower-cased) to its body, in order."""
    out: dict[str, str] = {}
    current, buf = None, []
    for line, fenced in _lines_outside_fences(text):
        m = None if fenced else HEADING_RE.match(line)
        if m and len(m[1]) <= level:
            if current is not None:
                out[current] = "\n".join(buf).strip()
            current = m[2].strip().lower() if len(m[1]) == level else None
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        out[current] = "\n".join(buf).strip()
    return out


def _split_row(line: str) -> list[str]:
    line = line.strip()
    if line.startswith("|"):
        line = line[1:]
    if line.endswith("|") and not line.endswith("\\|"):
        line = line[:-1]
    cells, cur, i = [], [], 0
    while i < len(line):
        if line[i] == "\\" and i + 1 < len(line) and line[i + 1] == "|":
            cur.append("|")
            i += 2
            continue
        if line[i] == "|":
            cells.append("".join(cur).strip())
            cur = []
        else:
            cur.append(line[i])
        i += 1
    cells.append("".join(cur).strip())
    return cells


def parse_table(text: str) -> list[dict[str, str]]:
    """Rows of the first pipe table in the text, keyed by lower-cased header."""
    lines = [ln for ln, fenced in _lines_outside_fences(text) if not fenced]
    for i in range(len(lines) - 1):
        if lines[i].strip().startswith("|") and re.match(r"^\s*\|?\s*:?-{3,}", lines[i + 1]):
            headers = [h.lower() for h in _split_row(lines[i])]
            rows = []
            for line in lines[i + 2:]:
                if not line.strip().startswith("|"):
                    break
                cells = _split_row(line)
                cells += [""] * (len(headers) - len(cells))
                rows.append(dict(zip(headers, cells)))
            return rows
    return []


def front_matter(text: str) -> tuple[dict | None, str]:
    """YAML front matter between leading '---' lines, or None when there is none."""
    if not text.startswith("---"):
        return None, text
    parts = re.split(r"^---\s*$", text, maxsplit=2, flags=re.MULTILINE)
    if len(parts) < 3:
        return None, text
    data = yaml.safe_load(parts[1]) or {}
    return (data if isinstance(data, dict) else None), parts[2].lstrip("\n")


def clean_cell(cell: str) -> str:
    cell = cell.strip()
    cell = re.sub(r"^(\*\*|__|\*|_)(.*)\1$", r"\2", cell)
    return cell.strip().strip("`").strip()


def split_list(cell: str) -> list[str]:
    """Comma- or <br>-separated cell values; dashes and 'none' mean empty."""
    parts = re.split(r",|<br\s*/?>|;", cell)
    out = [clean_cell(p) for p in parts]
    return [p for p in out if p and p.lower() not in {"-", "–", "—", "none", "n/a"}]
