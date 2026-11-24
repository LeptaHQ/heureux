"""Citable excerpts from a learner's original words, numbered in reading order."""

import re

_EXCERPT_LIMIT = 160


def _passages(text):
    start = end = 0
    for word in re.finditer(r"\S+", text):
        if end > start and word.end() - start > _EXCERPT_LIMIT:
            yield text[start:end]
            start = end
        if start == end:
            start = word.start()
        end = word.end()
        if end - start >= 32 and text[end - 1] in ".!?…;":
            yield text[start:end]
            start = end
    if end > start:
        yield text[start:end]


def number_passages(text, evidence, *, turn_index=None):
    passages = []
    for excerpt in _passages(text):
        key = None
        if len(excerpt) <= _EXCERPT_LIMIT and any(char.isalnum() for char in excerpt):
            key = f"E{len(evidence) + 1}"
            evidence[key] = {"quote": excerpt}
            if turn_index is not None:
                evidence[key]["turnIndex"] = turn_index
        passages.append({"id": key, "text": excerpt})
    return passages
