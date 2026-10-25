"""Stop 4, Plan: turn an approved spec's task breakdown into build runs, in dependency order."""

from __future__ import annotations

from . import github, trailers
from .spec import Spec, Task
from .util import BUILD_BRANCH_RE, SPEC_BRANCH_RE

RANK = {"merged": 3, "open": 2, "rejected": 1}


def task_states(key: str, prs: list[dict]) -> dict[str, str]:
    """merged, open or rejected per task ID, from the build pull requests of a ticket."""
    states: dict[str, str] = {}
    for pr in prs:
        m = BUILD_BRANCH_RE.match(pr.get("headRefName", ""))
        if not m or m["key"] != key:
            continue
        state = "merged" if pr.get("mergedAt") or pr.get("state") == "MERGED" else (
            "open" if pr.get("state") == "OPEN" else "rejected")
        if RANK[state] > RANK.get(states.get(m["task"], ""), 0):
            states[m["task"]] = state
    return states


def ready(spec: Spec, states: dict[str, str]) -> list[Task]:
    return [t for t in spec.tasks
            if t.id not in states and all(states.get(d) == "merged" for d in t.depends)]


def blocked(spec: Spec, states: dict[str, str]) -> list[Task]:
    """Tasks that can never start because a dependency was rejected."""
    rejected = {t for t, s in states.items() if s == "rejected"}
    out, changed = [], True
    dead = set(rejected)
    while changed:
        changed = False
        for t in spec.tasks:
            if t.id not in dead and any(d in dead for d in t.depends):
                dead.add(t.id)
                out.append(t)
                changed = True
    return out


def all_merged(spec: Spec, states: dict[str, str]) -> bool:
    return bool(spec.tasks) and all(states.get(t.id) == "merged" for t in spec.tasks)


def ticket_cost(key: str, prs: list[dict]) -> float:
    total = 0.0
    for pr in prs:
        head = pr.get("headRefName", "")
        mine = (m := SPEC_BRANCH_RE.match(head)) and m["key"] == key or (
            (b := BUILD_BRANCH_RE.match(head)) and b["key"] == key)
        if mine:
            total += trailers.summarize(github.commit_messages(pr["number"]))["cost_usd"]
    return round(total, 4)


def run_next(key: str, policy, jira=None, dispatch: bool = True) -> list[str]:
    """After a spec or task merges: dispatch every task whose dependencies have merged."""
    from . import spec as specmod
    from .jira import Jira
    from .util import env, require_key, step_summary

    require_key(key)
    base = github.base_for(key)
    text = github.file_content(f"docs/specs/{key}.md", base)
    if text is None:
        step_summary(f"## Plan for {key}\n\nNo merged spec on `{base}` yet; nothing to plan.")
        return []
    spec = specmod.parse(text)
    problems = specmod.lint(spec, policy, key)
    jira = jira or Jira.from_env()
    labels = policy.get("intake")
    if problems:
        jira.comment(key, "The merged spec has problems the factory can't plan around:\n" + "\n".join(problems))
        jira.labels(key, add=[labels["needs_human_label"]])
        return []

    prs = github.list_prs()
    states = task_states(key, prs)
    spent = ticket_cost(key, prs)
    cap = float(policy.get("budgets.ticket_cost_usd", 0) or 0)
    todo = ready(spec, states)
    started: list[str] = []
    if all_merged(spec, states):
        jira.comment(key, f"All {len(spec.tasks)} task(s) are merged. Gate 2 is done for this ticket "
                          f"(factory spend ${spent:.2f}).")
        jira.labels(key, add=[labels["merged_label"]], remove=[labels["active_label"]])
    elif cap and spent >= cap and todo:
        jira.comment(key, f"The ticket's cost cap is reached (${spent:.2f} of ${cap:.2f}); the factory won't "
                          f"start tasks {', '.join(t.id for t in todo)}.")
        jira.labels(key, add=[labels["needs_human_label"]])
    else:
        for t in todo:
            if dispatch:
                github.dispatch("factory-build.yml", env("FACTORY_DEFAULT_BRANCH", "main"),
                                key=key, task=t.id, mode="build")
            started.append(t.id)
        if not states and started:
            jira.comment(key, f"Spec approved at Gate 1. The factory planned {len(spec.tasks)} task(s):\n"
                              + "\n".join(f"- {t.id}: {t.title}" for t in spec.tasks))
    stuck = blocked(spec, states)
    if stuck:
        jira.comment(key, "These tasks can't start because a task they depend on was rejected: "
                          + ", ".join(t.id for t in stuck))
    step_summary(f"## Plan for {key}\n\nBase `{base}` · spent ${spent:.2f}\n\n{table(spec, states)}\n\n"
                 + (f"Started: {', '.join(started)}" if started else "No task started."))
    return started


def table(spec: Spec, states: dict[str, str]) -> str:
    rows = [f"| {t.id} | {t.title} | {', '.join(t.depends) or '–'} | {t.work_type} | {states.get(t.id, 'waiting')} |"
            for t in spec.tasks]
    return "| ID | Task | Depends on | Work type | State |\n| --- | --- | --- | --- | --- |\n" + "\n".join(rows)
