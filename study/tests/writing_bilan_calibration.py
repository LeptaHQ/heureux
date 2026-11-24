"""Opt-in live comparison using invented writing, never a saved learner response."""

import os
from unittest import skipUnless

from django.conf import settings
from django.test import SimpleTestCase

from study.catalogue.loader import _ee_word_count
from study.simulation import writing_evaluation


@skipUnless(os.environ.get("RUN_WRITING_CALIBRATION") == "1", "Opt in to live writing calibration.")
class WritingBilanCalibration(SimpleTestCase):
    def test_compare_ee1_providers_on_the_same_message(self):
        self.assertTrue(settings.GEMINI_EVALUATION_API_KEY and settings.GROQ_API_KEY, "Both evaluation keys are required.")
        subject = (
            "Un ami cherche une librairie pour acheter des livres d’occasion. "
            "Recommandez-lui une adresse et indiquez les horaires et les prix."
        )
        response = (
            "Salut Alex,\n\n"
            "Je te conseille La Page Verte, sur la place de la mairie. La librairie est ouverte "
            "du mardi au samedi, de 10 h à 18 h. Pour un roman de poche, comptes environ cinq euros. "
            "Il y a aussi un rayon de bandes dessinées à l’étage, juste à côté des livres pour enfants.\n\n"
            "Si tu veux, on peut y aller ensemble samedi après le marché.\n\n"
            "À bientôt !"
        )
        for provider in ("gemini", "groq"):
            with self.subTest(provider=provider), self.settings(EE1_EVALUATION_PROVIDER=provider):
                report = writing_evaluation.score(
                    task_number=1, subject=subject, response=response,
                    word_count=_ee_word_count(response), word_min=60, word_max=120,
                )
                self.assertTrue(report["gradeEvidence"])
                self.assertTrue(all(quote in response for quote in report["gradeEvidence"]))
                print(f"\n{provider}: {report['score']}/20 · {report['cefr']}")
                print(report["gradeRationale"])
                for correction in report["corrections"]:
                    print(f"{correction['before']} → {correction['after']}: {correction['why']}")
