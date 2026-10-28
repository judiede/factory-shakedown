"""Stop 2, Spec, and the Gate 1 revision loop: ticket in, spec pull request out."""

from __future__ import annotations

from pathlib import Path

from . import agent, discuss, github, grounding, scope, switch, trailers
from . import spec as specmod
from .jira import Jira
from .policy import Policy
from .publish import (agent_fields, agent_inputs_dir, commit_and_push, cost_line, load_state, logs_dir,
                      message, read_text, save_state)
from .results import push_record, record
from .util import FactoryError, gh_output, package_dirs, require_key, run_url, spec_branch, step_summary

ORG_ALIAS = "ticket-org"


def prepare(key: str, requested_mode: str, pr_number: str | None, policy: Policy) -> dict:
    """Work out the base branch, the mode and what is left of the budget. Runs before the work tree exists."""
    require_key(key)
    held = switch.paused(policy)
    if held:
        return switch.stop_run(held)
    base = github.base_for(key)
    branch = spec_branch(key)
    existing = github.open_pr(branch)
    budget = policy.budget("spec")
    ctx = {"key": key, "base": base, "branch": branch, "stop": False, "reason": "", "pr": None, "round": 1}

    if requested_mode in {"revise", "discuss"}:
        if not pr_number:
            raise FactoryError(f"{requested_mode.capitalize()} mode needs the spec pull request number")
        existing = github.pr(int(pr_number))
        if existing["headRefName"] != branch:
            raise FactoryError(f"PR #{pr_number} isn't the spec pull request for {key}")
        mode = requested_mode
    else:
        mode = "update" if existing else "new"

    agent_inputs_dir().mkdir(parents=True, exist_ok=True)
    if existing and mode == "discuss":
        _prepare_discussion(ctx, existing["number"], policy)
    elif existing:
        ctx["pr"] = existing["number"]
        state = trailers.budget_state(github.commit_messages(existing["number"]), budget, mode)
        ctx["round"] = state["revisions"] + 1
        ctx["max_cost"] = state["remaining_usd"]
        if state["exhausted"]:
            ctx.update(stop=True, reason=state["reason"])
        if mode == "revise":
            entries = discuss.items(github.issue_comments(existing["number"]), github.review_comments(existing["number"]))
            feedback = github.review_feedback(existing["number"])
            feedback += "\n\n# Conversation on the pull request (/factory)\n\n" + discuss.transcript(entries)
            (agent_inputs_dir() / "feedback.md").write_text(feedback, encoding="utf-8")
    else:
        ctx["max_cost"] = float(budget["cost_usd"])
    ctx["mode"] = mode
    ctx["checkout_ref"] = branch if github.remote_branch_exists(branch) else base
    save_state("context", ctx)
    gh_output(base=base, mode=mode, checkout_ref=ctx["checkout_ref"], stop=str(ctx["stop"]).lower(),
              reason=ctx["reason"], replay=str(base != "main").lower())
    if ctx["stop"] and ctx["pr"] and mode != "discuss":
        github.edit_pr(ctx["pr"], add_labels=["needs-human"])
        github.comment(ctx["pr"], f"The factory stopped: {ctx['reason']}. A person needs to take this spec over.")
    return ctx


def _prepare_discussion(ctx: dict, number: int, policy: Policy) -> None:
    """Collect the unanswered /factory questions and the conversation so far."""
    entries = discuss.items(github.issue_comments(number), github.review_comments(number))
    pending = discuss.unanswered(entries)
    limits = policy.budget("discuss")
    ctx.update(pr=number, max_cost=float(limits["cost_usd"]), questions=[i["id"] for i in pending],
               turn=discuss.reply_count(entries) + 1)
    if not pending:
        # Another run already answered them (several comments can arrive while one run is busy).
        ctx.update(stop=True, reason="no unanswered /factory questions")
    elif ctx["turn"] > int(limits["turns"]):
        ctx.update(stop=True, reason=f"the discussion limit of {limits['turns']} replies is reached")
        github.comment(number, f"{discuss.MARKER}\nThe factory has used its {limits['turns']} replies on this pull "
                               "request. Use a review with **Request changes**, or `/factory revise`, to move on.")
    (agent_inputs_dir() / "questions.md").write_text(discuss.questions(pending), encoding="utf-8")
    (agent_inputs_dir() / "conversation.md").write_text(discuss.transcript(entries), encoding="utf-8")


