"""Retirement work scales with candidates, not the whole phrase catalogue."""

from dataclasses import asdict
from datetime import timedelta
from io import StringIO
from unittest import skipUnless
from unittest.mock import patch

from django.core.management import call_command
from django.db import connection
from django.db.models import Exists, OuterRef, Q
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from study.account_services import provision_user_study_data
from study.models import (
    Card, CardQuerySet, ComprehensionQuestion, PersonalResponse, Phrase, Prompt,
)
from study.oral_history import preferred_personal
from study.retirement import active_phrases, retired_task_filter, retired_vocabulary
from study.routing import prompt_detail_url

from . import factories


def legacy_retired_vocabulary():
    sources = Prompt.objects.filter(phrases=OuterRef("pk"))
    prompts = sources.filter(
        is_active=True, theme__is_active=True,
        theme__task__is_active=True, theme__task__part__is_active=True,
    )
    retired = retired_task_filter("theme__task__")
    direct_retired = retired_task_filter("vocabulary_theme__task__")
    questions = ComprehensionQuestion.objects.filter(
        vocabulary=OuterRef("pk"), test__is_active=True,
    )
    return Phrase.objects.alias(
        _retired=Exists(sources.filter(retired)),
        _other=Exists(prompts.exclude(retired)),
        _comprehension=Exists(questions),
    ).filter(
        Q(_retired=True) | direct_retired,
    ).exclude(
        Q(_other=True) | Q(_comprehension=True)
        | (
            Q(vocabulary_theme__is_active=True, vocabulary_theme__task__is_active=True)
            & ~direct_retired
        ),
    ).order_by().values("pk")


def legacy_current_content(queryset):
    return queryset.filter(
        Q(response__is_active=True) | Q(phrase__is_active=True),
    ).exclude(phrase_id__in=legacy_retired_vocabulary())


