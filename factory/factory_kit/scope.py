"""Scope check: an agent may only change the paths its role or task allows."""

from __future__ import annotations

from pathlib import Path

from .globs import matches
from .policy import Policy
from .util import FactoryError, git, norm_path, run

IGNORED_PREFIXES = (".factory-out/",)


def worktree_changes(cwd: str | Path) -> list[tuple[str, str]]:
    """Uncommitted changes, including untracked files, as (status, path) pairs."""
    # Raw output: the status columns start with a space, which git()'s strip would eat.
    out = run(["git", "status", "--porcelain=v1", "-z", "--untracked-files=all"], cwd=cwd).stdout
    entries = out.split("\0") if out else []
    changes, i = [], 0
    while i < len(entries):
        entry = entries[i]
        if not entry:
            i += 1
            continue
        status, path = entry[:2], entry[3:]
        if "R" in status or "C" in status:
            changes.append(("R", norm_path(path)))
            changes.append(("D", norm_path(entries[i + 1])))
            i += 2
            continue
        code = "A" if status == "??" else ("D" if "D" in status else "M")
        changes.append((code, norm_path(path)))
        i += 1
    return [(s, p) for s, p in changes if not p.startswith(IGNORED_PREFIXES)]


def branch_changes(cwd: str | Path, base: str) -> list[tuple[str, str]]:
    """Committed changes between the merge base with `base` and HEAD."""
    out = git("diff", "--name-status", "-M", "-z", f"{base}...HEAD", cwd=cwd)
    entries = [e for e in out.split("\0")] if out else []
    changes, i = [], 0
    while i < len(entries):
        status = entries[i]
        if not status:
            i += 1
            continue
        if status[0] in "RC":
            changes.append(("D", norm_path(entries[i + 1])))
            changes.append(("A", norm_path(entries[i + 2])))
            i += 3
        else:
            changes.append((status[0], norm_path(entries[i + 1])))
            i += 2
    return changes


def rules_for(role: str, policy: Policy, key: str, allowed_task_paths: list[str] | None = None) -> tuple[list[str], list[str]]:
    if role == "spec":
        return policy.spec_allowed(key), []
    if role == "build":
        if not allowed_task_paths:
            raise FactoryError("A build task needs allowed paths")
        return list(allowed_task_paths) + policy.get("scope.always_allowed", []), policy.get("scope.forbidden", [])
    if role == "review":
        return [], []
    raise FactoryError(f"Unknown role {role!r}")


def violations(paths: list[str], allowed: list[str], forbidden: list[str]) -> list[tuple[str, str]]:
    out = []
    for path in sorted(set(paths)):
        if matches(path, forbidden):
            out.append((path, "forbidden for agents"))
        elif not matches(path, allowed):
            out.append((path, "outside the allowed paths"))
    return out


def report(found: list[tuple[str, str]]) -> str:
    if not found:
        return "Scope check passed: every change is inside the allowed paths."
    rows = "\n".join(f"| `{p}` | {why} |" for p, why in found)
    return f"Scope check failed: {len(found)} change(s) outside the task's scope.\n\n| Path | Problem |\n| --- | --- |\n{rows}"
