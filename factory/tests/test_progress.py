"""Stage report tests (control panel TASKS P3): the kit tells the factory org where a ticket is at each stop."""

import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from factory_kit import build_job, intake, progress, review_job, spec_job, switch  # noqa: E402
from factory_kit.policy import Policy  # noqa: E402
from factory_kit.publish import save_state  # noqa: E402

CONNECTED = Policy({"control_panel": {"landscape": "TEST_A"}})


class ProgressTests(unittest.TestCase):
    def setUp(self):
        switch._answers.clear()
        self.reports: list[dict] = []
        patcher = mock.patch.object(progress, "_post", side_effect=self.reports.append)
        self.post = patcher.start()
        self.addCleanup(patcher.stop)
        patcher = mock.patch.object(switch, "_ask", return_value={"paused": False})
        patcher.start()
        self.addCleanup(patcher.stop)

        self._env = dict(os.environ)
        self.addCleanup(self._restore_env)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        os.environ.update(GITHUB_WORKSPACE=tmp.name, RUNNER_TEMP=tmp.name, GITHUB_REPOSITORY="example/repo",
                          GITHUB_STEP_SUMMARY=str(Path(tmp.name) / "summary"), GITHUB_OUTPUT=str(Path(tmp.name) / "out"),
                          JIRA_PROJECT="KAN")

    def _restore_env(self):
        os.environ.clear()
        os.environ.update(self._env)

    def stages(self) -> list[tuple]:
        return [(r["key"], r["stage"], r["status"]) for r in self.reports]

    # ---------------------------------------------------------------- the report itself

    def test_is_off_until_the_policy_names_a_landscape(self):
        self.assertFalse(progress.report(Policy(), "KAN-2", "SPEC"))
        self.post.assert_not_called()

    def test_sends_the_landscape_and_only_the_fields_it_has(self):
        self.assertTrue(progress.report(CONNECTED, "KAN-2", "CI", note="x" * 300, prUrl="https://github.com/p/1",
                                        specPrUrl=None, title=""))
        self.assertEqual(self.reports, [{"key": "KAN-2", "landscape": "TEST_A", "stage": "CI", "status": "ACTIVE",
                                         "note": "x" * 255, "prUrl": "https://github.com/p/1"}])

    def test_a_failed_report_is_a_warning_and_never_stops_the_factory(self):
        self.post.side_effect = OSError("https://example.my.salesforce.com refused")
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertFalse(progress.report(CONNECTED, "KAN-2", "BUILD"))
        self.assertIn("::warning::The control panel didn't get the BUILD report for KAN-2 (OSError).", out.getvalue())
        self.assertNotIn("salesforce.com", out.getvalue())

    # ---------------------------------------------------------------- the stops

    def test_intake_reports_each_ticket_it_picks_up(self):
        jira = mock.Mock()
        jira.search.return_value = [{"key": "KAN-2", "fields": {"summary": "Account hierarchy view"}}]
        with mock.patch.object(intake.github, "dispatch"):
            intake.poll(CONNECTED, jira=jira)
        self.assertEqual(self.stages(), [("KAN-2", "INTAKE", "ACTIVE")])
        self.assertEqual(self.reports[0]["title"], "Account hierarchy view")

    def spec_finished(self, outcome: str) -> None:
        save_state("context", {"key": "KAN-2", "mode": "new"})
        save_state("result", {"outcome": outcome, "questions": "Which accounts count?"})
        save_state("publish", {"pr_url": "https://github.com/example/repo/pull/3"})
        spec_job.notify(CONNECTED, jira=mock.Mock())

    def test_a_ready_spec_waits_at_gate_1(self):
        self.spec_finished("spec_ready")
        self.assertEqual(self.stages(), [("KAN-2", "GATE1", "WAITING_HUMAN")])
        self.assertEqual(self.reports[0]["specPrUrl"], "https://github.com/example/repo/pull/3")

    def test_spec_questions_wait_for_a_person(self):
        self.spec_finished("questions")
        self.assertEqual(self.stages(), [("KAN-2", "SPEC", "WAITING_HUMAN")])

    def test_a_failed_spec_is_blocked(self):
        self.spec_finished("agent_failed")
        self.assertEqual(self.stages(), [("KAN-2", "SPEC", "BLOCKED")])

    def build_finished(self, mode: str, outcome: str) -> None:
        save_state("context", {"key": "KAN-2", "task": "a", "title": "Hierarchy component", "mode": mode})
        save_state("result", {"outcome": outcome, "spec_problem": "The field doesn't exist."})
        save_state("publish", {"pr_url": "https://github.com/example/repo/pull/4"})
        build_job.notify(CONNECTED, jira=mock.Mock())

    def test_a_new_pull_request_goes_to_ci(self):
        self.build_finished("build", "changes")
        self.assertEqual(self.stages(), [("KAN-2", "CI", "ACTIVE")])
        self.assertEqual(self.reports[0]["note"], "Task a (Hierarchy component): pull request opened; CI is checking it.")
        self.assertEqual(self.reports[0]["prUrl"], "https://github.com/example/repo/pull/4")

    def test_a_fix_goes_back_to_ci(self):
        self.build_finished("fix", "changes")
        self.assertEqual(self.reports[0]["note"], "Task a (Hierarchy component): changes pushed; CI is checking it.")

    def test_a_build_that_needs_a_person_is_blocked(self):
        self.build_finished("build", "scope_violation")
        self.assertEqual(self.stages(), [("KAN-2", "BUILD", "BLOCKED")])

    def test_a_posted_review_waits_at_gate_2(self):
        save_state("context", {"key": "KAN-2", "task": "a", "pr": 4, "sha": "abc"})
        save_state("result", {"outcome": "reviewed", "agent": {},
                              "review": {"summary": "Looks fine.", "comments": [
                                  {"path": "x.cls", "line": 1, "body": "Rename", "category": "naming"}]}})
        with mock.patch.object(review_job.github, "post_review", return_value=True), \
                mock.patch.object(review_job, "record", return_value={}), \
                mock.patch.object(review_job, "push_record"):
            review_job.publish(CONNECTED)
        self.assertEqual(self.stages(), [("KAN-2", "GATE2", "WAITING_HUMAN")])
        self.assertIn("left 1 comment(s); the code owner decides at Gate 2.", self.reports[0]["note"])
        self.assertEqual(self.reports[0]["prUrl"], "https://github.com/example/repo/pull/4")


if __name__ == "__main__":
    unittest.main()
