"""Find and redact personal data in ticket text before it reaches the model.

This is a safety net, not a guarantee: tickets are screened by a person before selection (poc-plan.md).
"""

from __future__ import annotations

import re

EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b")
PHONE = re.compile(
    r"(?<![\w+])(?:"
    r"\+\d{1,3}[\s.-]?\(?\d{1,5}\)?(?:[\s.-]?\d{2,}){2,}"   # +49 30 1234567, +1 (555) 123-4567
    r"|\b0\d{2,5}[\s/-]?\d{3,}(?:[\s-]?\d{2,})*\b"           # 030 1234567, 0171/1234567
    r"|\(?\b\d{3}\)?[\s.-]\d{3}[\s.-]\d{4}\b"                # 555-123-4567
    r")"
)
# Salesforce record IDs: 15 or 18 characters, with digits in them (unlike ordinary words).
RECORD_ID = re.compile(r"\b(?=[A-Za-z0-9]*\d[A-Za-z0-9]*\b)[A-Za-z0-9]{3}[0-9][A-Za-z0-9]{11}(?:[A-Za-z0-9]{3})?\b")
IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?:\s?[A-Z0-9]{4}){3,7}(?:\s?[A-Z0-9]{1,3})?\b")
CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")

KINDS = [("email", EMAIL), ("iban", IBAN), ("card", CARD), ("phone", PHONE), ("record-id", RECORD_ID)]


def _luhn(number: str) -> bool:
    digits = [int(c) for c in number if c.isdigit()]
    if not 13 <= len(digits) <= 19:
        return False
    total = 0
    for i, d in enumerate(reversed(digits)):
        if i % 2:
            d = d * 2 - 9 if d > 4 else d * 2
        total += d
    return total % 10 == 0


def scan(text: str) -> dict[str, int]:
    return redact(text)[1]


def redact(text: str) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}

    for kind, pattern in KINDS:
        def replace(m: re.Match, kind=kind) -> str:
            if kind == "card" and not _luhn(m[0]):
                return m[0]
            counts[kind] = counts.get(kind, 0) + 1
            return f"[{kind} removed]"
        text = pattern.sub(replace, text)
    return text, counts
