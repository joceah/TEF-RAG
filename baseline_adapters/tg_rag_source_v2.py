"""Recover original record identifiers from TG-RAG context-only results."""

from __future__ import annotations

import re
from typing import Any


_RECORD_ID = re.compile(r"^record_id:\s*(\S+)\s*$", re.MULTILINE)


def context_text(result: Any) -> str:
    """Return the textual context from TG-RAG's string or ``(text, stats)`` API."""

    if isinstance(result, tuple):
        if not result:
            return ""
        return context_text(result[0])
    if isinstance(result, str):
        return result
    raise TypeError(f"unsupported TG-RAG context result: {type(result).__name__}")


def source_ids(result: Any) -> list[str]:
    """Recover unique record IDs in the order returned by TG-RAG."""

    return list(dict.fromkeys(_RECORD_ID.findall(context_text(result))))
