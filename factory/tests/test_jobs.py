"""Job-level tests: the spec and build run steps with a fake claude CLI, and committing with trailers."""

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from factory_kit import build_job, publish, scope, spec_job, trailers, util  # noqa: E402
from factory_kit.policy import Policy  # noqa: E402
from test_kit import SPEC, write  # noqa: E402

FAKE = Path(__file__).with_name("fake_claude.py")


class JobTests(unittest.TestCase):
    def setUp(self):
        self._env = dict(os.environ)
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        os.environ.update(GITHUB_WORKSPACE=str(self.root), RUNNER_TEMP=str(self.root / "rt"),
                          FACTORY_CLAUDE_BIN=json.dumps([sys.executable, str(FAKE)]))
        os.environ.pop("GITHUB_OUTPUT", None)
        os.environ.pop("GITHUB_STEP_SUMMARY", None)
        self.work = self.root / "work"
        self.work.mkdir()
        util.git("init", "-q", cwd=self.work)
        write(self.work, "sfdx-project.json", '{"packageDirectories": [{"path": "force-app", "default": true}]}')
        write(self.work, "force-app/main/default/classes/AccountService.cls", "public with sharing class AccountService {}")
        util.git("add", "-A", cwd=self.work)
        util.git("-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "base", cwd=self.work)
        publish.init_workspace(self.work)
        self.spec_src = self.root / "spec.md"
        self.spec_src.write_text(SPEC, encoding="utf-8")

    def tearDown(self):
        os.environ.clear()
        os.environ.update(self._env)
        self._tmp.cleanup()

    def act(self, *items: str) -> None:
        os.environ["FAKE_CLAUDE_ACTION"] = ";".join(items)

    def spec_context(self):
        publish.save_state("context", {"key": "SALES-412", "mode": "new", "base": "main", "round": 1,
                                       "max_cost": 8.0, "branch": "spec/SALES-412", "pr": None})

    def build_context(self, mode="build"):
        publish.save_state("context", {"key": "SALES-412", "task": "c", "title": "LWC grid", "work_type": "medium",
                                       "allowed": ["force-app/main/default/lwc/forecastGrid/**"], "base": "main",
                                       "mode": mode, "attempt": 0, "max_cost": 10.0, "pr": None,
                                       "branch": "feature/SALES-412-c-lwc-grid"})

    def test_spec_ready(self):
        self.spec_context()
        self.act(f"write:docs/specs/SALES-412.md={self.spec_src}", "write:.factory-out/summary.md")
        result = spec_job.run(self.work, Policy(), org_ready=False)
        self.assertEqual(result["outcome"], "spec_ready", result)
        self.assertEqual(result["agent"]["cost_usd"], 0.4321)
        self.assertEqual(result["agent"]["tokens"]["input"], 1000)
        seen = json.loads((self.work / ".factory-out" / "args.json").read_text(encoding="utf-8"))
        self.assertIn("Edit(./docs/specs/SALES-412.md)", seen["settings"]["permissions"]["allow"])
        for flag in ("--permission-mode", "dontAsk", "--setting-sources", "--strict-mcp-config", "--max-budget-usd"):
            self.assertIn(flag, seen["args"])
        self.assertEqual(seen["args"][seen["args"].index("--model") + 1], "claude-opus-5-5")
        self.assertTrue((self.root / "rt" / "factory-logs" / "transcript.jsonl").exists())
        self.assertTrue((self.root / "rt" / "factory-logs" / "prompt.md").read_text(encoding="utf-8").strip())

    def test_spec_questions_and_scope(self):
        self.spec_context()
        questions = self.root / "q.md"
        questions.write_text(SPEC.replace("None.", "1. Which currency?"), encoding="utf-8")
        self.act(f"write:docs/specs/SALES-412.md={questions}")
        self.assertEqual(spec_job.run(self.work, Policy(), False)["outcome"], "questions")
        self.act(f"write:docs/specs/SALES-412.md={self.spec_src}", "write:force-app/main/default/classes/Sneaky.cls")
        result = spec_job.run(self.work, Policy(), False)
        self.assertEqual(result["outcome"], "scope_violation")

    def test_spec_grounding_failure(self):
        self.spec_context()
        bad = self.root / "bad.md"
        bad.write_text(SPEC.replace("| ApexClass | AccountService | existing |", "| ApexClass | AcountService | existing |"),
                       encoding="utf-8")
        self.act(f"write:docs/specs/SALES-412.md={bad}")
        result = spec_job.run(self.work, Policy(), False)
        self.assertEqual(result["outcome"], "checks_failed")
        self.assertEqual(result["grounding_errors"], 1)

    def test_spec_discussion(self):
        publish.save_state("context", {"key": "SALES-412", "mode": "discuss", "base": "main", "round": 1,
                                       "max_cost": 1.5, "branch": "spec/SALES-412", "pr": 5, "turn": 1,
                                       "questions": [3]})
        self.act("write:.factory-out/reply.md")
        result = spec_job.run(self.work, Policy(), False)
        self.assertEqual((result["outcome"], result["reply"]), ("answered", "x"))
        seen = json.loads((self.work / ".factory-out" / "args.json").read_text(encoding="utf-8"))
        self.assertNotIn("Edit(./docs/specs/SALES-412.md)", seen["settings"]["permissions"]["allow"])
        self.assertEqual(seen["args"][seen["args"].index("--max-budget-usd") + 1], "1.50")
        self.assertIn("questions.md", (self.root / "rt" / "factory-logs" / "prompt.md").read_text(encoding="utf-8"))
        self.act("write:docs/specs/SALES-412.md")
        self.assertEqual(spec_job.run(self.work, Policy(), False)["outcome"], "scope_violation")

    def test_build_outcomes(self):
        self.build_context()
        self.act("write:force-app/main/default/lwc/forecastGrid/forecastGrid.js", "write:docs/features/forecast-grid.md",
                 "write:.sf/config.json")
        result = build_job.run(self.work, Policy())
        self.assertEqual(result["outcome"], "changes", result)
        self.assertEqual(sorted(result["changed"]), ["docs/features/forecast-grid.md",
                                                     "force-app/main/default/lwc/forecastGrid/forecastGrid.js"])
        seen = json.loads((self.work / ".factory-out" / "args.json").read_text(encoding="utf-8"))
        self.assertEqual(seen["args"][seen["args"].index("--model") + 1], "claude-sonnet-5-5")

        self.act("write:.factory-out/spec-problem.md")
        self.assertEqual(build_job.run(self.work, Policy())["outcome"], "needs_spec_change")

        self.act("write:force-app/main/default/classes/Other.cls")
        self.assertEqual(build_job.run(self.work, Policy())["outcome"], "scope_violation")

    def test_build_timeout(self):
        self.build_context()
        for p in scope.worktree_changes(self.work):
            (self.work / p[1]).unlink()
        self.act("sleep:5")
        policy = Policy({"budgets": {"medium": {"time_minutes": 0.01}}})
        result = build_job.run(self.work, policy)
        self.assertEqual(result["agent"]["outcome"], "timeout")
        self.assertEqual(result["outcome"], "no_changes")

    def test_commit_and_push_with_trailers(self):
        bare = self.root / "remote.git"
        util.git("init", "-q", "--bare", str(bare), cwd=self.root)
        util.git("remote", "add", "origin", str(bare), cwd=self.work)
        os.environ["GH_TOKEN"] = "test-token"
        write(self.work, "force-app/main/default/lwc/forecastGrid/forecastGrid.js")
        write(self.work, ".factory-out/summary.md")
        write(self.work, ".sf/config.json")
        msg = publish.message("SALES-412: LWC grid", "Built it.", agent="build", mode="build", task="SALES-412/c",
                              attempt=0, cost_usd="0.4321")
        publish.commit_and_push(self.work, "feature/SALES-412-c-lwc-grid", msg)
        body = util.git("--git-dir", str(bare), "log", "-1", "--format=%B", "feature/SALES-412-c-lwc-grid")
        self.assertEqual(trailers.parse(body)["Factory-Cost-USD"], ["0.4321"])
        files = util.git("--git-dir", str(bare), "ls-tree", "-r", "--name-only", "feature/SALES-412-c-lwc-grid")
        self.assertNotIn(".factory-out", files)
        self.assertNotIn(".sf/", files)
        self.assertIn("forecastGrid.js", files)


    def test_results_branch(self):
        from factory_kit import results
        bare = self.root / "remote.git"
        util.git("init", "-q", "--bare", str(bare), cwd=self.root)
        os.environ.update(GH_TOKEN="test-token", GITHUB_SERVER_URL=self.root.as_posix(), GITHUB_REPOSITORY="remote")
        rec = results.record("build", "build", "SALES-412", "c", {"model": "m", "cost_usd": 0.5}, "changes", pr_url=None)
        first = results.push_record(rec, "factory-results")
        results.push({"screenshots/SALES-412/c/x.png": b"\x89PNG"}, "shots", "factory-results")
        files = util.git("--git-dir", str(bare), "ls-tree", "-r", "--name-only", "factory-results")
        self.assertIn(first, files)
        self.assertIn("screenshots/SALES-412/c/x.png", files)
        stored = json.loads(util.git("--git-dir", str(bare), "show", f"factory-results:{first}"))
        self.assertEqual((stored["ticket"], stored["cost_usd"], stored["schema"]), ("SALES-412", 0.5, 1))


if __name__ == "__main__":
    unittest.main()
