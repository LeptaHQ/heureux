from urllib.parse import parse_qs, urlsplit

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from study.models import Annotation, AnnotationKind, Card, CardState, Phrase, PhraseTier, Prompt
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
        cls.phrases = []
        for index in range(55):
            phrase = factories.make_phrase(tier=PhraseTier.SUBJECT, lot_order=index)
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
        cls.other_phrase = factories.make_phrase(tier=PhraseTier.SUBJECT, lot_order=100)
        cls.other_phrase.source_prompts.add(other_response.prompts.get())
        cls.url = reverse("study:task_phrases", args=["ee", "tache-3"])

    def setUp(self):
        self.client.force_login(self.user)

    def test_pagination_lists_every_identity_once_including_aliases(self):
        first = self.client.get(self.url)
        self.assertEqual(first.context["phrase_count"], 56)
        self.assertEqual(first.context["page_obj"].paginator.count, 56)
        self.assertEqual(len(first.context["entries"]), 50)
        second = self.client.get(first.context["next_page_url"])
        ids = [phrase.pk for page in (first, second) for phrase in page.context["entries"]]
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(set(ids), {phrase.pk for phrase in self.phrases} | {self.other_phrase.pk})
        self.assertNotContains(first, "data-subject-vocabulary-row")
        self.assertNotContains(first, "#subject-vocabulary")

    def test_search_uses_vocabulary_fields_across_all_pages(self):
        for query in ("accès", "fair", "réservé", "pédagogique", "fair équitable"):
            with self.subTest(query=query):
                page = self.client.get(self.url, {"q": query})
                self.assertEqual([phrase.pk for phrase in page.context["entries"]], [self.last.pk])
        empty = self.client.get(self.url, {"q": self.alias.text})
        self.assertEqual(empty.context["page_obj"].paginator.count, 0)
        self.assertContains(empty, "Aucune fiche")

    def test_filters_and_pagination_keep_the_selected_theme(self):
        page = self.client.get(self.url, {"theme": self.theme.slug, "status": "new"})
        self.assertEqual(page.context["phrase_count"], 55)
        self.assertEqual(page.context["page_obj"].paginator.count, 55)
        params = parse_qs(urlsplit(page.context["next_page_url"]).query)
        self.assertEqual(params, {"theme": [self.theme.slug], "status": ["new"], "page": ["2"]})
        second = self.client.get(page.context["next_page_url"])
        self.assertEqual(len(second.context["entries"]), 5)
        legacy = self.client.get(reverse(
            "study:task_vocabulary_theme", args=["ee", "tache-3", self.theme.slug],
        ))
        self.assertTemplateUsed(legacy, "study/vocabulary_entries.html")
        self.assertEqual(legacy.context["phrase_count"], 55)
        self.assertIn("theme=" + self.theme.slug, legacy.context["mixed_review_url"])

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
        before = {model: list(model.objects.order_by("pk").values()) for model in (Card, Annotation, Phrase)}
        for status, expected in (("active", first), ("done", second), ("suspended", third)):
            page = self.client.get(self.url, {"status": status})
            self.assertEqual([phrase.pk for phrase in page.context["entries"]], [expected.pk])
        search = self.client.get(self.url, {"q": "fair", "status": "new"})
        self.assertEqual([phrase.pk for phrase in search.context["entries"]], [self.last.pk])
        self.assertEqual(before, {model: list(model.objects.order_by("pk").values()) for model in before})

    def test_retired_and_out_of_scope_content_is_not_listed(self):
        foreign = factories.make_response(theme=factories.make_theme(
            "oral-only", task=factories.make_task(factories.make_part("eo"), "tache-3"),
        ))
        phrase = factories.make_phrase(tier=PhraseTier.SUBJECT)
        phrase.source_prompts.add(foreign.prompts.get())
        Phrase.objects.filter(pk=self.last.pk).update(is_active=False)
        page = self.client.get(self.url, {"q": "fair"})
        self.assertEqual(page.context["page_obj"].paginator.count, 0)
        self.assertEqual(page.context["phrase_count"], 55)
        self.assertEqual(len(page.context["themes"]), 2)
        self.response.is_active = False
        self.response.save(update_fields=["is_active"])
        page = self.client.get(self.url)
        self.assertEqual([entry.pk for entry in page.context["entries"]], [self.other_phrase.pk])

    def test_invalid_filters_are_rejected_and_empty_catalog_is_supported(self):
        for params in ({"theme": "missing"}, {"status": "missing"}):
            self.assertEqual(self.client.get(self.url, params).status_code, 404)
        Phrase.objects.update(is_active=False)
        page = self.client.get(self.url)
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.context["phrase_count"], 0)
        self.assertContains(page, "Aucune fiche")
