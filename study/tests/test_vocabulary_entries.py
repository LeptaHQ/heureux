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
    ThemeVocabularyProgress,
)
from . import factories


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
        self.assertTrue(all("title" not in batch for batch in expected))
        self.assertIn("theme=" + self.theme.slug, detail.context["mixed_review_url"])
        directory = self.client.get(self.url)
        entry = next(item for item in directory.context["themes"] if item["theme"] == self.theme)
        self.assertEqual(entry["summary"], detail.context["summary"])
        self.assertRedirects(self.client.get(self.url, {"theme": self.theme.slug}), self.theme_url)

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
            for model in (Card, Annotation, Phrase, ThemeVocabularyProgress)
        }
        self.client.get(self.url)
        detail = self.client.get(self.theme_url)
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
