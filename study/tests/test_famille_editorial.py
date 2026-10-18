from django.test import SimpleTestCase

from study import catalogue, content_loader as content


class FamilleEditorialTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sources = [
            source for source in content.parse_responses()
            if any(prompt.theme == "Famille" for prompt in source.prompts)
        ]

    def setUp(self):
        catalogue.clear_catalogue_cache()
        self.addCleanup(catalogue.clear_catalogue_cache)
        self.models = catalogue.tache_three_models()
        self.plans = catalogue.tache_three_subject_hints()

    def response(self, number):
        return self.models[f"eo/tache-3/famille-p{number}"].response

    def test_every_famille_consigne_matches_its_model_and_bilingual_plan(self):
        self.assertEqual(len(self.sources), 15)
        self.assertEqual(sum(len(source.prompts) for source in self.sources), 18)
        self.assertEqual(sum(
            prompt.theme == "Famille"
            for source in self.sources for prompt in source.prompts
        ), 17)
        for source in self.sources:
            with self.subTest(group=source.semantic_group):
                model = self.models[source.semantic_group]
                plan = self.plans[source.semantic_group]
                self.assertEqual(model.source_prompts, tuple(
                    (prompt.content_key, prompt.text) for prompt in source.prompts
                ))
                for prefix, argument, cue in zip(
                    ("Tout d'abord, ", "Ensuite, ", "Enfin, "),
                    model.response.arguments, plan.arguments, strict=True,
                ):
                    self.assertEqual(
                        argument.idea.removeprefix(prefix).casefold(),
                        cue.point.french.casefold(),
                    )

    def test_equivalence_does_not_merge_related_but_distinct_questions(self):
        groups = {
            key: model.group
            for model in self.models.values() for key, _ in model.source_prompts
        }
        for first, second in (
            ("famille:p4", "famille:p17"),
            ("famille:p6", "famille:p15"),
            ("famille:p8", "culture:p16"),
        ):
            self.assertEqual(groups[first], groups[second])
        for first, second in (
            ("famille:p2", "famille:p16"),
            ("famille:p8", "famille:p9"),
            ("famille:p9", "famille:p10"),
        ):
            self.assertNotEqual(groups[first], groups[second])

    def test_sound_household_and_friendship_arguments_are_reused_deliberately(self):
        comfort = self.response(2).arguments[2]
        practical = self.response(16).arguments[1]
        self.assertEqual(
            comfort.idea.removeprefix("Enfin, "),
            practical.idea.removeprefix("Ensuite, "),
        )
        self.assertEqual(comfort.developpement, practical.developpement)
        self.assertEqual(comfort.exemple, practical.exemple)
        self.assertEqual(
            self.plans["eo/tache-3/famille-p2"].arguments[2],
            self.plans["eo/tache-3/famille-p16"].arguments[1],
        )
        living_well = self.response(9)
        happiness = self.models["eo/tache-3/culture-p16"].response
        self.assertEqual(living_well.arguments[1].idea, happiness.arguments[1].idea)
        self.assertEqual(
            living_well.arguments[2].developpement,
            happiness.arguments[2].developpement,
        )
        self.assertEqual(living_well.arguments[2].exemple, happiness.arguments[2].exemple)
        self.assertNotEqual(living_well.arguments[0].idea, happiness.arguments[0].idea)

    def test_examples_make_the_actor_action_and_mechanism_explicit(self):
        for number, argument, required in (
            (3, 1, ("deux écoles", "cours théoriques", "ateliers", "tante âgée")),
            (4, 2, ("calcul", "retenue oubliée", "vérifier la méthode")),
            (6, 2, ("reformuler la consigne", "l'enseignant", "L'argent seul")),
            (10, 1, ("S'il craint", "clarifier son projet")),
            (10, 2, ("une autre ville", "sans répéter ses confidences", "comparer les logements")),
            (11, 1, ("Deux sœurs", "deux abonnements au lieu d'un")),
            (12, 1, ("livre de bibliothèque", "S'il sait", "lui en parler", "remplacer")),
            (16, 0, ("contribution financière", "si la cohabitation coûte moins cher", "la différence")),
        ):
            with self.subTest(response=number, argument=argument + 1):
                for phrase in required:
                    self.assertIn(phrase, self.response(number).arguments[argument].exemple)
        older_adviser = self.plans["eo/tache-3/famille-p3"].arguments[1].example
        self.assertIn("tante âgée", older_adviser.french)
        self.assertIn("older aunt", older_adviser.english)

    def test_comfort_is_not_conditional_on_a_financing_project_or_moving_out(self):
        comfort = self.response(2)
        self.assertIn("Se sentir bien chez ses parents n'est pas un défaut", comfort.position_claire)
        self.assertNotIn("simple confort sans réflexion", comfort.arguments[1].consequence)
        self.assertIn("sans faire du départ immédiat une obligation", comfort.arguments[1].consequence)
        self.assertIn("l'accord des parents", self.response(16).nuance)
        self.assertTrue(self.response(11).position.startswith("Vivre seul"))
