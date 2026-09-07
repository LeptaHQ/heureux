"""Cross-author checks for the complete, original CEFR course release."""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[1] / "content" / "learning"
LEVELS = ("A1", "A2", "B1", "B2", "C1-preparation")
BENCHMARK_COUNTS = {"A1": 134, "A2": 165, "B1": 96, "B2": 84}


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def normalise_prompt(text):
    return " ".join(text.replace("’", "'").split()).casefold()


class CourseBundleTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.legacy = read_json(ROOT / "curriculum.json")
        cls.manifest = read_json(ROOT / "legacy_manifest.json")
        cls.documents = [
            (path, read_json(path))
            for path in sorted((ROOT / "courses").glob("*/*.json"))
        ]
        cls.lessons = {lesson["id"]: lesson for _path, lesson in cls.documents}

    def test_all_levels_have_authored_lessons_with_unique_identities(self):
        self.assertTrue(self.documents, "The course release cannot be an empty shell.")
        self.assertEqual(len(self.lessons), len(self.documents))
        self.assertEqual(
            {lesson["cefr_level"] for lesson in self.lessons.values()}, set(LEVELS)
        )
        self.assertEqual(
            len({lesson["slug"] for lesson in self.lessons.values()}),
            len(self.lessons),
        )
        orders = set()
        legacy_ids = {
            lesson["id"]
            for module in self.legacy["modules"]
            for lesson in module["lessons"]
        }
        for path, lesson in self.documents:
            with self.subTest(lesson=lesson["id"]):
                level = lesson["cefr_level"]
                prefix = "c1-" if level == "C1-preparation" else level.lower() + "-"
                self.assertTrue(lesson["id"].startswith(prefix))
                self.assertEqual(path.parent.name, level.lower())
                self.assertNotIn(lesson["id"], legacy_ids)
                key = (level, lesson["order"])
                self.assertNotIn(key, orders)
                orders.add(key)

    def test_all_benchmark_topics_resolve_to_teaching_and_exercises(self):
        source_urls = set()
        for level, expected_count in BENCHMARK_COUNTS.items():
            with self.subTest(level=level):
                benchmark = read_json(ROOT / "benchmarks" / f"{level.lower()}.json")
                coverage = read_json(ROOT / "coverage" / f"{level.lower()}.json")
                expected = {
                    row["url"]: row["title"] for row in benchmark["entries"]
                }
                entries = coverage["entries"]
                actual = {row["source_url"]: row for row in entries}
                self.assertEqual(coverage["version"], 1)
                self.assertEqual(coverage["level"], level)
                self.assertEqual(coverage["source_index_url"], benchmark["url"])
                self.assertEqual(len(expected), expected_count)
                self.assertEqual(len(actual), len(entries))
                self.assertEqual(set(actual), set(expected))
                self.assertTrue(source_urls.isdisjoint(actual))
                source_urls.update(actual)
                for url, row in actual.items():
                    with self.subTest(topic=expected[url]):
                        self.assertEqual(row["source_title"], expected[url])
                        self.assertIn(
                            row["disposition"],
                            {"original-lesson", "consolidated", "recognition-track"},
                        )
                        self.assertGreater(len(row["evidence"].strip()), 20)
                        lesson = self.lessons[row["lesson_id"]]
                        self.assertEqual(lesson["cefr_level"], level)
                        section_ids = {section["id"] for section in lesson["sections"]}
                        items = {item["id"]: item for item in lesson["practice"]}
                        self.assertTrue(row["section_ids"])
                        self.assertTrue(row["practice_ids"])
                        self.assertTrue(set(row["section_ids"]).issubset(section_ids))
                        self.assertTrue(set(row["practice_ids"]).issubset(items))
                        for item_id in row["practice_ids"]:
                            self.assertIn(items[item_id]["section_id"], section_ids)
        self.assertEqual(len(source_urls), 479)

    def test_pools_have_distinct_prompts_and_constructed_answers(self):
        for lesson in self.lessons.values():
            with self.subTest(lesson=lesson["id"]):
                items = lesson["practice"]
                self.assertEqual(len(items), len({item["id"] for item in items}))
                counts = Counter(item["pool"] for item in items)
                for pool, minimum in (("practice", 4), ("check", 8), ("review", 4)):
                    self.assertGreaterEqual(counts[pool], minimum)
                seen = set()
                sections = {section["id"] for section in lesson["sections"]}
                for item in items:
                    with self.subTest(item=item["id"]):
                        self.assertIn(item["section_id"], sections)
                        self.assertTrue(item["answers"])
                        self.assertTrue(item["explanation"].strip())
                        key = (
                            normalise_prompt(item["prompt"]),
                            tuple(sorted(normalise_prompt(a) for a in item["answers"])),
                        )
                        self.assertNotIn(
                            key, seen, "Repeating an item does not create a fresh holdout."
                        )
                        seen.add(key)
                        if item["kind"] == "choice":
                            self.assertGreaterEqual(len(set(item["choices"])), 2)
                            self.assertTrue(
                                set(item["answers"]).issubset(item["choices"])
                            )
                        else:
                            self.assertEqual(item["kind"], "text")
                            self.assertEqual(item["choices"], [])
                for pool in ("check", "review"):
                    constructed = sum(
                        item["pool"] == pool and item["kind"] == "text"
                        for item in items
                    )
                    self.assertGreaterEqual(constructed * 2, counts[pool])

    def test_global_prerequisites_are_earlier_and_acyclic(self):
        positions = {
            lesson["id"]: (LEVELS.index(lesson["cefr_level"]), lesson["order"])
            for lesson in self.lessons.values()
        }
        topic_ids = {module["id"] for module in self.legacy["modules"]}
        legacy_ids = {
            lesson["id"]
            for module in self.legacy["modules"]
            for lesson in module["lessons"]
        }
        for lesson in self.lessons.values():
            with self.subTest(lesson=lesson["id"]):
                self.assertIn(lesson["topic"], topic_ids)
                self.assertTrue(set(lesson["related_legacy_ids"]).issubset(legacy_ids))
                prerequisites = lesson["prerequisites"]
                self.assertEqual(len(prerequisites), len(set(prerequisites)))
                for prerequisite in prerequisites:
                    self.assertIn(prerequisite, positions)
                    self.assertLess(positions[prerequisite], positions[lesson["id"]])

    def test_legacy_routes_annotations_and_sources_remain_preserved(self):
        current = {
            lesson["id"]: lesson
            for module in self.legacy["modules"]
            for lesson in module["lessons"]
        }
        self.assertEqual(len(self.manifest["lessons"]), 83)
        annotation_count = 0
        for published in self.manifest["lessons"]:
            with self.subTest(lesson=published["id"]):
                lesson = current[published["id"]]
                self.assertEqual(lesson["slug"], published["slug"])
                keys = {
                    f"learn:{lesson['id']}:{section['id']}"
                    for section in lesson["sections"]
                }
                self.assertTrue(set(published["annotation_keys"]).issubset(keys))
                self.assertTrue(set(published["sources"]).issubset(lesson["sources"]))
                annotation_count += len(published["annotation_keys"])
        self.assertEqual(annotation_count, 186)

    def test_examples_corrections_and_production_are_complete(self):
        for lesson in self.lessons.values():
            with self.subTest(lesson=lesson["id"]):
                examples = [
                    example
                    for section in lesson["sections"]
                    for example in section["examples"]
                ]
                corrections = [
                    mistake
                    for section in lesson["sections"]
                    for mistake in section["mistakes"]
                ]
                self.assertGreaterEqual(len(examples), 8)
                self.assertGreaterEqual(len(corrections), 2)
                for example in examples:
                    self.assertTrue(example["french"].strip())
                    self.assertTrue(example["english"].strip())
                    self.assertNotRegex(example["french"], r"<[^>]+>")
                for mistake in corrections:
                    self.assertTrue(mistake["why"].strip())
                    for text in (mistake["avoid"], mistake["prefer"]):
                        self.assertTrue(text.strip())
                        self.assertNotRegex(
                            text,
                            r"^(?:Translating|Translate|Reading|Read|Use|Always)\b",
                        )
                        self.assertNotIn("(intended:", text)
                production = lesson["production_task"]
                for field in ("prompt", "model_answer", "translation"):
                    self.assertTrue(production[field].strip())
                self.assertTrue(production["rubric"])
                serialized = json.dumps(lesson, ensure_ascii=False)
                self.assertNotRegex(
                    serialized,
                    re.compile(r"\b(?:TODO|TBD|FIXME)\b|https?://example\.(?:com|org)"),
                )
