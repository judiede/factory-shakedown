"""Stop 5, Build, and the stop 6 loops: a task in, a code pull request out; CI failures and review feedback back in."""

from __future__ import annotations

from pathlib import Path

from . import agent, github, progress, scope, switch, trailers
from . import spec as specmod
from .jira import Jira
from .policy import Policy
from .publish import (agent_fields, agent_inputs_dir, commit_and_push, cost_line, load_state, logs_dir, message,
                      read_text, save_state)
from .results import push, push_record, record, screenshot_url
from .util import (BUILD_BRANCH_RE, FactoryError, build_branch, gh_output, require_key, require_task, run_url,
                   step_summary)

ORG_ALIAS = "task-org"
VALIDATE_WORKFLOW = "factory-validate.yml"


def prepare(key: str, task_id: str, mode: str, pr_number: str | None, policy: Policy) -> dict:
    require_key(key)
    require_task(task_id)
    if mode not in {"build", "fix", "revise"}:
        raise FactoryError(f"Unknown build mode {mode!r}")
    held = switch.paused(policy)
    if held:
        return switch.stop_run(held)
    base = github.base_for(key)
    text = github.file_content(f"docs/specs/{key}.md", base)
    if text is None:
        raise FactoryError(f"No approved spec docs/specs/{key}.md on {base}; Gate 1 comes first")
    task = specmod.parse(text).task(task_id)
    budget = policy.budget(task.work_type)
    ctx = {"key": key, "task": task_id, "title": task.title, "allowed": task.allowed, "work_type": task.work_type,
           "depends": task.depends, "base": base, "mode": mode, "pr": None, "attempt": 0, "stop": False,
           "reason": "", "max_cost": float(budget["cost_usd"])}
    agent_inputs_dir().mkdir(parents=True, exist_ok=True)

    if mode == "build":
        branch = build_branch(key, task_id, task.title)
        if github.remote_branch_exists(branch) or github.open_pr(branch):
            ctx.update(stop=True, reason=f"{branch} already exists; the task is already in progress")
        ctx.update(branch=branch, checkout_ref=base)
    else:
        if not pr_number:
            raise FactoryError(f"{mode} mode needs the pull request number")
        pr = github.pr(int(pr_number))
        m = BUILD_BRANCH_RE.match(pr["headRefName"])
        if not m or m["key"] != key or m["task"] != task_id:
            raise FactoryError(f"PR #{pr_number} isn't the build pull request for {key} task {task_id}")
        if pr["state"] != "OPEN":
            ctx.update(stop=True, reason=f"PR #{pr_number} is no longer open")
        state = trailers.budget_state(github.commit_messages(pr["number"]), budget, mode)
        ctx.update(pr=pr["number"], branch=pr["headRefName"], checkout_ref=pr["headRefName"],
                   max_cost=state["remaining_usd"],
                   attempt=(state["fix_attempts"] if mode == "fix" else state["revisions"]) + 1)
        if state["exhausted"] and not ctx["stop"]:
            ctx.update(stop=True, reason=state["reason"])
            github.edit_pr(pr["number"], add_labels=["needs-human"])
            github.comment(pr["number"], f"The factory stopped this task: {state['reason']}. A person needs to take over.")
        elif mode == "fix":
            log = github.failed_logs(pr["headRefOid"], VALIDATE_WORKFLOW)
            (agent_inputs_dir() / "feedback.md").write_text(
                "# CI failure\n\nThe failed steps of the latest validation run:\n\n```\n" + log + "\n```\n", encoding="utf-8")
        else:
            (agent_inputs_dir() / "feedback.md").write_text(github.review_feedback(pr["number"]), encoding="utf-8")
    save_state("context", ctx)
    gh_output(base=base, branch=ctx["branch"], checkout_ref=ctx["checkout_ref"], stop=str(ctx["stop"]).lower(),
              reason=ctx["reason"], work_type=task.work_type)
    _report_start(ctx, policy)
    return ctx


