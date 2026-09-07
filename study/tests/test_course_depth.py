"""Synthetic audit validation is separate from actual public-source review."""

import hashlib
import json
from copy import deepcopy
from dataclasses import replace
from datetime import date, timedelta
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase

from study.course_content import (
    BENCHMARK_COUNTS,
    CONTENT_ROOT,
    DEPTH_BASELINE_COMMIT,
    DepthEntry,
    TeachingEvidence,
    build_course_catalog,
    load_course_catalog,
    validate_depth_report,
)

from .course_fixtures import course_lesson


def depth_fixture(benchmark):
    level = benchmark["level"]
    return {
        "version": 1,
        "level": level,
        "baseline_commit": DEPTH_BASELINE_COMMIT,
        "scope": "public-lesson-text",
        "entries": [{
            "source_url": entry["url"],
            "source_title": entry["title"],
            "checked_on": date.today().isoformat(),
            "access": "read",
            "finding": "sufficient",
            "note": "Synthetic fixture only: the rule has examples and a linked retrieval task.",
            "evidence": [{
                "lesson_id": f"{level.lower()}-foundations",
                "section_ids": ["rule"],
                "practice_ids": ["practice-01"],
            }],
            "references": [],
        } for entry in benchmark["entries"]],
    }


class CourseDepthSchemaTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.catalog = build_course_catalog(
            [course_lesson(level) for level in BENCHMARK_COUNTS]
        )
        cls.benchmark = json.loads(
            (CONTENT_ROOT / "benchmarks" / "a1.json").read_text(encoding="utf-8")
        )

    def setUp(self):
        self.report = depth_fixture(self.benchmark)

    def validate(self, report=None, **kwargs):
        return validate_depth_report(
            self.report if report is None else report, self.benchmark, self.catalog, **kwargs
        )

    def test_complete_report_returns_typed_evidence(self):
        entries = self.validate()
        self.assertEqual(len(entries), 134)
        self.assertIsInstance(entries[0], DepthEntry)
        self.assertIsInstance(entries[0].evidence[0], TeachingEvidence)
        self.assertTrue(all(entry.compared for entry in entries))
        self.assertEqual(entries[0].source_title, self.benchmark["entries"][0]["title"])

    def test_each_benchmark_url_is_required_exactly_once(self):
        for rows in (
            self.report["entries"][:-1],
            self.report["entries"] + [self.report["entries"][0]],
            self.report["entries"][:-1] + [self.report["entries"][0]],
        ):
            with self.subTest(length=len(rows)), self.assertRaisesRegex(ValueError, "exactly once"):
                self.validate({**self.report, "entries": rows})

    def test_report_metadata_is_strict(self):
        for key, value in (
            ("version", True), ("version", 2), ("level", "A2"), ("level", "C1-preparation"),
            ("baseline_commit", "0" * 40), ("scope", "private-question-bank"), ("entries", {}),
        ):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.validate({**self.report, key: value})
        for invalid in ([], {**self.report, "mastery_equivalent": True}):
            with self.subTest(invalid=type(invalid)), self.assertRaises(ValueError):
                self.validate(invalid)

    def test_benchmark_count_and_duplicate_sources_are_rejected(self):
        for rows in (self.benchmark["entries"][:-1], self.benchmark["entries"] * 2):
            with self.assertRaisesRegex(ValueError, "Benchmark count or uniqueness"):
                validate_depth_report(self.report, {**self.benchmark, "entries": rows}, self.catalog)

    def test_source_access_findings_and_notes_are_strict(self):
        for key, value in (
            ("source_url", "https://example.org/not-in-the-benchmark"),
            ("source_url", " " + self.report["entries"][0]["source_url"]),
            ("source_title", "An approximate title"),
            ("access", "assumed"), ("finding", "identical"),
            ("note", ""), ("note", None), ("evidence", {}), ("references", {}),
        ):
            invalid = deepcopy(self.report)
            invalid["entries"][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.validate(invalid)

    def test_dates_must_be_real_canonical_and_not_future(self):
        for value in (
            None, "2026-02-30", "20260907", "2026-W37-1", "2026-09-07T12:00:00Z",
            (date.today() + timedelta(days=1)).isoformat(),
        ):
            invalid = deepcopy(self.report)
            invalid["entries"][0]["checked_on"] = value
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, "checked_on"):
                self.validate(invalid)

    def test_incomplete_access_never_counts_as_a_comparison(self):
        for access in ("partial", "unavailable"):
            for finding in ("sufficient", "enriched", "reference-qualified"):
                invalid = deepcopy(self.report)
                invalid["entries"][0].update(access=access, finding=finding)
                with self.subTest(access=access, finding=finding):
                    with self.assertRaisesRegex(ValueError, "must remain not-assessed"):
                        self.validate(invalid)
        for access in ("read", "partial", "unavailable"):
            self.report["entries"][0].update(
                access=access, finding="not-assessed", evidence=[],
                note="Synthetic limitation: the comparison has not been completed.",
            )
            entries = self.validate()
            self.assertFalse(entries[0].compared)
            self.assertEqual(sum(entry.compared for entry in entries), 133)

    def test_compared_findings_require_evidence(self):
        for finding in ("sufficient", "enriched", "reference-qualified"):
            self.report["entries"][0].update(finding=finding, evidence=[])
            with self.subTest(finding=finding):
                with self.assertRaisesRegex(ValueError, "require teaching and exercise evidence"):
                    self.validate()

    def test_evidence_resolves_within_the_same_level(self):
        for key, value in (
            ("lesson_id", "a2-foundations"), ("lesson_id", "a1-missing"),
            ("section_ids", ["missing"]), ("section_ids", []),
            ("section_ids", ["rule", "rule"]), ("practice_ids", ["missing"]),
            ("practice_ids", []), ("practice_ids", ["practice-01", "practice-01"]),
        ):
            invalid = deepcopy(self.report)
            invalid["entries"][0]["evidence"][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.validate(invalid)

    def test_practice_evidence_must_exercise_a_mapped_visible_section(self):
        lesson = self.catalog.lessons[0]
        other = replace(lesson.sections[0], id="other")
        lesson = replace(
            lesson, sections=(*lesson.sections, other),
            practice=(replace(lesson.practice[0], section_id="other"), *lesson.practice[1:]),
        )
        catalog = build_course_catalog([lesson, *self.catalog.lessons[1:]])
        with self.assertRaisesRegex(ValueError, "practice must exercise a mapped section"):
            validate_depth_report(self.report, self.benchmark, catalog)
        lesson = replace(lesson, sections=(replace(lesson.sections[0], examples=()), other))
        catalog = build_course_catalog([lesson, *self.catalog.lessons[1:]])
        with self.assertRaisesRegex(ValueError, "visible examples"):
            validate_depth_report(self.report, self.benchmark, catalog)

    def test_evidence_can_span_multiple_lessons_at_its_level(self):
        other = course_lesson("A1", 2, suffix="other")
        catalog = build_course_catalog([*self.catalog.lessons, other])
        self.report["entries"][0]["evidence"].append({
            "lesson_id": other.id, "section_ids": ["rule"], "practice_ids": ["check-01"],
        })
        entries = validate_depth_report(self.report, self.benchmark, catalog)
        self.assertEqual(len(entries[0].evidence), 2)

    def test_references_require_real_url_shape_and_a_purpose(self):
        reference = {
            "url": "https://example.org/grammar",
            "purpose": "Synthetic fixture: distinguish a grammatical alternative from a restriction.",
        }
        self.report["entries"][0].update(finding="reference-qualified", references=[reference])
        self.assertEqual(self.validate()[0].references[0].purpose, reference["purpose"])
        for key, value in (
            ("url", "/relative"), ("url", "javascript:alert(1)"),
            ("url", "https://user:secret@example.org/"), ("purpose", ""),
        ):
            invalid = deepcopy(self.report)
            invalid["entries"][0]["references"][0][key] = value
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                self.validate(invalid)

    def test_unknown_fields_are_rejected_at_every_nested_level(self):
        self.report["entries"][0]["references"] = [{"url": "https://example.org/", "purpose": "Fixture."}]
        for path in (
            ("entries", 0), ("entries", 0, "evidence", 0), ("entries", 0, "references", 0),
        ):
            invalid = deepcopy(self.report)
            target = invalid
            for key in path:
                target = target[key]
            target["unrecognized"] = True
            with self.subTest(path=path), self.assertRaisesRegex(ValueError, "invalid fields"):
                self.validate(invalid)


class CourseDepthCommandTests(SimpleTestCase):
    def setUp(self):
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        (self.root / "depth").mkdir()
        (self.root / "benchmarks").mkdir()
        self.catalog = build_course_catalog(
            [course_lesson(level) for level in BENCHMARK_COUNTS]
        )
        for level in BENCHMARK_COUNTS:
            name = f"{level.lower()}.json"
            benchmark = json.loads(
                (CONTENT_ROOT / "benchmarks" / name).read_text(encoding="utf-8")
            )
            (self.root / "benchmarks" / name).write_text(json.dumps(benchmark), encoding="utf-8")
            (self.root / "depth" / name).write_text(json.dumps(depth_fixture(benchmark)), encoding="utf-8")
        for name, value in (("CONTENT_ROOT", self.root), ("load_course_catalog", self.catalog)):
            kwargs = {"return_value": value} if name == "load_course_catalog" else {"new": value}
            mocked = patch(f"study.management.commands.validate_courses.{name}", **kwargs)
            mocked.start()
            self.addCleanup(mocked.stop)

    def test_depth_is_optional_and_missing_requested_files_fail_explicitly(self):
        (self.root / "depth" / "a1.json").unlink()
        output = StringIO()
        call_command("validate_courses", stdout=output)
        self.assertIn("Validated 4 course lessons.", output.getvalue())
        self.assertNotIn("depth:", output.getvalue())
        with self.assertRaises(CommandError):
            call_command("validate_courses", depth=True, stdout=StringIO())

    def test_command_separates_read_access_from_completed_comparisons(self):
        path = self.root / "depth" / "a1.json"
        report = json.loads(path.read_text(encoding="utf-8"))
        for index, access in enumerate(("partial", "unavailable", "read")):
            report["entries"][index].update(access=access, finding="not-assessed", evidence=[])
        path.write_text(json.dumps(report), encoding="utf-8")
        output = StringIO()
        call_command("validate_courses", depth=True, stdout=output)
        text = output.getvalue()
        self.assertIn(
            "A1 depth: 134 recorded; 132 read, 1 partial, 1 unavailable; 131 compared, 3 not assessed.",
            text,
        )
        self.assertIn("A2 depth: 165 recorded; 165 read", text)
        self.assertIn("B1 depth: 96 recorded; 96 read", text)
        self.assertIn("B2 depth: 84 recorded; 84 read", text)
        self.assertIn("not source-reading truth", text)

    def test_invalid_later_report_does_not_print_premature_success(self):
        (self.root / "depth" / "b2.json").write_text("{", encoding="utf-8")
        output = StringIO()
        with self.assertRaises(CommandError):
            call_command("validate_courses", depth=True, stdout=output)
        self.assertEqual(output.getvalue(), "")


class CourseDepthBundleTests(SimpleTestCase):
    def test_all_published_depth_reports_resolve_to_the_current_course(self):
        expected_files = {f"{level.lower()}.json" for level in BENCHMARK_COUNTS}
        self.assertEqual(
            {path.name for path in (CONTENT_ROOT / "depth").glob("*.json")},
            expected_files,
        )
        catalog = load_course_catalog()
        source_urls = set()
        for level, count in BENCHMARK_COUNTS.items():
            with self.subTest(level=level):
                name = f"{level.lower()}.json"
                entries = validate_depth_report(
                    json.loads((CONTENT_ROOT / "depth" / name).read_text(encoding="utf-8")),
                    json.loads((CONTENT_ROOT / "benchmarks" / name).read_text(encoding="utf-8")),
                    catalog,
                )
                self.assertEqual(len(entries), count)
                urls = {entry.source_url for entry in entries}
                self.assertTrue(source_urls.isdisjoint(urls))
                source_urls.update(urls)
        self.assertEqual(len(source_urls), 479)


class PublishedCourseIdentityTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.manifest = json.loads(
            (CONTENT_ROOT / "course_manifest.json").read_text(encoding="utf-8")
        )
        cls.lessons = {}
        for path in (CONTENT_ROOT / "courses").glob("*/*.json"):
            lesson = json.loads(path.read_text(encoding="utf-8"))
            cls.lessons[lesson["id"]] = lesson

    def test_manifest_identifies_the_complete_fixed_published_baseline(self):
        self.assertEqual(self.manifest["version"], 1)
        self.assertEqual(self.manifest["baseline_commit"], DEPTH_BASELINE_COMMIT)
        published = self.manifest["lessons"]
        self.assertEqual(len(published), 129)
        self.assertEqual(len({lesson["id"] for lesson in published}), 129)
        self.assertEqual(sum(len(lesson["section_ids"]) for lesson in published), 348)
        self.assertEqual(sum(len(lesson["item_ids"]) for lesson in published), 2169)

    def test_published_routes_anchors_items_and_preparation_links_survive(self):
        for published in self.manifest["lessons"]:
            with self.subTest(lesson=published["id"]):
                self.assertIn(published["id"], self.lessons)
                current = self.lessons[published["id"]]
                self.assertEqual(current["slug"], published["slug"])
                self.assertEqual(current["cefr_level"], published["level"])
                self.assertLessEqual(
                    set(published["section_ids"]),
                    {section["id"] for section in current["sections"]},
                )
                self.assertLessEqual(
                    set(published["item_ids"]), {item["id"] for item in current["practice"]},
                )
                self.assertLessEqual(set(published["prerequisites"]), set(current["prerequisites"]))
                self.assertLessEqual(
                    {(source["label"], source["url"]) for source in published["sources"]},
                    {(source["label"], source["url"]) for source in current["sources"]},
                )

    def test_reference_library_and_preparation_bridge_are_byte_preserved(self):
        self.assertEqual(
            hashlib.sha256((CONTENT_ROOT / "curriculum.json").read_bytes()).hexdigest(),
            self.manifest["reference_sha256"],
        )
        bridge = [
            lesson for lesson in self.manifest["lessons"] if lesson["level"] == "C1-preparation"
        ]
        self.assertEqual(len(bridge), 9)
        for published in bridge:
            with self.subTest(lesson=published["id"]):
                self.assertEqual(
                    hashlib.sha256((CONTENT_ROOT / published["file"]).read_bytes()).hexdigest(),
                    published["baseline_sha256"],
                )
