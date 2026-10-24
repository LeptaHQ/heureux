from dataclasses import asdict
from hashlib import sha256
import json

from django.test import SimpleTestCase

from study import catalogue, content_loader as content
from study.tache_three_models import spoken_text


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

    def test_explicitly_excluded_canadian_cohabitation_is_unchanged(self):
        directory = content.CONTENT_DIR / "tache_3"
        for filename, expected in (
            ("responses/famille.json", "870c863086dcae67336853076b5408c3db89028b3c30e07572fce9e683323c7f"),
            ("hints.json", "5ddc21b9b69a3f3fa715d2464df8fc14306310726c64eafe037ec51ad39681cd"),
            ("prompt_notes.json", "1421a647b36b31652e877a8703a8269b9e7e759a06e4658dfa8e47216aa097f9"),
        ):
            with self.subTest(file=filename):
                text = (directory / filename).read_text()
                start = text.index("{", text.index('"famille-p2":'))
                _, end = json.JSONDecoder().raw_decode(text[start:])
                self.assertEqual(
                    sha256(text[start:start + end].encode()).hexdigest(), expected,
                )
        source = next(
            source for source in self.sources
            if source.semantic_group == "eo/tache-3/famille-p2"
        )
        self.assertEqual(
            tuple((prompt.content_key, prompt.text) for prompt in source.prompts),
            ((
                "famille:p2",
                "De jeunes adultes canadiens préfèrent rester vivre chez leurs parents "
                "parce qu'ils s'y sentent bien. Quel regard porterez-vous sur cette situation ?",
            ),),
        )
        self.assertEqual(
            sha256(json.dumps(asdict(source), ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
            "61b617cf7b6ea45f02d61ec0edb82b467d92a3ce9cf4296072099baf5c3a914d",
        )

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
                self.assertEqual(len(model.response.arguments), 3)
                self.assertEqual(len(plan.arguments), 3)
                self.assertTrue(300 <= len(spoken_text(model.response).split()) <= 430)
                cues = (
                    plan.introduction,
                    *(cue for argument in plan.arguments for cue in (
                        argument.point, argument.example,
                    )),
                    plan.nuance, plan.conclusion,
                )
                self.assertEqual(len(cues), 9)
                self.assertLessEqual(sum(len(cue.french.split()) for cue in cues), 140)
                self.assertEqual(
                    model.argument_ids,
                    {
                        "eo/tache-3/culture-p16": (1, 4, 5),
                        "eo/tache-3/famille-p1": (4, 2, 3),
                    }.get(model.group, (1, 2, 3)),
                )

    def test_consequences_explain_results_instead_of_adding_fresh_advice(self):
        for number, index, result in (
            (1, 1, "se reposer sans devoir répondre"),
            (3, 0, "financièrement réaliste"),
            (4, 0, "continuant à croire les explications"),
            (5, 0, "ressentir le manque de sa famille"),
            (6, 1, "un progrès réel sans récompense"),
            (7, 1, "relations familiales"),
            (10, 2, "respect montré"),
            (11, 1, "augmenter la dépense de chacune"),
            (12, 2, "organiser son travail"),
            (13, 2, "participer aux activités"),
            (14, 0, "du temps pour se reposer"),
        ):
            with self.subTest(model=number, argument=index + 1):
                self.assertIn(result, self.response(number).arguments[index].consequence)
        self.assertIn("Une personne sans amis", self.response(9).nuance)
        self.assertIn("son conjoint", self.response(9).nuance)
        self.assertIn("un coup de main", self.response(9).nuance)
        self.assertIn("respecte son choix", self.response(10).arguments[2].exemple)
        self.assertNotIn("indépendance", self.response(11).arguments[1].consequence)

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

    def test_social_media_permission_has_a_supported_benefit_not_only_access_rules(self):
        response = self.response(1)
        self.assertTrue(response.position_claire.startswith("Oui, "))
        friendship, rest, safety = response.arguments
        for phrase in ("change de collège", "anciens camarades", "groupe privé", "une sortie"):
            self.assertIn(phrase, friendship.exemple)
        self.assertIn("entretenir ses amitiés", friendship.idea)
        self.assertIn("le sommeil et la concentration", rest.idea)
        self.assertIn("jusqu'à minuit", rest.exemple)
        self.assertIn("couper les notifications", rest.exemple)
        self.assertIn("peur d'être puni", safety.developpement)
        self.assertIn("un adulte de confiance", safety.exemple)
        self.assertIn("bloquent le contact et signalent le message", safety.exemple)
        self.assertIn("conditions d'accès", response.nuance)
        self.assertIn("ni lire systématiquement tous les messages privés", response.nuance)

    def test_family_friendship_depends_on_trust_not_kinship_or_hobbies_alone(self):
        response = self.response(10)
        self.assertIn("on craint de les inquiéter ou de les décevoir", response.arguments[1].developpement)
        self.assertIn("notre meilleur ami", response.arguments[2].idea)
        self.assertIn("respecte son choix", response.arguments[2].exemple)
        self.assertIn("sans répéter ses confidences", response.arguments[2].exemple)
        self.assertIn("goûts différents", response.nuance)
        self.assertIn("Partager les mêmes loisirs ne suffit pas", response.nuance)
        self.assertIn("respecter les choix de l'autre", response.nuance)

    def test_household_reuse_does_not_force_friendship_necessity_arguments(self):
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
        self.assertIn("l'amitié", living_well.arguments[1].idea)
        self.assertIn("liens familiaux ou de couple", happiness.arguments[1].idea)
        self.assertIn("chorale", living_well.arguments[2].exemple)
        self.assertIn("potager", happiness.arguments[2].exemple)
        self.assertNotEqual(living_well.arguments[0].idea, happiness.arguments[0].idea)

    def test_examples_make_the_actor_action_and_mechanism_explicit(self):
        for number, argument, required in (
            (3, 0, ("grand-père", "quitté son emploi", "coût de sa formation", "avant de démissionner")),
            (3, 1, ("deux écoles", "cours théoriques", "ateliers", "tante âgée")),
            (3, 2, ("grand-père", "son CV", "candidature en ligne")),
            (4, 1, ("le mercredi", "à l'hôpital après une chute", "un appel", "sans promettre une guérison")),
            (4, 2, ("match de tennis perdu", "raté beaucoup de services", "erreur d'arbitrage", "à l'entraînement")),
            (5, 1, ("grands-parents, qui récupéraient", "voisine de confiance", "déjà autorisée", "récupérer son enfant", "Elle accepte")),
            (5, 2, ("huit heures de train", "anniversaire de son père", "deux jours de congé", "dépasse son budget", "renonce donc à venir")),
            (6, 0, ("dix euros", "refuse de refaire", "la correction n'est pas notée", "ne lui rapportera pas d'argent")),
            (6, 1, ("de 8 à 12 sur 20", "plusieurs semaines de travail", "qu'à partir de 15", "de vrais progrès")),
            (6, 2, ("additionne", "comparer", "reformuler la consigne", "l'enseignant", "le plus grand nombre")),
            (7, 1, ("au repas familial", "Leur mère prend parti", "se sent jugée", "les relations se tendent")),
            (7, 2, ("son cousin", "vingt heures par semaine", "ses missions", "sa rémunération", "un samedi supplémentaire", "gratuitement")),
            (9, 1, ("vit seule et travaille chez elle", "une promenade chaque samedi", "raconte sa semaine", "la semaine suivante")),
            (9, 2, ("aimerait chanter mais n'ose pas", "accompagner un ami", "séance d'essai dans une chorale")),
            (10, 1, ("menuiserie", "ses doutes", "sur son revenu", "projet plus clair")),
            (10, 2, ("une autre ville", "sans répéter ses confidences", "comparer les logements")),
            (11, 1, ("Deux sœurs", "quarante euros par mois", "vingt euros chacune", "deux abonnements au lieu d'un")),
            (11, 2, ("Dans un couple", "prépare le dîner", "les courses le lendemain", "déjà prêt à son retour")),
            (12, 0, ("sept ans", "sa sieste", "dessiner dans une autre pièce", "pendant que le bébé dort")),
            (12, 1, ("livre de bibliothèque", "en parle", "sans crier", "remplacer")),
            (12, 2, ("propose", "dix-sept heures", "avant le dîner", "Une semaine plus tard", "sans qu'elle ait à le lui rappeler")),
            (13, 0, ("refusé de jouer avec lui", "sa mère", "langue familiale", "le rassurer", "langue qu'elle maîtrise mal")),
            (13, 1, ("chaque semaine", "ses grands-parents", "ses jeux d'enfance", "les mots qu'il ne comprend pas")),
            (13, 2, ("conseils de l'enseignant", "bibliothèque", "marionnette", "demander du papier", "langue locale")),
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

    def test_post_25_support_and_household_planning_are_actual_benefits(self):
        cohabitation = self.response(16)
        self.assertIn("cadre familier", cohabitation.arguments[2].idea)
        self.assertIn("personnes avec qui parler", cohabitation.arguments[2].developpement)
        self.assertIn("Après une séparation", cohabitation.arguments[2].exemple)
        self.assertIn("sans devoir demander la permission", cohabitation.arguments[2].exemple)
        self.assertIn("financière, pratique et affective", cohabitation.conclusion)
        planning = self.response(14).arguments[2]
        self.assertIn("les oublis peuvent interrompre", planning.developpement)
        self.assertIn("avant qu'ils manquent", planning.exemple)
        self.assertIn("sans interrompre son travail", planning.exemple)
