from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from study.context_processors import VOCABULARY_COLLECTION_ROUTES, study_globals


class VocabularyCollectionDefaultsTests(SimpleTestCase):
    def context(self, route):
        request = RequestFactory().get("/?kind=spine")
        request.user = SimpleNamespace(is_authenticated=True)
        request.resolver_match = SimpleNamespace(
            namespace="study", url_name=route, kwargs={},
        )
        with patch("study.context_processors._explicit_task", return_value=None):
            return study_globals(request)

    def test_every_vocabulary_listing_defaults_to_a_separate_table_preference(self):
        for route in VOCABULARY_COLLECTION_ROUTES:
            with self.subTest(route=route):
                context = self.context(route)
                self.assertEqual(context["default_collection_view"], "table")
                self.assertEqual(context["collection_view_preference"], "vocabularyCollectionViewMode")

    def test_study_sessions_and_other_collections_keep_their_existing_preferences(self):
        for route in (
            "review", "task_review", "comprehension_vocabulary_review",
            "comprehension_oral_vocabulary_review", "task_browse", "task_notes", "learn",
        ):
            with self.subTest(route=route):
                context = self.context(route)
                self.assertNotIn("default_collection_view", context)
                self.assertNotIn("collection_view_preference", context)
