"""factory-policy.yml: models, budgets, path scope and CI settings, with safe defaults."""

from __future__ import annotations

import copy
import os
from pathlib import Path

import yaml

from .util import KIT_ROOT, FactoryError

DEFAULTS: dict = {
    "version": 1,
    "models": {"spec": "claude-opus-5-5", "build": "claude-sonnet-5-5", "review": "claude-sonnet-5-5"},
    "intake": {
        "ready_label": "factory-ready",
        "active_label": "factory-active",
        "clarification_label": "factory-needs-clarification",
        "merged_label": "factory-merged",
        "needs_human_label": "factory-needs-human",
        "max_dispatch_per_poll": 3,
    },
    "budgets": {
        "small": {"fix_attempts": 3, "revision_rounds": 2, "cost_usd": 5, "time_minutes": 30, "max_turns": 80},
        "medium": {"fix_attempts": 3, "revision_rounds": 2, "cost_usd": 10, "time_minutes": 45, "max_turns": 120},
        "large": {"fix_attempts": 3, "revision_rounds": 2, "cost_usd": 20, "time_minutes": 60, "max_turns": 160},
        "spec": {"revision_rounds": 3, "cost_usd": 8, "time_minutes": 30, "max_turns": 100},
        "review": {"cost_usd": 2, "time_minutes": 15, "max_turns": 40},
        "discuss": {"turns": 10, "cost_usd": 1.5, "time_minutes": 10, "max_turns": 30},
        "ticket_cost_usd": 60,
    },
    "scope": {
        "spec_allowed": ["docs/specs/{key}.md", "docs/adr/*.md"],
        "always_allowed": ["docs/features/**"],
        "forbidden": [
            ".github/**", ".claude/**", ".mcp.json", ".sf/**", ".sfdx/**", "factory/**", "factory-policy.yml",
            "AGENTS.md", "CLAUDE.md", "config/**", "sfdx-project.json", "package.json", "package-lock.json",
            ".forceignore", ".gitignore", "docs/specs/**", "docs/adr/**", "docs/architecture/**",
            "**/profiles/**",
        ],
    },
    "docs": {"features_dir": "docs/features", "unmapped_source_changes": "warn", "require_field_descriptions": True},
    "ci": {"test_level": "RunLocalTests", "code_analyzer_rule_selector": "Recommended", "code_analyzer_severity_threshold": 2},
    "redaction": {"mode": "redact"},
    "scratch_org": {"definition": "config/project-scratch-def.json", "duration_days": 1, "wait_minutes": 30},
    "web_domains": ["developer.salesforce.com", "help.salesforce.com", "architect.salesforce.com"],
    "results_branch": "factory-results",
}

WORK_TYPES = ("small", "medium", "large")


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in (override or {}).items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


class Policy:
    def __init__(self, data: dict | None = None):
        self.data = _merge(DEFAULTS, data or {})

    def get(self, dotted: str, default=None):
        node = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def model(self, role: str) -> str:
        return os.environ.get(f"FACTORY_MODEL_{role.upper()}") or self.data["models"][role]

    def budget(self, name: str) -> dict:
        budgets = self.data["budgets"]
        if name not in budgets or not isinstance(budgets[name], dict):
            raise FactoryError(f"No budget named {name!r} in factory-policy.yml (expected one of {', '.join(WORK_TYPES)})")
        return budgets[name]

    def spec_allowed(self, key: str) -> list[str]:
        return [p.replace("{key}", key) for p in self.data["scope"]["spec_allowed"]]


def load(path: str | Path | None = None) -> Policy:
    path = Path(path or os.environ.get("FACTORY_POLICY") or KIT_ROOT / "factory-policy.yml")
    if not path.exists():
        return Policy()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise FactoryError(f"{path} must contain a YAML mapping")
    return Policy(data)
