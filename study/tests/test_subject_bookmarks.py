"""Subject bookmarks are private saved targets, not study activity."""

from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.template import Context
from django.test import Client, RequestFactory, TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from study.catalogue import loader as content
from study.models import (
    Card,
    Prompt,
    Response,
    SubjectBookmark,
    Task,
    WritingSujet,
    WritingSujetCompletion,
)
from study.navigation.routing import prompt_detail_url, response_detail_url, theme_detail_url
from study.review.progress import subject_progress_by_response
from study.templatetags.study_bookmarks import subject_bookmark

from . import factories


class SubjectBookmarkTests(TestCase):
    def setUp(self):
        self.user = factories.make_user("bookmark-owner")
        self.other = factories.make_user("other-bookmark-owner")
        self.task = factories.make_task(factories.make_part("eo"), "tache-3")
        self.response = factories.make_response(
            theme=factories.make_theme("bookmark-theme", task=self.task),
        )
        self.writing_task = factories.make_task(factories.make_part("ee"), "tache-1")
        self.sujet = factories.make_writing_sujet(task=self.writing_task)
        self.client.force_login(self.user)

    def url(self, *, task=None, target_type="response", target_id=None):
        task = task or self.task
        return reverse("study:subject_bookmark", args=[
            task.part.slug, task.slug, target_type,
            self.response.pk if target_id is None else target_id,
        ])

    def save(self, value, **kwargs):
        return self.client.post(
            self.url(**kwargs), {"bookmarked": value},
            HTTP_X_REQUESTED_WITH="fetch",
        )

    def test_bookmark_is_persistent_idempotent_private_and_independent_of_progress(self):
        initial = subject_progress_by_response(self.user, {self.response.pk})
        cards = list(Card.objects.values())
        for value in ("1", "1", "0", "0"):
            with self.subTest(value=value):
                result = self.save(value)
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json(), {
                    "key": f"response:{self.response.pk}", "bookmarked": value == "1",
                })
                self.assertEqual(
                    SubjectBookmark.objects.filter(user=self.user).count(),
                    int(value),
                )
                self.assertEqual(list(Card.objects.values()), cards)
                self.assertEqual(
                    subject_progress_by_response(self.user, {self.response.pk}), initial,
                )
        self.save("1")
        self.client.force_login(self.other)
        self.save("0")
        self.assertTrue(SubjectBookmark.objects.filter(user=self.user).exists())
        self.assertFalse(SubjectBookmark.objects.filter(user=self.other).exists())
        self.save("1")
        self.assertEqual(SubjectBookmark.objects.count(), 2)

    def test_database_enforces_exactly_one_target_and_unique_user_target(self):
        invalid_targets = (
            {},
            {"response": self.response, "sujet": self.sujet},
        )
        for target in invalid_targets:
            with self.subTest(target=target), self.assertRaises(IntegrityError):
                with transaction.atomic():
                    SubjectBookmark.objects.create(user=self.user, **target)
        for target in ({"response": self.response}, {"sujet": self.sujet}):
            SubjectBookmark.objects.create(user=self.user, **target)
            with self.subTest(target=target), self.assertRaises(IntegrityError):
                with transaction.atomic():
                    SubjectBookmark.objects.create(user=self.user, **target)
            SubjectBookmark.objects.create(user=self.other, **target)

    def test_rejects_bad_state_task_target_method_and_anonymous_requests(self):
        for value in ("yes", "", "2"):
            self.assertEqual(self.save(value).status_code, 400)
        self.assertEqual(self.client.post(self.url()).status_code, 400)
        self.assertEqual(self.client.get(self.url()).status_code, 405)
        wrong_task = factories.make_task(self.task.part, "tache-2")
        for kwargs in (
            {"task": wrong_task},
            {"target_type": "unknown"},
            {"target_type": "writing-sujet", "target_id": self.sujet.pk},
            {"target_id": self.response.pk + 100000},
        ):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(self.save("1", **kwargs).status_code, 404)
        self.assertFalse(SubjectBookmark.objects.exists())
        self.client.logout()
        self.assertEqual(self.save("1").status_code, 302)

    def test_rejects_inactive_response_prompt_theme_and_writing_sujet(self):
        prompt = self.response.prompts.get(is_canonical=True)
        for target in (self.response, prompt, self.response.theme):
            with self.subTest(model=type(target).__name__):
                target.is_active = False
                target.save(update_fields=["is_active"])
                self.assertEqual(self.save("1").status_code, 404)
                target.is_active = True
                target.save(update_fields=["is_active"])
        self.sujet.is_active = False
        self.sujet.save(update_fields=["is_active"])
        self.assertEqual(self.save(
            "1", task=self.writing_task, target_type="writing-sujet",
            target_id=self.sujet.pk,
        ).status_code, 404)
        self.assertFalse(SubjectBookmark.objects.exists())

    def test_non_javascript_submission_redirects_and_csrf_is_required(self):
        response = self.client.post(self.url(), {"bookmarked": "1"})
        self.assertRedirects(
            response, prompt_detail_url(self.response.prompts.get(is_canonical=True)),
            fetch_redirect_response=False,
        )
        protected = Client(enforce_csrf_checks=True)
        protected.force_login(self.user)
        self.assertEqual(protected.post(
            self.url(), {"bookmarked": "0"},
            HTTP_X_REQUESTED_WITH="fetch",
        ).status_code, 403)
        self.assertTrue(SubjectBookmark.objects.filter(user=self.user).exists())

    def test_equivalent_prompts_share_detail_and_directory_bookmarks(self):
        alias = Prompt.objects.create(
            content_key="test:bookmark-alias", response=self.response,
            theme=self.response.theme, family=self.response.family,
            number=999, text="Une autre formulation du même sujet.",
        )
        self.save("1")
        for url in (
            response_detail_url(self.response),
            prompt_detail_url(alias),
            reverse("study:task_browse", args=["eo", "tache-3"]) + "?deduplicate=0",
        ):
            with self.subTest(url=url):
                page = self.client.get(url)
                self.assertContains(page, f'data-subject-bookmark-key="response:{self.response.pk}"')
                self.assertContains(page, 'aria-pressed="true"')
                self.assertContains(page, "subject-bookmark is-bookmarked")
        self.client.force_login(self.other)
        page = self.client.get(response_detail_url(self.response))
        self.assertNotContains(page, "subject-bookmark is-bookmarked")

    def test_writing_alias_setter_uses_canonical_target_without_completion(self):
        alias = factories.make_writing_sujet(task=self.writing_task)
        with patch(
            "study.views.library.content_module.ee_writing_canonical_slug_by_slug",
            return_value={alias.slug: self.sujet.slug},
        ):
            for value in ("1", "1", "0", "0"):
                result = self.save(
                    value, task=self.writing_task, target_type="writing-sujet",
                    target_id=alias.pk,
                )
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json(), {
                    "key": f"writing-sujet:{self.sujet.pk}",
                    "bookmarked": value == "1",
                })
                self.assertFalse(SubjectBookmark.objects.filter(sujet=alias).exists())
                self.assertEqual(
                    SubjectBookmark.objects.filter(sujet=self.sujet).count(), int(value),
                )
        self.assertFalse(WritingSujetCompletion.objects.exists())
        self.assertFalse(Card.objects.exists())

    def test_bookmark_ids_are_batched_per_request_user_task_and_target_type(self):
        SubjectBookmark.objects.create(user=self.user, response=self.response)
        SubjectBookmark.objects.create(user=self.other, sujet=self.sujet)
        request = RequestFactory().get("/")
        request.user = self.user
        context = Context({"request": request, "task": self.task})
        with self.assertNumQueries(1):
            for _ in range(25):
                self.assertTrue(subject_bookmark(context, response_id=self.response.pk)["bookmarked"])
        context["task"] = self.writing_task
        with self.assertNumQueries(1):
            self.assertFalse(subject_bookmark(context, sujet_id=self.sujet.pk)["bookmarked"])
        request.user = self.other
        with self.assertNumQueries(1):
            self.assertTrue(subject_bookmark(context, sujet_id=self.sujet.pk)["bookmarked"])
        with CaptureQueriesContext(connection) as queries:
            subject_progress_by_response(self.user, {self.response.pk}, summary_only=True)
        self.assertFalse(any("study_subjectbookmark" in row["sql"] for row in queries))

    def test_account_export_includes_only_owned_bookmarks(self):
        SubjectBookmark.objects.create(user=self.user, response=self.response)
        SubjectBookmark.objects.create(user=self.user, sujet=self.sujet)
        SubjectBookmark.objects.create(user=self.other, response=self.response)
        exported = self.client.get(reverse("study:export_account")).json()["subject_bookmarks"]
        self.assertEqual(len(exported), 2)
        self.assertEqual(exported[0]["response_key"], self.response.content_key)
        self.assertIsNone(exported[0]["sujet"])
        self.assertEqual(exported[1]["sujet"], self.sujet.slug)
        self.assertEqual((exported[1]["part"], exported[1]["task"]), ("ee", "tache-1"))


class SubjectBookmarkCatalogueTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("import_content", stdout=StringIO())
        cls.user = factories.make_user("catalogue-bookmark-owner")

    def setUp(self):
        self.client.force_login(self.user)

    def test_oral_and_written_task_three_share_saved_state_with_one_directory_query(self):
        for part in ("eo", "ee"):
            with self.subTest(part=part):
                task = Task.objects.select_related("part").get(
                    part__slug=part, slug="tache-3",
                )
                response = Response.objects.filter(
                    theme__task=task, is_active=True,
                ).order_by("pk").first()
                SubjectBookmark.objects.create(user=self.user, response=response)
                key = f'data-subject-bookmark-key="response:{response.pk}"'
                directory_url = reverse("study:task_browse", args=[part, task.slug])
                self.client.get(directory_url)
                with CaptureQueriesContext(connection) as queries:
                    directory = self.client.get(directory_url)
                self.assertContains(directory, key)
                self.assertContains(directory, "subject-bookmark is-bookmarked")
                self.assertNotContains(directory, 'class="icon-button prompt-copy-button"')
                self.assertEqual(
                    sum('FROM "study_subjectbookmark"' in row["sql"] for row in queries), 1,
                )
                detail = self.client.get(response_detail_url(response))
                self.assertContains(detail, key)
                self.assertContains(detail, "subject-bookmark is-bookmarked")
                self.assertContains(detail, 'data-icon="copy"')

    def test_published_writing_aliases_display_and_save_canonical_bookmarks(self):
        for tache in (1, 2):
            with self.subTest(tache=tache):
                task = Task.objects.select_related("part").get(
                    part__slug="ee", slug=f"tache-{tache}",
                )
                group = content.load_ee_equivalent_groups(tache)[0]
                canonical = WritingSujet.objects.get(
                    task=task, slug=content.ee_writing_sujet_slug(group.canonical),
                )
                alias = WritingSujet.objects.get(
                    task=task, slug=content.ee_writing_sujet_slug(
                        next(member for member in group.members if member != group.canonical)
                    ),
                )
                result = self.client.post(reverse("study:subject_bookmark", args=[
                    "ee", task.slug, "writing-sujet", alias.pk,
                ]), {"bookmarked": "1"}, HTTP_X_REQUESTED_WITH="fetch")
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json()["key"], f"writing-sujet:{canonical.pk}")
                detail = self.client.get(reverse("study:writing_sujet_detail", args=[
                    "ee", task.slug, alias.pk,
                ]))
                self.assertContains(detail, "subject-bookmark is-bookmarked")
                self.assertContains(detail, f'data-subject-bookmark-key="writing-sujet:{canonical.pk}"')
                directory_url = reverse("study:task_browse", args=["ee", task.slug])
                with CaptureQueriesContext(connection) as queries:
                    directory = self.client.get(directory_url)
                self.assertContains(directory, f'data-subject-bookmark-key="writing-sujet:{canonical.pk}"')
                self.assertNotContains(directory, f'data-subject-bookmark-key="writing-sujet:{alias.pk}"')
                self.assertEqual(
                    sum('FROM "study_subjectbookmark"' in row["sql"] for row in queries), 1,
                )
        self.assertFalse(WritingSujetCompletion.objects.exists())

    def test_alternate_oral_batch_and_written_month_directories_show_bookmarks(self):
        batch_url = reverse("study:task_subject_batch", args=["eo", "tache-2", "janvier", 1])
        batch = self.client.get(batch_url)
        response_id = batch.context["subject_batch"]["subjects"][0]["response_id"]
        SubjectBookmark.objects.create(user=self.user, response_id=response_id)
        batch = self.client.get(batch_url)
        self.assertContains(batch, f'data-subject-bookmark-key="response:{response_id}"')
        self.assertContains(batch, "subject-bookmark is-bookmarked")
        self.assertNotContains(batch, "data-prompt-copy-source")
        prompt = Prompt.objects.select_related("theme__task__part").filter(
            theme__task__part__slug="ee", theme__task__slug="tache-3",
            is_active=True, response__is_active=True,
        ).first()
        SubjectBookmark.objects.create(user=self.user, response_id=prompt.response_id)
        month = self.client.get(theme_detail_url(prompt.theme))
        self.assertContains(month, f'data-subject-bookmark-key="response:{prompt.response_id}"')
        self.assertContains(month, "subject-bookmark is-bookmarked")
