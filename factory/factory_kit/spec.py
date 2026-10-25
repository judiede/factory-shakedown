"""Spec documents (docs/specs/<KEY>.md): parsing and the lint that CI and the spec job run."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import markdown
from .globs import is_safe_pattern, matches
from .policy import WORK_TYPES, Policy
from .util import KEY_PATTERN, TASK_RE, FactoryError

REQUIRED_SECTIONS = [
    "problem", "options compared", "chosen approach", "impacted metadata", "task breakdown",
    "acceptance criteria", "test plan", "security", "open questions",
]
METADATA_COLUMNS = ("type", "api name", "status")
TASK_COLUMNS = ("id", "task", "depends on", "allowed paths", "work type")
NO_QUESTIONS = {"", "none", "none.", "n/a", "-", "–", "—", "no open questions.", "no open questions"}


@dataclass
class MetadataRef:
    type: str
    name: str
    status: str
    change: str = ""


@dataclass
class Task:
    id: str
    title: str
    depends: list[str]
    allowed: list[str]
    work_type: str


@dataclass
class Spec:
    key: str | None
    title: str | None
    sections: dict[str, str]
    metadata: list[MetadataRef] = field(default_factory=list)
    tasks: list[Task] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)

    @property
    def open_questions(self) -> str | None:
        body = self.sections.get("open questions", "").strip()
        return None if body.lower() in NO_QUESTIONS else body

    def task(self, task_id: str) -> Task:
        for t in self.tasks:
            if t.id == task_id:
                return t
        raise FactoryError(f"Task {task_id!r} isn't in the spec's task breakdown")


def parse(text: str) -> Spec:
    title = markdown.title(text)
    m = re.match(rf"^({KEY_PATTERN})\s*[:\-–]\s*(.+)$", title or "")
    spec = Spec(key=m[1] if m else None, title=(m[2] if m else title), sections=markdown.sections(text))

    rows = markdown.parse_table(spec.sections.get("impacted metadata", ""))
    if rows and not all(c in rows[0] for c in METADATA_COLUMNS):
        spec.problems.append(f"Impacted metadata table needs the columns {', '.join(METADATA_COLUMNS)}")
    else:
        for row in rows:
            spec.metadata.append(MetadataRef(
                type=markdown.clean_cell(row.get("type", "")),
                name=markdown.clean_cell(row.get("api name", "")),
                status=markdown.clean_cell(row.get("status", "")).lower(),
                change=row.get("change", "").strip(),
            ))

    rows = markdown.parse_table(spec.sections.get("task breakdown", ""))
    if rows and not all(c in rows[0] for c in TASK_COLUMNS):
        spec.problems.append(f"Task breakdown table needs the columns {', '.join(TASK_COLUMNS)}")
    else:
        for row in rows:
            spec.tasks.append(Task(
                id=markdown.clean_cell(row.get("id", "")).lower(),
                title=markdown.clean_cell(row.get("task", "")),
                depends=[d.lower() for d in markdown.split_list(row.get("depends on", ""))],
                allowed=markdown.split_list(row.get("allowed paths", "")),
                work_type=markdown.clean_cell(row.get("work type", "")).lower(),
            ))
    return spec


def load(path: str | Path) -> Spec:
    path = Path(path)
    if not path.exists():
        raise FactoryError(f"Spec not found: {path}")
    return parse(path.read_text(encoding="utf-8"))


def _cycle(tasks: list[Task]) -> list[str] | None:
    graph = {t.id: t.depends for t in tasks}
    state: dict[str, int] = {}

    def visit(node, trail):
        if state.get(node) == 1:
            return trail[trail.index(node):] + [node]
        if state.get(node) == 2 or node not in graph:
            return None
        state[node] = 1
        for dep in graph[node]:
            if found := visit(dep, trail + [node]):
                return found
        state[node] = 2
        return None

    for t in tasks:
        if found := visit(t.id, []):
            return found
    return None


def lint(spec: Spec, policy: Policy, key: str | None = None) -> list[str]:
    errors = list(spec.problems)
    if key and spec.key != key:
        errors.append(f"Title must start with the ticket key: '# {key}: <title>'")
    for name in REQUIRED_SECTIONS:
        if name not in spec.sections:
            errors.append(f"Missing section: ## {name.capitalize()}")

    if not spec.metadata:
        errors.append("Impacted metadata table is empty")
    for ref in spec.metadata:
        if not ref.type or not ref.name:
            errors.append(f"Impacted metadata row needs a type and an API name: {ref}")
        if ref.status not in {"existing", "new"}:
            errors.append(f"{ref.type} {ref.name}: status must be 'existing' or 'new', not {ref.status!r}")

    if not spec.tasks:
        errors.append("Task breakdown table is empty")
    ids = [t.id for t in spec.tasks]
    if len(ids) != len(set(ids)):
        errors.append("Task IDs must be unique")
    forbidden = policy.get("scope.forbidden", [])
    for t in spec.tasks:
        if not TASK_RE.match(t.id):
            errors.append(f"Task ID {t.id!r} must be one lowercase letter")
        if not t.title:
            errors.append(f"Task {t.id}: needs a description")
        for dep in t.depends:
            if dep not in ids:
                errors.append(f"Task {t.id}: depends on unknown task {dep!r}")
        if t.work_type not in WORK_TYPES:
            errors.append(f"Task {t.id}: work type must be one of {', '.join(WORK_TYPES)}")
        if not t.allowed:
            errors.append(f"Task {t.id}: needs at least one allowed path")
        for pattern in t.allowed:
            if not is_safe_pattern(pattern):
                errors.append(f"Task {t.id}: allowed path {pattern!r} must be a repo-relative glob")
            elif pattern.strip() in {"**", "*", "**/*"}:
                errors.append(f"Task {t.id}: allowed path {pattern!r} is too broad")
            elif matches(pattern.replace("*", "x"), forbidden):
                errors.append(f"Task {t.id}: allowed path {pattern!r} falls inside a forbidden path")
    if cycle := _cycle(spec.tasks):
        errors.append(f"Task dependencies form a cycle: {' -> '.join(cycle)}")
    return errors
