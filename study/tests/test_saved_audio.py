from dataclasses import asdict
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase, override_settings
from django.urls import reverse

from study import catalogue
from study.eo3_audio import (
    generate_narration, narration_presentation, narration_source, narration_spec,
    text_narration_spec,
)
from study.french_audio import enqueue, generate_prepared, source_grant, speech_spec
from study.models import EO3Narration, FrenchNarration, FrenchNarrationBudget, PersonalResponse, Prompt
from study.response_personalization import effective_response
from study.routing import prompt_detail_url

from . import factories
from .test_eo3_audio import AUDIO, AUDIO_PIN, ON_DEMAND_SETTINGS, TIMING


@override_settings(**ON_DEMAND_SETTINGS)
class SavedSubjectAudioTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("import_content", stdout=StringIO())
        cls.user = factories.make_user("saved-subject-reader")
        cls.other = factories.make_user("other-saved-reader")
        cls.prompt = Prompt.objects.select_related(
            "response__semantic_owner", "theme__task__part",
        ).get(content_key="culture:p26")

    def setUp(self):
        self.client.force_login(self.user)
        self.model = catalogue.tache_three_models()[self.prompt.response.semantic_group]
        self.source = narration_source(self.model)

    def take(self, text=None, owner=None, tracked=True):
        text = self.source.text if text is None else text
        spec = text_narration_spec(self.model.group, text, owner.pk if owner else None)
        EO3Narration.objects.create(
            fingerprint=spec.fingerprint, group=spec.group, voice_id=spec.voice_id,
            model_id=spec.model_id, audio=AUDIO, timing=TIMING,
        )
        if tracked:
            FrenchNarration.objects.create(
                pk=spec.fingerprint, target_group=spec.group, text=text,
                owner=owner, requested_by=self.user, status="ready",
                voice_id=spec.voice_id, model_id=spec.model_id,
            )
        return spec

    def prepare(self, *, refresh=False, pin=None):
        spec = narration_spec(self.model)
        return self.client.post(reverse("study:eo3_audio_prepare", args=[
            self.model.group.removeprefix("eo/tache-3/"), spec.fingerprint,
        ]), {
            "confirm_cost": True, "refresh": refresh, "pin": pin,
        }, content_type="application/json")

    def edit(self, introduction):
        content = self.model.response
        personal, _ = PersonalResponse.objects.update_or_create(
            user=self.user, response=self.prompt.response, defaults={
                "source_prompt": self.prompt, "position_claire": introduction,
                "arguments": [asdict(argument) for argument in content.arguments],
                "nuance": content.nuance, "conclusion": content.conclusion,
            },
        )
        return effective_response(self.prompt.response, self.user, personal=personal)

    @patch("study.french_audio.synthesize")
    def test_voice_change_keeps_saved_audio_with_no_key_pin_or_generation_budget(self, provider):
        old = self.take()
        with self.settings(
            ELEVENLABS_VOICE_ID="NewVoice", ELEVENLABS_API_KEY="", ELEVENLABS_PIN="",
            FRENCH_AUDIO_GENERATION_ENABLED=False, FRENCH_AUDIO_CHARACTER_BUDGET=0,
        ):
            presentation = narration_presentation(self.model)
            self.assertTrue(presentation["ready"])
            self.assertFalse(presentation["stale"])
            self.assertIn(old.fingerprint, presentation["url"])
            self.assertEqual(self.client.get(presentation["url"]).content, AUDIO)
            playlist = self.client.get(reverse("study:eo3_audio_playlist", args=[self.prompt.pk])).json()
            self.assertEqual(len(playlist["tracks"]), 1)
            self.assertIn(old.fingerprint, playlist["tracks"][0]["audio_url"])
        self.assertFalse(FrenchNarrationBudget.objects.exists())
        provider.assert_not_called()

    @patch("study.french_audio.synthesize")
    def test_earlier_text_is_playable_but_not_highlighted_or_silently_regenerated(self, provider):
        old = self.take(self.source.text + "\n\nUne ancienne conclusion.")
        presentation = narration_presentation(self.model)
        self.assertTrue(presentation["stale"])
        self.assertEqual(presentation["timing"], "")
        self.assertIn(old.fingerprint, presentation["url"])
        self.assertTrue(presentation["refresh_url"])
        page = self.client.get(prompt_detail_url(self.prompt))
        self.assertContains(page, "Enregistrement précédent")
        self.assertNotContains(page, "data-eo3-timing=")
        self.assertEqual(self.client.get(presentation["url"]).content, AUDIO)
        reply = self.prepare()
        self.assertEqual(reply.status_code, 200, reply.content)
        self.assertIn(old.fingerprint, reply.json()["html"])
        playlist = self.client.get(reverse("study:eo3_audio_playlist", args=[self.prompt.pk])).json()
        self.assertTrue(playlist["tracks"][0]["previous_version"])
        self.assertFalse(FrenchNarrationBudget.objects.exists())
        provider.assert_not_called()

    @patch("study.french_audio.synthesize", return_value=(AUDIO, TIMING))
    def test_only_explicit_refresh_with_pin_creates_current_text_and_voice(self, provider):
        old = self.take(self.source.text + "\n\nUne ancienne conclusion.")
        with self.settings(ELEVENLABS_VOICE_ID="NewVoice"):
            denied = self.prepare(refresh=True)
            self.assertEqual(denied.json()["error"], "pin_required")
            provider.assert_not_called()
            ready = self.prepare(refresh=True, pin=AUDIO_PIN)
            self.assertEqual(ready.status_code, 200, ready.content)
            generated = provider.call_args.args[0]
            self.assertEqual(generated.text, self.source.text)
            self.assertEqual(generated.voice_id, "NewVoice")
            self.assertNotEqual(generated.fingerprint, old.fingerprint)
            presentation = narration_presentation(self.model)
            self.assertFalse(presentation["stale"])
            self.assertIn(generated.fingerprint, presentation["url"])
            self.assertEqual(EO3Narration.objects.count(), 2)
            self.assertEqual(self.client.get(reverse("study:eo3_audio", args=[
                self.model.group.removeprefix("eo/tache-3/"), old.fingerprint,
            ])).content, AUDIO)
        provider.assert_called_once()

    @patch("study.french_audio.synthesize", return_value=(AUDIO, TIMING))
    def test_a_genuinely_missing_recording_uses_new_voice_and_requires_pin(self, provider):
        with self.settings(ELEVENLABS_VOICE_ID="NewVoice"):
            self.assertEqual(self.prepare().json()["error"], "pin_required")
            self.assertEqual(self.prepare(pin=AUDIO_PIN).status_code, 200)
        self.assertEqual(provider.call_args.args[0].voice_id, "NewVoice")
        provider.assert_called_once()

    def test_earlier_private_take_remains_owner_only_after_edit_and_voice_change(self):
        first = self.edit("Ma première introduction.")
        private_source = narration_source(self.model, first, self.user.pk)
        old = self.take(private_source.text, self.user)
        second = self.edit("Une nouvelle introduction.")
        with self.settings(ELEVENLABS_VOICE_ID="NewVoice"):
            presentation = narration_presentation(self.model, second, self.user.pk)
            self.assertTrue(presentation["stale"])
            self.assertIn(old.fingerprint, presentation["url"])
            reply = self.client.get(presentation["url"])
            self.assertEqual(reply.content, AUDIO)
            self.assertEqual(reply["Cache-Control"], "private, no-store")
            self.client.force_login(self.other)
            self.assertEqual(self.client.get(presentation["url"]).status_code, 404)
            self.assertFalse(narration_presentation(self.model)["ready"])

    def test_private_orphan_is_never_treated_as_a_public_previous_version(self):
        private = self.take(self.source.text, self.other, tracked=False)
        self.assertFalse(narration_presentation(self.model)["ready"])
        url = reverse("study:eo3_audio", args=[
            self.model.group.removeprefix("eo/tache-3/"), private.fingerprint,
        ])
        self.assertEqual(self.client.get(url).status_code, 404)

    def test_private_journal_never_becomes_public_and_account_deletion_removes_all_takes(self):
        public = self.take()
        first = self.take(self.source.text, self.other)
        second = self.take(self.source.text + "\n\nUne autre version privée.", self.other)
        FrenchNarration.objects.filter(pk=first.fingerprint).update(status="superseded")
        presentation = narration_presentation(self.model)
        self.assertIn(public.fingerprint, presentation["url"])
        private_url = reverse("study:eo3_audio", args=[
            self.model.group.removeprefix("eo/tache-3/"), first.fingerprint,
        ])
        self.assertEqual(self.client.get(private_url).status_code, 404)
        self.other.delete()
        self.assertFalse(EO3Narration.objects.filter(pk__in=[
            first.fingerprint, second.fingerprint,
        ]).exists())
        self.assertTrue(EO3Narration.objects.filter(pk=public.fingerprint).exists())

    def test_matching_text_is_preferred_over_a_newer_take_of_previous_text(self):
        exact = self.take()
        with self.settings(ELEVENLABS_VOICE_ID="AnotherVoice"):
            self.take(self.source.text + "\n\nUne ancienne conclusion.")
        with self.settings(ELEVENLABS_VOICE_ID="NewVoice"):
            presentation = narration_presentation(self.model)
        self.assertIn(exact.fingerprint, presentation["url"])
        self.assertFalse(presentation["stale"])

    @patch("study.eo3_audio.synthesize")
    @patch("study.management.commands.generate_eo3_audio.command_generation_pin")
    def test_operator_reuses_saved_subject_and_refresh_estimate_is_explicit(self, pin, provider):
        self.take(self.source.text + "\n\nUne ancienne conclusion.")
        with self.settings(ELEVENLABS_VOICE_ID="NewVoice", ELEVENLABS_PIN=""):
            output = StringIO()
            call_command("generate_eo3_audio", group=self.model.group, confirm_cost=True, stdout=output)
            self.assertIn("0 to generate", output.getvalue())
            output = StringIO()
            call_command("generate_eo3_audio", group=self.model.group, refresh=True, dry_run=True, stdout=output)
            self.assertIn("1 to generate", output.getvalue())
            self.assertFalse(generate_narration(narration_spec(self.model)))
        pin.assert_not_called()
        provider.assert_not_called()

    def test_source_and_owner_journal_must_match_before_reusing_older_text(self):
        old = self.take("Une ancienne intervention.")
        FrenchNarration.objects.filter(pk=old.fingerprint).update(target_group="eo/tache-3/other")
        self.assertFalse(narration_presentation(self.model)["ready"])


