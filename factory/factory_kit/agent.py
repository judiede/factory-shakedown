"""Run Claude Code headless as one of the factory agents, inside a permission fence the agent can't change.

Claude Code runs in print mode with --permission-mode dontAsk: every tool call that the generated
settings don't allow is denied. Project settings and the repo's .mcp.json are not loaded
(--setting-sources user, --strict-mcp-config), so the fence comes only from this module.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import subprocess
import tempfile
import time
from pathlib import Path

from .policy import Policy
from .util import KIT_ROOT, FactoryError, file_sha, norm_path

PROMPTS = KIT_ROOT / "factory" / "prompts"
OUT_DIR = ".factory-out"

READ_ONLY_BASH = [
    "git status *", "git diff *", "git log *", "git show *", "ls *", "grep *", "find *", "wc *", "head *", "tail *",
]
SF_READ = [
    "sf org list metadata *", "sf org list metadata-types *", "sf sobject describe *", "sf sobject list *",
    "sf data query *", "sf project retrieve start *", "sf project retrieve preview *",
]
SF_BUILD = [
    "sf project deploy start *", "sf project deploy report *", "sf project deploy resume *",
    "sf project deploy preview *", "sf apex run *", "sf apex get test *", "sf apex get log *",
    "sf data create record *", "sf data update record *", "sf data import tree *", "sf org assign permset *",
    "sf code-analyzer run *", "sf code-analyzer rules *",
    "npm run test:unit *", "npm run lint *", "npx sfdx-lwc-jest *", "sfdx-lwc-jest *", "npx prettier *", "prettier *",
    "factory-screenshot *",
]
ALWAYS_DENY_BASH = [
    "git push *", "git commit *", "git remote *", "git config *", "git checkout *", "git reset *", "git rebase *",
    "curl *", "wget *", "ssh *", "scp *", "nc *", "env *", "printenv *", "set *", "export *",
    "sf org login *", "sf org logout *", "sf org display *", "sf org create *", "sf org delete *", "sf org open *",
    "sf config *", "sf alias *", "sf plugins *", "npm install *", "npm i *", "npx -y *", "pip *",
]
PROTECTED_EDIT = [
    "./.claude/**", "./.github/**", "./factory/**", "./factory-policy.yml", "./AGENTS.md", "./CLAUDE.md",
    "./.mcp.json", "./.git/**", "./.sf/**", "./.sfdx/**", "./sfdx-project.json", "./package.json",
    "./package-lock.json", "./config/**",
]
PROTECTED_READ = ["~/.sf/**", "~/.sfdx/**", "~/.claude.json", "~/.config/gh/**", "./.git/config"]

MCP_TOOLSETS = {"spec": "metadata", "build": "metadata,testing,lwc-experts,code-analysis"}
WORK_TOOLS = {"spec": "spec", "build": "build", "review": "review"}


def settings_for(role: str, policy: Policy, key: str, allowed_paths: list[str] = (), read_only: bool = False) -> dict:
    """Permission settings for one run. read_only keeps every edit inside .factory-out (sparring replies)."""
    edits = [f"./{OUT_DIR}/**"]
    bash = list(READ_ONLY_BASH)
    if role == "spec":
        edits += [] if read_only else [f"./{norm_path(p)}" for p in policy.spec_allowed(key)]
        bash += SF_READ + ["sf project deploy start *", "sf project deploy report *", "sf apex run test *",
                           "sf apex get test *"]
    elif role == "build":
        edits += [f"./{norm_path(p)}" for p in list(allowed_paths) + policy.get("scope.always_allowed", [])]
        bash += SF_READ + SF_BUILD
    elif role != "review":
        raise FactoryError(f"Unknown role {role!r}")
    allow = [f"Edit({p})" for p in edits] + [f"Bash({c})" for c in bash]
    allow += [f"WebFetch(domain:{d})" for d in policy.get("web_domains", [])]
    if role in MCP_TOOLSETS:
        allow.append("mcp__salesforce__*")
    deny = [f"Bash({c})" for c in ALWAYS_DENY_BASH]
    deny += [f"Edit({p})" for p in PROTECTED_EDIT] + [f"Read({p})" for p in PROTECTED_READ]
    deny += ["WebSearch", "Agent"]
    return {
        "permissions": {"allow": allow, "deny": deny, "disableBypassPermissionsMode": "disable"},
        "disableAllHooks": True,
    }


def mcp_config(role: str, org_alias: str | None) -> dict | None:
    if role not in MCP_TOOLSETS or not org_alias:
        return None
    args = ["--orgs", org_alias, "--toolsets", MCP_TOOLSETS[role], "--no-telemetry"]
    return {"mcpServers": {"salesforce": {"command": "sf-mcp-server", "args": args}}}


PLACEHOLDER_RE = re.compile(r"\{\{([A-Z_]+)\}\}")


def render(template: str, variables: dict[str, str]) -> str:
    """Fill {{NAME}} placeholders. Checked against the template, so values may contain braces."""
    missing = sorted(set(PLACEHOLDER_RE.findall(template)) - set(variables))
    if missing:
        raise FactoryError(f"Prompt placeholders without a value: {', '.join(missing)}")
    return PLACEHOLDER_RE.sub(lambda m: str(variables[m[1]]), template)


def prompt_path(role: str, mode: str) -> Path:
    specific = PROMPTS / f"{role}-{mode}.md"
    return specific if specific.exists() else PROMPTS / f"{role}.md"


def _result_message(transcript: Path) -> dict | None:
    result = None
    if transcript.exists():
        for line in transcript.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                msg = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(msg, dict) and msg.get("type") == "result":
                result = msg
    return result


def run(role: str, mode: str, key: str, workdir: str | Path, policy: Policy, budget: dict,
        variables: dict[str, str], org_alias: str | None = None, allowed_paths: list[str] = (),
        max_cost: float | None = None, logs_dir: str | Path | None = None, read_only: bool = False) -> dict:
    """Run one agent session. Returns the facts for the run log; never raises on agent failure."""
    workdir = Path(workdir).resolve()
    (workdir / OUT_DIR).mkdir(exist_ok=True)
    logs = Path(logs_dir or tempfile.mkdtemp(prefix="factory-agent-"))
    logs.mkdir(parents=True, exist_ok=True)

    template = prompt_path(role, mode)
    prompt = render(template.read_text(encoding="utf-8"), {"KEY": key, "OUT": OUT_DIR, **variables})
    (logs / "prompt.md").write_text(prompt, encoding="utf-8")
    settings_file = logs / "settings.json"
    settings = settings_for(role, policy, key, allowed_paths, read_only=read_only)
    settings_file.write_text(json.dumps(settings, indent=2), encoding="utf-8")

    model = policy.model(WORK_TOOLS[role])
    override = os.environ.get("FACTORY_CLAUDE_BIN", "claude")  # a JSON list or a command line; tests use a fake
    claude = json.loads(override) if override.startswith("[") else shlex.split(override)
    cmd = [*claude, "-p", "--output-format", "stream-json", "--verbose", "--model", model,
           "--permission-mode", "dontAsk", "--setting-sources", "user", "--settings", str(settings_file),
           "--max-turns", str(budget.get("max_turns", 100))]
    if max_cost is not None:
        cmd += ["--max-budget-usd", f"{max(max_cost, 0.01):.2f}"]
    mcp = mcp_config(role, org_alias)
    mcp_file = logs / "mcp.json"
    mcp_file.write_text(json.dumps(mcp or {"mcpServers": {}}), encoding="utf-8")
    cmd += ["--mcp-config", str(mcp_file), "--strict-mcp-config"]

    transcript = logs / "transcript.jsonl"
    timeout = float(budget.get("time_minutes", 30)) * 60
    started = time.time()
    timed_out = False
    child_env = {k: v for k, v in os.environ.items() if not k.startswith(("SF_JWT", "JIRA_", "GH_", "GITHUB_TOKEN"))}
    child_env.update({"DISABLE_AUTOUPDATER": "1", "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1"})
    with open(transcript, "w", encoding="utf-8") as out, open(logs / "stderr.log", "w", encoding="utf-8") as err:
        proc = subprocess.Popen(cmd, cwd=workdir, stdin=subprocess.PIPE, stdout=out, stderr=err, text=True,
                                encoding="utf-8", env=child_env)
        try:
            proc.communicate(prompt, timeout=timeout)
        except subprocess.TimeoutExpired:
            timed_out = True
            proc.kill()
            proc.communicate()

    result = _result_message(transcript) or {}
    usage = result.get("usage") or {}
    outcome = "timeout" if timed_out else (result.get("subtype") or ("no_result" if not result else "unknown"))
    if not timed_out and result and result.get("is_error") and outcome == "success":
        outcome = "error"
    return {
        "role": role,
        "mode": mode,
        "model": model,
        "prompt": template.name,
        "prompt_sha": file_sha(template),
        "outcome": outcome,
        "ok": outcome == "success",
        "exit_code": proc.returncode,
        "duration_s": round(time.time() - started, 1),
        "num_turns": result.get("num_turns"),
        "cost_usd": result.get("total_cost_usd"),
        "tokens": {
            "input": usage.get("input_tokens"),
            "output": usage.get("output_tokens"),
            "cache_read": usage.get("cache_read_input_tokens"),
            "cache_creation": usage.get("cache_creation_input_tokens"),
        },
        "final_message": (result.get("result") or "")[-4000:],
        "logs_dir": str(logs),
    }
