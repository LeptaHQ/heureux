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

    def test_association_cue_names_the_setting_helper_and_newcomer(self):
        cue = self.plans["eo/tache-3/culture-p24"].arguments[1].example
        for phrase in ("Repas d'association", "Une habituée aide l'arrivante", "l'arrivante réutilise"):
            self.assertIn(phrase, cue.french)
        for phrase in ("Association meal", "A regular helps a newcomer", "the newcomer then reuses"):
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
        self.assertIn("n'est pas forcément oublier", nuance.french)
        self.assertIn("does not necessarily mean forgetting", nuance.english)

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
            (11, 0, ("sa solitude en français", "une amie de son pays qui parle sa langue", "le dimanche ensemble")),
            (11, 1, ("Une infirmière", "compatriote", "fait reconnaître son diplôme", "quels documents", "à quel organisme")),
            (15, 1, ("cuisine portugaise", "poisson salé et séché", "conserver le poisson", "longs voyages en mer")),
            (15, 2, ("séjour au Ghana", "même sans bien parler sa langue", "piler le manioc", "lorsque j'essaierais à mon tour")),
            (19, 0, ("à Tokyo", "le métro chaque matin", "à voix basse", "évitent les appels téléphoniques")),
            (19, 1, ("documentaire sur les Pays-Bas, sous-titré en français", "des digues et des pompes", "gagner des terres sur la mer", "protection contre les inondations")),
            (19, 2, ("document traduit", "projet de logements", "dans son quartier", "pendant la réunion", "il ne comprend pas pourquoi", "certains défendent le projet et d'autres s'y opposent")),
            (20, 1, ("documentaire sur Guernica de Picasso", "gros plans", "personnages qui crient", "bombardement", "dénonce la violence de la guerre")),
            (24, 1, ("Dans une association", "chacun apporte un plat", "dans la langue du pays", "d'autres rencontres")),
            (26, 2, ("prévoir leurs visites à l'avance", "question d'organisation", "pas un refus de me voir")),
            (30, 2, ("attend que notre diplôme soit reconnu", "faire du bénévolat pour rencontrer des gens", "ne remplace pas le métier ni le revenu")),
            (31, 1, ("remarque sur le physique", "moments les plus drôles", "à peine le malaise")),
            (35, 2, ("distribution alimentaire", "La famille comprend", "comme les autres bénévoles, il contribue")),
        ):
            with self.subTest(response=number, argument=argument + 1):
                example = self.response(number).arguments[argument].exemple
                for phrase in required:
                    self.assertIn(phrase, example)

    def test_television_value_includes_shared_experiences_and_nonproductive_rest(self):
        response = self.response(12)
        self.assertIn("objets mal triés", response.arguments[0].exemple)
        self.assertIn("consignes de sa commune", response.arguments[0].exemple)
        self.assertIn("rassembler des personnes", response.arguments[1].idea)
        self.assertIn("Un match ou un spectacle en direct", response.arguments[1].developpement)
        self.assertIn("on partage des émotions", response.arguments[1].developpement)
        for phrase in ("Coupe du monde", "chez l'un d'eux", "se connaissent peu", "discutant à la mi-temps", "engager la conversation"):
            self.assertIn(phrase, response.arguments[1].exemple)
        self.assertIn("un moment partagé", response.arguments[1].consequence)
        self.assertIn("même lorsqu'on n'apprend rien de nouveau", response.arguments[2].idea)
        self.assertIn("éteint à la fin de l'épisode", response.arguments[2].exemple)
        plan = self.plans["eo/tache-3/culture-p12"]
        self.assertIn("Coupe du monde", plan.arguments[1].example.french)
        self.assertIn("World Cup", plan.arguments[1].example.english)
        self.assertIn("à la fin de l'épisode", plan.arguments[2].example.french)
        self.assertIn("at the end of the episode", plan.arguments[2].example.english)
        self.assertIn("des proches", plan.nuance.french)
        self.assertIn("loved ones", plan.nuance.english)
        self.assertIn("négliger le sommeil", response.nuance)
        self.assertIn("le temps avec les proches", response.nuance)
        self.assertNotIn("ce qu'on délaisse", response.nuance)
        self.assertIn("informer, réunir et détendre", response.conclusion)

    def test_reality_television_shows_distinct_comparison_normalisation_and_advertising_risks(self):
        response = self.response(31)
        comparison, normalisation, advertising = response.arguments
        self.assertIn("ses cours et son petit boulot du week-end", comparison.exemple)
        self.assertIn("une partie choisie de la vie du candidat", comparison.exemple)
        self.assertIn("rendre l'humiliation plus acceptable", normalisation.idea)
        self.assertIn("une insulte attire l'attention et fait rire", normalisation.developpement)
        self.assertIn("une manière normale de se faire remarquer", normalisation.developpement)
        self.assertIn("la plaisanterie plutôt que la peine", normalisation.developpement)
        self.assertIn("moments les plus drôles", normalisation.exemple)
        self.assertIn("à peine le malaise de la personne concernée", normalisation.exemple)
        self.assertIn("acceptable parce qu'elle amuse les autres", normalisation.consequence)
        self.assertIn("ce qu'elle fait vivre à celui qui la reçoit", normalisation.consequence)
        self.assertIn("Après l'émission", advertising.developpement)
        self.assertIn("sur les réseaux sociaux", advertising.developpement)
        self.assertIn("une marque le rémunère", advertising.developpement)
        self.assertIn("Après l'achat, il remarque", advertising.exemple)
        self.assertIn("partenariat rémunéré", advertising.exemple)
        self.assertIn("sans avoir identifié la publicité", advertising.consequence)
        self.assertIn("sans vouloir imiter", response.nuance)

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

    def test_cuisine_examples_show_country_customs_history_and_local_practice(self):
        model = self.models["eo/tache-3/culture-p15"]
        response = model.response
        plan = self.plans["eo/tache-3/culture-p15"]
        self.assertEqual(model.argument_ids, (1, 2, 4))
        self.assertEqual(model.source_prompts, ((
            "culture:p15",
            "La cuisine permet de connaître la culture des pays. Êtes-vous d'accord ?",
        ),))
        customs, history, practice = response.arguments
        self.assertIn("L'heure à laquelle on mange", customs.developpement)
        self.assertIn("l'organisation du quotidien", customs.developpement)
        self.assertIn("ce que ces habitudes représentent pour ses hôtes", customs.developpement)
        self.assertIn("au Sénégal", customs.exemple)
        self.assertIn("un visiteur pourrait partager du riz et du poisson avec une famille", customs.exemple)
        self.assertIn("autour d'un même grand plat", customs.exemple)
        self.assertIn("Ses hôtes lui expliqueraient", customs.exemple)
        self.assertIn("repas du soir leur permet de se retrouver et de discuter après le travail", customs.exemple)
        self.assertIn("cette famille garde un moment en commun", customs.consequence)
        self.assertIn("sans supposer que toutes les familles", customs.consequence)
        self.assertNotIn("sa femme finit tard", customs.exemple)
        self.assertNotIn("En observant et en posant des questions", response.arguments[0].developpement)
        self.assertIn("traces de l'histoire du pays", history.idea)
        self.assertIn("Les ingrédients et les méthodes de préparation", history.developpement)
        self.assertIn("conserver les aliments en l'absence de réfrigérateur", history.developpement)
        self.assertIn("poisson salé et séché, présent dans la cuisine portugaise", history.exemple)
        self.assertIn("conserver le poisson, notamment pendant de longs voyages en mer", history.exemple)
        self.assertIn("certaines recettes et les contraintes de la navigation", history.exemple)
        self.assertNotIn("un visiteur", history.exemple)
        self.assertNotIn("Le cuisinier lui explique", history.exemple)
        self.assertIn("une façon concrète d'aborder une histoire", history.consequence)
        self.assertIn("en cuisinant avec quelqu'un, même avec peu de mots", practice.idea)
        self.assertIn("on observe, on essaie et l'autre personne nous guide", practice.developpement)
        example = response.arguments[2].exemple
        self.assertIn("avec mon hôte", example)
        self.assertNotIn("français", example)
        self.assertLess(example.index("Il me montrerait"), example.index("lorsque j'essaierais à mon tour"))
        self.assertIn("une façon de cuisiner en la pratiquant avec lui", practice.consequence)
        self.assertIn("même sans bien parler sa langue", practice.exemple)
        self.assertTrue(response.position_claire.startswith("Oui, je pense que la cuisine est une bonne manière"))
        for phrase in ("comment ils vivent ensemble", "une partie de leur histoire", "gestes transmis dans les familles"):
            self.assertIn(phrase, response.position_claire)
        self.assertNotIn("je suis en partie d'accord", response.position_claire)
        self.assertIn("des habitudes, une histoire et des savoir-faire", response.conclusion)
        self.assertIn("elle ne montre pas tout", response.nuance)
        self.assertIn("les débats politiques ou la langue", response.nuance)
        self.assertIn("Les habitudes varient", response.nuance)
        self.assertNotIn("il faut qu'on découvre aussi la langue", response.nuance)
        for language, country, etiquette, fish, activity, language_limit in (
            ("french", "Au Sénégal", "après le travail", "poisson salé et séché", "piler le manioc", "malgré peu de langue commune"),
            ("english", "In Senegal", "after work", "fish salted and dried", "pound cassava", "despite little shared language"),
        ):
            self.assertIn(country, getattr(plan.arguments[0].example, language))
            self.assertIn(etiquette, getattr(plan.arguments[0].example, language))
            self.assertIn(fish, getattr(plan.arguments[1].example, language))
            cue = getattr(plan.arguments[2].example, language)
            self.assertIn(activity, cue)
            self.assertIn(language_limit, cue)
        self.assertNotIn("français", plan.arguments[2].example.french)
        self.assertNotIn("French", plan.arguments[2].example.english)

    def test_cuisine_uses_familiar_words_without_losing_the_cultural_links(self):
        text = spoken_text(self.response(15))
        for expression in ("histoire maritime", "savoir-faire culinaire", "morue"):
            self.assertNotIn(expression, text)
        for expression in (
            "poisson salé et séché",
            "longs voyages en mer",
            "une façon de cuisiner",
        ):
            self.assertIn(expression, text)

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
        self.assertIn("Tout n'est pas traduit", response.arguments[2].developpement)
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

    def test_compatriot_support_is_not_necessary_and_nuance_keeps_other_connections(self):
        response = self.response(11)
        self.assertEqual(self.models["eo/tache-3/culture-p11"].argument_ids, (1, 2, 4))
        other_support = response.arguments[2]
        self.assertIn("personnes d'une autre origine", other_support.idea)
        for phrase in (
            "aucun compatriote", "Une collègue d'un autre pays", "formulaire de demande d'aide au logement",
            "La nouvelle arrivante rejoint aussi", "groupe d'échange linguistique", "amis d'autres pays",
        ):
            self.assertIn(phrase, other_support.exemple)
        self.assertIn("sans fréquenter de gens de son pays", other_support.consequence)
        for phrase in (
            "ne pas se limiter à ses compatriotes", "d'autres habitants",
            "pratiquer la langue du pays", "la confiance et les affinités",
        ):
            self.assertIn(phrase, response.nuance)
        plan = self.plans["eo/tache-3/culture-p11"]
        self.assertIn("Ne pas rester entre compatriotes", plan.nuance.french)
        self.assertIn("Do not stay only among compatriots", plan.nuance.english)
        self.assertIn("Sans compatriotes connus", plan.arguments[2].example.french)
        self.assertIn("un formulaire", plan.arguments[2].example.french)
        self.assertIn("groupe linguistique", plan.arguments[2].example.french)
        self.assertIn("No known compatriots", plan.arguments[2].example.english)
        self.assertIn("a colleague helps with a form", plan.arguments[2].example.english)
        self.assertIn("friends in a language exchange group", plan.arguments[2].example.english)

    def test_compatriot_professional_example_shares_experience_without_guaranteeing_recognition(self):
        argument = self.response(11).arguments[1]
        self.assertIn("qui exerce déjà ce métier sur place", argument.exemple)
        self.assertIn("pour commencer ses démarches", argument.exemple)
        self.assertIn("l'information soit vérifiée auprès de l'organisme compétent", argument.consequence)
        self.assertNotIn("traducteur", argument.exemple)
        cue = self.plans["eo/tache-3/culture-p11"].arguments[1].example
        self.assertIn("Une infirmière", cue.french)
        self.assertIn("compatriote", cue.french)
        self.assertIn("A nurse", cue.english)
        self.assertIn("recognition of her qualification", cue.english)
        self.assertIn("compatriot", cue.english)

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

    def test_living_abroad_financial_claim_is_developed_before_its_concrete_example(self):
        argument = self.response(17).arguments[1]
        self.assertEqual(
            argument.idea,
            "Mais les difficultés financières peuvent rendre la vie à l'étranger éprouvante.",
        )
        self.assertIn("revenus insuffisants ou irréguliers", argument.developpement)
        self.assertIn("payer le logement devient inquiétant", argument.developpement)
        self.assertIn("payer le loyer", argument.exemple)
        cue = self.plans["eo/tache-3/culture-p17"].arguments[1]
        self.assertIn("La précarité financière", cue.point.french)
        self.assertIn("Financial insecurity", cue.point.english)

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
        self.assertIn("n'a pas l'argent pour voir son père malade", cue.french)
        self.assertIn("cannot afford to visit her sick father", cue.english)

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

    def test_forgotten_traditional_skill_requires_relearning_before_transmission(self):
        argument = self.response(27).arguments[1]
        self.assertIn("une danse traditionnelle à ses enfants", argument.exemple)
        self.assertIn("après des années sans danser", argument.exemple)
        self.assertIn("ne retrouve plus certains pas", argument.exemple)
        self.assertIn("Sa sœur les lui montre à nouveau", argument.exemple)
        self.assertIn("réapprendre une partie de la danse", argument.consequence)
        self.assertIn("la transmettre à son tour", argument.consequence)
        self.assertNotIn("brioche", argument.exemple)

    def test_cultural_forgetting_introduction_explains_practice_without_repeating_the_same_claim(self):
        response = self.response(27)
        self.assertIn("peut conduire à oublier", response.position_claire)
        self.assertIn("cet oubli n'est pas automatique", response.position_claire)
        self.assertIn("occasions de parler sa langue ou de pratiquer une tradition", response.position_claire)
        self.assertIn("les liens que l'on garde comptent aussi", response.position_claire)
        self.assertIn("on peut oublier certains mots", response.arguments[0].idea)
        self.assertIn("certains savoir-faire peuvent se perdre", response.arguments[1].idea)

    def test_regular_contact_keeps_cultural_expressions_in_use_after_twenty_years(self):
        argument = self.response(27).arguments[2]
        self.assertIn("depuis vingt ans à l'étranger", argument.exemple)
        self.assertIn("chaque semaine à sa sœur", argument.exemple)
        self.assertIn("continuer à employer des expressions", argument.exemple)
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
        self.assertIn("banaliser les comportements agressifs", plan.arguments[1].point.french)
        self.assertIn("remarque sur le physique", plan.arguments[1].example.french)
        self.assertIn("les rires passent avant le malaise", plan.arguments[1].example.french)
        self.assertIn("replayed as a funny moment", plan.arguments[1].example.english)
        self.assertIn("laughter overshadows the person's discomfort", plan.arguments[1].example.english)
        self.assertNotIn("instead of", plan.arguments[1].example.english)
        self.assertIn("mis en spectacle", plan.conclusion.french)
        self.assertIn("what is turned into a spectacle", plan.conclusion.english)
        self.assertNotIn("staged", plan.conclusion.english)
        self.assertIn("acheté en croyant suivre un conseil personnel", response.arguments[2].consequence)
        self.assertNotIn("Le regard critique doit", response.arguments[2].consequence)

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
            "Un dimanche", "son enfant qui a de la fièvre",
            "ne connaît pas encore les services de santé du quartier",
            "demande conseil à une voisine", "le numéro d'une clinique sans rendez-vous",
            "puisse vérifier les horaires avant de s'y rendre",
        ):
            self.assertIn(phrase, example)
        self.assertIn("reconstruire les repères pratiques", response.arguments[2].idea)
        self.assertIn("pas tous dès les premiers jours", response.arguments[2].consequence)
        cue = self.plans["eo/tache-3/culture-p9"].arguments[2].example
        self.assertIn("donne le numéro", cue.french)
        self.assertIn("vérifier les horaires", cue.french)
        self.assertIn("number to check opening hours", cue.english)

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
            (30, 2, "reprendre son métier", "faire reconnaître son diplôme", "notre diplôme soit reconnu"),
            (31, 1, "rendre l'humiliation plus acceptable", "une manière normale de se faire remarquer", "remarque sur le physique"),
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
        response = self.response(30)
        self.assertIn("s'intégrer dans un pays étranger n'est pas toujours facile", response.position_claire)
        self.assertIn("Le temps et l'accueil des autres comptent", response.position_claire)
        self.assertNotIn("comprendre les échanges", response.position_claire)
        plan = self.plans["eo/tache-3/culture-p30"]
        self.assertIn("participer et trouver sa place", plan.introduction.french)
        self.assertIn("participating and belonging", plan.introduction.english)
        argument = response.arguments[0]
        self.assertIn("pas forcément un problème de langue", argument.developpement)
        self.assertIn("comprendre les mots sans savoir", argument.developpement)
        self.assertIn("à quoi les autres font allusion", argument.developpement)
        self.assertNotIn("intervenir aussi spontanément", argument.developpement)
        stages = (
            argument.exemple.index("une émission qu'on n'a jamais vue"),
            argument.exemple.index("raconte la scène"),
            argument.exemple.index("se joindre à la conversation"),
        )
        self.assertEqual(stages, tuple(sorted(stages)))
        self.assertIn("on comprend ce qui les fait rire", argument.exemple)
        self.assertIn("se sentir moins à l'écart", argument.consequence)
        cue = plan.arguments[0].example
        self.assertIn("émission inconnue", cue.french)
        self.assertIn("on peut comprendre la blague et participer", cue.french)
        self.assertIn("unfamiliar TV scene", cue.english)
        self.assertIn("understand the joke and join in", cue.english)

    def test_direct_framing_keeps_friendship_optional_and_integration_reciprocal(self):
        happiness = self.response(16)
        self.assertIn("on peut être heureux sans avoir d'amis", happiness.position_claire)
        self.assertNotIn("personne ne peut", happiness.position_claire)
        self.assertIn("ne pas avoir d'amis par choix", happiness.nuance)
        integration = self.response(30).arguments[1]
        self.assertIn("on a besoin de se revoir", integration.developpement)
        self.assertIn("on ne peut pas créer des liens tout seul", integration.idea)
        self.assertIn("les membres nous invitent", integration.exemple)
        self.assertIn("une fête du club", integration.exemple)
        self.assertIn("plusieurs semaines", integration.exemple)
        self.assertIn("apprendre à mieux se connaître", integration.consequence)

    def test_spoken_integration_keeps_professional_access_distinct_from_social_contact(self):
        model = self.models["eo/tache-3/culture-p30"]
        response = model.response
        self.assertEqual(model.argument_ids, (1, 2, 3))
        professional = response.arguments[2]
        self.assertIn("même si on commence à connaître du monde", professional.idea)
        self.assertIn("Dans certaines professions", professional.developpement)
        self.assertIn("faire reconnaître son diplôme ou suivre une formation", professional.developpement)
        self.assertIn("attend que notre diplôme soit reconnu", professional.exemple)
        self.assertIn("bénévolat pour rencontrer des gens", professional.exemple)
        self.assertIn("ne remplace pas le métier ni le revenu", professional.exemple)
        self.assertIn("proches sur place", response.nuance)
        self.assertIn("de quoi vivre pendant les démarches", response.nuance)
        self.assertIn("discrimination", response.nuance)
        self.assertIn("tout en restant attaché à ses origines", response.nuance)

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

    def test_reading_alternatives_demonstrate_documentary_learning_and_guided_practice(self):
        response = self.response(20)
        listening, practice = response.arguments[1:]
        self.assertIn("les documentaires permettent aussi de comprendre des œuvres", listening.idea)
        self.assertIn("attirer notre attention sur un détail", listening.developpement)
        self.assertIn("le commentaire explique le contexte", listening.developpement)
        self.assertIn("comprendre ce qu'elle exprime", listening.developpement)
        for phrase in ("Guernica de Picasso", "gros plans", "personnages qui crient", "bombardement", "dénonce la violence de la guerre"):
            self.assertIn(phrase, listening.exemple)
        self.assertIn("culture artistique et historique", listening.consequence)
        self.assertIn("sans avoir nécessairement lu de livre", listening.consequence)
        cue = self.plans["eo/tache-3/culture-p20"].arguments[1].example
        self.assertIn("Guernica", cue.french)
        self.assertIn("bombing", cue.english)
        for phrase in ("motif de feuilles", "sa grand-mère", "repas de fête", "les participants lorsqu'ils reproduisent"):
            self.assertIn(phrase, practice.exemple)
        self.assertIn("sans passer obligatoirement par un livre", practice.consequence)
        self.assertIn("ces façons d'apprendre peuvent se compléter", response.nuance)
        self.assertIn("Les documentaires, les rencontres et la pratique", response.conclusion)
        self.assertIn("documentaries", self.plans["eo/tache-3/culture-p20"].conclusion.english)
        self.assertIn("style d'un écrivain", response.nuance)
        self.assertIn("comprendre, réfléchir et discuter ce que l'on découvre", response.nuance)
        self.assertIn("le nombre de livres lus ne dit pas tout", response.nuance)
        self.assertIn("reading a lot", self.plans["eo/tache-3/culture-p20"].nuance.english)

    def test_personal_letters_keep_emotional_attention_fuller_expression_and_family_memories(self):
        attention, reflection, memory = self.response(18).arguments
        self.assertIn("consacré une attention particulière", attention.idea)
        for phrase in ("Choisir une carte", "chercher quelques mots", "en pensant à cette personne", "sa présence"):
            self.assertIn(phrase, attention.developpement)
        for phrase in ("son anniversaire", "son père", "promenades du dimanche", "son écriture", "l'entendre lui parler"):
            self.assertIn(phrase, attention.exemple)
        self.assertIn("un signe de proximité", attention.consequence)
        self.assertIn("exprimer ses sentiments plus en profondeur", reflection.idea)
        for phrase in ("ce qu'on ressent et pourquoi", "une formule rapide", "des mots précis", "à voix haute"):
            self.assertIn(phrase, reflection.developpement)
        for phrase in ("lettre d'amour", "sa compagne", "cherchait du travail", "reprendre confiance", "un simple « je t'aime »"):
            self.assertIn(phrase, reflection.exemple)
        self.assertIn("pourquoi il compte dans notre vie", reflection.consequence)
        for phrase in ("une boîte de souvenirs de famille", "envoyée par sa grand-mère", "travail dans un café", "la petite chambre qu'elle louait"):
            self.assertIn(phrase, memory.exemple)
        self.assertIn("Elle découvre une période", memory.consequence)
        self.assertIn("la vie de sa grand-mère qu'elle n'a pas connue elle-même", memory.consequence)
        self.assertNotIn("compte numérique", memory.idea)
        response = self.response(18)
        self.assertIn("un message numérique peut aussi être réfléchi", response.nuance)
        self.assertIn("attentionné et conservé", response.nuance)
        self.assertIn("se perdre", response.nuance)
        for phrase in ("L'attention, les mots et les souvenirs", "garde les lettres pour certaines occasions"):
            self.assertIn(phrase, response.conclusion)
        plan = self.plans["eo/tache-3/culture-p18"]
        self.assertIn("un geste personnel", plan.arguments[0].point.french)
        self.assertIn("exprimer pleinement ses sentiments", plan.arguments[1].point.french)
        self.assertIn("fuller expression", plan.conclusion.english)

    def test_reading_necessity_and_personal_cultural_forgetting_keep_their_scope(self):
        reading = self.response(20)
        self.assertIn("pas une condition unique pour être cultivé", reading.conclusion)
        self.assertIn("un documentaire sur Guernica", reading.arguments[1].exemple)
        self.assertIn("sans avoir nécessairement lu de livre sur le sujet", reading.arguments[1].consequence)
        self.assertNotIn("elle lit peu", reading.arguments[1].exemple)
        forgetting = self.response(27)
        self.assertEqual(self.models["eo/tache-3/culture-p27"].argument_ids, (1, 4, 3))
        self.assertIn("lorsqu'on utilise moins sa langue d'origine", forgetting.arguments[0].idea)
        self.assertIn("sa grand-mère lui disait souvent", forgetting.arguments[0].exemple)
        self.assertIn("sans savoir expliquer le message", forgetting.arguments[0].exemple)
        self.assertIn("même lorsque l'on continue à parler sa langue", forgetting.arguments[1].idea)
        self.assertIn("une danse traditionnelle à ses enfants", forgetting.arguments[1].exemple)
        self.assertIn("ne retrouve plus certains pas", forgetting.arguments[1].exemple)
        self.assertIn("Sa sœur les lui montre à nouveau", forgetting.arguments[1].exemple)
        self.assertNotIn("Les enfants", forgetting.arguments[1].developpement)
        self.assertIn("Un long séjour à l'étranger n'empêche donc pas, à lui seul", forgetting.arguments[2].consequence)
        self.assertIn("ne signifie donc pas forcément qu'une ancienne culture a été oubliée", forgetting.nuance)

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
        cooking = self.plans["eo/tache-3/culture-p15"].introduction.english
        self.assertIn("part of a culture", cooking)
        self.assertIn("not everything", cooking)
        celebrity = self.plans["eo/tache-3/culture-p33"].nuance.english
        self.assertIn("media attention", celebrity)
        self.assertIn("competence by fame alone", celebrity)
        immigration = self.plans["eo/tache-3/culture-p35"].nuance
        for phrase in ("Apports non automatiques", "efforts collectifs", "dignité sans preuve d'utilité"):
            self.assertIn(phrase, immigration.french)
        for phrase in ("Contributions are not automatic", "collective efforts", "dignity without proving usefulness"):
            self.assertIn(phrase, immigration.english)
