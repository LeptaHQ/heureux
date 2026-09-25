from datetime import datetime, timezone as datetime_timezone

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from study.models import (
    Card,
    MemoryQuestionProgress,
    PersonalResponse,
    PersonalWritingResponse,
    PhraseTier,
    ReviewLog,
    WritingResponseOverride,
    WritingSujetCompletion,
)
from study.views.library import _learning_activity, _stats_scope_cards
from study.writing_responses import model_version_keys

from . import factories


class ExpressionSearchVisibilityTests(TestCase):
    def setUp(self):
        self.user = factories.make_user()
        self.client.force_login(self.user)
        self.task = factories.make_task()
        self.theme = factories.make_theme(task=self.task)
        self.response = factories.make_response(theme=self.theme)
        self.prompt = self.response.canonical_prompt
        self.prompt.text = "Searchable subject"
        self.prompt.save(update_fields=["text"])

    def test_search_excludes_archived_prompt_ancestors_and_counts_only_live_subjects(self):
        for archived in (self.response, self.theme, self.task, self.task.part):
            with self.subTest(model=type(archived).__name__):
                archived.is_active = False
                archived.save(update_fields=["is_active"])
                for scope in ("subjects", ""):
                    page = self.client.get(reverse("study:search"), {
                        "q": "Searchable", "scope": scope,
                    })
                    self.assertEqual(page.status_code, 200)
                    self.assertEqual(page.context["prompt_result_count"], 0)
                    self.assertEqual(page.context["prompt_total"], 0)
                archived.is_active = True
                archived.save(update_fields=["is_active"])

    def test_global_subject_search_excludes_archived_writing_tasks_and_parts(self):
        sujet = factories.make_writing_sujet(prompt="Searchable writing subject")
        for archived in (sujet.task, sujet.task.part):
            with self.subTest(model=type(archived).__name__):
                archived.is_active = False
                archived.save(update_fields=["is_active"])
                page = self.client.get(reverse("study:search"), {
                    "q": "Searchable", "scope": "subjects",
                })
                self.assertEqual(page.status_code, 200)
                self.assertEqual(page.context["writing_sujet_result_count"], 0)
                self.assertEqual(page.context["prompt_total"], 1)
                archived.is_active = True
                archived.save(update_fields=["is_active"])

    def test_active_task_vocabulary_search_includes_direct_theme_sources(self):
        writing_task = factories.make_task(factories.make_part("ee"), "tache-2")
        writing_theme = factories.make_theme("writing-search", task=writing_task)
        phrase = factories.make_phrase(
            tier=PhraseTier.THEME, vocabulary_theme=writing_theme,
        )
        phrase.english_cue = "Searchable vocabulary"
        phrase.save(update_fields=["english_cue"])
        url = reverse("study:task_search", args=["ee", "tache-2"])
        page = self.client.get(url, {"q": "Searchable vocabulary"})
        self.assertEqual(page.context["phrase_results"], [phrase])
        self.assertEqual(page.context["phrase_result_count"], 1)
        self.assertEqual(page.context["phrase_total"], 1)
        oral_page = self.client.get(
            reverse("study:task_search", args=["eo", "tache-3"]),
            {"q": "Searchable vocabulary"},
        )
        self.assertEqual(oral_page.context["phrase_result_count"], 0)
        writing_theme.is_active = False
        writing_theme.save(update_fields=["is_active"])
        archived_page = self.client.get(url, {"q": "Searchable vocabulary"})
        self.assertEqual(archived_page.context["phrase_result_count"], 0)
        self.assertEqual(archived_page.context["phrase_total"], 0)

    def test_task_vocabulary_search_excludes_archived_prompt_sources(self):
        phrase = factories.make_phrase()
        phrase.source_prompts.add(self.prompt)
        self.prompt.is_active = False
        self.prompt.save(update_fields=["is_active"])
        page = self.client.get(
            reverse("study:task_search", args=["eo", "tache-3"]),
            {"q": phrase.english_cue},
        )
        self.assertEqual(page.context["phrase_result_count"], 0)
        self.assertEqual(page.context["phrase_total"], 0)

    def test_oral_directory_counts_exclude_archived_responses(self):
        self.response.is_active = False
        self.response.save(update_fields=["is_active"])
        url = reverse("study:task_browse", args=["eo", "tache-3"])
        for deduplicate in ("0", "1"):
            with self.subTest(deduplicate=deduplicate):
                page = self.client.get(url, {"deduplicate": deduplicate})
                self.assertEqual(page.context["publication_count"], 0)
                self.assertEqual(page.context["prompt_count"], 0)
                self.assertEqual(page.context["display_count"], 0)
        overview = self.client.get(reverse("study:task_detail", args=["eo", "tache-3"]))
        self.assertEqual(overview.context["prompt_count"], 0)

    def test_theme_and_family_directories_exclude_archived_responses(self):
        task = factories.make_task(factories.make_part("ee"), "tache-2")
        theme = factories.make_theme("writing-groups", task=task)
        active = factories.make_response(theme=theme)
        archived = factories.make_response(theme=theme)
        archived.is_active = False
        archived.save(update_fields=["is_active"])
        for name, slug in (
            ("study:theme_detail", theme.slug),
            ("study:task_family_detail", active.family.slug),
        ):
            with self.subTest(route=name):
                page = self.client.get(reverse(name, args=["ee", "tache-2", slug]))
                self.assertEqual(page.status_code, 200)
                self.assertEqual(
                    [row["prompt"].pk for row in page.context["rows"]],
                    [active.canonical_prompt.pk],
                )