@override_settings(**ON_DEMAND_SETTINGS, FRENCH_AUDIO_ENABLED=True)
class SavedFrenchAudioTests(TestCase):
    def setUp(self):
        self.user = factories.make_user("saved-french-reader")
        self.client.force_login(self.user)
        self.text = "Un texte français déjà enregistré."
        self.spec = speech_spec(self.text)
        self.recording = FrenchNarration.objects.create(
            pk=self.spec.fingerprint, text=self.text, voice_id=self.spec.voice_id,
            model_id=self.spec.model_id, status="ready", audio=AUDIO,
        )

    @patch("study.french_audio.synthesize")
    def test_voice_change_reuses_owned_scope_without_pin_queue_or_spend(self, provider):
        source = {"grant": source_grant(self.text, self.user.pk, private=False)}
        with self.settings(ELEVENLABS_VOICE_ID="NewVoice", ELEVENLABS_PIN=""):
            reply = self.client.post(reverse("study:french_audio_resolve"), {
                "sources": [source], "prepare": True, "confirm_cost": True,
            }, content_type="application/json")
            self.assertEqual(reply.status_code, 200, reply.content)
            self.assertEqual(reply.json()["state"], "ready")
            self.assertIn(self.recording.pk, reply.json()["url"])
            self.assertEqual(self.client.get(reply.json()["url"]).content, AUDIO)
            self.assertEqual(enqueue(speech_spec(self.text), self.user.pk, None).pk, self.recording.pk)
        self.assertFalse(FrenchNarrationBudget.objects.exists())
        provider.assert_not_called()

    @patch("study.french_audio.synthesize")
    def test_pending_duplicate_does_not_spend_after_another_voice_is_already_saved(self, provider):
        with self.settings(ELEVENLABS_VOICE_ID="NewVoice"):
            current = speech_spec(self.text)
            pending = FrenchNarration.objects.create(
                pk=current.fingerprint, text=self.text, voice_id=current.voice_id,
                model_id=current.model_id, requested_by=self.user,
            )
            self.assertFalse(generate_prepared(pending.pk))
        self.assertEqual(FrenchNarrationBudget.objects.get().reserved_characters, 0)
        provider.assert_not_called()
