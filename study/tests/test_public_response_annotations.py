from dataclasses import asdict, replace
from io import StringIO
from types import SimpleNamespace
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.db.backends.postgresql.base import DatabaseWrapper
from django.db.models import Q
from django.test import SimpleTestCase, TestCase, tag
from django.urls import reverse
from django.utils import timezone

from study import catalogue
from study.account_services import provision_user_study_data
from study.models import Annotation, AnnotationKind, Card, PersonalResponse, Prompt
from study.oral_highlights import AnnotationRootText
from study.oral_history import variant_annotation_key
from study.public_annotation_migration import PUBLIC_DIGESTS
from study.public_response_annotations import (
    _annotations_for_update, capture_rendered_response_anchor, current_anchor,
    render_current_response, response_field_anchor,
)
from study.routing import prompt_detail_url
from study.response_personalization import effective_response
from study.tache_two_dialogues import dialogue_response

from . import factories


class CurrentAnchorTests(SimpleTestCase):
    def test_repositions_an_unchanged_unicode_quote_without_a_previous_response(self):
        before = "A long unchanged introduction. 🎬 A retained sentence. A long unchanged conclusion."
        after = "A replaced introduction of another length. 🎬 A retained sentence. A long unchanged conclusion."
        quote = "🎬 A retained sentence."
        start = len(before[:before.index(quote)].encode("utf-16-le")) // 2
        anchor = SimpleNamespace(
            quote=quote, start_offset=start,
            end_offset=start + len(quote.encode("utf-16-le")) // 2,
            prefix=before[:before.index(quote)],
            suffix=" A long unchanged conclusion.",
        )
        rendered = AnnotationRootText(f"<div data-annotation-root>{after}</div>")
        offsets = current_anchor(anchor, rendered)
        self.assertIsNotNone(offsets)
        self.assertNotEqual(offsets[0], start)
        self.assertEqual(rendered.slice(*offsets), quote)

    def test_missing_quotes_and_ambiguous_reused_phrases_are_not_guessed(self):
        rendered = AnnotationRootText(
            "<div data-annotation-root>Same prefix long enough. Common phrase. Same suffix long enough."
            " Other text. Same prefix long enough. Common phrase. Same suffix long enough.</div>"
        )
        for quote in ("Removed words.", "Common phrase."):
            annotation = SimpleNamespace(
                quote=quote, start_offset=0, end_offset=len(quote),
                prefix="Same prefix long enough. ", suffix=" Same suffix long enough.",
            )
            self.assertIsNone(current_anchor(annotation, rendered))

    def test_migration_identifiers_are_fixed_not_an_archive_of_responses(self):
        self.assertEqual(len(PUBLIC_DIGESTS), 529)
        self.assertIn("c90983de3988ceb4", PUBLIC_DIGESTS)
        self.assertTrue(all(len(value) == 16 and int(value, 16) >= 0 for value in PUBLIC_DIGESTS))

    def test_a_unique_long_quote_remains_usable_when_old_context_is_unavailable(self):
        quote = "This complete unchanged sentence has sufficient distinctive text."
        root = AnnotationRootText(f"<div data-annotation-root>A new introduction. {quote}</div>")
        annotation = SimpleNamespace(
            quote=quote, start_offset=1, end_offset=len(quote) + 1,
            prefix="", suffix="",
        )
        offsets = current_anchor(annotation, root)
        self.assertEqual(root.slice(*offsets), quote)
        annotation.quote = "new"
        self.assertIsNone(current_anchor(annotation, root))

    def test_generic_section_labels_do_not_move_a_removed_quote_to_another_argument(self):
        quote = "A long repeated example which belonged to a different argument."
        root = AnnotationRootText(
            f"<div data-annotation-root>Another argument. Exemple concret {quote}"
            " Conséquence Another consequence.</div>"
        )
        annotation = SimpleNamespace(
            quote=quote, start_offset=0, end_offset=len(quote),
            prefix="The former argument. Exemple concret ",
            suffix=" Conséquence A former consequence.",
        )
        self.assertIsNone(current_anchor(annotation, root))

    def test_unchanged_field_checksum_restores_an_exact_utf16_subselection(self):
        field = "🎬 Same short word, then the same short word."
        before = AnnotationRootText(
            '<div data-annotation-root>Old introduction.<p data-response-field="argument-2-exemple">'
            f"{field}</p>Old consequence.</div>"
        )
        start = before.text.rindex("short".encode("utf-16-le")) // 2
        annotation = SimpleNamespace(
            quote="short", start_offset=start, end_offset=start + 5,
            prefix=before.slice(max(0, start - 160), start),
            suffix=before.slice(start + 5, start + 165),
        )
        annotation.response_anchor = capture_rendered_response_anchor(
            annotation, before,
        )
        self.assertTrue(annotation.response_anchor)
        after = AnnotationRootText(
            '<div data-annotation-root>Entirely different preceding development.'
            f'<p data-response-field="argument-2-exemple">{field}</p>'
            "A changed consequence and following claim.</div>"
        )
        offsets = current_anchor(annotation, after)
        self.assertEqual(offsets[0], after.text.rindex("short".encode("utf-16-le")) // 2)
        self.assertNotEqual(offsets[0], start)
        self.assertEqual(after.slice(*offsets), "short")

    def test_a_long_quote_reused_in_a_different_argument_does_not_escape_its_field(self):
        quote = " ".join(["A distinctive but deliberately reused complete example."] * 12)
        before = AnnotationRootText(
            '<div data-annotation-root>The former argument. Exemple concret '
            f'<p data-response-field="argument-1-exemple">{quote}</p>'
            " Conséquence A former consequence.</div>"
        )
        start = before.text.index(quote.encode("utf-16-le")) // 2
        annotation = SimpleNamespace(
            quote=quote, start_offset=start, end_offset=start + len(quote),
            prefix=before.slice(max(0, start - 160), start),
            suffix=before.slice(start + len(quote), start + len(quote) + 160),
            response_anchor=response_field_anchor(before, (start, start + len(quote))),
        )
        after = AnnotationRootText(
            '<div data-annotation-root>The former argument. Exemple concret '
            '<p data-response-field="argument-1-exemple">A replacement.</p>'
            " Conséquence A former consequence."
            f'<p data-response-field="argument-2-exemple">{quote}</p></div>'
        )
        self.assertIsNone(current_anchor(annotation, after))
        annotation.response_anchor = {}
        self.assertEqual(capture_rendered_response_anchor(annotation, after), {})
        self.assertIsNone(current_anchor(annotation, after))

    def test_field_capture_requires_complete_current_context_not_quote_uniqueness(self):
        quote = "An unchanged example whose old argument cannot be identified."
        root = AnnotationRootText(
            '<div data-annotation-root>New development. Exemple concret '
            f'<p data-response-field="argument-2-exemple">{quote}</p>'
            " Conséquence New consequence.</div>"
        )
        start = root.text.index(quote.encode("utf-16-le")) // 2
        annotation = SimpleNamespace(
            quote=quote, start_offset=start, end_offset=start + len(quote),
            prefix="Old development. Exemple concret ",
            suffix=" Conséquence Old consequence.",
        )
        self.assertEqual(capture_rendered_response_anchor(annotation, root), {})
        self.assertIsNone(current_anchor(annotation, root))

    def test_a_partially_edited_field_still_requires_exact_quote_and_meaningful_context(self):
        quote = "A retained sentence."
        before = AnnotationRootText(
            '<div data-annotation-root><p data-response-field="argument-2-exemple">'
            f"An old opening. A distinctive unchanged internal context. {quote}"
            " A distinctive unchanged closing context.</p></div>"
        )
        start = before.text.index(quote.encode("utf-16-le")) // 2
        end = start + len(quote)
        annotation = SimpleNamespace(
            quote=quote, start_offset=start, end_offset=end,
            prefix=before.slice(max(0, start - 160), start),
            suffix=before.slice(end, end + 160),
            response_anchor=response_field_anchor(before, (start, end)),
        )
        for changed, expected in (
            (
                f"A rewritten opening with another length. A distinctive unchanged internal context. {quote}"
                " A distinctive unchanged closing context.",
                True,
            ),
            (f"Different opening. {quote} Different closing.", False),
            ("A different sentence replaces the selected text.", False),
        ):
            with self.subTest(changed=changed):
                after = AnnotationRootText(
                    '<div data-annotation-root><p data-response-field="argument-2-exemple">'
                    f"{changed}</p></div>"
                )
                offsets = current_anchor(annotation, after)
                self.assertEqual(offsets is not None, expected)
                if expected:
                    self.assertEqual(after.slice(*offsets), quote)

    def test_response_field_markers_do_not_change_annotation_text(self):
        plain = AnnotationRootText(
            "<div data-annotation-root>Introduction<p>A sentence.</p>Conclusion</div>"
        )
        marked = AnnotationRootText(
            '<div data-annotation-root>Introduction<p data-response-field="introduction">'
            "A sentence.</p>Conclusion</div>"
        )
        self.assertEqual(plain.text, marked.text)
        self.assertEqual(marked.slice(*marked.response_fields["introduction"]), "A sentence.")


class PublicAnnotationPostgresQueryTests(SimpleTestCase):
    def test_nullable_task_join_locks_only_annotation_rows(self):
        connection = DatabaseWrapper(
            {"NAME": "compile_only", "OPTIONS": {}}, alias="compile_only",
        )
        queryset = _annotations_for_update(
            get_user_model()(pk=1), Q(source_path="/expression/orale/tache-3/sujets/1/"),
        )
        with patch.object(connection, "get_autocommit", return_value=False):
            sql, _ = queryset.query.get_compiler(connection=connection).as_sql()
        self.assertIn('LEFT OUTER JOIN "study_task"', sql)
        self.assertIn('"study_annotation"."task_id" IS NULL', sql)
        self.assertTrue(sql.endswith('FOR UPDATE OF "study_annotation"'), sql)


@tag("database-locking")
class PublicResponsePreservationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("import_content", stdout=StringIO())
        cls.user = factories.make_user("targeted-public-owner")
        cls.other = factories.make_user("targeted-public-other")
        provision_user_study_data(cls.user)
        provision_user_study_data(cls.other)

    def setUp(self):
        self.client.force_login(self.user)

    def test_subject_pages_and_source_requests_work_without_saved_annotations(self):
        for key in ("culture:p1", "tache2:fevrier:batch-02:subject-07"):
            with self.subTest(subject=key):
                prompt = self.prompt(key)
                path = prompt_detail_url(prompt)
                self.assertEqual(self.client.get(path).status_code, 200)
                self.assertEqual(self.fetch(path), [])
        for path in (
            "/expression/orale/", "/expression/orale/tache-2/",
            "/expression/orale/tache-3/", "/expression/orale/tache-3/sujets/",
        ):
            with self.subTest(source=path):
                self.assertEqual(self.fetch(path), [])

    def prompt(self, key):
        return Prompt.objects.select_related(
            "response", "theme__task__part", "family",
        ).get(content_key=key)

    def legacy_public_key(self, prompt):
        # Fixed pre-transition identities, independent of future corpus edits.
        digest = (
            "e97e4c8e3a4513a2" if prompt.content_key.startswith("tache2:")
            else "c90983de3988ceb4"
        )
        self.assertIn(digest, PUBLIC_DIGESTS)
        return f"response:{prompt.content_key}:variant-{digest}"

    def mark(self, prompt, content, quote, *, surface="detail", kind=AnnotationKind.HIGHLIGHT, **overrides):
        root = render_current_response(prompt, content, surface, self.user)
        start = root.text.index(quote.encode("utf-16-le")) // 2
        end = start + len(quote.encode("utf-16-le")) // 2
        suffix = f":{surface}" if surface != "detail" else ""
        path = (
            prompt_detail_url(prompt) if surface == "detail"
            else reverse("study:task_review", args=["eo", prompt.theme.task.slug]) + "?kind=spine&reset=1"
        )
        values = {
            "user": self.user, "task": prompt.theme.task,
            "source_prompt": prompt, "kind": kind,
            "source_path": path, "source_key": variant_annotation_key(prompt, content) + suffix,
            "quote": quote, "start_offset": start, "end_offset": end,
            "prefix": root.slice(max(0, start - 160), start),
            "suffix": root.slice(end, end + 160),
            "body": "My own saved note.", "title": "My title",
            "study_later": True, "completed_at": timezone.now(),
        }
        return Annotation.objects.create(**(values | overrides))

    def fetch(self, path):
        page = self.client.get(reverse("study:annotations_for_source"), {"source_path": path})
        self.assertEqual(page.status_code, 200)
        return page.json()["highlights"]

    def assert_preserved(self, mark, prompt, content, surface="detail"):
        private = {
            name: getattr(mark, name) for name in (
                "pk", "quote", "body", "title", "study_later", "completed_at", "created_at",
            )
        }
        mark.refresh_from_db()
        for name, value in private.items():
            self.assertEqual(getattr(mark, name), value)
        suffix = f":{surface}" if surface != "detail" else ""
        self.assertEqual(mark.source_key, variant_annotation_key(prompt, content) + suffix)
        root = render_current_response(prompt, content, surface, self.user)
        self.assertEqual(root.slice(mark.start_offset, mark.end_offset), mark.quote)

    def test_eo3_example_edit_keeps_one_public_key_and_every_unchanged_field(self):
        prompt = self.prompt("culture:p1")
        models = catalogue.tache_three_models()
        model = models[prompt.response.semantic_group]
        before = model.response
        texts = [
            before.position_claire,
            *(text for argument in before.arguments for text in (
                argument.idea, argument.developpement, argument.exemple, argument.consequence,
            )),
            before.nuance, before.conclusion,
        ]
        marks = [self.mark(prompt, before, text) for text in texts]
        note = self.mark(prompt, before, before.conclusion, kind=AnnotationKind.NOTE)
        original_key = marks[0].source_key
        arguments = list(before.arguments)
        arguments[0] = replace(arguments[0], exemple="A completely rewritten example of a different length.")
        after = replace(before, arguments=tuple(arguments))
        with patch.object(catalogue, "tache_three_models", return_value={
            **models, model.group: replace(model, response=after),
        }):
            self.assertEqual(variant_annotation_key(prompt, after), original_key)
            returned = self.fetch(prompt_detail_url(prompt))
            removed = marks[texts.index(before.arguments[0].exemple)]
            self.assertNotIn(removed.pk, {item["id"] for item in returned})
            for mark in [item for item in marks if item != removed] + [note]:
                self.assert_preserved(mark, prompt, after)
        self.assertEqual(Annotation.objects.filter(user=self.user).count(), 16)
        removed.refresh_from_db()
        self.assertEqual(removed.quote, before.arguments[0].exemple)
        self.assertEqual(removed.body, "My own saved note.")

    def test_adjacent_rewrites_keep_unique_unchanged_introduction_and_conclusion_anchors(self):
        prompt = self.prompt("technologie:p21")
        models = catalogue.tache_three_models()
        model = models[prompt.response.semantic_group]
        before = model.response
        arguments = list(before.arguments)
        arguments[0] = replace(
            arguments[0],
            idea="A completely different first claim.",
            developpement="A newly explained mechanism with no previous surrounding wording.",
            exemple="A different actor takes a different action and demonstrates its result.",
            consequence="A revised consequence follows from that demonstration.",
        )
        after = replace(
            before,
            arguments=tuple(arguments),
            nuance="An entirely rewritten limitation changes the context before the conclusion.",
        )
        cards_before = list(Card.objects.filter(user=self.user).order_by("pk").values())
        for surface in ("detail", "back"):
            with self.subTest(surface=surface):
                marks = [
                    self.mark(prompt, before, quote, surface=surface)
                    for quote in (before.position_claire, before.conclusion)
                ]
                note = self.mark(
                    prompt, before, before.conclusion,
                    surface=surface, kind=AnnotationKind.NOTE,
                )
                removed = self.mark(
                    prompt, before, before.arguments[0].exemple, surface=surface,
                )
                ids = [mark.pk for mark in marks] + [note.pk, removed.pk]
                saved = list(Annotation.objects.filter(pk__in=ids).order_by("pk").values(
                    "pk", "quote", "body", "title", "study_later", "completed_at",
                    "created_at", "source_prompt_id",
                ))
                call_command("backfill_response_anchors", stdout=StringIO())
                for mark in [*marks, note, removed]:
                    mark.refresh_from_db()
                    self.assertTrue(mark.response_anchor)
                initial = self.fetch(marks[0].source_path)
                self.assertEqual(
                    {row["id"] for row in initial},
                    {mark.pk for mark in [*marks, removed]},
                )
                with patch.object(catalogue, "tache_three_models", return_value={
                    **models, model.group: replace(model, response=after),
                }):
                    returned = {row["id"] for row in self.fetch(marks[0].source_path)}
                    self.assertTrue({mark.pk for mark in marks} <= returned)
                    self.assertNotIn(removed.pk, returned)
                    for mark in [*marks, note]:
                        self.assert_preserved(mark, prompt, after, surface)
                self.assertEqual(
                    list(Annotation.objects.filter(pk__in=ids).order_by("pk").values(
                        "pk", "quote", "body", "title", "study_later", "completed_at",
                        "created_at", "source_prompt_id",
                    )),
                    saved,
                )
        self.assertEqual(
            list(Card.objects.filter(user=self.user).order_by("pk").values()), cards_before,
        )

    def test_all_eo3_models_preserve_unchanged_detail_and_practice_sections(self):
        models = catalogue.tache_three_models()
        self.assertEqual(len(models), 131)
        cards_before = list(Card.objects.filter(user=self.user).order_by("pk").values())
        for model in models.values():
            prompt = self.prompt(model.source_prompts[0][0])
            before = model.response
            texts = [
                before.position_claire,
                *(text for argument in before.arguments for text in (
                    argument.idea, argument.developpement, argument.exemple,
                    argument.consequence,
                )),
                before.nuance, before.conclusion,
            ]
            after = replace(before, arguments=(
                replace(before.arguments[0], exemple=(
                    "Un exemple de test entièrement différent remplace seulement cet exemple."
                )),
                *before.arguments[1:],
            ))
            for surface in ("detail", "back"):
                with self.subTest(group=model.group, surface=surface):
                    marks = [
                        self.mark(prompt, before, text, surface=surface) for text in texts
                    ]
                    note = self.mark(
                        prompt, before, before.conclusion, surface=surface,
                        kind=AnnotationKind.NOTE,
                    )
                    with patch.object(catalogue, "tache_three_models", return_value={
                        **models, model.group: replace(model, response=after),
                    }):
                        suffix = ":back" if surface == "back" else ""
                        self.assertEqual(
                            variant_annotation_key(prompt, after) + suffix,
                            marks[0].source_key,
                        )
                        returned = self.fetch(marks[0].source_path)
                        self.assertEqual(
                            {item["id"] for item in returned},
                            {mark.pk for index, mark in enumerate(marks) if index != 3},
                        )
                        for index, mark in enumerate(marks):
                            if index != 3:
                                self.assert_preserved(mark, prompt, after, surface)
                        self.assert_preserved(note, prompt, after, surface)
                    removed = marks[3]
                    removed.refresh_from_db()
                    self.assertEqual(removed.quote, before.arguments[0].exemple)
                    self.assertEqual(removed.body, "My own saved note.")
                    ids = [mark.pk for mark in marks] + [note.pk]
                    self.assertEqual(
                        Annotation.objects.filter(pk__in=ids, user=self.user).count(), 16,
                    )
                    Annotation.objects.filter(pk__in=ids, user=self.user).delete()
        self.assertEqual(
            list(Card.objects.filter(user=self.user).order_by("pk").values()), cards_before,
        )

    def test_backfill_is_idempotent_and_does_not_guess_or_modify_private_metadata(self):
        prompt = self.prompt("culture:p1")
        before = catalogue.tache_three_models()[prompt.response.semantic_group].response
        mark = self.mark(prompt, before, before.arguments[1].exemple)
        unverified = self.mark(
            prompt, before, before.conclusion, prefix="Unprovable previous context.",
        )
        private = self.mark(
            prompt, before, before.nuance, source_key="response:culture:p1:personal",
        )
        original = list(Annotation.objects.order_by("pk").values())
        for _ in range(2):
            call_command("backfill_response_anchors", stdout=StringIO())
        mark.refresh_from_db()
        self.assertEqual(mark.response_anchor["field"], "argument-2-exemple")
        unverified.refresh_from_db()
        private.refresh_from_db()
        self.assertEqual(unverified.response_anchor, {})
        self.assertEqual(private.response_anchor, {})
        current = list(Annotation.objects.order_by("pk").values())
        for old, new in zip(original, current):
            old.pop("response_anchor")
            new.pop("response_anchor")
            self.assertEqual(old, new)

    def test_initial_source_read_records_only_metadata_without_changing_revision(self):
        prompt = self.prompt("culture:p1")
        before = catalogue.tache_three_models()[prompt.response.semantic_group].response
        mark = self.mark(prompt, before, before.arguments[1].exemple)
        original = Annotation.objects.filter(pk=mark.pk).values().get()
        returned = self.fetch(mark.source_path)
        current = Annotation.objects.filter(pk=mark.pk).values().get()
        self.assertTrue(current.pop("response_anchor"))
        self.assertEqual(original.pop("response_anchor"), {})
        self.assertEqual(current, original)
        self.assertEqual(returned[0]["revision"], mark.updated_at.isoformat())

    def test_create_api_captures_old_page_selections_and_recomputes_expanded_anchors(self):
        prompt = self.prompt("culture:p1")
        before = catalogue.tache_three_models()[prompt.response.semantic_group].response
        root = render_current_response(prompt, before, "detail", self.user)
        full_quote = before.arguments[1].exemple
        start = root.text.index(full_quote.encode("utf-16-le")) // 2
        for quote, expected_created in ((full_quote[:40], True), (full_quote, False)):
            end = start + len(quote.encode("utf-16-le")) // 2
            response = self.client.post(reverse("study:annotation_create"), {
                "kind": AnnotationKind.HIGHLIGHT, "quote": quote,
                "source_path": prompt_detail_url(prompt),
                "source_key": variant_annotation_key(prompt, before),
                "task_id": prompt.theme.task_id,
                "start_offset": start, "end_offset": end,
                "prefix": root.slice(max(0, start - 160), start),
                "suffix": root.slice(end, end + 160),
                "response_anchor": '{"field": "argument-3-exemple"}',
            })
            self.assertIn(response.status_code, (200, 201))
            self.assertEqual(response.json()["created"], expected_created)
            mark = Annotation.objects.get(pk=response.json()["id"])
            self.assertEqual(mark.response_anchor["field"], "argument-2-exemple")
            self.assertEqual(mark.response_anchor["end"] - mark.response_anchor["start"], end - start)

    def test_explicit_argument_identity_follows_an_authored_move_not_a_reused_quote(self):
        prompt = self.prompt("culture:p1")
        models = catalogue.tache_three_models()
        model = models[prompt.response.semantic_group]
        before = model.response
        for surface in ("detail", "back"):
            with self.subTest(surface=surface):
                kept = self.mark(prompt, before, before.arguments[1].exemple, surface=surface)
                retired = self.mark(prompt, before, before.arguments[2].exemple, surface=surface)
                call_command("backfill_response_anchors", stdout=StringIO())
                after = replace(before, arguments=(
                    before.arguments[0],
                    replace(before.arguments[2], order=2),
                    replace(before.arguments[1], order=3),
                ))
                for identities, expected in (((1, 4, 2), {kept.pk}), ((1, 4, 5), set())):
                    with patch.object(catalogue, "tache_three_models", return_value={
                        **models, model.group: replace(
                            model, response=after, argument_ids=identities,
                        ),
                    }):
                        returned = {row["id"] for row in self.fetch(kept.source_path)}
                        self.assertEqual(returned & {kept.pk, retired.pk}, expected)
                        if kept.pk in expected:
                            self.assert_preserved(kept, prompt, after, surface)
                self.assertTrue(Annotation.objects.filter(pk=retired.pk).exists())

    def test_a_stale_unscoped_client_after_cutover_remains_stored_without_guessed_identity(self):
        prompt = self.prompt("culture:p1")
        models = catalogue.tache_three_models()
        model = models[prompt.response.semantic_group]
        before = model.response
        stale = self.mark(prompt, before, before.arguments[1].exemple)
        arguments = list(before.arguments)
        arguments[1] = replace(
            arguments[1], developpement="Entirely replaced preceding development.",
            consequence="Entirely replaced following consequence.",
        )
        after = replace(before, arguments=tuple(arguments))
        Annotation.objects.filter(pk=stale.pk).delete()
        with patch.object(catalogue, "tache_three_models", return_value={
            **models, model.group: replace(model, response=after),
        }):
            response = self.client.post(reverse("study:annotation_create"), {
                "kind": AnnotationKind.NOTE, "quote": stale.quote,
                "body": "Saved from an already-open old page.",
                "source_path": stale.source_path, "source_key": stale.source_key,
                "task_id": stale.task_id,
                "start_offset": stale.start_offset, "end_offset": stale.end_offset,
                "prefix": stale.prefix, "suffix": stale.suffix,
            })
            self.assertEqual(response.status_code, 201)
            saved = Annotation.objects.get(pk=response.json()["id"])
            self.assertEqual(saved.response_anchor, {})
            call_command("backfill_response_anchors", stdout=StringIO())
            self.fetch(saved.source_path)
            saved.refresh_from_db()
            self.assertEqual(saved.response_anchor, {})
            self.assertEqual(saved.quote, stale.quote)
            self.assertEqual(saved.body, "Saved from an already-open old page.")

    def test_idempotent_old_page_highlight_retry_keeps_its_verified_field_anchor(self):
        prompt = self.prompt("culture:p1")
        models = catalogue.tache_three_models()
        model = models[prompt.response.semantic_group]
        before = model.response
        mark = self.mark(prompt, before, before.arguments[1].exemple)
        call_command("backfill_response_anchors", stdout=StringIO())
        mark.refresh_from_db()
        original_anchor = mark.response_anchor
        arguments = list(before.arguments)
        arguments[1] = replace(
            arguments[1], developpement="New development before the unchanged example.",
            consequence="New consequence after the unchanged example.",
        )
        after = replace(before, arguments=tuple(arguments))
        with patch.object(catalogue, "tache_three_models", return_value={
            **models, model.group: replace(model, response=after),
        }):
            response = self.client.post(reverse("study:annotation_create"), {
                "kind": AnnotationKind.HIGHLIGHT, "quote": mark.quote,
                "source_path": mark.source_path, "source_key": mark.source_key,
                "task_id": mark.task_id, "start_offset": mark.start_offset,
                "end_offset": mark.end_offset, "prefix": mark.prefix, "suffix": mark.suffix,
            })
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["id"], mark.pk)
            mark.refresh_from_db()
            self.assertEqual(mark.response_anchor, original_anchor)
            self.assertIn(mark.pk, {row["id"] for row in self.fetch(mark.source_path)})
            self.assert_preserved(mark, prompt, after)

    def test_eo2_question_edit_preserves_other_questions_boundaries_notes_and_progress(self):
        key = "tache2:fevrier:batch-02:subject-07"
        prompt = self.prompt(key)
        dialogues = catalogue.tache_two_dialogues()
        dialogue = dialogues[key]
        before = dialogue_response(dialogue)
        marks = [
            self.mark(prompt, before, question.question)
            for question in dialogue.questions
        ]
        note = self.mark(prompt, before, before.conclusion, kind=AnnotationKind.NOTE)
        before_cards = list(Card.objects.filter(user=self.user).order_by("pk").values())
        original_key = variant_annotation_key(prompt, before)
        questions = list(dialogue.questions)
        questions[0] = replace(questions[0], question="Quels lieux de sortie conseilleriez-vous aux nouveaux arrivants ?")
        revised = replace(dialogue, questions=tuple(questions))
        after = dialogue_response(revised)
        with patch.object(catalogue, "tache_two_dialogues", return_value={
            member: revised if item.group == dialogue.group else item
            for member, item in dialogues.items()
        }):
            self.assertEqual(variant_annotation_key(prompt, after), original_key)
            returned = self.fetch(prompt_detail_url(prompt))
            self.assertNotIn(marks[0].pk, {item["id"] for item in returned})
            for mark in marks[1:] + [note]:
                self.assert_preserved(mark, prompt, after)
        self.assertEqual(list(Card.objects.filter(user=self.user).order_by("pk").values()), before_cards)
        self.assertEqual(Annotation.objects.filter(user=self.user).count(), 9)

    def test_existing_pre_lunch_notes_and_highlights_are_recovered_without_storing_a_response_version(self):
        prompt = self.prompt("culture:p1")
        current = catalogue.tache_three_models()[prompt.response.semantic_group].response
        arguments = list(current.arguments)
        arguments[2] = replace(
            arguments[2],
            exemple="Si des collègues déjeunent plus tôt, un nouvel arrivant peut commencer par les rejoindre une fois par semaine. Il découvre leur organisation et participe aux conversations, puis décide comment concilier ce rythme avec les habitudes de sa famille.",
        )
        previous = replace(current, arguments=tuple(arguments))
        key = self.legacy_public_key(prompt)
        marks = [
            self.mark(prompt, previous, previous.conclusion, source_key=key, kind=kind)
            for kind in (AnnotationKind.HIGHLIGHT, AnnotationKind.NOTE)
        ]
        removed = self.mark(prompt, previous, previous.arguments[2].exemple, source_key=key)
        page = self.client.get(prompt_detail_url(prompt))
        self.assertEqual(page.status_code, 200)
        for mark in marks:
            self.assert_preserved(mark, prompt, current)
        removed.refresh_from_db()
        self.assertEqual(removed.source_key, key)
        self.assertEqual(removed.quote, previous.arguments[2].exemple)

    def test_detail_front_and_back_annotations_migrate_without_resetting_private_records(self):
        for key in ("culture:p1", "tache2:fevrier:batch-02:subject-07"):
            prompt = self.prompt(key)
            content = (
                catalogue.tache_three_models()[prompt.response.semantic_group].response
                if key == "culture:p1"
                else dialogue_response(catalogue.tache_two_dialogues()[key])
            )
            for surface in ("detail", "front", "back"):
                with self.subTest(key=key, surface=surface):
                    quote = prompt.text if surface == "front" else content.conclusion
                    suffix = f":{surface}" if surface != "detail" else ""
                    mark = self.mark(
                        prompt, content, quote, surface=surface,
                        source_key=self.legacy_public_key(prompt) + suffix,
                    )
                    returned = self.fetch(mark.source_path)
                    self.assertIn(mark.pk, {item["id"] for item in returned})
                    self.assert_preserved(mark, prompt, content, surface)

    def test_private_versions_other_users_and_unknown_namespaces_are_not_rewritten(self):
        prompt = self.prompt("culture:p1")
        current = catalogue.tache_three_models()[prompt.response.semantic_group].response
        private = replace(current, position_claire="A private introduction.", is_personal=True)
        personal = PersonalResponse.objects.create(
            user=self.user, response=prompt.response, source_prompt=prompt,
            position_claire=private.position_claire,
        )
        marks = [
            self.mark(prompt, current, current.nuance, source_key=variant_annotation_key(prompt, private)),
            self.mark(prompt, current, current.conclusion, user=self.other),
            self.mark(prompt, current, current.position_claire, source_key="response:culture:p1:variant-0000000000000000"),
            self.mark(prompt, current, current.arguments[0].idea, source_path="/unrelated/"),
        ]
        before = list(Annotation.objects.filter(pk__in=[item.pk for item in marks]).order_by("pk").values())
        private_before = PersonalResponse.objects.filter(pk=personal.pk).values().get()
        self.fetch(prompt_detail_url(prompt))
        self.assertEqual(
            list(Annotation.objects.filter(pk__in=[item.pk for item in marks]).order_by("pk").values()), before,
        )
        self.assertEqual(PersonalResponse.objects.filter(pk=personal.pk).values().get(), private_before)

    def test_existing_current_destination_and_old_private_note_bodies_are_not_deleted(self):
        prompt = self.prompt("culture:p1")
        current = catalogue.tache_three_models()[prompt.response.semantic_group].response
        old = self.mark(
            prompt, current, current.conclusion,
            source_key=self.legacy_public_key(prompt),
        )
        destination = self.mark(prompt, current, current.conclusion, body="A different saved note.")
        ids = {old.pk, destination.pk}
        self.fetch(prompt_detail_url(prompt))
        self.assertEqual(set(Annotation.objects.filter(pk__in=ids).values_list("pk", flat=True)), ids)
        old.refresh_from_db()
        destination.refresh_from_db()
        self.assertEqual(old.body, "My own saved note.")
        self.assertEqual(destination.body, "A different saved note.")

    def test_repeated_reads_are_idempotent(self):
        prompt = self.prompt("culture:p1")
        current = catalogue.tache_three_models()[prompt.response.semantic_group].response
        mark = self.mark(
            prompt, current, current.conclusion, task=None,
            source_key=self.legacy_public_key(prompt),
        )
        self.fetch(prompt_detail_url(prompt))
        self.assert_preserved(mark, prompt, current)
        before = Annotation.objects.filter(pk=mark.pk).values().get()
        self.fetch(prompt_detail_url(prompt))
        self.assertEqual(Annotation.objects.filter(pk=mark.pk).values().get(), before)

    def test_multiple_future_edits_preserve_detail_and_both_review_surfaces(self):
        for key in ("culture:p1", "tache2:fevrier:batch-02:subject-07"):
            prompt = self.prompt(key)
            eo2 = key.startswith("tache2:")
            catalogue_function = "tache_two_dialogues" if eo2 else "tache_three_models"
            items = getattr(catalogue, catalogue_function)()
            item = items[key if eo2 else prompt.response.semantic_group]
            before = dialogue_response(item) if eo2 else item.response
            marks = [
                self.mark(
                    prompt, before, prompt.text if surface == "front" else before.conclusion,
                    surface=surface,
                ) for surface in ("detail", "front", "back")
            ]
            key_before = variant_annotation_key(prompt, before)
            for index in (1, 2):
                with self.subTest(prompt=key, push=index):
                    if eo2:
                        questions = list(item.questions)
                        questions[0] = replace(questions[0], question=f"Question remplacée {index} avec une longueur différente ?")
                        edited = replace(item, questions=tuple(questions))
                        after = dialogue_response(edited)
                        replacements = {
                            member: edited if value.group == item.group else value
                            for member, value in items.items()
                        }
                    else:
                        arguments = list(item.response.arguments)
                        arguments[0] = replace(arguments[0], exemple=f"A new example for editorial push {index}." * index)
                        after = replace(item.response, arguments=tuple(arguments))
                        replacements = {**items, item.group: replace(item, response=after)}
                    with patch.object(catalogue, catalogue_function, return_value=replacements):
                        self.assertEqual(variant_annotation_key(prompt, after), key_before)
                        for surface, mark in zip(("detail", "front", "back"), marks):
                            self.assertIn(mark.pk, {row["id"] for row in self.fetch(mark.source_path)})
                            self.assert_preserved(mark, prompt, after, surface)

    def test_unanchored_general_notes_keep_their_identity_body_and_completion_state(self):
        prompt = self.prompt("culture:p1")
        current = catalogue.tache_three_models()[prompt.response.semantic_group].response
        note = Annotation.objects.create(
            user=self.user, task=None, kind=AnnotationKind.NOTE,
            source_path=prompt_detail_url(prompt),
            source_key=self.legacy_public_key(prompt),
            body="A general response note.", study_later=True, completed_at=timezone.now(),
        )
        original = (note.pk, note.body, note.completed_at, note.created_at)
        self.fetch(note.source_path)
        note.refresh_from_db()
        self.assertEqual(note.source_key, variant_annotation_key(prompt, current))
        self.assertEqual((note.pk, note.body, note.completed_at, note.created_at), original)
        self.assertEqual(note.quote, "")
        self.assertIsNone(note.start_offset)

    def test_part_review_and_legacy_numeric_subject_urls_are_supported(self):
        prompt = self.prompt("tache2:fevrier:batch-02:subject-07")
        current = dialogue_response(catalogue.tache_two_dialogues()[prompt.content_key])
        for surface, path in (
            ("back", reverse("study:part_review", args=["eo"]) + "?kind=spine"),
            ("detail", reverse("study:response_detail", args=["eo", "tache-2", prompt.pk])),
        ):
            with self.subTest(surface=surface):
                mark = self.mark(
                    prompt, current, current.conclusion, surface=surface,
                    source_path=path,
                    source_key=self.legacy_public_key(prompt)
                    + (":back" if surface == "back" else ""),
                )
                self.assertIn(mark.pk, {row["id"] for row in self.fetch(path)})
                self.assert_preserved(mark, prompt, current, surface)

    def test_eo2_private_note_only_copy_keeps_its_questions_when_the_public_model_changes(self):
        key = "tache2:fevrier:batch-02:subject-07"
        prompt = self.prompt(key)
        items = catalogue.tache_two_dialogues()
        dialogue = items[key]
        before = dialogue_response(dialogue)
        values = asdict(before)
        values.pop("is_personal")
        values["arguments"] = list(values["arguments"])
        values["nuance"] = "My own private English explanation."
        private = PersonalResponse.objects.create(
            user=self.user, response=prompt.response, source_prompt=prompt, **values,
        )
        marks = [
            self.mark(
                prompt, before,
                prompt.text if surface == "front" else dialogue.questions[0].question,
                surface=surface,
            ) for surface in ("detail", "front", "back")
        ]
        private_before = PersonalResponse.objects.filter(pk=private.pk).values().get()
        questions = list(dialogue.questions)
        questions[0] = replace(questions[0], question="Une nouvelle question publique différente ?")
        revised = replace(dialogue, questions=tuple(questions))
        with patch.object(catalogue, "tache_two_dialogues", return_value={
            member: revised if item.group == dialogue.group else item
            for member, item in items.items()
        }):
            current = effective_response(prompt.response, self.user, prompt=prompt)
            self.assertTrue(current.is_personal)
            self.assertEqual(current.arguments, before.arguments)
            for surface, mark in zip(("detail", "front", "back"), marks):
                self.assertIn(mark.pk, {row["id"] for row in self.fetch(mark.source_path)})
                self.assert_preserved(mark, prompt, current, surface)
        self.assertEqual(PersonalResponse.objects.filter(pk=private.pk).values().get(), private_before)
