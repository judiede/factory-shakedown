"""Shared helpers: naming rules, subprocess calls and GitHub Actions output."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

KEY_PATTERN = r"[A-Z][A-Z0-9_]*-[1-9][0-9]*"
KEY_RE = re.compile(rf"^{KEY_PATTERN}$")
TASK_RE = re.compile(r"^[a-z]$")
SPEC_BRANCH_RE = re.compile(rf"^spec/(?P<key>{KEY_PATTERN})$")
BUILD_BRANCH_RE = re.compile(rf"^feature/(?P<key>{KEY_PATTERN})-(?P<task>[a-z])-[a-z0-9-]+$")
BASE_BRANCH_RE = re.compile(rf"^poc/(?P<key>{KEY_PATTERN})$")

KIT_ROOT = Path(__file__).resolve().parents[2]


class FactoryError(Exception):
    """An expected failure with a message meant for the job log."""


def require_key(key: str | None) -> str:
    if not key or not KEY_RE.match(key):
        raise FactoryError(f"Not a valid Jira key: {key!r}")
    return key


def require_task(task: str | None) -> str:
    if not task or not TASK_RE.match(task):
        raise FactoryError(f"Not a valid task ID (one lowercase letter): {task!r}")
    return task


def slugify(text: str, max_len: int = 40) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (slug[:max_len].rstrip("-")) or "task"


def spec_branch(key: str) -> str:
    return f"spec/{require_key(key)}"


def build_branch(key: str, task: str, title: str) -> str:
    return f"feature/{require_key(key)}-{require_task(task)}-{slugify(title)}"


def parse_branch(ref: str) -> dict:
    """Classify a head branch: spec, build or human."""
    ref = ref.removeprefix("refs/heads/")
    if m := SPEC_BRANCH_RE.match(ref):
        return {"kind": "spec", "key": m["key"], "task": None}
    if m := BUILD_BRANCH_RE.match(ref):
        return {"kind": "build", "key": m["key"], "task": m["task"]}
    return {"kind": "human", "key": None, "task": None}


def norm_path(path: str) -> str:
    path = path.replace("\\", "/")
    while path.startswith("./"):
        path = path[2:]
    return path


def run(cmd: list[str], cwd: str | Path | None = None, check: bool = True, input: str | None = None,
        env: dict | None = None, timeout: float | None = None) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, cwd=cwd, input=input, env=env, timeout=timeout, text=True,
                          encoding="utf-8", errors="replace", capture_output=True)
    if check and proc.returncode != 0:
        raise FactoryError(f"Command failed ({proc.returncode}): {' '.join(cmd[:4])} ...\n{proc.stderr.strip()[-2000:]}")
    return proc


def git(*args: str, cwd: str | Path | None = None, check: bool = True) -> str:
    return run(["git", *args], cwd=cwd, check=check).stdout.strip()


def env(name: str, default: str | None = None, required: bool = False) -> str | None:
    value = os.environ.get(name, default)
    if required and not value:
        raise FactoryError(f"Environment variable {name} is not set")
    return value


def gh_output(**values: object) -> None:
    """Write step outputs, or print them when not running in Actions."""
    target = os.environ.get("GITHUB_OUTPUT")
    lines = []
    for name, value in values.items():
        text = value if isinstance(value, str) else json.dumps(value)
        if "\n" in text:
            marker = f"EOF_{uuid.uuid4().hex}"
            lines.append(f"{name}<<{marker}\n{text}\n{marker}")
        else:
            lines.append(f"{name}={text}")
    if target:
        with open(target, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    else:
        print("\n".join(lines))


def step_summary(markdown: str) -> None:
    target = os.environ.get("GITHUB_STEP_SUMMARY")
    if target:
        with open(target, "a", encoding="utf-8") as fh:
            fh.write(markdown.rstrip() + "\n\n")
    else:
        print(markdown, file=sys.stderr)


def run_url() -> str:
    server = os.environ.get("GITHUB_SERVER_URL", "https://github.com")
    repo = os.environ.get("GITHUB_REPOSITORY", "local/repo")
    run_id = os.environ.get("GITHUB_RUN_ID", "0")
    attempt = os.environ.get("GITHUB_RUN_ATTEMPT", "1")
    return f"{server}/{repo}/actions/runs/{run_id}/attempts/{attempt}"


def file_sha(path: str | Path, length: int = 12) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:length]


def read_json(path: str | Path) -> object:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def write_json(path: str | Path, data: object) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def package_dirs(root: str | Path) -> list[str]:
    """Package directories from sfdx-project.json, defaulting to force-app."""
    project = Path(root) / "sfdx-project.json"
    if project.exists():
        data = json.loads(project.read_text(encoding="utf-8"))
        dirs = [norm_path(d["path"]).rstrip("/") for d in data.get("packageDirectories", []) if d.get("path")]
        if dirs:
            return dirs
    return ["force-app"]