def _run_discussion(ctx: dict, workdir: Path, policy: Policy, org_ready: bool) -> dict:
    """Answer the pending /factory questions. The agent may only write its reply."""
    key = ctx["key"]
    variables = {"SPEC": f"docs/specs/{key}.md",
                 "ORG": ORG_ALIAS if org_ready else "none (no org for this discussion; rely on the repo)"}
    res = agent.run("spec", "discuss", key, workdir, policy, policy.budget("discuss"), variables,
                    org_alias=ORG_ALIAS if org_ready else None, max_cost=ctx.get("max_cost"), logs_dir=logs_dir(),
                    read_only=True)
    changes = scope.worktree_changes(workdir)
    reply = read_text(workdir / agent.OUT_DIR / "reply.md", 12000)
    outcome = "scope_violation" if changes else ("answered" if reply else "no_reply")
    result = {"agent": res, "outcome": outcome, "changed": [p for _, p in changes], "scope": [], "lint": [],
              "grounding_errors": 0, "reply": reply}
    save_state("result", result)
    step_summary(f"## Spec agent, sparring reply {ctx.get('turn')}: {outcome}\n\n{cost_line(res)}")
    gh_output(outcome=outcome)
    return result


def run(workdir: Path, policy: Policy, org_ready: bool) -> dict:
    ctx = load_state("context")
    key, mode = ctx["key"], ctx["mode"]
    if mode == "discuss":
        return _run_discussion(ctx, workdir, policy, org_ready)
    spec_path = f"docs/specs/{key}.md"
    variables = {
        "SPEC": spec_path, "BASE": ctx["base"], "MODE": mode, "ROUND": str(ctx["round"]),
        "ORG": ORG_ALIAS if org_ready else "none (no org could be prepared; rely on the repo)",
        "REPLAY": "yes" if ctx["base"] != "main" else "no",
    }
    res = agent.run("spec", mode, key, workdir, policy, policy.budget("spec"), variables,
                    org_alias=ORG_ALIAS if org_ready else None, max_cost=ctx.get("max_cost"), logs_dir=logs_dir())

    changes = scope.worktree_changes(workdir)
    found = scope.violations([p for _, p in changes], *scope.rules_for("spec", policy, key))
    result = {"agent": res, "changed": [p for _, p in changes], "scope": found, "lint": [], "grounding": "",
              "grounding_errors": 0, "questions": None}
    spec_file = workdir / spec_path
    if found:
        outcome = "scope_violation"
    elif not spec_file.exists():
        outcome = "agent_failed" if not res["ok"] else "no_spec"
    else:
        parsed = specmod.load(spec_file)
        result["lint"] = specmod.lint(parsed, policy, key)
        checks = grounding.check(parsed, workdir, package_dirs(workdir),
                                 grounding.OrgLookup(ORG_ALIAS) if org_ready else None)
        result["grounding"] = grounding.report(checks)
        result["grounding_errors"] = sum(r.is_error for r in checks)
        result["questions"] = parsed.open_questions
        result["title"] = parsed.title
        if not res["ok"]:
            outcome = "agent_failed"
        elif result["lint"] or result["grounding_errors"]:
            outcome = "checks_failed"
        else:
            outcome = "questions" if parsed.open_questions else "spec_ready"
    result["outcome"] = outcome
    save_state("result", result)
    step_summary(f"## Spec agent: {outcome}\n\n{cost_line(res)}\n\n{scope.report(found)}\n\n"
                 + ("\n".join(f"- {e}" for e in result["lint"]) or "Spec lint passed.") + "\n\n" + result["grounding"])
    gh_output(outcome=outcome)
    return result


def _pr_body(ctx: dict, result: dict, summary: str) -> str:
    parts = [f"Spec for **{ctx['key']}**, written by the spec agent. Merging this pull request is the Gate 1 approval.",
             f"Base branch: `{ctx['base']}` · Mode: {ctx['mode']} · Round {ctx['round']}"]
    if result.get("questions"):
        parts.append("### Open questions\n\nThe agent posted these to the Jira ticket. The pull request stays in draft "
                     "until they are answered; then add the `factory-ready` label to the ticket again.\n\n"
                     + result["questions"])
    if summary:
        parts.append("### Agent summary\n\n" + summary)
    parts.append("### Checks\n\n" + ("\n".join(f"- {e}" for e in result["lint"]) or "Spec lint passed.")
                 + "\n\n" + (result.get("grounding") or ""))
    parts.append(cost_line(result["agent"]))
    return "\n\n".join(parts)


