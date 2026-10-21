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
            (11, 0, ("un compatriote qui parle sa langue",)),
            (11, 1, ("traduire un diplôme", "quelles traductions sont acceptées")),
            (15, 1, ("légumes d'été", "en hiver", "histoire familiale")),
            (19, 2, ("en français", "une fête locale", "gestes")),
            (20, 1, ("sans passer par un texte",)),
            (24, 1, ("quel déchet va dans quel bac",)),
            (26, 2, ("prévoir leurs visites à l'avance", "manque de sympathie")),
            (30, 2, ("profession est réglementée", "avant d'exercer", "ne remplace ni")),
            (31, 1, ("moquerie", "humiliée", "relation réelle")),
            (35, 2, ("distribution alimentaire", "La famille comprend", "comme les autres bénévoles, il contribue")),
        ):
            with self.subTest(response=number, argument=argument + 1):
                example = self.response(number).arguments[argument].exemple
                for phrase in required:
                    self.assertIn(phrase, example)

    def test_adaptation_cue_means_adapting_to_constraints_not_changing_them(self):
        cue = self.plans["eo/tache-3/culture-p1"].conclusion
        self.assertIn("S'adapter aux contraintes", cue.french)
        self.assertIn("Adapt to constraints", cue.english)

    def test_adaptation_keeps_the_preferred_preferences_and_practical_response_wording(self):
        self.assertEqual(
            self.response(1).arguments[0].developpement,
            "Le climat et les horaires ne dépendent pas de nos préférences. "
            "En tenir compte permet de travailler, de se déplacer et d'organiser "
            "ses journées sans se mettre inutilement en difficulté.",
        )

    def test_direct_framing_keeps_friendship_optional_and_integration_reciprocal(self):
        happiness = self.response(16)
        self.assertIn("on peut aussi être heureux sans eux", happiness.position_claire)
        self.assertNotIn("personne ne peut", happiness.position_claire)
        self.assertIn("une solitude choisie", happiness.nuance)
        integration = self.response(30).arguments[1]
        self.assertIn("chacun ait envie de poursuivre l'échange", integration.developpement)
        self.assertIn("ne peuvent pas créer seuls une relation", integration.developpement)
        self.assertIn("le groupe l'invite", integration.exemple)

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
        self.assertIn("chansons apprises dans son enfance", forgetting.arguments[0].exemple)
        self.assertIn("raconter les préparatifs", forgetting.arguments[1].exemple)
        self.assertIn("son calendrier a changé, pas tous ses souvenirs", forgetting.arguments[1].exemple)
        self.assertNotIn("Les enfants", forgetting.arguments[1].developpement)
        self.assertIn("la durée du séjour", forgetting.arguments[2].consequence.casefold())
        self.assertIn("n'est pas nécessairement oublier", forgetting.nuance)
