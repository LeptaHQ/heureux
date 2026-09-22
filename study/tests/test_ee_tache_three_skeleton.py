"""Fixed-but-flexible structure for every EE Tâche 3 model answer."""

from django.test import SimpleTestCase

from study import content_loader as content


class EeTacheThreeSkeletonTests(SimpleTestCase):
    relation_markers = (
        "De son côté, le second",
        "En revanche, le second",
    )
    opinion_markers = (
        "Pour ma part,",
        "Tout d’abord,",
        "De plus,",
        "En conclusion,",
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

    def assert_opinion_skeleton(self, text):
        self.assertTrue(text.startswith(self.opinion_markers[0]), text)
        offsets = [text.find(marker) for marker in self.opinion_markers]
        self.assertTrue(all(offset >= 0 for offset in offsets), text)
        self.assertEqual(offsets, sorted(offsets), text)
        self.assertIn("Par exemple,", text)

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

    def test_all_78_effective_models_use_the_opinion_skeleton(self):
        self.assertEqual(len(self.responses), 78)
        self.assertEqual(sum(len(row.prompts) for row in self.responses), 138)
        for response in self.responses:
            with self.subTest(key=response.content_key):
                self.assert_opinion_skeleton(response.position_claire)

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
