"""Deterministic local keyword ranking. No embeddings, network access or model calls."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping

_STOPWORDS = frozenset(
    {"a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "for", "from", "how", "i", "in", "is", "it"}
    | {"its", "me", "my", "of", "on", "or", "our", "so", "that", "the", "this", "to", "want", "we", "with"}
)
# Verbs that appear everywhere. They break ties but cannot make a document match on their own.
_GENERIC = frozenset({"add", "apply", "create", "get", "make", "new", "run", "set", "use"})


def words(text: str) -> set[str]:
    """Lowercase words with a simple plural ending removed."""
    found = set()
    for word in re.findall(r"[a-z0-9]+", text.lower()):
        if len(word) > 3 and word.endswith("s") and not word.endswith("ss"):
            word = word[:-1]
        if word not in _STOPWORDS:
            found.add(word)
    return found


def matching_words(query: str, text: str) -> set[str]:
    """The query's distinctive words that appear in the text."""
    return (words(query) - _GENERIC) & words(text)


def rank(query: str, documents: Mapping[str, Iterable[tuple[int, str]]]) -> list[tuple[str, int]]:
    """Score documents of (weight, text) fields. Each query word counts once, at its best weight."""
    terms = words(query)
    distinctive = terms - _GENERIC
    scored = []
    for key, fields in documents.items():
        best: dict[str, int] = {}
        for weight, text in fields:
            for term in terms & words(text):
                best[term] = max(best.get(term, 0), 1 if term in _GENERIC else weight)
        if best and (not distinctive or distinctive & best.keys()):
            scored.append((key, sum(best.values())))
    return sorted(scored, key=lambda item: (-item[1], item[0]))
