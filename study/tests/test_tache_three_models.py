"""Reviewed EO3 defaults must not mutate published or learner-owned content."""

from copy import deepcopy
from dataclasses import FrozenInstanceError, asdict
import hashlib
from io import StringIO
import json
import re
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from django.core.management import call_command
from django.template import Context, Engine
from django.template.loader import render_to_string
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone
from django.utils.html import escape

from study import catalogue, content_loader as content
from study.account_services import provision_user_study_data
from study.card_presentation import card_payload
from study.models import (
    Annotation, AnnotationKind, Card, CardType, PersonalResponse, Prompt,
)
from study.oral_highlights import AnnotationRootText
from study.oral_history import variant_annotation_key
from study.response_personalization import EffectiveArgument, EffectiveResponse, effective_response
from study.routing import prompt_detail_url
from study.tache_three_models import (
    MODELS_DIR, load_tache_three_models, reviewed_model, spoken_text,
)

from . import factories


def original_effective(prompt):
    model = prompt.model_content
    return EffectiveResponse(
        **{name: model[name] for name in (
            "reformulation", "position", "position_claire", "nuance", "conclusion",
        )},
        arguments=tuple(EffectiveArgument(**row) for row in model["arguments"]),
        is_personal=False,
    )


class TacheThreeModelContentTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.sources = content.parse_responses()
        cls.payload = json.loads((MODELS_DIR / "culture.json").read_text())

    def setUp(self):
        catalogue.clear_catalogue_cache()
        self.addCleanup(catalogue.clear_catalogue_cache)

    def load(self, payload):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "culture.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            return load_tache_three_models(Path(directory), responses=self.sources)

    def test_argument_identities_are_optional_unique_and_independent_of_spoken_order(self):
        payload = deepcopy(self.payload)
        group = next(iter(payload["responses"]))
        baseline = self.load(payload)[f"eo/tache-3/{group}"]
        payload["responses"][group]["argument_ids"] = [1, 4, 2]
        revised = self.load(payload)[baseline.group]
        self.assertEqual(revised.argument_ids, (1, 4, 2))
        self.assertEqual(revised.response, baseline.response)
        for identities in ([1, 1, 2], [1, True, 2], [0, 2, 3], [1, 2], "123", [1, 2, 10000]):
            with self.subTest(identities=identities):
                payload["responses"][group]["argument_ids"] = identities
                with self.assertRaisesMessage(ValueError, "argument identities"):
                    self.load(payload)

    def test_culture_covers_every_publication_and_only_genuine_equivalents(self):
        models = catalogue.tache_three_models()
        culture = [source for source in self.sources if source.theme == "Culture"]
        self.assertEqual(len(culture), 31)
        self.assertEqual(sum(len(source.prompts) for source in culture), 39)
        for source in culture:
            model = models[source.semantic_group]
            self.assertEqual(
                model.source_prompts,
                tuple((prompt.content_key, prompt.text) for prompt in source.prompts),
            )
        for group, members in {
            "culture-p3": {"culture:p3", "economie:p5"},
            "culture-p6": {"culture:p6", "education:p8"},
            "culture-p10": {"culture:p10", "culture:p32"},
            "culture-p13": {"culture:p13", "education:p11"},
            "culture-p16": {"culture:p16", "famille:p8"},
            "culture-p17": {"culture:p17", "culture:p22"},
            "culture-p18": {"culture:p18", "culture:p23"},
            "culture-p24": {"culture:p24", "culture:p28"},
        }.items():
            self.assertEqual(
                {key for key, _text in models[f"eo/tache-3/{group}"].source_prompts},
                members,
            )
        for first, second in (
            ("culture-p2", "culture-p8"), ("culture-p6", "culture-p20"),
            ("culture-p9", "culture-p29"), ("culture-p9", "culture-p30"),
            ("culture-p14", "culture-p19"), ("culture-p11", "culture-p24"),
            ("culture-p12", "culture-p31"),
        ):
            self.assertNotEqual(
                models[f"eo/tache-3/{first}"].response,
                models[f"eo/tache-3/{second}"].response,
            )

    def test_reviewed_catalogue_covers_the_whole_oral_task_three_corpus(self):
        models = catalogue.tache_three_models()
        self.assertEqual(len(models), 131)
        self.assertEqual(set(models), {source.semantic_group for source in self.sources})
        self.assertEqual(
            {key for model in models.values() for key, _text in model.source_prompts},
            {prompt.content_key for source in self.sources for prompt in source.prompts},
        )
        self.assertEqual(sum(len(model.source_prompts) for model in models.values()), 167)
        self.assertEqual(
            set(models),
            set(content.load_tache_three_subject_hints()),
        )

    def test_economie_covers_all_sources_and_retains_distinct_questions(self):
        models = catalogue.tache_three_models()
        sources = [source for source in self.sources if source.theme == "Economie"]
        self.assertEqual(len(sources), 16)
        self.assertEqual(sum(len(source.prompts) for source in sources), 18)
        publications = {
            prompt.content_key for source in self.sources for prompt in source.prompts
            if prompt.theme == "Economie"
        }
        self.assertEqual(len(publications), 24)
        self.assertTrue(
            publications <= {key for model in models.values() for key, _text in model.source_prompts}
        )
        for source in sources:
            self.assertEqual(
                models[source.semantic_group].source_prompts,
                tuple((prompt.content_key, prompt.text) for prompt in source.prompts),
            )
        for group, members in {
            "economie-p6": {"economie:p6", "economie:p21"},
            "economie-p9": {"economie:p9", "economie:p13"},
        }.items():
            self.assertEqual(
                {key for key, _text in models[f"eo/tache-3/{group}"].source_prompts},
                members,
            )
        for first, second in (
            ("economie-p1", "economie-p15"), ("economie-p3", "economie-p17"),
            ("economie-p9", "economie-p18"), ("economie-p18", "sante-p22"),
            ("economie-p16", "environnement-p9"),
            ("economie-p24", "technologie-p20"),
        ):
            self.assertNotEqual(
                models[f"eo/tache-3/{first}"].response,
                models[f"eo/tache-3/{second}"].response,
            )

    def test_economie_arguments_preserve_scope_and_avoid_unsupported_guarantees(self):
        models = catalogue.tache_three_models()
        response = lambda key: models[f"eo/tache-3/economie-p{key}"].response
        self.assertIn("Si je m'installais", response(1).position_claire)
        self.assertIn("province ou le territoire", response(1).arguments[0].developpement)
        self.assertIn("pas que tous les postes", response(1).arguments[1].developpement)
        self.assertIn("à l'intérieur du sport", response(2).arguments[1].idea)
        self.assertIn("budgets des clubs et des hôpitaux", response(2).nuance)
        self.assertIn("l'aptitude doit être vérifiée", response(3).position_claire)
        self.assertIn("ne prouve pas non plus une incapacité", response(3).nuance)
        self.assertIn("temps de se réveiller", response(4).arguments[0].developpement)
        self.assertIn("relais", response(4).arguments[2].developpement)
        self.assertIn("manque chronique de sommeil", response(4).nuance)
        self.assertIn("répartit une partie", response(6).arguments[0].exemple)
        self.assertIn("deux consignes", response(6).arguments[1].exemple)
        self.assertIn("deux mois", response(9).arguments[2].exemple)
        self.assertIn("projet d'épargne", response(9).nuance)
        self.assertIn("financer un déplacement", response(10).arguments[2].exemple)
        self.assertIn("quelle proportion", response(14).nuance)
        self.assertIn("ne trouve pas de lieu sûr dans son pays", response(14).arguments[0].exemple)
        self.assertIn("chercher refuge à l'étranger", response(14).arguments[0].exemple)
        migration_cue = catalogue.tache_three_subject_hints()["eo/tache-3/economie-p14"].arguments[0].example
        self.assertIn("dans son pays", migration_cue.french)
        self.assertIn("protection à l'étranger", migration_cue.french)
        self.assertIn("no safe refuge in its country", migration_cue.english)
        self.assertIn("protection abroad", migration_cue.english)
        self.assertIn("son partenaire", response(14).arguments[2].exemple)
        self.assertIn("un permis est toujours nécessaire", response(15).arguments[0].developpement)
        self.assertIn("deux questions différentes", response(15).arguments[2].developpement)
        self.assertIn("recettes serve à l'entretien", response(16).arguments[2].exemple)
        self.assertIn("ni la fermeté aux hommes", response(17).arguments[1].developpement)
        self.assertIn("un carnet", response(18).arguments[1].exemple)
        self.assertIn("Aucun seuil universel", response(18).nuance)
        self.assertIn("pas devenu soudainement plus difficile", response(20).arguments[1].exemple)
        self.assertIn("métiers de bureau", response(20).nuance)
        self.assertIn("coût collectif", response(22).nuance)
        self.assertIn("ne prouve pas", response(22).nuance)
        self.assertIn("tout le monde ne peut pas travailler", response(23).nuance)
        self.assertIn("respecte son accord", response(23).arguments[2].exemple)
        self.assertIn("restent des trajets automobiles", response(24).nuance)

    def test_every_model_has_three_distinct_supported_arguments_and_speakable_length(self):
        for identity, model in catalogue.tache_three_models().items():
            response = model.response
            with self.subTest(group=identity):
                self.assertEqual([argument.order for argument in response.arguments], [1, 2, 3])
                self.assertGreaterEqual(len(spoken_text(response).split()), 300)
                self.assertLessEqual(len(spoken_text(response).split()), 430)
                for name in ("idea", "developpement", "exemple"):
                    values = [getattr(argument, name) for argument in response.arguments]
                    self.assertEqual(len(set(values)), 3)
                    self.assertTrue(all(value.strip() for value in values))
                self.assertTrue(response.position_claire)
                self.assertTrue(response.nuance)
                self.assertTrue(response.conclusion)
                self.assertNotIn("selon une étude", spoken_text(response).casefold())

    def test_famille_covers_all_its_sources_without_merging_related_questions(self):
        models = catalogue.tache_three_models()
        sources = [source for source in self.sources if source.theme == "Famille"]
        self.assertEqual(len(sources), 14)
        self.assertEqual(sum(len(source.prompts) for source in sources), 16)
        publications = [
            prompt for source in self.sources for prompt in source.prompts
            if prompt.theme == "Famille"
        ]
        self.assertEqual(len(publications), 17)
        covered = {key for model in models.values() for key, _text in model.source_prompts}
        self.assertTrue({prompt.content_key for prompt in publications} <= covered)
        for source in sources:
            self.assertEqual(
                models[source.semantic_group].source_prompts,
                tuple((prompt.content_key, prompt.text) for prompt in source.prompts),
            )
        for group, members in {
            "famille-p4": {"famille:p4", "famille:p17"},
            "famille-p6": {"famille:p6", "famille:p15"},
        }.items():
            self.assertEqual(
                {key for key, _text in models[f"eo/tache-3/{group}"].source_prompts},
                members,
            )
        for first, second in (
            ("famille-p2", "famille-p16"), ("famille-p9", "culture-p16"),
            ("famille-p9", "famille-p10"), ("famille-p1", "famille-p12"),
        ):
            self.assertNotEqual(
                models[f"eo/tache-3/{first}"].response,
                models[f"eo/tache-3/{second}"].response,
            )

    def test_famille_examples_answer_the_specific_issue_without_absolute_promises(self):
        models = catalogue.tache_three_models()
        response = lambda key: models[f"eo/tache-3/famille-p{key}"].response
        self.assertIn("conditions d'accès", response(1).nuance)
        self.assertIn("change de collège", response(1).arguments[0].exemple)
        self.assertIn("anciens camarades", response(1).arguments[0].exemple)
        self.assertIn("harcèlement", response(1).arguments[2].developpement)
        self.assertIn("canadiens", response(2).reformulation)
        self.assertIn("cohabitation durable", response(2).nuance)
        self.assertIn("toujours", response(3).position_claire)
        self.assertIn("plateforme", response(3).arguments[2].exemple)
        self.assertIn("sans promettre une guérison", response(4).arguments[1].exemple)
        self.assertIn("vie privée", response(4).nuance)
        self.assertIn("pas une source de soutien", response(5).nuance)
        self.assertIn("à partir d'une certaine note", response(6).arguments[1].developpement)
        self.assertIn("ne pas remarquer les efforts", response(6).arguments[1].developpement)
        self.assertIn("l'enseignant", response(6).arguments[2].exemple)
        self.assertIn("rémunération", response(7).arguments[2].exemple)
        self.assertIn("dire non", response(7).nuance)
        self.assertIn("ne veut pas dire vivre sans aucun lien", response(9).nuance)
        self.assertIn("chorale", response(9).arguments[2].exemple)
        self.assertNotEqual(response(9).arguments[2].exemple, models["eo/tache-3/culture-p16"].response.arguments[2].exemple)
        self.assertIn("ce n'est pas automatique", response(10).position_claire)
        self.assertIn("répéter ses confidences", response(10).arguments[2].exemple)
        self.assertIn("abonnement Internet", response(11).arguments[1].exemple)
        self.assertIn("n'empêche ni l'entraide", response(11).nuance)
        self.assertIn("sans menaces ni humiliation", response(12).nuance)
        self.assertIn("propose de commencer ses devoirs à dix-sept heures", response(12).arguments[2].exemple)
        self.assertIn("bilinguisme parfait n'est pas garanti", response(13).nuance)
        self.assertIn("ressources", response(13).arguments[2].exemple)
        self.assertIn("voire aucune tâche", response(14).nuance)
        self.assertIn("vérifier le stock", response(14).arguments[2].exemple)
        self.assertIn("après 25 ans", response(16).position_claire)
        self.assertIn("sans devoir demander la permission", response(16).arguments[2].exemple)
        self.assertIn("cohabitation durable", response(16).nuance)

    def test_education_covers_every_variant_and_retains_distinct_learning_scopes(self):
        models = catalogue.tache_three_models()
        sources = [source for source in self.sources if source.theme == "Education"]
        self.assertEqual(len(sources), 20)
        self.assertEqual(sum(len(source.prompts) for source in sources), 26)
        publications = {
            prompt.content_key for source in self.sources for prompt in source.prompts
            if prompt.theme == "Education"
        }
        self.assertEqual(len(publications), 25)
        covered = {key for model in models.values() for key, _text in model.source_prompts}
        self.assertTrue(publications <= covered)
        for source in sources:
            self.assertEqual(
                models[source.semantic_group].source_prompts,
                tuple((prompt.content_key, prompt.text) for prompt in source.prompts),
            )
        for group, members in {
            "education-p2": {"education:p2", "education:p9", "education:p25"},
            "education-p10": {"education:p10", "education:p24"},
            "education-p16": {"education:p16", "economie:p12"},
            "education-p19": {"education:p19", "technologie:p14"},
            "education-p20": {"education:p20", "economie:p19"},
        }.items():
            self.assertEqual(
                {key for key, _text in models[f"eo/tache-3/{group}"].source_prompts},
                members,
            )
        for first, second in (
            ("education-p2", "education-p7"), ("education-p12", "education-p21"),
            ("education-p1", "culture-p9"), ("education-p1", "culture-p30"),
            ("education-p14", "culture-p14"), ("education-p14", "culture-p19"),
            ("education-p15", "education-p3"), ("education-p3", "famille-p1"),
        ):
            self.assertNotEqual(
                models[f"eo/tache-3/{first}"].response,
                models[f"eo/tache-3/{second}"].response,
            )

    def test_environnement_covers_all_variants_and_retains_group_boundaries(self):
        models = catalogue.tache_three_models()
        sources = [source for source in self.sources if source.theme == "Environnement"]
        self.assertEqual(len(sources), 11)
        self.assertEqual(sum(len(source.prompts) for source in sources), 15)
        for source in sources:
            self.assertEqual(
                models[source.semantic_group].source_prompts,
                tuple((prompt.content_key, prompt.text) for prompt in source.prompts),
            )
        publications = {
            prompt.content_key for source in self.sources for prompt in source.prompts
            if prompt.theme == "Environnement"
        }
        self.assertEqual(len(publications), 16)
        self.assertTrue(
            publications <= {key for model in models.values() for key, _text in model.source_prompts}
        )
        for group, members in {
            "environnement-p7": {"environnement:p7", "environnement:p12", "economie:p8"},
            "environnement-p9": {"environnement:p9", "environnement:p16"},
            "environnement-p14": {"environnement:p14", "economie:p7"},
        }.items():
            self.assertEqual(
                {key for key, _text in models[f"eo/tache-3/{group}"].source_prompts},
                members,
            )
        for first, second in ((2, 4), (6, 8), (7, 13)):
            self.assertNotEqual(
                models[f"eo/tache-3/environnement-p{first}"].response,
                models[f"eo/tache-3/environnement-p{second}"].response,
            )

    def test_environnement_examples_distinguish_verified_facts_from_illustrations(self):
        models = catalogue.tache_three_models()
        response = lambda key: models[f"eo/tache-3/environnement-p{key}"].response
        self.assertIn("tout aussi utile", response(1).nuance)
        self.assertIn("bison d'Europe", response(2).arguments[1].exemple)
        self.assertIn("pas que toute espèce", response(2).arguments[1].exemple)
        self.assertIn("besoin médical", response(3).nuance)
        self.assertIn("Trier et réduire", response(3).nuance)
        self.assertIn("retardée indéfiniment", response(4).nuance)
        self.assertIn("rues voisines", response(6).arguments[0].exemple)
        self.assertIn("rémunération viable", response(7).arguments[2].exemple)
        self.assertIn("mobilité réduite", response(8).nuance)
        self.assertIn("raccourci automobile", response(8).arguments[2].exemple)
        self.assertIn("mesurer le bruit", response(8).arguments[2].exemple)
        self.assertIn("rues voisines", response(8).arguments[2].exemple)
        self.assertIn("autres causes de tension", response(9).arguments[1].exemple)
        self.assertIn("Exemple français documenté", response(11).reformulation)
        self.assertIn("à adapter", response(11).reformulation)
        self.assertNotIn("son propre pays", spoken_text(response(11)))
        self.assertIn("Info-tri", response(11).arguments[0].developpement)
        self.assertIn("Dans une commune qui propose", response(11).arguments[1].exemple)
        self.assertIn("pas une réussite nationale mesurée", response(11).nuance)
        self.assertIn("cadre européen", response(13).arguments[0].developpement)
        self.assertIn("pas d'une absence absolue de traitement", response(13).arguments[0].developpement)
        self.assertIn("hausse des volumes", response(14).arguments[2].developpement)
        self.assertIn("aucune activité n'est sans impact", response(14).nuance)

    def test_technologie_covers_every_variant_without_merging_related_scopes(self):
        models = catalogue.tache_three_models()
        sources = [source for source in self.sources if source.theme == "Technologie"]
        self.assertEqual(len(sources), 20)
        self.assertEqual(sum(len(source.prompts) for source in sources), 29)
        for source in sources:
            self.assertEqual(
                models[source.semantic_group].source_prompts,
                tuple((prompt.content_key, prompt.text) for prompt in source.prompts),
            )
        publications = {
            prompt.content_key for source in self.sources for prompt in source.prompts
            if prompt.theme == "Technologie"
        }
        self.assertEqual(len(publications), 26)
        self.assertTrue(
            publications <= {key for model in models.values() for key, _text in model.source_prompts}
        )
        for group, members in {
            "technologie-p1": {"technologie:p1", "technologie:p9"},
            "technologie-p2": {"technologie:p2", "technologie:p8"},
            "technologie-p13": {"technologie:p13", "technologie:p25"},
            "technologie-p17": {"technologie:p17", "economie:p11"},
            "technologie-p20": {
                "technologie:p20", "environnement:p5",
                "environnement:p10", "environnement:p15",
            },
            "technologie-p22": {"technologie:p22", "technologie:p23", "technologie:p26"},
        }.items():
            self.assertEqual(
                {key for key, _text in models[f"eo/tache-3/{group}"].source_prompts},
                members,
            )
        for first, second in ((2, 11), (3, 5), (5, 6), (4, 7), (21, 24)):
            self.assertNotEqual(
                models[f"eo/tache-3/technologie-p{first}"].response,
                models[f"eo/tache-3/technologie-p{second}"].response,
            )

    def test_technologie_examples_respect_possibility_and_specific_learning_mechanisms(self):
        models = catalogue.tache_three_models()
        response = lambda key: models[f"eo/tache-3/technologie-p{key}"].response
        self.assertIn("fausse relation", response(1).position_claire)
        self.assertIn("identification", response(2).arguments[1].exemple)
        self.assertIn("découvertes culturelles", response(3).arguments[2].idea)
        self.assertIn("transport adapté", response(4).arguments[2].exemple)
        self.assertIn("autre support n'est pas automatiquement", response(5).nuance)
        self.assertIn("il faut que l'image soit datée", response(6).arguments[1].developpement)
        self.assertIn("plateformes", response(7).nuance)
        self.assertIn("créer un compte", response(10).nuance)
        self.assertIn("sans aucun téléphone", response(11).reformulation)
        self.assertNotIn("téléphone fixe", spoken_text(response(11)))
        self.assertIn("perdu ou abîmé", response(12).arguments[2].exemple)
        self.assertIn("réponse permanente", response(13).position_claire)
        self.assertIn("exclusion faute de moyens", response(15).nuance)
        self.assertIn("adulte de confiance", response(16).arguments[2].exemple)
        self.assertIn("liquides", response(17).arguments[0].exemple)
        self.assertIn("satellites", response(17).nuance)
        self.assertIn("dispositif automatique", response(17).arguments[2].exemple)
        self.assertIn("reste un achat en ligne", response(18).nuance)
        self.assertIn("moyen de paiement", response(18).arguments[2].exemple)
        self.assertIn("raconter une histoire", response(19).arguments[1].exemple)
        self.assertIn("rôles", response(19).arguments[2].exemple)
        self.assertIn("utilisent encore ce moyen", response(20).nuance)
        self.assertIn("catégories se recoupent", response(21).nuance)
        self.assertIn("applique lui aussi cette règle", response(22).arguments[2].exemple)
        self.assertIn("rediffusions", response(24).nuance)

    def test_technologie_keeps_creative_expression_distinct_and_reuses_apt_media_reasoning(self):
        models = catalogue.tache_three_models()
        games = models["eo/tache-3/technologie-p19"].response
        self.assertIn("rampe", games.arguments[0].exemple)
        self.assertIn("exprimer son imagination", games.arguments[1].idea)
        self.assertIn("pas seulement la solution prévue", games.arguments[1].developpement)
        self.assertIn("raconter une histoire", games.arguments[1].exemple)
        self.assertIn("échangent les rôles", games.arguments[2].exemple)
        media = models["eo/tache-3/technologie-p21"].response.arguments[0]
        other_media = models["eo/tache-3/technologie-p24"].response.arguments[1]
        self.assertEqual(media.developpement, other_media.developpement)
        self.assertEqual(media.exemple, other_media.exemple)
        plan = catalogue.tache_three_subject_hints()["eo/tache-3/technologie-p19"]
        self.assertIn("exprimer une histoire", plan.arguments[1].point.french)
        self.assertIn("express a story", plan.arguments[1].point.english)

    def test_sante_preserves_coverage_and_distinguishes_state_sales_from_a_ban(self):
        models = catalogue.tache_three_models()
        sources = [source for source in self.sources if source.theme == "Sante"]
        self.assertEqual(len(sources), 19)
        self.assertEqual(sum(len(source.prompts) for source in sources), 24)
        for source in sources:
            self.assertEqual(
                models[source.semantic_group].source_prompts,
                tuple((prompt.content_key, prompt.text) for prompt in source.prompts),
            )
        for first, second in ((1, 5), (9, 24), (10, 12), (15, 18), (17, 21)):
            self.assertEqual(
                {key for key, _text in models[f"eo/tache-3/sante-p{first}"].source_prompts},
                {f"sante:p{first}", f"sante:p{second}"},
            )
        for first, second in ((1, 8), (2, 19), (6, 13), (10, 11), (20, 22)):
            self.assertNotEqual(
                models[f"eo/tache-3/sante-p{first}"].response,
                models[f"eo/tache-3/sante-p{second}"].response,
            )
        state_sales = models["eo/tache-3/sante-p11"].response
        self.assertIn("organisme public", state_sales.position_claire)
        self.assertIn("ne vend pas lui-même partout", state_sales.position_claire)
        self.assertIn("interdire toute vente", state_sales.nuance)
        self.assertIn("indépendantes", state_sales.conclusion)

    def test_sante_uses_specific_supports_without_health_or_income_guarantees(self):
        models = catalogue.tache_three_models()
        response = lambda key: models[f"eo/tache-3/sante-p{key}"].response
        self.assertIn("hors compétition", response(1).nuance)
        self.assertIn("également les parents", response(2).arguments[2].exemple)
        self.assertIn("financement", response(3).arguments[2].consequence)
        self.assertIn("consentement", response(4).arguments[2].developpement)
        self.assertIn("ne suffit", response(6).conclusion)
        self.assertIn("ne dit pas à lui seul", response(7).nuance)
        self.assertIn("handicap", response(8).arguments[2].exemple)
        self.assertIn("pas connaître les motivations", response(9).nuance)
        self.assertIn("pas une raison", response(10).arguments[1].developpement)
        self.assertIn("base commune", response(13).arguments[2].developpement)
        self.assertIn("village bien relié", response(14).nuance)
        self.assertIn("volontairement", response(15).position_claire)
        self.assertIn("illustratif à personnaliser", response(16).reformulation)
        self.assertIn("motivé sans", response(17).nuance)
        self.assertIn("achats non autorisés", response(19).arguments[2].exemple)
        self.assertIn("défaut de gestion", response(20).nuance)
        self.assertIn("je n'en ferais pas une condition universelle", response(22).position_claire)
        self.assertIn("type 1", response(23).arguments[0].exemple)
        self.assertIn("sans l'avis du professionnel", response(23).nuance)
        self.assertNotIn("guérissent le plus souvent", spoken_text(response(23)))

    def test_economie_transport_benefits_require_real_changes_and_distinct_contributions(self):
        models = catalogue.tache_three_models()
        free_transport = models["eo/tache-3/economie-p22"].response
        self.assertIn("une ligne fiable convient au trajet", free_transport.arguments[1].developpement)
        self.assertIn("Si ces personnes laissent leur voiture chez elles", free_transport.arguments[1].developpement)
        self.assertEqual(models["eo/tache-3/economie-p22"].argument_ids, (1, 4, 2))
        self.assertIn("laisser sa voiture chez elle", free_transport.arguments[1].exemple)
        self.assertIn("bibliothèque", free_transport.arguments[2].exemple)
        self.assertIn("ne prouve pas", free_transport.nuance)
        car_free = models["eo/tache-3/economie-p24"].response
        self.assertIn("bouger régulièrement", car_free.arguments[1].idea)
        self.assertIn("marche alors matin et soir", car_free.arguments[1].exemple)
        self.assertIn("L'entrée est moins encombrée", car_free.arguments[2].exemple)
        personal_help = models["eo/tache-3/economie-p23"].response.arguments[2]
        self.assertIn("distribution alimentaire", personal_help.exemple)
        self.assertIn("n'organise pas lui-même la distribution", personal_help.consequence)
        plan = catalogue.tache_three_subject_hints()["eo/tache-3/economie-p23"]
        self.assertIn("people around them", plan.nuance.english)

    def test_education_addresses_qualifiers_priorities_and_realistic_conditions(self):
        models = catalogue.tache_three_models()
        response = lambda key: models[f"eo/tache-3/education-p{key}"].response
        self.assertIn("résultat assuré", response(1).position_claire)
        self.assertIn("pas figée", response(1).arguments[0].consequence)
        self.assertIn("accueil", response(1).conclusion)
        self.assertIn("la santé", response(2).nuance)
        self.assertNotIn("âge limite biologique", spoken_text(response(2)))
        self.assertIn("besoin d'accessibilité", response(3).nuance)
        self.assertIn("ne garantit pas la concentration", response(3).arguments[0].consequence)
        self.assertIn("règles applicables", response(4).nuance)
        self.assertIn("soutien extérieur", response(4).arguments[2].exemple)
        for argument in response(5).arguments:
            self.assertTrue(argument.idea.endswith("?"))
        self.assertIn("admissibilité", response(5).nuance)
        self.assertNotIn("six mois", spoken_text(response(5)))
        self.assertNotIn("main-d'œuvre", spoken_text(response(5)))
        self.assertIn("hors ligne", response(6).nuance)
        self.assertIn("même moment", response(6).arguments[1].exemple)
        self.assertIn("temps partiel", response(7).arguments[2].exemple)
        self.assertIn("prérequis", response(7).nuance)
        self.assertIn("distribution alimentaire", response(10).position_claire)
        self.assertIn(
            "sans cuisson",
            catalogue.tache_three_subject_hints()["eo/tache-3/education-p10"].arguments[2].example.french,
        )
        self.assertIn("dons financiers", response(10).nuance)
        self.assertIn("sans décider de l'embauche", response(12).arguments[1].consequence)
        self.assertIn("objectifs progressifs", response(13).nuance)
        language_example = response(13).arguments[0].exemple
        self.assertIn("Où habitez-vous ?", language_example)
        self.assertIn("Où travaillez-vous ?", language_example)
        self.assertIn("sans relire son modèle", language_example)
        language_cue = catalogue.tache_three_subject_hints()["eo/tache-3/education-p13"].arguments[0].example
        self.assertIn("sur le lieu de vie et de travail", language_cue.french)
        self.assertIn("without rereading the model", language_cue.english)
        self.assertIn("point de vue", response(14).arguments[1].developpement)
        self.assertIn("La fiction", response(14).nuance)
        self.assertIn("sources indépendantes", response(15).arguments[2].developpement)
        self.assertIn("plateformes", response(15).nuance)
        self.assertIn("temps partiel", response(16).arguments[1].exemple)
        self.assertIn("discriminations", response(16).nuance)
        self.assertIn("réexamen", response(17).arguments[2].exemple)
        self.assertIn("peut choquer", response(17).nuance)
        self.assertIn("priorité essentielle", response(18).position_claire)
        self.assertIn("à l'intérieur", response(18).arguments[1].developpement)
        self.assertIn("programme distrayant", response(19).nuance)
        self.assertNotIn("avant trois ans", spoken_text(response(19)))
        self.assertIn("ni une obligation", response(20).position_claire)
        self.assertIn("version accessible", response(20).arguments[1].exemple)
        self.assertIn("conditions", response(21).arguments[2].developpement)
        self.assertIn("résultats modestes ne condamnent pas", response(21).nuance)
        self.assertIn("plus un apprentissage entièrement seul", response(22).arguments[1].consequence)
        self.assertIn("encadrement approprié", response(22).arguments[2].exemple)
        self.assertIn("animaux", response(23).nuance)
        self.assertNotIn("pendant des années", spoken_text(response(23)))

    def test_scenario_specific_corrections_remain_explicit(self):
        models = catalogue.tache_three_models()
        response = lambda key: models[f"eo/tache-3/culture-p{key}"].response
        self.assertIn("pas toutes", response(1).position_claire)
        self.assertNotIn("conduire sur la neige", spoken_text(response(1)))
        self.assertIn("tous les adultes ne pensent pas ainsi", response(2).position_claire)
        self.assertIn("un soutien moral, des conseils pratiques", response(11).position_claire)
        self.assertIn("ne devraient pas constituer le seul cercle social", response(11).position_claire)
        self.assertIn("rencontrer d'autres habitants", response(11).position_claire)
        self.assertIn("ne comprend pas toutes les explications", response(15).arguments[2].developpement)
        self.assertIn("comprend encore mal le français", response(15).arguments[2].exemple)
        self.assertIn("réussit à refaire ce geste", response(15).arguments[2].exemple)
        self.assertIn("Ne pas avoir d'amis ne veut pas dire vivre sans aucun lien", response(16).arguments[1].developpement)
        self.assertIn("pas d'accord avec le mot", response(17).position_claire)
        self.assertIn("sauvegardé", response(18).nuance)
        self.assertIn("traductions", response(19).arguments[1].idea)
        self.assertIn("sans généraliser ces deux expériences", response(19).arguments[1].exemple)
        self.assertIn("en écoutant", response(20).position_claire)
        self.assertIn("en pratiquant une activité", response(20).position_claire)
        self.assertIn("réservations", response(21).nuance)
        self.assertIn("relations de confiance", response(24).nuance)
        self.assertIn("conjoint", response(25).arguments[2].developpement)
        self.assertIn("si j'immigrais", response(26).position_claire.casefold())
        self.assertIn("pas seulement de la volonté", response(27).nuance)
        self.assertIn("Selon le pays et le statut", response(29).arguments[2].developpement)
        self.assertIn("l'ouverture des autres", response(30).arguments[1].idea)
        self.assertIn("publicité", response(31).arguments[2].idea)
        self.assertIn("recommandées par un candidat", response(31).arguments[2].exemple)
        self.assertIn("financer", response(33).arguments[2].exemple)
        self.assertIn("seconde main", response(34).position_claire)
        self.assertIn("vie associative", response(35).arguments[2].idea)

    def test_culture_distinguishes_friendship_benefits_from_happiness_necessity(self):
        models = catalogue.tache_three_models()
        model = models["eo/tache-3/culture-p16"]
        response = model.response
        self.assertEqual(model.argument_ids, (1, 4, 5))
        self.assertIn("on peut être heureux sans avoir d'amis", response.position_claire)
        self.assertIn("soutien", response.arguments[0].idea)
        self.assertIn("liens familiaux ou de couple", response.arguments[1].idea)
        self.assertIn("sans qu'on ait d'amis", response.arguments[2].developpement)
        self.assertIn("qui n'a pas d'amis", response.arguments[2].exemple)
        self.assertIn("isolement qui fait souffrir", response.nuance)
        self.assertIn("conjoint", response.arguments[1].exemple)
        self.assertIn("qui n'a pas d'amis", response.arguments[1].exemple)
        self.assertNotIn("sur place", response.arguments[1].exemple)
        cue = catalogue.tache_three_subject_hints()[model.group].arguments[1].example
        self.assertIn("Sans avoir d'amis", cue.french)
        self.assertIn("without having friends", cue.english)
        self.assertIn("récolte", response.arguments[2].exemple)
        self.assertEqual(
            {key for key, _ in model.source_prompts}, {"culture:p16", "famille:p8"},
        )

    def test_culture_local_relationships_address_necessity_not_friend_count(self):
        model = catalogue.tache_three_models()["eo/tache-3/culture-p24"]
        response = model.response
        plan = catalogue.tache_three_subject_hints()[model.group]
        self.assertEqual(model.argument_ids, (1, 2, 4))
        self.assertEqual(
            {key for key, _ in model.source_prompts}, {"culture:p24", "culture:p28"},
        )
        self.assertIn("pas une condition indispensable pour tout le monde", response.position_claire)
        self.assertNotIn("durablement", response.position_claire)
        self.assertIn("réduire l'isolement", response.arguments[0].idea)
        self.assertIn("chaque samedi", response.arguments[0].exemple)
        self.assertIn("quelques courses", response.arguments[0].exemple)
        self.assertIn("codes sociaux", response.arguments[1].idea)
        self.assertIn("pratiquer la langue du pays", response.arguments[1].idea)
        self.assertIn("Les conversations régulières", response.arguments[1].developpement)
        self.assertIn("les habitudes d'un groupe", response.arguments[1].developpement)
        self.assertIn("avec des interlocuteurs que l'on connaît", response.arguments[1].developpement)
        self.assertIn("chacun apporte un plat", response.arguments[1].exemple)
        self.assertIn("dans la langue du pays", response.arguments[1].exemple)
        self.assertIn("réutilise ensuite ces expressions lors d'autres rencontres", response.arguments[1].exemple)
        self.assertIn("tous les habitants aient les mêmes habitudes", response.arguments[1].consequence)
        self.assertIn("chacun apporte un plat", plan.arguments[1].example.french)
        self.assertIn("everyone brings a dish", plan.arguments[1].example.english)
        self.assertIn("sans avoir encore créé de liens personnels sur place", response.arguments[2].idea)
        self.assertIn("travaille à distance", response.arguments[2].exemple)
        self.assertIn("avant d'avoir rencontré des personnes avec qui se lier", response.arguments[2].exemple)
        self.assertIn("isolement qui fait souffrir", response.nuance)
        self.assertIn(
            "Quelques relations de confiance peuvent apporter plus de soutien",
            response.nuance,
        )
        self.assertIn("contacts superficiels", response.nuance)
        self.assertNotIn("Les habitants sont de toutes origines", response.nuance)
        self.assertIn("sans être indispensables au bien-être de tous", response.conclusion)
        self.assertIn("La confiance peut compter davantage", plan.nuance.french)
        self.assertIn("Trust can matter more", plan.nuance.english)
        self.assertIn("sans être indispensables", plan.introduction.french)
        self.assertIn("without being essential", plan.introduction.english)
        self.assertIn("avant d'avoir noué des liens locaux", plan.arguments[2].example.french)
        self.assertIn("before forming local relationships", plan.arguments[2].example.english)

    def test_culture_migration_motivations_can_combine_and_change(self):
        group = "eo/tache-3/culture-p25"
        response = catalogue.tache_three_models()[group].response
        cue = catalogue.tache_three_subject_hints()[group].nuance
        self.assertIn("à la fois pour étudier et pour rejoindre son conjoint", response.nuance)
        self.assertIn("puis donner davantage de place à sa carrière", response.nuance)
        self.assertNotIn("fuite", response.nuance)
        self.assertNotIn("insécurité", response.nuance)
        self.assertIn("se combiner ou évoluer", cue.french)
        self.assertIn("combine or change", cue.english)

    def test_culture_local_cultural_experience_is_not_a_second_question_session(self):
        response = catalogue.tache_three_models()["eo/tache-3/culture-p14"].response
        self.assertIn("en participant à des activités près de chez soi", response.arguments[1].idea)
        self.assertIn("En y participant", response.arguments[1].developpement)
        self.assertIn("en les faisant soi-même", response.arguments[1].developpement)
        self.assertNotIn("autrement", response.arguments[1].developpement)
        self.assertIn("atelier de danse irlandaise dans mon quartier", response.arguments[1].exemple)
        self.assertIn("avec le groupe", response.arguments[1].exemple)
        self.assertIn("Au bal organisé après l'atelier", response.arguments[1].exemple)
        self.assertIn("au lieu de rester spectateur", response.arguments[1].exemple)
        self.assertIn("en la partageant avec d'autres personnes", response.arguments[1].consequence)
        self.assertIn("approfondir sa connaissance d'une culture", response.arguments[2].idea)
        self.assertIn("poser une question précise", response.arguments[2].developpement)
        self.assertIn("vérifier ce qu'on a compris", response.arguments[2].developpement)

    def test_culture_country_knowledge_has_distinct_material_legal_and_relational_reasons(self):
        model = catalogue.tache_three_models()["eo/tache-3/culture-p26"]
        response = model.response
        self.assertEqual(model.argument_ids, (2, 4, 3))
        self.assertIn("financièrement réaliste", response.arguments[0].idea)
        self.assertIn("2 500 dollars nets par mois", response.arguments[0].exemple)
        self.assertIn("sans compter sur un revenu incertain", response.arguments[0].developpement)
        self.assertIn("connaître mes droits", response.arguments[1].idea)
        self.assertIn("règles locales", response.arguments[1].exemple)
        self.assertIn("ce qui est autorisé", response.arguments[1].exemple)
        self.assertIn("habitudes locales", response.arguments[2].idea)
        self.assertIn("si j'immigrais", response.position_claire.casefold())
        self.assertIn("défendre mes droits", response.conclusion)

    def test_culture_preparation_positions_do_not_reverse_negative_source_claims(self):
        models = catalogue.tache_three_models()
        self.assertTrue(
            models["eo/tache-3/culture-p7"].response.position.startswith(
                "Les métiers artistiques sont sérieux",
            ),
        )
        self.assertIn(
            "ont leur place à l'école",
            models["eo/tache-3/culture-p13"].response.position,
        )

    def test_culture_revised_examples_keep_bilingual_cues_specific(self):
        models = catalogue.tache_three_models()
        plans = catalogue.tache_three_subject_hints()
        for group, index, source, french, english in (
            ("culture-p7", 1, "proportions", "proportions", "proportions"),
            ("culture-p9", 1, "dîner sans compagnie", "dîner seul", "eat alone"),
            ("culture-p11", 0, "passer le dimanche ensemble", "dimanche ensemble", "Sunday together"),
            ("culture-p11", 2, "danse traditionnelle", "danse traditionnelle", "traditional dance"),
            ("culture-p12", 0, "objets mal triés", "objets mal triés", "incorrectly sorted items"),
            ("culture-p13", 1, "tableau", "tableau", "painting"),
            ("culture-p13", 1, "sourient", "sourires", "smiles"),
            ("culture-p14", 0, "raviolis", "raviolis", "dumplings"),
            ("culture-p14", 1, "danse irlandaise", "danse irlandaise", "Irish dance"),
            ("culture-p14", 2, "chaussures", "chaussures", "shoes"),
            ("culture-p15", 1, "tomates", "tomates", "tomatoes"),
            ("culture-p16", 1, "conjoint", "conjoint", "partner"),
            ("culture-p16", 2, "récolte", "récolte", "harvest"),
            ("culture-p18", 1, "phrase trop brusque", "phrase trop brusque", "blunt sentence"),
            ("culture-p19", 2, "ancienne usine", "usine", "factory"),
            ("culture-p20", 2, "motif", "motif", "motif"),
            ("culture-p24", 0, "chaque samedi", "samedi", "Saturday"),
            ("culture-p24", 1, "chacun apporte un plat", "chacun apporte un plat", "everyone brings a dish"),
            ("culture-p24", 1, "réutilise ensuite ces expressions", "réutiliser les expressions", "reuse expressions"),
            ("culture-p24", 2, "randonnée seule", "randonnées en solitaire", "solo hikes"),
            ("culture-p26", 0, "New York", "New York", "New York"),
            ("culture-p26", 0, "2 500 dollars nets par mois", "2 500 dollars nets par mois", "$2,500 monthly take-home pay"),
            ("culture-p26", 0, "un loyer à 2 000 dollars", "2 000 de loyer", "$2,000 rent"),
            ("culture-p26", 0, "500 dollars pour les autres dépenses", "500 pour le reste", "$500 for other costs"),
            ("culture-p26", 1, "propriétaire", "propriétaire", "landlord"),
            ("culture-p27", 0, "proverbe", "proverbe", "proverb"),
            ("culture-p27", 1, "danse traditionnelle", "pas de danse", "dance steps"),
            ("culture-p27", 1, "Sa sœur", "sa sœur", "Her sister"),
            ("culture-p30", 1, "plusieurs semaines", "plusieurs semaines", "several weeks"),
            ("culture-p31", 2, "partenariat rémunéré", "partenariat rémunéré", "paid partnership"),
        ):
            identity = f"eo/tache-3/{group}"
            with self.subTest(group=group, argument=index + 1):
                self.assertIn(source, models[identity].response.arguments[index].exemple)
                cue = plans[identity].arguments[index].example
                self.assertIn(french, cue.french)
                self.assertIn(english, cue.english)

    def test_published_storage_and_vocabulary_provenance_are_unchanged(self):
        root = content.CONTENT_DIR.parent.parent
        for relative, expected in {
            "study/content/responses": "4af8a23c7b8e1f82a9a6da123242dbccda9ef1f19e58c252d00f1433cbfc6823",
            "study/content/subject_vocabulary": "2415a32bccf94004f9293d46faaef4b36677c6aefd79b765f54225afa44fea99",
            "study/content/phrases.tsv": "2643dfa0d3cf26cf68e50062a05c4bd803e03425a879e8a00fb195e1e200c09e",
        }.items():
            path = root / relative
            paths = sorted(path.rglob("*")) if path.is_dir() else [path]
            digest = hashlib.sha256()
            for source in paths:
                if source.is_file():
                    label = source.relative_to(root).as_posix()
                    digest.update(label.encode() + b"\0" + source.read_bytes() + b"\0")
            self.assertEqual(digest.hexdigest(), expected, relative)
        self.assertEqual(len(content.parse_response_storage()), 130)
        self.assertEqual(len(self.sources), 131)
        self.assertEqual(sum(len(source.prompts) for source in self.sources), 167)
        self.assertEqual(len(content.parse_phrases(self.sources)), 1410)
        self.assertTrue(content.parse_subject_vocabulary(self.sources))

    def test_unreviewed_models_keep_their_original_effective_content(self):
        with patch("study.catalogue.tache_three_models", return_value={}):
            for source in self.sources:
                for prompt in source.prompts:
                    self.assertEqual(
                        effective_response(source, None, prompt=prompt, model_only=True),
                        original_effective(prompt),
                    )

    def test_catalogue_and_nested_records_are_immutable_and_failures_are_not_cached(self):
        models = catalogue.tache_three_models()
        self.assertIs(catalogue.tache_three_models(), models)
        model = next(iter(models.values()))
        with self.assertRaises(TypeError):
            models["other"] = model
        with self.assertRaises(FrozenInstanceError):
            model.response.nuance = "Changed"
        with self.assertRaises(FrozenInstanceError):
            model.response.arguments[0].exemple = "Changed"
        catalogue.clear_catalogue_cache()
        with patch("study.tache_three_models.load_tache_three_models", side_effect=ValueError("Invalid model")) as loader:
            for _ in range(2):
                with self.assertRaisesMessage(ValueError, "Invalid model"):
                    catalogue.tache_three_models()
            self.assertEqual(loader.call_count, 2)

    def test_rejects_incomplete_themes_changed_consigne_or_equivalence(self):
        invalid = deepcopy(self.payload)
        invalid["responses"].pop("culture-p1")
        with self.assertRaisesMessage(ValueError, "coverage"):
            self.load(invalid)
        invalid = deepcopy(self.payload)
        invalid["responses"]["culture-p3"]["prompt_signatures"].pop("economie:p5")
        with self.assertRaisesMessage(ValueError, "re-audit"):
            self.load(invalid)
        invalid = deepcopy(self.payload)
        invalid["responses"]["culture-p1"]["prompt_signatures"]["culture:p1"] = "changed"
        with self.assertRaisesMessage(ValueError, "re-audit"):
            self.load(invalid)

    def test_rejects_invalid_models_missing_supports_and_superficial_repetition(self):
        for field, value in (("version", True), ("task", "ee/tache-3"), ("theme", "famille")):
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.load({**self.payload, field: value})
        for field in ("position_claire", "nuance", "conclusion"):
            invalid = deepcopy(self.payload)
            invalid["responses"]["culture-p1"][field] = " "
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.load(invalid)
        for part in ("idea", "developpement", "exemple", "consequence"):
            invalid = deepcopy(self.payload)
            invalid["responses"]["culture-p1"]["arguments"][0][part] = ""
            with self.subTest(part=part), self.assertRaises(ValueError):
                self.load(invalid)
        for change in ("missing", "extra", "duplicate", "restatement"):
            invalid = deepcopy(self.payload)
            arguments = invalid["responses"]["culture-p1"]["arguments"]
            if change == "missing":
                arguments.pop()
            elif change == "extra":
                arguments.append(deepcopy(arguments[0]))
            elif change == "duplicate":
                arguments[1]["exemple"] = arguments[0]["exemple"]
            else:
                arguments[0]["exemple"] = arguments[0]["idea"]
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.load(invalid)
        invalid = deepcopy(self.payload)
        invalid["responses"]["culture-p1"]["nuance"] = " ".join(["mot"] * 500)
        with self.assertRaisesMessage(ValueError, "rehearsal"):
            self.load(invalid)

    def test_rejects_duplicate_json_fields_unknown_groups_and_empty_catalogue(self):
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesMessage(ValueError, "empty"):
                load_tache_three_models(root, responses=self.sources)
            (root / "culture.json").write_text(
                json.dumps(self.payload).replace('"version": 1', '"version": 1, "version": 1'),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError):
                load_tache_three_models(root, responses=self.sources)
        invalid = deepcopy(self.payload)
        invalid["responses"]["culture-p999"] = invalid["responses"]["culture-p1"]
        with self.assertRaisesMessage(ValueError, "coverage"):
            self.load(invalid)

    def test_task_boundaries_and_stale_database_prompts_are_not_silent_fallbacks(self):
        with patch.object(catalogue, "tache_three_models", side_effect=AssertionError("Wrong task")):
            for group in ("", "eo/tache-2/example", "ee/tache-3/example"):
                self.assertIsNone(reviewed_model(SimpleNamespace(semantic_group=group)))
        with self.assertRaisesMessage(RuntimeError, "not synchronized"):
            reviewed_model(
                SimpleNamespace(semantic_group="eo/tache-3/culture-p1"),
                SimpleNamespace(content_key="culture:p1", text="Changed consigne"),
            )


class TacheThreeModelViewTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("import_content", stdout=StringIO())
        cls.user = factories.make_user("eo3-model-owner")
        cls.other = factories.make_user("eo3-model-other")
        provision_user_study_data(cls.user)
        provision_user_study_data(cls.other)

    def setUp(self):
        catalogue.clear_catalogue_cache()
        self.addCleanup(catalogue.clear_catalogue_cache)
        self.client.force_login(self.user)

    def prompt(self, key="culture:p1"):
        return Prompt.objects.select_related(
            "response__theme__task__part", "theme__task__part", "family",
        ).get(content_key=key)

    def assert_model_order(self, html, response):
        rendered = AnnotationRootText(html).text.decode("utf-16-le")
        parts = (
            response.position_claire,
            *(text for argument in response.arguments for text in (
                argument.idea, argument.developpement, argument.exemple, argument.consequence,
            )),
            response.nuance, response.conclusion,
        )
        positions = [rendered.index(text) for text in parts]
        self.assertEqual(positions, sorted(positions))
        self.assertEqual(len(set(positions)), len(positions))

    def test_all_reviewed_publications_show_full_ordered_interventions_on_detail_and_review(self):
        for model in catalogue.tache_three_models().values():
            for key, source_text in model.source_prompts:
                with self.subTest(prompt=key):
                    prompt = self.prompt(key)
                    page = self.client.get(prompt_detail_url(prompt))
                    self.assertEqual(page.status_code, 200)
                    self.assertEqual(page.context["selected_prompt"].text, source_text)
                    self.assert_model_order(page.content.decode(), model.response)
                    self.assertContains(page, "data-response-edit", count=1)
                    self.assertContains(page, "Exemple concret", count=3)
                    note = catalogue.tache_three_prompt_notes()[model.group]
                    self.assertContains(page, escape(note.note))
                    plan = catalogue.tache_three_subject_hints()[model.group]
                    self.assertIs(page.context["subject_hints"], plan)
                    for cue in (
                        plan.introduction,
                        *(cue for argument in plan.arguments for cue in (argument.point, argument.example)),
                        plan.nuance, plan.conclusion,
                    ):
                        self.assertContains(page, escape(cue.french))
                        self.assertContains(page, escape(cue.english))
                    self.assertEqual(json.loads(page.context["oral_legacy_annotation_keys"]), [])
                    card = Card.objects.get(user=self.user, response=prompt.response, card_type=CardType.SPINE)
                    payload = card_payload(card, prompt=prompt)
                    self.assertIs(payload["eo3_prompt_note"], note)
                    front = render_to_string("study/partials/card_front.html", payload)
                    self.assertIn("Comprendre la consigne", front)
                    self.assertIn(escape(note.note), front)
                    self.assertNotIn("subject-hints--speaking", front)
                    self.assertIs(payload["eo3_pistes"], plan)
                    rendered = render_to_string("study/partials/card_back.html", payload)
                    self.assertIn("subject-hints--speaking", rendered)
                    for cue in (plan.introduction, plan.nuance, plan.conclusion):
                        self.assertIn(escape(cue.french), rendered)
                    self.assertIn("Ouvrir la fiche", rendered)
                    self.assertNotIn("data-response-field", rendered)
                    self.assertNotIn("Exemple concret", rendered)
                    # Read-aloud still voices the full answer; nothing else shows it.
                    visible = re.sub(r'data-(?:read-aloud-value|speech-text)="[^"]*"', "", rendered)
                    self.assertIn(escape(model.response.conclusion), rendered)
                    self.assertNotIn(escape(model.response.conclusion), visible)
                    self.assertEqual(
                        AnnotationRootText(
                            "<div data-annotation-root>" + rendered + "</div>"
                        ).text.decode("utf-16-le").strip(),
                        "Ouvrir la fiche",
                    )
                    self.assertEqual(payload["response_content"], model.response)
                    self.assertNotEqual(payload["annotation_source_key"], variant_annotation_key(prompt, original_effective(prompt)))

    def test_editor_seeds_current_supported_default_without_writing_a_private_row(self):
        prompt = self.prompt()
        url = reverse("study:edit_response", args=["eo", "tache-3", prompt.pk])
        page = self.client.get(url)
        model = catalogue.tache_three_models()[prompt.response.semantic_group].response
        form = page.context["form"]
        self.assertEqual(form.fields["position_claire"].initial, model.position_claire)
        for argument in model.arguments:
            self.assertEqual(
                form.fields[f"argument_{argument.order}_exemple"].initial,
                argument.exemple,
            )
        self.assertFalse(PersonalResponse.objects.filter(user=self.user).exists())

    def test_original_and_private_annotation_layouts_remain_exactly_reproducible(self):
        archive = json.loads(
            (content.CONTENT_DIR / "tache_3/layout_history/original.json").read_text()
        )
        for key in ("culture:p1", "culture:p3", "economie:p5", "famille:p1"):
            prompt = self.prompt(key)
            page = self.client.get(prompt_detail_url(prompt))
            original = original_effective(prompt)
            card = Card.objects.get(
                user=self.user, response=prompt.response, card_type=CardType.SPINE,
            )
            for is_personal in (False, True):
                value = EffectiveResponse(**{**asdict(original), "arguments": original.arguments, "is_personal": is_personal})
                contexts = {
                    "study/response_detail.html": page.context[0].flatten(),
                    **{
                        f"study/partials/card_{surface}.html": card_payload(card, prompt=prompt)
                        for surface in ("front", "back")
                    },
                }
                for name, context in contexts.items():
                    context = {
                        **context, "response_content": value,
                        "arguments": value.arguments, "reviewed_eo3": False,
                        "structured_eo3": False,
                        "single_response_eo3": False,
                        # Cards without Pistes keep the archived full-answer back.
                        "eo3_pistes": None,
                    }
                    source = archive["templates"][name]
                    if name == "study/response_detail.html":
                        # The archived sidebar buttons are gone; excluding them keeps offsets comparable.
                        actions = '<div class="response-sidebar-actions">'
                        self.assertEqual(source.count(actions), 1)
                        source = source.replace(
                            actions,
                            '<div class="response-sidebar-actions" data-annotation-exclude>',
                        )
                        # The flashcard stats were trimmed to the start date.
                        source, removed = re.subn(
                            r'      \{% if card %\}\n        <div class="spine-label">Pratique de la réponse</div>.*?      \{% endif %\}\n',
                            lambda _: (
                                '      {% if subject_progress.started_at %}\n'
                                '        <dl class="kv"><div><dt>Commencée</dt><dd>{{ subject_progress.started_at|date:"j M Y" }}</dd></div></dl>\n'
                                '      {% endif %}\n'
                            ),
                            source, count=1, flags=re.S,
                        )
                        self.assertEqual(removed, 1)
                    previous = Engine.get_default().from_string(source).render(Context(context))
                    current = render_to_string(name, context)
                    if "partials" in name:
                        previous = "<div data-annotation-root>" + previous + "</div>"
                        current = "<div data-annotation-root>" + current + "</div>"
                    with self.subTest(prompt=key, personal=is_personal, template=name):
                        self.assertEqual(
                            AnnotationRootText(current).text,
                            AnnotationRootText(previous).text,
                        )

    def test_private_content_notes_highlights_and_progress_survive_repeat_import_and_reset(self):
        prompt = self.prompt()
        personal = PersonalResponse.objects.create(
            user=self.user, response=prompt.response, source_prompt=prompt,
            position="Ma position privée.", position_claire="Mon introduction privée.",
            arguments=[asdict(EffectiveArgument(
                order=1, idea="Mon idée.", developpement="Ma raison.",
                exemple="Mon exemple privé.", consequence="Ma conséquence.",
            ))],
            nuance="Ma nuance.", conclusion="Ma conclusion.",
        )
        current = effective_response(prompt.response, self.user, prompt=prompt)
        old_model = original_effective(prompt)
        annotations = []
        for kind, key, quote, body in (
            (AnnotationKind.HIGHLIGHT, variant_annotation_key(prompt, old_model), old_model.position_claire, ""),
            (AnnotationKind.HIGHLIGHT, variant_annotation_key(prompt, current), current.position_claire, ""),
            (AnnotationKind.NOTE, "response:culture:p1", "", "Ma note conservée."),
        ):
            annotations.append(Annotation.objects.create(
                user=self.user, task=prompt.theme.task, source_prompt=prompt,
                kind=kind, source_path=prompt_detail_url(prompt), source_key=key,
                quote=quote, body=body, start_offset=0, end_offset=len(quote),
            ))
        Card.objects.filter(user=self.user, response=prompt.response).update(
            reps=8, subject_completed_at=timezone.now(),
        )
        private_before = PersonalResponse.objects.filter(pk=personal.pk).values().get()
        notes_before = list(Annotation.objects.filter(pk__in=[row.pk for row in annotations]).order_by("pk").values())
        cards_before = list(Card.objects.filter(user=self.user, response=prompt.response).values())
        prompt_before = Prompt.objects.filter(pk=prompt.pk).values().get()
        for _ in range(2):
            call_command("import_content", stdout=StringIO())
        self.assertEqual(PersonalResponse.objects.filter(pk=personal.pk).values().get(), private_before)
        self.assertEqual(list(Annotation.objects.filter(pk__in=[row.pk for row in annotations]).order_by("pk").values()), notes_before)
        self.assertEqual(list(Card.objects.filter(user=self.user, response=prompt.response).values()), cards_before)
        self.assertEqual(Prompt.objects.filter(pk=prompt.pk).values().get(), prompt_before)
        page = self.client.get(prompt_detail_url(prompt))
        self.assertContains(page, "Mon exemple privé.")
        self.assertFalse(page.context["reviewed_eo3"])
        self.client.force_login(self.other)
        other = self.client.get(prompt_detail_url(prompt))
        self.assertNotContains(other, "Mon exemple privé.")
        self.assertTrue(other.context["reviewed_eo3"])
        self.client.force_login(self.user)
        self.client.post(reverse("study:edit_response", args=["eo", "tache-3", prompt.pk]), {"action": "reset"})
        personal.refresh_from_db()
        self.assertFalse(personal.is_active)
        self.assertEqual(personal.arguments, private_before["arguments"])
        restored = self.client.get(prompt_detail_url(prompt))
        self.assertTrue(restored.context["reviewed_eo3"])
        self.assertEqual(json.loads(restored.context["oral_legacy_annotation_keys"]), [])
        self.assertEqual(list(Annotation.objects.filter(pk__in=[row.pk for row in annotations]).order_by("pk").values()), notes_before)
