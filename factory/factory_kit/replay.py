"""Replay setup, run locally by a factory admin: one base branch per replayed ticket.

poc/<KEY> = the commit just before the human change + one commit that adds the factory files the agents
and CI need. Run it with your own git credentials: the factory App has no permission to push workflow files.
"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from .util import FactoryError, git, require_key

# Factory files a replay branch needs. Seeded ADRs are added per ticket with --extra, and only when they
# predate the ticket, so no later decision gives the answer away.
OVERLAY = [
    ".github", "AGENTS.md", "CLAUDE.md", "config/project-scratch-def.json",
    "docs/specs/_template.md", "docs/adr/0000-template.md", "docs/features/_template.md",
    "docs/architecture/decision-rules.md", "docs/architecture/security-rules.md",
]


def prepare(key: str, before: str, kit_ref: str = "main", extra: list[str] = (), push: bool = False,
            remote: str = "origin", repo: str | Path = ".") -> str:
    require_key(key)
    repo = Path(repo).resolve()
    branch, tag = f"poc/{key}", f"replay/{key}"
    if git("rev-parse", "--verify", "--quiet", f"refs/heads/{branch}", cwd=repo, check=False):
        raise FactoryError(f"{branch} already exists")
    commit = git("rev-parse", "--verify", f"{before}^{{commit}}", cwd=repo)
    tmp = Path(tempfile.mkdtemp(prefix=f"replay-{key}-"))
    try:
        git("worktree", "add", "-q", "-b", branch, str(tmp), commit, cwd=repo)
        paths = [p for p in OVERLAY + list(extra)
                 if git("ls-tree", "--name-only", kit_ref, "--", p, cwd=repo)]
        if not paths:
            raise FactoryError(f"None of the factory files exist on {kit_ref}")
        git("checkout", kit_ref, "--", *paths, cwd=tmp)
        git("add", "-A", cwd=tmp)
        git("commit", "-q", "-m", f"{key}: factory kit overlay for replay\n\nBase: {commit}\nKit: {kit_ref}", cwd=tmp)
        git("tag", "-a", tag, commit, "-m", f"Replay start for {key}: the commit before the human change", cwd=repo)
    finally:
        git("worktree", "remove", "--force", str(tmp), cwd=repo, check=False)
        shutil.rmtree(tmp, ignore_errors=True)
    if push:
        git("push", remote, f"refs/heads/{branch}", f"refs/tags/{tag}", cwd=repo)
    return branch
