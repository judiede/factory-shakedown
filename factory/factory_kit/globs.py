"""Repo-relative path globs with gitignore-style `**`, used for allowed paths and feature doc maps."""

from __future__ import annotations

import re
from functools import lru_cache

from .util import norm_path

_WILDCARDS = set("*?[")


@lru_cache(maxsize=1024)
def compile_glob(pattern: str) -> re.Pattern:
    pattern = norm_path(pattern.strip())
    if pattern.endswith("/"):
        pattern += "**"
    out, i = [], 0
    while i < len(pattern):
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("/**", i) and i + 3 == len(pattern):
            out.append("(?:/.*)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif pattern[i] == "*":
            out.append("[^/]*")
            i += 1
        elif pattern[i] == "?":
            out.append("[^/]")
            i += 1
        elif pattern[i] == "[" and (end := pattern.find("]", i + 2)) != -1:
            body = pattern[i + 1:end].replace("\\", "\\\\")
            if body.startswith("!"):
                body = "^" + body[1:]
            out.append(f"[{body}]")
            i = end + 1
        else:
            out.append(re.escape(pattern[i]))
            i += 1
    regex = "".join(out)
    if not _WILDCARDS & set(pattern):
        # A plain path also covers everything below it, like a directory.
        regex += "(?:/.*)?"
    return re.compile(f"^{regex}$")


def matches(path: str, patterns) -> bool:
    path = norm_path(path)
    return any(compile_glob(p).match(path) for p in patterns if p and p.strip())


def is_safe_pattern(pattern: str) -> bool:
    """Allowed-path globs must stay inside the repo."""
    p = norm_path(pattern.strip())
    return bool(p) and not p.startswith("/") and ".." not in p.split("/") and ":" not in p
