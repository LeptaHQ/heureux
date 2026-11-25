import uuid

from django.test import TestCase, override_settings
from django.urls import reverse

from study.catalogue.loader import tache_two_subject_content_key
from study.models import EO2PracticeAttempt, EO2TopicStatus, LiveSimulation, Prompt
from . import factories


@override_settings(GEMINI_API_KEY="")
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
        self.live = reverse("study:eo_tache_two_live", args=["mai", 2, 8])
        self.rehearsal = reverse("study:eo2_rehearsal", args=[self.prompt.pk])

    @override_settings(GEMINI_API_KEY="test-key", AI_PIN="test-pin")
    def test_topic_and_old_bookmarks_open_only_the_matching_simulation(self):
        picker = self.client.get(self.picker)
        photo = reverse("study:eo_tache_two_live")
        self.assertContains(picker, f'href="{photo}"', count=1)
        self.assertContains(picker, f'href="{self.live}"', count=1)
        self.assertNotContains(picker, self.rehearsal)
        self.assertRedirects(self.client.get(self.rehearsal), self.live)
        self.assertRedirects(self.client.get(reverse("study:eo_tache_two_interaction")), photo)
        for token, url in ((self.prompt.pk, self.live), ("atelier-photo", photo)):
            history = self.client.get(reverse("study:eo2_topic_history", args=[token]))
            self.assertContains(history, f'href="{url}">Pratiquer ce sujet')
            session = self.client.get(url)
            self.assertEqual(session.context["subject"].title, history.context["topic"].title)
            for step in ("Préparation", "Échange", "Bilan"):
                self.assertContains(session, f'class="lv-step__name">{step}</span>')
            for obsolete in ("simulateur guidé", "Au clavier", self.rehearsal):
                self.assertNotContains(session, obsolete)
        self.assertFalse(EO2PracticeAttempt.objects.exists())

    def test_equivalent_publications_share_markers_but_not_session_counts(self):
        alias = Prompt.objects.create(
            theme=self.prompt.theme, response=self.prompt.response, family=self.prompt.family,
            number=self.prompt.number + 1, content_key=tache_two_subject_content_key("octobre", 5, 21),
            text="Autre publication",
        )
        EO2TopicStatus.objects.create(user=self.user, subject_key=alias.content_key, done=True, retry=True)
        EO2PracticeAttempt.objects.create(user=self.user, subject_key=alias.content_key, attempt=uuid.uuid4())
        grouped = self.client.get(self.picker)
        self.assertEqual((grouped.context["total"], grouped.context["done_total"], grouped.context["retry_total"]), (2, 1, 1))
        published = self.client.get(self.picker, {"deduplicate": "0"})
        rows = {row["token"]: row for row in published.context["page"]}
        self.assertTrue(all(rows[pk]["done"] and rows[pk]["retry"] for pk in (self.prompt.pk, alias.pk)))
        self.assertEqual((rows[self.prompt.pk]["count"], rows[alias.pk]["count"]), (0, 1))
        self.client.post(self.status, {"field": "done", "value": "0"})
        self.assertFalse(EO2TopicStatus.objects.filter(user=self.user, done=True).exists())
        self.assertEqual(self.client.get(self.picker).context["retry_total"], 1)

    def test_markers_are_independent_of_each_other_and_actual_sessions(self):
        self.assertEqual(self.client.post(self.status, {"field": "done", "value": "1"}).status_code, 302)
        self.client.post(self.status, {"field": "retry", "value": "1"})
        for mark in ("done", "retry", "new"):
            self.assertContains(self.client.get(self.picker, {"etat": mark}), self.live)
        self.client.post(self.status, {"field": "done", "value": "0"})
        self.assertNotContains(self.client.get(self.picker, {"etat": "done"}), self.live)
        self.assertEqual(self.client.get(self.history).context["page"].paginator.count, 0)
        self.assertFalse(EO2PracticeAttempt.objects.exists())
        current = EO2TopicStatus.objects.get(user=self.user, subject_key=self.prompt.content_key)
        self.assertFalse(current.done)
        self.assertTrue(current.retry)
        self.client.force_login(self.other)
        self.assertNotContains(self.client.get(self.picker, {"etat": "retry"}), self.live)

    @override_settings(GEMINI_API_KEY="", AI_PIN="")
    def test_existing_guided_attempt_and_saved_bilan_remain_private_and_count_once(self):
        key = self.prompt.content_key
        EO2PracticeAttempt.objects.create(user=self.user, subject_key=key, attempt=uuid.uuid4())
        saved = LiveSimulation.objects.create(user=self.user, subject_key=key, rows=[])
        EO2PracticeAttempt.objects.create(user=self.user, subject_key=key, attempt=saved.pk,
                                          vocal=True, live_simulation=saved)
        review_url = f"{self.live}?simulation={saved.pk}"
        history = self.client.get(self.history)
        self.assertContains(history, "Ancien entraînement guidé")
        self.assertContains(history, f'href="{review_url}"', count=1)
        self.assertEqual(str(self.client.get(review_url).context["saved_simulation"]["id"]), str(saved.pk))
        topic_row = next(r for r in self.client.get(self.picker).context["page"] if r["token"] == self.prompt.pk)
        self.assertEqual(topic_row["count"], 2)
        for path in ("/simulation/orale/tache-2/seances/", f"/simulation/orale/tache-2/sujets/{self.prompt.pk}/replique/"):
            self.assertEqual(self.client.post(path, {"topic": self.prompt.pk, "attempt": str(uuid.uuid4())}).status_code, 404)
        self.assertEqual(EO2PracticeAttempt.objects.count(), 2)
        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self.history).context["page"].paginator.count, 0)
        self.assertIsNone(self.client.get(review_url).context["saved_simulation"])

    def test_table_combines_theme_search_and_status_and_sorts_all_results(self):
        EO2PracticeAttempt.objects.create(user=self.user, subject_key=self.prompt.content_key, attempt=uuid.uuid4())
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
        self.prompt.is_active = False
        self.prompt.save(update_fields=["is_active"])
        self.assertNotContains(self.client.get(self.picker), self.live)
        self.assertEqual(self.client.post(self.status, {"field": "retry", "value": "1"}).status_code, 404)
        self.assertEqual(self.client.get(self.history).status_code, 404)
        self.assertEqual(self.client.get(self.rehearsal).status_code, 404)
        self.task.available = False
        self.task.save(update_fields=["available"])
        self.assertEqual(self.client.get(self.picker).status_code, 404)
        self.assertFalse(EO2PracticeAttempt.objects.exists())
