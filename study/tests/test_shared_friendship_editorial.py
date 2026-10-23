from django.test import SimpleTestCase

from study import catalogue, content_loader as content
from study.tache_three_models import spoken_text


class SharedFriendshipEditorialTests(SimpleTestCase):
    def test_both_publications_answer_necessity_with_actual_counterexamples(self):
        group = "eo/tache-3/culture-p16"
        model = catalogue.tache_three_models()[group]
        source = next(
            source for source in content.parse_responses()
            if source.semantic_group == group
        )
        self.assertEqual(
            model.source_prompts,
            (
                ("culture:p16", "Il n'est pas nécessaire d'avoir des ami(e)s pour être heureux(se). Qu'en pensez-vous ?"),
                ("famille:p8", "Il n'est pas nécessaire d'avoir des ami(e)s pour être heureux(se). Qu'en pensez-vous ?"),
            ),
        )
        self.assertEqual(model.argument_ids, (1, 4, 5))
        self.assertEqual(source.prompts[0].model_content, source.prompts[1].model_content)
        response = model.response
        self.assertIn("on peut être heureux sans avoir d'amis", response.position_claire)
        self.assertIn("écoute et pose des questions", response.arguments[0].developpement)
        self.assertIn("Elle se sent écoutée", response.arguments[0].consequence)
        for argument, demonstration in (
            (response.arguments[1], "son conjoint"),
            (response.arguments[2], "sa récolte"),
        ):
            self.assertIn("Une personne qui n'a pas d'amis", argument.exemple)
            self.assertIn(demonstration, argument.exemple)
        self.assertIn("voir le résultat de ses efforts", response.arguments[2].developpement)
        self.assertIn("en dehors d'une relation amicale", response.arguments[2].consequence)
        self.assertIn("solitude choisie", response.nuance)
        self.assertIn("isolement qui fait souffrir", response.nuance)
        self.assertIn("Je ne recommande donc pas de vivre sans amis", response.nuance)
        self.assertIn("sans qu'on ait d'amis", spoken_text(response))
        self.assertLessEqual(300, len(spoken_text(response).split()))
        self.assertLessEqual(len(spoken_text(response).split()), 430)

    def test_bilingual_plan_keeps_no_friends_not_merely_no_local_friends(self):
        group = "eo/tache-3/culture-p16"
        response = catalogue.tache_three_models()[group].response
        plan = catalogue.tache_three_subject_hints()[group]
        for prefix, argument, cue in zip(
            ("Tout d'abord, ", "Ensuite, ", "Enfin, "),
            response.arguments, plan.arguments, strict=True,
        ):
            self.assertEqual(
                argument.idea.removeprefix(prefix).casefold(),
                cue.point.french.casefold(),
            )
        for cue in plan.arguments[1:]:
            self.assertIn("Sans avoir d'amis", cue.example.french)
            self.assertIn("without", cue.example.english)
            self.assertIn("friends", cue.example.english)
            self.assertNotIn("local", cue.example.english)
