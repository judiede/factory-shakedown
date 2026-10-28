"""Stage reports to the Slack control panel (control panel TASKS P3, DECISIONS D12).

At each stop of the route the kit tells the factory org where a ticket is (POST /factory/v1/items); the org records
the work item, and the Slack card follows it. Best effort: a report that fails is a warning in the run log, never a
reason to stop the factory. Off while the control panel isn't connected (control_panel.landscape).
"""

from __future__ import annotations

from . import controlpanel
from .policy import Policy

# What the control panel's card shows after Gate 2: UAT is the next stop, and the PoC ends before it.
AFTER_GATE2 = "All tasks merged at Gate 2. UAT comes next; it isn't part of the factory PoC."


def report(policy: Policy, key: str, stage: str, status: str = "ACTIVE", note: str | None = None,
           **links: str | None) -> bool:
    """Reports one stop. links: title, prUrl, specPrUrl; empty ones are left out, so the org keeps what it had.
    Returns whether the control panel got the report."""
    landscape = controlpanel.landscape(policy)
    if not landscape:
        return False
    body = {"key": key, "landscape": landscape, "stage": stage, "status": status}
    if note:
        body["note"] = note[:255]
    body.update({name: value for name, value in links.items() if value})
    try:
        _post(body)
    except Exception as exc:  # noqa: BLE001 - reporting never stops the factory
        # Only the error's type, as in switch.py: the logs of a public repository are public.
        print(f"::warning::The control panel didn't get the {stage} report for {key} ({type(exc).__name__}).")
        return False
    return True


def _post(body: dict) -> dict:
    """Sends one report. Tests replace this."""
    return controlpanel.call("POST", "/items", body)