class ExpressionEditorContractTests(TestCase):
    def setUp(self):
        self.user = factories.make_user()
        self.client.force_login(self.user)

    def test_oral_editor_rejects_removed_selectors_before_resetting(self):
        for task_slug in ("tache-2", "tache-3"):
            task = factories.make_task(slug=task_slug)
            theme = factories.make_theme(task_slug, task=task)
            response = factories.make_response(theme=theme)
            prompt = response.canonical_prompt
            if task_slug == "tache-2":
                prompt.content_key = "tache2:janvier:batch-01:subject-01"
                prompt.save(update_fields=["content_key"])
            personal = PersonalResponse.objects.create(
                user=self.user, response=response, position="Keep my current response",
            )
            url = reverse("study:edit_response", args=["eo", task_slug, prompt.pk])
            for query in ("model=1", f"personal={personal.pk}"):
                with self.subTest(task=task_slug, query=query):
                    self.assertEqual(self.client.get(f"{url}?{query}").status_code, 404)
                    self.assertEqual(
                        self.client.post(f"{url}?{query}", {"action": "reset"}).status_code,
                        404,
                    )
                    personal.refresh_from_db()
                    self.assertTrue(personal.is_active)
                    self.assertEqual(personal.position, "Keep my current response")

    def test_writing_editor_rejects_unknown_actions_without_overwriting(self):
        sujet = factories.make_writing_sujet()
        personal = PersonalWritingResponse.objects.create(
            user=self.user, sujet=sujet, body="Keep my writing response",
        )
        url = reverse("study:writing_sujet_edit", args=["ee", "tache-1", sujet.pk])
        result = self.client.post(url, {"action": "delete", "body": "Unexpected replacement"})
        self.assertEqual(result.status_code, 400)
        personal.refresh_from_db()
        self.assertEqual(personal.body, "Keep my writing response")

    def test_oral_editor_rejects_unknown_actions(self):
        response = factories.make_response()
        url = reverse(
            "study:edit_response", args=["eo", "tache-3", response.canonical_prompt.pk],
        )
        result = self.client.post(url, {"action": "delete"})
        self.assertEqual(result.status_code, 400)
        self.assertFalse(PersonalResponse.objects.filter(user=self.user).exists())

    def test_writing_reset_cannot_remove_the_only_remaining_response(self):
        for versions in ((), ("Shared answer",)):
            with self.subTest(versions=versions):
                sujet = factories.make_writing_sujet(versions=versions)
                personal = PersonalWritingResponse.objects.create(
                    user=self.user, sujet=sujet, body="My only remaining answer",
                )
                for key in model_version_keys(sujet.model_versions):
                    WritingResponseOverride.objects.create(
                        user=self.user, sujet=sujet, version_key=key, is_deleted=True,
                    )
                url = reverse("study:writing_sujet_edit", args=["ee", "tache-1", sujet.pk])
                result = self.client.post(url, {"action": "reset"})
                self.assertEqual(result.status_code, 400)
                personal.refresh_from_db()
                self.assertEqual(personal.body, "My only remaining answer")


