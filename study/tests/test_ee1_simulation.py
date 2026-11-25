import json
from contextlib import nullcontext
from datetime import timedelta
from unittest.mock import patch

from django.conf import settings
from django.db import connection
from django.test import Client, TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from study.catalogue.loader import _ee_word_count
from study.models import (
    WritingSimulationAttempt,
    WritingSimulationAttemptStatus,
    WritingSimulationEvaluationStatus,
    WritingSujetCompletion,
)
from study.simulation import evaluation, writing_evaluation
from study.simulation.evidence import number_passages
from study.views import writing_simulation

from . import factories


class EE1SimulationTests(TestCase):
    spec = writing_simulation.SPECS[1]
    workers_account_id = "0123456789abcdef" * 2

    def setUp(self):
        self.part = factories.make_part("ee")
        self.task = factories.make_task(self.part, "tache-1")
        self.sujet = factories.make_writing_sujet(
            self.task,
            slug="invitation",
            prompt="Invitez votre amie à une fête et donnez-lui les informations utiles.",
            order=1,
        )
        self.other_sujet = factories.make_writing_sujet(
            self.task,
            slug="sortie",
            category="sorties",
            category_label="Sorties",
            prompt="Proposez une sortie à votre collègue.",
            order=2,
        )
        self.owner = factories.make_user("ee1-simulation-owner")
        self.other = factories.make_user("ee1-simulation-other")
        self.client.force_login(self.owner)

    def _setup_url(self):
        return reverse("study:ee1_simulation")

    def _start_url(self):
        return reverse("study:ee1_simulation_start")

    def _attempt_url(self, attempt):
        return reverse("study:ee1_simulation_attempt", args=[attempt.pk])

    def _revision(self, attempt):
        return self.client.get(self._attempt_url(attempt)).context["draft_revision"]

    def test_subject_picker_reuses_directory_controls_and_filters_private_sessions(self):
        response = self.client.get(reverse("study:ee1_subject_picker"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_nav_area"], "simulation")
        self.assertContains(response, f'<a href="{reverse("study:simulation")}">Simulation</a>', html=True)
        self.assertContains(response, f'<a href="{reverse("study:simulation_track", args=["ee"])}">EE</a>', html=True)
        self.assertContains(response, f'<strong aria-current="page">{self.task.name}</strong>', html=True)
        self.assertContains(response, "Choisir un sujet")
        self.assertContains(response, "Rechercher un sujet ou un thème")
        self.assertContains(response, "Sans séance")
        self.assertContains(response, self.sujet.prompt)
        self.assertContains(
            response,
            f'href="{reverse("study:ee1_simulation")}?sujet_id={self.sujet.pk}"',
        )
        self.assertContains(response, 'aria-label="Pratiquer :')
        self.assertContains(response, 'data-writing-sujet-completion-form')
        self.assertContains(response, "subject-progress.js")
        self.assertContains(response, 'name="theme" data-custom-select data-auto-submit')
        self.assertContains(response, 'name="etat" data-custom-select data-auto-submit')
        self.assertContains(response, 'name="tri" data-custom-select data-auto-submit')
        self.assertNotContains(response, ">Choisir</a>")
        self.assertNotContains(response, ">Choisir</button>")
        self.assertNotContains(response, ">Action<")
        fragment = self.client.get(
            reverse("study:ee1_subject_picker"),
            headers={"x-requested-with": "fetch"},
        )
        self.assertContains(fragment, 'id="ee1-topic-results"')
        self.assertNotContains(fragment, "<html")

        self.client.post(self._start_url(), {"sujet_id": str(self.sujet.pk)})
        response = self.client.get(
            reverse("study:ee1_subject_picker") + "?etat=new"
        )
        self.assertNotContains(response, self.sujet.prompt)
        self.assertContains(response, self.other_sujet.prompt)

        response = self.client.get(
            reverse("study:ee1_subject_picker") + "?q=SORTIES&tri=az"
        )
        self.assertContains(response, self.other_sujet.prompt)
        self.assertNotContains(response, self.sujet.prompt)
        self.assertEqual(response.context["directory_selection"]["order"], "az")

        self.client.force_login(self.other)
        response = self.client.get(reverse("study:ee1_subject_picker"))
        self.assertTrue(all(row["count"] == 0 for row in response.context["page"]))

    def test_subject_picker_deduplicates_equivalent_subjects_and_keeps_canonical_completion(self):
        WritingSujetCompletion.objects.create(user=self.owner, sujet=self.sujet)
        with patch(
            "study.views.writing_simulation.content_module.ee_writing_canonical_slug_by_slug",
            return_value={
                self.sujet.slug: self.sujet.slug,
                self.other_sujet.slug: self.sujet.slug,
            },
        ):
            url = reverse("study:ee1_subject_picker")
            response = self.client.get(url)
            publications = self.client.get(url, {"deduplicate": "0"})
            filtered = self.client.get(url, {"q": self.other_sujet.prompt}, headers={"x-requested-with": "fetch"})

        self.assertEqual(response.context["total"], 1)
        self.assertTemplateUsed(response, "study/shared/partials/subject_deduplication_toggle.html")
        self.assertContains(response, 'aria-checked="true"', count=1)
        self.assertNotContains(response, self.other_sujet.prompt)
        self.assertContains(publications, 'aria-checked="true"', count=2)
        self.assertContains(publications, f"sujet_id={self.other_sujet.pk}&amp;deduplicate=0")
        self.assertContains(
            publications,
            f'data-writing-sujet-id="{self.sujet.pk}"',
            count=2,
        )
        self.assertContains(filtered, self.other_sujet.prompt)
        self.assertNotContains(filtered, self.sujet.prompt)

    def test_subject_picker_loads_progress_for_the_visible_page(self):
        for index in range(16):
            factories.make_writing_sujet(self.task, slug=f"invit-{index}", prompt=f"Événement {index:02}", order=index + 3)
        with patch.object(
            writing_simulation, "writing_sujet_progress_by_id", wraps=writing_simulation.writing_sujet_progress_by_id,
        ) as progress:
            page = self.client.get(reverse("study:ee1_subject_picker"), {"q": "evenement", "tri": "za", "page": 2})
        row, = page.context["page"]
        self.assertEqual(row["title"], "Événement 00")
        self.assertEqual(progress.call_args.args[1], {row["subject_id"]})

    @override_settings(EE1_SIMULATION_MINUTES=12)
    def test_setup_reuses_the_shared_session_page(self):
        response = self.client.get(self._setup_url())

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["active_nav_area"], "simulation")
        self.assertContains(response, 'class="lv-studio ee1-session"')
        self.assertContains(response, "Studio écrit · EE Tâche 1")
        self.assertContains(response, "Expression écrite")
        self.assertContains(response, 'data-step="live"')
        self.assertContains(response, "Rédaction")
        self.assertContains(response, "60–120 mots")
        self.assertContains(response, "12 min")
        self.assertContains(response, 'name="sujet_id"')

    def test_selected_subject_uses_the_study_navigation_with_simulation_destinations(self):
        next_sujet = factories.make_writing_sujet(
            self.task, slug="anniversaire", category=self.sujet.category, order=self.sujet.order + 1,
        )
        alias = factories.make_writing_sujet(
            self.task, slug="invitation-variante", category=self.sujet.category, order=self.sujet.order + 2,
        )
        with patch.object(
            writing_simulation.content_module, "ee_writing_canonical_slug_by_slug", return_value={alias.slug: self.sujet.slug},
        ):
            setup = self.client.get(self._setup_url(), {"sujet_id": self.sujet.pk})
            equivalent = self.client.get(self._setup_url(), {"sujet_id": alias.pk})
        self.assertEqual(equivalent.context["session_subject_nav"]["total"], 2)
        self.assertEqual(equivalent.context["session_subject_nav"]["choices"][0]["label"], alias.prompt)
        for component in ("task_breadcrumb", "subject_back", "subject_navigation"):
            self.assertTemplateUsed(setup, f"study/expression/partials/{component}.html")
        nav = setup.context["session_subject_nav"]
        self.assertEqual((nav["position"], nav["total"]), (1, 2))
        self.assertIsNone(nav["previous"])
        self.assertEqual(nav["next"]["url"], reverse("study:ee1_simulation", query={"sujet_id": next_sujet.pk}))
        self.assertContains(setup, 'data-short-label="Sujet 1 sur 2"')
        self.assertNotContains(setup, self.other_sujet.prompt)
        self.assertEqual(
            setup.context["session_back_url"], reverse("study:ee1_subject_picker", query={"theme": self.sujet.category}),
        )
        self.client.post(self._start_url(), {"sujet_id": self.sujet.pk})
        attempt = WritingSimulationAttempt.objects.get(user=self.owner)
        legacy = {key: value for key, value in attempt.snapshot.items() if key != "category"}
        WritingSimulationAttempt.objects.filter(pk=attempt.pk).update(snapshot=legacy)
        with patch.object(
            writing_simulation.content_module, "ee_writing_canonical_slug_by_slug", return_value={alias.slug: self.sujet.slug},
        ):
            self.assertEqual(self.client.get(self._attempt_url(attempt)).context["session_subject_nav"], nav)

    def test_saved_sessions_match_the_selected_subject_and_can_only_be_deleted_by_the_owner(self):
        self.client.post(self._start_url(), {"sujet_id": self.sujet.pk})
        mine = WritingSimulationAttempt.objects.get(user=self.owner)
        sibling = factories.make_writing_sujet(self.task, slug="another-invitation", category=self.sujet.category)
        unrelated = WritingSimulationAttempt.objects.create(
            user=self.owner, task=self.task, sujet=sibling, deadline_at=mine.deadline_at,
        )
        other = WritingSimulationAttempt.objects.create(
            user=self.other, task=self.task, sujet=self.sujet, deadline_at=mine.deadline_at,
        )
        self.client.post(self._attempt_url(mine), {
            "action": "submit", "body": " ".join(["Bonjour"] * 60), "draft_revision": self._revision(mine),
        })
        completion = WritingSujetCompletion.objects.create(user=self.owner, sujet=self.sujet)
        query = {"sujet_id": self.sujet.pk}
        setup = reverse("study:ee1_simulation", query=query)
        delete = reverse("study:ee1_simulation_delete", query=query)
        guarded = Client(enforce_csrf_checks=True)
        guarded.force_login(self.owner)
        page = guarded.get(setup)
        self.assertTemplateUsed(page, "study/simulation/partials/saved_sessions.html")
        self.assertContains(page, f'action="{delete}"')
        self.assertContains(page, 'data-icon="trash"', count=1)
        self.assertContains(page, "Sans bilan")
        self.assertNotContains(page, "Remise")
        self.assertNotContains(page, self._attempt_url(other))
        self.assertNotContains(page, self._attempt_url(unrelated))
        self.assertContains(guarded.get(self._setup_url()), self._attempt_url(unrelated))

        WritingSimulationAttempt.objects.filter(pk=mine.pk).update(
            evaluation_status=WritingSimulationEvaluationStatus.UNAVAILABLE,
            evaluation={"provider": "gemini", "reports": {"groq": {"score": 12}}},
        )
        self.assertContains(guarded.get(setup), "Bilan disponible")
        self.assertEqual(guarded.get(delete).status_code, 405)
        self.assertEqual(guarded.post(delete, {"simulation": mine.pk}).status_code, 403)
        csrf = guarded.cookies["csrftoken"].value
        self.assertEqual(guarded.post(delete, {"simulation": other.pk, "csrfmiddlewaretoken": csrf}).status_code, 404)
        self.assertEqual(self.client.post(reverse("study:ee2_simulation_delete"), {"simulation": mine.pk}).status_code, 404)
        self.assertRedirects(guarded.post(delete, {"simulation": mine.pk, "csrfmiddlewaretoken": csrf}), setup)
        self.assertFalse(WritingSimulationAttempt.objects.filter(pk=mine.pk).exists())
        self.assertTrue(WritingSimulationAttempt.objects.filter(pk=unrelated.pk).exists())
        self.assertTrue(WritingSimulationAttempt.objects.filter(pk=other.pk).exists())
        self.assertTrue(WritingSujetCompletion.objects.filter(pk=completion.pk).exists())

    @override_settings(EE1_SIMULATION_MINUTES=7)
    def test_duration_is_configurable_for_new_sessions(self):
        response = self.client.get(self._setup_url())
        self.assertContains(response, "7 min")

        self.client.post(self._start_url(), {"sujet_id": str(self.sujet.pk)})
        attempt = WritingSimulationAttempt.objects.get(user=self.owner)
        self.assertEqual(attempt.snapshot["simulation_minutes"], 7)
        self.assertEqual(
            attempt.deadline_at - attempt.started_at,
            timedelta(minutes=7),
        )

    def test_subject_page_links_to_the_same_subject_in_simulation(self):
        response = self.client.get(
            reverse("study:writing_sujet_detail", args=["ee", "tache-1", self.sujet.pk])
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f"?sujet_id={self.sujet.pk}")
        self.assertContains(response, "Lancer la simulation écrite")

    def test_start_freezes_selected_prompt_and_keeps_attempt_private(self):
        response = self.client.post(
            self._start_url(),
            {"sujet_id": str(self.sujet.pk)},
        )

        attempt = WritingSimulationAttempt.objects.get(user=self.owner)
        self.assertRedirects(response, self._attempt_url(attempt))
        self.assertEqual(attempt.snapshot["prompt"], self.sujet.prompt)
        self.assertEqual(attempt.snapshot["word_min"], 60)
        self.assertEqual(
            attempt.snapshot["simulation_minutes"],
            settings.EE1_SIMULATION_MINUTES,
        )
        self.assertEqual(attempt.status, WritingSimulationAttemptStatus.ACTIVE)

        self.client.force_login(self.other)
        self.assertEqual(self.client.get(self._attempt_url(attempt)).status_code, 404)

    def test_attempt_editor_disables_correction_and_exposes_french_character_tools(self):
        self.client.post(self._start_url(), {"sujet_id": str(self.sujet.pk)})
        attempt = WritingSimulationAttempt.objects.get(user=self.owner)
        response = self.client.get(self._attempt_url(attempt))

        self.assertContains(response, 'class="lv-studio ee1-session ee1-simulation ee1-simulation--attempt"')
        self.assertContains(response, "Studio écrit · EE Tâche 1")
        self.assertContains(response, 'data-step="live"')
        self.assertContains(response, 'spellcheck="false"')
        self.assertContains(response, 'autocorrect="off"')
        self.assertContains(response, 'data-gramm="false"')
        self.assertContains(response, 'class="ee1-writing-textarea"')
        self.assertContains(response, 'maxlength="20000"')
        self.assertContains(response, "Caractères français")
        self.assertContains(response, 'data-ee1-character="é"')
        self.assertContains(response, 'data-writing-word-count-display')

    def test_submission_requires_word_limit_then_shows_private_bilan(self):
        self.client.post(self._start_url(), {"sujet_id": str(self.sujet.pk)})
        attempt = WritingSimulationAttempt.objects.get(user=self.owner)
        revision = self._revision(attempt)
        response = self.client.post(
            self._attempt_url(attempt),
            {"action": "submit", "body": "Trop court.", "draft_revision": revision},
        )

        self.assertEqual(response.status_code, 400)
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, WritingSimulationAttemptStatus.ACTIVE)
        self.assertContains(response, "entre 60 et 120 mots", status_code=400)

        body = " ".join(["Bonjour"] * 60)
        response = self.client.post(
            self._attempt_url(attempt),
            {"action": "submit", "body": body, "draft_revision": revision},
        )

        self.assertRedirects(response, self._attempt_url(attempt))
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, WritingSimulationAttemptStatus.SUBMITTED)
        self.assertEqual(attempt.word_count, 60)
        result = self.client.get(self._attempt_url(attempt))
        self.assertTemplateUsed(result, "study/simulation/partials/session_header.html")
        self.assertTemplateUsed(result, "study/simulation/partials/session_status.html")
        self.assertContains(result, 'tabindex="-1">Simulation</h1>')
        self.assertContains(result, ">Votre bilan</p>")
        self.assertContains(result, ">Séance enregistrée.</p>")
        self.assertContains(result, self.sujet.prompt)
        self.assertNotContains(result, "Une lecture concise")
        self.assertContains(result, "60 / 60–120")
        self.assertContains(result, 'class="lv-studio ee1-session"')
        self.assertContains(result, 'class="lv-track"')
        self.assertContains(result, 'data-icon="target"')
        self.assertContains(result, 'data-icon="reset"')
        self.assertContains(result, 'data-icon="book-open"')
        exported = self.client.get(reverse("study:export_account")).json()
        self.assertEqual(len(exported["ee1_simulation_attempts"]), 1)
        self.assertEqual(
            exported["ee1_simulation_attempts"][0]["id"],
            str(attempt.pk),
        )

    @override_settings(GROQ_API_KEY="fixture-groq-key")
    def test_overtime_keeps_the_editor_and_requires_manual_submission(self):
        self.client.post(self._start_url(), {"sujet_id": ""})
        attempt = WritingSimulationAttempt.objects.get(user=self.owner)
        draft = "Un brouillon encore incomplet."
        response = self.client.post(
            self._attempt_url(attempt),
            {"action": "save", "body": draft, "evaluation_consent": "groq", "draft_revision": self._revision(attempt)},
        )
        self.assertRedirects(response, self._attempt_url(attempt) + "?saved=1")

        attempt.refresh_from_db()
        attempt.deadline_at = timezone.now() - timedelta(seconds=12)
        attempt.save(update_fields=["deadline_at"])
        url = self._attempt_url(attempt)
        editor = self.client.get(url)
        self.assertTemplateUsed(editor, "study/simulation/writing_simulation_attempt.html")
        self.assertLess(editor.context["remaining_seconds"], 0)
        self.assertEqual((editor.context["remaining_minutes"], editor.context["remaining_second_remainder"]), (0, 0))
        self.assertEqual(self.client.get(reverse("study:ee1_simulation_evaluate", args=[attempt.pk])).status_code, 400)
        revision = editor.context["draft_revision"]

        with patch("study.views.writing_simulation.threading.Thread") as thread, self.captureOnCommitCallbacks(execute=True):
            rejected = self.client.post(url, {
                "action": "submit", "body": draft, "evaluation_consent": "groq", "draft_revision": revision,
            })
            self.assertContains(rejected, "entre 60 et 120 mots", status_code=400)
            thread.assert_not_called()
            attempt.refresh_from_db()
            self.assertEqual(attempt.status, WritingSimulationAttemptStatus.ACTIVE)
            self.assertIsNone(attempt.submitted_at)
            self.assertEqual(attempt.body, draft)

            body = " ".join(["Bonjour"] * 60)
            response = self.client.post(url, {
                "action": "submit", "body": body, "evaluation_consent": "groq", "draft_revision": revision,
            })
            self.assertRedirects(response, url, fetch_redirect_response=False)
        thread.assert_called_once()
        attempt.refresh_from_db()
        self.assertEqual(attempt.status, WritingSimulationAttemptStatus.SUBMITTED)
        self.assertEqual(attempt.evaluation_status, WritingSimulationEvaluationStatus.PROCESSING)
        self.assertGreater(attempt.submitted_at, attempt.deadline_at)
        self.assertEqual(attempt.body, body)

    def test_legacy_expire_saves_a_draft_without_overwriting_a_newer_one(self):
        self.client.post(self._start_url(), {"sujet_id": self.sujet.pk})
        attempt = WritingSimulationAttempt.objects.get(user=self.owner)
        url = self._attempt_url(attempt) + "?deduplicate=0"
        draft = "Mon brouillon enregistré."
        response = self.client.post(url, {"action": "expire", "body": draft})
        self.assertRedirects(response, self._attempt_url(attempt) + "?saved=1&deduplicate=0")
        stale = self.client.post(url, {"action": "expire", "body": "Le brouillon de l’ancien onglet."})
        self.assertContains(stale, f'href="{url}">Recharger le brouillon enregistré', status_code=409)
        attempt.refresh_from_db()
        self.assertEqual(attempt.body, draft)
        self.assertEqual(attempt.status, WritingSimulationAttemptStatus.ACTIVE)
        self.assertIsNone(attempt.evaluation_started_at)

    @override_settings(
        EE1_EVALUATION_PROVIDER="cloudflare", GROQ_API_KEY="fixture-groq-key",
        CLOUDFLARE_WORKERS_API_KEY="fixture-workers-token", CLOUDFLARE_ACCOUNT_ID=workers_account_id,
    )
    def test_submitting_the_disclosed_form_starts_workers_once_and_saves_the_bilan(self):
        self.client.post(self._start_url(), {"sujet_id": self.sujet.pk})
        attempt = WritingSimulationAttempt.objects.get(user=self.owner)
        url = self._attempt_url(attempt)
        page = self.client.get(url)
        self.assertContains(page, "Envoi à Workers : réponse, consigne.")
        self.assertContains(page, 'name="evaluation_consent" value="cloudflare"')
        revision = page.context["draft_revision"]

        with patch("study.views.writing_simulation.threading.Thread") as thread, self.captureOnCommitCallbacks(execute=True):
            rejected = self.client.post(url, {
                "action": "submit", "body": "Trop court.", "evaluation_consent": "cloudflare", "draft_revision": revision,
            })
            self.assertEqual(rejected.status_code, 400)
            data = {
                "action": "submit", "body": "  " + " ".join(["Bonjour"] * 60) + "\n",
                "evaluation_consent": "cloudflare", "draft_revision": revision,
            }
            self.assertRedirects(self.client.post(url, data), url, fetch_redirect_response=False)
            self.assertRedirects(self.client.post(url, data), url, fetch_redirect_response=False)

        attempt.refresh_from_db()
        self.assertEqual(attempt.evaluation_status, WritingSimulationEvaluationStatus.PROCESSING)
        self.assertEqual(attempt.evaluation, {"provider": "cloudflare", "reports": {}})
        thread.assert_called_once_with(
            target=writing_simulation.run_evaluation,
            args=(attempt.pk, attempt.evaluation_started_at, self.spec, "cloudflare"),
            daemon=True,
        )
        self.assertContains(self.client.get(url), 'data-evaluation-provider="cloudflare"')
        bilan = reverse("study:ee1_simulation_evaluate", args=[attempt.pk])
        with CaptureQueriesContext(connection) as reads:
            status = self.client.get(bilan)
        self.assertEqual(status.json()["status"], "processing")
        attempt_query, = [query["sql"] for query in reads if WritingSimulationAttempt._meta.db_table in query["sql"]]
        for field in ("body", "position_body", "snapshot"):
            self.assertNotIn(f'"{field}"', attempt_query)
        busy = self.client.post(bilan, data={"consent": True, "provider": "groq"}, content_type="application/json")
        self.assertEqual(busy.status_code, 409)

        report = {**self._provider_report(), "gradeEvidenceIds": []}
        reply = json.dumps(self._workers_reply(json.dumps(report))).encode()
        with patch.object(evaluation, "_post", return_value=(reply, 86)) as call:
            writing_simulation.run_evaluation(*thread.call_args.kwargs["args"])
        call.assert_called_once()
        request = json.loads(call.call_args.args[0])
        packet = json.loads(request["messages"][1]["content"])
        self.assertEqual(packet["response"], data["body"])
        grounded = self.client.get(bilan).json()
        self.assertEqual(grounded["status"], "ready")
        self.assertEqual(grounded["report"]["score"], 12)
        self.assertTrue(data["body"].lstrip().startswith(grounded["report"]["gradeEvidence"][0]))

    @override_settings(EE1_EVALUATION_PROVIDER="gemini", GEMINI_API_KEY="fixture-gemini-key", GROQ_API_KEY="")
    def test_evaluation_requires_consent_for_the_disclosed_provider_and_claims_once(self):
        self.client.post(self._start_url(), {"sujet_id": str(self.sujet.pk)})
        attempt = WritingSimulationAttempt.objects.get(user=self.owner)
        body = " ".join(["Bonjour"] * 60)
        page = self.client.get(self._attempt_url(attempt))
        self.assertContains(page, 'name="evaluation_consent" value="gemini"')
        self.client.post(self._attempt_url(attempt), {
            "action": "submit", "body": body, "evaluation_consent": "groq", "draft_revision": page.context["draft_revision"],
        })

        evaluation_url = reverse("study:ee1_simulation_evaluate", args=[attempt.pk])
        self.assertContains(self.client.get(self._attempt_url(attempt)), "Envoi à Gemini : réponse, consigne.")
        self.assertEqual(self.client.post(evaluation_url, content_type="application/json", data="{}").status_code, 400)
        with patch("study.views.writing_simulation.threading.Thread") as thread:
            for consent in ({"consent": True}, {"consent": True, "provider": "groq"}):
                rejected = self.client.post(evaluation_url, data=consent, content_type="application/json")
                self.assertEqual(rejected.status_code, 409)
            attempt.refresh_from_db()
            self.assertEqual(attempt.evaluation_status, WritingSimulationEvaluationStatus.NOT_REQUESTED)
            with self.captureOnCommitCallbacks(execute=True):
                response = self.client.post(
                    evaluation_url,
                    data={"consent": True, "provider": "gemini"},
                    content_type="application/json",
                )
        self.assertEqual(response.status_code, 202)
        attempt.refresh_from_db()
        self.assertEqual(attempt.evaluation_status, "processing")
        thread.assert_called_once()

    @override_settings(
        EE1_EVALUATION_PROVIDER="gemini", GEMINI_API_KEY="fixture-gemini-key", GROQ_API_KEY="fixture-groq-key",
    )
    def test_selecting_a_second_model_preserves_the_original_report(self):
        self.client.post(self._start_url(), {"sujet_id": self.sujet.pk})
        attempt = WritingSimulationAttempt.objects.get(user=self.owner)
        attempt.body = " ".join(["Bonjour"] * 60)
        attempt.status = WritingSimulationAttemptStatus.SUBMITTED
        attempt.evaluation_status = WritingSimulationEvaluationStatus.READY
        attempt.evaluation = {"score": 9}
        attempt.save(update_fields=["body", "status", "evaluation_status", "evaluation"])
        url = reverse("study:ee1_simulation_evaluate", args=[attempt.pk])
        with self.settings(CLOUDFLARE_WORKERS_API_KEY="fixture-workers-token", CLOUDFLARE_ACCOUNT_ID=""):
            self.assertNotContains(self.client.get(self._attempt_url(attempt)), "Évaluer avec Workers")
            unavailable = self.client.post(
                url, data={"consent": True, "provider": "cloudflare"}, content_type="application/json",
            )
            self.assertEqual(unavailable.status_code, 409)
        with self.settings(CLOUDFLARE_WORKERS_API_KEY="fixture-workers-token", CLOUDFLARE_ACCOUNT_ID=self.workers_account_id):
            page = self.client.get(self._attempt_url(attempt))
            self.assertContains(page, "Évaluer avec Workers")
            self.assertNotContains(page, settings.CLOUDFLARE_WORKERS_API_KEY)
        self.assertEqual(self.client.get(url, {"provider": "groq"}).json()["report"], {"score": 9})
        self.assertEqual(self.client.get(url, {"provider": "gemini"}).json()["status"], "not_requested")

        with patch("study.views.writing_simulation.threading.Thread") as thread, self.captureOnCommitCallbacks(execute=True):
            claim = self.client.post(url, data={"consent": True, "provider": "gemini"}, content_type="application/json")
        self.assertEqual(claim.status_code, 202)
        attempt.refresh_from_db()
        thread.assert_called_once()
        self.assertEqual(thread.call_args.kwargs["args"][-1], "gemini")
        self.assertEqual(self.client.get(url, {"provider": "groq"}).json()["report"], {"score": 9})

        with patch.object(writing_evaluation, "score", return_value={"score": 11}) as score:
            writing_simulation.run_evaluation(attempt.pk, attempt.evaluation_started_at, self.spec, "groq")
            score.assert_not_called()
            writing_simulation.run_evaluation(attempt.pk, attempt.evaluation_started_at, self.spec, "gemini")
        self.assertEqual(score.call_args.kwargs["provider"], "gemini")
        self.assertContains(self.client.get(self._attempt_url(attempt)), 'data-evaluation-provider="groq"')
        self.assertEqual(self.client.get(url).json()["report"], {"score": 9})

        with self.settings(GEMINI_API_KEY=""), patch("study.views.writing_simulation.threading.Thread") as thread:
            with self.captureOnCommitCallbacks(execute=True):
                for provider, expected in (("gemini", 11), ("groq", 9)):
                    cached = self.client.post(url, data={"consent": True, "provider": provider}, content_type="application/json")
                    self.assertEqual(cached.json()["report"], {"score": expected})
            thread.assert_not_called()

        WritingSimulationAttempt.objects.filter(pk=attempt.pk).update(
            evaluation={"provider": "gemini", "reports": {"gemini": {"score": 11}}},
        )
        self.assertEqual(self.client.get(url).json()["report"], {"score": 11})

    @override_settings(EE1_EVALUATION_PROVIDER="groq")
    def test_evaluation_worker_persists_ready_report_only_for_its_claim(self):
        self.client.post(self._start_url(), {"sujet_id": str(self.sujet.pk)})
        attempt = WritingSimulationAttempt.objects.get(user=self.owner)
        attempt.body = " ".join(["Bonjour"] * 60)
        attempt.status = WritingSimulationAttemptStatus.SUBMITTED
        attempt.word_count = 60
        started_at = timezone.now()
        attempt.evaluation_status = WritingSimulationEvaluationStatus.PROCESSING
        attempt.evaluation_started_at = started_at
        attempt.save(
            update_fields=[
                "body",
                "status",
                "word_count",
                "evaluation_status",
                "evaluation_started_at",
            ]
        )

        with (
            patch.object(writing_evaluation, "score", return_value={"cefr": "B2", "score": 12}),
            self.assertLogs(writing_simulation.logger, "INFO") as logs,
        ):
            writing_simulation.run_evaluation(attempt.pk, started_at, self.spec)

        self.assertRegex(
            logs.output[-1],
            rf"writing evaluation ready task=ee1 provider=groq attempt={attempt.pk} elapsed_ms=\d+$",
        )
        attempt.refresh_from_db()
        self.assertEqual(attempt.evaluation_status, WritingSimulationEvaluationStatus.READY)
        self.assertEqual(attempt.evaluation, {"cefr": "B2", "score": 12})
        self.assertEqual(attempt.evaluation_error, "")
        self.assertIsNotNone(attempt.evaluated_at)

        newer_started_at = started_at + timedelta(seconds=1)
        attempt.evaluation_status = WritingSimulationEvaluationStatus.PROCESSING
        attempt.evaluation_started_at = newer_started_at
        attempt.evaluation = {"new": True}
        attempt.save(update_fields=["evaluation_status", "evaluation_started_at", "evaluation"])
        with patch(
            "study.simulation.writing_evaluation.score",
            return_value={"old": True},
        ):
            writing_simulation.run_evaluation(attempt.pk, started_at, self.spec)
        attempt.refresh_from_db()
        self.assertEqual(attempt.evaluation_status, WritingSimulationEvaluationStatus.PROCESSING)
        self.assertEqual(attempt.evaluation, {"new": True})

    @override_settings(CLOUDFLARE_WORKERS_API_KEY="fixture-workers-token", CLOUDFLARE_ACCOUNT_ID=workers_account_id)
    def test_evaluation_worker_logs_validation_failure_without_private_text(self):
        self.client.post(self._start_url(), {"sujet_id": self.sujet.pk})
        attempt = WritingSimulationAttempt.objects.get(user=self.owner)
        body = "réponseprivée " + " ".join(["à"] * 59)
        self.client.post(self._attempt_url(attempt), {
            "action": "submit", "body": body, "draft_revision": self._revision(attempt),
        })
        url = reverse("study:ee1_simulation_evaluate", args=[attempt.pk])
        claim = self.client.post(url, data={"consent": True, "provider": "cloudflare"}, content_type="application/json")
        self.assertEqual(claim.status_code, 202)
        attempt.refresh_from_db()

        private_citation = "private-model-output"
        report = {**self._provider_report(), "gradeEvidenceIds": [private_citation]}
        reply = json.dumps(self._workers_reply(json.dumps(report))).encode()
        with (
            patch.object(evaluation, "_post", return_value=(reply, 1)),
            self.assertLogs(writing_simulation.logger, "INFO") as logs,
        ):
            writing_simulation.run_evaluation(attempt.pk, attempt.evaluation_started_at, self.spec, "cloudflare")

        context = f"task=ee1 provider=cloudflare attempt={attempt.pk}"
        self.assertTrue(logs.output[0].endswith(f"writing evaluation started {context}"))
        self.assertRegex(
            logs.output[1],
            rf"writing evaluation rejected {context} field=gradeEvidence\.evidence "
            r"reason=no_matching_passages passages=1 elapsed_ms=\d+$",
        )
        for private in ("réponseprivée", self.sujet.prompt, private_citation, settings.CLOUDFLARE_WORKERS_API_KEY):
            self.assertNotIn(private, "\n".join(logs.output))
        payload = self.client.get(url, {"provider": "cloudflare"}).json()
        self.assertEqual(payload["status"], WritingSimulationEvaluationStatus.UNAVAILABLE)
        self.assertIsNone(payload["report"])
        self.assertIn("n’a pas pu être vérifié", payload["error"])
        attempt.refresh_from_db()
        self.assertEqual(attempt.body, body)

    def _provider_report(self):
        return {
            "verdict": "Réponse claire.",
            "score": 12,
            "scoreRange": {"min": 10, "max": 13},
            "confidence": "Medium",
            "uncertainty": "Une seule tâche ne suffit pas.",
            "taskCompliance": [{"item": "But", "status": "Met", "evidenceId": "E1", "evidence": "Le message est adressé."}],
            "criteria": {
                key: {"rating": "Adequate", "evidenceIds": ["E1"], "evidence": "Le passage est exploitable."}
                for key in ("linguistic", "pragmatic", "sociolinguistic")
            },
            "gradeRationale": "Le texte montre un contrôle fonctionnel.",
            "gradeEvidenceIds": ["E99", "E1"],
            "strengths": [{"evidenceId": "E1", "text": "Ouverture claire."}],
            "verbFeedback": [],
            "corrections": [],
            "relevance": [],
            "upgrades": [],
            "improvedResponse": "",
            "priorities": ["Préciser le but.", "Relier les idées.", "Relire les accords."],
        }

    @staticmethod
    def _workers_reply(content, *, finish="stop", **message):
        return {
            "success": True,
            "result": {"choices": [{"finish_reason": finish, "message": {"content": content, **message}}]},
        }

    def test_evaluation_grounding_requires_evidence_and_a_valid_score_range(self):
        self.assertIsNotNone(
            writing_evaluation._locate(
                "J’ai déjà visité Montréal.\u00a0",
                "J'ai déjà visité Montréal.",
            )
        )
        evidence = {}
        number_passages("Bonjour", evidence)
        packet = dict(subject=self.sujet.prompt, response="Bonjour", evidence=evidence, word_count=1, word_min=60, word_max=120)
        report = self._provider_report()
        grounded = writing_evaluation.ground(report, **packet)

        self.assertEqual(grounded["cefr"], "B2")
        self.assertEqual(grounded["nclc"], "NCLC 8")
        self.assertEqual(grounded["gradeEvidence"], ["Bonjour"])
        self.assertIn("gradeEvidence", grounded["omittedSections"])
        report["gradeEvidenceIds"] = ["E99"]
        with self.assertRaisesRegex(writing_evaluation.ReportError, r"gradeEvidence\.evidence"):
            writing_evaluation.ground(report, **packet)
        report["gradeEvidenceIds"] = ["E1"]
        report["criteria"]["linguistic"]["evidenceIds"] = [None, "E99"]
        with self.assertRaisesRegex(writing_evaluation.ReportError, r"criteria\.linguistic\.evidence"):
            writing_evaluation.ground(report, **packet)
        report["criteria"]["linguistic"]["evidenceIds"] = ["E1"]
        report["score"] = 14
        with self.assertRaisesRegex(writing_evaluation.ReportError, "scoreRange"):
            writing_evaluation.ground(report, **packet)

    def test_unusable_optional_feedback_does_not_discard_a_supported_score(self):
        report = self._provider_report()
        report["criteria"]["linguistic"].update(
            evidence="Observation détaillée. " * 40,
            evidenceIds=[42, "E1"],
        )
        report.update(
            verdict="Avis détaillé. " * 80,
            confidence="Moyenne",
            uncertainty=None,
            gradeRationale="Justification détaillée. " * 100,
            strengths=[{"evidenceId": "E1"}],
            corrections=[
                {"before": "Bonjour", "after": None, "type": "Registre", "why": "Salutation."},
                {"before": "salu!", "after": "salut !", "type": "Orthographe", "why": "Il manque le t."},
            ],
            improvedResponse=None,
            upgrades={"unexpected": True},
            priorities=[None, "Relire les accords."],
        )
        response = "Bonjour, salu!"
        evidence = {}
        number_passages(response, evidence)
        result = writing_evaluation.ground(
            report, subject=self.sujet.prompt, response=response, evidence=evidence,
            word_count=2, word_min=60, word_max=120,
        )
        self.assertEqual(result["score"], 12)
        self.assertEqual(result["confidence"], "")
        self.assertEqual(result["uncertainty"], "")
        self.assertEqual(result["strengths"], [])
        self.assertEqual(result["upgrades"], [])
        self.assertEqual([item["after"] for item in result["corrections"]], ["salut !"])
        self.assertEqual(result["priorities"], ["Relire les accords."])
        self.assertEqual(result["improvedResponse"], "")
        self.assertEqual(result["criteria"][0]["quotes"], [response])
        for prose, phrase, limit in (
            (result["verdict"], "Avis détaillé.", 900),
            (result["gradeRationale"], "Justification détaillée.", 1800),
            (result["criteria"][0]["evidence"], "Observation détaillée.", 700),
        ):
            self.assertTrue(prose.startswith(phrase))
            self.assertTrue(prose.endswith("…"))
            self.assertLessEqual(len(prose), limit)
        self.assertTrue({"strengths", "corrections", "improvedResponse"} <= set(result["omittedSections"]))

    def test_corrections_preserve_the_source_line_breaks(self):
        response = "Salut!\r\nJe passerai bientot.\r\n\r\nN."
        evidence = {}
        number_passages(response, evidence)
        invented = {
            "before": "Salut! Je", "after": "Salut ! Je",
            "type": "Ponctuation", "why": "This quote replaces the actual line break with a space.",
        }
        valid = [
            {"before": "Salut!\nJe", "after": "Salut !\nJe",
             "type": "Typographie", "why": "Add the French space before the exclamation mark."},
            {"before": "bientot", "after": "bientôt",
             "type": "Orthographe", "why": "Add the circumflex to « bientôt »."},
        ]
        report = {**self._provider_report(), "gradeEvidenceIds": ["E1"], "corrections": [invented, *valid]}

        result = writing_evaluation.ground(
            report, subject=self.sujet.prompt, response=response, evidence=evidence,
            word_count=5, word_min=60, word_max=120,
        )

        self.assertEqual(result["corrections"], valid)
        self.assertEqual(result["omittedSections"], ["corrections"])

    def test_verb_feedback_keeps_cited_explanations_without_repeating_the_quote(self):
        response = "Il pleuvait quand nous sommes arrivés.\n\nNous avons acheter deux billets."
        background, event = response.split("\n\n")
        report = self._provider_report()
        note = "« Pleuvait » is in the imparfait because it sets the scene for your arrival."
        report["verbFeedback"] = [
            {"evidenceId": "E1", "text": note},
            {"evidenceId": "E99", "text": "This has no supporting passage."},
            {"evidenceId": "E2", "text": event},
        ]
        report["corrections"] = [{
            "before": "Nous avons acheter", "after": "Nous avons acheté",
            "type": "Passé composé", "why": "After « avons », use the past participle « acheté », not the infinitive.",
        }, {
            "before": "deux billets", "after": "deux billets",
            "type": "No change", "why": "This is not a correction.",
        }]
        report["priorities"] = ["After « avoir », recheck the past participle: « avons acheté »."]
        with patch.object(evaluation, "request_report", return_value=report) as request:
            result = writing_evaluation.score(
                task_number=2, subject="Racontez votre visite au musée.",
                response=response, word_count=11, word_min=120, word_max=150,
            )
        self.assertIn("a completed event or bounded period may use the passé composé", request.call_args.args[0])
        self.assertEqual(result["verbFeedback"], [{"quote": background, "text": note}])
        self.assertEqual(result["corrections"], report["corrections"][:1])
        self.assertEqual(result["score"], 12)
        self.assertEqual(result["priorities"], report["priorities"])
        self.assertEqual(set(result["omittedSections"]), {"gradeEvidence", "verbFeedback", "corrections"})

    def test_proofreads_proposal_without_changing_the_supported_grade(self):
        response = (
            "Salut Alex, merci pour ta aide pendant mon absence. Peux-tu arroser les plantes mercredi et samedi ? "
            "J’ai laissé l’arrosoir près du balcon. Pour le chien, les croquettes sont dans le placard de la cuisine. "
            "Tu peux le sortir après le travail. Le facteur passe le matin ; laisse le courrier sur la table. "
            "Si tu as une question, appelle-moi. Merci encore pour ta aide. À bientôt !"
        )
        report = {**self._provider_report(), "improvedResponse": response}
        corrected = response.replace("ta aide", "ton aide")
        for revision, expected in (
            ({"improvedResponse": corrected}, corrected),
            ({"improvedResponse": ""}, ""),
            ({"improvedResponse": "Merci pour ton aide."}, ""),
            (evaluation.EvaluationError(504, "La relecture n’a pas abouti."), ""),
        ):
            with (
                self.subTest(expected=bool(expected), revision=type(revision).__name__),
                patch.object(evaluation, "request_provider_report", side_effect=[report, revision]) as request,
                nullcontext() if expected else self.assertLogs(writing_evaluation.logger, "WARNING"),
            ):
                result = writing_evaluation.score(
                    task_number=1, subject=self.sujet.prompt, response=response,
                    word_count=_ee_word_count(response), word_min=60, word_max=120, provider="groq",
                )
                self.assertEqual(result["score"], 12)
                self.assertEqual(result["improvedResponse"], expected)
                self.assertEqual("improvedResponse" in result["omittedSections"], not expected)
                first, proofread = request.call_args_list
                self.assertEqual(proofread.args[0], first.args[0])
                self.assertEqual(proofread.args[2]["original"], response)
                self.assertEqual(proofread.args[2]["proposal"], response)
                self.assertEqual(proofread.args[3]["required"], ["improvedResponse"])
                self.assertLess(proofread.kwargs["deadline"], first.kwargs["deadline"])

    @override_settings(EE1_EVALUATION_PROVIDER="groq")
    def test_groq_reports_ground_evidence_in_strict_mode_and_after_schema_retry(self):
        greeting = "Bonjour, j’ai trouvé une salle de sport près de chez moi."
        original = f"{greeting}\n\nÀ bientôt !"
        valid = {**self._provider_report(), "strengths": ["Not a structured strength"]}
        invalid = {**valid, "score": True}
        rejected = json.dumps({"error": {"code": "json_validate_failed", "message": original}}).encode()

        def completion(report):
            return json.dumps({"choices": [{
                "finish_reason": "stop", "message": {"content": json.dumps(report)},
            }]}).encode()

        for responses, expected in (
            ([(200, completion(valid))], "ready"),
            ([(400, rejected), (200, completion(valid))], "ready"),
            ([(400, rejected), (200, completion(invalid))], "n’a pas pu être vérifié"),
            ([(400, rejected), (400, rejected)], "json_validate_failed"),
            ([(400, b'{"error":{"code":"invalid_request_error"}}')], "invalid_request_error"),
            ([(400, b'{"error":{"code":"private_upstream_code"}}')], "HTTP 400"),
        ):
            with self.subTest(expected=expected), patch.object(
                evaluation, "HTTPSConnection", autospec=True,
            ) as transport:
                conn = transport.return_value
                conn.sock = None
                response = conn.getresponse.return_value.__enter__.return_value
                remaining = iter(responses)

                def respond(*args, **kwargs):
                    response.status, response.read.return_value = next(remaining)

                conn.request.side_effect = respond

                def score():
                    return writing_evaluation.score(
                        task_number=1, subject=self.sujet.prompt, response=original,
                        word_count=13, word_min=60, word_max=120,
                    )

                if expected == "ready":
                    report = score()
                    self.assertEqual(report["gradeEvidence"], [greeting])
                    self.assertEqual(report["criteria"][0]["quotes"], [greeting])
                    self.assertEqual(report["taskCompliance"][0]["quote"], greeting)
                    self.assertEqual(report["strengths"], [])
                else:
                    with self.assertLogs(evaluation.logger, "WARNING") as logs:
                        with self.assertRaisesRegex(evaluation.EvaluationError, expected):
                            score()
                    diagnostics = "\n".join(logs.output)
                    self.assertNotIn(greeting, diagnostics)
                    self.assertNotIn("private_upstream_code", diagnostics)
                    if responses[0][1] == rejected:
                        self.assertIn("provider HTTP 400 json_validate_failed", diagnostics)
                requests = [json.loads(call.kwargs["body"]) for call in conn.request.call_args_list]
                self.assertEqual([request["response_format"]["type"] for request in requests],
                                 ["json_schema", "json_object"][:len(responses)])
                system, user = requests[0]["messages"]
                self.assertIn("Choose CEFR first", system["content"])
                self.assertIn("an informal message to a friend does not need a more formal tone", system["content"])
                self.assertNotIn("MANDATORY WRITTEN REPORT", system["content"])
                self.assertNotIn("wait silently", system["content"])
                self.assertEqual(json.loads(user["content"]), {
                    "subject": self.sujet.prompt, "response": original,
                    "passages": [{"id": "E1", "text": greeting}, {"id": "E2", "text": "À bientôt !"}],
                    "wordCount": 13, "wordMin": 60, "wordMax": 120,
                })
                if len(responses) == 2:
                    self.assertEqual(requests[0]["messages"][1], requests[1]["messages"][1])

    @override_settings(EE1_EVALUATION_PROVIDER="gemini", GEMINI_API_KEY="fixture-gemini-key")
    @patch.object(evaluation, "HTTPSConnection", autospec=True)
    def test_gemini_uses_the_writing_rubric_and_grounds_its_report(self, transport):
        conn = transport.return_value
        conn.sock = None
        upstream = conn.getresponse.return_value.__enter__.return_value
        upstream.status = 200
        fixture = self._provider_report()
        fixture["criteria"]["sociolinguistic"]["rating"] = "Excellent"
        output = json.dumps(fixture)
        upstream.read.return_value = json.dumps({"candidates": [{
            "finishReason": "STOP",
            "content": {"parts": [
                {"thought": True, "text": "Not part of the report."},
                {"text": output[:80]}, {"text": output[80:]},
            ]},
        }]}).encode()

        report = writing_evaluation.score(
            task_number=1, subject=self.sujet.prompt, response="Bonjour",
            word_count=1, word_min=60, word_max=120,
        )

        self.assertEqual((report["score"], report["cefr"], report["gradeEvidence"]), (12, "B2", ["Bonjour"]))
        self.assertEqual(report["criteria"][-1]["rating"], "Excellent")
        transport.assert_called_once()
        self.assertEqual(transport.call_args.args, ("generativelanguage.googleapis.com",))
        request = conn.request.call_args
        self.assertEqual(request.args, ("POST", "/v1beta/models/gemini-3.8-flash:generateContent"))
        self.assertEqual(request.kwargs["headers"]["x-goog-api-key"], settings.GEMINI_API_KEY)
        payload = json.loads(request.kwargs["body"])
        self.assertIn(writing_evaluation._rubric(1), payload["systemInstruction"]["parts"][0]["text"])
        self.assertEqual(json.loads(payload["contents"][0]["parts"][0]["text"]), {
            "subject": self.sujet.prompt, "response": "Bonjour", "passages": [{"id": "E1", "text": "Bonjour"}],
            "wordCount": 1, "wordMin": 60, "wordMax": 120,
        })
        self.assertEqual(payload["generationConfig"]["responseMimeType"], "application/json")
        self.assertEqual(payload["generationConfig"]["responseJsonSchema"], writing_evaluation._SCHEMA)

    @override_settings(GEMINI_API_KEY="fixture-gemini-key")
    def test_gemini_retries_a_transient_failure_once_with_the_same_request_and_deadline(self):
        complete = json.dumps({"candidates": [{
            "finishReason": "STOP",
            "content": {"parts": [{"text": json.dumps({"score": 12})}]},
        }]}).encode()
        errors = {
            503: b'{"error":{"code":503,"status":"UNAVAILABLE"}}',
            429: b'{"error":{"code":429,"status":"RESOURCE_EXHAUSTED"}}',
        }
        for statuses in ((503, 200), (503, 503), (429,)):
            with (
                self.subTest(statuses=statuses),
                patch.object(evaluation, "HTTPSConnection", autospec=True) as transport,
                patch.object(evaluation, "_post", wraps=evaluation._post) as post,
                patch.object(evaluation.time, "sleep") as backoff,
                self.assertLogs(evaluation.logger, "WARNING"),
            ):
                conn = transport.return_value
                conn.sock = None
                upstream = conn.getresponse.return_value.__enter__.return_value
                upstream.getheader.return_value = None
                pending = iter(statuses)

                def respond(*args, **kwargs):
                    upstream.status = next(pending)
                    upstream.read.return_value = errors.get(upstream.status, complete)

                conn.request.side_effect = respond
                if statuses[-1] == 200:
                    self.assertEqual(evaluation.request_gemini_report("Rubric", {}, {}), {"score": 12})
                else:
                    with self.assertRaisesRegex(evaluation.EvaluationError, f"HTTP {statuses[-1]}"):
                        evaluation.request_gemini_report("Rubric", {}, {})

                self.assertEqual(post.call_count, len(statuses))
                self.assertEqual(backoff.call_count, len(statuses) - 1)
                self.assertEqual(post.call_args.kwargs["service"], "Gemini")
                if len(statuses) == 2:
                    self.assertEqual(post.call_args_list[0], post.call_args_list[1])

    @override_settings(GEMINI_API_KEY="fixture-gemini-key")
    def test_gemini_does_not_grade_blocked_or_incomplete_responses(self):
        for reply, message in (
            ({"promptFeedback": {"blockReason": "SAFETY"}}, "Aucun bilan"),
            ({"candidates": [{"finishReason": "MAX_TOKENS"}]}, "incomplet"),
            ({"candidates": [{"finishReason": "STOP", "content": {"parts": []}}]}, "illisible"),
        ):
            with self.subTest(message=message), patch.object(
                evaluation, "_post", return_value=(json.dumps(reply).encode(), 1),
            ) as post:
                with self.assertRaisesRegex(evaluation.EvaluationError, message):
                    evaluation.request_gemini_report("Rubric", {}, {})
                post.assert_called_once()

    @override_settings(GEMINI_API_KEY="")
    @patch.object(evaluation, "_post")
    def test_gemini_grading_does_not_call_the_provider_without_a_key(self, post):
        with self.assertLogs(evaluation.logger, "WARNING"), self.assertRaises(evaluation.EvaluationError):
            evaluation.request_gemini_report("Rubric", {}, {})
        post.assert_not_called()

    @override_settings(CLOUDFLARE_WORKERS_API_KEY="fixture-workers-token", CLOUDFLARE_ACCOUNT_ID=workers_account_id)
    def test_workers_grades_with_the_same_rubric_and_evidence_checks(self):
        reply = self._workers_reply(json.dumps(self._provider_report()), reasoning_content="Not assessment feedback.")
        with patch.object(evaluation, "HTTPSConnection", autospec=True) as transport:
            conn = transport.return_value
            conn.sock = None
            upstream = conn.getresponse.return_value.__enter__.return_value
            upstream.status = 200
            upstream.read.return_value = json.dumps(reply).encode()
            report = writing_evaluation.score(
                task_number=1, subject=self.sujet.prompt, response="Bonjour",
                word_count=1, word_min=60, word_max=120, provider="cloudflare",
            )

        self.assertEqual((report["score"], report["gradeEvidence"]), (12, ["Bonjour"]))
        transport.assert_called_once()
        self.assertEqual(transport.call_args.args, ("api.cloudflare.com",))
        request = conn.request.call_args
        self.assertEqual(request.args, (
            "POST", f"/client/v4/accounts/{self.workers_account_id}/ai/run/@cf/google/gemma-4-26b-a4b-it",
        ))
        self.assertEqual(request.kwargs["headers"]["Authorization"], "Bearer fixture-workers-token")
        payload = json.loads(request.kwargs["body"])
        self.assertIn(writing_evaluation._rubric(1), payload["messages"][0]["content"])
        self.assertEqual(json.loads(payload["messages"][1]["content"])["response"], "Bonjour")
        self.assertEqual(payload["response_format"], {
            "type": "json_schema",
            "json_schema": {"name": "ee1_bilan", "strict": True, "schema": writing_evaluation._SCHEMA},
        })
        self.assertIs(payload["store"], False)

    @override_settings(CLOUDFLARE_WORKERS_API_KEY="fixture-workers-token", CLOUDFLARE_ACCOUNT_ID=workers_account_id)
    def test_workers_rejects_unsuccessful_or_malformed_replies(self):
        for reply, message in (
            ({"success": False, "errors": [{"message": "private upstream detail"}]}, "refusé"),
            (self._workers_reply("not JSON"), "illisible"),
            (self._workers_reply('{"score":12,"score":15}'), "illisible"),
            (self._workers_reply('{"score":12}', finish="length"), "incomplet"),
            (self._workers_reply(None, finish="content_filter", refusal="private upstream detail"), "Aucun bilan"),
        ):
            with (
                self.subTest(message=message),
                patch.object(evaluation, "_post", return_value=(json.dumps(reply).encode(), 1)) as post,
                self.assertLogs(evaluation.logger, "WARNING") as logs,
                self.assertRaisesRegex(evaluation.EvaluationError, message),
            ):
                evaluation.request_workers_report("Rubric", {}, {})
            self.assertNotIn("private upstream detail", "\n".join(logs.output))
            post.assert_called_once()