class RetirementCandidateTests(TestCase):
    def setUp(self):
        self.user = factories.make_user("retirement-performance")
        self.other = factories.make_user("other-retirement-performance")
        part = factories.make_part("eo")
        retired = factories.make_task(part, "tache-3")
        current = factories.make_task(part, "tache-2")
        self.retired = factories.make_response(
            theme=factories.make_theme("retired-performance", task=retired),
        )
        self.current = factories.make_response(
            theme=factories.make_theme("current-performance", task=current),
        )
        self.phrase = factories.make_phrase()
        self.phrase.source_prompts.add(self.retired.prompts.get())
        self.card = factories.make_phrase_card(phrase=self.phrase, user=self.user)
        factories.make_phrase_card(phrase=self.phrase, user=self.other)
        factories.make_spine_card(theme=self.retired.theme, user=self.user)
        factories.make_phrase_card(
            phrase=factories.make_phrase(is_active=False), user=self.user,
        )
        factories.make_phrase_card(user=None)
        factories.make_phrase_card(user=self.user, suspended=True)

    def assert_legacy_equality(self):
        self.assertSetEqual(
            set(retired_vocabulary().values_list("pk", flat=True)),
            set(legacy_retired_vocabulary().values_list("pk", flat=True)),
        )
        for user in (None, self.user, self.other):
            with self.subTest(user=user):
                cards = Card.objects.filter(user=user)
                self.assertEqual(
                    list(cards.current_content().values_list("pk", flat=True)),
                    list(legacy_current_content(cards).values_list("pk", flat=True)),
                )
                self.assertEqual(
                    list(cards.active().values_list("pk", flat=True)),
                    list(legacy_current_content(cards).filter(
                        suspended=False,
                    ).values_list("pk", flat=True)),
                )
        phrases = Phrase.objects.order_by("-pk")
        self.assertEqual(
            list(active_phrases(phrases).values_list("pk", flat=True)),
            list(phrases.exclude(
                pk__in=legacy_retired_vocabulary(),
            ).values_list("pk", flat=True)),
        )

    def test_retirement_matches_legacy_and_is_fresh_after_ownership_changes(self):
        self.assert_legacy_equality()
        candidates = Card.objects.filter(user=self.user, pk=self.card.pk)
        self.assertFalse(candidates.current_content().exists())
        self.phrase.source_prompts.add(self.current.prompts.get())
        self.assertTrue(candidates.current_content().exists())
        self.assert_legacy_equality()
        self.current.prompts.update(is_active=False)
        self.assertFalse(candidates.current_content().exists())
        self.assert_legacy_equality()

    def test_membership_sets_preserve_null_and_shared_source_semantics(self):
        factories.make_phrase(vocabulary_theme=self.retired.theme)
        direct = factories.make_phrase(vocabulary_theme=self.current.theme)
        direct.source_prompts.add(self.retired.prompts.get())
        factories.make_phrase()
        comprehension = factories.make_comprehension_test(question_count=2)
        comprehension.questions.first().vocabulary.add(self.phrase)
        self.assert_legacy_equality()
        self.assertTrue(active_phrases().filter(pk=self.phrase.pk).exists())
        comprehension.is_active = False
        comprehension.save(update_fields=["is_active"])
        self.assert_legacy_equality()
        self.assertFalse(active_phrases().filter(pk=self.phrase.pk).exists())
        self.phrase.source_prompts.add(self.current.prompts.get())
        self.assert_legacy_equality()
        self.assertTrue(active_phrases().filter(pk=self.phrase.pk).exists())
        self.current.theme.is_active = False
        self.current.theme.save(update_fields=["is_active"])
        self.assert_legacy_equality()
        self.assertFalse(active_phrases().filter(pk=self.phrase.pk).exists())

    def _steps(self, queryset):
        steps = 0

        def count():
            nonlocal steps
            steps += 1
            return 0

        connection.ensure_connection()
        connection.connection.set_progress_handler(count, 1)
        try:
            with self.assertNumQueries(1):
                list(queryset.values_list("pk", flat=True))
        finally:
            connection.connection.set_progress_handler(None, 0)
        return steps

    @skipUnless(connection.vendor == "sqlite", "SQLite VM scaling regression")
    def test_unrelated_catalogue_growth_does_not_add_retirement_scan_work(self):
        def candidates():
            return (
                Card.objects.filter(pk=self.card.pk).current_content(),
                active_phrases(Phrase.objects.filter(pk=self.phrase.pk)),
            )

        before = [self._steps(query) for query in candidates()]
        Phrase.objects.bulk_create([
            Phrase(
                phrase_id=f"unrelated-performance-{index}",
                category=self.phrase.category,
                expression="Une expression sans rapport.",
            )
            for index in range(1000)
        ])
        after = [self._steps(query) for query in candidates()]
        for old, new in zip(before, after):
            self.assertLessEqual(new, old + 50)


class OralRequestPerformanceTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("import_content", stdout=StringIO())
        cls.user = factories.make_user("oral-performance")
        provision_user_study_data(cls.user)
        cls.other = factories.make_user("other-oral-performance")
        cls.prompts = [
            Prompt.objects.select_related("response", "theme__task__part").filter(
                theme__task__part__slug="eo", theme__task__slug=slug,
                is_active=True, response__is_active=True,
            ).first()
            for slug in ("tache-2", "tache-3")
        ]

    def setUp(self):
        self.client.force_login(self.user)

    def test_full_corpus_requests_keep_their_content_and_query_budgets(self):
        for prompt in self.prompts:
            url = prompt_detail_url(prompt)
            self.client.get(url)
            with patch.object(CardQuerySet, "current_content", legacy_current_content):
                previous = self.client.get(url)
            with CaptureQueriesContext(connection) as queries:
                current = self.client.get(url)
            self.assertEqual(current.status_code, 200)
            for key in ("response_content", "subject_progress"):
                self.assertEqual(current.context[key], previous.context[key])
            self.assertEqual(
                current.context["oral_annotation_key"],
                previous.context["oral_annotation_key"],
            )
            self.assertLessEqual(len(queries), 15)
            personal_queries = [
                query for query in queries
                if query["sql"].startswith('SELECT "study_personalresponse"')
            ]
            self.assertEqual(len(personal_queries), 1)
            self.assertEqual(current["Cache-Control"], "private, no-store")

    def test_eo2_detail_resolves_task_and_response_once(self):
        with CaptureQueriesContext(connection) as queries:
            page = self.client.get(prompt_detail_url(self.prompts[0]))
        self.assertEqual(page.status_code, 200)
        statements = [query["sql"] for query in queries]
        self.assertEqual(sum(
            sql.startswith('SELECT "study_task".') for sql in statements
        ), 1)
        self.assertFalse(any(
            sql.startswith('SELECT "study_response".') for sql in statements
        ))
        self.assertLessEqual(len(queries), 13)

    def test_eo2_detail_still_rejects_inactive_content_and_unavailable_tasks(self):
        prompt = self.prompts[0]
        for model in (prompt, prompt.response, prompt.theme.task):
            field = "available" if model is prompt.theme.task else "is_active"
            original = getattr(model, field)
            setattr(model, field, False)
            model.save(update_fields=[field])
            self.assertEqual(
                self.client.get(prompt_detail_url(prompt)).status_code, 404,
            )
            setattr(model, field, original)
            model.save(update_fields=[field])

    def test_personal_response_changes_resets_and_user_isolation_are_immediate(self):
        for prompt in self.prompts:
            url = prompt_detail_url(prompt)
            original = self.client.get(url).context["response_content"]
            self.assertFalse(original.is_personal)
            fields = asdict(original)
            fields.pop("is_personal")
            fields["arguments"] = list(fields["arguments"])
            fields["arguments"][0]["idea"] = "Comment choisir mon activité privée et unique ?"
            fields["position_claire"] = "Mon introduction privée et unique."
            personal = PersonalResponse.objects.create(
                user=self.user, response=prompt.response, source_prompt=prompt,
                **fields,
            )
            page = self.client.get(url)
            self.assertContains(page, fields["arguments"][0]["idea"])
            self.assertEqual(
                page.context["response_content"].position_claire,
                personal.position_claire,
            )
            self.assertTrue(page.context["response_content"].is_personal)
            self.client.force_login(self.other)
            page = self.client.get(url)
            self.assertNotContains(page, personal.position_claire)
            self.assertFalse(page.context["response_content"].is_personal)
            self.client.force_login(self.user)
            personal.is_active = False
            personal.save(update_fields=["is_active"])
            page = self.client.get(url)
            self.assertFalse(page.context["response_content"].is_personal)
            self.assertNotContains(page, personal.position_claire)

    def test_own_reset_wins_over_active_history_in_one_query(self):
        owner = self.prompts[-1].response
        historical = factories.make_response(theme=factories.make_theme(
            "historical-performance", task=owner.theme.task,
        ))
        historical.semantic_owner = owner
        historical.save(update_fields=["semantic_owner"])
        personal = PersonalResponse.objects.create(
            user=self.user, response=historical,
        )
        with self.assertNumQueries(1):
            self.assertEqual(preferred_personal(owner, self.user), personal)
        reset = PersonalResponse.objects.create(
            user=self.user, response=owner, is_active=False,
        )
        PersonalResponse.objects.filter(pk=personal.pk).update(
            updated_at=reset.updated_at + timedelta(days=1),
        )
        personal.refresh_from_db(fields=["updated_at"])
        self.assertGreater(personal.updated_at, reset.updated_at)
        with self.assertNumQueries(1):
            self.assertIsNone(preferred_personal(owner, self.user))
        reset.delete()
        with self.assertNumQueries(1):
            self.assertEqual(preferred_personal(owner, self.user), personal)

    def test_tied_active_history_prefers_highest_id_in_one_query(self):
        owner = self.prompts[-1].response
        candidates = []
        for index in range(2):
            historical = factories.make_response(theme=factories.make_theme(
                f"tied-history-performance-{index}", task=owner.theme.task,
            ))
            historical.semantic_owner = owner
            historical.save(update_fields=["semantic_owner"])
            candidates.append(PersonalResponse.objects.create(
                user=self.user, response=historical,
            ))
        PersonalResponse.objects.filter(
            pk__in=[candidate.pk for candidate in candidates],
        ).update(updated_at=candidates[0].updated_at)
        with self.assertNumQueries(1):
            self.assertEqual(
                preferred_personal(owner, self.user),
                max(candidates, key=lambda candidate: candidate.pk),
            )
