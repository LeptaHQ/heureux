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
            (11, 1, ("Une infirmière", "compatriote", "fait reconnaître son diplôme", "quels documents", "à quel organisme")),
            (15, 1, ("sa grand-mère", "sécher des tomates", "conserver jusqu'en hiver", "jardin n'en donnait plus")),
            (15, 2, ("En préparant un repas de quartier", "voisins d'origines différentes", "épices", "habitudes de l'autre")),
            (19, 2, ("en français", "une ancienne usine", "devenue un lieu culturel", "poser des questions")),
            (20, 1, ("sans passer par un texte",)),
            (24, 1, ("association de quartier", "chacun apporte un plat", "dans la langue du pays", "d'autres rencontres")),
            (26, 2, ("prévoir leurs visites à l'avance", "manque de sympathie")),
            (30, 2, ("profession est réglementée", "avant d'exercer", "ne remplace ni")),
            (31, 1, ("moquerie", "humiliée", "relation réelle")),
            (35, 2, ("distribution alimentaire", "La famille comprend", "comme les autres bénévoles, il contribue")),
        ):
            with self.subTest(response=number, argument=argument + 1):
                example = self.response(number).arguments[argument].exemple
                for phrase in required:
                    self.assertIn(phrase, example)

    def test_television_value_includes_shared_experiences_and_nonproductive_rest(self):
        response = self.response(12)
        self.assertIn("objets mal triés", response.arguments[0].exemple)
        self.assertIn("consignes de tri de sa commune", response.arguments[0].exemple)
        self.assertIn("Ils s'appellent ensuite", response.arguments[1].exemple)
        self.assertIn("même si l'on n'apprend rien de nouveau", response.arguments[2].developpement)
        self.assertIn("éteint la télévision à la fin de l'épisode", response.arguments[2].exemple)
        plan = self.plans["eo/tache-3/culture-p12"]
        self.assertIn("à la fin de l'épisode", plan.arguments[2].example.french)
        self.assertIn("when the episode ends", plan.arguments[2].example.english)
        self.assertIn("ses proches", plan.nuance.french)
        self.assertIn("loved ones", plan.nuance.english)

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

    def test_compatriot_cultural_transmission_is_collective_and_nuance_keeps_other_connections(self):
        response = self.response(11)
        cultural = response.arguments[2]
        self.assertIn("d'autres familles", cultural.developpement)
        for phrase in (
            "association de compatriotes", "danse traditionnelle",
            "répètent ensemble", "fête de la communauté",
        ):
            self.assertIn(phrase, cultural.exemple)
        self.assertNotIn("sans exclure les autres habitants", cultural.developpement)
        for phrase in (
            "ne pas se limiter à ses compatriotes", "d'autres habitants",
            "pratiquer la langue du pays", "la confiance et les affinités",
        ):
            self.assertIn(phrase, response.nuance)
        plan = self.plans["eo/tache-3/culture-p11"]
        self.assertIn("Ne pas se limiter aux compatriotes", plan.nuance.french)
        self.assertIn("Get to know other residents", plan.nuance.english)
        self.assertIn("danse traditionnelle", plan.arguments[2].example.french)
        self.assertIn("traditional dance", plan.arguments[2].example.english)

    def test_compatriot_professional_example_shares_experience_without_guaranteeing_recognition(self):
        argument = self.response(11).arguments[1]
        self.assertIn("qui exerce déjà ce métier sur place", argument.exemple)
        self.assertIn("pour commencer ses démarches", argument.exemple)
        self.assertIn("l'information soit vérifiée auprès de l'organisme compétent", argument.consequence)
        self.assertNotIn("traducteur", argument.exemple)
        cue = self.plans["eo/tache-3/culture-p11"].arguments[1].example
        self.assertIn("Une infirmière", cue.french)
        self.assertIn("compatriote du même métier", cue.french)
        self.assertIn("A nurse", cue.english)
        self.assertIn("qualifications recognised", cue.english)
        self.assertIn("compatriot", cue.english)

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

    def test_living_abroad_skills_argument_focuses_on_training_and_professional_practice(self):
        argument = self.response(17).arguments[0]
        self.assertIn("se former", argument.idea)
        self.assertIn("compétences professionnelles", argument.idea)
        for phrase in ("formation spécialisée", "les stages", "conseils de professionnels"):
            self.assertIn(phrase, argument.developpement)
        self.assertIn("vie professionnelle", argument.consequence)
        self.assertIn("même après le retour", argument.consequence)
        cue = self.plans["eo/tache-3/culture-p17"].arguments[0]
        self.assertIn("training opportunities", cue.point.english)
        self.assertIn("professional skills", cue.point.english)

    def test_living_abroad_financial_claim_is_developed_before_its_concrete_example(self):
        argument = self.response(17).arguments[1]
        self.assertEqual(
            argument.idea,
            "Ensuite, les difficultés financières peuvent rendre la vie à l'étranger éprouvante.",
        )
        self.assertIn("revenus sont insuffisants ou irréguliers", argument.developpement)
        self.assertIn("payer le logement et les dépenses courantes", argument.developpement)
        self.assertIn("payer le loyer", argument.exemple)
        cue = self.plans["eo/tache-3/culture-p17"].arguments[1]
        self.assertIn("Les difficultés financières", cue.point.french)
        self.assertIn("Financial difficulties", cue.point.english)

    def test_living_abroad_personal_cost_explains_absence_rather_than_how_to_assess_the_stay(self):
        argument = self.response(17).arguments[2]
        self.assertIn(
            "il arrive qu'on ne puisse pas rentrer quand un proche a besoin d'aide.",
            argument.developpement,
        )
        self.assertNotIn("le bilan tienne compte", argument.developpement)
        self.assertIn("son père tombe malade", argument.exemple)
        self.assertIn("Elle n'a pas l'argent pour aller le voir", argument.exemple)
        self.assertIn("Malgré ses bons résultats", argument.exemple)
        self.assertIn("ne pas pouvoir être auprès de lui", argument.exemple)
        cue = self.plans["eo/tache-3/culture-p17"].arguments[2].example
        self.assertIn("ne peut pas payer le voyage", cue.french)
        self.assertIn("cannot afford to travel", cue.english)

    def test_living_abroad_nuance_distinguishes_learning_from_compensating_for_hardship(self):
        nuance = self.response(17).nuance
        self.assertIn("une difficulté ponctuelle ne rend pas tout le séjour négatif", nuance)
        self.assertIn("Un soutien ou un changement de projet peut améliorer la situation.", nuance)
        self.assertIn(
            "ce que l'on apprend d'une épreuve ne compense pas toujours la souffrance qu'elle a causée.",
            nuance,
        )
        self.assertNotIn("il ne faut pas prétendre", nuance)
        cue = self.plans["eo/tache-3/culture-p17"].nuance
        self.assertIn("apprendre ne compense pas toujours la souffrance", cue.french)
        self.assertIn("learning from it does not always make up for the suffering", cue.english)

    def test_family_migration_example_and_consequence_follow_childrens_safety_and_schooling(self):
        response = self.response(25)
        family = response.arguments[2]
        for phrase in (
            "Une famille", "les violences entraînent des fermetures d'écoles",
            "peut envisager", "Les parents cherchent alors", "aller régulièrement en classe",
        ):
            self.assertIn(phrase, family.exemple)
        self.assertNotIn("ne plus vivre séparés", family.exemple)
        self.assertEqual(
            family.consequence,
            "La sécurité et la scolarité des enfants guident alors le choix de la destination.",
        )
        self.assertIn("priorités familiales", response.position)
        self.assertIn("réaliser un projet familial", response.conclusion)
        plan = self.plans["eo/tache-3/culture-p25"]
        self.assertIn("réaliser un projet familial", plan.introduction.french)
        self.assertIn("Une famille cherche un pays plus sûr", plan.arguments[2].example.french)
        self.assertIn("aller régulièrement à l'école", plan.arguments[2].example.french)
        self.assertIn("safer country", plan.arguments[2].example.english)
        self.assertIn("attend school regularly", plan.arguments[2].example.english)

    def test_immigration_knowledge_consequences_explain_affordability_and_mutual_adjustment(self):
        response = self.response(26)
        self.assertIn("réduirait le risque", response.arguments[0].consequence)
        self.assertIn("au-dessus de mes moyens", response.arguments[0].consequence)
        self.assertIn("qui convienne à chacun", response.arguments[2].consequence)
        self.assertNotIn("me laissant mes propres habitudes", response.arguments[2].consequence)

    def test_forgotten_traditional_skill_requires_relearning_before_transmission(self):
        argument = self.response(27).arguments[1]
        self.assertIn("une danse traditionnelle qu'elle connaissait bien", argument.exemple)
        self.assertIn("Après des années sans la pratiquer", argument.exemple)
        self.assertIn("ne retrouve plus certains pas", argument.exemple)
        self.assertIn("Sa sœur les lui montre à nouveau", argument.exemple)
        self.assertIn("réapprendre ces pas", argument.consequence)
        self.assertIn("transmettre cette danse à ses enfants", argument.consequence)
        self.assertNotIn("brioche", argument.exemple)

    def test_cultural_forgetting_introduction_explains_practice_without_repeating_the_same_claim(self):
        response = self.response(27)
        self.assertIn("peut entraîner l'oubli", response.position_claire)
        self.assertIn("cet oubli n'est pas automatique", response.position_claire)
        self.assertIn("pratiquer certaines traditions avec ses proches", response.position_claire)
        self.assertIn("on risque moins de les oublier", response.position_claire)
        self.assertIn("on peut finir par oublier", response.arguments[0].idea)
        self.assertIn("perdre certains savoir-faire", response.arguments[1].idea)

    def test_regular_contact_keeps_cultural_expressions_in_use_after_twenty_years(self):
        argument = self.response(27).arguments[2]
        self.assertIn("depuis vingt ans à l'étranger", argument.exemple)
        self.assertIn("chaque semaine à sa sœur", argument.exemple)
        self.assertIn("continuer à utiliser des expressions", argument.exemple)
        self.assertIn("qu'elle entend rarement au travail", argument.exemple)
        cue = self.plans["eo/tache-3/culture-p27"].arguments[2].example
        self.assertIn("continuer à utiliser les expressions familiales", cue.french)
        self.assertIn("après vingt ans", cue.french)
        self.assertIn("keep family expressions in use", cue.english)
        self.assertIn("after twenty years abroad", cue.english)
        self.assertNotIn("recall a forgotten expression", cue.english)

    def test_reality_tv_cues_keep_humiliation_and_spectacle_without_inventing_staging(self):
        response = self.response(31)
        plan = self.plans["eo/tache-3/culture-p31"]
        self.assertIn("pour faire rire", plan.arguments[1].example.french)
        self.assertIn("et abîmer leur relation", plan.arguments[1].example.french)
        self.assertIn("to make others laugh", plan.arguments[1].example.english)
        self.assertNotIn("instead of", plan.arguments[1].example.english)
        self.assertIn("mis en spectacle", plan.conclusion.french)
        self.assertIn("conflicts turned into entertainment", plan.conclusion.english)
        self.assertNotIn("staged", plan.conclusion.english)
        self.assertIn("Son choix peut donc être influencé par une publicité", response.arguments[2].consequence)
        self.assertNotIn("Le regard critique doit", response.arguments[2].consequence)

    def test_celebrity_experience_and_scrutiny_explain_concrete_contributions(self):
        response = self.response(33)
        self.assertIn("connaître des besoins concrets", response.arguments[0].developpement)
        self.assertIn("écouter les personnes concernées", response.arguments[0].developpement)
        self.assertNotIn("plutôt que rejeter sa parole", response.arguments[0].developpement)
        self.assertIn("évaluer sa préparation sur un projet concret", response.arguments[2].consequence)
        self.assertIn("plutôt que sur sa seule popularité", response.arguments[2].consequence)

    def test_argument_claims_state_the_benefit_or_risk_before_explaining_its_mechanism(self):
        for number, index, claim, explanation, example in (
            (5, 2, "contacts sur place", "Des conseils précis", "relire son CV"),
            (14, 2, "approfondir sa connaissance", "poser une question précise", "formules de politesse"),
            (26, 2, "éviter des malentendus", "mal interpréter", "prévoir leurs visites"),
            (30, 2, "obstacles administratifs", "faire reconnaître un diplôme", "profession est réglementée"),
            (31, 1, "banaliser les comportements agressifs", "peut sembler valorisée", "moquerie"),
            (33, 1, "mobiliser le public", "informations vérifiées", "réunion publique"),
        ):
            with self.subTest(response=number, argument=index + 1):
                argument = self.response(number).arguments[index]
                self.assertIn(claim, argument.idea)
                self.assertIn(explanation, argument.developpement)
                self.assertIn(example, argument.exemple)

    def test_impulse_buying_consequence_is_a_result_not_fresh_advice(self):
        argument = self.response(34).arguments[1]
        self.assertIn("augmenter les dépenses", argument.consequence)
        self.assertIn("sans mieux répondre aux besoins", argument.consequence)
        self.assertNotIn("Attendre avant de payer", argument.consequence)
        plan = self.plans["eo/tache-3/culture-p34"]
        self.assertIn("offre semble urgente", plan.arguments[1].example.french)
        self.assertIn("offer seems urgent", plan.arguments[1].example.english)
        self.assertIn("plusieurs enfants", plan.arguments[2].example.french)
        self.assertIn("several children", plan.arguments[2].example.english)

    def test_standalone_positions_name_the_issue_instead_of_an_orphan_pronoun(self):
        self.assertTrue(self.response(9).position.startswith("S'adapter"))
        for number in (17, 29):
            with self.subTest(response=number):
                self.assertTrue(self.response(number).position.startswith("La vie à l'étranger"))

    def test_adaptation_keeps_the_preferred_preferences_and_practical_response_wording(self):
        self.assertEqual(
            self.response(1).arguments[0].developpement,
            "Le climat et les horaires ne dépendent pas de nos préférences. "
            "En tenir compte permet de travailler, de se déplacer et d'organiser "
            "ses journées sans se mettre inutilement en difficulté.",
        )

    def test_integration_example_keeps_shared_context_distinct_from_understanding_words(self):
        argument = self.response(30).arguments[0]
        self.assertIn("les mêmes références que les autres", argument.developpement)
        self.assertIn("poser une question", argument.developpement)
        self.assertNotIn("intervenir aussi spontanément", argument.developpement)
        self.assertIn("une émission qu'un nouvel arrivant n'a jamais vue", argument.exemple)
        self.assertIn("Il comprend les mots, mais pas la blague", argument.exemple)
        self.assertIn("Un collègue lui explique ce qui s'est passé dans l'émission", argument.exemple)
        self.assertIn("Le nouvel arrivant peut alors participer à la discussion", argument.exemple)
        cue = self.plans["eo/tache-3/culture-p30"].arguments[0].example
        self.assertIn("ce qui s'est passé dans une émission", cue.french)
        self.assertIn("comprend la blague et peut participer", cue.french)
        self.assertIn("what happened in a TV show", cue.english)
        self.assertIn("understand the joke and join in", cue.english)

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
        self.assertIn("on utilise moins sa langue d'origine", forgetting.arguments[0].idea)
        self.assertIn("sa grand-mère lui disait souvent", forgetting.arguments[0].exemple)
        self.assertIn("il en a oublié le sens", forgetting.arguments[0].exemple)
        self.assertIn("même si l'on continue à parler sa langue d'origine", forgetting.arguments[1].developpement)
        self.assertIn("une danse traditionnelle qu'elle connaissait bien", forgetting.arguments[1].exemple)
        self.assertIn("ne retrouve plus certains pas", forgetting.arguments[1].exemple)
        self.assertIn("Sa sœur les lui montre à nouveau", forgetting.arguments[1].exemple)
        self.assertNotIn("Les enfants", forgetting.arguments[1].developpement)
        self.assertIn("la durée du séjour", forgetting.arguments[2].consequence.casefold())
        self.assertIn("n'est pas nécessairement oublier", forgetting.nuance)

    def test_material_difficulty_includes_time_and_fatigue_not_only_expenses(self):
        response = self.response(29)
        material = response.arguments[0]
        self.assertIn("les contraintes matérielles", material.idea)
        self.assertIn("Le coût du logement", material.developpement)
        self.assertIn("possibilités d'emploi", material.developpement)
        self.assertIn("trajet quotidien", material.exemple)
        self.assertIn("son budget, sa fatigue", material.exemple)
        self.assertIn("contraintes qui peuvent durer", material.consequence)
        self.assertIn("d'être à leurs côtés", response.arguments[1].idea)
        self.assertIn("après une opération", response.arguments[1].exemple)

    def test_work_authorisation_example_keeps_the_condition_and_possible_housing_delay(self):
        argument = self.response(29).arguments[2]
        self.assertIn("Selon le pays et le statut", argument.developpement)
        self.assertIn("reçoit une offre d'emploi", argument.exemple)
        self.assertIn("liée à son employeur actuel", argument.exemple)
        self.assertIn("Si elle doit attendre une nouvelle autorisation pour commencer", argument.exemple)
        self.assertIn("ne peut pas encore compter sur ce salaire", argument.exemple)
        self.assertIn("Elle devra peut-être reporter son déménagement", argument.exemple)
        cue = self.plans["eo/tache-3/culture-p29"].arguments[2].example
        self.assertIn("Attendre une nouvelle autorisation", cue.french)
        self.assertIn("peut retarder", cue.french)
        self.assertIn("un déménagement", cue.french)
        self.assertIn("new work authorisation", cue.english)
        self.assertIn("can delay expected pay and a move", cue.english)

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
