from html.parser import HTMLParser

from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.utils.html import strip_tags


class _GuideMarkup(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.elements = []
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        self.elements.append((tag, dict(attrs)))

    def attributes_for(self, tag):
        return [attrs for name, attrs in self.elements if name == tag]


class EeTacheThreeMemoryGuideTests(SimpleTestCase):
    template = "study/partials/ee_tache_three_memory_guide.html"

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.markup = render_to_string(cls.template)
        cls.parsed = _GuideMarkup(cls.markup)
        cls.text = " ".join(strip_tags(cls.markup).split())

    def test_guide_is_a_native_collapsed_disclosure(self):
        details = self.parsed.attributes_for("details")
        self.assertEqual(len(details), 1)
        self.assertNotIn("open", details[0])
        self.assertEqual(details[0]["lang"], "fr")
        self.assertInHTML(
            "<summary>Comment apprendre ces formulations</summary>",
            self.markup,
        )

    def test_ten_essentials_have_english_meanings_and_usage(self):
        self.assertEqual(len(self.parsed.attributes_for("dt")), 10)
        definitions = self.parsed.attributes_for("dd")
        self.assertEqual(len(definitions), 10)
        self.assertTrue(all(attrs.get("lang") == "en" for attrs in definitions))
        for phrase in (
            "Les deux documents abordent",
            "De son côté, le second souligne",
            "En revanche",
            "Pour ma part",
            "Tout d’abord",
            "De plus",
            "Cela permet de",
            "Par exemple",
            "Même si",
            "En conclusion",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)
        self.assertIn("Do not fit all ten into every answer.", self.text)
        self.assertIn("state your position in Part 2, not the synthesis", self.text)

    def test_path_keeps_exam_constraints_and_transfer_clear(self):
        for phrase in (
            "40–60 mots",
            "80–120 mots",
            "120–180 mots au total",
            "60 minutes pour les trois tâches",
            "Reformulez sans avis personnel",
            "adaptez-la à deux sujets différents",
            "Le titre dépend du support",
            "il n’est pas obligatoire dans tous les cas",
            "Ces conseils ne garantissent pas une note",
            "B2 / NCLC 7–8",
            "5 minutes",
            "12 minutes",
            "3 minutes",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)

    def test_comparison_examples_do_not_invent_source_claims(self):
        for phrase in (
            "Si les deux textes soutiennent la gratuité",
            "Les deux documents défendent la gratuité des musées",
            "Si leurs positions sont opposées",
            "le second souhaite maintenir une entrée payante",
            "si les documents disent réellement cela",
            "N’inventez ni opposition, ni étude, ni source",
            "Complementary views need not be opposing views",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)

    def test_grammar_cues_distinguish_required_completions(self):
        for phrase in (
            "Bien que + subjonctif",
            "Bien que ce soit utile",
            "même si + indicatif",
            "Même si c’est utile",
            "Malgré + nom",
            "À condition que + subjonctif",
            "à condition que les règles soient claires",
            "à condition de + infinitif",
            "Vérifiez qui fait l’action",
            "Seulement si + indicatif",
            "quel que soit le coût",
            "quelle que soit la solution",
            "quels que soient les coûts",
            "quelles que soient les solutions",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.text)

    def test_checkbox_guidance_describes_self_assessed_reuse(self):
        self.assertIn(
            "Je peux la réutiliser sans regarder, dans une phrase adaptée.",
            self.text,
        )
        self.assertIn(
            "I can reuse this without looking, in an appropriate sentence.",
            self.text,
        )
        self.assertIn("not proof of a language level", self.text)
        self.assertFalse(self.parsed.attributes_for("input"))
        self.assertFalse(self.parsed.attributes_for("form"))

    def test_guide_does_not_create_annotation_or_progress_roots(self):
        for _tag, attrs in self.parsed.elements:
            self.assertNotIn("data-annotation-root", attrs)
            self.assertNotIn("data-annotation-source-key", attrs)
            self.assertNotIn("data-question-bank-question", attrs)
            self.assertNotIn("data-question-key", attrs)
        self.assertFalse(self.parsed.attributes_for("a"))
        self.assertNotRegex(self.markup, r"https?://|www\.")

    def test_methodology_button_targets_existing_task_three_dialog(self):
        buttons = self.parsed.attributes_for("button")
        self.assertEqual(len(buttons), 1)
        button = buttons[0]
        self.assertEqual(button["type"], "button")
        self.assertEqual(button["aria-haspopup"], "dialog")
        self.assertEqual(button["aria-controls"], "writing-methodology-dialog")
        self.assertEqual(button["data-dialog-open"], button["aria-controls"])
        self.assertFalse(self.parsed.attributes_for("dialog"))

        dialog = _GuideMarkup(render_to_string(
            "study/partials/writing_methodology_dialog.html",
            {"tache": 3},
        )).attributes_for("dialog")
        self.assertEqual(len(dialog), 1)
        self.assertEqual(dialog[0]["id"], button["aria-controls"])
        self.assertEqual(dialog[0]["data-writing-methodology"], "3")

    def test_methodology_dialog_teaches_the_same_timed_skeleton(self):
        text = " ".join(strip_tags(render_to_string(
            "study/partials/writing_methodology_task_three.html"
        )).split())
        for phrase in (
            "5 minutes pour lire et cartographier",
            "5 minutes pour planifier",
            "12 minutes pour écrire",
            "3 minutes pour relire",
            "Les deux documents abordent",
            "De son côté, le second",
            "En revanche, le second",
            "Pour ma part",
            "Tout d’abord",
            "De plus",
            "En conclusion",
            "document manque ou est inutilisable",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, text)

    def test_each_section_has_a_unique_accessible_heading(self):
        heading_ids = {
            attrs["id"] for attrs in self.parsed.attributes_for("h3")
        }
        labelled_sections = [
            attrs["aria-labelledby"]
            for attrs in self.parsed.attributes_for("section")
        ]
        self.assertEqual(len(heading_ids), 5)
        self.assertEqual(len(labelled_sections), len(set(labelled_sections)))
        self.assertEqual(set(labelled_sections), heading_ids)
