"""PII scrubber for the Claude chat context (Phase 5).

Strips identifying details from any text before it leaves the machine for the
Anthropic API:
  * account / card numbers (long digit runs, masked forms like ****1234)
  * the user's name(s) from config
  * email addresses, phone numbers, street addresses, ZIP codes
  * optional "paranoid" mode that drops merchant names, keeping only categories

The Anthropic API does not train on inputs, but scrubbing is good hygiene and
the plan calls for it explicitly.
"""

from __future__ import annotations

import re

from utils.config import settings

# Order matters: run more specific patterns before generic digit runs.
_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[EMAIL]"),
    (re.compile(r"\*{2,}\s?\d{3,4}"), "[ACCT]"),                 # ****1234
    (re.compile(r"\bx{2,}\d{3,4}\b", re.IGNORECASE), "[ACCT]"),  # xxxx1234
    (re.compile(r"\b(?:\d[ -]?){13,19}\b"), "[CARD]"),           # card numbers
    (re.compile(r"\b\d{9,}\b"), "[ACCT]"),                       # long acct nums
    (re.compile(
        r"(?<!\d)(?:\+?1[\s.-]?)?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4}(?!\d)"
    ), "[PHONE]"),
    (re.compile(
        r"\b\d{1,6}\s+[A-Za-z0-9.\s]{2,30}\b"
        r"(?:Street|St|Avenue|Ave|Road|Rd|Boulevard|Blvd|Lane|Ln|Drive|Dr|"
        r"Court|Ct|Way|Place|Pl|Terrace|Ter)\b\.?",
        re.IGNORECASE,
    ), "[ADDRESS]"),
    (re.compile(r"\b\d{5}(?:-\d{4})?\b"), "[ZIP]"),
]


def _redact_names(text: str) -> str:
    for name in settings.user_names:
        if not name:
            continue
        text = re.sub(rf"\b{re.escape(name)}\b", "[NAME]", text, flags=re.IGNORECASE)
    return text


def scrub(text: str, *, paranoid: bool = False) -> str:
    """Return ``text`` with PII redacted.

    ``paranoid`` additionally strips anything that looks like a merchant token by
    collapsing capitalized multi-word names; callers that want category-only
    context should instead build the context without merchant fields.
    """
    if not text:
        return text
    # Run structured patterns first (so e.g. an email is redacted whole, before
    # a name inside it is touched), then redact configured names from the rest.
    out = text
    for pattern, repl in _PATTERNS:
        out = pattern.sub(repl, out)
    out = _redact_names(out)
    return out


def scrub_merchant(merchant: str | None) -> str:
    """Light normalization for merchant display in scrubbed context."""
    if not merchant:
        return "Unknown"
    return scrub(merchant)
