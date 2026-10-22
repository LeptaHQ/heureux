from django.test import SimpleTestCase

from study import catalogue


class TacheThreeReuseTests(SimpleTestCase):
    def setUp(self):
        catalogue.clear_catalogue_cache()
        self.addCleanup(catalogue.clear_catalogue_cache)
        self.models = catalogue.tache_three_models()
        self.plans = catalogue.tache_three_subject_hints()

    def response(self, group):
        return self.models[f"eo/tache-3/{group}"].response

    def cue(self, group, index):
        return self.plans[f"eo/tache-3/{group}"].arguments[index]

    def test_compatible_complete_arguments_and_bilingual_cues_are_identical(self):
        for first, second, indices in (
            ("culture-p18", "technologie-p12", (0, 1, 2)),
            ("famille-p1", "technologie-p16", (2,)),
        ):
            for index in indices:
                with self.subTest(first=first, second=second, argument=index + 1):
                    self.assertEqual(
                        self.response(first).arguments[index],
                        self.response(second).arguments[index],
                    )
                    self.assertEqual(self.cue(first, index), self.cue(second, index))

    def test_shared_household_argument_keeps_its_different_spoken_position(self):
        comfort = self.response("famille-p2").arguments[2]
        practical = self.response("famille-p16").arguments[1]
        self.assertTrue(comfort.idea.startswith("Enfin, "))
        self.assertTrue(practical.idea.startswith("Ensuite, "))
        for field in ("developpement", "exemple", "consequence"):
            self.assertEqual(getattr(comfort, field), getattr(practical, field))
        self.assertEqual(self.cue("famille-p2", 2), self.cue("famille-p16", 1))

    def test_shared_cases_and_their_memory_cues_do_not_need_synonym_versions(self):
        for first, first_index, second, second_index in (
            ("culture-p9", 0, "education-p13", 1),
            ("technologie-p4", 0, "technologie-p13", 1),
            ("sante-p4", 0, "economie-p23", 0),
            ("environnement-p1", 1, "sante-p4", 1),
            ("environnement-p3", 1, "environnement-p14", 0),
            ("environnement-p2", 1, "environnement-p4", 1),
            ("environnement-p6", 0, "environnement-p8", 2),
            ("sante-p22", 2, "economie-p9", 0),
            ("education-p15", 2, "technologie-p21", 1),
        ):
            with self.subTest(first=first, second=second):
                self.assertEqual(
                    self.response(first).arguments[first_index].exemple,
                    self.response(second).arguments[second_index].exemple,
                )
                self.assertEqual(
                    self.cue(first, first_index).example,
                    self.cue(second, second_index).example,
                )

    def test_shared_language_does_not_merge_different_questions_or_positions(self):
        for first, second in (
            ("culture-p18", "technologie-p12"),
            ("culture-p16", "famille-p9"),
            ("culture-p16", "culture-p24"),
            ("famille-p2", "famille-p16"),
            ("famille-p1", "technologie-p16"),
            ("culture-p9", "education-p13"),
            ("environnement-p2", "environnement-p4"),
            ("environnement-p6", "environnement-p8"),
            ("sante-p22", "economie-p9"),
        ):
            with self.subTest(first=first, second=second):
                self.assertNotEqual(
                    self.models[f"eo/tache-3/{first}"].source_prompts,
                    self.models[f"eo/tache-3/{second}"].source_prompts,
                )
                self.assertNotEqual(self.response(first).position_claire, self.response(second).position_claire)
                self.assertNotEqual(self.response(first).nuance, self.response(second).nuance)
                self.assertNotEqual(self.response(first).conclusion, self.response(second).conclusion)

    def test_adaptations_retain_their_specific_actor_jurisdiction_and_mechanism(self):
        self.assertIn("un adulte", self.response("culture-p2").arguments[2].exemple)
        self.assertIn("une personne âgée", self.response("culture-p8").arguments[2].exemple)
        self.assertIn("livre de bibliothèque", self.response("famille-p12").arguments[1].exemple)
        self.assertIn("la province ou le territoire", self.response("economie-p1").arguments[0].developpement)
        self.assertIn("organisme québécois", self.response("education-p5").arguments[1].exemple)
        self.assertIn("Traduire son diplôme", self.response("economie-p15").arguments[2].exemple)
        self.assertIn("formation complémentaire", self.response("culture-p5").arguments[1].exemple)
        self.assertIn("devenir cuisinier", self.response("culture-p5").arguments[0].exemple)
        self.assertIn("d'occasion", self.response("culture-p34").arguments[2].exemple)
        self.assertIn("Une enseigne peut acheter", self.response("environnement-p7").arguments[1].exemple)
        self.assertIn("occasion de contact", self.response("environnement-p13").arguments[0].exemple)
        self.assertIn("besoins restent couverts", self.response("economie-p9").arguments[0].exemple)
        self.assertIn("heures supplémentaires", self.response("economie-p18").arguments[2].exemple)
        for group in ("famille-p1", "technologie-p16"):
            self.assertIn("harcèlement", self.response(group).arguments[2].developpement)
            self.assertIn("d'un inconnu", self.response(group).arguments[2].exemple)
        for group in ("environnement-p2", "environnement-p4"):
            self.assertIn("pas que toute espèce", self.response(group).arguments[1].exemple)

    def test_partial_reuse_includes_development_and_a_relevant_nuance(self):
        self.assertEqual(
            self.response("technologie-p4").arguments[0].developpement,
            self.response("technologie-p13").arguments[1].developpement,
        )
        self.assertEqual(
            self.response("environnement-p6").arguments[0].developpement,
            self.response("environnement-p8").arguments[2].developpement,
        )
        common_letter_limit = (
            "Un message numérique peut aussi être réfléchi, attentionné, sauvegardé et accessible."
        )
        self.assertIn(common_letter_limit.casefold(), self.response("culture-p18").nuance.casefold())
        self.assertIn(common_letter_limit, self.response("technologie-p12").nuance)
        solitude = "Cependant, il faut distinguer une solitude choisie d'un isolement qui fait souffrir."
        self.assertIn(solitude, self.response("culture-p16").nuance)
        self.assertIn(solitude, self.response("culture-p24").nuance)
        consent = "Une cohabitation durable peut fonctionner, mais doit rester choisie de part et d'autre."
        self.assertIn(consent, self.response("famille-p2").nuance)
        self.assertIn(consent, self.response("famille-p16").nuance)
