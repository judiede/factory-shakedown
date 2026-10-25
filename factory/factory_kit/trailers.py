"""Commit trailers on agent commits. They carry the run record and are the source of truth for budgets."""

from __future__ import annotations

import re

TRAILER_RE = re.compile(r"^([A-Za-z][A-Za-z0-9-]*):\s?(.*)$")


def parse(message: str) -> dict[str, list[str]]:
    """Trailers from the last paragraph of a commit message."""
    paragraphs = [p for p in re.split(r"\n\s*\n", message.strip()) if p.strip()]
    if len(paragraphs) < 2:
        return {}
    out: dict[str, list[str]] = {}
    for line in paragraphs[-1].splitlines():
        m = TRAILER_RE.match(line.strip())
        if not m:
            return {}
        out.setdefault(m[1], []).append(m[2].strip())
    return out


def format(trailers: dict[str, object]) -> str:
    return "\n".join(f"{k}: {v}" for k, v in trailers.items() if v is not None and v != "")


def summarize(messages: list[str]) -> dict:
    """Fix attempts, revision rounds and cost so far, from a PR's commit messages."""
    fixes = revisions = 0
    cost = 0.0
    for message in messages:
        t = parse(message)
        if "Factory-Agent" not in t:
            continue
        mode = (t.get("Factory-Mode") or [""])[0]
        fixes += mode == "fix"
        revisions += mode == "revise"
        for value in t.get("Factory-Cost-USD", []):
            try:
                cost += float(value)
            except ValueError:
                pass
    return {"fix_attempts": fixes, "revisions": revisions, "cost_usd": round(cost, 4)}


def budget_state(messages: list[str], budget: dict, mode: str) -> dict:
    """Whether another run in this mode fits the task's budget."""
    used = summarize(messages)
    reason = None
    if used["cost_usd"] >= float(budget.get("cost_usd", 0) or 0):
        reason = f"cost cap reached (${used['cost_usd']:.2f} of ${budget.get('cost_usd')})"
    elif mode == "fix" and used["fix_attempts"] >= int(budget.get("fix_attempts", 0)):
        reason = f"all {budget.get('fix_attempts')} fix attempts used"
    elif mode == "revise" and used["revisions"] >= int(budget.get("revision_rounds", 0)):
        reason = f"all {budget.get('revision_rounds')} revision rounds used"
    remaining = max(0.0, float(budget.get("cost_usd", 0) or 0) - used["cost_usd"])
    return {**used, "exhausted": reason is not None, "reason": reason, "remaining_usd": round(remaining, 4)}
