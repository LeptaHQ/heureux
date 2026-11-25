"""Opt-in live comparison using invented writing, never a saved learner response."""

import os
from contextlib import nullcontext
from unittest import skipUnless
from unittest.mock import patch

from django.test import SimpleTestCase

from study.catalogue.loader import _ee_word_count
from study.simulation import copilot_runtime, evaluation, writing_evaluation


_RUN = os.environ.get("RUN_WRITING_CALIBRATION")
_COPILOT_MODELS = {label: (provider, model) for provider, (label, model) in copilot_runtime.MODELS.items()}


@skipUnless(_RUN in {"1", "copilot"}, "Opt in to live writing calibration.")
class WritingBilanCalibration(SimpleTestCase):
    def test_compare_ee1_providers_on_the_same_message(self):
        transport = nullcontext()
        if _RUN == "copilot":
            token = os.environ.get("COPILOT_GITHUB_TOKEN", "").strip()
            self.assertTrue(bool(token), "Set COPILOT_GITHUB_TOKEN for the opt-in Copilot pilot.")
            model = os.environ.get("COPILOT_CALIBRATION_MODEL", "MAI")
            self.assertIn(model, _COPILOT_MODELS, "Choose Astra, MAI, or Opus for the Copilot pilot.")
            provider, model_id = _COPILOT_MODELS[model]
            transport = patch.object(evaluation, "request_provider_report", copilot_runtime.report_transport(
                token, model_id, measure=True,
            ))
            providers = [provider]
        else:
            providers = sorted(evaluation.available_providers())
        self.assertTrue(providers, "Configure at least one writing evaluation provider.")
        subject = (
            "Un ami cherche une librairie pour acheter des livres d’occasion. "
            "Recommandez-lui une adresse et indiquez les horaires et les prix."
        )
        response = (
            "Salut Alex,\n\n"
            "Je te conseille La Page Verte, sur la place de la mairie. La librairie est ouverte "
            "du mardi au samedi, de 10 h à 18 h. Pour un roman de poche, comptes environ cinq euros. "
            "Hier, j’y suis passé : il y avait peu de monde et j’ai acheter un roman. "
            "Il y a aussi un rayon de bandes dessinées à l’étage.\n\n"
            "Si tu veux, on peut y aller ensemble samedi après le marché.\n\n"
            "À bientôt !"
        )
        for provider in providers:
            with self.subTest(provider=provider), transport:
                report = writing_evaluation.score(
                    task_number=1, subject=subject, response=response,
                    word_count=_ee_word_count(response), word_min=60, word_max=120,
                    provider=provider,
                )
                self.assertTrue(report["gradeEvidence"])
                self.assertTrue(all(quote in response for quote in report["gradeEvidence"]))
                self.assertTrue(report["verbFeedback"], "No grounded feedback on verb forms.")
                self.assertTrue(all(note["quote"] in response for note in report["verbFeedback"]))
                print(f"\n{provider}: {report['score']}/20 · {report['cefr']}")
                print(report["gradeRationale"])
                for note in report["verbFeedback"]:
                    print(f"« {note['quote']} » — {note['text']}")
                for correction in report["corrections"]:
                    print(f"{correction['before']} → {correction['after']}: {correction['why']}")
                if provider in copilot_runtime.MODELS:
                    self.assertTrue(report["improvedResponse"], "No usable Copilot proposal.")
