"""EO3 vocabulary is unavailable without deleting historical learner data."""

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from study.account_services import provision_user_study_data
from study.models import (
    Annotation, Card, CardState, CardType, Phrase, PhraseTier, Rating,
    ReviewLog, ReviewSession, Settings, ThemeVocabularyProgress,
)
from study.progress import subject_progress_by_response
from study.queue import scoped_cards
from study.retirement import active_phrases, is_retired_vocabulary_scope
from study.routing import prompt_detail_url
from . import factories


class Eo3VocabularyRetirementTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = factories.make_user("eo3-vocabulary-retirement")
        cls.other_user = factories.make_user("other-eo3-vocabulary-reader")
        cls.task = factories.make_task(factories.make_part("eo"), "tache-3")
        cls.theme = factories.make_theme("culture", task=cls.task)
        cls.response = factories.make_response(theme=cls.theme)
        cls.response.position_claire = "Voici une introduction conservée."
        cls.response.save(update_fields=["position_claire"])
        cls.prompt = cls.response.prompts.get()
        cls.spine = Card.objects.create(
            user=cls.user, response=cls.response, card_type=CardType.SPINE,
        )
        cls.phrase = factories.make_phrase(tier=PhraseTier.SUBJECT)
        cls.phrase.source_prompts.add(cls.prompt)
        cls.phrase_card = factories.make_phrase_card(
            user=cls.user, phrase=cls.phrase, state=CardState.REVIEW,
            interval_days=31, started_at=timezone.now(), needs_revisit=True,
        )
        factories.make_phrase_card(user=cls.other_user, phrase=cls.phrase)
        cls.direct = factories.make_phrase(
            tier=PhraseTier.THEME, vocabulary_theme=cls.theme,
        )
        factories.make_phrase_card(user=cls.user, phrase=cls.direct)
        cls.scope = {"part": "eo", "task": "tache-3"}
        cls.vocabulary_url = reverse(
            "study:task_phrases", args=["eo", "tache-3"],
        )
        Settings.load(cls.user)
        ReviewSession.load(cls.user)

    def setUp(self):
        self.client.force_login(self.user)

    def test_removed_directories_categories_lots_and_progress_are_closed(self):
        theme_url = reverse("study:task_vocabulary_theme", args=[
            "eo", "tache-3", self.theme.slug,
        ])
        urls = (
            self.vocabulary_url,
            reverse("study:task_vocabulary_category", args=[
                "eo", "tache-3", self.phrase.category.slug,
            ]),
            theme_url,
            f"{theme_url}?batch=1",
        )
        for url in urls:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 404)
        progress_url = reverse("study:theme_vocabulary_progress", args=[
            "eo", "tache-3", self.theme.slug, self.direct.pk,
        ])
        self.assertEqual(
            self.client.post(progress_url, {"completed": "1"}).status_code, 404,
        )
        self.assertFalse(ThemeVocabularyProgress.objects.exists())

    def test_overview_subject_and_directory_do_not_offer_vocabulary(self):
        urls = (
            reverse("study:task_detail", args=["eo", "tache-3"]),
            reverse("study:task_browse", args=["eo", "tache-3"]),
            reverse("study:response_detail", args=[
                "eo", "tache-3", self.prompt.pk,
            ]),
        )
        for url in urls:
            with self.subTest(url=url):
                page = self.client.get(url)
                self.assertEqual(page.status_code, 200)
                self.assertNotContains(page, self.vocabulary_url)
                self.assertNotContains(page, "Vocabulaire de ce sujet")
                self.assertNotContains(page, 'data-task-choice="vocabulary"')
                self.assertNotContains(page, "response-subject-vocabulary")
                self.assertNotContains(page, "response-related-vocabulary")
        detail = self.client.get(urls[-1])
        self.assertContains(detail, self.response.position_claire)
        self.assertContains(detail, "Progression du sujet")
        self.assertContains(detail, "Pratiquer cette réponse")
        self.assertFalse(detail.context["related_phrases"])
        self.assertFalse(detail.context.get("subject_vocabulary"))
        self.assertContains(
            self.client.get(urls[1]), "subject-collection__table--response-only",
        )

    def test_old_vocabulary_reviews_are_closed_but_response_practice_remains(self):
        url = reverse("study:task_review", args=["eo", "tache-3"])
        for query in (
            {"kind": "vocab"}, {"kind": "phrase"}, {"kind": "theme_vocab"},
            {"content": "vocabulary"},
            {"kind": "theme_vocab", "content": "theme_vocabulary"},
            {"kind": "vocab", "response": self.response.pk, "batch": 1},
        ):
            with self.subTest(query=query):
                self.assertEqual(self.client.get(url, query).status_code, 404)
        for inferred in (
            {"response": self.response.pk},
            {"prompt": self.prompt.pk},
            {"theme": self.theme.slug},
        ):
            self.assertTrue(is_retired_vocabulary_scope({"kind": "vocab", **inferred}))
            self.assertFalse(scoped_cards(
                {"kind": "vocab", **inferred}, user=self.user,
            ).exists())
        self.assertEqual(list(scoped_cards(
            {**self.scope, "kind": "spine"}, user=self.user,
        ).values_list("pk", flat=True)), [self.spine.pk])
        self.assertEqual(self.client.get(url, {
            "kind": "spine", "response": self.response.pk,
            "prompt": self.prompt.pk,
        }).status_code, 200)

    def test_schedules_annotations_logs_and_other_users_are_preserved(self):
        Annotation.objects.create(
            user=self.user, task=self.task, kind="note",
            quote=self.phrase.expression, body="An existing translation.",
            source_path=self.vocabulary_url,
            source_key=f"phrase:{self.phrase.phrase_id}:catalog",
            start_offset=0, end_offset=len(self.phrase.expression),
        )
        ThemeVocabularyProgress.objects.create(
            user=self.other_user, phrase=self.phrase,
        )
        ReviewLog.objects.create(
            user=self.user, card=self.phrase_card, rating=Rating.GOOD,
            state_before=CardState.LEARNING, state_after=CardState.REVIEW,
        )
        models = (
            Card, Annotation, Phrase, ThemeVocabularyProgress, ReviewLog, ReviewSession,
        )
        before = {m: list(m.objects.order_by("pk").values()) for m in models}
        self.client.get(self.vocabulary_url)
        self.client.get(reverse("study:response_detail", args=[
            "eo", "tache-3", self.prompt.pk,
        ]))
        self.assertFalse(scoped_cards(
            {**self.scope, "kind": "vocab"}, user=self.user,
        ).exists())
        self.assertFalse(scoped_cards({"kind": "vocab"}, user=self.user).exists())
        self.assertEqual(before, {
            m: list(m.objects.order_by("pk").values()) for m in models
        })

    def test_shared_phrases_stay_available_only_in_other_active_tasks(self):
        task = factories.make_task(factories.make_part("ee"), "tache-2")
        theme = factories.make_theme("active-writing-vocabulary", task=task)
        response = factories.make_response(theme=theme)
        self.phrase.source_prompts.add(response.prompts.get())
        self.assertIn(self.phrase, active_phrases())
        self.assertNotIn(self.direct, active_phrases())
        self.assertEqual(list(scoped_cards({
            "part": "ee", "task": "tache-2", "kind": "vocab",
        }, user=self.user).values_list("phrase_id", flat=True)), [self.phrase.pk])
        self.assertFalse(scoped_cards({
            **self.scope, "kind": "vocab",
        }, user=self.user).exists())
        self.assertFalse(scoped_cards({
            "part": "eo", "kind": "vocab",
        }, user=self.user).exists())
        for summary_only in (True, False):
            progress = subject_progress_by_response(
                self.user, [self.response.pk, response.pk], summary_only=summary_only,
            )
            self.assertEqual(progress[self.response.pk].status, "new")
            self.assertFalse(progress[self.response.pk].vocabulary_activity_started)
            self.assertTrue(progress[response.pk].vocabulary_activity_started)
        search = self.client.get(reverse(
            "study:task_search", args=["eo", "tache-3"],
        ), {"q": self.phrase.expression})
        self.assertEqual(search.context["phrase_result_count"], 0)

    def test_new_accounts_do_not_receive_retired_vocabulary_cards(self):
        user = factories.make_user("new-reader-without-eo3-vocabulary")
        provision_user_study_data(user, force=True)
        self.assertTrue(Card.objects.filter(
            user=user, response=self.response, card_type=CardType.SPINE,
        ).exists())
        self.assertFalse(Card.objects.filter(
            user=user, phrase__in=[self.phrase, self.direct],
        ).exists())

    def test_shared_revisit_links_do_not_point_to_removed_vocabulary(self):
        task = factories.make_task(factories.make_part("ee"), "tache-2")
        theme = factories.make_theme("shared-vocabulary-links", task=task)
        response = factories.make_response(theme=theme)
        prompt = response.prompts.get()
        self.phrase.source_prompts.add(prompt)
        self.direct.source_prompts.add(prompt)
        Card.objects.filter(user=self.user, phrase=self.direct).update(needs_revisit=True)
        page = self.client.get(reverse("study:revisit_list"))
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, prompt_detail_url(prompt))
        self.assertNotContains(page, self.vocabulary_url)
        for item in page.context["items"]:
            if item["card"].phrase_id:
                self.assertTrue(item["url"].startswith(prompt_detail_url(prompt)))
