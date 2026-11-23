"""Explicit live smoke checks with invented speech; no accounts, recordings or saved sessions."""
import os
from unittest import skipUnless

from django.conf import settings
from django.test import SimpleTestCase

from study.expression.eo.tache_2 import oral_evaluation


@skipUnless(os.environ.get("RUN_GROQ_CALIBRATION") == "1", "Set RUN_GROQ_CALIBRATION=1 for live synthetic grading")
class OralBilanCalibration(SimpleTestCase):
    def marks(self, prompt, rows, *, monologue=False):
        self.assertTrue(settings.GROQ_API_KEY, "A Groq key is required for live calibration.")
        report = oral_evaluation.score(prompt, rows, monologue=monologue)
        self.assertEqual(report["scoreStatus"], "scored", report["criteria"])
        for mark in report["criteria"]:
            source = rows[mark["turnIndex"]]
            self.assertEqual(source["speaker"], "user")
            self.assertIn(mark["quote"], source["text"])
        return {item["key"]: item["score"] for item in report["criteria"]}

    def test_eo2_following_up_beats_reasking_for_information_just_given(self):
        prompt = "Je travaille au centre sportif. Vous voulez vous inscrire à un cours de natation et me demandez des renseignements."
        def exchange(follow_up, final):
            return [{"speaker": speaker, "text": text} for speaker, text in (
                ("user", "Bonjour, je voudrais suivre un cours pour débutants. Quels jours proposez-vous ?"),
                ("model", "Il y a un cours le samedi matin. Il faut réserver sa place."),
                ("user", follow_up), ("model", "La réservation se fait à l’accueil, avant jeudi."),
                ("user", final))]
        repetitive = self.marks(prompt, exchange("Quel jour a lieu le cours pour débutants ?",
                                                "Et le cours, c’est quel jour déjà ?"))
        responsive = self.marks(prompt, exchange("Le samedi me convient. Comment est-ce que je peux réserver ma place ?",
                                                "Si je passe mercredi à l’accueil, quels documents dois-je apporter ?"))
        self.assertGreater(responsive["task"], repetitive["task"], (responsive, repetitive))
        self.assertGreater(responsive["coherence"], repetitive["coherence"], (responsive, repetitive))

    def test_eo3_same_words_different_question_separates_task_from_grammar(self):
        rows = [{"speaker": "user", "text":
                 "Je préfère emprunter mes livres à la bibliothèque. Comme je ne relis presque jamais un roman, "
                 "je peux en essayer plusieurs sans dépenser davantage. C'est ce qui m'a permis de découvrir "
                 "une autrice que je n'aurais pas choisie en librairie. En revanche, quand un livre me plaît "
                 "vraiment, je l'achète pour pouvoir le prêter à mes amis."}]
        relevant = self.marks("Vaut-il mieux emprunter ses livres ou les acheter ?", rows, monologue=True)
        unrelated = self.marks("Faut-il installer des pistes cyclables dans toutes les villes ?", rows, monologue=True)
        self.assertGreater(relevant["task"], unrelated["task"], (relevant, unrelated))
        self.assertLessEqual(abs(relevant["grammar"] - unrelated["grammar"]), 1, (relevant, unrelated))
