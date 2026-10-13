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
                    if history[current.group].replacements:
                        self.assertEqual(
                            [question.topic for question in old.questions],
                            [question.topic for question in current.questions],
                        )
                        reference = history[current.group].revisions[-1]
                        if len(history[current.group].revisions) == 1:
                            reference = current
                        self.assertEqual(
                            [question.follow_up_to for question in old.questions],
                            [question.follow_up_to for question in reference.questions],
                        )

    def test_recorded_substitutions_reconstruct_current_or_archived_geographic_models(self):
        by_group = {item.group: item for item in catalogue.tache_two_dialogues().values()}
        for group, history in catalogue.tache_two_location_history().items():
            if not history.replacements:
                continue
            previous = history.revisions[0]
            current = history.revisions[-1] if len(history.revisions) > 1 else by_group[group]
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

    def test_apartment_condition_question_offers_work_or_ready_to_live_in(self):
        current = next(
            row for row in catalogue.tache_two_dialogues().values()
            if row.group == "estate-agent-advertised-apartment-purchase"
        )
        self.assertEqual(
            current.questions[2].question,
            "L'appartement nécessite-t-il des travaux, ou est-il prêt à être habité ?",
        )
        self.assertIn("habitable immédiatement", current.questions[2].answer)
        self.assertEqual(
            current.questions[7].question, "Quand pourrais-je passer voir l'appartement ?",
        )
        self.assertEqual(
            current.questions[5].question,
            "L'appartement dispose-t-il d'un balcon, d'un espace de rangement ou d'une place de stationnement ?",
        )
        self.assertIsNone(current.questions[5].follow_up_to)
        hints = json.loads(content.TACHE_TWO_SUBJECT_HINTS_PATH.read_text())["groups"][current.group]
        self.assertEqual(hints[5]["english"], "Balcony, storage space and parking")

    def test_delivery_price_precedes_access_solutions_and_pistes_follow_question_order(self):
        current = next(
            row for row in catalogue.tache_two_dialogues().values()
            if row.group == "furniture-delivery-service"
        )
        self.assertTrue(current.questions[1].question.startswith("Quel est votre tarif de base"))
        self.assertEqual(
            current.questions[2].question,
            "Si le canapé ne passe pas par l'escalier, quelles solutions proposez-vous ?",
        )
        self.assertEqual(current.questions[3].follow_up_to, 2)
        hints = json.loads(content.TACHE_TWO_SUBJECT_HINTS_PATH.read_text())["groups"][current.group]
        self.assertEqual(hints[1]["english"], "Base rate and distance, floor or access surcharges")
        self.assertEqual(hints[2]["french"], "Solutions si le canapé ne passe pas par l'escalier")
        self.assertNotIn("photos", current.closing)

    def test_quebec_agency_starts_with_offers_fees_then_availability_and_lease_length(self):
        current = next(
            row for row in catalogue.tache_two_dialogues().values()
            if row.group == "quebec-newcomer-estate-agency-housing-procedures"
        )
        self.assertEqual(
            current.questions[0].question,
            "Quels types de logements avez-vous actuellement à louer, et vos services sont-ils payants pour les locataires ?",
        )
        self.assertEqual(
            current.questions[1].question,
            "À partir de quand ces logements sont-ils disponibles, et quelle est la durée minimale du bail ?",
        )
        self.assertEqual(current.questions[1].follow_up_to, 1)
        self.assertIn("payés par le propriétaire", current.questions[0].answer)
        self.assertIn("immédiatement", current.questions[1].answer)
        self.assertIn("d'un an", current.questions[1].answer)
        previous = catalogue.tache_two_location_history()[current.group].revisions[-1]
        self.assertEqual(current.opening, previous.opening)
        self.assertEqual(current.closing, previous.closing)
        for number, (old, new) in enumerate(zip(previous.questions, current.questions), 1):
            if number == 7:
                continue
            self.assertEqual(old.question, new.question)
            self.assertEqual(old.follow_up_to, new.follow_up_to)
            self.assertEqual(old.topic, new.topic)
            self.assertEqual(old.condition, new.condition)
        self.assertEqual(
            current.questions[6].question,
            "Si je n'ai pas de références locatives au Québec, quels justificatifs puis-je fournir à la place, et faut-il un garant ?",
        )
        self.assertEqual(current.questions[6].follow_up_to, 6)
        self.assertIn("ancien propriétaire à l'étranger", current.questions[6].answer)
        self.assertIn("un garant peut être demandé selon", current.questions[6].answer)
        hints = json.loads(content.TACHE_TWO_SUBJECT_HINTS_PATH.read_text())["groups"][current.group]
        self.assertEqual(hints[0]["english"], "Available rental types and agency fees for tenants")
        self.assertEqual(hints[1]["english"], "Availability dates and minimum lease length")
        self.assertEqual(
            hints[6]["french"],
            "Justificatifs sans références locatives au Québec et nécessité d'un garant",
        )
        self.assertEqual(
            hints[6]["english"],
            "Alternative supporting documents without Quebec rental references and need for a guarantor",
        )

    def test_shared_room_combines_costs_and_separates_availability_from_lease_arrangements(self):
        current = next(
            row for row in catalogue.tache_two_dialogues().values()
            if row.group == "offered-room-in-existing-shared-apartment"
        )
        self.assertEqual(len(current.questions), 8)
        self.assertEqual(
            [row.question for row in current.questions[:3]],
            [
                "Combien coûterait la chambre par mois, et quelles charges et dépenses communes seraient comprises dans ce loyer ?",
                "À partir de quand la chambre sera-t-elle libre ?",
                "Signerais-je un bail ou une entente de sous-location, et pour quelle durée minimale ?",
            ],
        )
        self.assertIn("1 300 $ par mois", current.questions[0].answer)
        self.assertIn("chauffage, électricité et Internet compris", current.questions[0].answer)
        self.assertIn("produits ménagers", current.questions[0].answer)
        self.assertEqual(current.questions[1].answer, "Dès le premier du mois prochain.")
        self.assertIn("ajout au bail existant", current.questions[2].answer)
        self.assertIn("six mois", current.questions[2].answer)
        self.assertTrue(all(row.follow_up_to is None for row in current.questions[:3]))
        previous = catalogue.tache_two_location_history()[current.group].revisions[0]
        self.assertEqual(current.opening, previous.opening)
        self.assertEqual(current.closing, previous.closing)
        for old, new in zip(previous.questions[3:], current.questions[3:]):
            self.assertEqual(old.question, new.question)
            self.assertEqual(old.topic, new.topic)
            self.assertEqual(old.follow_up_to, new.follow_up_to)
            self.assertEqual(old.condition, new.condition)
        hints = json.loads(content.TACHE_TWO_SUBJECT_HINTS_PATH.read_text())["groups"][current.group]
        self.assertEqual(
            hints[:3],
            [
                {
                    "french": "Loyer mensuel, charges et dépenses communes comprises",
                    "english": "Monthly rent, included utilities and shared expenses",
                },
                {
                    "french": "Date de disponibilité de la chambre",
                    "english": "Room availability date",
                },
                {
                    "french": "Bail ou entente de sous-location et durée minimale",
                    "english": "Lease or sublet agreement and minimum term",
                },
            ],
        )

    def test_friend_housing_advice_has_two_procedure_questions_and_concrete_extra_costs(self):
        current = next(
            row for row in catalogue.tache_two_dialogues().values()
            if row.group == "friend-city-housing-search-advice"
        )
        previous = catalogue.tache_two_location_history()[current.group].revisions[0]
        self.assertEqual(len(current.questions), 8)
        self.assertEqual(
            [row.topic for row in current.questions],
            ["Quartiers"] * 3 + ["Budget"] * 2 + ["Recherche", "Démarches", "Démarches"],
        )
        self.assertEqual(current.opening, previous.opening)
        self.assertEqual(current.closing, previous.closing)
        for old_number, new_number in ((1, 1), (2, 2), (3, 3), (5, 4), (7, 6)):
            self.assertEqual(
                current.questions[new_number - 1].question,
                previous.questions[old_number - 1].question,
            )
        self.assertEqual(
            current.questions[4].question,
            "En plus du loyer, quels frais dois-je prévoir, par exemple pour le chauffage, Internet ou l'assurance habitation ?",
        )
        self.assertEqual(current.questions[4].follow_up_to, 4)
        self.assertIn("l'assurance habitation", current.questions[4].answer)
        self.assertEqual(
            current.questions[6].question,
            "Quels documents me conseillerais-tu de préparer pour déposer un dossier de location ?",
        )
        self.assertIn("les exigences varient selon le propriétaire", current.questions[6].answer)
        self.assertEqual(
            current.questions[7].question,
            "Si je n'ai pas de références locatives au Canada, quels justificatifs puis-je fournir à la place, et faut-il un garant ?",
        )
        self.assertEqual(current.questions[7].follow_up_to, 7)
        self.assertIn("Certains propriétaires", current.questions[7].answer)
        self.assertIn("d'autres peuvent demander un garant", current.questions[7].answer)
        hints = json.loads(content.TACHE_TWO_SUBJECT_HINTS_PATH.read_text())["groups"][current.group]
        self.assertEqual(hints[4]["english"], "Costs beyond rent: heating, Internet and home insurance")
        self.assertEqual(hints[6]["english"], "Documents to prepare for the rental application")
        self.assertEqual(
            hints[7]["english"], "Alternatives to Canadian rental references and need for a guarantor",
        )

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
        self.prompt = self.response.prompts.get()
        self.configure_group("estate-agent-housing-options")
        self.client.force_login(self.user)

    def configure_group(self, group):
        key, self.current = next(
            (key, value) for key, value in catalogue.tache_two_dialogues().items()
            if value.group == group
        )
        self.response.content_key = key
        self.response.semantic_group = self.current.group
        self.response.save(update_fields=["content_key", "semantic_group"])
        self.prompt.content_key = key
        self.prompt.model_content = {"storage_key": key}
        self.prompt.save(update_fields=["content_key", "model_content"])
        self.old = catalogue.tache_two_location_history()[self.current.group].revisions[0]
        self.path = prompt_detail_url(self.prompt)

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

    def test_delivery_reorder_recovers_unchanged_questions_but_not_rewritten_wording(self):
        self.configure_group("furniture-delivery-service")
        marks = [
            self.highlight(1),
            self.highlight(3, body="My price vocabulary."),
            self.highlight(4),
            self.highlight(7),
        ]
        changed = self.highlight(2)
        old_key = changed.source_key
        review_path = reverse("study:task_review", args=["eo", "tache-2"]) + "?kind=spine"
        back = self.highlight(3, surface="back", source_path=review_path)
        self.fetch()
        self.fetch(review_path)
        for mark in marks:
            self.assert_current(mark)
        self.assert_current(back, "back")
        rendered = _render_questions(
            self.prompt, dialogue_response(self.current), "detail", [self.prompt],
        )
        self.assertEqual(
            (marks[1].start_offset, marks[1].end_offset), rendered.fields[(2, "question")],
        )
        self.assertEqual(marks[1].body, "My price vocabulary.")
        changed.refresh_from_db()
        self.assertEqual(changed.source_key, old_key)
        self.assertIn("mesures et de photos", changed.quote)
        self.assertEqual(Annotation.objects.count(), 6)

    def test_apartment_rewrite_preserves_other_highlights_from_both_published_revisions(self):
        self.configure_group("estate-agent-advertised-apartment-purchase")
        marks = [self.highlight(1), self.highlight(7)]
        previous = dialogue_response(self.old)
        rendered = _render_questions(
            self.prompt, previous, "detail", [self.prompt], dialogue=self.old,
        )
        quote = "Beltline"
        start = rendered.text.index(quote.encode("utf-16-le")) // 2
        location = Annotation.objects.create(
            user=self.user, task=self.task, kind=AnnotationKind.HIGHLIGHT,
            source_path=self.path,
            source_key=variant_annotation_key(self.prompt, previous, tache_two_dialogue=self.old),
            quote=quote, start_offset=start, end_offset=start + len(quote),
            prefix=rendered.slice(max(0, start - 160), start),
            suffix=rendered.slice(start + len(quote), start + len(quote) + 160),
        )
        self.old = catalogue.tache_two_location_history()[self.current.group].revisions[-1]
        marks.append(self.highlight(4))
        changed = self.highlight(3, body="My original work-needed note.")
        old_key = changed.source_key
        self.fetch()
        for mark in (*marks, location):
            self.assert_current(mark)
        self.assertEqual(location.quote, "Capitol Hill")
        changed.refresh_from_db()
        self.assertEqual(changed.source_key, old_key)
        self.assertEqual(changed.body, "My original work-needed note.")

    def test_quebec_agency_rewrite_preserves_highlights_from_original_revision(self):
        self.configure_group("quebec-newcomer-estate-agency-housing-procedures")
        unchanged = [self.highlight(number) for number in (3, 4, 5, 6, 8)]
        changed = [self.highlight(number) for number in (1, 2, 7)]
        old_keys = [mark.source_key for mark in changed]
        self.fetch()
        for mark in unchanged:
            self.assert_current(mark)
        for mark, old_key in zip(changed, old_keys):
            mark.refresh_from_db()
            self.assertEqual(mark.source_key, old_key)
        self.assertEqual(Annotation.objects.count(), 8)

    def test_quebec_agency_guarantor_edit_preserves_other_highlights_and_archived_note(self):
        self.configure_group("quebec-newcomer-estate-agency-housing-procedures")
        self.old = catalogue.tache_two_location_history()[self.current.group].revisions[-1]
        unchanged = [self.highlight(number) for number in (1, 2, 3, 4, 5, 6, 8)]
        changed = self.highlight(7, body="My rental references note.", study_later=True)
        old_key = changed.source_key
        self.fetch()
        for mark in unchanged:
            self.assert_current(mark)
        changed.refresh_from_db()
        self.assertEqual(changed.source_key, old_key)
        self.assertEqual(changed.body, "My rental references note.")
        self.assertTrue(changed.study_later)
        self.assertEqual(Annotation.objects.count(), 8)

    def test_shared_room_combination_preserves_unchanged_highlights_and_archived_notes(self):
        self.configure_group("offered-room-in-existing-shared-apartment")
        unchanged = [self.highlight(number) for number in range(4, 9)]
        changed = [
            self.highlight(number, body=f"My original question {number} note.", study_later=True)
            for number in range(1, 4)
        ]
        old_keys = [mark.source_key for mark in changed]
        self.fetch()
        for mark in unchanged:
            self.assert_current(mark)
        for number, (mark, old_key) in enumerate(zip(changed, old_keys), 1):
            mark.refresh_from_db()
            self.assertEqual(mark.source_key, old_key)
            self.assertEqual(mark.body, f"My original question {number} note.")
            self.assertTrue(mark.study_later)
        self.assertEqual(Annotation.objects.count(), 8)

    def test_friend_housing_topic_split_preserves_unchanged_and_moved_question_highlights(self):
        self.configure_group("friend-city-housing-search-advice")
        unchanged = [
            self.highlight(number, body=f"My learned question {number}.")
            for number in (1, 2, 3, 5, 7)
        ]
        changed = [self.highlight(number) for number in (4, 6, 8)]
        old_keys = [mark.source_key for mark in changed]
        self.fetch()
        rendered = _render_questions(
            self.prompt, dialogue_response(self.current), "detail", [self.prompt],
        )
        for mark, new_number in zip(unchanged, (1, 2, 3, 4, 6)):
            self.assert_current(mark)
            self.assertEqual(
                (mark.start_offset, mark.end_offset), rendered.fields[(new_number, "question")],
            )
            self.assertTrue(mark.body.startswith("My learned question "))
        for mark, old_key in zip(changed, old_keys):
            mark.refresh_from_db()
            self.assertEqual(mark.source_key, old_key)
        self.assertEqual(Annotation.objects.count(), 8)

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
