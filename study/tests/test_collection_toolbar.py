from django.template.loader import render_to_string
from django.test import SimpleTestCase


class CollectionToolbarTests(SimpleTestCase):
    template = "study/partials/collection_toolbar.html"

    def test_progress_accepts_zero_but_not_missing_totals(self):
        for context in ({}, {"progress_total": None}, {"progress_total": ""}):
            with self.subTest(context=context):
                markup = render_to_string(self.template, context)
                self.assertNotIn("data-collection-progress", markup)
        for completed, total in ((0, 0), (0, 70), (12, 70)):
            with self.subTest(completed=completed, total=total):
                markup = render_to_string(self.template, {
                    "progress_completed": completed,
                    "progress_total": total,
                    "progress_unit": "sujets terminés",
                })
                self.assertIn(
                    f'data-collection-progress-value>{completed}/{total}</span>',
                    markup,
                )
                self.assertIn(
                    f'{completed} sur {total} sujets terminés</span>', markup
                )
                self.assertNotIn('class="progress', markup)

    def test_empty_collections_do_not_offer_unavailable_actions(self):
        context = {
            "primary_action_url": "",
            "secondary_action_url": "/mixed-review/",
            "secondary_action_label": "Révision mélangée",
            "secondary_action_visible": 0,
            "show_views": [],
        }
        markup = render_to_string(self.template, context)
        self.assertNotIn("<a ", markup)
        self.assertNotIn("data-collection-view-toggle", markup)
        context.update({
            "primary_action_url": "/next-batch/",
            "primary_action_label": "Continuer le prochain lot",
            "secondary_action_visible": 20,
            "show_views": True,
        })
        markup = render_to_string(self.template, context)
        self.assertIn('href="/next-batch/"', markup)
        self.assertIn('href="/mixed-review/"', markup)
        self.assertIn("data-collection-view-toggle", markup)
