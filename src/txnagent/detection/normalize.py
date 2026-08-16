"""Merchant name normalization.

Raw counterparty strings from a core banking feed are messy: trailing POS
terminal codes, city names, reference numbers, inconsistent casing. Grouping
transactions into a recurring series first requires collapsing these
variants onto a stable key — this is the same normalization problem the
Verification-of-Payee name matching in `instant-payments-core` solves for
beneficiary names, applied here to merchants instead.
"""

from __future__ import annotations

import re

_NOISE_TOKENS = re.compile(
    r"\b(SPA|S\.P\.A\.?|SRL|S\.R\.L\.?|LTD|INC|GMBH|AB|ITALIA|ITALY|MILANO|"
    r"ROMA|POS|CARTA|RIF\.?|N\.?|\d{4,})\b",
    re.IGNORECASE,
)
_PUNCT = re.compile(r"[^\w\s]")
_MULTI_SPACE = re.compile(r"\s+")


def normalize_merchant(raw: str) -> str:
    """Return a stable, comparable key for a raw counterparty string.

    Not meant to be human-facing — `display_name` in RecurringSeries keeps
    the original casing for that.
    """
    s = raw.upper()
    s = _PUNCT.sub(" ", s)
    s = _NOISE_TOKENS.sub(" ", s)
    s = _MULTI_SPACE.sub(" ", s).strip()
    return s or raw.upper().strip()
