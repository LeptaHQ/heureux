from datetime import timedelta

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from study import content_loader as content
from study.models import (
    Annotation,
    AnnotationKind,
    Card,
    CardState,
    Phrase,
    PhraseCategory,
    PhraseTier,
    Prompt,
    ReviewLog,
    ReviewSession,
    ThemeVocabularyProgress,
)
from . import factories
from .vocabulary_assertions import assert_vocabulary_lot_tables


class VocabularyEntryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = factories.make_user("vocabulary-entries")
        cls.other_user = factories.make_user("other-vocabulary-reader")
        cls.task = factories.make_task(factories.make_part("ee"), "tache-3")
        cls.theme = factories.make_theme("education", task=cls.task)
        cls.other_theme = factories.make_theme("environment", task=cls.task)
        cls.response = factories.make_response(theme=cls.theme)
        cls.prompt = cls.response.prompts.get()
        cls.alias = Prompt.objects.create(
            content_key="test:vocabulary-alias", theme=cls.theme,
            family=cls.prompt.family, response=cls.response, number=999,
            text="Une autre publication du même sujet.",
        )
        category = PhraseCategory.objects.create(
            slug="ee3-words", content_key="test:ee3-words",
            name=content.EE_TACHE_THREE_VOCABULARY_CATEGORIES["mot-cle"],
        )
        cls.phrases = []
        for index in range(55):
            phrase = factories.make_phrase(
                category=category, tier=PhraseTier.SUBJECT, lot_order=index,
            )
            phrase.source_prompts.add(cls.prompt, cls.alias)
            factories.make_phrase_card(user=cls.user, phrase=phrase)
            cls.phrases.append(phrase)
        cls.last = cls.phrases[-1]
        Phrase.objects.filter(pk=cls.last.pk).update(
            expression="accès équitable", english_cue="fair access",
            example="Un exemple réservé à la recherche.", note="Une précision pédagogique.",
        )
        cls.last.refresh_from_db()
        other_response = factories.make_response(theme=cls.other_theme)
        cls.other_phrase = factories.make_phrase(
            category=category, tier=PhraseTier.SUBJECT, lot_order=100,
        )
        cls.other_phrase.source_prompts.add(other_response.prompts.get())
        cls.url = reverse("study:task_phrases", args=["ee", "tache-3"])
        cls.theme_url = reverse(
            "study:task_vocabulary_theme", args=["ee", "tache-3", cls.theme.slug],
        )

    def setUp(self):
        self.client.force_login(self.user)

    def test_shared_directory_and_details_list_vocabulary_not_subjects(self):
        directory = self.client.get(self.url)
        self.assertTemplateUsed(directory, "study/theme_vocabulary_directory.html")
        self.assertEqual(directory.context["phrase_count"], 56)
        self.assertEqual(directory.context["theme_count"], 2)
        self.assertContains(directory, self.theme_url)
        self.assertNotContains(directory, "data-subject-vocabulary-row")
        detail = self.client.get(self.theme_url)
        self.assertTemplateUsed(detail, "study/theme_vocabulary_detail.html")
        self.assertContains(detail, "data-theme-vocabulary-progress-form", count=55)
        ids = [
            phrase.pk
            for section in detail.context["phrase_sections"]
            for phrase in section["phrases"]
        ]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), {phrase.pk for phrase in self.phrases})
        self.assertContains(detail, self.last.expression)
        self.assertContains(detail, self.last.english_cue)
        self.assertNotContains(detail, "#subject-vocabulary")

    def test_guided_lots_keep_their_original_scope_and_order(self):
        from study.views.helpers import _review_batches

        detail = self.client.get(self.theme_url)
        scope = {"part": "ee", "task": "tache-3", "kind": "vocab", "theme": self.theme.slug}
        expected = _review_batches(scope, self.user)
        self.assertEqual(detail.context["review_batches"], expected)
        self.assertEqual(len(expected), 6)
        self.assertTemplateUsed(detail, "study/partials/review_batches.html")
        self.assertContains(detail, "batch-card--compact", count=6)
        self.assertContains(detail, 'class="batch-card__count" aria-hidden="true">0/5')
        self.assertNotContains(detail, 'class="review-batches"')
        self.assertTrue(all("title" not in batch for batch in expected))
        self.assertIn("theme=" + self.theme.slug, detail.context["mixed_review_url"])
        directory = self.client.get(self.url)
        entry = next(item for item in directory.context["themes"] if item["theme"] == self.theme)
        self.assertEqual(entry["summary"], detail.context["summary"])
        self.assertRedirects(self.client.get(self.url, {"theme": self.theme.slug}), self.theme_url)

    def test_completed_and_suspended_lots_remain_browsable(self):
        from django.template.loader import render_to_string

        Card.objects.filter(
            user=self.user, phrase__in=self.phrases[:10],
        ).update(state=CardState.REVIEW, due=timezone.now() + timedelta(days=30))
        Card.objects.filter(
            user=self.user, phrase__in=self.phrases[10:20],
        ).update(suspended=True)
        Card.objects.filter(
            user=self.user, phrase=self.phrases[20],
        ).update(state=CardState.LEARNING)
        detail = self.client.get(self.theme_url)
        batches = detail.context["vocabulary_lots"]
        self.assertEqual(
            [(batch["completed_count"], batch["active_count"]) for batch in batches],
            [(10, 10), (0, 0), (1, 10), (0, 10), (0, 10), (0, 5)],
        )
        for batch in batches:
            markup = render_to_string(
                "study/partials/batch_card.html", {"batch": batch, "compact": True},
            )
            self.assertIn(
                f'{batch["completed_count"]}/{batch["active_count"]}', markup,
            )
            self.assertIn(batch["status_label"], markup)
            self.assertIn(f'href="{batch["table_url"]}"', markup)
            self.assertNotIn('aria-disabled="true"', markup)
            self.assertNotIn("batch-card__status", markup)
            self.assertNotIn("<strong>", markup)
        for number in (1, 2):
            page = self.client.get(self.theme_url, {"batch": number})
            self.assertEqual(page.context["catalog_phrase_count"], 10)
            self.assertFalse(page.context["selected_batch"]["can_review"])
            self.assertContains(page, 'disabled title=')

    def test_lot_tables_follow_queue_order_not_catalogue_order(self):
        alternate = PhraseCategory.objects.create(
            slug="ee3-alternate", content_key="test:ee3-alternate",
            name=content.EE_TACHE_THREE_VOCABULARY_CATEGORIES["expression"],
        )
        Phrase.objects.filter(pk=self.phrases[0].pk).update(order=99999)
        Phrase.objects.filter(pk__in=[phrase.pk for phrase in self.phrases[1:4]]).update(
            category=alternate,
        )
        Card.objects.filter(user=self.user, phrase=self.phrases[5]).update(suspended=True)
        scope = {"part": "ee", "task": "tache-3", "kind": "vocab", "theme": self.theme.slug}
        assert_vocabulary_lot_tables(self, self.theme_url, scope, "phrase_sections")
        first = self.client.get(self.theme_url, {"batch": 1})
        self.assertEqual(
            [phrase.pk for phrase in first.context["phrase_sections"][0]["phrases"]],
            [phrase.pk for phrase in self.phrases[:10]],
        )
        last = self.client.get(self.theme_url, {"batch": 6})
        self.assertEqual(last.context["catalog_phrase_count"], 5)
        self.assertEqual(len(last.context["phrase_sections"]), 1)
        self.assertNotContains(last, self.phrases[0].english_cue)

    def test_lot_counts_and_progress_redirect_stay_scoped(self):
        ThemeVocabularyProgress.objects.create(user=self.user, phrase=self.phrases[0])
        ThemeVocabularyProgress.objects.create(user=self.user, phrase=self.last)
        page = self.client.get(self.theme_url, {"batch": 6})
        self.assertEqual(page.context["learned_summary"].completed, 2)
        self.assertEqual(page.context["learned_summary"].total, 55)
        self.assertEqual(page.context["catalog_learned_count"], 1)
        self.assertEqual(page.context["catalog_unlearned_count"], 4)
        self.assertContains(page, 'name="batch" value="6"', count=5)
        phrase = page.context["phrase_sections"][0]["phrases"][0]
        result = self.client.post(phrase.progress_url, {"completed": "1", "batch": "6"})
        self.assertRedirects(
            result, self.theme_url + "?batch=6#phrase-" + phrase.phrase_id,
        )
        result = self.client.post(
            phrase.progress_url, {"completed": "0", "batch": "6"},
            HTTP_X_REQUESTED_WITH="fetch",
        )
        self.assertEqual(result.json()["total"], 55)
        self.assertEqual(result.json()["learned"], 2)
        all_fiches = self.client.get(page.context["all_lots_url"])
        self.assertEqual(all_fiches.context["catalog_phrase_count"], 55)
        self.assertIsNone(all_fiches.context["selected_batch"])

    def test_invalid_lot_selection_is_rejected_without_mutation(self):
        url = reverse(
            "study:theme_vocabulary_progress",
            args=["ee", "tache-3", self.theme.slug, self.last.pk],
        )
        for value in ("", "0", "-1", "7", "01", "1.0", "abc", "9" * 5000, ["1", "2"]):
            with self.subTest(value=str(value)[:30]):
                self.assertEqual(self.client.get(self.theme_url, {"batch": value}).status_code, 404)
                self.assertEqual(
                    self.client.post(url, {"completed": "1", "batch": value}).status_code,
                    404,
                )
        self.assertEqual(self.client.post(url, {"completed": "1", "batch": "1"}).status_code, 404)
        self.assertFalse(ThemeVocabularyProgress.objects.filter(user=self.user).exists())

    def test_status_is_private_and_reading_does_not_change_saved_state(self):
        first, second, third = self.phrases[:3]
        Card.objects.filter(user=self.user, phrase=first).update(started_at=timezone.now())
        Card.objects.filter(user=self.user, phrase=second).update(state=CardState.LEARNING)
        Card.objects.filter(user=self.user, phrase=third).update(suspended=True)
        factories.make_phrase_card(user=self.other_user, phrase=self.last, state=CardState.REVIEW)
        Annotation.objects.create(
            user=self.user, task=self.task, kind=AnnotationKind.HIGHLIGHT,
            quote=self.last.expression, source_key=f"phrase:{self.last.phrase_id}:front",
            start_offset=0, end_offset=len(self.last.expression), source_path=self.url,
        )
        ThemeVocabularyProgress.objects.create(user=self.other_user, phrase=self.last)
        before = {
            model: list(model.objects.order_by("pk").values())
            for model in (Card, Annotation, Phrase, ThemeVocabularyProgress, ReviewLog, ReviewSession)
        }
        self.client.get(self.url)
        detail = self.client.get(self.theme_url)
        self.client.get(self.theme_url, {"batch": 1})
        self.client.get(self.theme_url, {"batch": 6})
        self.assertEqual(detail.context["learned_summary"].completed, 0)
        self.assertTrue(all(
            not phrase.is_explicitly_learned
            for section in detail.context["phrase_sections"]
            for phrase in section["phrases"]
        ))
        self.assertEqual(before, {model: list(model.objects.order_by("pk").values()) for model in before})

    def test_shared_learned_controls_do_not_change_srs_or_other_users(self):
        url = reverse(
            "study:theme_vocabulary_progress",
            args=["ee", "tache-3", self.theme.slug, self.last.pk],
        )
        ThemeVocabularyProgress.objects.create(user=self.other_user, phrase=self.last)
        before = list(Card.objects.order_by("pk").values())
        for completed, count in (("1", 1), ("1", 1), ("0", 0)):
            result = self.client.post(url, {"completed": completed}, HTTP_X_REQUESTED_WITH="fetch")
            self.assertEqual(result.status_code, 200)
            self.assertEqual(result.json(), {
                "completed": completed == "1", "phrase_id": self.last.phrase_id,
                "learned": count, "total": 55,
            })
            detail = self.client.get(self.theme_url)
            self.assertEqual(detail.context["learned_summary"].completed, count)
        self.assertEqual(before, list(Card.objects.order_by("pk").values()))
        self.assertTrue(ThemeVocabularyProgress.objects.filter(
            user=self.other_user, phrase=self.last,
        ).exists())
        self.assertEqual(self.client.post(url, {"completed": "invalid"}).status_code, 400)
        wrong_theme = reverse(
            "study:theme_vocabulary_progress",
            args=["ee", "tache-3", self.other_theme.slug, self.last.pk],
        )
        self.assertEqual(self.client.post(wrong_theme, {"completed": "1"}).status_code, 404)
        saved = self.client.post(url, {"completed": "1"})
        self.assertRedirects(saved, self.theme_url + "#phrase-" + self.last.phrase_id)

    def test_retired_and_out_of_scope_content_is_not_listed(self):
        foreign = factories.make_response(theme=factories.make_theme(
            "oral-only", task=factories.make_task(factories.make_part("eo"), "tache-3"),
        ))
        phrase = factories.make_phrase(tier=PhraseTier.SUBJECT)
        phrase.source_prompts.add(foreign.prompts.get())
        Phrase.objects.filter(pk=self.last.pk).update(is_active=False)
        page = self.client.get(self.url)
        self.assertEqual(page.context["phrase_count"], 55)
        self.assertEqual(len(page.context["themes"]), 2)
        self.assertNotContains(self.client.get(self.theme_url), self.last.expression)
        self.response.is_active = False
        self.response.save(update_fields=["is_active"])
        page = self.client.get(self.url)
        self.assertEqual(page.context["phrase_count"], 1)
        self.assertEqual(self.client.get(self.theme_url).context["phrase_count"], 0)

    def test_invalid_themes_are_rejected_and_empty_catalog_is_supported(self):
        self.assertEqual(self.client.get(self.url, {"theme": "missing"}).status_code, 404)
        Phrase.objects.update(is_active=False)
        page = self.client.get(self.url)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context["phrase_count"], 0)
        self.assertEqual(self.client.get(self.theme_url).context["phrase_count"], 0)
