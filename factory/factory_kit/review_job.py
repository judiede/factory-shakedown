"""Stop 6, reviewer agent: comments on a green build pull request before the code owner looks. It never approves."""

from __future__ import annotations

import json
from pathlib import Path

from . import agent, github
from .policy import Policy
from .publish import agent_inputs_dir, cost_line, load_state, logs_dir, save_state
from .results import push_record, record
from .util import BUILD_BRANCH_RE, FactoryError, env, gh_output, step_summary

CATEGORIES = ["correctness", "security", "sharing", "limits", "tests", "docs", "standards", "style"]
MAX_COMMENTS = 15


def prepare(pr_number: str, policy: Policy) -> dict:
    pr = github.pr(int(pr_number))
    m = BUILD_BRANCH_RE.match(pr["headRefName"])
    labels = {label["name"] for label in pr.get("labels", [])}
    bot = f"{github_app_slug()}[bot]"
    ctx = {"pr": pr["number"], "head": pr["headRefName"], "sha": pr["headRefOid"], "base": pr["baseRefName"],
           "key": m["key"] if m else None, "task": m["task"] if m else None, "stop": False, "reason": ""}
    if not m:
        ctx.update(stop=True, reason="not a factory build pull request")
    elif pr["state"] != "OPEN" or pr["isDraft"] or labels & {"needs-human", "needs-spec-change"}:
        ctx.update(stop=True, reason="pull request is closed, a draft or waiting for a person")
    elif any(r.get("commit_id") == pr["headRefOid"] and (r.get("user") or {}).get("login") == bot
             for r in github.reviews(pr["number"])):
        ctx.update(stop=True, reason="this commit already has a factory review")
    if not ctx["stop"]:
        agent_inputs_dir().mkdir(parents=True, exist_ok=True)
        diff = github.gh("pr", "diff", str(pr["number"]), "--repo", github.repo())
        (agent_inputs_dir() / "pr.diff").write_text(diff, encoding="utf-8")
    save_state("context", ctx)
    gh_output(stop=str(ctx["stop"]).lower(), reason=ctx["reason"], checkout_ref=ctx["head"], key=ctx["key"] or "")
    return ctx


def github_app_slug() -> str:
    return env("FACTORY_APP_SLUG", "factory-agent")


def run(workdir: Path, policy: Policy) -> dict:
    ctx = load_state("context")
    variables = {"PR": str(ctx["pr"]), "TASK_ID": ctx["task"], "SPEC": f"docs/specs/{ctx['key']}.md",
                 "BASE": ctx["base"], "CATEGORIES": ", ".join(CATEGORIES), "MAX_COMMENTS": str(MAX_COMMENTS)}
    res = agent.run("review", "review", ctx["key"], workdir, policy, policy.budget("review"), variables,
                    logs_dir=logs_dir())
    review_file = workdir / agent.OUT_DIR / "review.json"
    review, outcome = None, "agent_failed"
    if review_file.exists():
        try:
            review = validate(json.loads(review_file.read_text(encoding="utf-8")))
            outcome = "reviewed"
        except (json.JSONDecodeError, FactoryError) as exc:
            outcome = "bad_review_file"
            step_summary(f"Review file rejected: {exc}")
    save_state("result", {"agent": res, "outcome": outcome, "review": review})
    step_summary(f"## Reviewer agent: {outcome}\n\n{cost_line(res)}")
    gh_output(outcome=outcome)
    return {"outcome": outcome}


def validate(data: dict) -> dict:
    if not isinstance(data, dict) or not isinstance(data.get("summary"), str):
        raise FactoryError("review.json needs a 'summary' string")
    comments = []
    for c in (data.get("comments") or [])[:MAX_COMMENTS]:
        if not isinstance(c, dict) or not c.get("path") or not isinstance(c.get("line"), int) or not c.get("body"):
            raise FactoryError(f"Each comment needs path, line (integer) and body: {c!r}")
        category = c.get("category") if c.get("category") in CATEGORIES else "correctness"
        comments.append({"path": str(c["path"]), "line": c["line"], "body": f"**{category}**: {c['body']}",
                         "category": category})
    return {"summary": data["summary"].strip(), "comments": comments}


def publish(policy: Policy) -> None:
    ctx, result = load_state("context"), load_state("result")
    review = result.get("review")
    if review:
        body = (f"Factory reviewer agent (comments only; a code owner decides).\n\n{review['summary']}\n\n"
                f"{cost_line(result['agent'])}")
        inline = [{"path": c["path"], "line": c["line"], "side": "RIGHT", "body": c["body"]} for c in review["comments"]]
        payload = {"commit_id": ctx["sha"], "event": "COMMENT", "body": body, "comments": inline}
        if not github.post_review(ctx["pr"], payload):
            # Inline comments on lines outside the diff are rejected; fold them into the body instead.
            folded = "\n".join(f"- `{c['path']}` line {c['line']}: {c['body']}" for c in review["comments"])
            payload.update(comments=[], body=body + ("\n\n### Comments\n\n" + folded if folded else ""))
            if not github.post_review(ctx["pr"], payload):
                raise FactoryError("GitHub rejected the review")
    counts: dict[str, int] = {}
    for c in (review or {}).get("comments", []):
        counts[c["category"]] = counts.get(c["category"], 0) + 1
    rec = record("review", "review", ctx["key"], ctx["task"], result["agent"], result["outcome"],
                 pr=ctx["pr"], review_comments=counts)
    push_record(rec, policy.get("results_branch"))