class WritingLearningActivityTests(TestCase):
    def setUp(self):
        self.user = factories.make_user()
        self.other = factories.make_user()
        self.client.force_login(self.user)
        self.part = factories.make_part("ee")
        self.first_task = factories.make_task(self.part, "tache-1")
        self.second_task = factories.make_task(self.part, "tache-2")
        self.oral_task = factories.make_task()
        for task in (self.first_task, self.second_task):
            sujet = factories.make_writing_sujet(task)
            for user in (self.user, self.other):
                PersonalWritingResponse.objects.create(user=user, sujet=sujet, body="My main answer")
                WritingResponseOverride.objects.create(
                    user=user, sujet=sujet, version_key="edited", body="My alternative answer",
                )
                WritingResponseOverride.objects.create(
                    user=user, sujet=sujet, version_key="hidden", is_deleted=True,
                )
                WritingSujetCompletion.objects.create(user=user, sujet=sujet)

    def test_writing_activity_is_counted_once_per_owned_record_and_scoped(self):
        for url, subjects, responses in (
            (reverse("study:stats"), 2, 4),
            (reverse("study:part_stats", args=["ee"]), 2, 4),
            (reverse("study:task_stats", args=["ee", "tache-1"]), 1, 2),
            (reverse("study:task_stats", args=["ee", "tache-2"]), 1, 2),
            (reverse("study:task_stats", args=["eo", "tache-3"]), 0, 0),
        ):
            with self.subTest(url=url):
                page = self.client.get(url)
                self.assertEqual(page.status_code, 200)
                rows = page.context["breakdown"]
                counts = {row["key"]: row["count"] for row in rows}
                self.assertEqual(len(rows), len(counts))
                self.assertEqual(counts["subjects"], subjects)
                self.assertEqual(counts["responses"], responses)
                self.assertEqual(page.context["total_activity"], subjects + responses)
                self.assertEqual(page.context["activity_today"], subjects + responses)
                self.assertEqual(page.context["activity_30_days"], subjects + responses)

    def test_writing_activity_uses_each_records_timestamp_and_keeps_all_time_totals(self):
        now = timezone.now()
        previous_day = now - timezone.timedelta(days=2)
        old_day = now - timezone.timedelta(days=400)
        PersonalWritingResponse.objects.filter(
            user=self.user, sujet__task=self.first_task,
        ).update(updated_at=old_day)
        WritingResponseOverride.objects.filter(
            user=self.user, sujet__task=self.first_task, version_key="edited",
        ).update(updated_at=previous_day)
        WritingSujetCompletion.objects.filter(
            user=self.user, sujet__task=self.first_task,
        ).update(completed_at=previous_day)
        page = self.client.get(reverse("study:task_stats", args=["ee", "tache-1"]))
        self.assertEqual(page.context["total_activity"], 3)
        self.assertEqual(page.context["activity_today"], 0)
        self.assertEqual(page.context["activity_30_days"], 2)
        day_counts = {row["date"]: row["count"] for row in page.context["daily"]}
        self.assertEqual(day_counts[timezone.localtime(previous_day).date()], 2)

    def test_activity_sources_are_batched_for_every_scope_in_one_query(self):
        now = timezone.now()
        PersonalWritingResponse.objects.update(updated_at=now)
        WritingResponseOverride.objects.update(updated_at=now)
        WritingSujetCompletion.objects.update(completed_at=now)
        for scope, total in (
            ({}, 6),
            ({"part": "ee"}, 6),
            ({"part": "ee", "task": "tache-1"}, 3),
            ({"part": "ee", "task": "tache-2"}, 3),
            ({"part": "eo", "task": "tache-3"}, 0),
        ):
            with self.subTest(scope=scope):
                cards = _stats_scope_cards(scope, self.user)
                logs = ReviewLog.objects.filter(user=self.user)
                with self.assertNumQueries(1):
                    activity = _learning_activity(scope, self.user, cards, logs, now)
                self.assertEqual(activity["total_activity"], total)
                self.assertEqual(
                    activity["per_day"],
                    {timezone.localtime(now).date(): total} if total else {},
                )
                self.assertEqual(
                    [item["key"] for item in activity["breakdown"]],
                    ["reviews", "subjects", "responses", "notes"]
                    + ([] if scope else ["comprehension", "memories", "lessons"])
                    + (
                        ["formulations"]
                        if not scope
                        or scope.get("part") == "ee"
                        and scope.get("task") in {None, "tache-1", "tache-3"}
                        else []
                    ),
                )

    def test_formulation_language_progress_is_not_reported_as_memory(self):
        now = timezone.now()
        for question_key in (
            "formulation:ee1:v1:opening",
            "formulation-language:ee1:v1:greetings:hello",
            "formulation:ee3:v1:stance",
            "formulation-language:ee3:v1:education:access",
            "legacy-memory",
        ):
            MemoryQuestionProgress.objects.create(
                user=self.user,
                memory_number=1,
                question_key=question_key,
            )

        activity = _learning_activity(
            {},
            self.user,
            _stats_scope_cards({}, self.user),
            ReviewLog.objects.filter(user=self.user),
            now,
        )
        counts = {
            row["key"]: row["count"]
            for row in activity["breakdown"]
        }
        self.assertEqual(counts["memories"], 1)
        self.assertEqual(counts["formulations"], 4)

        activity = _learning_activity(
            {"part": "ee", "task": "tache-1"},
            self.user,
            _stats_scope_cards(
                {"part": "ee", "task": "tache-1"},
                self.user,
            ),
            ReviewLog.objects.filter(user=self.user),
            now,
        )
        counts = {
            row["key"]: row["count"]
            for row in activity["breakdown"]
        }
        self.assertEqual(counts["formulations"], 2)
        self.assertNotIn("memories", counts)

    def test_batched_activity_keeps_local_days_and_exact_history_cutoff(self):
        now = datetime(2026, 3, 12, 0, 30, tzinfo=datetime_timezone.utc)
        cutoff = now - timezone.timedelta(days=365)
        PersonalWritingResponse.objects.filter(
            user=self.user, sujet__task=self.first_task,
        ).update(updated_at=cutoff - timezone.timedelta(hours=1))
        PersonalWritingResponse.objects.filter(
            user=self.user, sujet__task=self.second_task,
        ).update(updated_at=cutoff)
        WritingResponseOverride.objects.filter(user=self.user).update(updated_at=now)
        WritingSujetCompletion.objects.filter(user=self.user).update(completed_at=now)
        with timezone.override("America/Los_Angeles"):
            with self.assertNumQueries(1):
                activity = _learning_activity(
                    {}, self.user,
                    Card.objects.filter(user=self.user),
                    ReviewLog.objects.filter(user=self.user),
                    now,
                )
            expected_days = {
                timezone.localtime(now).date(): 4,
                timezone.localtime(cutoff).date(): 1,
            }
        self.assertEqual(activity["total_activity"], 6)
        self.assertEqual(activity["per_day"], expected_days)
        self.assertEqual(activity["active_days"], set(expected_days))
