# -*- coding: utf-8 -*-
import re

_WORD_OVERRIDES = {
    "REQUEST": "Q",
    "CLEARANCE": "CL",
    "CLEARANT": "CL",
    "CLEARENT": "CL",
    "PASS": "PA",
    "GATE": "GA",
    "EXIT": "EX",
}

_STOPWORDS = {"AND", "OR", "THE", "A", "AN", "OF", "FOR", "TO", "IN", "ON", "&"}


def make_sequence_code(name: str, max_len: int = 4) -> str:
    """Build a short code from a display name.
    Examples:
      Gate Pass -> GAPA
      IT Request -> ITQ
      Exit Clearent -> EXCL
    """
    name = (name or "").strip()
    if not name:
        return "WS01"

    tokens = re.findall(r"[A-Za-z0-9]+", name.upper())
    tokens = [t for t in tokens if t and t not in _STOPWORDS]
    if not tokens:
        return "WS01"

    # Single word -> first N letters
    if len(tokens) == 1:
        t = tokens[0]
        return (t[:max_len] if len(t) >= max_len else (t + "X" * max_len)[:max_len])

    parts = []
    for t in tokens:
        parts.append(_WORD_OVERRIDES.get(t, t[:2]))
        if len("".join(parts)) >= max_len:
            break

    return ("".join(parts)[:max_len]) or "WS01"


def unique_sequence_code(env, code: str, *, model_name="workflow.approval.category", field_name="sequence_code") -> str:
    """Ensure code is unique on a model/field (default: workflow.approval.category.sequence_code)."""
    Model = env[model_name].sudo()
    code = (code or "").upper()[:4] or "WS01"

    if not Model.search_count([(field_name, "=", code)]):
        return code

    # Try ABC1..ABC9
    prefix3 = code[:3]
    for i in range(1, 10):
        alt = f"{prefix3}{i}"
        if not Model.search_count([(field_name, "=", alt)]):
            return alt

    # Try AB01..AB99
    prefix2 = code[:2]
    for i in range(1, 100):
        alt = f"{prefix2}{i:02d}"
        if not Model.search_count([(field_name, "=", alt)]):
            return alt

    return "WS99"