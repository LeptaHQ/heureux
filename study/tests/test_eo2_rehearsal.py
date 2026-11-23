import json
import shutil
import subprocess
import time
from pathlib import Path
from unittest import skipUnless
from unittest.mock import patch
from urllib.parse import urlencode

from django.conf import settings
from django.test import Client, SimpleTestCase, TestCase, override_settings
from django.urls import reverse
from django.utils.html import escape

from study.catalogue import registry as catalogue
from study.views.eo2_rehearsal import CURSOR_MAX_AGE
from . import factories


@override_settings(GEMINI_LIVE_API_KEY="", AI_PIN="")
class EO2RehearsalTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.user = factories.make_user()
        cls.other_user = factories.make_user()
        cls.task = factories.make_task(factories.make_part("eo"), "tache-2")
        cls.theme = factories.make_theme("rehearsal", task=cls.task)
        cls.prompts = []
        groups = set()
        for key, dialogue in catalogue.tache_two_dialogues().items():
            if dialogue.group in groups:
                continue
            response = factories.make_response(theme=cls.theme)
            prompt = response.prompts.get()
            prompt.content_key = key
            prompt.save(update_fields=["content_key"])
            cls.prompts.append(prompt)
            groups.add(dialogue.group)
            if len(cls.prompts) == 2:
                break

    def setUp(self):
        self.client.force_login(self.user)
        self.prompt = self.prompts[0]
        self.dialogue = catalogue.tache_two_dialogues()[self.prompt.content_key]
        self.url = reverse("study:eo2_rehearsal", args=[self.prompt.pk])
        self.reply_url = reverse("study:eo2_rehearsal_reply", args=[self.prompt.pk])

    def reply(self, cursor, *, action="reply", url=None, **extra):
        return self.client.post(
            url or self.reply_url, urlencode({"cursor": cursor, "action": action, **extra}),
            content_type="application/x-www-form-urlencoded",
        )

    def test_selected_publication_works_without_live_voice_or_an_answer_bank(self):
        page = self.client.get(self.url + "?deduplicate=0")
        self.assertEqual(page.status_code, 200)
        self.assertFalse(page.context["gemini_live_available"])
        self.assertContains(page, escape(page.context["topic"].prompt))
        self.assertContains(page, escape(page.context["topic"].title))
        self.assertIn("deduplicate=0", page.context["subject_url"])
        self.assertIn("no-store", page["Cache-Control"])
        self.assertContains(page, "sans audio ni transcription")
        self.assertEqual(page.context["initial_turn"]["question"], self.dialogue.questions[0].question)
        for question in self.dialogue.questions:
            self.assertNotContains(page, escape(question.answer))
            self.assertNotContains(page, json.dumps(question.answer))
        for field in ("dialogue", "answers", "response_content"):
            self.assertNotIn(field, page.context)

        current = page.context["initial_turn"]
        for index, question in enumerate(self.dialogue.questions):
            with self.subTest(turn=index + 1):
                result = self.reply(current["cursor"])
                self.assertEqual(result.status_code, 200)
                self.assertIn("no-store", result["Cache-Control"])
                data = result.json()
                self.assertEqual(data["answer"], question.answer)
                self.assertEqual(set(data), {"answer", "next", "closing"})
                if index + 1 < len(self.dialogue.questions):
                    self.assertEqual(data["next"]["question"], self.dialogue.questions[index + 1].question)
                    self.assertNotIn("answer", data["next"])
                    self.assertEqual(data["closing"], "")
                else:
                    self.assertIsNone(data["next"])
                    self.assertEqual(data["closing"], self.dialogue.closing)
                current = data["next"]

    def test_cursor_is_bound_to_publication_and_user_and_expires(self):
        cursor = self.client.get(self.url).context["initial_turn"]["cursor"]
        other_url = reverse("study:eo2_rehearsal_reply", args=[self.prompts[1].pk])
        self.assertEqual(self.reply(cursor, url=other_url).status_code, 400)
        self.client.force_login(self.other_user)
        self.assertEqual(self.reply(cursor).status_code, 400)
        self.client.force_login(self.user)
        self.assertEqual(self.reply(cursor + "tampered").status_code, 400)
        with patch("django.core.signing.time.time", return_value=time.time() + CURSOR_MAX_AGE + 1):
            self.assertEqual(self.reply(cursor).status_code, 400)

    def test_unavailable_publication_never_falls_back_to_the_photo_studio(self):
        cursor = self.client.get(self.url).context["initial_turn"]["cursor"]
        with patch("study.views.eo2_rehearsal.catalogue.tache_two_dialogues", return_value={}):
            self.assertEqual(self.client.get(self.url).status_code, 404)
            self.assertEqual(self.reply(cursor).status_code, 404)
        self.prompt.is_active = False
        self.prompt.save(update_fields=["is_active"])
        self.assertEqual(self.client.get(self.url).status_code, 404)
        self.assertEqual(self.reply(cursor).status_code, 404)

    def test_reply_requires_csrf_and_accepts_no_learner_text(self):
        self.client = Client(enforce_csrf_checks=True)
        self.client.force_login(self.user)
        cursor = self.client.get(self.url).context["initial_turn"]["cursor"]
        self.assertEqual(self.reply(cursor).status_code, 403)
        token = self.client.cookies[settings.CSRF_COOKIE_NAME].value
        self.assertEqual(self.reply(cursor, csrfmiddlewaretoken=token).status_code, 200)
        result = self.reply(cursor, csrfmiddlewaretoken=token, text="private learner words")
        self.assertEqual(result.status_code, 400)
        self.assertNotIn("private learner words", result.content.decode())
        self.assertEqual(self.client.get(self.reply_url).status_code, 405)

    def test_only_conditional_relances_can_be_skipped_without_revealing_answers(self):
        current = self.client.get(self.url).context["initial_turn"]
        for question in self.dialogue.questions:
            result = self.reply(current["cursor"], action="skip")
            if question.follow_up_to is not None:
                self.assertEqual(result.status_code, 200)
                self.assertEqual(result.json()["answer"], "")
                self.assertNotIn(question.answer, result.content.decode())
                break
            self.assertEqual(result.status_code, 400)
            current = self.reply(current["cursor"]).json()["next"]
        else:
            self.fail("The published route must contain a conditional relance.")


class EO2RehearsalScriptTests(SimpleTestCase):
    @skipUnless(shutil.which("node"), "Node is required for JavaScript unit checks")
    def test_rehearsal_turns_and_retry(self):
        result = subprocess.run(
            ["node", str(Path(__file__).with_name("eo2_rehearsal_check.js"))],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
