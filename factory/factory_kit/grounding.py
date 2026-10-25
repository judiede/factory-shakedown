"""Grounding check: every metadata name a spec marks as existing must really exist.

Custom components are looked up in the base branch source, so the human solution in today's org
can't make a replay spec pass. Standard and managed-package components aren't in source; they are
checked against the org when one is available (the spec job) and reported as unverified otherwise (CI).
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .spec import MetadataRef, Spec
from .util import norm_path, run

# Where each metadata type lives in SFDX source format. {name} is the full API name,
# {obj} and {child} are its two halves for child components such as fields.
SOURCE_PATTERNS: dict[str, list[str]] = {
    "CustomObject": ["objects/{name}/{name}.object-meta.xml"],
    "CustomField": ["objects/{obj}/fields/{child}.field-meta.xml"],
    "ValidationRule": ["objects/{obj}/validationRules/{child}.validationRule-meta.xml"],
    "RecordType": ["objects/{obj}/recordTypes/{child}.recordType-meta.xml"],
    "ListView": ["objects/{obj}/listViews/{child}.listView-meta.xml"],
    "FieldSet": ["objects/{obj}/fieldSets/{child}.fieldSet-meta.xml"],
    "CompactLayout": ["objects/{obj}/compactLayouts/{child}.compactLayout-meta.xml"],
    "WebLink": ["objects/{obj}/webLinks/{child}.webLink-meta.xml"],
    "BusinessProcess": ["objects/{obj}/businessProcesses/{child}.businessProcess-meta.xml"],
    "ApexClass": ["classes/{name}.cls"],
    "ApexTrigger": ["triggers/{name}.trigger"],
    "ApexPage": ["pages/{name}.page"],
    "ApexComponent": ["components/{name}.component"],
    "LightningComponentBundle": ["lwc/{name}/{name}.js-meta.xml"],
    "AuraDefinitionBundle": ["aura/{name}/{name}.cmp", "aura/{name}/{name}.app", "aura/{name}/{name}.evt"],
    "Flow": ["flows/{name}.flow-meta.xml"],
    "PermissionSet": ["permissionsets/{name}.permissionset-meta.xml"],
    "PermissionSetGroup": ["permissionsetgroups/{name}.permissionsetgroup-meta.xml"],
    "Profile": ["profiles/{name}.profile-meta.xml"],
    "CustomPermission": ["customPermissions/{name}.customPermission-meta.xml"],
    "FlexiPage": ["flexipages/{name}.flexipage-meta.xml"],
    "Layout": ["layouts/{name}.layout-meta.xml"],
    "CustomMetadata": ["customMetadata/{name}.md-meta.xml"],
    "CustomTab": ["tabs/{name}.tab-meta.xml"],
    "StaticResource": ["staticresources/{name}.resource-meta.xml"],
    "SharingRules": ["sharingRules/{name}.sharingRules-meta.xml"],
    "NamedCredential": ["namedCredentials/{name}.namedCredential-meta.xml"],
    "ExternalCredential": ["externalCredentials/{name}.externalCredential-meta.xml"],
    "QuickAction": ["quickActions/{name}.quickAction-meta.xml"],
    "GlobalValueSet": ["globalValueSets/{name}.globalValueSet-meta.xml"],
    "Queue": ["queues/{name}.queue-meta.xml"],
    "Group": ["groups/{name}.group-meta.xml"],
    "EmailTemplate": ["email/{name}.email-meta.xml"],
    "PlatformEventChannel": ["platformEventChannels/{name}.platformEventChannel-meta.xml"],
}
CHILD_TYPES = {"CustomField", "ValidationRule", "RecordType", "ListView", "FieldSet", "CompactLayout",
               "WebLink", "BusinessProcess"}


def _custom(name: str) -> bool:
    return "__" in name


def _namespaced(name: str) -> bool:
    # ns__Object__c has two double underscores; Object__c has one.
    return name.count("__") >= 2


@dataclass
class Result:
    ref: MetadataRef
    verdict: str  # ok | missing | exists | unverified
    detail: str

    @property
    def is_error(self) -> bool:
        return self.verdict in {"missing", "exists"}


class SourceIndex:
    def __init__(self, root: str | Path, package_dirs: list[str]):
        self.root = Path(root)
        self.files: set[str] = set()
        for pkg in package_dirs:
            base = self.root / pkg
            if base.is_dir():
                for p in base.rglob("*"):
                    if p.is_file():
                        self.files.add(norm_path(str(p.relative_to(self.root))))

    def find(self, suffix: str) -> list[str]:
        return sorted(f for f in self.files if f == suffix or f.endswith("/" + suffix))

    def find_label(self, name: str) -> bool:
        needle = f"<fullName>{name}</fullName>"
        for f in self.files:
            if f.endswith(".labels-meta.xml") and needle in (self.root / f).read_text(encoding="utf-8", errors="replace"):
                return True
        return False


class OrgLookup:
    """Read-only lookups against an authorized org through the sf CLI."""

    def __init__(self, alias: str):
        self.alias = alias
        self._fields: dict[str, set[str] | None] = {}
        self._members: dict[str, set[str]] = {}

    def _sf(self, *args: str) -> dict | None:
        proc = run(["sf", *args, "--target-org", self.alias, "--json"], check=False, timeout=300)
        try:
            data = json.loads(proc.stdout or "{}")
        except json.JSONDecodeError:
            return None
        return data if data.get("status") == 0 else None

    def fields(self, obj: str) -> set[str] | None:
        if obj not in self._fields:
            data = self._sf("sobject", "describe", "--sobject", obj)
            self._fields[obj] = None if data is None else {f["name"] for f in data["result"].get("fields", [])}
        return self._fields[obj]

    def has(self, mtype: str, name: str) -> bool:
        if mtype == "CustomObject":
            return self.fields(name) is not None
        if mtype == "CustomField" and "." in name:
            obj, child = name.split(".", 1)
            fields = self.fields(obj)
            return fields is not None and child in fields
        if mtype not in self._members:
            data = self._sf("org", "list", "metadata", "--metadata-type", mtype)
            result = (data or {}).get("result") or []
            self._members[mtype] = {m.get("fullName") for m in result if isinstance(m, dict)}
        return name in self._members[mtype]


def _source_lookup(index: SourceIndex, ref: MetadataRef) -> bool | None:
    """True or False when source can answer, None when only an org can."""
    name, mtype = ref.name, ref.type
    if mtype == "CustomLabel":
        return index.find_label(name)
    obj, child = (name.split(".", 1) + [""])[:2] if "." in name else (name, "")
    if mtype in CHILD_TYPES and not child:
        return False
    if mtype == "CustomObject" and (not _custom(name) or _namespaced(name)):
        return None
    if mtype == "CustomField" and (not _custom(child) or _namespaced(child)):
        return None
    if mtype not in CHILD_TYPES and mtype != "CustomObject" and _namespaced(name):
        return None
    patterns = SOURCE_PATTERNS.get(mtype)
    if patterns is None:
        found = index.find(f"{name}.") or [f for f in index.files if f.rsplit("/", 1)[-1].startswith(name + ".")]
        return True if found else None
    return any(index.find(p.format(name=name, obj=obj, child=child)) for p in patterns)


def check(spec: Spec, root: str | Path, package_dirs: list[str], org: OrgLookup | None = None) -> list[Result]:
    index = SourceIndex(root, package_dirs)
    results = []
    for ref in spec.metadata:
        in_source = _source_lookup(index, ref)
        if ref.status == "new":
            if in_source:
                results.append(Result(ref, "exists", "marked new, but it already exists on the base branch"))
            else:
                results.append(Result(ref, "ok", "new"))
            continue
        if in_source:
            results.append(Result(ref, "ok", "found in source"))
        elif in_source is False:
            results.append(Result(ref, "missing", "not on the base branch; mark it new or fix the name"))
        elif org is None:
            results.append(Result(ref, "unverified", "standard or managed component; no org to check against"))
        elif org.has(ref.type, ref.name):
            results.append(Result(ref, "ok", f"found in org {org.alias}"))
        else:
            results.append(Result(ref, "missing", f"not found in org {org.alias}"))
    return results


def report(results: list[Result]) -> str:
    errors = [r for r in results if r.is_error]
    head = ("Grounding check passed." if not errors
            else f"Grounding check failed: {len(errors)} reference(s) don't match reality.")
    rows = "\n".join(f"| {r.ref.type} | `{r.ref.name}` | {r.ref.status} | {r.verdict} | {r.detail} |" for r in results)
    return f"{head}\n\n| Type | API name | Status | Result | Detail |\n| --- | --- | --- | --- | --- |\n{rows}"


def org_from_env() -> OrgLookup | None:
    alias = os.environ.get("FACTORY_GROUNDING_ORG")
    return OrgLookup(alias) if alias else None
