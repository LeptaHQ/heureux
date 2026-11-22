from dataclasses import asdict

from django.test import SimpleTestCase

from study.catalogue import registry as catalogue
from study.catalogue import loader as content
from study.expression.eo.tache_3.responses import spoken_text


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

    def test_every_culture_consigne_uses_the_matching_model_and_complete_bilingual_cues(self):
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
                self.assertEqual(len(plan.arguments), len(model.response.arguments))
                for argument, cue in zip(
                    model.response.arguments,
                    plan.arguments,
                    strict=True,
                ):
                    self.assertTrue(argument.idea.strip())
                    for memory in (cue.point, cue.example):
                        self.assertTrue(memory.french.strip())
                        self.assertTrue(memory.english.strip())

    def test_actor_preparation_cue_refers_to_learning_lines_not_having_a_script(self):
        cue = self.plans["eo/tache-3/culture-p7"].arguments[2].example
        self.assertIn("Sans connaître son texte", cue.french)
        self.assertIn("Without knowing her lines", cue.english)

    def test_local_relationships_cue_connects_conversations_to_social_codes(self):
        cue = self.plans["eo/tache-3/culture-p24"].arguments[1].example
        for phrase in ("voisins ou ses collègues", "tutoyer ou vouvoyer", "accepter une invitation"):
            self.assertIn(phrase, cue.french)
        for phrase in ("neighbours or colleagues", "use tu or vous", "accept an invitation"):
            self.assertIn(phrase, cue.english)

    def test_distance_example_establishes_work_before_leave_and_does_not_assume_help(self):
        example = self.response(29).arguments[1].exemple
        for phrase in (
            "Une salariée à l'étranger", "son père", "après une opération",
            "ne peut pas obtenir de congé immédiatement",
            "peut chercher quelqu'un pour aider son père sur place",
        ):
            self.assertIn(phrase, example)
        cue = self.plans["eo/tache-3/culture-p29"].arguments[1].example
        self.assertIn("Une salariée sans congé immédiat", cue.french)
        self.assertIn("peut chercher une aide sur place", cue.french)
        self.assertIn("An employee cannot get immediate leave", cue.english)
        self.assertIn("she can seek help", cue.english)

    def test_food_distribution_example_establishes_a_language_both_sides_understand(self):
        example = self.response(35).arguments[2].exemple
        self.assertIn("une langue qu'ils ont en commun", example)
        self.assertIn("La famille comprend comment retirer son colis", example)

    def test_language_and_transmission_cues_preserve_the_models_qualified_claims(self):
        conclusion = self.plans["eo/tache-3/culture-p19"].conclusion
        self.assertIn("grâce aux traductions", conclusion.french)
        self.assertIn("observation and translations", conclusion.english)
        self.assertNotIn("surface", conclusion.french)
        self.assertNotIn("surface", conclusion.english)
        nuance = self.plans["eo/tache-3/culture-p27"].nuance
        self.assertIn("ce qu'on veut conserver et transmettre", nuance.french)
        self.assertIn("what to preserve and pass on", nuance.english)

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

    def test_older_memory_example_compares_the_same_parent_child_conflict(self):
        example = self.response(8).arguments[0].exemple
        self.assertIn("de se disputer avec leurs parents", example)
        self.assertIn("les disputes qu'elle avait avec ses parents au sujet de ses sorties", example)
        self.assertNotIn("respectait toujours", example)

    def test_older_media_example_connects_repetition_to_a_judgment_about_young_people(self):
        example = self.response(8).arguments[1].exemple
        cue = self.plans["eo/tache-3/culture-p8"].arguments[1].example
        self.assertIn("plusieurs extraits d'une même bagarre", example)
        self.assertIn("la violence soit fréquente chez les jeunes", example)
        self.assertNotIn("tous les établissements", example)
        self.assertIn("une violence fréquente", cue.french)
        self.assertIn("fear frequent violence", cue.english)

    def test_books_and_documentaries_show_cultural_discovery_without_travel(self):
        argument = self.response(14).arguments[0]
        self.assertIn("les livres et les documentaires", argument.idea)
        self.assertIn("l'histoire d'une tradition", argument.developpement)
        self.assertIn("les raisons derrière une pratique", argument.developpement)
        self.assertNotIn("ne représente pas tout un pays", argument.developpement)
        self.assertNotIn("croise les sources", argument.developpement)
        for phrase in (
            "un livre sur la cuisine portugaise", "pourquoi on sale et sèche le poisson",
            "le conserver pendant de longs voyages en mer", "contraintes de la navigation",
        ):
            self.assertIn(phrase, argument.exemple)
        self.assertNotIn("roman", argument.exemple)
        self.assertNotIn("raviolis", argument.exemple)
        self.assertNotIn("Marseille", argument.exemple)
        self.assertNotIn("bouillabaisse", argument.exemple)
        self.assertIn("relier à une histoire et à un contexte", argument.consequence)
        cue = self.plans["eo/tache-3/culture-p14"].arguments[0].example
        for language, recipe, preservation, history in (
            ("french", "cuisine portugaise", "poisson salé et séché", "longs voyages en mer"),
            ("english", "Portuguese cooking", "fish salted and dried", "long sea voyages"),
        ):
            text = getattr(cue, language)
            self.assertIn(recipe, text)
            self.assertIn(preservation, text)
            self.assertIn(history, text)
            self.assertNotIn("Marseille", text)
            self.assertNotIn("bouillabaisse", text.casefold())

    def test_local_dance_practice_leads_to_joining_the_dance(self):
        example = self.response(14).arguments[1].exemple
        stages = (
            example.index("En essayant les pas avec le groupe"),
            example.index("les conseils de l'animateur"),
            example.index("assez de pas pour participer ensuite au bal"),
        )
        self.assertEqual(stages, tuple(sorted(stages)))
        self.assertNotIn("au lieu de rester spectateur", example)

    def test_remote_conversation_explains_a_specific_household_custom(self):
        argument = self.response(14).arguments[2]
        self.assertIn("poser ses propres questions", argument.idea)
        self.assertIn("demander une explication", argument.developpement)
        self.assertIn("comment cette personne vit une habitude au quotidien", argument.developpement)
        for phrase in (
            "un appel vidéo", "Je pourrais lui demander", "une amie japonaise",
            "pourquoi elle enlève ses chaussures", "sa famille s'assoit parfois au sol",
            "le garder propre",
        ):
            self.assertIn(phrase, argument.exemple)
        cue = self.plans["eo/tache-3/culture-p14"].arguments[2].example
        self.assertIn("Une amie japonaise", cue.french)
        self.assertIn("enlève ses chaussures", cue.french)
        self.assertIn("sa famille", cue.french)
        self.assertIn("A Japanese friend", cue.english)
        self.assertIn("takes off her shoes", cue.english)
        self.assertIn("her family sometimes sits on it", cue.english)

    def test_cultural_discovery_introduction_connects_learning_routes_to_their_value(self):
        response = self.response(14)
        self.assertIn(
            "Les livres, les activités près de chez soi et les échanges à distance "
            "permettent déjà de comprendre des pratiques et leur sens.",
            response.position_claire,
        )
        self.assertNotIn("Il ne s'agit pas", response.position_claire)

    def test_cultural_discovery_nuance_compares_learning_with_firsthand_experience(self):
        response = self.response(14)
        self.assertTrue(response.nuance.startswith(
            "Bien que ces moyens soient utiles, ils ne remplacent pas complètement l'expérience sur place"
        ))
        self.assertIn("ses odeurs et son rythme quotidien", response.nuance)
        self.assertIn("Mais tout le monde ne peut pas voyager", response.nuance)
        self.assertIn("ne retire pas leur valeur aux connaissances acquises autrement", response.nuance)
        self.assertIn("sans prendre l'avion", response.conclusion)
        self.assertNotIn("documentaire", response.nuance)
        self.assertNotIn("touristes", response.nuance)
        cue = self.plans["eo/tache-3/culture-p14"].nuance
        self.assertIn("ne remplacent pas complètement l'expérience sur place", cue.french)
        self.assertIn("tout le monde ne peut pas voyager", cue.french)
        self.assertIn("cannot fully replace first-hand experience", cue.english)
        self.assertIn("not everyone can travel", cue.english)

    def test_examples_demonstrate_concrete_prompt_faithful_mechanisms(self):
        for number, argument, required in (
            (1, 2, ("à 14 heures", "à midi", "une fois par semaine", "le week-end")),
            (4, 2, ("a droit", "aide au logement", "formulaire")),
            (6, 0, ("un essai", "la voiture en ville", "la pollution", "sans transports en commun", "interdiction totale")),
            (11, 0, ("un logement", "petit emploi", "compatriotes déjà installés qui connaissent le terrain")),
            (11, 1, ("installées depuis des années", "très peu la langue locale", "presque fréquenté que leur communauté")),
            (15, 1, ("couscous", "repas partagé au Maghreb", "morue au Portugal", "échanges avec l'Atlantique")),
            (15, 2, ("pho vietnamien", "tapas espagnoles", "les rituels du repas", "l'histoire de ces plats")),
            (19, 0, ("à Tokyo", "le métro chaque matin", "à voix basse", "évitent les appels téléphoniques")),
            (19, 1, ("documentaire sur les Pays-Bas, sous-titré en français", "des digues et des pompes", "gagner des terres sur la mer", "protection contre les inondations")),
            (19, 2, ("document traduit", "projet de logements", "dans son quartier", "pendant la réunion", "il ne comprend pas pourquoi", "certains défendent le projet et d'autres s'y opposent")),
            (20, 1, ("l'histoire, la musique ou la géographie d'un pays", "elles ont voyagé, regardé des documentaires et discuté")),
            (24, 1, ("en discutant avec des collègues ou des voisins", "tutoyer ou vouvoyer", "accepter une invitation")),
            (26, 2, ("prévoir leurs visites à l'avance", "question d'organisation", "pas un refus de me voir")),
            (30, 2, ("parle couramment la langue", "un bon emploi", "un logement stable", "se sentir encore étrangère")),
            (31, 1, ("rediffusée plusieurs fois", "extrait viral", "comme un spectacle")),
            (35, 2, ("distribution alimentaire", "La famille comprend", "comme les autres bénévoles, il contribue")),
        ):
            with self.subTest(response=number, argument=argument + 1):
                example = self.response(number).arguments[argument].exemple
                for phrase in required:
                    self.assertIn(phrase, example)

    def test_television_value_includes_learning_shared_experiences_and_intentional_viewing(self):
        response = self.response(12)
        self.assertIn("documentaire sur l'environnement ou sur l'histoire", response.arguments[0].exemple)
        self.assertIn("valeur culturelle et sociale", response.arguments[1].idea)
        self.assertIn("un match important en famille", response.arguments[1].exemple)
        self.assertIn("un moment partagé qui compte autant que le contenu", response.arguments[1].exemple)
        self.assertIn("programmes que l'on n'a même pas choisis", response.arguments[2].exemple)
        self.assertIn("l'usage passif", response.arguments[2].consequence)
        plan = self.plans["eo/tache-3/culture-p12"]
        self.assertIn("match important en famille", plan.arguments[1].example.french)
        self.assertIn("a big match with family", plan.arguments[1].example.english)
        self.assertIn("sans choisir", response.nuance)
        self.assertIn("du regard critique que l'on garde", response.conclusion)

    def test_reality_television_distinguishes_superficial_success_conflict_and_repeated_exposure(self):
        response = self.response(31)
        success, normalisation, exposure = response.arguments
        self.assertIn("mises en scène de richesse", success.exemple)
        self.assertIn("une vision déformée de la réussite", success.consequence)
        self.assertIn("comme un spectacle plutôt que comme un vrai manque de respect", normalisation.exemple)
        self.assertIn("rendre ordinaires des comportements", normalisation.consequence)
        self.assertIn("le regard critique sont encore en pleine construction", exposure.developpement)
        self.assertIn("un adolescent qui suit quotidiennement ces programmes", exposure.exemple)
        self.assertIn("tous les jeunes y sont sensibles de la même manière", response.nuance)

    def test_school_arts_restore_original_expression_cultural_openness_and_career_arguments(self):
        response = self.response(13)
        source = next(source for source in self.sources if source.semantic_group == "eo/tache-3/culture-p13")
        self.assertEqual(
            [argument.idea for argument in response.arguments],
            [argument["idea"] for argument in source.prompts[0].model_content["arguments"]],
        )
        expression, cultures, careers = response.arguments
        self.assertIn("faire des choix et de les expliquer", expression.developpement)
        self.assertIn("écoute les réactions des autres", expression.developpement)
        for phrase in ("nouvelle école", "voix hésitante", "des pauses", "Ses camarades discutent"):
            self.assertIn(phrase, expression.exemple)
        for phrase in ("peinture mexicaine", "fête des Morts", "fleurs", "photos", "rendre hommage"):
            self.assertIn(phrase, cultures.exemple)
        self.assertIn("sans que les parents aient à payer des cours privés", careers.developpement)
        self.assertIn("envisager une formation", careers.developpement)
        for phrase in ("affiche", "agrandit les titres", "simplifie les images", "métier de graphiste"):
            self.assertIn(phrase, careers.exemple)
        self.assertIn("voie professionnelle", careers.consequence)
        plan = self.plans["eo/tache-3/culture-p13"]
        self.assertIn("esprit critique", plan.arguments[0].point.french)
        self.assertIn("other cultures", plan.arguments[1].point.english)
        self.assertIn("artistic career", plan.arguments[2].point.english)
        self.assertIn("trouver une voie professionnelle", response.conclusion)
        self.assertIn("la lecture et le calcul restent prioritaires", response.nuance)
        self.assertIn("sans les opposer aux apprentissages fondamentaux", response.nuance)

    def test_cuisine_keeps_the_requested_source_answer_and_aligned_cues(self):
        model = self.models["eo/tache-3/culture-p15"]
        response = model.response
        plan = self.plans[model.group]
        source = next(source for source in self.sources if source.semantic_group == model.group)
        self.assertEqual(model.argument_ids, (1, 2, 5))
        self.assertEqual(model.source_prompts, ((
            "culture:p15",
            "La cuisine permet de connaître la culture des pays. Êtes-vous d'accord ?",
        ),))
        for field in ("reformulation", "position", "position_claire", "nuance", "conclusion"):
            self.assertEqual(getattr(response, field), getattr(source, field), field)
        self.assertEqual(
            [asdict(argument) for argument in response.arguments],
            [asdict(argument) for argument in source.arguments],
        )
        for language, example_phrases in (
            ("french", ("manger en famille", "Couscous au Maghreb", "pho vietnamien")),
            ("english", ("eat with family", "Couscous in the Maghreb", "Vietnamese pho")),
        ):
            for argument, phrase in zip(plan.arguments, example_phrases):
                self.assertIn(phrase, getattr(argument.example, language))

    def test_country_knowledge_has_a_supported_limit_not_a_second_language_workaround(self):
        model = self.models["eo/tache-3/culture-p19"]
        response = model.response
        self.assertEqual(model.argument_ids, (1, 2, 4))
        self.assertEqual(model.source_prompts, ((
            "culture:p19",
            "À votre avis, peut-on connaître un pays sans en parler la langue ? Pourquoi ?",
        ),))
        self.assertIn("les transports, les commerces ou les lieux de rencontre", response.arguments[0].developpement)
        self.assertIn("comment les personnes se comportent", response.arguments[0].developpement)
        self.assertNotIn("l'explication que l'on imagine", response.arguments[0].developpement)
        self.assertIn("on peut déjà apprendre beaucoup sur un pays sans parler sa langue", response.position_claire)
        self.assertIn("Observer la vie quotidienne et utiliser des traductions", response.position_claire)
        self.assertIn("suivre les échanges spontanés", response.position_claire)
        self.assertNotIn("une partie d'un pays", response.position_claire)
        self.assertNotIn("une partie d'un pays", response.position)
        self.assertIn("à Tokyo", response.arguments[0].exemple)
        self.assertIn("le métro chaque matin", response.arguments[0].exemple)
        self.assertIn("Bien qu'il ne comprenne pas les conversations", response.arguments[0].exemple)
        self.assertIn("parlent à voix basse", response.arguments[0].exemple)
        self.assertIn("évitent les appels téléphoniques", response.arguments[0].exemple)
        self.assertNotIn("marché", response.arguments[0].exemple)
        self.assertNotIn("changer deux fois", response.arguments[0].exemple)
        self.assertIn("rester discret dans les transports", response.arguments[0].consequence)
        self.assertIn("sans avoir d'abord appris le japonais", response.arguments[0].consequence)
        cue = self.plans[model.group].arguments[0].example
        self.assertIn("Tokyo", cue.french)
        self.assertIn("parler bas et éviter les appels", cue.french)
        self.assertIn("Tokyo", cue.english)
        self.assertIn("keep the noise down", cue.english)
        self.assertIn("other metro passengers", cue.english)
        self.assertIn("des connaissances sur le pays dans une langue que l'on comprend", response.arguments[1].idea)
        self.assertNotIn("les raisons", response.arguments[1].idea)
        point = self.plans[model.group].arguments[1].point
        self.assertIn("s'informer sur le pays", point.french)
        self.assertIn("learn about the country", point.english)
        development = response.arguments[1].developpement
        for phrase in ("Un article traduit", "un documentaire sous-titré", "l'histoire d'un pays", "son actualité", "ses institutions"):
            self.assertIn(phrase, development)
        self.assertIn("documentaire sur les Pays-Bas, sous-titré en français", response.arguments[1].exemple)
        self.assertIn("des digues et des pompes ont permis de gagner des terres sur la mer", response.arguments[1].exemple)
        self.assertIn("pourquoi la protection contre les inondations", response.arguments[1].exemple)
        self.assertIn("comprendre un enjeu important sans maîtriser la langue locale", response.arguments[1].consequence)
        example_cue = self.plans[model.group].arguments[1].example
        self.assertIn("Pays-Bas", example_cue.french)
        self.assertIn("protection contre les inondations", example_cue.french)
        self.assertIn("Dutch land reclaimed from the sea", example_cue.english)
        self.assertIn("flood protection", example_cue.english)
        self.assertIn("certaines discussions restent difficiles", response.arguments[2].idea)
        self.assertIn("il n'y a pas toujours quelqu'un pour traduire", response.arguments[2].developpement)
        self.assertIn("Il sait ce qu'on veut construire", response.arguments[2].exemple)
        self.assertIn("il ne comprend pas pourquoi certains défendent le projet et d'autres s'y opposent", response.arguments[2].exemple)
        self.assertNotIn("va être construit", response.arguments[2].exemple)
        self.assertIn("suivre leurs arguments et à participer davantage", response.arguments[2].consequence)
        self.assertIn("la langue ne suffit pas à tout expliquer", response.nuance)
        self.assertIn("le ton, les gestes et les références culturelles", response.nuance)
        self.assertIn("comprendre tous les mots sans saisir une plaisanterie", response.nuance)
        self.assertNotIn("réunion", response.nuance)
        self.assertNotIn("projet", response.nuance)
        nuance_cue = self.plans[model.group].nuance
        for phrase in ("ton", "gestes", "références culturelles"):
            self.assertIn(phrase, nuance_cue.french)
        for phrase in ("tone", "gestures", "cultural references"):
            self.assertIn(phrase, nuance_cue.english)
        self.assertNotIn("une langue commune", response.position_claire)
        self.assertNotIn("une langue commune", response.conclusion)

    def test_solo_travel_builds_autonomy_by_resolving_a_specific_disruption(self):
        response = self.response(21)
        argument = response.arguments[0]
        self.assertIn("l'autonomie et la confiance en soi", argument.idea)
        self.assertIn("sans attendre qu'un proche décide à notre place", argument.developpement)
        self.assertIn("demander des renseignements", argument.developpement)
        self.assertIn("comparer les possibilités et choisir", argument.developpement)
        for phrase in (
            "une étudiante voyage seule pour la première fois",
            "Son train est annulé",
            "le suivant ne part que le lendemain",
            "Elle demande à un agent quelles solutions existent",
            "compare les horaires",
            "choisit un bus",
            "où elle a réservé une chambre",
            "Elle arrive le soir même et peut s'installer",
        ):
            self.assertIn(phrase, argument.exemple)
        steps = tuple(argument.exemple.index(phrase) for phrase in (
            "demande à un agent", "compare les horaires", "choisit un bus", "Elle arrive le soir même",
        ))
        self.assertEqual(steps, tuple(sorted(steps)))
        self.assertIn("Après avoir surmonté cet imprévu", argument.consequence)
        self.assertIn("plus capable d'organiser la suite", argument.consequence)
        self.assertNotIn("sans aide", argument.developpement)
        cue = self.plans["eo/tache-3/culture-p21"].arguments[0].example
        for language, problem, choice, arrival in (
            ("french", "Train annulé", "choisir un bus", "avant la fermeture de la réception"),
            ("english", "Train cancelled", "choose a bus", "before reception closes"),
        ):
            text = getattr(cue, language)
            self.assertIn(problem, text)
            self.assertIn(choice, text)
            self.assertIn(arrival, text)
        painting = response.arguments[1].exemple
        self.assertNotIn("rentrer tôt", painting)
        self.assertIn("consacrer l'après-midi à une exposition.", painting)
        self.assertIn("écourter sa visite", painting)
        self.assertIn("faire les magasins", painting)

    def test_compatriot_support_connects_familiar_community_with_first_steps(self):
        argument = self.response(11).arguments[0]
        self.assertIn("réseau humain qu'on a mis des années à construire", argument.developpement)
        self.assertIn("rompre la solitude des débuts", argument.developpement)
        self.assertIn("un logement, un petit emploi, les bonnes adresses", argument.exemple)
        self.assertIn("compatriotes déjà installés", argument.exemple)

    def test_compatriot_answer_distinguishes_local_action_from_language_exposure(self):
        response = self.response(11)
        self.assertIn("On pratique peu la langue locale", response.arguments[1].developpement)
        action = response.arguments[2]
        self.assertIn("avoir son mot à dire", action.idea)
        self.assertIn("Même quand on parle bien la langue", action.developpement)
        self.assertIn("pas en sécurité quand elle traverse la rue avec son enfant", action.exemple)
        self.assertIn("demandent à la mairie qu'un passage piéton soit aménagé", action.exemple)
        self.assertIn("on agit avec les autres pour l'améliorer", action.consequence)
        cue = self.plans["eo/tache-3/culture-p11"].arguments[2].example
        self.assertIn("demandent ensemble un passage piéton à la mairie", cue.french)
        self.assertIn("ask the council for a pedestrian crossing together", cue.english)

    def test_traditions_keep_the_selected_version_and_explained_family_heritage(self):
        response = self.response(10)
        self.assertIn("restant libre de l'adapter et de le partager", response.position_claire)
        self.assertIn("les traditions donnent des repères", response.arguments[0].idea)
        self.assertIn("Ce lien avec sa vie d'avant peut aider à trouver sa place dans la nouvelle", response.arguments[0].developpement)
        self.assertIn("rendre le changement plus facile à vivre", response.arguments[0].consequence)
        self.assertIn("Les enfants qui grandissent ailleurs ne peuvent pas deviner", response.arguments[1].developpement)
        self.assertIn("connaître leurs origines tout en appartenant pleinement au pays", response.arguments[1].developpement)
        self.assertIn("une histoire qu'il peut comprendre et s'approprier, pas seulement une règle", response.arguments[1].consequence)
        self.assertIn("d'échanger ses propres souvenirs", response.arguments[2].developpement)
        self.assertIn("ni de porter atteinte aux droits des autres", response.nuance)
        self.assertIn("n'exige pas que chaque pratique soit reproduite exactement", response.nuance)
        self.assertIn("restant libre d'évoluer", self.plans["eo/tache-3/culture-p10"].conclusion.french)
        self.assertIn("droits des autres", self.plans["eo/tache-3/culture-p10"].nuance.french)

    def test_family_transmission_example_explains_the_meal_and_family_memories(self):
        example = self.response(10).arguments[1].exemple
        self.assertIn("expliquer pourquoi ce plat compte pour eux", example)
        self.assertIn("appeler les grands-parents pour écouter leurs souvenirs", example)
        self.assertIn("plutôt que demander simplement à l'enfant de suivre la tradition", example)
        self.assertNotIn("camarades", example)
        cue = self.plans["eo/tache-3/culture-p10"].arguments[1].example
        self.assertNotIn("camarades", cue.french)
        self.assertNotIn("classmates", cue.english)

    def test_adaptation_cue_means_adapting_to_constraints_not_changing_them(self):
        cue = self.plans["eo/tache-3/culture-p1"].conclusion
        self.assertIn("Adapter le nécessaire", cue.french)
        self.assertIn("sans effacer sa vie d'avant", cue.french)
        self.assertIn("Adapt what is necessary", cue.english)
        self.assertIn("without erasing your previous life", cue.english)

    def test_living_abroad_example_links_cooking_training_to_a_clear_career_goal(self):
        example = self.response(5).arguments[0].exemple
        for phrase in (
            "devenir cuisinier", "une spécialité de pâtisserie absente près de chez lui",
            "à l'étranger une école", "stage en restaurant", "sous la direction d'un chef",
        ):
            self.assertIn(phrase, example)
        self.assertNotIn("irrigation", example)
        cue = self.plans["eo/tache-3/culture-p5"].arguments[0].example
        self.assertIn("pâtisserie", cue.french)
        self.assertIn("desserts préparés en stage avec un chef", cue.french)
        self.assertIn("desserts prepared on a placement with a chef", cue.english)

    def test_living_abroad_skills_argument_focuses_on_training_and_professional_practice(self):
        argument = self.response(17).arguments[0]
        self.assertIn("se former", argument.idea)
        self.assertIn("compétences professionnelles", argument.idea)
        for phrase in ("formation spécialisée", "les stages", "conseils de professionnels"):
            self.assertIn(phrase, argument.developpement)
        self.assertIn("vie professionnelle", argument.consequence)
        self.assertIn("même après le retour", argument.consequence)
        cue = self.plans["eo/tache-3/culture-p17"].arguments[0]
        self.assertIn("Training and placements", cue.point.english)
        self.assertIn("develop skills", cue.point.english)

    def test_living_abroad_budget_limits_time_to_overcome_language_difficulties(self):
        argument = self.response(17).arguments[2]
        self.assertIn("travailler pour payer ses factures", argument.idea)
        self.assertIn("moins de temps pour apprendre la langue", argument.idea)
        self.assertIn("le temps de prendre des cours de langue ou de chercher de l'aide", argument.developpement)
        self.assertIn(
            "quand on doit aussi travailler pour payer son loyer, c'est justement ce temps-là qui manque",
            argument.developpement,
        )
        self.assertIn("a du mal à suivre ses cours", argument.exemple)
        self.assertIn("des cours de langue le soir, mais elle travaille à ces heures-là pour payer son loyer", argument.exemple)
        self.assertIn("Elle ne peut pas y aller et prend du retard", argument.exemple)
        cue = self.plans["eo/tache-3/culture-p17"].arguments[2].example
        self.assertIn("elle ne peut pas suivre les cours de langue et prend du retard", cue.french)
        self.assertIn("she can't attend language classes and falls behind", cue.english)

    def test_living_abroad_family_distance_can_hurt_even_when_the_job_goes_well(self):
        argument = self.response(17).arguments[1]
        self.assertIn("les appels aident à garder le lien", argument.developpement)
        self.assertIn("certains moments ne se rattrapent pas", argument.developpement)
        self.assertIn("un travail qui lui plaît à l'étranger", argument.exemple)
        self.assertIn("son fils reste quelques mois au pays", argument.exemple)
        self.assertIn("sa première rentrée", argument.exemple)
        self.assertIn("elle aurait aimé être là pour l'accompagner", argument.exemple)
        cue = self.plans["eo/tache-3/culture-p17"].arguments[1].example
        self.assertIn("la première rentrée de son fils qu'en photo", cue.french)
        self.assertIn("her son's first day at school in a photo", cue.english)

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
        self.assertIn("learning does not always compensate for suffering", cue.english)

    def test_family_migration_example_and_consequence_follow_childrens_safety_and_schooling(self):
        response = self.response(25)
        family = response.arguments[2]
        for phrase in (
            "Une famille", "les violences entraînent des fermetures d'écoles",
            "peut envisager", "Les parents cherchent alors", "aller régulièrement en classe",
        ):
            self.assertIn(phrase.casefold(), family.exemple.casefold())
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
        self.assertIn("réduirais ainsi le risque", response.arguments[0].consequence)
        self.assertIn("manquer d'argent dès mon arrivée", response.arguments[0].consequence)
        self.assertIn("si on me proposait", response.arguments[0].exemple)
        self.assertIn("2 500 dollars nets par mois", response.arguments[0].exemple)
        self.assertIn("ne me resterait que 500 dollars", response.arguments[0].exemple)
        self.assertIn("reporterais le départ", response.arguments[0].exemple)
        self.assertIn("croire qu'une personne m'évite", response.arguments[2].developpement)
        self.assertIn("alors qu'elle a simplement d'autres habitudes", response.arguments[2].developpement)
        self.assertIn("comprendre son comportement", response.arguments[2].developpement)
        self.assertIn("un rejet", response.arguments[2].developpement)
        self.assertIn("qui convienne à chacun", response.arguments[2].consequence)
        self.assertNotIn("me laissant mes propres habitudes", response.arguments[2].consequence)

    def test_cultural_forgetting_keeps_the_requested_source_answer_and_aligned_cues(self):
        model = self.models["eo/tache-3/culture-p27"]
        response = model.response
        source = next(source for source in self.sources if source.semantic_group == model.group)
        for field in ("reformulation", "position", "position_claire", "nuance", "conclusion"):
            self.assertEqual(getattr(response, field), getattr(source, field), field)
        self.assertEqual(
            [asdict(argument) for argument in response.arguments],
            [asdict(argument) for argument in source.arguments],
        )
        cue = self.plans[model.group].arguments[2].example
        self.assertIn("l'une transmet sa langue et ses traditions", cue.french)
        self.assertIn("one passes on its language and traditions", cue.english)

    def test_reality_tv_cues_keep_the_dispute_and_critical_thinking(self):
        response = self.response(31)
        plan = self.plans["eo/tache-3/culture-p31"]
        self.assertIn("dispute de couple rediffusée", plan.arguments[1].example.french)
        self.assertIn("replayed and shared as a spectacle", plan.arguments[1].example.english)
        self.assertIn("l'esprit critique à l'école et en famille", plan.conclusion.french)
        self.assertIn("critical thinking at school and at home", plan.conclusion.english)
        self.assertIn("les parents et l'école développent l'esprit critique", response.arguments[2].consequence)

    def test_personal_project_example_connects_learning_progress_to_enjoyment_without_friends(self):
        response = self.response(16)
        example = response.arguments[2].exemple
        self.assertIn("sans qu'on ait d'amis", response.arguments[2].developpement)
        self.assertIn("apprend le piano chez elle", example)
        self.assertIn("Après plusieurs semaines", example)
        self.assertIn("jouer entièrement un morceau qu'elle aime", example)
        self.assertIn("le rejoue avec plaisir", example)
        self.assertIn("fière de ses progrès", example)
        self.assertNotIn("potager", example)
        self.assertIn("ne remplace pas l'affection", response.arguments[2].consequence)
        self.assertIn("souffrir de solitude", response.nuance)
        cue = self.plans["eo/tache-3/culture-p16"].arguments[2].example
        self.assertIn("piano", cue.french)
        self.assertIn("fière de ses progrès", cue.french)
        self.assertIn("enjoys replaying it", cue.english)
        self.assertIn("proud of the progress", cue.english)

    def test_celebrity_experience_and_scrutiny_explain_concrete_contributions(self):
        response = self.response(33)
        self.assertIn("connaître des besoins concrets", response.arguments[0].developpement)
        self.assertIn("écouter les personnes concernées", response.arguments[0].developpement)
        self.assertNotIn("plutôt que rejeter sa parole", response.arguments[0].developpement)
        self.assertIn("évaluer sa préparation sur un projet concret", response.arguments[2].consequence)
        self.assertIn("plutôt que sur sa seule popularité", response.arguments[2].consequence)

    def test_adaptation_example_rebuilds_practical_contacts_without_assuming_the_clinic_is_open(self):
        response = self.response(9)
        example = response.arguments[2].exemple
        for phrase in (
            "un dimanche", "son enfant qui a de la fièvre",
            "ne connaît pas encore les services de santé du quartier",
            "cherche une clinique sans rendez-vous",
            "appelle pour vérifier les horaires avant de partir",
        ):
            self.assertIn(phrase, example)
        self.assertIn("démarches courantes peuvent être compliquées", response.arguments[2].idea)
        self.assertIn("ressources du quartier", response.arguments[2].developpement)
        self.assertIn("Il a ainsi une première piste", response.arguments[2].consequence)
        cue = self.plans["eo/tache-3/culture-p9"].arguments[2].example
        point = self.plans["eo/tache-3/culture-p9"].arguments[2].point
        self.assertIn("services locaux", point.french)
        self.assertIn("complicate everyday tasks", point.english)
        self.assertIn("trouver une clinique", cue.french)
        self.assertIn("vérifier ses horaires", cue.french)
        self.assertIn("find a walk-in clinic", cue.english)

    def test_new_country_habits_distinguish_adaptation_from_majority_conformity(self):
        response = self.response(1)
        argument = response.arguments[1]
        self.assertIn("retrouver des gestes familiers aide à se sentir chez soi", argument.developpement)
        self.assertIn(
            "Une habitude n'a pas à disparaître simplement parce que la majorité des habitants fait autrement.",
            argument.developpement,
        )
        self.assertIn("tout en apprenant la langue locale", argument.exemple)
        self.assertIn("sans empêcher de participer à la vie du pays", argument.consequence)
        self.assertIn("la sécurité et les règles communes", response.nuance)
        self.assertIn("dans le respect des autres", response.nuance)

    def test_goals_abroad_restore_preparation_as_the_argument_not_just_a_professional_obstacle(self):
        response = self.response(5)
        preparation = response.arguments[1]
        self.assertIn("la préparation transforme une ambition générale en étapes réalisables", preparation.idea)
        for phrase in ("conditions d'accès", "les dépenses", "les compétences manquantes", "avant d'engager des frais importants"):
            self.assertIn(phrase, preparation.developpement)
        self.assertIn("vérifier les exigences auprès de l'organisme compétent", preparation.exemple)
        self.assertIn("Si une formation complémentaire est demandée", preparation.exemple)
        self.assertIn("prévoir du temps et un budget", preparation.exemple)
        self.assertIn("réduit les surprises", preparation.consequence)
        self.assertIn("ajuster le calendrier", preparation.consequence)
        self.assertIn("la préparation ne supprime ni les difficultés économiques ni les refus possibles", response.nuance)
        point = self.plans["eo/tache-3/culture-p5"].arguments[1].point
        self.assertIn("la préparation transforme", point.french.casefold())
        self.assertIn("achievable steps", point.english)

    def test_argument_claims_state_the_benefit_or_risk_before_explaining_its_mechanism(self):
        for number, index, claim, explanation, example in (
            (5, 2, "contacts sur place", "Des conseils précis", "relire son CV"),
            (14, 2, "approfondir ce que l'on découvre", "demander une explication", "pourquoi elle enlève ses chaussures"),
            (26, 2, "éviter des malentendus", "comprendre son comportement", "prévoir leurs visites"),
            (30, 2, "sans pour autant se sentir vraiment chez soi", "un rythme de vie et une mentalité différents", "se sentir encore étrangère"),
            (31, 1, "banalise des comportements", "une manière acceptable de gérer", "commentée comme un spectacle"),
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

    def test_integration_codes_go_beyond_learning_the_language(self):
        response = self.response(30)
        self.assertIn("s'intégrer dans un pays étranger n'est pas vraiment facile", response.position_claire)
        self.assertIn("S'intégrer, ce n'est pas seulement s'installer", response.position_claire)
        argument = response.arguments[0]
        self.assertIn("beaucoup de codes culturels ne s'apprennent pas dans un manuel", argument.developpement)
        self.assertIn("quand il faut tutoyer ou vouvoyer", argument.exemple)
        self.assertIn("comment accepter ou refuser une invitation", argument.exemple)
        cue = self.plans["eo/tache-3/culture-p30"].arguments[0].example
        self.assertIn("tutoyer ou vouvoyer", cue.french)
        self.assertIn("use tu or vous", cue.english)

    def test_direct_framing_keeps_friendship_optional_and_integration_reciprocal(self):
        happiness = self.response(16)
        self.assertIn("on peut être heureux sans avoir d'amis", happiness.position_claire)
        self.assertNotIn("personne ne peut", happiness.position_claire)
        self.assertIn("ne pas avoir d'amis par choix", happiness.nuance)
        integration = self.response(30).arguments[1]
        self.assertIn("ne dépend pas seulement des efforts de la personne", integration.idea)
        self.assertIn("les groupes d'amis et les réseaux professionnels sont déjà formés", integration.developpement)
        self.assertIn("invité à déjeuner par politesse", integration.exemple)
        self.assertIn("le groupe d'amis qui se retrouve le week-end", integration.exemple)
        self.assertIn("un processus à deux sens", integration.consequence)

    def test_spoken_integration_keeps_belonging_distinct_from_practical_stability(self):
        model = self.models["eo/tache-3/culture-p30"]
        response = model.response
        self.assertEqual(model.argument_ids, (1, 2, 4))
        belonging = response.arguments[2]
        self.assertIn("sentiment intérieur d'être chez soi", belonging.developpement)
        self.assertIn("un logement stable peut très bien se sentir encore étrangère", belonging.exemple)
        self.assertIn("au-delà de l'adaptation pratique", belonging.consequence)
        self.assertIn("une société d'accueil ouverte", response.nuance)
        self.assertIn("un travail stable et de relations sincères", response.nuance)

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
        self.assertIn("une heure chaque soir", argument.exemple)
        self.assertIn("une réflexion plus profonde et plus structurée", argument.consequence)
        cue = self.plans[group].arguments[0]
        for language in ("french", "english"):
            point = getattr(cue.point, language)
            self.assertIn("réflexion" if language == "french" else "reflection", point)
            self.assertIn("concentration", point)
        self.assertIn("transports en commun", cue.example.french)
        self.assertIn("public transport", cue.example.english)
        self.assertIn("Un livre peut aussi se lire sur un écran", response.nuance)

    def test_requested_book_arguments_show_durable_learning_and_a_characters_choices(self):
        learning = self.response(6).arguments[1]
        for phrase in ("apprend les fractions", "quatre parts égales", "deux sont coloriées", "deux quarts font une moitié", "Il fait ensuite des exercices", "vérifie ses réponses avec le corrigé"):
            self.assertIn(phrase, learning.exemple)
        self.assertIn("connaissances solides et durables", learning.idea)
        for phrase in ("explique une méthode", "exercices pour l'appliquer", "Grâce au corrigé", "on repère ses erreurs", "relire l'explication et recommencer"):
            self.assertIn(phrase, learning.developpement)
        self.assertIn("réviser et utiliser plus tard", learning.consequence)
        cue = self.plans["eo/tache-3/culture-p6"].arguments[1].example
        self.assertIn("deux quarts font une moitié", cue.french)
        self.assertIn("exercices et corrigé", cue.french)
        self.assertIn("two quarters make a half", cue.english)
        self.assertIn("exercises and an answer key", cue.english)
        self.assertNotIn("beaucoup plus solides", learning.idea)
        story = self.response(6).arguments[2]
        self.assertIn("imaginer les scènes", story.developpement)
        self.assertIn("réfléchir à leurs choix", story.developpement)
        self.assertIn("auprès de sa mère malade", story.exemple)
        self.assertIn("la peur du personnage", story.exemple)
        self.assertIn("avant de juger les personnes", story.consequence)
        self.assertNotIn("mieux que la plupart", story.idea)
        self.assertNotIn("indispensable", self.response(6).conclusion)

    def test_reading_necessity_puts_reflection_before_alternatives_and_original_texts(self):
        model = self.models["eo/tache-3/culture-p20"]
        response = model.response
        reflection, alternatives, originals = response.arguments
        self.assertEqual(model.argument_ids, (1, 2, 4))
        self.assertIn("D'abord, la lecture reste la voie la plus profonde", response.position_claire)
        self.assertIn("Ensuite, la culture passe aujourd'hui aussi par les documentaires", response.position_claire)
        self.assertIn("Je pense d'abord", reflection.idea)
        self.assertIn("revenir en arrière et de réfléchir", reflection.developpement)
        self.assertIn("un essai ou un roman complet", reflection.exemple)
        self.assertIn("Cela dit", alternatives.idea)
        self.assertIn("par leur métier, par leurs rencontres ou par leur curiosité", alternatives.developpement)
        self.assertIn("une langue, un style et une époque", originals.developpement)
        self.assertIn("lire vraiment leurs œuvres", originals.exemple)

    def test_personal_letters_keep_emotional_attention_fuller_expression_and_family_memories(self):
        response = self.response(18)
        attention, reflection, memory = response.arguments
        self.assertIn("avait pris du temps spécialement pour nous", attention.developpement)
        self.assertIn("voir l'écriture de quelqu'un, de toucher le papier", attention.developpement)
        self.assertIn("on construisait des phrases plus complètes", reflection.developpement)
        self.assertIn("expliquer un sentiment ou une situation en détail", reflection.exemple)
        self.assertIn("une sorte de petite histoire personnelle ou familiale", memory.developpement)
        self.assertIn("grands-parents ou par un premier amour", memory.exemple)
        self.assertIn("garder le contact avec des personnes très éloignées", response.nuance)

    def test_reading_necessity_keeps_its_scope(self):
        reading = self.response(20)
        self.assertIn("on n'est pas obligé de lire pour être cultivé", reading.conclusion)
        self.assertIn("l'héritage culturel que rien d'autre ne remplace vraiment", reading.conclusion)
        self.assertIn("lire beaucoup ne suffit pas en soi à être cultivé", reading.nuance)

    def test_immigration_economic_contribution_keeps_work_and_skills_together(self):
        model = self.models["eo/tache-3/culture-p35"]
        response = model.response
        self.assertEqual(model.argument_ids, (1, 2, 3))
        self.assertIn("sur le plan économique, culturel et humain", response.position_claire)
        self.assertIn("possibilités de participer", response.position_claire)
        self.assertNotIn("Je ne parle pas seulement de main-d'œuvre", response.position_claire)
        economic = response.arguments[0]
        self.assertIn("par leur travail et leurs compétences", economic.idea)
        self.assertIn("produire des biens et à fournir des services", economic.developpement)
        self.assertIn("Leur expérience peut aussi aider leurs collègues", economic.developpement)
        self.assertIn("dans de bonnes conditions", economic.developpement)
        self.assertIn("si nécessaire, faire reconnaître leurs qualifications", economic.developpement)
        self.assertIn("Une technicienne", economic.exemple)
        self.assertIn("En leur montrant comment elle la répare", economic.exemple)
        self.assertIn("par leur travail et leurs compétences", response.conclusion)
        plan = self.plans[model.group]
        self.assertIn("leur travail, leurs compétences", plan.introduction.french)
        for cue in (plan.introduction, plan.arguments[0].point):
            self.assertIn("work and skills", cue.english)

    def test_immigration_contributions_do_not_condition_dignity_on_economic_usefulness(self):
        response = self.response(35)
        self.assertIn("réutiliser cette solution", response.arguments[0].consequence)
        self.assertIn("si la même panne se reproduit", response.arguments[0].consequence)
        self.assertIn("sans qu'elle ait à prouver son utilité économique", response.nuance)
        self.assertNotIn("immédiatement", response.nuance)

    def test_material_difficulty_includes_time_and_fatigue_not_only_expenses(self):
        response = self.response(29)
        material = response.arguments[0]
        self.assertIn("les contraintes matérielles", material.idea)
        self.assertIn("Le coût du logement", material.developpement)
        self.assertIn("possibilités d'emploi", material.developpement)
        self.assertIn("deux heures par jour dans les transports", material.exemple)
        self.assertIn("rentre fatiguée", material.exemple)
        self.assertIn("un logement plus proche dépasse son budget", material.exemple)
        self.assertIn("Respecter son budget", material.consequence)
        self.assertIn("un quotidien plus fatigant", material.consequence)
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
        cooking = self.plans["eo/tache-3/culture-p15"].conclusion.english
        self.assertIn("a starting point", cooking)
        self.assertIn("not enough on its own", cooking)
        celebrity = self.plans["eo/tache-3/culture-p33"].nuance.english
        self.assertIn("media attention", celebrity)
        self.assertIn("competence by fame alone", celebrity)
        immigration = self.plans["eo/tache-3/culture-p35"].nuance
        for phrase in ("Apports non automatiques", "efforts collectifs", "dignité sans preuve d'utilité"):
            self.assertIn(phrase, immigration.french)
        for phrase in ("Contributions are not automatic", "collective efforts", "dignity without proving usefulness"):
            self.assertIn(phrase, immigration.english)
