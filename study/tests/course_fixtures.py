"""Small synthetic banks for platform behavior, not published teaching content."""

from copy import deepcopy

from study.course_content import build_course_catalog, parse_course_lesson


def inline_teaching_fields(payload):
    """Yield containers and keys for English teaching that can embed French."""
    yield payload, "summary"
    for index in range(len(payload["objectives"])):
        yield payload["objectives"], index
    for section in payload["sections"]:
        yield section, "title"
        for field in ("paragraphs", "points"):
            for index in range(len(section[field])):
                yield section[field], index
        for example in section["examples"]:
            for field in ("english", "note"):
                if field in example:
                    yield example, field
        for mistake in section["mistakes"]:
            yield mistake, "why"
    production = payload["production_task"]
    for field in ("prompt", "translation"):
        yield production, field
    for index in range(len(production["rubric"])):
        yield production["rubric"], index


def course_payload(level="A1", order=1, *, suffix="foundations", topic="grammar-foundations"):
    prefix = level[:2].lower()
    return {
        "version": 1, "id": f"{prefix}-{suffix}", "slug": f"{prefix}-{suffix}",
        "cefr_level": level, "topic": topic, "title": f"{level} · Une école",
        "summary": "Choose a noun's article and preserve its accents.", "order": order,
        "duration_minutes": 10, "prerequisites": [],
        "objectives": ["Choose an article that agrees with the noun."],
        "keywords": ["article", "école", "school"],
        "sources": [{"label": "Topic index", "url": "https://french.kwiziq.com/revision/grammar/by-cefr-level/cefr-a1"}],
        "related_legacy_ids": ["grammar-articles-gender"],
        "sections": [{
            "id": "rule", "title": "Article agreement",
            "paragraphs": ["A **noun** names a person, place or thing. <script>unsafe()</script>"],
            "points": ["Keep grammatical accents."],
            "examples": [
                {"french": french, "english": english, "note": ""}
                for french, english in (
                    ("**Une** école.\n**Une** maison.", "A school.\nA house."),
                    ("Un chat.", "A cat."), ("Un livre.", "A book."),
                    ("Une porte.", "A door."), ("La porte.", "The door."),
                    ("Le chat.", "The cat."), ("Les livres.", "The books."),
                    ("Des maisons.", "Some houses."),
                )
            ],
            "mistakes": [
                {"avoid": "un maison", "prefer": "une maison", "why": "Maison is feminine."},
                {"avoid": "une livre", "prefer": "un livre", "why": "A book is masculine."},
            ],
        }],
        "practice": [
            {
                "id": f"{pool}-{index + 1:02}", "kind": "text" if index % 2 == 0 else "choice",
                "pool": pool, "section_id": "rule",
                "prompt": f"{level} {pool} fixture {index + 1}: supply the French word for school.",
                "choices": [] if index % 2 == 0 else ["école", "maison"],
                "answers": ["école", "l'école"] if index % 2 == 0 else ["école"],
                "explanation": f"Private {pool} feedback {index + 1}: keep the accent in école.",
            }
            for pool, count in (("practice", 4), ("check", 8), ("review", 4))
            for index in range(count)
        ],
        "production_task": {
            "prompt": "Describe a place in your town using two noun phrases.",
            "model_answer": "Il y a une école et une bibliothèque.",
            "translation": "There is a school and a library.",
            "rubric": ["Did you choose an article agreeing with each noun?"],
        },
    }


def course_lesson(level="A1", order=1, **kwargs):
    payload = course_payload(level, order, **kwargs)
    directory = "c1-preparation" if level == "C1-preparation" else level.lower()
    return parse_course_lesson(payload, directory=directory)


def course_catalog():
    return build_course_catalog((
        course_lesson(), course_lesson("A2"), course_lesson("C1-preparation"),
    ))


def sectioned_course_lesson(section_count=3):
    payload = course_payload()
    sections, items = [], []
    for index in range(section_count):
        section = deepcopy(payload["sections"][0])
        section.update(id=f"section-{index}", title=f"Teaching section {index + 1}")
        sections.append(section)
        for original in payload["practice"]:
            item = deepcopy(original)
            item.update(
                id=f"s{index}-{original['id']}", section_id=section["id"],
                prompt=f"Section {index + 1}: {original['prompt']}",
            )
            items.append(item)
    return parse_course_lesson({**payload, "sections": sections, "practice": items}, directory="a1")
