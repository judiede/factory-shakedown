"""Sparring on a spec pull request: `/factory <question>` asks the spec agent, `/factory revise` applies the talk.

The agent answers in the pull request conversation without changing the spec, and may ask questions back.
Every factory reply carries MARKER, which is how the conversation and its turn budget are reconstructed.
"""

from __future__ import annotations

import re

MARKER = "<!-- factory:discuss -->"
COMMAND_RE = re.compile(r"^\s*/factory\b(?P<rest>.*)$", re.S | re.I)
TRUSTED = {"OWNER", "MEMBER", "COLLABORATOR"}


def parse_command(body: str | None) -> tuple[str, str] | None:
    """('revise', note) or ('ask', question) for a /factory comment; None for anything else."""
    m = COMMAND_RE.match(body or "")
    if not m:
        return None
    rest = m["rest"].strip()
    if re.match(r"^revise\b", rest, re.I):
        return "revise", rest[6:].strip()
    return "ask", rest


def items(issue_comments: list[dict], review_comments: list[dict]) -> list[dict]:
    """Both kinds of pull request comments, normalised and in time order."""
    out = []
    for c, kind in [(c, "issue") for c in issue_comments] + [(c, "review") for c in review_comments]:
        user = c.get("user") or {}
        out.append({
            "id": c.get("id"), "kind": kind, "author": user.get("login", ""), "bot": user.get("type") == "Bot",
            "association": c.get("author_association", ""), "created_at": c.get("created_at", ""),
            "body": c.get("body") or "", "path": c.get("path"), "line": c.get("line") or c.get("original_line"),
            "hunk": c.get("diff_hunk"), "url": c.get("html_url", ""),
        })
    return sorted(out, key=lambda i: i["created_at"])


def is_reply(item: dict) -> bool:
    return item["bot"] and MARKER in item["body"]


def is_command(item: dict) -> bool:
    return not item["bot"] and item["association"] in TRUSTED and parse_command(item["body"]) is not None


def reply_count(entries: list[dict]) -> int:
    return sum(is_reply(i) for i in entries)


def unanswered(entries: list[dict]) -> list[dict]:
    """/factory questions posted after the factory's latest reply (several can pile up while a run is busy)."""
    last = max((i["created_at"] for i in entries if is_reply(i)), default="")
    return [i for i in entries if is_command(i) and i["created_at"] > last and parse_command(i["body"])[0] == "ask"]


def _where(item: dict) -> str:
    return f" on `{item['path']}` line {item['line']}" if item.get("path") else ""


def transcript(entries: list[dict]) -> str:
    """The conversation so far, for the agent: reviewers' /factory comments and the factory's replies."""
    lines = []
    for i in entries:
        if is_reply(i):
            lines += [f"### Factory ({i['created_at'][:16]})", "", i["body"].replace(MARKER, "").strip(), ""]
        elif is_command(i):
            lines += [f"### {i['author']} ({i['created_at'][:16]}){_where(i)}", ""]
            if i.get("hunk"):
                lines += ["```diff", i["hunk"][-1500:], "```", ""]
            lines += [i["body"].strip(), ""]
    return "\n".join(lines).strip() or "(No conversation yet.)"


def questions(pending: list[dict]) -> str:
    """The questions this run must answer, numbered, with where they were asked."""
    lines = ["# Questions to answer now", ""]
    for n, i in enumerate(pending, 1):
        kind, text = parse_command(i["body"])
        lines += [f"{n}. From {i['author']}{_where(i)}:", "", text or "(no text)", ""]
    return "\n".join(lines)
