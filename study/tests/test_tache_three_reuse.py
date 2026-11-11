from django.test import SimpleTestCase

from study.catalogue import registry as catalogue


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
            ("culture-p18", "technologie-p12", (2,)),
        ):
            for index in indices:
                with self.subTest(first=first, second=second, argument=index + 1):
                    self.assertEqual(
                        self.response(first).arguments[index],
                        self.response(second).arguments[index],
                    )
                    self.assertEqual(self.cue(first, index), self.cue(second, index))
        for index in (0, 1):
            with self.subTest(argument=index + 1):
                self.assertNotEqual(
                    self.response("culture-p18").arguments[index],
                    self.response("technologie-p12").arguments[index],
                )
        self.assertIn("exprimer ses sentiments", self.response("culture-p18").arguments[1].idea)
        self.assertIn("clarifier ce que l'on veut vraiment dire", self.response("technologie-p12").arguments[1].idea)

    def test_cohabitation_answers_distinguish_parental_consent_from_reciprocal_help(self):
        comfort = self.response("famille-p2")
        practical = self.response("famille-p16")
        self.assertIn("se sentir bien chez ses parents", comfort.arguments[0].idea)
        self.assertIn("convienne aussi aux parents", comfort.nuance)
        self.assertIn("repos et d'intimité", comfort.nuance)
        self.assertIn("ne doit pas aller dans un seul sens", practical.arguments[1].idea)
        self.assertIn("prépare le dîner", practical.arguments[1].exemple)
        self.assertIn("sans demander l'autorisation de sortir", practical.arguments[2].exemple)
        self.assertNotEqual(comfort.arguments[1], practical.arguments[1])

    def test_live_questions_and_translated_explanations_keep_distinct_mechanisms(self):
        conversation = self.response("culture-p14").arguments[2]
        translation = self.response("culture-p19").arguments[1]
        self.assertIn("poser ses propres questions", conversation.idea)
        self.assertIn("demander une explication", conversation.developpement)
        self.assertIn("Un article traduit ou un documentaire sous-titré", translation.developpement)
        self.assertIn("la qualité des explications", translation.developpement)
        self.assertIn("sous-titré en français", translation.exemple)
        self.assertIn("les Pays-Bas", translation.exemple)
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
        self.assertIn("abîmé un livre de bibliothèque", self.response("famille-p12").arguments[1].exemple)
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
        self.assertIn("harcèlement", self.response("technologie-p16").arguments[2].developpement)
        self.assertIn("d'un inconnu", self.response("technologie-p16").arguments[2].exemple)
        child_help = self.response("famille-p1").arguments[2]
        self.assertIn("sans craindre d'être puni", child_help.idea)
        self.assertIn("garder une preuve", child_help.exemple)
        self.assertIn("Un inconnu demande une photo", child_help.exemple)
        self.assertIn("bloquent et signalent le compte", child_help.exemple)
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
        for group in ("culture-p18", "technologie-p12"):
            with self.subTest(group=group):
                nuance = self.response(group).nuance
                self.assertIn("un message numérique peut aussi être", nuance)
                self.assertIn("réfléchi", nuance)
                self.assertIn("conservé", nuance)
        solitude = "Cependant, il faut distinguer une solitude choisie d'un isolement qui fait souffrir."
        self.assertIn(solitude, self.response("culture-p24").nuance)
        self.assertIn("souffrir de solitude", self.response("culture-p16").nuance)
        self.assertIn("convienne aussi aux parents", self.response("famille-p2").nuance)
        self.assertIn("si chacun y trouve son compte", self.response("famille-p16").conclusion)

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

    def test_famille_distance_distinguishes_missed_moments_local_help_and_visits(self):
        family = self.response("famille-p5")
        self.assertIn("repas improvisé chez sa sœur", family.arguments[0].exemple)
        self.assertIn("ce moment s'est passé sans elle", family.arguments[0].exemple)
        self.assertIn("récupérer son enfant", family.arguments[1].exemple)
        self.assertIn("voisine de confiance", family.arguments[1].exemple)
        self.assertIn("déjà autorisée auprès de l'école", family.arguments[1].exemple)
        self.assertIn("Si elle n'est pas disponible", family.arguments[1].consequence)
        self.assertIn("vit et travaille", family.arguments[2].exemple)
        self.assertIn("Le billet dépasse aussi son budget", family.arguments[2].exemple)
        self.assertIn("elle renonce donc à la visite", family.arguments[2].exemple)
        self.assertNotEqual(family.arguments[0].exemple, self.response("culture-p9").arguments[1].exemple)
        self.assertIn("les débuts", self.response("culture-p9").arguments[1].idea)

    def test_familiar_routines_do_not_replace_adult_privacy_in_the_practical_answer(self):
        tradition = self.response("culture-p10").arguments[0]
        self.assertIn("un geste familier peut apporter du réconfort", tradition.developpement)
        self.assertIn("rendre le changement plus facile à vivre", tradition.consequence)
        self.assertIn("parler sa langue", self.response("culture-p1").arguments[1].exemple)
        self.assertIn("parents ne décident plus de tous ses choix", self.response("famille-p16").arguments[2].developpement)
        self.assertIn("respecte les espaces communs", self.response("famille-p16").arguments[2].exemple)

    def test_friendship_answers_support_nonnecessity_without_merging_their_benefits(self):
        happiness = self.response("culture-p16")
        living_well = self.response("famille-p9")
        self.assertIn("Elle n'a pas d'amis", happiness.arguments[1].consequence)
        self.assertIn("sa sœur l'écoute sans la juger", happiness.arguments[1].exemple)
        self.assertIn("consultation de suivi à l'hôpital", living_well.arguments[0].exemple)
        self.assertIn("poursuit les répétitions", living_well.arguments[1].exemple)
        self.assertIn("chante ensuite à son premier concert", living_well.arguments[1].exemple)
        self.assertIn("Un retraité sans amis", living_well.arguments[2].exemple)
        self.assertIn("sans avoir noué d'amitié", living_well.arguments[2].consequence)
        self.assertIn("connaissance ne remplace pas toujours un confident", living_well.nuance)

    def test_family_and_compatriot_trust_are_not_identity_guarantees(self):
        family = self.response("famille-p10")
        self.assertIn("la parenté ne la garantit pas", family.arguments[2].developpement)
        self.assertTrue(family.arguments[2].developpement.startswith("L'amitié suppose"))
        self.assertIn("ont grandi ensemble", family.arguments[2].exemple)
        self.assertIn("la même école", family.arguments[2].exemple)
        self.assertIn("se soutiennent", family.arguments[2].exemple)
        self.assertIn("pas seulement de leur parenté", family.arguments[2].consequence)
        self.assertIn("selon la confiance et les affinités, pas seulement selon l'origine", self.response("culture-p11").nuance)

    def test_child_language_keeps_direct_family_contact_distinct_from_parent_child_dialogue(self):
        conversation = self.response("culture-p14").arguments[2]
        self.assertIn("poser ses propres questions", conversation.idea)
        self.assertIn("demander une explication", conversation.developpement)
        child = self.response("famille-p13")
        self.assertIn("sa relation avec elle", child.arguments[1].consequence)
        self.assertIn("pose ses propres questions sans attendre sa mère", child.arguments[1].exemple)
        self.assertIn("Sa mère", child.arguments[0].exemple)
        self.assertIn("écoute les détails", child.arguments[0].exemple)
        self.assertIn("chaque semaine à", self.response("culture-p27").arguments[2].exemple)
        self.assertIn("sa sœur", self.response("culture-p27").arguments[2].exemple)
        self.assertIn("pas obligé de réserver une langue à la maison et l'autre à l'école", child.nuance)
        self.assertIn("lire une histoire dans la langue du pays", child.nuance)
        self.assertIn("parler la langue familiale pendant une promenade", child.nuance)

    def test_cuisine_and_local_workshops_demonstrate_guided_practice_without_merging_positions(self):
        dance = self.response("culture-p14").arguments[1]
        cooking = self.response("culture-p15").arguments[2]
        self.assertIn("on peut essayer, se tromper et recevoir des conseils", dance.developpement)
        self.assertIn("on observe, on essaie et l'autre personne nous guide", cooking.developpement)
        self.assertIn("danse irlandaise", self.response("culture-p14").arguments[1].exemple)
        self.assertIn("préparer du fufu", self.response("culture-p15").arguments[2].exemple)
        self.assertIn("sans bien parler sa langue", self.response("culture-p15").arguments[2].exemple)
        self.assertNotEqual(
            self.models["eo/tache-3/culture-p14"].source_prompts,
            self.models["eo/tache-3/culture-p15"].source_prompts,
        )
