"""Command line for the factory workflows: `factory <command>` (python3 -m factory_kit)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import (build_job, ci, docs_check, grounding, intake, orgs, plan, publish, replay, review_job, route, scope,
               smoke, spec_job, ticket)
from . import spec as specmod
from .jira import Jira
from .policy import load as load_policy
from .util import FactoryError, gh_output, package_dirs, require_key, run_url, step_summary


def _org_up(purpose: str, workdir: Path, policy) -> int:
    """Prepare the agent's org. Replay specs and every build get a scratch org built from the work tree."""
    ctx = publish.load_state("context")
    alias = spec_job.ORG_ALIAS if purpose == "spec" else build_job.ORG_ALIAS
    scratch = purpose == "build" or ctx["base"].startswith("poc/")
    state = {"alias": alias, "scratch": scratch, "ready": False, "created": False, "note": ""}
    if purpose == "spec" and ctx.get("mode") == "discuss" and scratch:
        # Building a scratch org to answer a question costs more than the answer is worth.
        state.update(scratch=False, alias=None, note="No org for discussions on replayed tickets; the agent uses the repo.")
        publish.save_state("org", state)
        gh_output(ready="false")
        return 0
    try:
        if scratch:
            # The Dev Hub key must stay available while the CLI logs in to the new scratch org and deploys.
            with orgs.session("devhub", "devhub"):
                try:
                    orgs.create_scratch(alias, workdir, policy)
                    state["created"] = True
                    ok, note = orgs.deploy(alias, workdir)
                finally:
                    orgs.logout("devhub")
            state.update(ready=True, note=note, deployed=ok)
            if not ok and (purpose == "spec" or ctx.get("mode") == "build"):
                # The base itself doesn't deploy: a pipeline problem, not the agent's (poc-plan.md pitfalls).
                # In fix and revise runs a failing deploy is expected: it is what the agent fixes.
                state["ready"] = False
        else:
            orgs.login("spec", alias)
            state.update(ready=True, note=f"Logged in to the integration sandbox as the read-only spec user ({alias}).")
        if state["ready"]:
            orgs.set_default(alias, workdir)
    except FactoryError as exc:
        state["note"] = f"Org setup failed: {exc}"
    publish.save_state("org", state)
    step_summary(f"## Org for the {purpose} agent\n\n{state['note']}")
    gh_output(ready=str(state["ready"]).lower())
    # A build always needs its scratch org, and a new build needs the base to deploy cleanly.
    if purpose == "build" and (not state["created"] or (ctx.get("mode") == "build" and not state["ready"])):
        print(f"::error::{state['note']}")
        return 1
    return 0


def _org_down() -> int:
    state = publish.load_state("org", {})
    if not state.get("alias"):
        return 0
    if state.get("scratch"):
        with orgs.session("devhub", "devhub"):
            try:
                orgs.delete_scratch(state["alias"])
            finally:
                orgs.logout("devhub")
    else:
        orgs.logout(state["alias"])
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="factory", description=__doc__)
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("intake", help="stop 1: start spec runs for tickets labeled factory-ready")
    sub.add_parser("route", help="dispatch factory runs for a pull request event")
    sp = sub.add_parser("plan", help="stop 4: dispatch the build tasks that are ready")
    sp.add_argument("--key", required=True)

    sp = sub.add_parser("ticket", help="fetch or screen Jira tickets")
    sp.add_argument("action", choices=["fetch", "screen"])
    sp.add_argument("--key")
    sp.add_argument("--dir", type=Path)
    sp.add_argument("--jql")

    sp = sub.add_parser("workspace", help="prepare the work tree for an agent")
    sp.add_argument("--dir", type=Path, required=True)

    sp = sub.add_parser("org", help="set up or tear down the agent's org")
    sp.add_argument("action", choices=["up", "down"])
    sp.add_argument("--for", dest="purpose", choices=["spec", "build"])
    sp.add_argument("--dir", type=Path)

    for name, actions in (("spec", ["prepare", "run", "publish", "notify"]),
                          ("build", ["prepare", "run", "publish", "notify", "stopped"]),
                          ("review", ["prepare", "run", "publish"])):
        sp = sub.add_parser(name, help=f"{name} agent job steps")
        sp.add_argument("action", choices=actions)
        sp.add_argument("--key")
        sp.add_argument("--task")
        sp.add_argument("--mode", default="auto")
        sp.add_argument("--pr")
        sp.add_argument("--dir", type=Path)
        sp.add_argument("--org-ready", default="false")

    sp = sub.add_parser("guard", help="stop 6: scope, spec and docs checks for a pull request")
    sp.add_argument("--dir", type=Path, required=True)
    sp.add_argument("--base-ref", required=True)
    sp.add_argument("--head-ref", required=True)

    sp = sub.add_parser("ci", help="stop 6: static checks, or validation in a scratch org or the sandbox")
    sp.add_argument("action", choices=["static", "scratch", "sandbox"])
    sp.add_argument("--dir", type=Path, required=True)
    sp.add_argument("--base-ref")

    sp = sub.add_parser("smoke", help="Step 1 check: identities and the model")
    sp.add_argument("checks", nargs="+", choices=["jira", "model", "devhub", "spec", "ci"])
    sp.add_argument("--dir", type=Path, default=Path("."))

    sp = sub.add_parser("failed", help="tell Jira that a factory run failed")
    sp.add_argument("--key", required=True)
    sp.add_argument("--stage", required=True)

    sp = sub.add_parser("lint", help="lint a spec file")
    sp.add_argument("file", type=Path)
    sp.add_argument("--key")

    sp = sub.add_parser("grounding", help="check a spec's metadata references")
    sp.add_argument("file", type=Path)
    sp.add_argument("--dir", type=Path, default=Path("."))
    sp.add_argument("--org")

    sp = sub.add_parser("docs-check", help="check feature docs for the changes since a base ref")
    sp.add_argument("--dir", type=Path, default=Path("."))
    sp.add_argument("--base-ref", required=True)

    sp = sub.add_parser("scope", help="check uncommitted changes against a task's allowed paths")
    sp.add_argument("--dir", type=Path, default=Path("."))
    sp.add_argument("--spec", type=Path, required=True)
    sp.add_argument("--task", required=True)

    sp = sub.add_parser("replay", help="create the poc/<KEY> base branch for a replayed ticket (run locally)")
    sp.add_argument("--key", required=True)
    sp.add_argument("--before", required=True, help="the commit just before the human change")
    sp.add_argument("--kit-ref", default="main")
    sp.add_argument("--extra", nargs="*", default=[], help="more files to copy, such as ADRs that predate the ticket")
    sp.add_argument("--push", action="store_true")

    args = p.parse_args(argv)
    policy = load_policy()
    try:
        return _dispatch(args, policy)
    except FactoryError as exc:
        print(f"::error::{exc}")
        return 1


