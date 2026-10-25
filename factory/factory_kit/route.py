"""Event router: turns pull request events into factory runs.

Runs without secrets, on pull_request, pull_request_review and workflow_run events. It only dispatches
workflow_dispatch runs on the default branch, where the factory-agent environment and its secrets live.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import discuss, github
from .util import env, parse_branch, step_summary

VALIDATE_NAME = "Factory: validate (stop 6)"


def _labels(pr: dict) -> set[str]:
    return {label["name"] for label in pr.get("labels", [])}


def comment_command(event_name: str, payload: dict, head_of=None) -> tuple[str, dict] | None:
    """A /factory comment on a spec pull request, from someone with write access, as (workflow, inputs)."""
    if payload.get("action") != "created":
        return None
    comment = payload.get("comment") or {}
    if (comment.get("user") or {}).get("type") == "Bot" or comment.get("author_association") not in discuss.TRUSTED:
        return None
    command = discuss.parse_command(comment.get("body"))
    if not command:
        return None
    if event_name == "issue_comment":
        issue = payload.get("issue") or {}
        if "pull_request" not in issue or head_of is None:  # the key only exists on pull request comments
            return None
        number, head = issue.get("number"), head_of(issue.get("number"))
    else:
        pr = payload.get("pull_request") or {}
        number, head = pr.get("number"), (pr.get("head") or {}).get("ref", "")
    info = parse_branch(head or "")
    if info["kind"] != "spec":
        return None
    return "factory-spec.yml", {"key": info["key"], "mode": "discuss" if command[0] == "ask" else "revise",
                                "pr": str(number)}


def decide(event_name: str, payload: dict, head_of=None) -> list[tuple[str, dict]]:
    """(workflow file, inputs) pairs to dispatch for one event. Pure, so it can be tested.
    head_of(number) looks up a pull request's head branch, which issue_comment payloads don't carry."""
    if event_name in {"issue_comment", "pull_request_review_comment"}:
        found = comment_command(event_name, payload, head_of)
        return [found] if found else []

    if event_name == "pull_request":
        pr = payload.get("pull_request") or {}
        info = parse_branch((pr.get("head") or {}).get("ref", ""))
        if payload.get("action") == "closed" and pr.get("merged") and info["kind"] in {"spec", "build"}:
            return [("factory-plan.yml", {"key": info["key"]})]
        return []

    if event_name == "pull_request_review":
        review, pr = payload.get("review") or {}, payload.get("pull_request") or {}
        info = parse_branch((pr.get("head") or {}).get("ref", ""))
        if payload.get("action") != "submitted" or (review.get("state") or "").lower() != "changes_requested":
            return []
        if (review.get("user") or {}).get("type") == "Bot":
            return []
        number = str(pr.get("number"))
        if info["kind"] == "spec":
            return [("factory-spec.yml", {"key": info["key"], "mode": "revise", "pr": number})]
        if info["kind"] == "build":
            return [("factory-build.yml", {"key": info["key"], "task": info["task"], "mode": "revise", "pr": number})]
        return []

    if event_name == "workflow_run":
        run = payload.get("workflow_run") or {}
        info = parse_branch(run.get("head_branch") or "")
        if run.get("name") != VALIDATE_NAME or run.get("event") != "pull_request" or info["kind"] != "build":
            return []
        prs = run.get("pull_requests") or []
        if not prs:
            return []
        number = str(prs[0]["number"])
        if run.get("conclusion") == "failure":
            return [("factory-build.yml", {"key": info["key"], "task": info["task"], "mode": "fix", "pr": number})]
        if run.get("conclusion") == "success":
            return [("factory-review.yml", {"pr": number})]
    return []


def main() -> int:
    event_name = env("GITHUB_EVENT_NAME", required=True)
    payload = json.loads(Path(env("GITHUB_EVENT_PATH", required=True)).read_text(encoding="utf-8"))
    actions = decide(event_name, payload, head_of=lambda n: github.pr(int(n))["headRefName"])
    ref = env("FACTORY_DEFAULT_BRANCH", "main")
    done = []
    if actions and event_name in {"issue_comment", "pull_request_review_comment"}:
        github.react(payload["comment"]["id"], "issue" if event_name == "issue_comment" else "review")
    for workflow, inputs in actions:
        if "pr" in inputs and workflow != "factory-plan.yml":
            pr = github.pr(int(inputs["pr"]))
            if pr["state"] != "OPEN" or (workflow != "factory-spec.yml" and pr["isDraft"]) \
                    or _labels(pr) & {"needs-human", "needs-spec-change"}:
                done.append(f"- Skipped {workflow} for #{inputs['pr']}: closed, draft or waiting for a person")
                continue
        github.dispatch(workflow, ref, **inputs)
        done.append(f"- Dispatched {workflow} with {inputs}")
    step_summary("## Factory router\n\n" + ("\n".join(done) or "Nothing to do for this event."))
    return 0
