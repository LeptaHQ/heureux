"""Fixed structure for every EE Tâche 3 model answer."""

import re

from django.test import SimpleTestCase

from study import content_loader as content


class EeTacheThreeSkeletonTests(SimpleTestCase):
    relation_markers = (
        "De son côté, le second",
        "En revanche, le second",
    )
    stance_marker = "Pour ma part,"
    first_argument_marker = "Tout d’abord,"
    concrete_support_marker = "Par exemple,"
    second_argument_marker = "De plus,"
    conclusion_marker = "En conclusion,"
    support_pattern = re.compile(
        r"[.!?:]\s+\S"
        r"|[,;]\s*(?:car|parce que|puisque|ce qui|afin de|de sorte que|si|à condition que|alors qu)\b"
        r"|\blorsque\b",
        re.IGNORECASE,
    )

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.months = content.load_ee_tache_three_months()
        cls.sources = tuple(
            combinaison
            for month in cls.months
            for combinaison in month.combinaisons
        )
        cls.responses = tuple(content.parse_ee_tache_three_responses(cls.months))
        cls.source_by_key = {row.content_key: row for row in cls.sources}
        cls.response_by_key = {row.content_key: row for row in cls.responses}

    def assert_opinion_skeleton(self, text):
        self.assertTrue(text.startswith(self.stance_marker), text)
        offsets = (
            text.find(self.stance_marker),
            text.find(self.first_argument_marker),
            text.find(self.second_argument_marker),
            text.find(self.conclusion_marker),
        )
        self.assertTrue(all(offset >= 0 for offset in offsets), text)
        self.assertEqual(offsets, tuple(sorted(offsets)), text)
        self.assertIn(self.concrete_support_marker, text)
        first_argument = text[offsets[1]:offsets[2]]
        second_argument = text[offsets[2]:offsets[3]]
        self.assertGreaterEqual(content._ee_word_count(first_argument), 8, text)
        self.assertGreaterEqual(content._ee_word_count(second_argument), 8, text)
        self.assertRegex(first_argument, self.support_pattern, text)
        self.assertRegex(second_argument, self.support_pattern, text)
        for marker in (
            self.stance_marker,
            self.first_argument_marker,
            self.second_argument_marker,
            self.conclusion_marker,
        ):
            self.assertEqual(text.count(marker), 1, text)
        self.assertNotRegex(text, r"\b(?:Argument [12]|Stance)\b")

    def assert_synthesis_frame(self, text):
        self.assertTrue(text.startswith("Les deux documents abordent"), text)
        self.assertIn("Le premier", text)
        self.assertEqual(
            sum(marker in text for marker in self.relation_markers),
            1,
            text,
        )

    def test_all_138_source_models_use_the_opinion_skeleton(self):
        self.assertEqual(len(self.sources), 138)
        for source in self.sources:
            with self.subTest(key=source.content_key):
                self.assert_opinion_skeleton(source.point_de_vue)
                self.assertTrue(
                    80 <= content._ee_word_count(source.point_de_vue) <= 120
                )
                answer = content.ee_tache_three_answer_text(
                    source.heading, source.synthese, source.point_de_vue,
                )
                self.assertTrue(120 <= content._ee_word_count(answer) <= 180)

    def test_all_78_effective_models_use_the_opinion_skeleton(self):
        self.assertEqual(len(self.responses), 78)
        self.assertEqual(sum(len(row.prompts) for row in self.responses), 138)
        for response in self.responses:
            with self.subTest(key=response.content_key):
                self.assert_opinion_skeleton(response.position_claire)
                self.assertTrue(
                    80 <= content._ee_word_count(response.position_claire) <= 120
                )
                answer = content.ee_tache_three_answer_text(
                    response.reformulation,
                    response.position,
                    response.position_claire,
                )
                self.assertTrue(120 <= content._ee_word_count(answer) <= 180)

    def test_loader_counts_remain_stable(self):
        self.assertEqual(len(self.sources), 138)
        self.assertEqual(len(self.responses), 78)
        self.assertEqual(sum(len(row.prompts) for row in self.responses), 138)
        self.assertEqual(
            len(content.parse_ee_tache_three_subject_vocabulary(self.responses)),
            2340,
        )

    def test_audited_semantic_corrections_remain_in_place(self):
        source = self.source_by_key
        effective = self.response_by_key

        self.assertIn(
            "même si certains élèves y voient une atteinte à leur vie privée",
            source["ee-tache3:avril:combinaison-8"].synthese,
        )
        self.assertIn(
            "le second reconnaît les économies",
            source["ee-tache3:decembre:combinaison-13"].synthese,
        )
        self.assertIn(
            "le second, revenu chez ses parents après la perte d’un emploi",
            source["ee-tache3:decembre:combinaison-15"].synthese,
        )
        self.assertIn(
            "dont l’une est devenue auteure",
            effective["ee-tache3:janvier:combinaison-2"].position,
        )
        self.assertNotIn(
            "Il faut surtout qu’il maîtrise aussi les règles d’hygiène",
            effective["ee-tache3:janvier:combinaison-2"].position_claire,
        )
        self.assertIn(
            "aux livreurs, aux policiers et aux services d’urgence",
            effective["ee-tache3:janvier:combinaison-17"].position_claire,
        )
        self.assertIn(
            "un aller-retour à bas prix vers l’Espagne",
            effective["ee-tache3:janvier:combinaison-19"].position_claire,
        )
        self.assertIn(
            "un accès rapide à une boisson aide les élèves à rester concentrés",
            effective["ee-tache3:janvier:combinaison-1"].position_claire,
        )
        self.assertNotIn(
            "De plus, certaines populations trop nombreuses peuvent toutefois",
            source["ee-tache3:avril:combinaison-4"].point_de_vue,
        )
        self.assertIn(
            "répartit les tâches sur quatre jours",
            source["ee-tache3:mai:combinaison-3"].point_de_vue,
        )
        self.assertIn(
            "un jeu de gestion pousse un adolescent à élaborer une stratégie",
            source["ee-tache3:mai:combinaison-3-bis"].point_de_vue,
        )
        self.assertNotIn(
            "privilégient le spectacle",
            source["ee-tache3:mai:combinaison-2"].point_de_vue,
        )
        self.assertIn(
            "limiter la quantité de publicités",
            source["ee-tache3:octobre:combinaison-1"].point_de_vue,
        )
        self.assertIn(
            "dégradations non autorisées",
            source["ee-tache3:novembre:combinaison-10"].point_de_vue,
        )
        self.assertIn(
            "Le seul document exploitable constate",
            source["ee-tache3:decembre:combinaison-10"].synthese,
        )

    def test_complete_source_pairs_use_the_flexible_synthesis_frame(self):
        for source in self.sources:
            if (
                source.document2_missing
                or source.documents_identical
                or source.document1_invalid
            ):
                continue
            with self.subTest(key=source.content_key):
                self.assert_synthesis_frame(source.synthese)

    def test_complete_effective_pairs_use_the_flexible_synthesis_frame(self):
        defective_keys = {
            source.content_key
            for source in self.sources
            if (
                source.document2_missing
                or source.documents_identical
                or source.document1_invalid
            )
        }
        for response in self.responses:
            if response.content_key in defective_keys:
                continue
            with self.subTest(key=response.content_key):
                self.assert_synthesis_frame(response.position)

    def test_defective_sources_are_described_instead_of_completed(self):
        defective = {
            source.content_key: source
            for source in self.sources
            if (
                source.document2_missing
                or source.documents_identical
                or source.document1_invalid
            )
        }
        self.assertEqual(
            set(defective),
            {
                "ee-tache3:mai:combinaison-3-bis",
                "ee-tache3:juin:combinaison-2",
                "ee-tache3:juin:combinaison-3",
                "ee-tache3:decembre:combinaison-10",
            },
        )
        self.assertIn(
            "documents publiés sont identiques",
            defective["ee-tache3:mai:combinaison-3-bis"].synthese,
        )
        for key in (
            "ee-tache3:juin:combinaison-2",
            "ee-tache3:juin:combinaison-3",
            "ee-tache3:decembre:combinaison-10",
        ):
            with self.subTest(key=key):
                self.assertIn("Un seul document", defective[key].synthese)
