"""Continuous reading lists only compatible cached audio, never paid work."""

from dataclasses import asdict
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from study.eo3_audio import narration_spec
from study.models import EO3Narration, FrenchNarration, FrenchNarrationBudget, PersonalResponse, Prompt
from study.oral_history import preferred_personal, preferred_personals
from study.response_personalization import effective_response
from study.routing import prompt_detail_url
from study.tache_three_models import reviewed_model
from . import factories
from .test_eo3_audio import AUDIO, AUDIO_SETTINGS


CACHED_SETTINGS = {
    **AUDIO_SETTINGS,
    "ELEVENLABS_API_KEY": "",
    "ELEVENLABS_PIN": "",
    "FRENCH_AUDIO_GENERATION_ENABLED": False,
    "FRENCH_AUDIO_CHARACTER_BUDGET": 0,
}


@override_settings(**CACHED_SETTINGS)
class CachedReaderTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("import_content", stdout=StringIO())
        cls.user = factories.make_user("cached-reader")
        cls.other = factories.make_user("other-cached-reader")
        ordered = Prompt.objects.filter(
            theme__slug="culture", is_active=True, response__is_active=True,
        ).select_related("theme__task__part", "response__semantic_owner").order_by(
            "family__order", "family__name", "number", "pk",
        )
        representatives = {}
        for prompt in ordered:
            representatives.setdefault(prompt.response_id, prompt)
        cls.prompts = list(representatives.values())

    def setUp(self):
        self.client.force_login(self.user)

    def url(self, prompt):
        return reverse("study:eo3_audio_playlist", args=[prompt.pk])

    def cache(self, prompt, personal=None, owner=None, audio=AUDIO):
        model = reviewed_model(prompt.response, prompt)
        value = effective_response(prompt.response, owner, personal=personal) if personal else None
        spec = narration_spec(model, value, owner.pk if value is not None else None)
        EO3Narration.objects.create(
            fingerprint=spec.fingerprint, group=spec.group,
            voice_id=spec.voice_id, model_id=spec.model_id, audio=audio,
        )
        return spec

    def edit(self, prompt, user):
        content = reviewed_model(prompt.response, prompt).response
        return PersonalResponse.objects.create(
            user=user, response=prompt.response, source_prompt=prompt,
            reformulation=content.reformulation, position=content.position,
            position_claire="Une introduction personnelle unique.",
            arguments=[asdict(argument) for argument in content.arguments],
            nuance=content.nuance, conclusion=content.conclusion,
        )

    @patch("study.french_audio.generate_prepared")
    @patch("study.eo3_audio.synthesize")
    def test_current_theme_current_position_order_and_no_generation(self, provider, prepare):
        self.cache(self.prompts[0])
        self.cache(self.prompts[1])
        self.cache(self.prompts[3])
        other = Prompt.objects.select_related("response", "theme__task__part").filter(
            theme__task__part__slug="eo", theme__task__slug="tache-3",
            is_active=True, response__is_active=True,
        ).exclude(response_id__in=[p.response_id for p in self.prompts]).first()
        self.cache(other)
        with CaptureQueriesContext(connection) as queries:
            reply = self.client.get(self.url(self.prompts[1]))
        self.assertEqual(reply.status_code, 200, reply.content)
        data = reply.json()
        self.assertEqual(data["theme"], "Culture")
        self.assertEqual(data["start_position"], 2)
        self.assertEqual(data["total_subjects"], len(self.prompts))
        self.assertEqual([track["position"] for track in data["tracks"]], [2, 4])
        self.assertEqual([track["source_url"] for track in data["tracks"]], [
            prompt_detail_url(self.prompts[1]), prompt_detail_url(self.prompts[3]),
        ])
        self.assertLessEqual(len(queries), 6)
        selected_columns = "\n".join(q["sql"].partition(" FROM ")[0] for q in queries)
        self.assertNotIn('"model_content"', selected_columns)
        self.assertNotIn('"audio"', selected_columns)
        self.assertEqual(reply["Cache-Control"], "private, no-store")
        self.assertFalse(FrenchNarration.objects.exists())
        self.assertFalse(FrenchNarrationBudget.objects.exists())
        provider.assert_not_called()
        prepare.assert_not_called()

    def test_no_recordings_empty_recordings_and_outdated_recordings_are_skipped(self):
        empty = self.cache(self.prompts[0], audio=b"")
        old = self.cache(self.prompts[1])
        EO3Narration.objects.filter(pk=old.fingerprint).update(fingerprint="0" * 64)
        data = self.client.get(self.url(self.prompts[0])).json()
        self.assertEqual(data["tracks"], [])
        self.assertTrue(EO3Narration.objects.filter(pk=empty.fingerprint).exists())

    def test_private_copy_never_falls_back_to_the_public_recording(self):
        prompt = self.prompts[0]
        self.cache(prompt)
        personal = self.edit(prompt, self.user)
        self.assertEqual(self.client.get(self.url(prompt)).json()["tracks"], [])
        own = self.cache(prompt, personal, self.user)
        reply = self.client.get(self.url(prompt))
        self.assertEqual(len(reply.json()["tracks"]), 1)
        self.assertIn(own.fingerprint, reply.json()["tracks"][0]["audio_url"])
        self.assertNotIn(personal.position_claire, reply.content.decode())

    def test_another_users_private_recording_is_not_listed(self):
        prompt = self.prompts[0]
        personal = self.edit(prompt, self.other)
        self.cache(prompt, personal, self.other)
        self.assertEqual(self.client.get(self.url(prompt)).json()["tracks"], [])

    def test_explicit_model_reset_uses_the_public_cache(self):
        prompt = self.prompts[0]
        public = self.cache(prompt)
        personal = self.edit(prompt, self.user)
        personal.is_active = False
        personal.save(update_fields=["is_active"])
        tracks = self.client.get(self.url(prompt)).json()["tracks"]
        self.assertEqual(len(tracks), 1)
        self.assertIn(public.fingerprint, tracks[0]["audio_url"])

    def test_aliases_follow_the_same_deduplication_option_as_sujet_navigation(self):
        alias = Prompt.objects.filter(
            theme=self.prompts[0].theme, is_active=True,
        ).exclude(pk__in=[p.pk for p in self.prompts]).select_related(
            "response", "theme__task__part",
        ).first()
        self.assertIsNotNone(alias)
        spec = self.cache(alias)
        deduplicated = self.client.get(self.url(alias)).json()
        self.assertEqual(len(deduplicated["tracks"]), 1)
        expanded = self.client.get(self.url(alias), {"deduplicate": "0"}).json()
        self.assertGreater(expanded["total_subjects"], deduplicated["total_subjects"])
        self.assertTrue(all("deduplicate=0" in t["source_url"] for t in expanded["tracks"]))
        self.assertTrue(all(spec.fingerprint in t["audio_url"] for t in expanded["tracks"]))

    def test_login_feature_flag_and_method_are_enforced(self):
        url = self.url(self.prompts[0])
        self.assertEqual(self.client.post(url, {}).status_code, 405)
        with self.settings(EO3_AUDIO_ENABLED=False):
            self.assertEqual(self.client.get(url).status_code, 404)
        self.client.logout()
        self.assertEqual(self.client.get(url).status_code, 302)

    @override_settings(ELEVENLABS_VOICE_ID="")
    def test_invalid_voice_configuration_is_explicit(self):
        reply = self.client.get(self.url(self.prompts[0]))
        self.assertEqual(reply.status_code, 503)
        self.assertIn("ELEVENLABS_VOICE_ID", reply.json()["message"])


