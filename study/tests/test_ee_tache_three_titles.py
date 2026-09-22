"""EE3 titles are answer content, not synthesis text or a new study identity."""

import json
import re
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase, TestCase
from django.utils import timezone

from study import content_loader as content
from study.management.commands.import_content import Command
from study.models import (
    Annotation,
    AnnotationKind,
    Card,
    CardState,
    CardType,
    OralStateSnapshot,
    PersonalResponse,
    Prompt,
    Response,
    ReviewLog,
    ReviewSession,
)
from study.oral_history import snapshot
from study.routing import prompt_detail_url

from . import factories


class EeTacheThreeTitleContentTests(SimpleTestCase):
    def test_all_source_totals_include_the_title_without_changing_part_counts(self):
        count = 0
        for path in content.EE_TACHE_THREE_RESPONSES_DIR.glob("*.md"):
            text = path.read_text(encoding="utf-8")
            essays = content._ee_tache_three_parse_essays(text)
            totals = re.findall(r"\*\*Total : (\d+) mots \(titre compris\)\*\*", text)
            syntheses = re.findall(r"Partie 1 — Synthèse \((\d+) mots\)", text)
            positions = re.findall(r"Partie 2 — Point de vue personnel \((\d+) mots\)", text)
            self.assertEqual(len(totals), len(essays))
            self.assertEqual(len(syntheses), len(essays))
            self.assertEqual(len(positions), len(essays))
            for essay, total, synthese, position in zip(essays, totals, syntheses, positions):
                with self.subTest(path=path.name, label=essay["label"]):
                    answer = content.ee_tache_three_answer_text(
                        essay["heading"], essay["synthese"], essay["point_de_vue"],
                    )
                    self.assertEqual(int(total), content._ee_word_count(answer))
                    self.assertEqual(int(synthese), content._ee_word_count(essay["synthese"]))
                    self.assertEqual(int(position), content._ee_word_count(essay["point_de_vue"]))
                    self.assertTrue(120 <= int(total) <= 180)
                    self.assertTrue(40 <= int(synthese) <= 60)
                    self.assertTrue(80 <= int(position) <= 120)
                    count += 1
        self.assertEqual(count, 138)

    def test_effective_titles_follow_author_overrides_and_canonical_groups(self):
        responses = content.parse_ee_tache_three_responses()
        authors = content.load_ee_tache_three_author_responses()
        sources = {
            row.content_key: row
            for month in content.load_ee_tache_three_months()
            for row in month.combinaisons
        }
        self.assertEqual(len(responses), 78)
        self.assertEqual(sum(len(row.prompts) for row in responses), 138)
        self.assertEqual(len(authors), 10)
        for row in responses:
            with self.subTest(key=row.content_key):
                author = authors.get(row.content_key)
                source = sources[row.content_key]
                self.assertEqual(row.reformulation, author["heading"] if author else source.heading)
                self.assertEqual(row.position, author["synthese"] if author else source.synthese)
                self.assertEqual(row.position_claire, author["point_de_vue"] if author else source.point_de_vue)
                answer = content.ee_tache_three_answer_text(
                    row.reformulation, row.position, row.position_claire,
                )
                self.assertTrue(row.body.endswith(answer))
                self.assertTrue(120 <= content._ee_word_count(answer) <= 180)
                self.assertTrue(40 <= content._ee_word_count(row.position) <= 60)
                self.assertTrue(80 <= content._ee_word_count(row.position_claire) <= 120)
                self.assertNotRegex(answer, r"https?://|www\.")

    def test_source_parser_rejects_a_title_that_pushes_the_total_over_180(self):
        source = (
            "## Combinaison 1\n\n**Sujet :** Un débat\n\n### Un titre\n\n"
            "**Partie 1 — Synthèse (60 mots)**\n\n"
            + " ".join(["synthèse"] * 60)
            + "\n\n**Partie 2 — Point de vue personnel (120 mots)**\n\n"
            + " ".join(["opinion"] * 120)
            + "\n\n**Total : 180 mots**"
        )
        with self.assertRaisesMessage(ValueError, "including title) has 182 words"):
            content._ee_tache_three_parse_essays(source)

    def test_author_parser_rejects_a_title_that_pushes_the_total_over_180(self):
        payload = {
            "version": 1,
            "responses": [{
                "content_key": "ee-tache3:janvier:combinaison-1",
                "heading": "Un titre",
                "synthese": " ".join(["synthèse"] * 60),
                "point_de_vue": " ".join(["opinion"] * 120),
                "origin": "author",
            }],
        }
        with patch.object(Path, "read_text", return_value=json.dumps(payload)):
            # Keep the bundled membership contracts independent of the mocked file.
            with (
                patch.object(content, "load_ee_subject_keys", return_value=(
                    "ee-tache3:janvier:combinaison-1",
                )),
                patch.object(content, "ee_canonical_by_content_key", return_value={}),
                self.assertRaisesMessage(ValueError, "including title) has 182 words"),
            ):
                content.load_ee_tache_three_author_responses(Path("author-responses.json"))

    def test_merged_parser_validates_the_effective_answer_with_its_title(self):
        months = content.load_ee_tache_three_months()
        response = months[0].combinaisons[3]
        body_count = content._ee_word_count(
            response.synthese + " " + response.point_de_vue
        )
        invalid = replace(
            response,
            heading=" ".join(["titre"] * (181 - body_count)),
        )
        months = (replace(months[0], combinaisons=(invalid,)),)
        with self.assertRaisesMessage(ValueError, "including title) has 181 words"):
            content.parse_ee_tache_three_responses(months)


class EeTacheThreeTitlePageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        command = Command()
        cls.months = content.load_ee_tache_three_months()
        tasks = command._import_sections(content.load_sections())
        cls.themes = command._import_themes(content.ee_tache_three_themes(cls.months), tasks)
        cls.families = command._import_families(content.ee_tache_three_families(cls.months))
        cls.responses = content.parse_ee_tache_three_responses(cls.months)
        rows = command._import_responses(cls.responses, cls.themes, cls.families)
        command._import_prompts(cls.responses, rows, cls.themes, cls.families)
        cls.task = tasks["ee/tache-3"]
        cls.user = factories.make_user()

    def setUp(self):
        self.command = Command()
        self.client.force_login(self.user)
        self.prompt = Prompt.objects.get(content_key="ee-tache3:janvier:combinaison-1")

    def copied_answer(self, page):
        payload = re.search(
            r'<script id="ee-tache-three-response-content" type="application/json">(.*?)</script>',
            page.content.decode(), re.DOTALL,
        )
        self.assertIsNotNone(payload)
        return json.loads(payload.group(1))

    def annotation_html(self, page):
        text = page.content.decode()
        start = text.index(
            f'<div class="answer-columns" data-annotation-root '
            f'data-annotation-source-key="response:{self.prompt.response.content_key}">'
        )
        end = text.index('<aside class="detail-side"', start)
        return text[start:end]

    def test_title_is_in_the_answer_and_copy_including_for_an_equivalent_subject(self):
        for key in (
            self.prompt.content_key,
            self.prompt.response.prompts.filter(is_canonical=False).first().content_key,
            "ee-tache3:janvier:combinaison-4",
        ):
            with self.subTest(key=key):
                prompt = Prompt.objects.get(content_key=key)
                page = self.client.get(prompt_detail_url(prompt))
                self.assertEqual(page.status_code, 200)
                row = prompt.response
                answer = "\n\n".join((row.reformulation, row.position, row.position_claire))
                self.assertEqual(self.copied_answer(page), answer)
                self.assertContains(
                    page, f'<h2 class="spine-text">{row.reformulation}</h2>', html=True,
                )
                self.assertContains(page, 'aria-label="Réponse complète"', count=1)
                self.assertNotContains(page, '<p class="reform">')
                self.assertContains(
                    page, f"Total : {content._ee_word_count(answer)} mots, titre compris",
                )
                self.assertNotIn("Document 1", answer)
                self.assertNotIn("Partie 1", answer)
                self.assertNotIn("Total :", answer)

    def test_changing_the_title_does_not_shift_the_existing_annotation_root(self):
        before = self.client.get(prompt_detail_url(self.prompt))
        Response.objects.filter(pk=self.prompt.response_id).update(
            reformulation="Un autre titre pour la réponse",
        )
        after = self.client.get(prompt_detail_url(self.prompt))
        self.assertEqual(self.annotation_html(before), self.annotation_html(after))
        self.assertNotIn(self.prompt.response.reformulation, self.annotation_html(before))
        self.assertNotIn("Total :", self.annotation_html(before))

    def test_personal_title_and_titleless_correspondence_are_not_replaced(self):
        personal = PersonalResponse.objects.create(
            user=self.user, response=self.prompt.response,
            reformulation="Mon titre <personnel>",
            position="Madame, Monsieur,\n\nMerci pour votre message.",
            position_claire="Voici mon avis.\n\nCordialement,\nCamille",
        )
        for heading in ("Mon titre <personnel>", ""):
            with self.subTest(heading=heading):
                personal.reformulation = heading
                personal.save(update_fields=["reformulation"])
                before = PersonalResponse.objects.values().get(pk=personal.pk)
                page = self.client.get(prompt_detail_url(self.prompt))
                expected = "\n\n".join(part for part in (
                    heading, personal.position, personal.position_claire,
                ) if part)
                self.assertEqual(self.copied_answer(page), expected)
                self.assertContains(page, f"Total : {content._ee_word_count(expected)} mots")
                self.assertNotContains(page, self.prompt.response.reformulation)
                if heading:
                    self.assertContains(page, "Mon titre &lt;personnel&gt;")
                else:
                    self.assertNotContains(page, "titre compris")
                self.assertEqual(PersonalResponse.objects.values().get(pk=personal.pk), before)

    def test_reimport_preserves_identity_private_state_and_historical_snapshots(self):
        response = self.prompt.response
        response.reformulation = "Ancien titre conservé dans l’historique"
        response.body = "Ancien contenu archivé"
        response.body_hash = "old-content-hash"
        response.save(update_fields=["reformulation", "body", "body_hash"])
        now = timezone.now()
        personal = PersonalResponse.objects.create(
            user=self.user, response=response, reformulation="Mon propre titre",
            position="Ma synthèse personnelle.", position_claire="Mon avis personnel.",
        )
        card = Card.objects.create(
            user=self.user, response=response, card_type=CardType.SPINE,
            state=CardState.REVIEW, reps=9, lapses=2, interval_days=21, due=now,
            started_at=now, response_practice_started_at=now, subject_completed_at=now,
        )
        for kind in (AnnotationKind.NOTE, AnnotationKind.HIGHLIGHT):
            Annotation.objects.create(
                user=self.user, task=self.task, kind=kind,
                source_key=f"response:{response.content_key}",
                source_path=prompt_detail_url(self.prompt),
                quote="Les deux documents", body="Ma note à conserver",
                start_offset=12, end_offset=30, completed_at=now,
            )
        log = ReviewLog.objects.create(
            user=self.user, card=card, rating=3, state_before="learning", state_after="review",
            card_before={"title": response.reformulation, "body": response.body},
        )
        ReviewSession.objects.create(
            user=self.user, current_card=card, previous_card=card, previous_review=log,
            scope={"part": "ee", "task": "tache-3"},
        )
        snapshot(personal, "personal")
        snapshot(card, "card")
        models = (PersonalResponse, Card, Annotation, ReviewLog, ReviewSession, OralStateSnapshot)
        saved = {model: list(model.objects.order_by("pk").values()) for model in models}
        prompt_ids = dict(Prompt.objects.values_list("content_key", "pk"))
        response_ids = dict(Response.objects.values_list("content_key", "pk"))
        for _ in range(2):
            rows = self.command._import_responses(self.responses, self.themes, self.families)
            self.command._import_prompts(self.responses, rows, self.themes, self.families)
            self.command._reconcile_personal_responses(rows)
            self.command._reconcile_response_annotations(rows)
            self.command._reconcile_response_cards(rows)
            self.assertEqual(dict(Prompt.objects.values_list("content_key", "pk")), prompt_ids)
            self.assertEqual(dict(Response.objects.values_list("content_key", "pk")), response_ids)
            for model in models:
                self.assertEqual(list(model.objects.order_by("pk").values()), saved[model])
            response.refresh_from_db()
            self.assertEqual(response.reformulation, "Distributeurs scolaires : la santé d’abord")
            self.assertIn(response.reformulation, response.body)
