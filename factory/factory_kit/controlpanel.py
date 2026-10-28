"""The factory's line to the Slack control panel's factory org: the kill switch (switch.py) and stage reports
(progress.py).

Off until factory-policy.yml names this repository's landscape under control_panel.landscape. The kit logs in once
per job with the SF_FACTORY_* identity and calls the /factory/v1 REST API. The access token is never logged.
"""

from __future__ import annotations

import json
import urllib.request

from . import orgs
from .policy import Policy

ALIAS = "factory"

_access: tuple[str, str] | None = None


def landscape(policy: Policy) -> str | None:
    """This repository's landscape code, or None while the control panel isn't connected."""
    return policy.get("control_panel.landscape") or None


def call(method: str, path: str, body: dict | None = None) -> dict:
    """One /factory/v1 call, for example call("GET", "/switch?landscape=X"). Raises on any failure."""
    global _access
    if _access is None:
        with orgs.session("factory", ALIAS):
            _access = orgs.access(ALIAS)
    instance_url, token = _access
    request = urllib.request.Request(
        f"{instance_url}/services/apexrest/factory/v1{path}",
        data=None if body is None else json.dumps(body).encode("utf-8"),
        method=method,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read().decode("utf-8"))
