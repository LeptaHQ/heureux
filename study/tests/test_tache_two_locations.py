from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import patch
import hashlib
import json

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from study import catalogue, content_loader as content
from study.models import Annotation, AnnotationKind, PersonalResponse
from study.oral_highlights import (
    QuestionText, _project_location_annotation, _render_questions,
)
from study.oral_history import variant_annotation_key
from study.response_personalization import effective_response
from study.routing import prompt_detail_url
from study.tache_two_dialogues import dialogue_response
from study.tache_two_location_history import LOCATION_HISTORY_PATH, load_location_history

from . import factories


class TacheTwoLocationCorpusTests(SimpleTestCase):
    def setUp(self):
        catalogue.clear_catalogue_cache()
        self.addCleanup(catalogue.clear_catalogue_cache)

    def test_arrival_theme_is_unchanged(self):
        _, mapping = catalogue.tache_two_subject_themes()
        protected = {
            row.group for key, row in catalogue.tache_two_dialogues().items()
            if mapping[key] == "arrivee"
        }
        rows = [
            row for path in (content.QUESTION_BANK_DIR / "dialogues").glob("*.json")
            for row in json.loads(path.read_text())["dialogues"]
            if row["group"] in protected
        ]
        snapshot = json.dumps(
            sorted(rows, key=lambda row: row["group"]), ensure_ascii=False, sort_keys=True,
        ).encode()
        self.assertEqual(len(rows), 6)
        self.assertEqual(
            hashlib.sha256(snapshot).hexdigest(),
            "b3f62225759c57d763f3af704a1a1756d7d83700d5b9c061b8b5b2de52304802",
        )

    def test_history_excludes_arrival_theme_and_retains_topic_and_question_order(self):
        history = catalogue.tache_two_location_history()
        _, mapping = catalogue.tache_two_subject_themes()
        dialogues = catalogue.tache_two_dialogues()
        for key, current in dialogues.items():
            if current.group not in history:
                continue
            with self.subTest(group=current.group):
                self.assertNotEqual(mapping[key], "arrivee")
                for old in history[current.group].revisions:
                    self.assertEqual(
                        [question.topic for question in old.questions],
                        [question.topic for question in current.questions],
                    )
                    self.assertEqual(
                        [question.follow_up_to for question in old.questions],
                        [question.follow_up_to for question in current.questions],
                    )

    def test_recorded_substitutions_reconstruct_each_current_visible_model(self):
        by_group = {item.group: item for item in catalogue.tache_two_dialogues().values()}
        for group, history in catalogue.tache_two_location_history().items():
            previous = history.revisions[0]
            current = by_group[group]
            old_fields = [
                previous.opening, *(row.question for row in previous.questions), previous.closing,
            ]
            new_fields = [
                current.opening, *(row.question for row in current.questions), current.closing,
            ]
            for old, new in zip(old_fields, new_fields):
                for before, after in history.replacements:
                    old = old.replace(before, after)
                self.assertEqual(old, new, group)

    def test_fixed_canadian_settings_and_francophone_roles_remain_valid(self):
        by_group = {item.group: item for item in catalogue.tache_two_dialogues().values()}
        for group, place in (
            ("friend-city-housing-search-advice", "Toronto"),
            ("colleague-montreal-work-week-transit", "Montréal"),
            ("edmonton-newcomer-neighbor-schools", "Edmonton"),
            ("canadian-friend-long-time-catch-up", "Calgary"),
        ):
            with self.subTest(group=group):
                self.assertIn(place, json.dumps(asdict(by_group[group]), ensure_ascii=False))
                self.assertNotIn("Seattle", json.dumps(asdict(by_group[group]), ensure_ascii=False))
        student = by_group["french-class-survey-francophone-student"]
        self.assertIn("du Canada", student.questions[0].answer)
        self.assertIn("Montréal", student.questions[1].answer)
        countries = by_group["friend-visited-countries-destination-choice"]
        self.assertIn("Le Canada et les États-Unis", countries.questions[0].answer)

    def test_history_rejects_invalid_replacements_and_follow_up_references(self):
        data = json.loads(LOCATION_HISTORY_PATH.read_text())
        first = next(iter(data["groups"].values()))
        for invalid in (["", "Seattle"], ["Calgary"], ["Calgary", "Calgary"]):
            first["replacements"][0] = invalid
            with patch("pathlib.Path.read_text", return_value=json.dumps(data)):
                with self.assertRaisesRegex(ValueError, "invalid replacement"):
                    load_location_history()
        data = json.loads(LOCATION_HISTORY_PATH.read_text())
        first = next(iter(data["groups"].values()))
        first["revisions"][0]["questions"][0]["follow_up_to"] = 2
        with patch("pathlib.Path.read_text", return_value=json.dumps(data)):
            with self.assertRaisesRegex(ValueError, "invalid follow-up"):
                load_location_history()

    def test_utf16_projection_preserves_a_selection_crossing_a_replaced_place(self):
        old = QuestionText("<div data-annotation-root>🎬 À Beltline, puis un café.</div>")
        new = QuestionText("<div data-annotation-root>🎬 À Capitol Hill, puis un café.</div>")
        quote = "À Beltline, puis"
        start = old.text.index(quote.encode("utf-16-le")) // 2
        anchor = SimpleNamespace(
            quote=quote, start_offset=start, end_offset=start + len(quote),
            prefix=old.slice(0, start), suffix=old.slice(start + len(quote), len(old.units)),
        )
        offsets = _project_location_annotation(anchor, old, new, (("Beltline", "Capitol Hill"),))
        self.assertIsNotNone(offsets)
        self.assertEqual(new.slice(*offsets), "À Capitol Hill, puis")
        altered = QuestionText("<div data-annotation-root>🎬 À Capitol Hill, puis le bus.</div>")
        self.assertIsNone(
            _project_location_annotation(anchor, old, altered, (("Beltline", "Capitol Hill"),))
        )


