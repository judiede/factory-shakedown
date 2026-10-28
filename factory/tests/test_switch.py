"""Kill switch tests (control panel TASKS P2): the factory asks the factory org before it starts work."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from factory_kit import build_job, github, intake, review_job, spec_job, switch  # noqa: E402
from factory_kit.policy import Policy  # noqa: E402

# The factory org's answers by landscape: TEST_A is paused, TEST_B runs.
ANSWERS = {
    "TEST_A": {"paused": True, "scope": "TEST_A", "reason": "Release freeze"},
    "TEST_B": {"paused": False, "scope": None, "reason": None},
}


def policy(landscape: str | None) -> Policy:
    return Policy({"control_panel": {"landscape": landscape}})


def no_github(*args, **kwargs):
    raise AssertionError("A paused run must not call GitHub")


class SwitchTests(unittest.TestCase):
    def setUp(self):
        switch._answers.clear()
        self.asked: list[str] = []

        def ask(landscape):
            self.asked.append(landscape)
            return ANSWERS[landscape]

        for target, name, replacement in ((switch, "_ask", ask), (github, "gh", no_github), (github, "run", no_github)):
            patcher = mock.patch.object(target, name, side_effect=replacement)
            setattr(self, f"patched_{name.strip('_')}", patcher.start())
            self.addCleanup(patcher.stop)

        self._env = dict(os.environ)
        self.addCleanup(self._restore_env)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.output = Path(tmp.name) / "output"
        self.summary = Path(tmp.name) / "summary"
        self.output.write_text("", encoding="utf-8")
        self.summary.write_text("", encoding="utf-8")
        os.environ.update(GITHUB_OUTPUT=str(self.output), GITHUB_STEP_SUMMARY=str(self.summary),
                          RUNNER_TEMP=tmp.name, GITHUB_WORKSPACE=tmp.name, GITHUB_REPOSITORY="example/repo")

    def _restore_env(self):
        os.environ.clear()
        os.environ.update(self._env)

    def test_is_off_until_the_policy_names_a_landscape(self):
        self.assertIsNone(switch.paused(Policy()))
        self.assertIsNone(switch.paused(policy("")))
        self.assertEqual(self.asked, [], "Without a landscape nobody is asked")

    def test_pausing_one_landscape_stops_its_work_but_not_another_landscapes(self):
        self.assertEqual(switch.paused(policy("TEST_A")), "TEST_A is paused in the control panel (Release freeze)")
        self.assertIsNone(switch.paused(policy("TEST_B")), "TEST_B keeps running")

    def test_a_global_pause_stops_every_landscape(self):
        self.patched_ask.side_effect = lambda landscape: {"paused": True, "scope": "GLOBAL", "reason": None}
        self.assertEqual(switch.paused(policy("TEST_B")), "the whole factory is paused in the control panel")

    def test_fails_closed_without_putting_the_org_url_in_public_logs(self):
        self.patched_ask.side_effect = OSError("https://example.my.salesforce.com is unreachable")
        reason = switch.paused(policy("TEST_B"))
        self.assertIn("couldn't be asked whether TEST_B is paused (OSError)", reason)
        self.assertIn("no new work starts", reason)
        self.assertNotIn("salesforce.com", reason)

    def test_asks_once_per_job(self):
        switch.paused(policy("TEST_A"))
        switch.paused(policy("TEST_A"))
        self.assertEqual(self.asked, ["TEST_A"])

    def test_intake_starts_no_tickets_while_paused(self):
        jira = mock.Mock()
        started = intake.poll(policy("TEST_A"), jira=jira)
        self.assertEqual(started, [])
        self.assertEqual(jira.mock_calls, [], "Tickets keep their ready label for the first poll after the resume")
        self.assertIn("No tickets started: TEST_A is paused", self.summary.read_text(encoding="utf-8"))

    def test_spec_build_and_review_runs_stop_without_asking_for_a_person(self):
        runs = {
            "spec": lambda p: spec_job.prepare("SALES-412", "auto", None, p),
            "build": lambda p: build_job.prepare("SALES-412", "c", "build", None, p),
            "review": lambda p: review_job.prepare("7", p),
        }
        for name, prepare in runs.items():
            with self.subTest(name):
                self.output.write_text("", encoding="utf-8")
                ctx = prepare(policy("TEST_A"))
                outputs = self.output.read_text(encoding="utf-8")
                self.assertTrue(ctx["stop"])
                self.assertIn("stop=true", outputs)
                self.assertIn("paused=true", outputs, "so the budget-stop step stays quiet")
                self.assertIn("reason=TEST_A is paused in the control panel (Release freeze)", outputs)

    def test_a_running_landscape_lets_the_run_go_on(self):
        # The first GitHub call after the check shows the run went on; the no_github guard stops it right there.
        with self.assertRaisesRegex(AssertionError, "must not call GitHub"):
            review_job.prepare("7", policy("TEST_B"))


if __name__ == "__main__":
    unittest.main()
