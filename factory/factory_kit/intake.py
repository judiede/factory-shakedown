"""Stop 1, Intake: tickets labeled factory-ready become spec runs."""

from __future__ import annotations

from . import github, progress, switch
from .jira import Jira
from .policy import Policy
from .util import KEY_RE, env, step_summary


def poll(policy: Policy, jira: Jira | None = None, dispatch: bool = True) -> list[str]:
    held = switch.paused(policy)
    if held:
        # The tickets keep their ready label, so the first poll after the resume picks them up.
        step_summary(f"## Factory intake\n\nNo tickets started: {held}.")
        return []
    jira = jira or Jira.from_env()
    labels = policy.get("intake")
    project = env("JIRA_PROJECT", required=True)
    jql = (f'project = "{project}" AND labels = "{labels["ready_label"]}" '
           "ORDER BY priority DESC, created ASC")
    issues = jira.search(jql, ["summary", "labels"], limit=int(labels["max_dispatch_per_poll"]))
    started, lines = [], []
    for issue in issues:
        key = issue.get("key", "")
        if not KEY_RE.match(key):
            lines.append(f"- Skipped {key!r}: not a valid key")
            continue
        if dispatch:
            github.dispatch("factory-spec.yml", env("FACTORY_DEFAULT_BRANCH", "main"), key=key, mode="auto")
            jira.labels(key, add=[labels["active_label"]],
                        remove=[labels["ready_label"], labels["clarification_label"], labels["needs_human_label"]])
            progress.report(policy, key, "INTAKE", note="Picked up from Jira; the spec agent starts.",
                            title=(issue.get("fields") or {}).get("summary"))
        started.append(key)
        lines.append(f"- {key}: spec run started")
    step_summary("## Factory intake\n\n" + ("\n".join(lines) or "No tickets are labeled factory-ready."))
    return started
