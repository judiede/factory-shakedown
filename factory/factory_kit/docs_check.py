"""Docs check: a change to a feature's source must update its feature doc, and new custom fields need a description.

Each feature doc (docs/features/<name>.md) lists the source paths it covers in its front matter:

    ---
    feature: Forecast grid
    paths:
      - force-app/main/default/lwc/forecastGrid/**
    ---
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from . import markdown
from .globs import matches
from .policy import Policy
from .util import norm_path

MD_NS = "{http://soap.sforce.com/2006/04/metadata}"


@dataclass
class Feature:
    doc: str
    paths: list[str]


def load_features(root: str | Path, features_dir: str) -> tuple[list[Feature], list[str]]:
    features, errors = [], []
    base = Path(root) / features_dir
    for path in sorted(base.glob("*.md")) if base.is_dir() else []:
        if path.name.startswith("_"):
            continue
        rel = norm_path(str(path.relative_to(root)))
        try:
            meta, _ = markdown.front_matter(path.read_text(encoding="utf-8"))
        except Exception as exc:  # malformed YAML
            errors.append(f"{rel}: front matter isn't valid YAML ({exc})")
            continue
        paths = (meta or {}).get("paths")
        if not isinstance(paths, list) or not all(isinstance(p, str) for p in paths) or not paths:
            errors.append(f"{rel}: front matter needs a 'paths' list of source globs")
            continue
        features.append(Feature(rel, paths))
    return features, errors


def field_has_description(path: Path) -> bool:
    try:
        tree = ET.parse(path)
    except (ET.ParseError, OSError):
        return False
    node = tree.getroot().find(f"{MD_NS}description")
    if node is None:
        node = tree.getroot().find("description")
    return node is not None and bool((node.text or "").strip())


def check(changes: list[tuple[str, str]], root: str | Path, package_dirs: list[str], policy: Policy) -> tuple[list[str], list[str]]:
    errors, warnings = [], []
    root = Path(root)
    features, problems = load_features(root, policy.get("docs.features_dir", "docs/features"))
    errors += problems

    changed = {p for s, p in changes if s != "D"}
    touched = {p for _, p in changes}
    source = sorted(p for p in touched if any(p == d or p.startswith(d + "/") for d in package_dirs))

    unmapped = []
    for path in source:
        owners = [f for f in features if matches(path, f.paths)]
        if not owners:
            unmapped.append(path)
        for f in owners:
            if f.doc not in changed:
                errors.append(f"`{path}` belongs to {f.doc}, which this change doesn't update")
    if unmapped:
        msg = f"{len(unmapped)} source change(s) belong to no feature doc: " + ", ".join(f"`{p}`" for p in unmapped[:10])
        (errors if policy.get("docs.unmapped_source_changes") == "fail" else warnings).append(msg)

    if policy.get("docs.require_field_descriptions", True):
        for status, path in changes:
            if status in {"A", "M"} and path.endswith("__c.field-meta.xml") and (root / path).exists():
                if not field_has_description(root / path):
                    errors.append(f"`{path}`: custom field needs a description")
    return sorted(set(errors)), warnings


def report(errors: list[str], warnings: list[str]) -> str:
    lines = ["Docs check passed." if not errors else f"Docs check failed: {len(errors)} problem(s)."]
    lines += [f"- {e}" for e in errors]
    lines += [f"- Warning: {w}" for w in warnings]
    return "\n".join(lines)
