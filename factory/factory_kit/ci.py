"""Stop 6, CI guard: the checks that run on every pull request before any job with credentials.

The guard runs without secrets. Validation jobs (deploys and tests) only start when it passes.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import docs_check, grounding, scope
from . import spec as specmod
from .policy import Policy
from .util import FactoryError, gh_output, package_dirs, parse_branch, run, step_summary

BUNDLE_DIRS = ("lwc", "aura", "experiences", "staticresources", "waveTemplates")


def guard(workdir: Path, base_ref: str, head_ref: str, policy: Policy) -> int:
    info = parse_branch(head_ref)
    kind, key, task = info["kind"], info["key"], info["task"]
    changes = scope.branch_changes(workdir, f"origin/{base_ref}")
    sections, errors = [f"## Factory guard\n\nPull request kind: **{kind}**" + (f" ({key})" if key else "")], []

    if kind == "spec":
        found = scope.violations([p for _, p in changes], *scope.rules_for("spec", policy, key))
        errors += [f"{p}: {why}" for p, why in found]
        sections.append(scope.report(found))
        spec_file = workdir / f"docs/specs/{key}.md"
        if not spec_file.exists():
            errors.append(f"docs/specs/{key}.md is missing")
        else:
            parsed = specmod.load(spec_file)
            lint = specmod.lint(parsed, policy, key)
            errors += lint
            sections.append("### Spec lint\n\n" + ("\n".join(f"- {e}" for e in lint) or "Passed."))
            results = grounding.check(parsed, workdir, package_dirs(workdir))
            errors += [f"{r.ref.type} {r.ref.name}: {r.detail}" for r in results if r.is_error]
            sections.append("### Grounding (source)\n\n" + grounding.report(results))
    elif kind == "build":
        text = run(["git", "show", f"origin/{base_ref}:docs/specs/{key}.md"], cwd=workdir, check=False)
        if text.returncode != 0:
            errors.append(f"No approved spec docs/specs/{key}.md on {base_ref}")
        else:
            try:
                t = specmod.parse(text.stdout).task(task)
                found = scope.violations([p for _, p in changes], *scope.rules_for("build", policy, key, t.allowed))
                errors += [f"{p}: {why}" for p, why in found]
                sections.append(scope.report(found))
            except FactoryError as exc:
                errors.append(str(exc))

    pkgs = package_dirs(workdir)
    doc_errors, doc_warnings = docs_check.check(changes, workdir, pkgs, policy)
    errors += doc_errors
    sections.append("### Docs\n\n" + docs_check.report(doc_errors, doc_warnings))

    sources = deploy_paths(changes, pkgs)
    (workdir / ".factory-out").mkdir(exist_ok=True)
    (workdir / ".factory-out" / "deploy-paths.txt").write_text("\n".join(sources) + "\n", encoding="utf-8")
    changed = [p for s, p in changes if s != "D"]
    gh_output(kind=kind, key=key or "", task=task or "", source_changed=str(bool(sources)).lower(),
              has_lwc=str(any("/lwc/" in p for p in changed)).lower(),
              changed_files="\n".join(changed))
    step_summary("\n\n".join(sections) + ("\n\n**Guard failed.**" if errors else "\n\n**Guard passed.**"))
    for e in errors:
        print(f"::error::{e}")
    return 1 if errors else 0


def deploy_paths(changes: list[tuple[str, str]], pkgs: list[str]) -> list[str]:
    """Paths for a check-only deploy of the changed source. Bundle files deploy as their bundle folder."""
    out = []
    for status, path in changes:
        if status == "D" or not any(path.startswith(p + "/") for p in pkgs):
            continue
        parts = path.split("/")
        for i, part in enumerate(parts[:-1]):
            if part in BUNDLE_DIRS and i + 1 < len(parts) - 1:
                path = "/".join(parts[:i + 2])
                break
        out.append(path)
    return sorted(set(out))


def fetch_base(workdir: Path, base_ref: str) -> None:
    """Make origin/<base> available. CI checks out with full history, so this is normally already there."""
    if run(["git", "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{base_ref}"], cwd=workdir,
           check=False).returncode == 0:
        return
    proc = run(["git", "fetch", "-q", "--no-tags", "origin",
                f"+refs/heads/{base_ref}:refs/remotes/origin/{base_ref}"], cwd=workdir, check=False)
    if proc.returncode != 0:
        raise FactoryError(f"origin/{base_ref} isn't available; check out the pull request with fetch-depth: 0")


ANALYZABLE = (".cls", ".trigger", ".js", ".html", ".page", ".component", ".flow-meta.xml")


def static(workdir: Path, base_ref: str, policy: Policy) -> int:
    """Jest and Code Analyzer on the changed source. Runs without secrets."""
    changes = scope.branch_changes(workdir, f"origin/{base_ref}")
    pkgs = package_dirs(workdir)
    files = [p for s, p in changes if s != "D" and any(p.startswith(d + "/") for d in pkgs)]
    failures, notes = [], []

    if any("/lwc/" in p for p in files):
        pkg = workdir / "package.json"
        scripts = (json.loads(pkg.read_text(encoding="utf-8")).get("scripts") or {}) if pkg.exists() else {}
        if "test:unit" not in scripts:
            failures.append("LWC files changed, but package.json has no test:unit script, so Jest can't run")
        else:
            install = ["npm", "ci", "--ignore-scripts"] if (workdir / "package-lock.json").exists() else \
                ["npm", "install", "--ignore-scripts", "--no-save"]
            proc = run(install, cwd=workdir, check=False, timeout=1200)
            proc = proc if proc.returncode else run(["npm", "run", "test:unit"], cwd=workdir,
                                                    check=False, timeout=1800)
            print(proc.stdout[-20000:], proc.stderr[-20000:])
            (failures if proc.returncode else notes).append("Jest " + ("failed" if proc.returncode else "passed"))

    targets = [p for p in files if p.endswith(ANALYZABLE) and "/__tests__/" not in p]
    if targets:
        args = ["sf", "code-analyzer", "run", "--workspace", ".", "--rule-selector",
                str(policy.get("ci.code_analyzer_rule_selector")), "--severity-threshold",
                str(policy.get("ci.code_analyzer_severity_threshold")),
                "--output-file", ".factory-out/code-analyzer.json", "--output-file", ".factory-out/code-analyzer.html"]
        for t in targets:
            args += ["--target", t]
        (workdir / ".factory-out").mkdir(exist_ok=True)
        proc = run(args, cwd=workdir, check=False, timeout=1800)
        print(proc.stdout[-20000:], proc.stderr[-5000:])
        (failures if proc.returncode else notes).append(
            f"Code Analyzer on {len(targets)} file(s) " + ("found findings at or above the threshold" if proc.returncode
                                                           else "passed"))
    step_summary("## Static checks\n\n" + ("\n".join(f"- {n}" for n in notes + failures) or "Nothing to check."))
    for f in failures:
        print(f"::error::{f}")
    return 1 if failures else 0


def _test_summary(data: dict) -> tuple[bool, str]:
    result = data.get("result") or {}
    summary = result.get("summary") or {}
    fails = [t for t in result.get("tests") or [] if t.get("Outcome") not in {"Pass", "Skip"}]
    lines = [f"Apex tests: {summary.get('outcome', '?')}, {summary.get('passing', '?')} passed, "
             f"{summary.get('failing', '?')} failed, org-wide coverage {summary.get('orgWideCoverage', '?')}"]
    lines += [f"- {t.get('FullName')}: {(t.get('Message') or '')[:300]}" for t in fails[:30]]
    return data.get("status") == 0 and not fails, "\n".join(lines)


def scratch(workdir: Path, policy: Policy) -> int:
    """Replay pull requests: deploy everything to a fresh scratch org built from the merge commit, run local tests."""
    from . import orgs
    alias, ok, report = "ci-org", False, ""
    orgs.login("devhub", "devhub")
    try:
        orgs.create_scratch(alias, workdir, policy)
        deployed, note = orgs.deploy(alias, workdir)
        report = note
        if deployed:
            proc = run(["sf", "apex", "run", "test", "--target-org", alias, "--test-level",
                        str(policy.get("ci.test_level")), "--code-coverage", "--result-format", "json",
                        "--output-dir", ".factory-out/test-results", "--wait", "60"],
                       cwd=workdir, check=False, timeout=4200)
            try:
                ok, tests = _test_summary(json.loads(proc.stdout or "{}"))
            except json.JSONDecodeError:
                ok, tests = False, proc.stdout[-3000:] or proc.stderr[-3000:]
            report += "\n\n" + tests
    finally:
        orgs.delete_scratch(alias)
        orgs.logout("devhub")
    step_summary("## Scratch org validation\n\n" + report)
    print(report)
    return 0 if ok else 1


def sandbox(workdir: Path, base_ref: str, policy: Policy) -> int:
    """Pull requests to the default branch: check-only deploy of the changed source to the integration sandbox."""
    from . import orgs
    changes = scope.branch_changes(workdir, f"origin/{base_ref}")
    paths = deploy_paths(changes, package_dirs(workdir))
    if not paths:
        step_summary("## Sandbox validation\n\nNo source changes to validate.")
        return 0
    orgs.login("ci", "ci-sandbox")
    try:
        args = ["sf", "project", "deploy", "validate", "--target-org", "ci-sandbox", "--test-level",
                str(policy.get("ci.test_level")), "--wait", "120", "--json"]
        for p in paths:
            args += ["--source-dir", p]
        proc = run(args, cwd=workdir, check=False, timeout=7500)
    finally:
        orgs.logout("ci-sandbox")
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        data = {"status": 1, "message": proc.stderr[-3000:]}
    result = data.get("result") or {}
    failures = [f for f in result.get("files") or [] if f.get("state") == "Failed"]
    tests = ((result.get("details") or {}).get("runTestResult") or {}).get("failures") or []
    tests = tests if isinstance(tests, list) else [tests]
    lines = [f"Check-only deploy of {len(paths)} path(s): {'passed' if data.get('status') == 0 else 'failed'}. "
             f"{data.get('message') or ''}"]
    lines += [f"- {f.get('type')} {f.get('fullName')}: {f.get('error')}" for f in failures[:30]]
    lines += [f"- Test {t.get('name')}.{t.get('methodName')}: {(t.get('message') or '')[:300]}" for t in tests[:30]]
    step_summary("## Sandbox validation\n\n" + "\n".join(lines))
    print("\n".join(lines))
    return 0 if data.get("status") == 0 else 1