def _dispatch(args, policy) -> int:
    cmd = args.cmd
    if cmd == "intake":
        intake.poll(policy)
    elif cmd == "route":
        return route.main()
    elif cmd == "plan":
        plan.run_next(args.key, policy)
    elif cmd == "ticket" and args.action == "fetch":
        info = ticket.fetch(require_key(args.key), args.dir / ".factory-out", policy)
        publish.save_state("redactions", info["redactions"])
        step_summary(f"Ticket {args.key} fetched. Redacted: {info['redactions'] or 'nothing'}.")
    elif cmd == "ticket":
        if not args.jql:
            raise FactoryError("--jql is required for screen")
        for key, counts in ticket.screen(args.jql):
            print(f"{key}\t{'clean' if not counts else counts}")
    elif cmd == "workspace":
        publish.init_workspace(args.dir)
    elif cmd == "org" and args.action == "up":
        return _org_up(args.purpose, args.dir, policy)
    elif cmd == "org":
        return _org_down()
    elif cmd == "spec":
        if args.action == "prepare":
            spec_job.prepare(args.key, args.mode, args.pr, policy)
        elif args.action == "run":
            spec_job.run(args.dir, policy, _truthy(args.org_ready))
        elif args.action == "publish":
            spec_job.publish(args.dir, policy)
        else:
            spec_job.notify(policy)
    elif cmd == "build":
        if args.action == "prepare":
            build_job.prepare(args.key, args.task, args.mode, args.pr, policy)
        elif args.action == "run":
            build_job.run(args.dir, policy)
        elif args.action == "publish":
            build_job.publish(args.dir, policy)
        elif args.action == "notify":
            build_job.notify(policy)
        else:
            build_job.stopped(policy)
    elif cmd == "review":
        if args.action == "prepare":
            review_job.prepare(args.pr, policy)
        elif args.action == "run":
            review_job.run(args.dir, policy)
        else:
            review_job.publish(policy)
    elif cmd == "guard":
        ci.fetch_base(args.dir, args.base_ref)
        return ci.guard(args.dir, args.base_ref, args.head_ref, policy)
    elif cmd == "ci":
        if args.action == "scratch":
            return ci.scratch(args.dir, policy)
        if not args.base_ref:
            raise FactoryError("--base-ref is required")
        ci.fetch_base(args.dir, args.base_ref)
        if args.action == "static":
            return ci.static(args.dir, args.base_ref, policy)
        return ci.sandbox(args.dir, args.base_ref, policy)
    elif cmd == "smoke":
        return smoke.main(args.checks, args.dir, policy)
    elif cmd == "failed":
        key = require_key(args.key)
        Jira.from_env().comment(key, f"The factory's {args.stage} run failed and needs a person: {run_url()}")
        Jira.from_env().labels(key, add=[policy.get("intake.needs_human_label")])
    elif cmd == "lint":
        errors = specmod.lint(specmod.load(args.file), policy, args.key)
        print("\n".join(errors) or "Spec lint passed.")
        return 1 if errors else 0
    elif cmd == "grounding":
        results = grounding.check(specmod.load(args.file), args.dir, package_dirs(args.dir),
                                  grounding.OrgLookup(args.org) if args.org else None)
        print(grounding.report(results))
        return 1 if any(r.is_error for r in results) else 0
    elif cmd == "docs-check":
        errors, warnings = docs_check.check(scope.branch_changes(args.dir, args.base_ref), args.dir,
                                            package_dirs(args.dir), policy)
        print(docs_check.report(errors, warnings))
        return 1 if errors else 0
    elif cmd == "scope":
        task = specmod.load(args.spec).task(args.task)
        found = scope.violations([p for _, p in scope.worktree_changes(args.dir)],
                                 *scope.rules_for("build", policy, "LOCAL-1", task.allowed))
        print(scope.report(found))
        return 1 if found else 0
    elif cmd == "replay":
        branch = replay.prepare(args.key, args.before, args.kit_ref, args.extra, args.push)
        print(f"Created {branch}" + (" and pushed it" if args.push else "; push it with --push or git push"))
    return 0


def _truthy(value: str) -> bool:
    return str(value).lower() in {"1", "true", "yes"}


def run() -> None:
    sys.exit(main())


if __name__ == "__main__":
    run()
