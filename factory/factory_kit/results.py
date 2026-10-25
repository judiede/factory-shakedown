"""Run logs and screenshots go to the factory-results branch: one file per record, so parallel jobs never conflict."""

from __future__ import annotations

import base64
import datetime as dt
import shutil
import tempfile
from pathlib import Path

from .util import FactoryError, env, git, run, run_url, write_json

SCHEMA_VERSION = 1


def record(role: str, mode: str, key: str, task: str | None, agent: dict | None, outcome: str, **extra) -> dict:
    """One run log record. The shape is documented in factory/schemas/run-log.schema.json."""
    agent = agent or {}
    started = env("FACTORY_JOB_STARTED")
    job_s = None
    if started:
        try:
            job_s = round(dt.datetime.now(dt.timezone.utc).timestamp() - float(started), 1)
        except ValueError:
            pass
    return {
        "schema": SCHEMA_VERSION,
        "ticket": key,
        "task": task,
        "role": role,
        "mode": mode,
        "outcome": outcome,
        "run_id": env("GITHUB_RUN_ID", "local"),
        "run_attempt": env("GITHUB_RUN_ATTEMPT", "1"),
        "run_url": run_url(),
        "recorded_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "model": agent.get("model"),
        "prompt": agent.get("prompt"),
        "prompt_sha": agent.get("prompt_sha"),
        "agent_outcome": agent.get("outcome"),
        "num_turns": agent.get("num_turns"),
        "agent_duration_s": agent.get("duration_s"),
        "job_duration_s": job_s,
        "cost_usd": agent.get("cost_usd"),
        "tokens": agent.get("tokens"),
        **extra,
    }


def _auth_header(token: str) -> str:
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return f"http.extraheader=AUTHORIZATION: basic {basic}"


def push(files: dict[str, Path | str | bytes], message: str, branch: str, retries: int = 5) -> None:
    """Commit files (destination path -> source path or content) to the results branch and push."""
    token = env("GH_TOKEN", required=True)
    repo = env("GITHUB_REPOSITORY", required=True)
    server = env("GITHUB_SERVER_URL", "https://github.com")
    tmp = Path(tempfile.mkdtemp(prefix="factory-results-"))
    auth = ["-c", _auth_header(token)]
    try:
        git("init", "-q", cwd=tmp)
        git("remote", "add", "origin", f"{server}/{repo}.git", cwd=tmp)
        for name, value in [("user.name", env("FACTORY_GIT_NAME", "factory-agent[bot]")),
                            ("user.email", env("FACTORY_GIT_EMAIL", "factory-agent[bot]@users.noreply.github.com"))]:
            git("config", name, value, cwd=tmp)
        for _ in range(retries):
            # Start from the branch's current tip each time; another job may have pushed in between.
            exists = run(["git", *auth, "fetch", "-q", "--depth", "1", "origin", branch], cwd=tmp,
                         check=False).returncode == 0
            if exists:
                git("checkout", "-q", "-f", "-B", branch, "FETCH_HEAD", cwd=tmp)
            else:
                git("checkout", "-q", "--orphan", branch, cwd=tmp)
            for dest, src in files.items():
                target = tmp / dest
                target.parent.mkdir(parents=True, exist_ok=True)
                if isinstance(src, bytes):
                    target.write_bytes(src)
                elif isinstance(src, Path):
                    shutil.copyfile(src, target)
                else:
                    target.write_text(src, encoding="utf-8")
            git("add", "-A", cwd=tmp)
            git("commit", "-q", "-m", message, cwd=tmp)
            if run(["git", *auth, "push", "-q", "origin", f"HEAD:{branch}"], cwd=tmp, check=False).returncode == 0:
                return
        raise FactoryError(f"Could not push to {branch} after {retries} attempts")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def push_record(rec: dict, branch: str) -> str:
    month = rec["recorded_at"][:7]
    name = f"runs/{month}/{rec['ticket']}-{rec.get('task') or 'spec'}-{rec['role']}-{rec['run_id']}-{rec['run_attempt']}.json"
    local = Path(tempfile.mkdtemp()) / "record.json"
    write_json(local, rec)
    push({name: local}, f"{rec['ticket']}: run log ({rec['role']}, {rec['outcome']})", branch)
    return name


def screenshot_url(path: str, branch: str) -> str:
    server = env("GITHUB_SERVER_URL", "https://github.com")
    return f"{server}/{env('GITHUB_REPOSITORY', 'local/repo')}/blob/{branch}/{path}?raw=true"
