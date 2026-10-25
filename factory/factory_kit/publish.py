"""Shared steps around an agent run: workspace setup, step state, and commits with trailers.

Step state lives in $GITHUB_WORKSPACE/factory-in, outside the work tree, so the agent can neither read nor
change it. The agent never pushes: these steps commit and push its work as the factory GitHub App.
"""

from __future__ import annotations

import base64
import shutil
from pathlib import Path

from . import trailers
from .agent import OUT_DIR
from .util import FactoryError, env, git, read_json, run, run_url, write_json


def state_dir() -> Path:
    return Path(env("GITHUB_WORKSPACE", ".")) / "factory-in"


def agent_inputs_dir() -> Path:
    """Files the prepare step collects for the agent; copied into the work tree's .factory-out."""
    return state_dir() / "agent"


def logs_dir() -> Path:
    return Path(env("RUNNER_TEMP", "/tmp")) / "factory-logs"


def save_state(name: str, data: dict) -> None:
    write_json(state_dir() / f"{name}.json", data)


def load_state(name: str, default: dict | None = None) -> dict:
    path = state_dir() / f"{name}.json"
    if path.exists():
        return read_json(path)
    if default is not None:
        return default
    raise FactoryError(f"State file {path} not found; did an earlier step fail?")


def init_workspace(workdir: str | Path) -> Path:
    """Keep agent inputs and outputs out of git, and hand over what the prepare step collected."""
    workdir = Path(workdir)
    out = workdir / OUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    exclude = workdir / ".git" / "info" / "exclude"
    exclude.parent.mkdir(parents=True, exist_ok=True)
    lines = exclude.read_text(encoding="utf-8").splitlines() if exclude.exists() else []
    # Tool output that must never count as the agent's change: sf config, npm installs, test coverage.
    wanted = [f"/{OUT_DIR}/", "/.sf/", "/.sfdx/", "/node_modules/", "/coverage/", "/.localdevserver/"]
    missing = [w for w in wanted if w not in lines]
    if missing:
        exclude.write_text("\n".join(lines + missing) + "\n", encoding="utf-8")
    src = agent_inputs_dir()
    if src.is_dir():
        for item in src.iterdir():
            if item.is_file():
                shutil.copyfile(item, out / item.name)
    return out


def identity() -> tuple[str, str]:
    """Commit as the GitHub App's bot user."""
    slug = env("FACTORY_APP_SLUG")
    if not slug:
        return "factory-agent[bot]", "factory-agent[bot]@users.noreply.github.com"
    proc = run(["gh", "api", f"users/{slug}[bot]", "--jq", ".id"], check=False)
    user_id = proc.stdout.strip() if proc.returncode == 0 else ""
    prefix = f"{user_id}+" if user_id else ""
    return f"{slug}[bot]", f"{prefix}{slug}[bot]@users.noreply.github.com"


def auth_args() -> list[str]:
    token = env("GH_TOKEN", required=True)
    basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    return ["-c", f"http.extraheader=AUTHORIZATION: basic {basic}"]


def message(subject: str, body: str, **fields: object) -> str:
    """Commit message whose last paragraph holds Factory-* trailers (see trailers.py)."""
    names = {k: "Factory-" + k.replace("_", "-").title().replace("-Usd", "-USD") for k in fields}
    block = trailers.format({names[k]: v for k, v in fields.items()})
    return "\n\n".join(p.strip() for p in (subject, body, block) if p and p.strip())


def commit_and_push(workdir: str | Path, branch: str, msg: str, allow_empty: bool = False) -> str:
    name, email = identity()
    git("checkout", "-q", "-B", branch, cwd=workdir)
    git("add", "-A", cwd=workdir)
    args = ["git", "-c", f"user.name={name}", "-c", f"user.email={email}", "commit", "-q", "-F", "-"]
    if allow_empty:
        args.append("--allow-empty")
    proc = run(args, cwd=workdir, input=msg, check=False)
    if proc.returncode != 0 and "nothing to commit" not in proc.stdout + proc.stderr:
        raise FactoryError(f"git commit failed: {proc.stderr.strip() or proc.stdout.strip()}")
    run(["git", *auth_args(), "push", "-q", "origin", f"HEAD:refs/heads/{branch}"], cwd=workdir)
    return git("rev-parse", "HEAD", cwd=workdir)


def read_text(path: Path, limit: int = 6000) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace").strip()
    return text if len(text) <= limit else text[:limit] + "\n\n(truncated)"


def cost_line(agent: dict) -> str:
    cost = agent.get("cost_usd")
    cost_txt = f"${cost:.2f}" if isinstance(cost, (int, float)) else "unknown"
    return (f"Model `{agent.get('model')}` · {agent.get('num_turns') or '?'} turns · "
            f"{agent.get('duration_s') or '?'} s · cost {cost_txt} · [workflow run]({run_url()})")


def agent_fields(agent: dict) -> dict:
    cost = agent.get("cost_usd")
    return {
        "run": run_url(),
        "model": agent.get("model"),
        "prompt": f"{agent.get('prompt')}@{agent.get('prompt_sha')}",
        "cost_usd": f"{cost:.4f}" if isinstance(cost, (int, float)) else None,
        "duration_s": agent.get("duration_s"),
    }