class PublishedTacheTwoHighlightTests(TestCase):
    def setUp(self):
        catalogue.clear_catalogue_cache()
        self.addCleanup(catalogue.clear_catalogue_cache)
        self.user = factories.make_user("location-highlights")
        self.task = factories.make_task(factories.make_part("eo"), "tache-2")
        self.response = factories.make_response(theme=factories.make_theme(task=self.task))
        key, self.current = next(
            (key, value) for key, value in catalogue.tache_two_dialogues().items()
            if value.group == "estate-agent-housing-options"
        )
        self.response.content_key = key
        self.response.semantic_group = self.current.group
        self.response.save(update_fields=["content_key", "semantic_group"])
        self.prompt = self.response.prompts.get()
        self.prompt.content_key = key
        self.prompt.model_content = {"storage_key": key}
        self.prompt.save(update_fields=["content_key", "model_content"])
        self.old = catalogue.tache_two_location_history()[self.current.group].revisions[0]
        self.path = prompt_detail_url(self.prompt)
        self.client.force_login(self.user)

    def highlight(self, number, quote=None, *, surface="detail", **overrides):
        previous = dialogue_response(self.old)
        rendered = _render_questions(
            self.prompt, previous, surface, [self.prompt], dialogue=self.old,
        )
        start, end = rendered.fields[(number, "question")]
        if quote is not None:
            start = rendered.text.index(quote.encode("utf-16-le"), start * 2, end * 2) // 2
            end = start + len(quote.encode("utf-16-le")) // 2
        return Annotation.objects.create(**({
            "user": self.user, "task": self.task, "kind": AnnotationKind.HIGHLIGHT,
            "source_path": self.path,
            "source_key": variant_annotation_key(
                self.prompt, previous, tache_two_dialogue=self.old,
            ) + (":back" if surface == "back" else ""),
            "quote": rendered.slice(start, end), "start_offset": start, "end_offset": end,
            "prefix": rendered.slice(max(0, start - 160), start),
            "suffix": rendered.slice(end, end + 160),
        } | overrides))

    def fetch(self, path=None):
        response = self.client.get(
            reverse("study:annotations_for_source"), {"source_path": path or self.path},
        )
        self.assertEqual(response.status_code, 200)
        return response.json()["highlights"]

    def assert_current(self, annotation, surface="detail"):
        annotation.refresh_from_db()
        current = effective_response(self.response, self.user, prompt=self.prompt)
        key = variant_annotation_key(self.prompt, current) + (":back" if surface == "back" else "")
        self.assertEqual(annotation.source_key, key)
        rendered = _render_questions(self.prompt, current, surface, [self.prompt])
        self.assertEqual(
            rendered.slice(annotation.start_offset, annotation.end_offset), annotation.quote,
        )
        self.assertTrue(rendered.slice(0, annotation.start_offset).endswith(annotation.prefix))
        self.assertTrue(
            rendered.slice(annotation.end_offset, len(rendered.units)).startswith(annotation.suffix)
        )

    def test_saved_key_matches_original_published_layout(self):
        previous = dialogue_response(self.old)
        with patch("study.tache_two_dialogues.published_dialogue", return_value=self.old):
            self.assertEqual(
                variant_annotation_key(self.prompt, previous),
                variant_annotation_key(self.prompt, previous, tache_two_dialogue=self.old),
            )

    def test_unchanged_and_replaced_highlights_remain_visible_and_keep_notes(self):
        marks = [
            self.highlight(1),
            self.highlight(3, "Beltline"),
            self.highlight(3),
            self.highlight(8, body="My learned phrase.", title="Review", study_later=True),
        ]
        highlights = self.fetch()
        self.assertEqual(len(highlights), len(marks))
        for mark in marks:
            self.assert_current(mark)
        self.assertEqual(marks[1].quote, "Capitol Hill")
        self.assertIn("Capitol Hill et Ballard", marks[2].quote)
        self.assertEqual(
            (marks[3].body, marks[3].title, marks[3].study_later),
            ("My learned phrase.", "Review", True),
        )
        revisions = [mark.updated_at for mark in marks]
        self.fetch()
        for mark, timestamp in zip(marks, revisions):
            mark.refresh_from_db()
            self.assertEqual(mark.updated_at, timestamp)

    def test_review_front_and_back_are_preserved(self):
        path = reverse("study:task_review", args=["eo", "tache-2"]) + "?kind=spine"
        back = self.highlight(3, "Bridgeland", surface="back", source_path=path)
        front = self.highlight(
            1, source_path=path,
            source_key=variant_annotation_key(
                self.prompt, dialogue_response(self.old), tache_two_dialogue=self.old,
            ) + ":front",
        )
        self.fetch(path)
        self.assert_current(back, "back")
        front.refresh_from_db()
        self.assertEqual(
            front.source_key, variant_annotation_key(self.prompt, dialogue_response(self.current)) + ":front",
        )

    def test_old_personal_model_and_private_note_are_not_rewritten(self):
        previous = dialogue_response(self.old)
        values = asdict(previous)
        values.pop("is_personal")
        values["arguments"] = list(values["arguments"])
        values["nuance"] = "My private prompt explanation."
        personal = PersonalResponse.objects.create(
            user=self.user, response=self.response, source_prompt=self.prompt, **values,
        )
        mark = self.highlight(3)
        self.fetch()
        self.assert_current(mark)
        self.assertIn("Beltline et Bridgeland", mark.quote)
        personal.refresh_from_db()
        self.assertEqual(personal.arguments, values["arguments"])
        self.assertEqual(personal.nuance, values["nuance"])

    def test_personal_edits_remain_unchanged_and_only_unmodified_fields_recover(self):
        previous = dialogue_response(self.old)
        values = asdict(previous)
        values.pop("is_personal")
        values["arguments"] = list(values["arguments"])
        values["arguments"][2]["idea"] = "Ma question personnelle sur le quartier ?"
        personal = PersonalResponse.objects.create(
            user=self.user, response=self.response, source_prompt=self.prompt, **values,
        )
        unchanged = self.highlight(8)
        changed = self.highlight(3, "Beltline")
        old_key = changed.source_key
        self.fetch()
        self.assert_current(unchanged)
        changed.refresh_from_db()
        self.assertEqual(changed.source_key, old_key)
        personal.refresh_from_db()
        self.assertEqual(personal.arguments, values["arguments"])

    def test_other_users_invalid_context_and_unknown_revisions_are_untouched(self):
        other = self.highlight(1, user=factories.make_user("other-location-reader"))
        invalid = self.highlight(2, prefix="Not the saved source context")
        unknown = self.highlight(8, source_key=f"response:{self.prompt.content_key}:variant-0000000000000000")
        keys = {mark.pk: mark.source_key for mark in (other, invalid, unknown)}
        self.fetch()
        for mark in (other, invalid, unknown):
            mark.refresh_from_db()
            self.assertEqual(mark.source_key, keys[mark.pk])
        self.assertEqual(Annotation.objects.count(), 3)
