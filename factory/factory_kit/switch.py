"""Kill switch from the Slack control panel (control panel TASKS P2).

Before the factory starts work (intake, the next build task, a spec, build or review run), it asks the factory org
whether this repository's landscape, or the whole factory, is paused: GET /factory/v1/switch?landscape=<code>.

Off unless factory-policy.yml names the landscape under control_panel.landscape. Once on, the check fails closed: if
the factory org can't be asked, no new work starts. The repository variable FACTORY_ENABLED stays the hard off.
"""

from __future__ import annotations

import urllib.parse

from . import controlpanel
from .policy import Policy
from .util import gh_output, step_summary

# One answer per landscape and process: a job asks once, however many times it checks.
_answers: dict[str, str | None] = {}


def paused(policy: Policy) -> str | None:
    """Why the factory must not start work now, or None when it may."""
    landscape = controlpanel.landscape(policy)
    if not landscape:
        return None
    if landscape not in _answers:
        _answers[landscape] = _reason(landscape)
    return _answers[landscape]


def stop_run(reason: str) -> dict:
    """Ends a run before it does anything. Every later workflow step checks the stop output; paused tells the
    steps that report budget stops apart from a pause, which is not a failure and needs no person."""
    gh_output(stop="true", paused="true", reason=reason)
    step_summary(f"## Factory paused\n\nThis run did nothing: {reason}.")
    return {"stop": True, "paused": True, "reason": reason}


def _reason(landscape: str) -> str | None:
    try:
        answer = _ask(landscape)
    except Exception as exc:  # noqa: BLE001 - any failure means "can't confirm it's running", so fail closed
        # Only the error's type: the message can carry the org's URL, and the logs of a public repository are public.
        return (f"the control panel couldn't be asked whether {landscape} is paused ({type(exc).__name__}), "
                "so no new work starts")
    if not answer.get("paused"):
        return None
    scope = "the whole factory" if answer.get("scope") == "GLOBAL" else landscape
    why = f" ({answer['reason']})" if answer.get("reason") else ""
    return f"{scope} is paused in the control panel{why}"


def _ask(landscape: str) -> dict:
    """The factory org's answer for one landscape. Tests replace this."""
    return controlpanel.call("GET", "/switch?" + urllib.parse.urlencode({"landscape": landscape}))
