"""Shared removal of knowledge-cutoff metadata from semantic query text."""

import re


LEADING_KNOWLEDGE_CUTOFF = re.compile(
    r"^\s*截至(?:当前|\d{4}年\d{1,2}月\d{1,2}日)\s*[，,；;：:]?\s*"
)


def semantic_question(text):
    core = str(text).split("；", 1)[-1]
    return LEADING_KNOWLEDGE_CUTOFF.sub("", core).strip()
