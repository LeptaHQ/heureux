import uuid

from django.test import TestCase, override_settings
from django.urls import reverse

from study.catalogue.loader import tache_two_subject_content_key
from study.models import EO2PracticeAttempt, EO2TopicStatus
from . import factories


@override_settings(GEMINI_LIVE_API_KEY="")
class TopicPracticeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.task = factories.make_task(factories.make_part("eo"), "tache-2")
        theme = factories.make_theme("sujets", task=cls.task)
        cls.prompt = factories.make_response(theme=theme).prompts.get()
        cls.prompt.content_key = tache_two_subject_content_key("mai", 2, 8)
        cls.prompt.save(update_fields=["content_key"])
        cls.user = factories.make_user("topic-learner")
        cls.other = factories.make_user("other-topic-learner")

    def setUp(self):
        self.client.force_login(self.user)
        self.picker = reverse("study:eo2_topic_picker")
        self.status = reverse("study:eo2_topic_status", args=[self.prompt.pk])
        self.history = reverse("study:eo2_topic_history", args=[self.prompt.pk])
        self.finish = reverse("study:eo2_practice_finish")
        self.rehearsal = reverse("study:eo2_rehearsal", args=[self.prompt.pk])

    def test_markers_are_independent_of_each_other_and_actual_sessions(self):
        self.assertContains(self.client.get(self.picker), self.rehearsal)
        self.assertEqual(self.client.get(self.rehearsal).status_code, 200)
        self.assertEqual(self.client.post(self.status, {"field": "done", "value": "1"}).status_code, 302)
        self.client.post(self.status, {"field": "retry", "value": "1"})
        for mark in ("done", "retry", "new"):
            self.assertContains(self.client.get(self.picker, {"status": mark}), self.rehearsal)
        self.client.post(self.status, {"field": "done", "value": "0"})
        self.assertNotContains(self.client.get(self.picker, {"status": "done"}), self.rehearsal)
        self.assertEqual(self.client.get(self.history).context["page"].paginator.count, 0)
        self.assertFalse(EO2PracticeAttempt.objects.exists())
        payload = {"topic": self.prompt.pk, "attempt": str(uuid.uuid4())}
        self.assertEqual(self.client.post(self.finish, payload).json(), {"recorded": True})
        self.client.post(self.status, {"field": "done", "value": "0"})
        self.assertEqual(self.client.post(self.finish, payload).json(), {"recorded": True})
        current = EO2TopicStatus.objects.get(user=self.user, subject_key=self.prompt.content_key)
        self.assertFalse(current.done)
        self.assertTrue(current.retry)
        self.assertEqual(self.client.post(self.finish, {**payload, "topic": "atelier-photo"}).status_code, 409)
        self.client.post(self.finish, {**payload, "attempt": uuid.uuid4()})
        self.assertEqual(self.client.get(self.history).context["page"].paginator.count, 2)
        self.assertNotContains(self.client.get(self.picker, {"status": "new"}), self.rehearsal)
        retry_page = self.client.get(self.picker, {"etat": "retry"})
        self.assertEqual(retry_page.context["page"][0]["count"], 2)
        self.assertContains(retry_page, self.history)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.history).context["page"].paginator.count, 0)
        self.assertNotContains(self.client.get(self.picker, {"status": "retry"}), self.rehearsal)
        self.assertEqual(self.client.post(self.finish, payload).status_code, 200)
        self.assertEqual(self.client.get(self.history).context["page"].paginator.count, 1)

    def test_table_combines_theme_search_and_status_and_sorts_all_results(self):
        done = {"topic": self.prompt.pk, "attempt": uuid.uuid4()}
        self.client.post(self.finish, done)
        self.client.post(self.status, {"field": "retry", "value": "1"})
        page = self.client.get(self.picker)
        topic = next(row["topic"] for row in page.context["page"] if row["token"] == self.prompt.pk)
        filters = {"q": topic.title, "theme": topic.theme_slug, "etat": "retry", "tri": "az"}
        selected = self.client.get(self.picker, filters)
        self.assertEqual([row["token"] for row in selected.context["page"]], [self.prompt.pk])
        self.assertContains(selected, 'aria-sort="ascending"')
        self.assertContains(selected, 'aria-label="Réinitialiser les filtres"')
        self.assertContains(self.client.get(self.picker, {**filters, "etat": "new"}), "Aucun sujet")
        self.assertContains(self.client.get(self.picker, {**filters, "theme": "absent"}), "Aucun sujet")
        self.assertEqual(self.client.get(self.picker, {"tri": "recent"}).context["page"][0]["token"], self.prompt.pk)
        self.assertEqual(self.client.get(self.picker, {"tri": "least"}).context["page"][0]["token"], "atelier-photo")
        az, za = ([r["token"] for r in self.client.get(self.picker, {"tri": order}).context["page"]] for order in ("az", "za"))
        self.assertEqual(za, list(reversed(az)))

    def test_status_post_supports_background_save_and_plain_form_redirect(self):
        headers = {"x-requested-with": "fetch"}
        change = {"field": "retry", "value": "1"}
        for _ in range(2):
            response = self.client.post(self.status, change, headers=headers)
            self.assertEqual(response.json(), {"field": "retry", "value": True})
        self.assertEqual(self.client.post(self.status, {**change, "value": "x"}, headers=headers).status_code, 400)
        response = self.client.post(self.status + "?etat=retry&page=2", {"field": "done", "value": "1"})
        self.assertRedirects(response, f"{self.picker}?etat=retry&page=2#topic-{self.prompt.pk}")
        self.assertTrue(EO2TopicStatus.objects.get(user=self.user, subject_key=self.prompt.content_key).retry)
        self.assertFalse(EO2PracticeAttempt.objects.exists())

    def test_unpublished_and_unavailable_topics_cannot_be_practiced_or_marked(self):
        self.assertEqual(self.client.post(self.finish, {"topic": self.prompt.pk, "attempt": "incorrect"}).status_code, 400)
        self.prompt.is_active = False
        self.prompt.save(update_fields=["is_active"])
        self.assertNotContains(self.client.get(self.picker), self.rehearsal)
        self.assertEqual(self.client.post(self.status, {"field": "retry", "value": "1"}).status_code, 404)
        self.assertEqual(self.client.get(self.history).status_code, 404)
        self.assertEqual(self.client.get(self.rehearsal).status_code, 404)
        self.task.available = False
        self.task.save(update_fields=["available"])
        self.assertEqual(self.client.get(self.picker).status_code, 404)
        self.assertEqual(self.client.post(self.finish, {"topic": "atelier-photo", "attempt": uuid.uuid4()}).status_code, 404)
        self.assertFalse(EO2PracticeAttempt.objects.exists())
