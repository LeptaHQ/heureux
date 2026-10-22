from django.test import SimpleTestCase

from study import catalogue, content_loader as content


class CultureEditorialTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sources = content.parse_responses()

    def setUp(self):
        catalogue.clear_catalogue_cache()
        self.addCleanup(catalogue.clear_catalogue_cache)
        self.models = catalogue.tache_three_models()
        self.plans = catalogue.tache_three_subject_hints()

    def response(self, number):
        return self.models[f"eo/tache-3/culture-p{number}"].response

    def test_every_culture_consigne_uses_the_matching_model_and_argument_cues(self):
        sources = [source for source in self.sources if source.theme == "Culture"]
        self.assertEqual(len(sources), 31)
        self.assertEqual(sum(len(source.prompts) for source in sources), 39)
        self.assertEqual(
            sum(prompt.theme == "Culture" for source in sources for prompt in source.prompts),
            35,
        )
        for source in sources:
            with self.subTest(group=source.semantic_group):
                model = self.models[source.semantic_group]
                plan = self.plans[source.semantic_group]
                self.assertEqual(
                    model.source_prompts,
                    tuple((prompt.content_key, prompt.text) for prompt in source.prompts),
                )
                for prefix, argument, cue in zip(
                    ("Tout d'abord, ", "Ensuite, ", "Enfin, "),
                    model.response.arguments,
                    plan.arguments,
                    strict=True,
                ):
                    self.assertEqual(
                        argument.idea.removeprefix(prefix).casefold(),
                        cue.point.french.casefold(),
                    )

    def test_related_youth_questions_reuse_language_without_merging_the_actors(self):
        adults = self.response(2)
        older_people = self.response(8)
        self.assertEqual(
            [argument.idea for argument in adults.arguments],
            [argument.idea for argument in older_people.arguments],
        )
        self.assertEqual(
            adults.arguments[2].developpement,
            older_people.arguments[2].developpement,
        )
        self.assertIn("un adulte", adults.arguments[2].exemple)
        self.assertIn("une personne âgée", older_people.arguments[2].exemple)
        older_cue = self.plans["eo/tache-3/culture-p8"].arguments[2].example
        self.assertIn("personne âgée", older_cue.french)
        self.assertIn("older person", older_cue.english)
        self.assertNotEqual(adults, older_people)
        self.assertNotEqual(
            self.models["eo/tache-3/culture-p2"].source_prompts,
            self.models["eo/tache-3/culture-p8"].source_prompts,
        )

    def test_examples_demonstrate_concrete_prompt_faithful_mechanisms(self):
        for number, argument, required in (
            (1, 2, ("à 14 heures", "à midi", "une fois par semaine", "le week-end")),
            (4, 2, ("a droit", "aide au logement", "formulaire")),
            (6, 0, ("un essai", "la voiture en ville", "la pollution", "sans transports en commun", "interdiction totale")),
            (11, 0, ("sa solitude en français", "une amie de son pays qui parle sa langue", "le dimanche ensemble")),
            (11, 1, ("traduire un diplôme", "quelles traductions sont acceptées")),
            (15, 1, ("sa grand-mère", "sécher des tomates", "conserver jusqu'en hiver")),
            (19, 2, ("en français", "une ancienne usine", "devenue un lieu culturel", "poser des questions")),
            (20, 1, ("sans passer par un texte",)),
            (24, 1, ("dans leur équipe", "dès qu'elles apparaissent", "corriger un dossier avant son envoi")),
            (26, 2, ("prévoir leurs visites à l'avance", "manque de sympathie")),
            (30, 2, ("profession est réglementée", "avant d'exercer", "ne remplace ni")),
            (31, 1, ("moquerie", "humiliée", "relation réelle")),
            (35, 2, ("distribution alimentaire", "La famille comprend", "comme les autres bénévoles, il contribue")),
        ):
            with self.subTest(response=number, argument=argument + 1):
                example = self.response(number).arguments[argument].exemple
                for phrase in required:
                    self.assertIn(phrase, example)

    def test_compatriot_support_explains_new_social_ties_without_rewriting_the_example(self):
        argument = self.response(11).arguments[0]
        self.assertEqual(
            argument.developpement,
            "Quand on arrive à l'étranger, on peut se retrouver loin de son entourage habituel. "
            "Fréquenter des compatriotes qui parlent sa langue permet de nouer des liens sans "
            "attendre de bien maîtriser la langue du pays.",
        )
        self.assertEqual(
            argument.exemple,
            "Une nouvelle arrivante peut avoir du mal à expliquer sa solitude en français. "
            "Avec une amie de son pays qui parle sa langue, elle raconte que sa famille lui manque. "
            "Son amie l'écoute et lui propose de passer le dimanche ensemble.",
        )

    def test_family_transmission_example_stops_after_fetes_without_a_classmates_clause(self):
        example = self.response(10).arguments[1].exemple
        self.assertTrue(
            example.endswith(
                "L'enfant découvre cette tradition familiale tout en participant aux fêtes."
            )
        )
        self.assertNotIn("camarades", example)
        cue = self.plans["eo/tache-3/culture-p10"].arguments[1].example
        self.assertNotIn("camarades", cue.french)
        self.assertNotIn("classmates", cue.english)

    def test_adaptation_cue_means_adapting_to_constraints_not_changing_them(self):
        cue = self.plans["eo/tache-3/culture-p1"].conclusion
        self.assertIn("S'adapter aux contraintes", cue.french)
        self.assertIn("Adapt to constraints", cue.english)

    def test_living_abroad_example_links_cooking_training_to_a_clear_career_goal(self):
        example = self.response(5).arguments[0].exemple
        for phrase in (
            "devenir cuisinier", "spécialité qui n'est pas enseignée près de chez lui",
            "Une école à l'étranger", "stage en restaurant", "apprendre le métier",
        ):
            self.assertIn(phrase, example)
        self.assertNotIn("irrigation", example)
        cue = self.plans["eo/tache-3/culture-p5"].arguments[0].example
        self.assertIn("formation de cuisine", cue.french)
        self.assertIn("restaurant placement", cue.english)

    def test_adaptation_keeps_the_preferred_preferences_and_practical_response_wording(self):
        self.assertEqual(
            self.response(1).arguments[0].developpement,
            "Le climat et les horaires ne dépendent pas de nos préférences. "
            "En tenir compte permet de travailler, de se déplacer et d'organiser "
            "ses journées sans se mettre inutilement en difficulté.",
        )

    def test_direct_framing_keeps_friendship_optional_and_integration_reciprocal(self):
        happiness = self.response(16)
        self.assertIn("on peut être heureux sans avoir d'amis", happiness.position_claire)
        self.assertNotIn("personne ne peut", happiness.position_claire)
        self.assertIn("une solitude choisie", happiness.nuance)
        integration = self.response(30).arguments[1]
        self.assertIn("chacun ait envie de poursuivre l'échange", integration.developpement)
        self.assertIn("ne peuvent pas créer seuls une relation", integration.developpement)
        self.assertIn("le groupe l'invite", integration.exemple)

    def test_adaptation_introduction_keeps_the_preferred_living_abroad_wording(self):
        introduction = self.response(9).position_claire
        self.assertIn(
            "Vivre à l'étranger ne consiste pas seulement à y habiter : "
            "il faut communiquer dans un nouvel environnement",
            introduction,
        )
        self.assertNotIn("une question de bonne volonté", introduction)

    def test_book_usefulness_keeps_the_original_reflection_and_concentration_argument(self):
        group = "eo/tache-3/culture-p6"
        response = self.models[group].response
        source = next(source for source in self.sources if source.semantic_group == group)
        original = source.prompts[0].model_content["arguments"][0]
        argument = response.arguments[0]
        self.assertEqual(argument.idea, original["idea"])
        self.assertIn("suivre une pensée longue", argument.developpement)
        self.assertIn("tenir son attention", argument.developpement)
        self.assertIn("examiner un raisonnement dans son ensemble", argument.developpement)
        self.assertIn("un jugement plus réfléchi", argument.consequence)
        cue = self.plans[group].arguments[0]
        for language in ("french", "english"):
            point = getattr(cue.point, language)
            self.assertIn("réflexion" if language == "french" else "reflection", point)
            self.assertIn("concentration", point)
        self.assertIn("transports en commun", cue.example.french)
        self.assertIn("public transport", cue.example.english)
        self.assertIn("un livre peut aussi se lire sur un écran", response.nuance)

    def test_reading_necessity_and_personal_cultural_forgetting_keep_their_scope(self):
        reading = self.response(20)
        self.assertIn("la lecture n'est pas indispensable", reading.conclusion)
        self.assertIn("sans passer par un texte", reading.arguments[1].exemple)
        self.assertNotIn("elle lit peu", reading.arguments[1].exemple)
        forgetting = self.response(27)
        self.assertEqual(self.models["eo/tache-3/culture-p27"].argument_ids, (1, 4, 3))
        self.assertIn("moins utiliser sa langue d'origine", forgetting.arguments[0].idea)
        self.assertIn("Elle le connaissait bien autrefois", forgetting.arguments[0].exemple)
        self.assertIn("ne se souvient plus de sa signification", forgetting.arguments[0].exemple)
        self.assertIn("même si l'on continue à parler sa langue d'origine", forgetting.arguments[1].developpement)
        self.assertIn("qui savait tresser", forgetting.arguments[1].exemple)
        self.assertIn("peut oublier le geste", forgetting.arguments[1].exemple)
        self.assertIn("lui remontrer le geste", forgetting.arguments[1].exemple)
        self.assertNotIn("Les enfants", forgetting.arguments[1].developpement)
        self.assertIn("la durée du séjour", forgetting.arguments[2].consequence.casefold())
        self.assertIn("n'est pas nécessairement oublier", forgetting.nuance)

    def test_material_difficulty_includes_time_and_fatigue_not_only_expenses(self):
        response = self.response(29)
        material = response.arguments[0]
        self.assertIn("le travail et le logement", material.idea)
        self.assertIn("trajet quotidien", material.exemple)
        self.assertIn("son budget, sa fatigue", material.exemple)
        self.assertIn("contraintes qui peuvent durer", material.consequence)
        self.assertIn("d'être à leurs côtés", response.arguments[1].idea)
        self.assertIn("après une opération", response.arguments[1].exemple)

    def test_memory_cues_explain_abstract_terms_in_their_actual_context(self):
        poverty = self.plans["eo/tache-3/culture-p4"].conclusion
        self.assertIn("Répondre aux besoins essentiels", poverty.french)
        self.assertIn("Meet basic needs", poverty.english)
        cooking = self.plans["eo/tache-3/culture-p15"].introduction.english
        self.assertIn("mealtime customs", cooking)
        self.assertIn("history of recipes", cooking)
        self.assertIn("get to know each other", cooking)
        celebrity = self.plans["eo/tache-3/culture-p33"].nuance.english
        self.assertIn("extra media attention", celebrity)
        self.assertIn("competence by fame alone", celebrity)
        immigration = self.plans["eo/tache-3/culture-p35"].nuance
        for phrase in ("l'emploi", "logement", "respect", "contribution économique"):
            self.assertIn(phrase, immigration.french)
        for phrase in ("jobs", "housing", "Everyone deserves respect", "whether or not"):
            self.assertIn(phrase, immigration.english)