class BatchedPreferredPersonalTests(TestCase):
    def test_batch_matches_single_lookup_with_history_resets_and_ordinary_sources(self):
        user = factories.make_user("batch-personals")
        owner = factories.make_response()
        owner.semantic_group = "eo/tache-3/batch-owner"
        owner.save(update_fields=["semantic_group"])
        previous = factories.make_response(theme=owner.theme)
        previous.semantic_group = owner.semantic_group
        previous.semantic_owner = owner
        previous.save(update_fields=["semantic_group", "semantic_owner"])
        plain = factories.make_response(theme=owner.theme)
        PersonalResponse.objects.create(user=user, response=previous, is_active=True)
        reset = PersonalResponse.objects.create(user=user, response=owner, is_active=False)
        PersonalResponse.objects.create(
            user=user, response=plain, source_prompt=owner.prompts.first(),
        )
        responses = list(type(owner).objects.filter(pk__in=[
            owner.pk, previous.pk, plain.pk,
        ]).select_related("semantic_owner"))
        for reset_active in (False, True):
            reset.is_active = reset_active
            reset.save(update_fields=["is_active"])
            expected = {response.pk: preferred_personal(response, user) for response in responses}
            with self.assertNumQueries(1):
                actual = preferred_personals(responses, user)
            self.assertEqual(
                {key: value.pk if value else None for key, value in actual.items()},
                {key: value.pk if value else None for key, value in expected.items()},
            )
