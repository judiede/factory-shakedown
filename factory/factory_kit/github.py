"""GitHub operations through the gh CLI. GH_TOKEN decides the identity: the factory App or GITHUB_TOKEN."""

from __future__ import annotations

import json

from .util import FactoryError, env, run


def gh(*args: str, input: str | None = None, check: bool = True) -> str:
    proc = run(["gh", *args], input=input, check=False)
    if check and proc.returncode != 0:
        raise FactoryError(f"gh {' '.join(args[:3])} failed: {proc.stderr.strip()[-1500:]}")
    return proc.stdout


def gh_json(*args: str) -> object:
    out = gh(*args)
    return json.loads(out) if out.strip() else None


def repo() -> str:
    return env("GITHUB_REPOSITORY", required=True)


PR_FIELDS = "number,url,state,isDraft,headRefName,baseRefName,title,labels,mergedAt,headRefOid"


def open_pr(head: str) -> dict | None:
    prs = gh_json("pr", "list", "--repo", repo(), "--head", head, "--state", "open", "--json", PR_FIELDS)
    return prs[0] if prs else None


def pr(number: int) -> dict:
    return gh_json("pr", "view", str(number), "--repo", repo(), "--json", PR_FIELDS + ",body")


def list_prs(limit: int = 500) -> list[dict]:
    return gh_json("pr", "list", "--repo", repo(), "--state", "all", "--limit", str(limit), "--json", PR_FIELDS) or []


def commit_messages(number: int) -> list[str]:
    data = gh_json("pr", "view", str(number), "--repo", repo(), "--json", "commits")
    return [f"{c.get('messageHeadline', '')}\n\n{c.get('messageBody', '')}".strip() for c in data.get("commits", [])]


def create_pr(base: str, head: str, title: str, body: str, labels: list[str], draft: bool) -> str:
    args = ["pr", "create", "--repo", repo(), "--base", base, "--head", head, "--title", title, "--body-file", "-"]
    for label in labels:
        args += ["--label", label]
    if draft:
        args.append("--draft")
    return gh(*args, input=body).strip()


def edit_pr(number: int, body: str | None = None, add_labels: list[str] = (), remove_labels: list[str] = ()) -> None:
    args = ["pr", "edit", str(number), "--repo", repo()]
    if body is not None:
        args += ["--body-file", "-"]
    for label in add_labels:
        args += ["--add-label", label]
    for label in remove_labels:
        args += ["--remove-label", label]
    if len(args) > 4:
        gh(*args, input=body)


def set_draft(number: int, draft: bool) -> None:
    gh("pr", "ready", str(number), "--repo", repo(), *(["--undo"] if draft else []), check=False)


def comment(number: int, body: str) -> None:
    gh("pr", "comment", str(number), "--repo", repo(), "--body-file", "-", input=body)


def dispatch(workflow: str, ref: str, **inputs: str) -> None:
    args = ["workflow", "run", workflow, "--repo", repo(), "--ref", ref]
    for k, v in inputs.items():
        if v is not None and v != "":
            args += ["-f", f"{k}={v}"]
    gh(*args)


def gh_paged(path: str) -> list:
    """All items of a paginated REST list endpoint."""
    pages = gh_json("api", path, "--paginate", "--slurp") or []
    return [item for page in pages for item in (page if isinstance(page, list) else [page])]


def remote_branch_exists(branch: str) -> bool:
    # The git refs endpoint takes branch names with slashes, such as poc/SALES-412.
    proc = run(["gh", "api", f"repos/{repo()}/git/ref/heads/{branch}"], check=False)
    return proc.returncode == 0


def file_content(path: str, ref: str) -> str | None:
    proc = run(["gh", "api", f"repos/{repo()}/contents/{path}?ref={ref}",
                "-H", "Accept: application/vnd.github.raw+json"], check=False)
    return proc.stdout if proc.returncode == 0 else None


def base_for(key: str) -> str:
    """Replay tickets have a poc/<KEY> base branch; backlog tickets build on the default branch."""
    return f"poc/{key}" if remote_branch_exists(f"poc/{key}") else env("FACTORY_DEFAULT_BRANCH", "main")


def failed_logs(head_sha: str, workflow: str, limit_bytes: int = 60_000) -> str:
    """Failed-step logs of the latest failed run of a workflow for a commit."""
    runs = gh_json("run", "list", "--repo", repo(), "--workflow", workflow, "--commit", head_sha,
                   "--json", "databaseId,conclusion,status", "--limit", "5") or []
    failed = [r for r in runs if r.get("conclusion") == "failure"]
    if not failed:
        return "(No failed CI run found for this commit.)"
    log = gh("run", "view", str(failed[0]["databaseId"]), "--repo", repo(), "--log-failed", check=False)
    return log[-limit_bytes:] if len(log) > limit_bytes else log


def review_feedback(number: int) -> str:
    """The latest review's body and its inline comments, as Markdown for the agent."""
    asked = [r for r in reviews(number) if r.get("state") == "CHANGES_REQUESTED"]
    if not asked:
        return "(No review asking for changes was found.)"
    latest = asked[-1]
    comments = gh_paged(f"repos/{repo()}/pulls/{number}/reviews/{latest['id']}/comments")
    lines = ["# Review feedback", "", (latest.get("body") or "").strip() or "(No summary comment.)", ""]
    for c in comments:
        lines += [f"## `{c.get('path')}` line {c.get('line') or c.get('original_line')}", "", c.get("body", "").strip(), ""]
    return "\n".join(lines)


def reviews(number: int) -> list[dict]:
    return gh_paged(f"repos/{repo()}/pulls/{number}/reviews")


def issue_comments(number: int) -> list[dict]:
    """The pull request's conversation comments."""
    return gh_paged(f"repos/{repo()}/issues/{number}/comments")


def review_comments(number: int) -> list[dict]:
    """The pull request's inline comments on lines of the diff."""
    return gh_paged(f"repos/{repo()}/pulls/{number}/comments")


def react(comment_id: int, kind: str, content: str = "eyes") -> None:
    """Acknowledge a comment, so people see the factory picked it up."""
    path = f"repos/{repo()}/{'pulls' if kind == 'review' else 'issues'}/comments/{comment_id}/reactions"
    run(["gh", "api", path, "--method", "POST", "-f", f"content={content}"], check=False)


def post_review(number: int, payload: dict) -> bool:
    proc = run(["gh", "api", f"repos/{repo()}/pulls/{number}/reviews", "--method", "POST", "--input", "-"],
               input=json.dumps(payload), check=False)
    return proc.returncode == 0
