"""Minimal Jira Cloud REST client for the factory's service account (read tickets, comment, set labels)."""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.parse
import urllib.request

from .util import FactoryError, env, require_key


class Jira:
    def __init__(self, base_url: str, user: str, token: str):
        self.base = base_url.rstrip("/")
        auth = base64.b64encode(f"{user}:{token}".encode()).decode()
        self.headers = {"Authorization": f"Basic {auth}", "Accept": "application/json",
                        "Content-Type": "application/json"}

    @classmethod
    def from_env(cls) -> "Jira":
        return cls(env("JIRA_BASE_URL", required=True), env("JIRA_USER", required=True),
                   env("JIRA_API_TOKEN", required=True))

    def _call(self, method: str, path: str, body: dict | None = None, query: dict | None = None) -> dict:
        url = f"{self.base}{path}"
        if query:
            url += "?" + urllib.parse.urlencode(query)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method, headers=self.headers)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")[:500]
            raise FactoryError(f"Jira {method} {path} failed with {exc.code}: {detail}") from None

    def myself(self) -> dict:
        return self._call("GET", "/rest/api/3/myself")

    def search(self, jql: str, fields: list[str], limit: int = 50) -> list[dict]:
        issues, token = [], None
        while len(issues) < limit:
            query = {"jql": jql, "fields": ",".join(fields), "maxResults": min(50, limit - len(issues))}
            if token:
                query["nextPageToken"] = token
            page = self._call("GET", "/rest/api/3/search/jql", query=query)
            issues += page.get("issues", [])
            token = page.get("nextPageToken")
            if not token or page.get("isLast", True):
                break
        return issues

    def issue(self, key: str) -> dict:
        # API v2 returns description and comments as plain wiki text, which suits a prompt.
        fields = "summary,description,comment,issuetype,priority,labels,components,status,attachment"
        return self._call("GET", f"/rest/api/2/issue/{require_key(key)}", query={"fields": fields})

    def comment(self, key: str, text: str) -> None:
        self._call("POST", f"/rest/api/2/issue/{require_key(key)}/comment", body={"body": text})

    def labels(self, key: str, add: list[str] = (), remove: list[str] = ()) -> None:
        ops = [{"add": a} for a in add] + [{"remove": r} for r in remove]
        if ops:
            self._call("PUT", f"/rest/api/2/issue/{require_key(key)}", body={"update": {"labels": ops}})
