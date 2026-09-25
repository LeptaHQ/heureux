"""Removed EE3 vocabulary URLs stay absent without mutating stored data."""

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from study.models import (
    Annotation, Card, CardState, MemoryQuestionProgress, Phrase, PhraseTier,
    Prompt, ReviewLog, ReviewSession, ThemeVocabularyProgress,
)
from study.queue import scoped_cards
from . import factories


class VocabularyEntryTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = factories.make_user("vocabulary-entries")
        cls.other_user = factories.make_user("other-vocabulary-reader")
        cls.task = factories.make_task(factories.make_part("ee"), "tache-3")
        cls.theme = factories.make_theme("ee-tache-3-education", task=cls.task)
        cls.response = factories.make_response(theme=cls.theme)
        cls.prompt = cls.response.prompts.get()
        cls.alias = Prompt.objects.create(
            content_key="test:vocabulary-alias", theme=cls.theme,
            family=cls.prompt.family, response=cls.response, number=999,
            text="Une autre publication du même sujet.",
        )
        cls.phrases = []
        for index in range(55):
            phrase = factories.make_phrase(tier=PhraseTier.SUBJECT, lot_order=index)
            phrase.source_prompts.add(cls.prompt, cls.alias)
            factories.make_phrase_card(user=cls.user, phrase=phrase)
            cls.phrases.append(phrase)
        cls.last = cls.phrases[-1]
        cls.url = reverse("study:task_phrases", args=["ee", "tache-3"])
        cls.theme_url = reverse(
            "study:task_vocabulary_theme", args=["ee", "tache-3", cls.theme.slug],
        )
        cls.replacement = reverse("study:ee_formulations")

    def setUp(self):
        self.client.force_login(self.user)

    def test_removed_directory_category_theme_and_lot_links_return_404(self):
        category_url = reverse("study:task_vocabulary_category", args=[
            "ee", "tache-3", self.last.category.slug,
        ])
        for url in (self.url, category_url):
            self.assertEqual(self.client.get(url).status_code, 404)
        for query in ({}, {"batch": "1"}, {"batch": "6"}, {"batch": ["1", "2"]}):
            self.assertEqual(
                self.client.get(self.theme_url, query).status_code,
                404,
            )

    def test_legacy_progress_posts_do_not_repurpose_old_flags(self):
        ThemeVocabularyProgress.objects.create(user=self.user, phrase=self.last)
        ThemeVocabularyProgress.objects.create(user=self.other_user, phrase=self.last)
        original = list(ThemeVocabularyProgress.objects.order_by("pk").values())
        url = reverse("study:theme_vocabulary_progress", args=[
            "ee", "tache-3", self.theme.slug, self.last.pk,
        ])
        for state in ("0", "1", "invalid"):
            self.assertEqual(
                self.client.post(
                    url, {"completed": state, "batch": "6"}
                ).status_code,
                404,
            )
        self.assertEqual(original, list(ThemeVocabularyProgress.objects.order_by("pk").values()))
        self.assertFalse(MemoryQuestionProgress.objects.filter(user=self.user).exists())

    def test_retirement_does_not_change_schedules_notes_ids_or_other_users(self):
        Card.objects.filter(user=self.user, phrase__in=self.phrases[:10]).update(
            state=CardState.REVIEW, due=timezone.now(), interval_days=31,
            needs_revisit=True, started_at=timezone.now(),
        )
        Card.objects.filter(user=self.user, phrase__in=self.phrases[10:20]).update(
            suspended=True,
        )
        factories.make_phrase_card(user=self.other_user, phrase=self.last, state=CardState.REVIEW)
        Annotation.objects.create(
            user=self.user, task=self.task, kind="highlight",
            quote=self.last.expression, source_key=f"phrase:{self.last.phrase_id}:catalog",
            start_offset=0, end_offset=len(self.last.expression), source_path=self.url,
        )
        ThemeVocabularyProgress.objects.create(user=self.other_user, phrase=self.last)
        models = (Card, Annotation, Phrase, ThemeVocabularyProgress, ReviewLog, ReviewSession)
        before = {model: list(model.objects.order_by("pk").values()) for model in models}
        self.client.get(self.url)
        self.client.get(self.theme_url, {"batch": 1})
        self.client.get(self.theme_url, {"batch": 6})
        formulations = self.client.get(self.replacement)
        self.assertEqual(formulations.context["progress"].completed, 0)
        self.assertFalse(scoped_cards({
            "part": "ee", "task": "tache-3", "kind": "vocab",
        }, user=self.user).exists())
        self.assertEqual(before, {model: list(model.objects.order_by("pk").values()) for model in models})

    def test_inactive_source_also_stays_out_of_new_learning_queues(self):
        self.prompt.is_active = False
        self.prompt.save(update_fields=["is_active"])
        self.alias.is_active = False
        self.alias.save(update_fields=["is_active"])
        self.assertFalse(scoped_cards({"kind": "vocab"}, user=self.user).exists())
        self.assertEqual(Phrase.objects.count(), 55)

    def test_shared_active_ownership_preserves_unrelated_task_vocabulary(self):
        oral_task = factories.make_task(factories.make_part("eo"), "tache-3")
        theme = factories.make_theme("oral-only", task=oral_task)
        response = factories.make_response(theme=theme)
        self.last.source_prompts.add(response.prompts.get())
        self.assertEqual(list(scoped_cards({
            "part": "eo", "task": "tache-3", "kind": "vocab",
        }, user=self.user).values_list("phrase_id", flat=True)), [self.last.pk])
        self.assertFalse(scoped_cards({
            "part": "ee", "task": "tache-3", "kind": "vocab",
        }, user=self.user).exists())
