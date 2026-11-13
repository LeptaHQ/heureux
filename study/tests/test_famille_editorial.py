from dataclasses import asdict
from hashlib import sha256
import json

from django.test import SimpleTestCase

from study.catalogue import registry as catalogue
from study.catalogue import loader as content
from study.expression.eo.tache_3.responses import spoken_text


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

    def test_explicitly_excluded_social_media_is_unchanged_and_source_questions_are_preserved(self):
        directory = content.EO_TACHE_THREE_THEMES_DIR / "famille"
        for filename, expected in (
            ("responses.json", "5ef80786d694866c5a1b51903d077f5c677a4c8172a99e57290ef07dc3aecc32"),
            ("hints.json", "93b28f319989346b55a7248e3848334878bcf1b98f70ccd62f26c5d4e4b58f79"),
            ("prompt_notes.json", "0eb6083b08547fb3733fa56dd7f36cfc6ea19b3eb9aae1d6230a86c6b720227a"),
        ):
            with self.subTest(file=filename):
                text = (directory / filename).read_text()
                start = text.index("{", text.index('"famille-p1":'))
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
                for argument, cue in zip(model.response.arguments, plan.arguments, strict=True):
                    self.assertTrue(argument.idea)
                    self.assertTrue(cue.point.french)
                    self.assertTrue(cue.point.english)
                self.assertEqual(len(model.response.arguments), 3)
                self.assertEqual(len(plan.arguments), 3)
                self.assertTrue(300 <= len(spoken_text(model.response).split()) <= 500)
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
                        "eo/tache-3/famille-p1": (5, 2, 3),
                        "eo/tache-3/famille-p2": (1, 5, 3),
                        "eo/tache-3/famille-p6": (1, 2, 4),
                        "eo/tache-3/famille-p9": (1, 3, 4),
                        "eo/tache-3/famille-p11": (1, 2, 4),
                        "eo/tache-3/famille-p12": (4, 2, 5),
                        "eo/tache-3/famille-p14": (1, 2, 4),
                        "eo/tache-3/famille-p16": (1, 2, 4),
                    }.get(model.group, (1, 2, 3)),
                )

    def test_consequences_explain_results_instead_of_adding_fresh_advice(self):
        for number, index, result in (
            (1, 1, "se reposer sans devoir répondre"),
            (3, 0, "financièrement réaliste"),
            (4, 0, "gardant confiance"),
            (5, 0, "La relation reste forte"),
            (6, 1, "ses efforts comptent"),
            (7, 1, "relations familiales"),
            (10, 2, "sans que cela soit une règle"),
            (11, 1, "Sur un petit budget"),
            (12, 2, "voit ses parents donner l'exemple"),
            (13, 2, "pratique la langue"),
            (14, 0, "profiter d'un moment de repos"),
        ):
            with self.subTest(model=number, argument=index + 1):
                self.assertIn(result, self.response(number).arguments[index].consequence)
        self.assertIn("Une personne sans amis", self.response(9).nuance)
        self.assertIn("son conjoint", self.response(9).nuance)
        self.assertIn("un coup de main", self.response(9).nuance)
        self.assertIn("histoire commune explique cette confiance", self.response(10).arguments[2].exemple)
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

    def test_excluded_social_media_keeps_privacy_rest_and_access_to_help(self):
        response = self.response(1)
        self.assertTrue(response.position_claire.startswith("À mon avis, les parents peuvent"))
        privacy, rest, safety = response.arguments
        for phrase in ("vidéo", "numéro de sa maison", "nom de la rue", "masquer"):
            self.assertIn(phrase, privacy.exemple)
        self.assertIn("inconnus", privacy.idea)
        self.assertIn("détriment du sommeil", rest.developpement)
        self.assertIn("jusqu'à minuit", rest.exemple)
        self.assertIn("téléphone dans le salon pendant la nuit", rest.exemple)
        self.assertIn("craindre d'être puni", safety.idea)
        self.assertIn("montre le message à son père", safety.exemple)
        self.assertIn("garder une preuve, puis bloquent et signalent", safety.exemple)
        self.assertIn("davantage de liberté quand il respecte les règles", response.nuance)
        self.assertIn("ce n'est pas lire tous ses messages", response.nuance)

    def test_family_friendship_depends_on_trust_not_kinship_or_hobbies_alone(self):
        response = self.response(10)
        self.assertIn("un humour, d'intérêts ou d'une façon de voir la vie", response.arguments[0].developpement)
        self.assertIn("discuter de musique ou rire pendant des heures", response.arguments[0].exemple)
        self.assertIn("on peut craindre de les inquiéter ou de les décevoir", response.arguments[1].developpement)
        self.assertIn("une amitié grâce à la confiance", response.arguments[2].idea)
        self.assertIn("garder une confidence et accepter un désaccord", response.arguments[2].developpement)
        self.assertIn("traversé des difficultés en se soutenant", response.arguments[2].exemple)
        self.assertIn("au-delà du simple lien de famille", response.arguments[2].exemple)
        self.assertIn("un meilleur ami extérieur à la famille", response.nuance)

    def test_household_reuse_does_not_force_friendship_necessity_arguments(self):
        comfort = self.response(2).arguments[2]
        practical = self.response(16).arguments[1]
        self.assertIn("un véritable échange", comfort.developpement)
        self.assertIn("l'aide fonctionne dans les deux sens", practical.developpement)
        self.assertIn("courses", comfort.exemple)
        self.assertIn("courses", practical.exemple)
        self.assertIn("adultes canadiens", self.response(2).position_claire)
        self.assertIn("après vingt-cinq ans", self.response(16).position_claire)
        living_well = self.response(9)
        happiness = self.models["eo/tache-3/culture-p16"].response
        self.assertIn("l'amitié", living_well.arguments[1].idea)
        self.assertIn("liens familiaux ou de couple", happiness.arguments[1].idea)
        self.assertIn("chorale", living_well.arguments[2].exemple)
        self.assertIn("piano", happiness.arguments[2].exemple)
        self.assertIn("de la joie en le rejouant", happiness.arguments[2].exemple)
        self.assertNotEqual(living_well.arguments[0].idea, happiness.arguments[0].idea)

    def test_examples_make_the_actor_action_and_mechanism_explicit(self):
        for number, argument, required in (
            (3, 0, ("grand-père", "quitté son emploi", "coût de sa formation", "avant de démissionner")),
            (3, 1, ("deux écoles", "cours théoriques", "ateliers", "tante âgée")),
            (3, 2, ("grand-père", "son CV", "candidature en ligne")),
            (4, 1, ("le mercredi", "à l'hôpital après une chute", "un appel", "sans promettre qu'elle guérira")),
            (4, 2, ("audition de piano", "Le début est solide", "tu hésites à la fin", "Reprenons-la lentement")),
            (5, 1, ("grands-parents", "récupérer son enfant", "autre personne de confiance", "quitter le travail plus tôt")),
            (5, 2, ("travaille", "huit heures de train", "son anniversaire", "deux jours de congé", "n'a pas les moyens de payer", "renoncer à la visite")),
            (6, 0, ("dix euros", "bonne note", "exposé non noté", "rapporte aussi de l'argent")),
            (6, 1, ("plusieurs semaines de travail", "sa note reste moyenne", "reconnaissent le chemin parcouru")),
            (6, 2, ("relu les consignes", "évité tes erreurs habituelles", "au prochain contrôle")),
            (7, 1, ("travaillent ensemble", "Au repas familial", "Leur mère prend parti", "se sent jugée", "les relations se tendent")),
            (7, 2, ("son cousin", "vingt heures par semaine", "ses missions", "sa rémunération", "un samedi supplémentaire", "gratuitement")),
            (9, 0, ("Une personne malade", "consultation de suivi à l'hôpital", "Un ami vient la chercher", "jusqu'au service", "puis la ramène chez elle")),
            (9, 1, ("vit seule et travaille chez elle", "une promenade chaque samedi", "raconte sa semaine", "la semaine suivante")),
            (9, 2, ("aimerait chanter mais n'ose pas", "Un ami l'accompagne", "séance d'essai", "répète chaque semaine", "premier concert")),
            (10, 1, ("une étudiante", "doute du cursus", "à une amie", "avant d'expliquer ses hésitations")),
            (10, 2, ("deux cousines", "la même école", "difficultés en se soutenant", "meilleures amies")),
            (11, 1, ("deux sœurs", "quarante euros par mois", "chacune paie vingt euros", "deux logements", "quarante euros chacune")),
            (11, 2, ("avant de rentrer chez elle", "opération du genou", "les courses avec sa sœur", "livraisons de repas")),
            (12, 0, ("continuer à jouer", "école le lendemain", "heure raisonnable pour le coucher", "dorme suffisamment")),
            (12, 1, ("livre de bibliothèque", "cacher dans son cartable", "sans être humilié", "réparer ou remplacer")),
            (12, 2, ("téléphones", "pendant le repas", "raconter sa journée", "rangent aussi les leurs", "moment en famille")),
            (13, 0, ("refusé de jouer avec lui", "sa mère", "leur langue commune", "le rassurer", "manque de vocabulaire")),
            (13, 1, ("grand-mère", "ancienne photo", "Son petit-fils", "où elle a été prise", "traduise chaque phrase")),
            (13, 2, ("des parents inscrivent", "au football", "Au fil des entraînements", "comprend mieux les consignes", "discuter avec ses coéquipiers")),
            (14, 0, ("deux parents rentrent du travail", "l'un peut préparer le dîner", "l'autre met la table", "vaisselle après le repas")),
            (14, 1, ("trier le linge", "utiliser la machine à laver", "plusieurs essais", "sans aide")),
            (14, 2, ("un frère et une sœur", "se disputent", "après le dîner", "sa sœur s'en chargera", "où il a entraînement", "La tâche est ainsi prévue")),
            (16, 0, ("vingt-sept ans", "neuf cents euros sans les charges", "Avec l'accord de ses parents", "trois cents euros par mois")),
            (16, 2, ("rentrera tard", "sans leur demander la permission", "ne pas les réveiller", "respectant leur repos")),
        ):
            with self.subTest(response=number, argument=argument + 1):
                for phrase in required:
                    self.assertIn(phrase, self.response(number).arguments[argument].exemple)
        older_adviser = self.plans["eo/tache-3/famille-p3"].arguments[1].example
        self.assertIn("tante âgée", older_adviser.french)
        self.assertIn("older aunt", older_adviser.english)

    def test_friendship_help_company_and_growth_explain_distinct_mechanisms(self):
        help_, company, growth = self.response(9).arguments
        self.assertIn("restent nécessaires alors qu'on a moins de forces", help_.developpement)
        self.assertIn("Un ami disponible", help_.developpement)
        self.assertIn("se rendre à sa consultation", help_.consequence)
        self.assertIn("partager son quotidien", company.developpement)
        self.assertIn("un repère dans la semaine", company.consequence)
        self.assertIn("on doute de ses capacités", growth.developpement)
        self.assertIn("persévérer malgré les difficultés", growth.developpement)
        self.assertIn("réaliser un projet", growth.consequence)
        self.assertNotIn("un avis différent", help_.developpement)
        self.assertNotIn("un avis différent", growth.developpement)

    def test_personal_advice_compares_choices_against_the_learners_needs(self):
        advice = self.response(3).arguments[1]
        self.assertIn("nos envies et nos contraintes", advice.developpement)
        self.assertIn("comparer plusieurs possibilités", advice.developpement)
        self.assertIn("trouver celle qui nous convient", advice.developpement)
        self.assertIn("son goût pour la pratique", advice.exemple)
        self.assertIn("sa façon d'apprendre", advice.exemple)

    def test_family_distance_explains_the_need_for_replacement_local_help(self):
        help_ = self.response(5).arguments[1]
        self.assertIn("reconstruire un réseau de personnes de confiance", help_.developpement)
        self.assertIn("qui appeler en cas d'imprévu", help_.developpement)
        self.assertIn("trouver une autre personne de confiance", help_.exemple)
        self.assertIn("demander à quitter le travail plus tôt", help_.exemple)

    def test_grade_encouragement_recognises_effort_even_without_a_perfect_mark(self):
        recognition = self.response(6).arguments[1]
        self.assertIn("cela mérite d'être reconnu, même si la note n'est pas parfaite", recognition.developpement)
        self.assertIn("sa note reste moyenne", recognition.exemple)
        self.assertIn("reconnaissent le chemin parcouru", recognition.exemple)
        self.assertIn("peut lui donner confiance", recognition.consequence)

    def test_family_language_conversation_keeps_its_causal_bridge(self):
        communication = self.response(13).arguments[0]
        self.assertIn("ils ne trouvent pas toujours les mots", communication.developpement)
        self.assertIn("la langue qu'ils maîtrisent le mieux", communication.developpement)
        self.assertIn("Dans leur langue commune", communication.exemple)
        self.assertIn("parler de ce qui compte", communication.consequence)

    def test_practical_help_explains_shared_effort_before_the_hospital_example(self):
        support = self.response(9).arguments[0]
        self.assertIn("restent nécessaires alors qu'on a moins de forces", support.developpement)
        self.assertIn("prendre une partie en charge", support.developpement)
        self.assertIn("consultation de suivi à l'hôpital", support.exemple)

    def test_friendship_encouragement_supports_progress_beyond_a_first_attempt(self):
        progress = self.response(9).arguments[2]
        self.assertIn("nous dépasser", progress.idea)
        self.assertIn("persévérer malgré les difficultés", progress.developpement)
        self.assertIn("sans qu'il décide à notre place", progress.developpement)
        self.assertIn("répète chaque semaine", progress.exemple)
        self.assertIn("premier concert", progress.exemple)
        self.assertIn("réaliser un projet", progress.consequence)

    def test_family_home_response_distinguishes_attachment_preparation_and_reciprocity(self):
        response = self.response(2)
        attachment, preparation, reciprocity = response.arguments
        self.assertIn("parce qu'ils s'y sentent bien", response.position_claire)
        self.assertIn("pas seulement dans le fait d'avoir une autre adresse", attachment.developpement)
        self.assertIn("leur raconter sa journée", attachment.exemple)
        self.assertIn("le bien-être est la première raison de rester", preparation.developpement)
        self.assertIn("premier salaire", preparation.developpement)
        self.assertIn("participer aux dépenses", preparation.exemple)
        self.assertIn("épargnant pour son futur logement", preparation.exemple)
        self.assertIn("plutôt qu'à la repousser", preparation.consequence)
        self.assertIn("un véritable échange", reciprocity.developpement)
        self.assertIn("ses parents rentrent tard", reciprocity.exemple)
        self.assertIn("évite de devoir tout gérer après le travail", reciprocity.exemple)
        self.assertIn("tout comme il peut compter sur eux", reciprocity.consequence)
        for phrase in ("convienne aussi aux parents", "repos et d'intimité", "repousser ses responsabilités"):
            self.assertIn(phrase, response.nuance)
        plan = self.plans["eo/tache-3/famille-p2"]
        self.assertIn("préparer son départ", plan.arguments[1].point.french)
        self.assertIn("prepare for leaving home", plan.arguments[1].point.english)
        self.assertIn("repos et l'intimité", plan.nuance.french)
        self.assertIn("rest and privacy", plan.nuance.english)

    def test_parental_authority_distinguishes_boundaries_fear_and_explained_rules(self):
        response = self.response(12)
        boundaries, fear, explained = response.arguments
        self.assertIn("pas d'un autoritarisme rigide", response.position_claire)
        self.assertIn("Ce cadre le protège", boundaries.developpement)
        self.assertIn("école le lendemain", boundaries.exemple)
        self.assertIn("prendre soin de lui", boundaries.consequence)
        self.assertIn("ne pas se faire prendre", fear.developpement)
        self.assertIn("cacher dans son cartable", fear.exemple)
        self.assertIn("S'il pouvait en parler sans être humilié", fear.exemple)
        self.assertTrue(fear.consequence.startswith("La peur produit du silence"))
        self.assertIn("Il faut que l'enfant comprenne pourquoi une limite existe", explained.developpement)
        self.assertIn("tout en restant fermes sur l'essentiel", explained.developpement)
        self.assertIn("pour que chacun puisse raconter sa journée", explained.exemple)
        self.assertIn("S'ils rangent aussi les leurs", explained.exemple)
        self.assertIn("voit ses parents donner l'exemple", explained.consequence)
        self.assertIn("ne veut pas dire tout permettre", response.nuance)
        self.assertIn("intervenir immédiatement et expliquer ensuite", response.nuance)
        plan = self.plans["eo/tache-3/famille-p12"]
        self.assertIn("sans humiliation", plan.arguments[1].example.french)
        self.assertIn("without humiliation", plan.arguments[1].example.english)
        self.assertIn("rangent aussi les leurs", plan.arguments[2].example.french)
        self.assertIn("they put theirs away too", plan.arguments[2].example.english)

    def test_comfort_is_not_conditional_on_a_financing_project_or_moving_out(self):
        comfort = self.response(2)
        self.assertIn("aimer la vie familiale n'est pas un défaut", comfort.position_claire)
        self.assertNotIn("simple confort sans réflexion", comfort.arguments[1].consequence)
        self.assertIn("le plus important n'est pas leur adresse", comfort.conclusion)
        self.assertIn("l'accord des parents", self.response(16).nuance)
        self.assertIn("vivre seul donne plus de liberté", self.response(11).position)

    def test_post_25_freedom_and_household_agreements_have_clear_limits(self):
        cohabitation = self.response(16)
        self.assertIn("la liberté et l'intimité de chacun", cohabitation.arguments[2].idea)
        self.assertIn("respecter les habitudes du foyer", cohabitation.arguments[2].developpement)
        self.assertIn("sans leur demander la permission", cohabitation.arguments[2].exemple)
        self.assertIn("respectant leur repos", cohabitation.arguments[2].exemple)
        self.assertIn("économies, entraide et liberté", cohabitation.conclusion)
        planning = self.response(14).arguments[2]
        self.assertIn("les rappels risquent de devenir des reproches", planning.developpement)
        self.assertIn("sauf les soirs d'entraînement", planning.exemple)
        self.assertIn("peut réduire les rappels et les disputes", planning.consequence)