def _report_start(ctx: dict, policy: Policy) -> None:
    task = f"Task {ctx['task']} ({ctx['title']})"
    pr_url = f"https://github.com/{github.repo()}/pull/{ctx['pr']}" if ctx["pr"] else None
    if ctx["stop"]:
        if ctx["pr"]:  # a duplicate build dispatch just ends quietly
            progress.report(policy, ctx["key"], "BUILD", "BLOCKED", f"{task} stopped: {ctx['reason']}.", prUrl=pr_url)
        return
    notes = {"build": f"{task}: the build agent is building it.",
             "fix": f"{task}: CI failed; the build agent is fixing it (attempt {ctx['attempt']}).",
             "revise": f"{task}: the build agent is working in the review comments (round {ctx['attempt']})."}
    progress.report(policy, ctx["key"], "BUILD", note=notes[ctx["mode"]], prUrl=pr_url)


def run(workdir: Path, policy: Policy) -> dict:
    ctx = load_state("context")
    key, mode = ctx["key"], ctx["mode"]
    out = workdir / agent.OUT_DIR
    deploy_note = load_state("org", {}).get("note", "")
    (out / "deploy.md").write_text(deploy_note or "(No deploy note.)", encoding="utf-8")
    variables = {
        "TASK_ID": ctx["task"], "TASK_TITLE": ctx["title"], "BASE": ctx["base"], "ORG": ORG_ALIAS,
        "SPEC": f"docs/specs/{key}.md", "ATTEMPT": str(ctx["attempt"]), "WORK_TYPE": ctx["work_type"],
        "ALLOWED": "\n".join(f"- `{p}`" for p in ctx["allowed"] + policy.get("scope.always_allowed", [])),
    }
    budget = policy.budget(ctx["work_type"])
    res = agent.run("build", mode, key, workdir, policy, budget, variables, org_alias=ORG_ALIAS,
                    allowed_paths=ctx["allowed"], max_cost=ctx["max_cost"], logs_dir=logs_dir())

    changes = scope.worktree_changes(workdir)
    found = scope.violations([p for _, p in changes], *scope.rules_for("build", policy, key, ctx["allowed"]))
    spec_problem = read_text(out / "spec-problem.md")
    if found:
        outcome = "scope_violation"
    elif spec_problem:
        outcome = "needs_spec_change"
    elif not changes:
        outcome = "no_changes"
    elif not res["ok"]:
        outcome = "overrun"  # time, turns or budget ran out with work in progress
    else:
        outcome = "changes"
    shots = sorted(p.name for p in (out / "screenshots").glob("*.png")) if (out / "screenshots").is_dir() else []
    result = {"agent": res, "outcome": outcome, "changed": [p for _, p in changes], "scope": found,
              "spec_problem": spec_problem, "screenshots": shots}
    save_state("result", result)
    step_summary(f"## Build agent ({mode}): {outcome}\n\n{cost_line(res)}\n\n{scope.report(found)}")
    gh_output(outcome=outcome)
    return result


def _screenshots(ctx: dict, workdir: Path, names: list[str], sha: str, branch: str) -> str:
    if not names:
        return ""
    files, md = {}, []
    for name in names[:10]:
        dest = f"screenshots/{ctx['key']}/{ctx['task']}/{sha[:12]}/{name}"
        files[dest] = workdir / agent.OUT_DIR / "screenshots" / name
        md.append(f"![{name}]({screenshot_url(dest, branch)})")
    push(files, f"{ctx['key']}: screenshots for task {ctx['task']}", branch)
    return "### Screenshots\n\n" + "\n\n".join(md)


def _pr_body(ctx: dict, result: dict, summary: str, shots: str) -> str:
    changed = "\n".join(f"- `{p}`" for p in result["changed"][:60]) or "- (none)"
    parts = [f"Task **{ctx['task']}** of **{ctx['key']}**: {ctx['title']}",
             f"Spec: `docs/specs/{ctx['key']}.md` on `{ctx['base']}` · Work type: {ctx['work_type']}",
             "### Agent summary\n\n" + (summary or "(The agent left no summary.)")]
    if result["spec_problem"]:
        parts.append("### The spec can't be built as written\n\n" + result["spec_problem"])
    parts += [f"### Changed files\n\n{changed}", shots, cost_line(result["agent"])]
    return "\n\n".join(p for p in parts if p)


