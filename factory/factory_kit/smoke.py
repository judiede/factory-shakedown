"""Step 1 check: every identity can log in, and the model answers. Nothing here prints a secret."""

from __future__ import annotations

import json
from pathlib import Path

from . import orgs
from .jira import Jira
from .policy import Policy
from .util import FactoryError, run, step_summary


def jira() -> str:
    me = Jira.from_env().myself()
    return f"Jira: logged in as {me.get('displayName')} ({me.get('accountType', 'user')})."


def model(policy: Policy) -> str:
    proc = run(["claude", "-p", "--model", policy.model("spec"), "--max-turns", "1", "--output-format", "json",
                "--permission-mode", "dontAsk", "--setting-sources", "user"],
               input="Reply with the single word OK.", check=False, timeout=300)
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise FactoryError(f"The model didn't answer: {proc.stderr[-500:] or proc.stdout[-500:]}") from None
    if data.get("is_error"):
        raise FactoryError(f"The model call failed: {data.get('result')}")
    return f"Model: {policy.model('spec')} answered {data.get('result', '').strip()[:20]!r}."


def devhub(workdir: Path, policy: Policy) -> str:
    orgs.login("devhub", "devhub")
    try:
        orgs.create_scratch("smoke-org", workdir, policy)
        orgs.delete_scratch("smoke-org")
    finally:
        orgs.logout("devhub")
    return "Dev Hub: logged in, created and deleted a scratch org."


def sandbox(who: str) -> str:
    alias = f"smoke-{who}"
    orgs.login(who, alias)
    orgs.logout(alias)
    return f"Integration sandbox: the {who} user logged in."


def main(checks: list[str], workdir: Path, policy: Policy) -> int:
    lines, failed = [], False
    for check in checks:
        try:
            if check == "jira":
                lines.append(jira())
            elif check == "model":
                lines.append(model(policy))
            elif check == "devhub":
                lines.append(devhub(workdir, policy))
            elif check in {"spec", "ci"}:
                lines.append(sandbox(check))
            else:
                raise FactoryError(f"Unknown check {check!r}")
        except FactoryError as exc:
            failed = True
            lines.append(f"FAILED {check}: {exc}")
    step_summary("## Factory smoke test\n\n" + "\n".join(f"- {line}" for line in lines))
    print("\n".join(lines))
    return 1 if failed else 0
