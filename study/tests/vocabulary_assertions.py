from django.template.loader import render_to_string

from study import queue


def assert_vocabulary_lot_tables(case, url, scope, group_key):
    full = case.client.get(url)
    case.assertEqual(full.status_code, 200)
    lots = full.context["vocabulary_lots"]
    case.assertTrue(lots)
    for lot in (lots if len(lots) == 1 else (lots[0], lots[-1])):
        with case.subTest(url=url, lot=lot["number"]):
            page = case.client.get(lot["table_url"])
            case.assertEqual(page.status_code, 200)
            expected = list(
                queue.scoped_cards(
                    {**scope, "batch": str(lot["number"])},
                    user=case.user,
                    include_suspended=True,
                )
                .order_by("phrase__lot_order", "phrase_id")
                .values_list("phrase_id", flat=True)
                .distinct()
            )
            actual = [
                phrase.pk
                for group in page.context[group_key]
                for phrase in group["phrases"]
            ]
            case.assertEqual(actual, expected)
            case.assertEqual(page.context["catalog_phrase_count"], len(expected))
            case.assertEqual(page.context["phrase_count"], full.context["phrase_count"])
            case.assertEqual(page.context["selected_batch"]["review_url"], lot["review_url"])
            case.assertEqual(page.context["initial_collection_view"], "table")
            case.assertContains(page, 'data-initial-collection-view="table"')
            navigation = render_to_string(
                "study/partials/review_batches.html",
                {"batches": page.context["vocabulary_lots"]},
            )
            case.assertEqual(navigation.count('aria-current="page"'), 1)
            case.assertTemplateUsed(page, "study/partials/vocabulary_lot_actions.html")
            case.assertContains(page, "Pratiquer ce lot")
            case.assertContains(page, "Toutes les fiches")