def _publish_discussion(ctx: dict, result: dict, policy: Policy) -> dict:
    """Post the reply in the pull request conversation; nothing is committed."""
    if result["outcome"] == "answered":
        body = (f"{discuss.MARKER}\n**Factory**, reply {ctx.get('turn')}:\n\n{result['reply']}\n\n---\n"
                f"<sub>Ask again with `/factory <question>`; apply the outcome with `/factory revise`. "
                f"{cost_line(result['agent'])}</sub>")
    else:
        body = f"{discuss.MARKER}\nThe factory couldn't answer this time ({result['outcome']}): {run_url()}"
    github.comment(ctx["pr"], body)
    rec = record("spec", "discuss", ctx["key"], None, result["agent"], result["outcome"], pr=ctx["pr"],
                 turn=ctx.get("turn"), questions_answered=len(ctx.get("questions", [])))
    push_record(rec, policy.get("results_branch"))
    save_state("publish", {"pr_url": None})
    return {"pr_url": None}


def publish(workdir: Path, policy: Policy) -> dict:
    ctx, result = load_state("context"), load_state("result")
    if ctx["mode"] == "discuss":
        return _publish_discussion(ctx, result, policy)
    key, outcome, res = ctx["key"], result["outcome"], result["agent"]
    pr_url, pr_number = None, ctx.get("pr")
    if outcome in {"spec_ready", "questions", "checks_failed"}:
        title = result.get("title") or "spec"
        msg = message(f"{key}: {'revise ' if ctx['mode'] == 'revise' else ''}spec – {title}",
                      read_text(workdir / agent.OUT_DIR / "summary.md", 1500),
                      agent="spec", mode=ctx["mode"], task=f"{key}/spec", attempt=ctx["round"], **agent_fields(res))
        commit_and_push(workdir, ctx["branch"], msg)
        summary = read_text(workdir / agent.OUT_DIR / "summary.md")
        body = _pr_body(ctx, result, summary)
        draft = outcome != "spec_ready"
        labels = ["factory-spec"] + (["needs-human"] if outcome == "checks_failed" else [])
        if pr_number:
            github.edit_pr(pr_number, body=body, add_labels=labels)
            github.set_draft(pr_number, draft)
            github.comment(pr_number, f"Spec updated ({ctx['mode']}, round {ctx['round']}): {outcome}.\n\n{summary[:3000]}")
            pr_url = github.pr(pr_number)["url"]
        else:
            pr_url = github.create_pr(ctx["base"], ctx["branch"], f"{key}: spec – {title}", body, labels, draft)
    elif pr_number:
        github.edit_pr(pr_number, add_labels=["needs-human"])
        github.comment(pr_number, f"The spec agent's run ended with **{outcome}**, so nothing was pushed. {run_url()}")

    rec = record("spec", ctx["mode"], key, None, res, outcome, pr_url=pr_url, base=ctx["base"],
                 lint_errors=len(result["lint"]), grounding_errors=result["grounding_errors"],
                 scope_violations=len(result["scope"]), questions=bool(result.get("questions")),
                 redactions=load_state("redactions", {}))
    push_record(rec, policy.get("results_branch"))
    save_state("publish", {"pr_url": pr_url})
    gh_output(pr_url=pr_url or "")
    return {"pr_url": pr_url}


def notify(policy: Policy, jira: Jira | None = None) -> None:
    ctx, result = load_state("context"), load_state("result")
    if ctx["mode"] == "discuss":
        return  # sparring stays in the pull request
    pub = load_state("publish", {"pr_url": None})
    jira = jira or Jira.from_env()
    key, outcome = ctx["key"], result["outcome"]
    labels = policy.get("intake")
    link = pub.get("pr_url") or run_url()
    if outcome == "questions":
        jira.comment(key, f"The factory's spec agent needs answers before the spec can be approved. "
                          f"Reply in a comment, then add the label {labels['ready_label']} again.\n\n"
                          f"{result['questions']}\n\nDraft spec: {link}")
        jira.labels(key, add=[labels["clarification_label"]])
    elif outcome == "spec_ready":
        jira.comment(key, f"Spec ready for Gate 1 review: {link}")
        jira.labels(key, remove=[labels["clarification_label"]])
    else:
        jira.comment(key, f"The factory couldn't produce a spec ({outcome}). A person needs to look: {link}")
        jira.labels(key, add=[labels["needs_human_label"]])