def publish(workdir: Path, policy: Policy) -> dict:
    ctx, result = load_state("context"), load_state("result")
    key, mode, outcome, res = ctx["key"], ctx["mode"], result["outcome"], result["agent"]
    branch = policy.get("results_branch")
    pr_url, pr_number = None, ctx.get("pr")
    labels = {"needs_spec_change": ["needs-spec-change"], "overrun": ["needs-human"]}.get(outcome, [])
    summary = read_text(workdir / agent.OUT_DIR / "summary.md")

    if outcome in {"changes", "overrun", "needs_spec_change"}:
        subject = {"build": f"{key}: {ctx['title']}", "fix": f"{key}: fix CI (attempt {ctx['attempt']})",
                   "revise": f"{key}: address review (round {ctx['attempt']})"}[mode]
        msg = message(subject, summary[:1500], agent="build", mode=mode, task=f"{key}/{ctx['task']}",
                      attempt=ctx["attempt"], **agent_fields(res))
        sha = commit_and_push(workdir, ctx["branch"], msg, allow_empty=outcome == "needs_spec_change")
        shots = _screenshots(ctx, workdir, result["screenshots"], sha, branch)
        if pr_number:
            if labels:
                github.edit_pr(pr_number, add_labels=labels)
            github.comment(pr_number, f"**{mode.capitalize()} attempt {ctx['attempt']}**: {outcome}.\n\n"
                                      f"{summary[:3000]}\n\n{shots}\n\n{cost_line(res)}")
            pr_url = github.pr(pr_number)["url"]
        else:
            pr_url = github.create_pr(ctx["base"], ctx["branch"], f"{key}: {ctx['title']}",
                                      _pr_body(ctx, result, summary, shots), ["factory-build"] + labels,
                                      draft=outcome != "changes")
    elif pr_number:
        github.edit_pr(pr_number, add_labels=["needs-human"])
        github.comment(pr_number, f"The build agent's {mode} run ended with **{outcome}**; nothing was pushed. "
                                  f"A person needs to take over. {run_url()}")

    rec = record("build", mode, key, ctx["task"], res, outcome, pr_url=pr_url, base=ctx["base"],
                 work_type=ctx["work_type"], attempt=ctx["attempt"], changed_files=len(result["changed"]),
                 scope_violations=len(result["scope"]), screenshots=len(result["screenshots"]))
    push_record(rec, branch)
    save_state("publish", {"pr_url": pr_url})
    gh_output(pr_url=pr_url or "")
    return {"pr_url": pr_url}


def notify(policy: Policy, jira: Jira | None = None) -> None:
    ctx, result = load_state("context"), load_state("result")
    pub = load_state("publish", {"pr_url": None})
    jira = jira or Jira.from_env()
    outcome, link = result["outcome"], pub.get("pr_url") or run_url()
    task = f"task {ctx['task']} ({ctx['title']})"
    pr_url = pub.get("pr_url")
    if outcome == "changes" and ctx["mode"] == "build":
        jira.comment(ctx["key"], f"The factory opened a pull request for {task}: {link}")
    elif outcome == "needs_spec_change":
        jira.comment(ctx["key"], f"The build agent found that the spec can't be built as written for {task}. "
                                 f"A spec amendment needs Gate 1 again: {link}\n\n{result['spec_problem'][:2000]}")
    elif outcome in {"scope_violation", "no_changes", "overrun", "agent_failed"}:
        jira.comment(ctx["key"], f"The factory needs a person for {task} ({outcome}): {link}")
        jira.labels(ctx["key"], add=[policy.get("intake.needs_human_label")])
    # The control panel hears about every outcome, also the fixes and revisions Jira isn't told about.
    if outcome == "changes":
        opened = "pull request opened" if ctx["mode"] == "build" else "changes pushed"
        progress.report(policy, ctx["key"], "CI", note=f"{task[0].upper()}{task[1:]}: {opened}; CI is checking it.",
                        prUrl=pr_url)
    else:
        why = ("the spec can't be built as written, so a spec amendment needs Gate 1 again"
               if outcome == "needs_spec_change" else f"a person needs to look ({outcome})")
        progress.report(policy, ctx["key"], "BUILD", "BLOCKED", f"{task[0].upper()}{task[1:]}: {why}.", prUrl=pr_url)


def stopped(policy: Policy, jira: Jira | None = None) -> None:
    """Tell Jira when the budget gate stopped a fix or revise run. A duplicate build dispatch just ends quietly."""
    ctx = load_state("context")
    if ctx["mode"] == "build" or not ctx.get("pr"):
        return
    jira = jira or Jira.from_env()
    jira.comment(ctx["key"], f"The factory stopped task {ctx['task']}: {ctx['reason']}. {run_url()}")
    jira.labels(ctx["key"], add=[policy.get("intake.needs_human_label")])
