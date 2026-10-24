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

    def test_live_questions_and_translated_explanations_keep_distinct_mechanisms(self):
        conversation = self.response("culture-p14").arguments[2]
        translation = self.response("culture-p19").arguments[1]
        self.assertIn("poser ses propres questions", conversation.developpement)
        self.assertIn("demander des précisions", conversation.developpement)
        self.assertIn("voir une habitude sans en comprendre la raison", translation.developpement)
        self.assertIn("Avec des sous-titres", translation.developpement)
        self.assertIn("ne parle pas japonais", translation.exemple)
        self.assertNotEqual(
            self.models["eo/tache-3/culture-p14"].source_prompts,
            self.models["eo/tache-3/culture-p19"].source_prompts,
        )

    def test_shared_cases_and_their_memory_cues_do_not_need_synonym_versions(self):
        for first, first_index, second, second_index in (
            ("culture-p5", 0, "culture-p17", 0),
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
            ("culture-p5", "culture-p17"),
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

    def test_remote_contact_limit_keeps_the_same_words_for_three_relevant_questions(self):
        shared = (
            "Les appels entretiennent le lien, mais ne remplacent pas toujours "
            "une présence physique."
        )
        for group, index in (("culture-p9", 1), ("culture-p24", 0), ("culture-p29", 1)):
            with self.subTest(group=group):
                self.assertTrue(self.response(group).arguments[index].developpement.startswith(shared))
        self.assertIn("dîner sans compagnie", self.response("culture-p9").arguments[1].exemple)
        self.assertIn("quelques courses", self.response("culture-p24").arguments[0].exemple)
        self.assertIn("après une opération", self.response("culture-p29").arguments[1].exemple)

    def test_famille_distance_reuses_the_same_call_case_and_bilingual_example(self):
        self.assertEqual(
            self.response("famille-p5").arguments[0].exemple,
            self.response("culture-p9").arguments[1].exemple,
        )
        self.assertEqual(
            self.cue("famille-p5", 0).example,
            self.cue("culture-p9", 1).example,
        )
        shared = (
            "Les appels entretiennent le lien, mais ne remplacent pas toujours "
            "une présence physique."
        )
        for group, index in (
            ("famille-p5", 0), ("culture-p9", 1),
            ("culture-p24", 0), ("culture-p29", 1),
        ):
            self.assertTrue(self.response(group).arguments[index].developpement.startswith(shared))
        self.assertIn("au quotidien", self.response("famille-p5").arguments[0].idea)
        self.assertIn("les débuts", self.response("culture-p9").arguments[1].idea)
        self.assertIn("récupérer son enfant", self.response("famille-p5").arguments[1].exemple)

    def test_familiar_routines_help_without_copying_a_cultural_identity_argument(self):
        shared = self.response("culture-p1").arguments[1].developpement.split(". ")[0] + "."
        self.assertTrue(self.response("culture-p10").arguments[0].developpement.startswith(shared))
        self.assertTrue(self.response("famille-p16").arguments[2].developpement.startswith(shared))
        self.assertIn("Après une séparation", self.response("famille-p16").arguments[2].exemple)
        self.assertIn("parler sa langue", self.response("culture-p1").arguments[1].exemple)
        self.assertIn("sans leur confier toutes ses décisions", self.response("famille-p16").arguments[2].developpement)

    def test_friendship_partial_reuse_keeps_practical_help_and_discovery_distinct(self):
        no_friends = "Ne pas avoir d'amis ne veut pas dire vivre sans aucun lien."
        self.assertIn(no_friends, self.response("culture-p16").arguments[1].developpement)
        self.assertIn(no_friends.casefold(), self.response("famille-p9").nuance.casefold())
        shared = "Pouvoir se retrouver régulièrement permet de partager son quotidien"
        for group, index in (("famille-p9", 1), ("culture-p24", 0)):
            self.assertIn(shared, self.response(group).arguments[index].developpement)
        self.assertNotIn("s'entraider", self.response("famille-p9").arguments[1].developpement)
        self.assertIn("s'entraider", self.response("culture-p24").arguments[0].developpement)
        self.assertIn("cartons", self.response("famille-p9").arguments[0].exemple)
        self.assertIn("chorale", self.response("famille-p9").arguments[2].exemple)

    def test_family_and_compatriot_trust_share_words_not_an_identity_guarantee(self):
        for group, text, distinct in (
            ("famille-p10", self.response("famille-p10").conclusion, "lien de parenté"),
            ("culture-p11", self.response("culture-p11").nuance, "l'origine"),
        ):
            self.assertIn("L'essentiel est de choisir ses", text)
            self.assertIn("selon la confiance et les affinités, pas seulement selon", text)
            self.assertIn(distinct, text)
        self.assertIn("respecte son choix", self.response("famille-p10").arguments[2].exemple)

    def test_child_language_reuses_precise_questions_and_regular_family_calls(self):
        question = (
            "On peut poser ses propres questions et demander des précisions "
            "sur ce qu'on n'a pas compris."
        )
        child = self.response("famille-p13").arguments[1]
        self.assertIn(question, child.developpement)
        self.assertIn(question, self.response("culture-p14").arguments[2].developpement)
        for example in (child.exemple, self.response("culture-p27").arguments[2].exemple):
            self.assertIn("chaque semaine à", example)
            self.assertIn("dans leur langue familiale", example)
        self.assertIn("ses grands-parents", child.exemple)
        self.assertIn("sa sœur", self.response("culture-p27").arguments[2].exemple)
        self.assertIn("bilinguisme parfait n'est pas garanti", self.response("famille-p13").nuance)

    def test_cuisine_and_local_workshops_share_guided_practice_not_their_positions(self):
        practice = (
            "En y participant, on apprend les gestes en les faisant soi-même, "
            "avec quelqu'un pour nous guider."
        )
        self.assertIn(practice, self.response("culture-p14").arguments[1].developpement)
        self.assertIn(practice, self.response("culture-p15").arguments[2].developpement)
        self.assertIn("danse irlandaise", self.response("culture-p14").arguments[1].exemple)
        self.assertIn("cuisine mexicaine", self.response("culture-p15").arguments[2].exemple)
        self.assertNotEqual(
            self.models["eo/tache-3/culture-p14"].source_prompts,
            self.models["eo/tache-3/culture-p15"].source_prompts,
        )
