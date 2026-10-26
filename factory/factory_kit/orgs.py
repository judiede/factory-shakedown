"""Salesforce org setup for agent and CI jobs: JWT logins, scratch orgs and cleanup.

Each identity's private key arrives in its own environment variable, only in the step that logs in.
The key is written to a container-local temp file and deleted straight after the login.
"""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path

from .policy import Policy
from .util import FactoryError, env, run

IDENTITIES = {
    # who: (username var, client id var, login URL var, default login URL, key var)
    "devhub": ("SF_DEVHUB_USERNAME", "SF_DEVHUB_CLIENT_ID", "SF_DEVHUB_URL", "https://login.salesforce.com", "SF_DEVHUB_JWT_KEY"),
    "spec": ("SF_SPEC_USERNAME", "SF_SPEC_CLIENT_ID", "SF_SANDBOX_URL", "https://test.salesforce.com", "SF_SPEC_JWT_KEY"),
    "ci": ("SF_CI_USERNAME", "SF_CI_CLIENT_ID", "SF_SANDBOX_URL", "https://test.salesforce.com", "SF_CI_JWT_KEY"),
}


def _sf(*args: str, cwd: str | Path | None = None, timeout: int = 3600, check: bool = True) -> dict:
    proc = run(["sf", *args, "--json"], cwd=cwd, check=False, timeout=timeout)
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        data = {"status": 1, "message": proc.stdout[-2000:] or proc.stderr[-2000:]}
    if check and data.get("status") != 0:
        raise FactoryError(f"sf {' '.join(args[:3])} failed: {data.get('message') or data.get('name') or proc.stderr[-1500:]}")
    return data


@contextmanager
def session(who: str, alias: str):
    """Log in with JWT and keep the key file until the block ends.

    The CLI records the key file's path and reads it again later: to log in to a scratch org it has just created
    through this Dev Hub, and to renew an expired session. So every use of the login goes inside the block. The file
    lives in the step's own container and is deleted when the block ends.
    """
    if who not in IDENTITIES:
        raise FactoryError(f"Unknown identity {who!r}")
    user_var, client_var, url_var, default_url, key_var = IDENTITIES[who]
    key = env(key_var, required=True)
    fd, key_file = tempfile.mkstemp(prefix="sfjwt-")
    try:
        with os.fdopen(fd, "w") as fh:
            fh.write(key if key.endswith("\n") else key + "\n")
        os.chmod(key_file, 0o600)
        args = ["org", "login", "jwt", "--username", env(user_var, required=True),
                "--client-id", env(client_var, required=True), "--jwt-key-file", key_file,
                "--instance-url", env(url_var) or default_url, "--alias", alias]
        _sf(*args, timeout=300)
        yield alias
    finally:
        os.remove(key_file)


def login(who: str, alias: str) -> None:
    """Log in for a step that only uses this org directly (no scratch org creation through it)."""
    with session(who, alias):
        pass


def logout(alias: str) -> None:
    _sf("org", "logout", "--target-org", alias, "--no-prompt", check=False, timeout=120)


def create_scratch(alias: str, cwd: str | Path, policy: Policy, devhub: str = "devhub") -> None:
    definition = Path(cwd) / policy.get("scratch_org.definition")
    if not definition.exists():
        raise FactoryError(f"Scratch org definition not found: {definition}")
    _sf("org", "create", "scratch", "--definition-file", str(definition), "--alias", alias,
        "--duration-days", str(policy.get("scratch_org.duration_days", 1)),
        "--wait", str(policy.get("scratch_org.wait_minutes", 30)), "--target-dev-hub", devhub,
        cwd=cwd, timeout=int(policy.get("scratch_org.wait_minutes", 30)) * 60 + 300)


def deploy(alias: str, cwd: str | Path, wait: int = 60) -> tuple[bool, str]:
    data = _sf("project", "deploy", "start", "--target-org", alias, "--wait", str(wait), cwd=cwd,
               timeout=wait * 60 + 300, check=False)
    if data.get("status") == 0:
        files = (data.get("result") or {}).get("files") or []
        return True, f"Deployed {len(files)} component file(s) to {alias}."
    result = data.get("result") or {}
    failures = [f for f in (result.get("files") or []) if f.get("state") == "Failed"]
    lines = [f"- {f.get('type')} {f.get('fullName')}: {f.get('error')}" for f in failures[:30]]
    return False, "Deploy failed: " + (data.get("message") or "") + ("\n" + "\n".join(lines) if lines else "")


def delete_scratch(alias: str) -> None:
    _sf("org", "delete", "scratch", "--target-org", alias, "--no-prompt", check=False, timeout=600)


def set_default(alias: str, cwd: str | Path) -> None:
    _sf("config", "set", f"target-org={alias}", cwd=cwd, check=False, timeout=60)
