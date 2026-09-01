from __future__ import annotations

import json
from unittest import mock

from django.core.cache import cache
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from study.models import Annotation, AnnotationKind, Card, CardType, Prompt
from study.routing import prompt_detail_url, response_detail_url, theme_detail_url

from . import factories
from .test_views import FLASHCARD_DECK_HOOKS


class AnnotationTests(TestCase):
    def setUp(self):
        self.user = factories.make_user("notes-owner")
        self.other = factories.make_user("notes-other")
        self.client.force_login(self.user)
        self.part = factories.make_part(slug="eo")
        self.task = factories.make_task(part=self.part, slug="tache-3")
        self.source_path = reverse(
            "study:task_detail",
            args=[self.part.slug, self.task.slug],
        )
        self.task_notes_url = reverse(
            "study:task_notes",
            args=[self.part.slug, self.task.slug],
        )
        self.general_notes_url = reverse("study:general_notes")
        self.custom_notes_url = reverse("study:custom_notes")
        self.selection = {
            "quote": "Il faut nuancer cette affirmation.",
            "start_offset": "24",
            "end_offset": "58",
            "prefix": "Préambule ",
            "suffix": " Conclusion",
            "source_path": self.source_path,
            "source_title": "Tâche 3 · Heureux",
            "task_id": str(self.task.id),
        }

    def test_notes_hierarchy_and_subsections_render(self):
        note = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            title="Structure à réutiliser",
            body="Réutiliser cette structure.",
        )
        highlight = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.HIGHLIGHT,
            quote="Passage important",
            source_path=self.source_path,
            start_offset=2,
            end_offset=19,
        )

        overview = self.client.get(reverse("study:notes_overview"))
        self.assertContains(overview, self.part.short_name)
        self.assertContains(overview, self.task.name)
        self.assertEqual(len(overview.context["notes"]), 1)
        self.assertEqual(len(overview.context["highlights"]), 1)

        notes_tab = self.client.get(self.task_notes_url)
        self.assertContains(notes_tab, 'role="tablist"')
        self.assertContains(
            notes_tab,
            'class="annotations-grid collection-table '
            'collection-table--annotations"',
        )
        self.assertContains(notes_tab, "data-collection-view-toggle", count=1)
        self.assertContains(
            notes_tab,
            'data-collection-view-option="cards"',
        )
        self.assertContains(
            notes_tab,
            'data-collection-view-option="table"',
        )
        self.assertContains(notes_tab, "data-notes-recall", count=1)
        self.assertContains(notes_tab, 'data-recall-column="english"', count=1)
        self.assertContains(
            notes_tab,
            "data-note-dialog-paste-close",
            count=1,
        )
        self.assertContains(notes_tab, "Coller et fermer")
        self.assertContains(notes_tab, "<span>Note</span>")
        self.assertContains(notes_tab, f'id="note-{note.id}"', count=1)
        self.assertContains(
            notes_tab,
            f'data-annotation-item="{note.id}"',
            count=1,
        )
        self.assertContains(
            notes_tab,
            'id="notes-tab"',
        )
        self.assertContains(notes_tab, 'aria-selected="true"')
        self.assertContains(notes_tab, "Réutiliser cette structure.")
        self.assertNotContains(notes_tab, "Passage important")
        self.assertContains(
            notes_tab,
            "annotation-action__icon--study",
        )
        # The optional title is French and can be read aloud.
        self.assertContains(
            notes_tab,
            "read-aloud-action__icon",
        )
        # Template comments must never leak into the rendered page.
        self.assertNotContains(notes_tab, "{#")
        self.assertNotContains(notes_tab, "text-to-speech")
        self.assertNotContains(notes_tab, "annotation-action__icon--flashcard")
        self.assertContains(
            notes_tab,
            "annotation-action__icon--edit",
        )
        self.assertContains(
            notes_tab,
            "annotation-action__icon--delete",
        )

        highlights_tab = self.client.get(
            self.task_notes_url + "?tab=highlights"
        )
        self.assertEqual(highlights_tab.context["active_tab"], "highlights")
        self.assertContains(
            highlights_tab,
            'class="annotations-grid collection-table '
            'collection-table--annotations"',
        )
        self.assertContains(highlights_tab, "<span>Passage</span>")
        self.assertContains(
            highlights_tab,
            f'id="highlight-{highlight.id}"',
            count=1,
        )
        self.assertContains(
            highlights_tab,
            f'data-annotation-item="{highlight.id}"',
            count=1,
        )
        self.assertContains(highlights_tab, "Passage important")
        self.assertNotContains(highlights_tab, "Réutiliser cette structure.")
        self.assertContains(highlights_tab, "data-notes-recall", count=1)

    def test_notes_render_one_adaptive_node_per_annotation(self):
        notes = [
            Annotation.objects.create(
                user=self.user,
                task=self.task,
                kind=AnnotationKind.NOTE,
                title=f"Titre {index}",
                quote=f"Passage cité {index}.",
                body=f"Corps **{index}** à relire.",
                source_path=self.source_path,
                source_title="Tâche 3 · Heureux",
                study_later=index == 0,
            )
            for index in range(3)
        ]
        older = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            body="Note de la semaine dernière.",
        )
        Annotation.objects.filter(pk=older.pk).update(
            created_at=timezone.now() - timezone.timedelta(days=20)
        )

        response = self.client.get(self.task_notes_url)
        body = response.content.decode()

        # Exactly one node — and therefore one Markdown render, one anchor and
        # one of every action — per annotation, whichever view mode the
        # learner has stored client-side.
        self.assertEqual(body.count("data-annotation-item="), 4)
        for index, note in enumerate(notes):
            self.assertContains(
                response,
                f'data-annotation-item="{note.id}"',
                count=1,
            )
            self.assertContains(response, f'id="note-{note.id}"', count=1)
            self.assertContains(
                response,
                f"<strong>{index}</strong>",
                count=1,
                html=True,
            )
            self.assertContains(
                response,
                f"annotation-french-{note.id}",
                count=2,
            )
            self.assertContains(
                response,
                f'data-annotation-action="study" data-annotation-id="{note.id}"',
                count=1,
            )
            self.assertContains(
                response,
                f'data-annotation-action="complete" '
                f'data-annotation-id="{note.id}"',
                count=1,
            )
            self.assertContains(
                response,
                f'data-annotation-action="delete" '
                f'data-annotation-id="{note.id}"',
                count=1,
            )
            self.assertContains(
                response,
                f'data-annotation-edit="{note.id}"',
                count=1,
            )
            self.assertContains(
                response,
                f'data-annotation-edit-source="{note.id}"',
                count=1,
            )

        # One node covers both view modes, so nothing is hidden behind a
        # per-mode panel any more.
        self.assertNotContains(response, "data-collection-view-panel")
        self.assertNotContains(response, "data-annotation-anchor")
        self.assertEqual(body.count('data-collection-view="adaptive"'), 2)
        self.assertEqual(body.count("data-collection-table-header"), 2)
        self.assertEqual(body.count("data-collection-item"), 4)

        # Every column the table shows is written into that one node: kind,
        # status, date, scope, source and actions.
        self.assertContains(response, "annotation-card__kind")
        self.assertContains(response, "annotation-card__study", count=1)
        self.assertContains(response, "annotation-card__context", count=4)
        self.assertContains(response, "annotation-card__scope", count=4)
        self.assertContains(response, "annotation-card__source", count=3)

        # Date grouping and its counts survive the single representation.
        self.assertEqual(
            [section["key"] for section in response.context["notes_sections"]],
            ["today", "earlier"],
        )
        self.assertContains(response, 'id="notes-today-heading"', count=1)
        self.assertContains(response, 'id="notes-earlier-heading"', count=1)
        self.assertContains(response, "notes-date-section__count", count=2)

    def test_highlights_render_one_adaptive_node_per_annotation(self):
        highlight = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.HIGHLIGHT,
            quote="Passage à revoir plus tard.",
            source_path=self.source_path,
            source_key="response:culture:p1:back",
            source_title="Tâche 3 · Heureux",
            start_offset=1,
            end_offset=28,
        )

        response = self.client.get(self.task_notes_url + "?tab=highlights")
        body = response.content.decode()

        self.assertEqual(body.count("data-annotation-item="), 1)
        self.assertContains(response, f'id="highlight-{highlight.id}"', count=1)
        self.assertContains(response, "Passage à revoir plus tard.", count=1)
        self.assertContains(response, "annotation-card__origin", count=1)
        self.assertContains(response, "annotation-card__source", count=1)
        self.assertNotContains(response, "data-annotation-edit=")
        self.assertContains(
            response,
            f'data-annotation-action="delete" '
            f'data-annotation-id="{highlight.id}"',
            count=1,
        )

    def test_empty_notes_and_highlights_hide_the_view_toggle(self):
        notes_tab = self.client.get(self.task_notes_url)
        self.assertNotContains(notes_tab, "data-collection-view-toggle")
        self.assertNotContains(notes_tab, "data-notes-recall")

        highlights_tab = self.client.get(
            self.task_notes_url + "?tab=highlights"
        )
        self.assertNotContains(highlights_tab, "data-collection-view-toggle")
        self.assertNotContains(highlights_tab, "data-notes-recall")

    def test_notes_recall_fields_follow_the_content_language(self):
        note = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            title="Titre facultatif",
            quote="Passage capturé en français.",
            body="The written note is in English.",
        )

        response = self.client.get(self.task_notes_url)

        self.assertContains(response, 'data-recall-column="french"', count=1)
        self.assertContains(response, 'data-recall-column="english"', count=1)
        # The single card groups the French title and passage together.
        self.assertContains(
            response,
            f'data-recall-entry="annotation-french-{note.id}"',
            count=2,
        )
        # Only the written note belongs to the English recall field.
        self.assertContains(
            response,
            f'data-recall-entry="annotation-english-{note.id}"',
            count=1,
        )

        search = self.client.get(
            reverse("study:annotation_search"),
            {"q": "written note"},
        )
        self.assertNotContains(search, "data-recall-cell")

    def test_note_bodies_render_safe_markdown_everywhere(self):
        Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            title="Rappel Markdown",
            body=(
                "## Structure\n\n"
                "- **Nuancer** l'idée\n"
                "- Employer `cependant`\n\n"
                "[Source](https://example.com)\n\n"
                "<script>alert('x')</script>\n\n"
                "[Lien dangereux](javascript:alert(1))"
            ),
            study_later=True,
        )

        notes_page = self.client.get(self.task_notes_url)
        # The page renders each annotation once, so each Markdown body is
        # converted once too.
        self.assertContains(notes_page, "<h2>Structure</h2>", count=1, html=True)
        self.assertContains(
            notes_page,
            "<strong>Nuancer</strong>",
            count=1,
            html=True,
        )
        self.assertContains(notes_page, 'href="https://example.com"', count=1)
        self.assertNotContains(notes_page, "<script>")
        self.assertNotContains(notes_page, 'href="javascript:')
        self.assertContains(notes_page, "&lt;script&gt;alert")
        self.assertContains(notes_page, "Markdown pris en charge")

        search_page = self.client.get(
            reverse("study:annotation_search"),
            {"q": "Nuancer"},
        )
        self.assertContains(search_page, "<h2>Structure</h2>", html=True)
        self.assertContains(
            search_page,
            "<strong>Nuancer</strong>",
            html=True,
        )
        self.assertNotContains(search_page, "<script>")
        self.assertNotContains(search_page, 'href="javascript:')

        study_page = self.client.get(
            reverse(
                "study:task_annotation_study",
                args=[self.part.slug, self.task.slug],
            )
        )
        self.assertContains(study_page, "<h2>Structure</h2>", html=True)
        self.assertContains(
            study_page,
            "<strong>Nuancer</strong>",
            html=True,
        )
        self.assertNotContains(study_page, "<script>")
        self.assertNotContains(study_page, 'href="javascript:')

    def test_highlights_show_source_origin_and_group_by_date(self):
        response_highlight = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.HIGHLIGHT,
            quote="Passage d'une réponse",
            source_path=self.source_path,
            source_key="response:culture:p1:back",
            start_offset=1,
            end_offset=21,
        )
        legacy_response_highlight = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.HIGHLIGHT,
            quote="Ancien passage de réponse",
            source_path=self.source_path,
            start_offset=22,
            end_offset=47,
        )
        expression_highlight = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.HIGHLIGHT,
            quote="Passage d'une expression",
            source_path=reverse("study:review") + "?kind=phrase",
            source_key="phrase:expr-1:phrase_production:back",
            start_offset=1,
            end_offset=25,
        )
        legacy_expression_highlight = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.HIGHLIGHT,
            quote="Ancien passage d'expression",
            source_path=reverse(
                "study:task_phrases",
                args=[self.part.slug, self.task.slug],
            ),
            start_offset=1,
            end_offset=28,
        )

        response = self.client.get(
            self.task_notes_url + "?tab=highlights"
        )

        origins = {
            highlight.id: highlight.origin_label
            for highlight in response.context["highlights"]
        }
        self.assertEqual(origins[response_highlight.id], "Réponse")
        self.assertEqual(origins[legacy_response_highlight.id], "Réponse")
        self.assertEqual(origins[expression_highlight.id], "Expression")
        self.assertEqual(origins[legacy_expression_highlight.id], "Expression")
        self.assertContains(response, "Réponse")
        self.assertContains(response, "Expression")

        section_keys = [
            section["key"]
            for section in response.context["highlights_sections"]
        ]
        self.assertEqual(section_keys, ["today"])
        self.assertContains(response, "Aujourd")

    def test_freeform_notes_are_categorized_by_task_or_general(self):
        task_url = self.task_notes_url
        response = self.client.post(
            task_url,
            {"title": "Connecteurs", "body": "Employer cependant et pourtant."},
        )
        task_note = Annotation.objects.get(title="Connecteurs")
        self.assertRedirects(
            response,
            task_url + f"?tab=notes#note-{task_note.id}",
        )
        self.assertEqual(task_note.user, self.user)
        self.assertEqual(task_note.task, self.task)
        self.assertEqual(task_note.kind, AnnotationKind.NOTE)

        general_url = self.general_notes_url
        response = self.client.post(
            general_url,
            {"title": "", "body": "Objectif de la semaine."},
        )
        general_note = Annotation.objects.get(body="Objectif de la semaine.")
        self.assertRedirects(
            response,
            self.custom_notes_url + f"?tab=notes#note-{general_note.id}",
        )
        self.assertIsNone(general_note.task)

    def test_note_dialog_preserves_a_safe_filtered_return_url(self):
        return_url = self.task_notes_url + "?q=transition"
        response = self.client.post(
            self.task_notes_url,
            {
                "title": "Transition",
                "body": "Conserver cette transition.",
                "next": return_url,
            },
        )
        note = Annotation.objects.get(title="Transition")
        self.assertRedirects(
            response,
            return_url + f"#note-{note.id}",
        )

    def test_selected_note_is_private_and_source_linked(self):
        response = self.client.post(
            reverse("study:annotation_create"),
            {**self.selection, "kind": AnnotationKind.NOTE, "body": "À mémoriser."},
        )
        self.assertEqual(response.status_code, 201)
        note = Annotation.objects.get()
        self.assertEqual(note.user, self.user)
        self.assertEqual(note.task, self.task)
        self.assertEqual(note.quote, self.selection["quote"])
        self.assertEqual(note.body, "À mémoriser.")
        self.assertEqual(note.source_path, self.source_path)
        self.assertEqual(
            response.json()["notes_url"],
            self.task_notes_url + f"?tab=notes#note-{note.id}",
        )

        self.client.force_login(self.other)
        other_page = self.client.get(self.task_notes_url)
        self.assertNotContains(other_page, "À mémoriser.")
        self.assertEqual(
            self.client.post(
                reverse("study:annotation_delete", args=[note.id])
            ).status_code,
            404,
        )

    def test_highlight_creation_is_idempotent_and_restorable(self):
        payload = {
            **self.selection,
            "kind": AnnotationKind.HIGHLIGHT,
            "overlap_ids": "",
        }
        first = self.client.post(reverse("study:annotation_create"), payload)
        second = self.client.post(reverse("study:annotation_create"), payload)

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(Annotation.objects.count(), 1)
        self.assertEqual(
            first.json()["notes_url"],
            self.task_notes_url
            + f"?tab=highlights#highlight-{first.json()['id']}",
        )

        response = self.client.get(
            reverse("study:annotations_for_source"),
            {"source_path": self.source_path},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()["highlights"]), 1)
        self.assertEqual(
            response.json()["highlights"][0]["quote"],
            self.selection["quote"],
        )

        self.client.force_login(self.other)
        response = self.client.get(
            reverse("study:annotations_for_source"),
            {"source_path": self.source_path},
        )
        self.assertEqual(response.json()["highlights"], [])

    def test_response_highlight_marks_only_its_subject_in_progress(self):
        theme = factories.make_theme(
            "highlight-progress",
            task=self.task,
        )
        response = factories.make_response(theme=theme)
        card = Card.objects.create(
            user=self.user,
            card_type=CardType.SPINE,
            response=response,
        )
        other_card = Card.objects.create(
            user=self.other,
            card_type=CardType.SPINE,
            response=response,
        )
        source_path = response_detail_url(response)

        created = self.client.post(
            reverse("study:annotation_create"),
            {
                **self.selection,
                "kind": AnnotationKind.HIGHLIGHT,
                "source_path": source_path,
                "source_key": "",
                "overlap_ids": "",
            },
        )

        self.assertEqual(created.status_code, 201)
        card.refresh_from_db()
        other_card.refresh_from_db()
        self.assertIsNone(card.started_at)
        self.assertIsNone(other_card.started_at)

        theme_page = self.client.get(
            theme_detail_url(theme)
        )
        self.assertContains(
            theme_page,
            '<span class="progress-status progress-status--active" '
            f'data-subject-progress-status="{card.response_id}">'
            "En cours</span>",
            html=True,
        )

        deleted = self.client.post(
            reverse("study:annotation_delete", args=[created.json()["id"]]),
            {"next": source_path},
        )
        self.assertRedirects(deleted, source_path)
        subject_page = self.client.get(source_path)
        self.assertEqual(subject_page.context["subject_progress"].status, "new")

    def test_notes_and_linked_expression_highlights_do_not_start_subject(self):
        theme = factories.make_theme("annotation-progress-exclusions", task=self.task)
        response = factories.make_response(theme=theme)
        prompt = response.prompts.get(is_canonical=True)
        linked_phrase = factories.make_phrase(tier="response")
        linked_phrase.source_prompts.add(prompt)
        source_path = response_detail_url(response)
        Card.objects.create(
            user=self.user,
            card_type=CardType.SPINE,
            response=response,
        )

        note = self.client.post(
            reverse("study:annotation_create"),
            {
                **self.selection,
                "kind": AnnotationKind.NOTE,
                "body": "Une note sur cette réponse.",
                "source_path": source_path,
                "source_key": "",
            },
        )
        linked_expression_highlight = self.client.post(
            reverse("study:annotation_create"),
            {
                **self.selection,
                "kind": AnnotationKind.HIGHLIGHT,
                "source_path": source_path,
                "source_key": f"phrase:{linked_phrase.phrase_id}:catalog",
                "overlap_ids": "",
            },
        )
        sidebar_highlight = self.client.post(
            reverse("study:annotation_create"),
            {
                **self.selection,
                "kind": AnnotationKind.HIGHLIGHT,
                "source_path": source_path,
                "source_key": (
                    f"subject-sidebar:{response.content_key}"
                ),
                "overlap_ids": "",
            },
        )

        self.assertEqual(note.status_code, 201)
        self.assertEqual(linked_expression_highlight.status_code, 201)
        self.assertEqual(sidebar_highlight.status_code, 201)
        subject_page = self.client.get(source_path)
        self.assertEqual(subject_page.context["subject_progress"].status, "new")

    def test_subject_vocabulary_highlight_starts_its_subject(self):
        theme = factories.make_theme("subject-vocabulary-highlight", task=self.task)
        response = factories.make_response(theme=theme)
        prompt = response.prompts.get(is_canonical=True)
        subject_phrase = factories.make_phrase(tier="subject")
        subject_phrase.source_prompts.add(prompt)
        Card.objects.create(
            user=self.user,
            card_type=CardType.SPINE,
            response=response,
        )

        created = self.client.post(
            reverse("study:annotation_create"),
            {
                **self.selection,
                "kind": AnnotationKind.HIGHLIGHT,
                "source_path": response_detail_url(response),
                "source_key": f"phrase:{subject_phrase.phrase_id}:catalog",
                "overlap_ids": "",
            },
        )

        self.assertEqual(created.status_code, 201)
        subject_page = self.client.get(response_detail_url(response))
        self.assertEqual(
            subject_page.context["subject_progress"].status,
            "active",
        )

    def test_dynamic_card_source_keys_prevent_offset_collisions(self):
        first = self.client.post(
            reverse("study:annotation_create"),
            {
                **self.selection,
                "kind": AnnotationKind.HIGHLIGHT,
                "source_key": "response:culture:p1:front",
            },
        )
        second = self.client.post(
            reverse("study:annotation_create"),
            {
                **self.selection,
                "kind": AnnotationKind.HIGHLIGHT,
                "quote": "Un autre passage aux mêmes positions.",
                "source_key": "response:economie:p1:front",
            },
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 201)
        self.assertNotEqual(first.json()["id"], second.json()["id"])
        self.assertEqual(Annotation.objects.count(), 2)
        restored = self.client.get(
            reverse("study:annotations_for_source"),
            {"source_path": self.source_path},
        ).json()["highlights"]
        keys = {item["source_key"] for item in restored}
        self.assertEqual(
            keys,
            {
                "response:culture:p1:front",
                "response:economie:p1:front",
            },
        )

    def test_changed_text_updates_the_same_highlight_anchor(self):
        payload = {
            **self.selection,
            "kind": AnnotationKind.HIGHLIGHT,
            "source_key": "response:culture:p1:back",
        }
        first = self.client.post(reverse("study:annotation_create"), payload)
        second = self.client.post(
            reverse("study:annotation_create"),
            {
                **payload,
                "quote": "Le passage a été légèrement corrigé.",
                "prefix": "Nouveau contexte ",
            },
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json()["id"], second.json()["id"])
        annotation = Annotation.objects.get()
        self.assertEqual(
            annotation.quote,
            "Le passage a été légèrement corrigé.",
        )
        self.assertEqual(annotation.prefix, "Nouveau contexte ")

    def test_partial_overlap_expands_and_merges_the_highlight(self):
        partial = {
            **self.selection,
            "kind": AnnotationKind.HIGHLIGHT,
            "quote": "nuancer cette",
            "start_offset": "32",
            "end_offset": "45",
        }
        first = self.client.post(reverse("study:annotation_create"), partial)
        annotation = Annotation.objects.get()
        annotation.study_later = True
        annotation.save(update_fields=["study_later", "updated_at"])

        expanded = self.client.post(
            reverse("study:annotation_create"),
            {
                **self.selection,
                "kind": AnnotationKind.HIGHLIGHT,
                "overlap_ids": str(annotation.id),
                "overlap_revisions": json.dumps(
                    {str(annotation.id): annotation.updated_at.isoformat()}
                ),
            },
        )

        self.assertEqual(first.status_code, 201)
        self.assertEqual(expanded.status_code, 200)
        self.assertEqual(expanded.json()["id"], first.json()["id"])
        self.assertEqual(expanded.json()["removed_ids"], [])
        self.assertEqual(
            expanded.json()["delete_url"],
            reverse("study:annotation_delete", args=[annotation.id]),
        )
        annotation.refresh_from_db()
        self.assertEqual(annotation.quote, self.selection["quote"])
        self.assertEqual(annotation.start_offset, 24)
        self.assertEqual(annotation.end_offset, 58)
        self.assertTrue(annotation.study_later)

        restored = self.client.get(
            reverse("study:annotations_for_source"),
            {"source_path": self.source_path},
        ).json()["highlights"]
        self.assertEqual(len(restored), 1)
        self.assertEqual(
            restored[0]["delete_url"],
            reverse("study:annotation_delete", args=[annotation.id]),
        )

    def test_expanding_across_highlights_merges_them(self):
        first = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.HIGHLIGHT,
            quote="Il faut",
            source_path=self.source_path,
            start_offset=24,
            end_offset=31,
        )
        second = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.HIGHLIGHT,
            quote="nuancer",
            source_path=self.source_path,
            start_offset=32,
            end_offset=39,
            study_later=True,
        )

        response = self.client.post(
            reverse("study:annotation_create"),
            {
                **self.selection,
                "kind": AnnotationKind.HIGHLIGHT,
                "overlap_ids": f"{first.id},{second.id}",
                "overlap_revisions": json.dumps(
                    {
                        str(first.id): first.updated_at.isoformat(),
                        str(second.id): second.updated_at.isoformat(),
                    }
                ),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], second.id)
        self.assertEqual(response.json()["removed_ids"], [first.id])
        merged = Annotation.objects.get()
        self.assertEqual(merged.quote, self.selection["quote"])
        self.assertTrue(merged.study_later)

    def test_resolved_overlap_ids_override_stale_offsets(self):
        resolved = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.HIGHLIGHT,
            quote="Passage déplacé",
            source_path=self.source_path,
            start_offset=100,
            end_offset=115,
        )
        stale_collision = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.HIGHLIGHT,
            quote="Autre passage déplacé",
            source_path=self.source_path,
            start_offset=30,
            end_offset=42,
        )

        response = self.client.post(
            reverse("study:annotation_create"),
            {
                **self.selection,
                "kind": AnnotationKind.HIGHLIGHT,
                "overlap_ids": str(resolved.id),
                "overlap_revisions": json.dumps(
                    {str(resolved.id): resolved.updated_at.isoformat()}
                ),
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["id"], resolved.id)
        self.assertEqual(response.json()["removed_ids"], [])
        resolved.refresh_from_db()
        self.assertEqual(resolved.start_offset, 24)
        self.assertEqual(resolved.end_offset, 58)
        self.assertTrue(
            Annotation.objects.filter(pk=stale_collision.id).exists()
        )

    def test_resolved_ids_do_not_overwrite_exact_stale_collision(self):
        resolved = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.HIGHLIGHT,
            quote="Passage déplacé",
            source_path=self.source_path,
            start_offset=100,
            end_offset=115,
        )
        stale_collision = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.HIGHLIGHT,
            quote="Autre passage déplacé",
            source_path=self.source_path,
            start_offset=24,
            end_offset=58,
        )

        response = self.client.post(
            reverse("study:annotation_create"),
            {
                **self.selection,
                "kind": AnnotationKind.HIGHLIGHT,
                "overlap_ids": str(resolved.id),
                "overlap_revisions": json.dumps(
                    {str(resolved.id): resolved.updated_at.isoformat()}
                ),
            },
        )

        self.assertEqual(response.status_code, 409)
        self.assertIn("passage en conflit", response.json()["error"])
        resolved.refresh_from_db()
        stale_collision.refresh_from_db()
        self.assertEqual(resolved.start_offset, 100)
        self.assertEqual(resolved.end_offset, 115)
        self.assertEqual(stale_collision.quote, "Autre passage déplacé")

    def test_stale_expansion_cannot_overwrite_a_concurrent_expansion(self):
        highlight = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.HIGHLIGHT,
            quote="nuancer cette",
            source_path=self.source_path,
            start_offset=32,
            end_offset=45,
        )
        saved = self.client.get(
            reverse("study:annotations_for_source"),
            {"source_path": self.source_path},
        ).json()["highlights"][0]
        revisions = json.dumps({str(highlight.id): saved["revision"]})

        first = self.client.post(
            reverse("study:annotation_create"),
            {
                **self.selection,
                "kind": AnnotationKind.HIGHLIGHT,
                "quote": "Il faut nuancer cette",
                "end_offset": "45",
                "overlap_ids": str(highlight.id),
                "overlap_revisions": revisions,
            },
        )
        stale = self.client.post(
            reverse("study:annotation_create"),
            {
                **self.selection,
                "kind": AnnotationKind.HIGHLIGHT,
                "quote": "nuancer cette affirmation.",
                "start_offset": "32",
                "overlap_ids": str(highlight.id),
                "overlap_revisions": revisions,
            },
        )

        self.assertEqual(first.status_code, 200)
        self.assertEqual(stale.status_code, 409)
        self.assertIn("autre onglet", stale.json()["error"])
        highlight.refresh_from_db()
        self.assertEqual(highlight.start_offset, 24)
        self.assertEqual(highlight.end_offset, 45)

    def test_prompt_aliases_share_saved_highlights(self):
        response = factories.make_response(
            theme=factories.make_theme("shared-response", task=self.task)
        )
        canonical = response.prompts.get()
        alias = Prompt.objects.create(
            response=response,
            content_key="test-prompt:shared-response-alias",
            theme=canonical.theme,
            family=canonical.family,
            number=canonical.number + 1,
            text="Sujet équivalent ?",
        )
        canonical_path = prompt_detail_url(canonical)
        alias_path = prompt_detail_url(alias)
        highlight = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.HIGHLIGHT,
            quote="Texte inchangé",
            source_path=alias_path + "?saved=1",
            start_offset=100,
            end_offset=115,
        )

        restored = self.client.get(
            reverse("study:annotations_for_source"),
            {"source_path": canonical_path},
        ).json()["highlights"]

        self.assertNotEqual(canonical_path, alias_path)
        self.assertEqual([item["id"] for item in restored], [highlight.id])

    def test_annotation_validation_rejects_empty_or_external_selection(self):
        empty = self.client.post(
            reverse("study:annotation_create"),
            {**self.selection, "kind": AnnotationKind.NOTE, "quote": "   "},
        )
        self.assertEqual(empty.status_code, 400)

        external = self.client.post(
            reverse("study:annotation_create"),
            {
                **self.selection,
                "kind": AnnotationKind.HIGHLIGHT,
                "source_path": "https://example.com/stolen",
            },
        )
        self.assertEqual(external.status_code, 400)
        self.assertFalse(Annotation.objects.exists())

        invalid_source_key = self.client.post(
            reverse("study:annotation_create"),
            {
                **self.selection,
                "kind": AnnotationKind.HIGHLIGHT,
                "source_key": "<script>",
            },
        )
        self.assertEqual(invalid_source_key.status_code, 400)
        self.assertFalse(Annotation.objects.exists())

    def test_note_can_be_updated_and_highlight_deleted(self):
        note = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            body="Première version",
        )
        highlight = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.HIGHLIGHT,
            quote="Texte surligné",
            source_path=self.source_path,
            start_offset=1,
            end_offset=15,
        )
        detail_url = self.task_notes_url

        response = self.client.post(
            reverse("study:annotation_update", args=[note.id]),
            {
                "title": "Version finale",
                "body": "Note corrigée",
                "next": detail_url,
            },
        )
        self.assertRedirects(response, detail_url + f"#note-{note.id}")
        note.refresh_from_db()
        self.assertEqual(note.title, "Version finale")
        self.assertEqual(note.body, "Note corrigée")

        response = self.client.post(
            reverse("study:annotation_update", args=[note.id]),
            {"title": "", "body": "", "next": detail_url},
            HTTP_X_REQUESTED_WITH="fetch",
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("error", response.json())

        response = self.client.post(
            reverse("study:annotation_update", args=[note.id]),
            {
                "title": "Version via dialogue",
                "body": "Note enregistrée sans quitter la fenêtre.",
                "next": detail_url,
            },
            HTTP_X_REQUESTED_WITH="fetch",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json()["redirect_url"],
            detail_url + f"#note-{note.id}",
        )
        note.refresh_from_db()
        self.assertEqual(note.title, "Version via dialogue")
        self.assertEqual(note.body, "Note enregistrée sans quitter la fenêtre.")

        response = self.client.post(
            reverse("study:annotation_delete", args=[highlight.id]),
            {"next": detail_url},
        )
        self.assertRedirects(response, detail_url)
        self.assertFalse(Annotation.objects.filter(pk=highlight.id).exists())

    def test_page_annotation_context_does_not_misclassify_dashboard(self):
        dashboard = self.client.get(reverse("study:dashboard"))
        self.assertContains(dashboard, 'data-annotation-task-id=""')

        task_page = self.client.get(self.source_path)
        self.assertContains(
            task_page,
            f'data-annotation-task-id="{self.task.id}"',
        )

    def test_private_annotation_search_filters_content_and_kind(self):
        matching_note = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            title="Connecteurs",
            body="Employer cependant pour nuancer.",
            study_later=True,
        )
        Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.HIGHLIGHT,
            quote="Cependant, cette difficulté n'est pas une fatalité.",
            source_path=self.source_path,
            start_offset=1,
            end_offset=53,
        )
        Annotation.objects.create(
            user=self.other,
            task=self.task,
            kind=AnnotationKind.NOTE,
            body="Cependant, ceci est privé.",
        )

        response = self.client.get(
            reverse("study:annotation_search"),
            {"q": "cependant", "kind": "note", "study": "1"},
        )

        self.assertEqual(response.context["result_count"], 1)
        self.assertContains(response, matching_note.body)
        self.assertNotContains(response, "cette difficulté")
        self.assertNotContains(response, "ceci est privé")

    def test_annotations_can_be_marked_and_studied_by_task(self):
        note = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            title="Nuance",
            body="Le mot toujours est trop fort.",
        )
        other_task = factories.make_task(
            part=factories.make_part(slug="ee"),
            slug="tache-1",
        )
        other_note = Annotation.objects.create(
            user=self.user,
            task=other_task,
            kind=AnnotationKind.NOTE,
            body="Une autre tâche.",
            study_later=True,
        )

        detail_url = self.task_notes_url
        response = self.client.post(
            reverse("study:annotation_study_toggle", args=[note.id]),
            {"study_later": "1", "next": detail_url},
        )
        self.assertRedirects(response, detail_url)
        note.refresh_from_db()
        self.assertTrue(note.study_later)

        study = self.client.get(
            reverse(
                "study:task_annotation_study",
                args=[self.part.slug, self.task.slug],
            )
        )
        self.assertContains(study, "Le mot toujours est trop fort.")
        self.assertNotContains(study, other_note.body)
        self.assertContains(study, "data-annotation-study")

        self.client.force_login(self.other)
        self.assertEqual(
            self.client.post(
                reverse("study:annotation_study_toggle", args=[note.id]),
                {"study_later": "0"},
            ).status_code,
            404,
        )
        self.assertNotContains(
            self.client.get(reverse("study:annotation_study")),
            note.body,
        )

    def test_flashcards_follow_the_current_scope_query_status_and_tab(self):
        new_note = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            title="Nouvelle",
            body="Contenu cible nouveau.",
        )
        done_note = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            title="Terminée",
            body="Contenu cible terminé.",
            completed_at=timezone.now(),
        )
        unrelated_note = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            body="Contenu sans rapport.",
        )
        quoted_note = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            quote="Passage cible sélectionné.",
            body="Contenu cible annoté.",
        )
        queued_highlight = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.HIGHLIGHT,
            quote="Passage cible à revoir.",
            source_path=self.source_path,
            start_offset=3,
            end_offset=21,
            study_later=True,
        )
        private_note = Annotation.objects.create(
            user=self.other,
            task=self.task,
            kind=AnnotationKind.NOTE,
            body="Contenu cible privé.",
        )
        task_study_url = reverse(
            "study:task_annotation_study",
            args=[self.part.slug, self.task.slug],
        )

        notes_page = self.client.get(
            self.task_notes_url,
            {"q": "cible", "status": "todo", "tab": "notes"},
        )
        self.assertEqual(
            notes_page.context["flashcard_url"],
            (
                f"{task_study_url}"
                "?mode=all&tab=notes&q=cible&status=todo"
            ),
        )
        self.assertNotContains(notes_page, "?item=")
        # One node per annotation, so one read control each.
        self.assertContains(
            notes_page,
            f'data-read-aloud-key="{new_note.pk}"',
            count=1,
        )
        self.assertContains(
            notes_page,
            f'data-read-aloud-key="{quoted_note.pk}"',
            count=1,
        )
        self.assertNotContains(notes_page, done_note.body)

        highlights_page = self.client.get(
            self.task_notes_url,
            {"q": "cible", "status": "study", "tab": "highlights"},
        )
        self.assertEqual(
            highlights_page.context["flashcard_url"],
            (
                f"{task_study_url}"
                "?mode=all&tab=highlights&q=cible&status=study"
            ),
        )
        self.assertContains(
            highlights_page,
            f'data-read-aloud-key="{queued_highlight.pk}"',
            count=1,
        )

        todo_deck = self.client.get(
            task_study_url,
            {
                "mode": "all",
                "tab": "notes",
                "q": "cible",
                "status": "todo",
            },
        )
        self.assertEqual(todo_deck.context["study_mode"], "all")
        self.assertEqual(
            todo_deck.context["back_url"],
            self.task_notes_url + "?tab=notes&q=cible&status=todo",
        )
        self.assertContains(todo_deck, new_note.body)
        self.assertNotContains(todo_deck, done_note.body)
        self.assertNotContains(todo_deck, unrelated_note.body)
        self.assertNotContains(todo_deck, queued_highlight.quote)
        self.assertNotContains(todo_deck, private_note.body)

        done_deck = self.client.get(
            task_study_url,
            {
                "mode": "all",
                "tab": "notes",
                "q": "cible",
                "status": "done",
            },
        )
        self.assertContains(done_deck, done_note.body)
        self.assertNotContains(done_deck, new_note.body)

        highlight_deck = self.client.get(
            task_study_url,
            {
                "mode": "all",
                "tab": "highlights",
                "q": "cible",
                "status": "study",
            },
        )
        self.assertContains(highlight_deck, queued_highlight.quote)
        self.assertNotContains(highlight_deck, new_note.body)

        queue = self.client.get(task_study_url)
        self.assertEqual(queue.context["study_mode"], "queue")
        self.assertNotContains(queue, new_note.body)
        self.assertNotContains(queue, done_note.body)
        self.assertContains(queue, queued_highlight.quote)

        self.assertEqual(
            self.client.get(
                reverse("study:annotation_study"),
                {"item": new_note.pk},
            ).status_code,
            404,
        )

    def test_selected_note_uses_selection_as_front_and_note_as_back(self):
        Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            quote="séance",
            body="showing",
            study_later=True,
        )

        response = self.client.get(reverse("study:annotation_study"))
        html = response.content.decode()
        front = html.split("data-study-front>", 1)[1].split("</div>", 1)[0]
        back = html.split("data-study-back>", 1)[1].split("</div>", 1)[0]

        self.assertIn("séance", front)
        self.assertNotIn("showing", front)
        self.assertIn("showing", back)
        self.assertNotIn("séance", back)
        self.assertContains(
            response,
            'data-flashcard-order="back"',
        )
        self.assertContains(response, "data-flashcard-deck")
        self.assertContains(response, "data-flashcard-card")
        self.assertContains(response, "data-read-aloud")

    def test_study_deck_uses_the_shared_flashcard_standard(self):
        Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            body="D\u00e9cision \u00e0 m\u00e9moriser.",
            study_later=True,
        )

        response = self.client.get(reverse("study:annotation_study"))

        for hook in FLASHCARD_DECK_HOOKS:
            with self.subTest(hook=hook):
                self.assertContains(response, hook)
        # The Notes deck keeps its own study hooks on top of the standard.
        self.assertContains(response, "data-study-previous")
        self.assertContains(response, "data-study-reveal")
        self.assertContains(response, "data-study-next")
        self.assertContains(response, "data-study-progress")
        self.assertContains(response, "data-study-done")
        self.assertContains(response, "flashcard-deck__actions")

    def test_study_decisions_update_the_queue_without_a_redirect(self):
        note = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            body="Décision à mémoriser.",
            study_later=True,
        )
        page = self.client.get(reverse("study:annotation_study"))
        # The deck only ever exposes Précédente / Retourner / Suivante;
        # grading happens with the per-card actions.
        self.assertContains(page, "data-study-previous")
        self.assertContains(page, "data-study-reveal")
        self.assertContains(page, "data-study-next")
        self.assertNotContains(page, "Je le connais")
        self.assertNotContains(page, "À revoir encore")

        learned = self.client.post(
            reverse("study:annotation_study_toggle", args=[note.pk]),
            {"study_later": "0"},
            HTTP_X_REQUESTED_WITH="fetch",
        )

        self.assertEqual(learned.status_code, 200)
        self.assertEqual(
            learned.json(),
            {"study_later": False, "id": note.pk, "kind": "note"},
        )
        note.refresh_from_db()
        self.assertFalse(note.study_later)
        self.assertNotContains(
            self.client.get(reverse("study:annotation_study")),
            note.body,
        )

        keep = self.client.post(
            reverse("study:annotation_study_toggle", args=[note.pk]),
            {"study_later": "1"},
            HTTP_X_REQUESTED_WITH="fetch",
        )
        self.assertEqual(keep.json()["study_later"], True)
        note.refresh_from_db()
        self.assertTrue(note.study_later)

    def test_study_cards_expose_done_and_revisit_actions(self):
        note = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            body="Décision à mémoriser.",
            study_later=True,
        )
        study_url = reverse("study:annotation_study_toggle", args=[note.pk])
        complete_url = reverse(
            "study:annotation_complete_toggle", args=[note.pk]
        )

        page = self.client.get(reverse("study:annotation_study"))

        self.assertContains(page, f'data-study-flag-url="{study_url}"')
        self.assertContains(page, f'data-study-flag-url="{complete_url}"')
        self.assertContains(page, 'data-study-flag="study_later"')
        self.assertContains(page, 'data-study-flag="completed"')
        self.assertContains(page, "Marquer comme terminé")
        self.assertContains(page, "Retirer de l’étude")

        completed = self.client.post(
            complete_url,
            {"completed": "1"},
            HTTP_X_REQUESTED_WITH="fetch",
        )

        self.assertEqual(completed.status_code, 200)
        self.assertEqual(completed.json()["completed"], True)
        note.refresh_from_db()
        self.assertTrue(note.completed)

        marked = self.client.get(reverse("study:annotation_study"))

        self.assertContains(marked, "Marquer comme à faire")

    def test_delete_on_fetch_returns_scope_metadata(self):
        note = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            body="À retirer de la liste.",
            study_later=True,
        )
        response = self.client.post(
            reverse("study:annotation_delete", args=[note.pk]),
            {},
            HTTP_X_REQUESTED_WITH="fetch",
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "deleted": True,
                "id": note.pk,
                "kind": "note",
                "was_study": True,
                "scope": f"task:{self.task.pk}",
            },
        )
        self.assertFalse(Annotation.objects.filter(pk=note.pk).exists())

    def test_highlight_actions_survive_a_source_key_without_a_sujet(self):
        """``writing-sujet:0`` parses, but no sujet can ever carry that id.

        The progress payload has to stay optional: a highlight captured on
        such a key must still create, delete and redirect cleanly.
        """
        selection = dict(self.selection)
        selection["kind"] = AnnotationKind.HIGHLIGHT
        selection["source_key"] = "writing-sujet:0:personal"

        created = self.client.post(
            reverse("study:annotation_create"),
            selection,
            HTTP_X_REQUESTED_WITH="fetch",
        )

        self.assertEqual(created.status_code, 201)
        self.assertNotIn("writing_sujet_progress", created.json())

        highlight_id = created.json()["id"]
        deleted = self.client.post(
            reverse("study:annotation_delete", args=[highlight_id]),
            HTTP_X_REQUESTED_WITH="fetch",
        )

        self.assertEqual(deleted.status_code, 200)
        self.assertEqual(deleted.json()["deleted"], True)
        self.assertNotIn("writing_sujet_progress", deleted.json())
        self.assertFalse(
            Annotation.objects.filter(pk=highlight_id).exists()
        )

        without_fetch = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.HIGHLIGHT,
            quote="Passage sans sujet réel.",
            source_path=self.source_path,
            source_key="writing-sujet:0:model-2",
            start_offset=0,
            end_offset=24,
        )
        response = self.client.post(
            reverse("study:annotation_delete", args=[without_fetch.pk]),
            {"next": self.task_notes_url},
        )

        self.assertRedirects(
            response,
            self.task_notes_url,
            fetch_redirect_response=False,
        )
        self.assertFalse(
            Annotation.objects.filter(pk=without_fetch.pk).exists()
        )

    def test_delete_on_fetch_reports_comprehension_scope(self):
        note = Annotation.objects.create(
            user=self.user,
            kind=AnnotationKind.NOTE,
            body="Note de compréhension écrite.",
            source_path="/comprehension/ecrite/quelque-chose/",
        )
        response = self.client.post(
            reverse("study:annotation_delete", args=[note.pk]),
            {},
            HTTP_X_REQUESTED_WITH="fetch",
        )
        self.assertEqual(response.json()["scope"], "ecrite")
        self.assertFalse(response.json()["was_study"])

    def test_notes_can_be_marked_complete_and_reverted(self):
        note = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            body="Relire cette tournure.",
        )
        self.assertFalse(note.completed)

        done = self.client.post(
            reverse("study:annotation_complete_toggle", args=[note.id]),
            {"completed": "1", "next": self.task_notes_url},
        )
        self.assertRedirects(done, self.task_notes_url)
        note.refresh_from_db()
        self.assertTrue(note.completed)
        self.assertIsNotNone(note.completed_at)
        self.assertContains(self.client.get(self.task_notes_url), "Terminée")

        undone = self.client.post(
            reverse("study:annotation_complete_toggle", args=[note.id]),
            {"completed": "0", "next": self.task_notes_url},
        )
        self.assertRedirects(undone, self.task_notes_url)
        note.refresh_from_db()
        self.assertFalse(note.completed)
        self.assertIsNone(note.completed_at)

    def test_complete_toggle_returns_json_for_fetch(self):
        note = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            body="Décision à clôturer.",
        )
        marked = self.client.post(
            reverse("study:annotation_complete_toggle", args=[note.pk]),
            {"completed": "1"},
            HTTP_X_REQUESTED_WITH="fetch",
        )
        self.assertEqual(marked.status_code, 200)
        self.assertEqual(
            marked.json(), {"completed": True, "id": note.pk, "kind": "note"}
        )
        note.refresh_from_db()
        self.assertTrue(note.completed)

    def test_complete_toggle_rejects_invalid_value(self):
        note = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            body="Valeur incorrecte.",
        )
        response = self.client.post(
            reverse("study:annotation_complete_toggle", args=[note.pk]),
            {"completed": "oui"},
        )
        self.assertEqual(response.status_code, 400)
        note.refresh_from_db()
        self.assertFalse(note.completed)

    def test_complete_toggle_forbidden_for_other_user(self):
        note = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            body="Note privée.",
        )
        self.client.force_login(self.other)
        self.assertEqual(
            self.client.post(
                reverse("study:annotation_complete_toggle", args=[note.pk]),
                {"completed": "1"},
            ).status_code,
            404,
        )
        note.refresh_from_db()
        self.assertFalse(note.completed)

    def test_status_filter_limits_the_notes_list(self):
        done = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            body="Note terminée.",
            completed_at=timezone.now(),
        )
        todo = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            body="Note à faire.",
        )
        study = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            body="Note à étudier.",
            study_later=True,
        )

        default = self.client.get(self.task_notes_url)
        self.assertEqual(len(default.context["notes"]), 3)
        self.assertEqual(default.context["study_count"], 1)

        done_only = self.client.get(self.task_notes_url, {"status": "done"})
        self.assertEqual(done_only.context["notes"], [done])
        self.assertEqual(done_only.context["status"], "done")
        self.assertEqual(done_only.context["study_count"], 1)

        todo_only = self.client.get(self.task_notes_url, {"status": "todo"})
        self.assertEqual(todo_only.context["notes"], [todo])

        study_only = self.client.get(self.task_notes_url, {"status": "study"})
        self.assertEqual(study_only.context["notes"], [study])

    def test_todo_status_excludes_study_later_notes(self):
        plain = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            body="Sans statut.",
        )
        Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            body="À étudier.",
            study_later=True,
        )
        Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
            body="Terminée.",
            completed_at=timezone.now(),
        )
        todo_only = self.client.get(self.task_notes_url, {"status": "todo"})
        self.assertEqual(todo_only.context["notes"], [plain])

    def test_comprehension_notes_are_separated_from_generales(self):
        general = Annotation.objects.create(
            user=self.user,
            kind=AnnotationKind.NOTE,
            body="Note générale.",
            source_path="/vocabulaire/",
        )
        ecrite = Annotation.objects.create(
            user=self.user,
            kind=AnnotationKind.NOTE,
            body="Note CE.",
            source_path="/comprehension/ecrite/tests/t1/tentatives/1/questions/2/",
        )
        orale = Annotation.objects.create(
            user=self.user,
            kind=AnnotationKind.NOTE,
            body="Note CO.",
            source_path="/comprehension/orale/tests/t1/tentatives/1/questions/2/",
        )

        general_page = self.client.get(self.general_notes_url)
        self.assertEqual(general_page.context["notes"], [general])
        self.assertEqual(general_page.context["general_count"], 1)
        self.assertEqual(general_page.context["ce_count"], 1)
        self.assertEqual(general_page.context["co_count"], 1)
        self.assertIsNone(general_page.context["comprehension"])

        ce_page = self.client.get(
            reverse("study:comprehension_notes", args=["ecrite"])
        )
        self.assertEqual(ce_page.context["notes"], [ecrite])
        self.assertEqual(ce_page.context["comprehension"], "ecrite")
        self.assertEqual(ce_page.context["scope_title"], "Compréhension écrite")

        co_page = self.client.get(
            reverse("study:comprehension_notes", args=["orale"])
        )
        self.assertEqual(co_page.context["notes"], [orale])
        self.assertEqual(co_page.context["comprehension"], "orale")

        aggregate = self.client.get(reverse("study:notes_overview"))
        self.assertCountEqual(
            aggregate.context["notes"], [general, ecrite, orale]
        )

    def test_personal_notes_are_separated_from_generales_and_flashcards(self):
        personal = Annotation.objects.create(
            user=self.user,
            kind=AnnotationKind.NOTE,
            title="Objectifs",
            body="Travailler le vocabulaire chaque matin.",
            study_later=True,
        )
        general = Annotation.objects.create(
            user=self.user,
            kind=AnnotationKind.NOTE,
            quote="Expression relevée",
            body="Note liée à une source générale.",
            source_path="/vocabulaire/",
        )

        personal_page = self.client.get(self.custom_notes_url)
        general_page = self.client.get(self.general_notes_url)

        self.assertEqual(personal_page.context["notes"], [personal])
        self.assertEqual(personal_page.context["highlights"], [])
        self.assertEqual(personal_page.context["custom_count"], 1)
        self.assertEqual(personal_page.context["general_count"], 1)
        self.assertEqual(personal_page.context["scope_title"], "Notes personnelles")
        self.assertTrue(personal_page.context["custom"])
        self.assertContains(personal_page, "Personnelles")
        self.assertNotContains(personal_page, 'id="highlights-tab"')
        self.assertEqual(general_page.context["notes"], [general])
        self.assertNotContains(general_page, personal.body)

        study_url = reverse("study:custom_annotation_study")
        self.assertEqual(
            personal_page.context["flashcard_url"],
            study_url + "?mode=all&tab=notes",
        )
        deck = self.client.get(
            study_url,
            {"mode": "all", "tab": "highlights"},
        )
        self.assertEqual(deck.context["items"], [personal])
        self.assertEqual(deck.context["scope_title"], "Notes personnelles")
        self.assertContains(deck, personal.body)
        self.assertNotContains(deck, general.body)

        search = self.client.get(
            reverse("study:annotation_search"),
            {"q": "Travailler"},
        )
        self.assertEqual(search.context["results"][0].scope_label, "Notes personnelles")
        self.assertContains(search, "Notes personnelles")

    def test_personal_note_creation_preserves_personal_filters(self):
        return_url = (
            self.custom_notes_url
            + "?q=objectif&status=todo&tab=notes"
        )

        response = self.client.post(
            self.custom_notes_url,
            {
                "title": "Objectif",
                "body": "Réviser chaque jour.",
                "next": return_url,
            },
        )

        note = Annotation.objects.get(title="Objectif")
        self.assertRedirects(
            response,
            return_url + f"#note-{note.pk}",
            fetch_redirect_response=False,
        )

    def test_comprehension_notes_reject_unknown_mode(self):
        response = self.client.get(
            reverse("study:comprehension_notes", args=["invalide"])
        )
        self.assertEqual(response.status_code, 404)

    def test_status_filter_is_preserved_when_switching_tabs(self):
        response = self.client.get(
            self.task_notes_url, {"status": "done", "q": "note", "tab": "highlights"}
        )
        self.assertIn("status=done", response.context["tab_url_prefix"])
        self.assertIn("q=note", response.context["tab_url_prefix"])


class TranslateSelectionTests(TestCase):
    def setUp(self):
        self.user = factories.make_user("translate-owner")
        self.client.force_login(self.user)
        self.url = reverse("study:translate_selection")
        cache.clear()

    def test_translation_is_unavailable_until_an_endpoint_is_configured(self):
        with override_settings(TRANSLATION_API_URL=""):
            response = self.client.post(self.url, {"text": "Bonjour"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["error"], "not_configured")

    def test_translation_rejects_empty_and_oversized_text(self):
        with override_settings(TRANSLATION_API_URL="http://translate.test/translate"):
            empty = self.client.post(self.url, {"text": "   "})
            oversized = self.client.post(self.url, {"text": "a" * 2001})
        self.assertEqual(empty.status_code, 400)
        self.assertEqual(oversized.status_code, 413)

    def test_translation_proxies_the_configured_endpoint_and_caches_it(self):
        calls = []

        class FakeResponse:
            def read(self):
                return json.dumps({"translatedText": "Hello"}).encode("utf-8")

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_urlopen(request, timeout=None):
            calls.append(json.loads(request.data.decode("utf-8")))
            return FakeResponse()

        with override_settings(
            TRANSLATION_API_URL="http://translate.test/translate",
            TRANSLATION_API_KEY="secret",
        ), mock.patch("study.views.notes.urllib.request.urlopen", fake_urlopen):
            first = self.client.post(self.url, {"text": "Bonjour"})
            second = self.client.post(self.url, {"text": "Bonjour"})

        self.assertEqual(first.json()["translation"], "Hello")
        self.assertTrue(second.json()["cached"])
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0]["source"], "fr")
        self.assertEqual(calls[0]["target"], "en")
        self.assertEqual(calls[0]["api_key"], "secret")


class NotesScopeSemanticsTests(TestCase):
    """Counts, grouping and labels the folder pages promise."""

    def setUp(self):
        self.user = factories.make_user("notes-scope-owner")
        self.other = factories.make_user("notes-scope-other")
        self.client.force_login(self.user)
        self.part = factories.make_part(slug="eo")
        self.task = factories.make_task(part=self.part, slug="tache-3")
        self.retired = factories.make_task(part=self.part, slug="tache-4")
        self.retired.is_active = False
        self.retired.save(update_fields=["is_active"])

    def _note(self, **values):
        values.setdefault("kind", AnnotationKind.NOTE)
        values.setdefault("body", "Contenu de la note.")
        return Annotation.objects.create(user=self.user, **values)

    def _highlight(self, **values):
        values.setdefault("kind", AnnotationKind.HIGHLIGHT)
        values.setdefault("quote", "Passage relevé.")
        values.setdefault("start_offset", 0)
        values.setdefault("end_offset", 12)
        values.setdefault("source_path", "/vocabulaire/")
        return Annotation.objects.create(user=self.user, **values)

    def test_folder_counts_and_labels_cover_every_bucket(self):
        task_note = self._note(task=self.task, body="Note de tâche.")
        retired_note = self._note(task=self.retired, body="Note archivée.")
        general = self._note(body="Note générale.", source_path="/vocabulaire/")
        general_highlight = self._highlight()
        custom = self._note(body="Note personnelle.")
        ecrite = self._note(
            body="Note CE.",
            source_path="/comprehension/ecrite/tests/t1/",
        )
        orale = self._note(
            body="Note CO.",
            source_path="/comprehension/orale/tests/t1/",
        )
        Annotation.objects.create(
            user=self.other,
            task=self.task,
            kind=AnnotationKind.NOTE,
            body="Note d'un autre apprenant.",
        )

        page = self.client.get(reverse("study:general_notes"))

        self.assertEqual(page.context["general_count"], 2)
        self.assertEqual(page.context["custom_count"], 1)
        self.assertEqual(page.context["ce_count"], 1)
        self.assertEqual(page.context["co_count"], 1)
        self.assertEqual(page.context["notes"], [general])
        self.assertEqual(page.context["highlights"], [general_highlight])
        self.assertEqual(
            [item.scope_label for item in page.context["notes"]],
            ["Notes générales"],
        )
        counts = {
            item["task"].pk: item["count"]
            for item in page.context["task_filters"]
        }
        # A retired task keeps its folder while it still owns annotations.
        self.assertEqual(counts[self.task.pk], 1)
        self.assertEqual(counts[self.retired.pk], 1)

        labels = {
            "custom": (reverse("study:custom_notes"), "Notes personnelles"),
            "ecrite": (
                reverse("study:comprehension_notes", args=["ecrite"]),
                "Compréhension écrite",
            ),
            "orale": (
                reverse("study:comprehension_notes", args=["orale"]),
                "Compréhension orale",
            ),
        }
        for key, (url, label) in labels.items():
            with self.subTest(scope=key):
                scoped = self.client.get(url)
                self.assertEqual(
                    [item.scope_label for item in scoped.context["notes"]],
                    [label],
                )

        task_page = self.client.get(
            reverse("study:task_notes", args=[self.part.slug, self.task.slug])
        )
        self.assertEqual(task_page.context["notes"], [task_note])
        self.assertEqual(
            task_page.context["notes"][0].scope_label,
            f"{self.part.short_name} · {self.task.name}",
        )

        aggregate = self.client.get(reverse("study:notes_overview"))
        self.assertCountEqual(
            [item.scope_label for item in aggregate.context["notes"]],
            [
                f"{self.part.short_name} · {self.task.name}",
                f"{self.part.short_name} · {self.retired.name}",
                "Notes générales",
                "Notes personnelles",
                "Compréhension écrite",
                "Compréhension orale",
            ],
        )
        self.assertEqual(
            [item.pk for item in aggregate.context["notes"]],
            [
                orale.pk,
                ecrite.pk,
                custom.pk,
                general.pk,
                retired_note.pk,
                task_note.pk,
            ],
        )

    def test_personal_folder_never_lists_highlights(self):
        self._note(body="Note personnelle.")
        self._highlight()

        page = self.client.get(reverse("study:custom_notes"))

        self.assertEqual(page.context["highlights"], [])
        self.assertEqual(len(page.context["notes"]), 1)
        self.assertNotContains(page, 'id="highlights-tab"')

    def test_study_count_covers_the_folder_under_every_status_filter(self):
        self._note(task=self.task, body="À étudier.", study_later=True)
        self._note(
            task=self.task,
            body="Terminée.",
            completed_at=timezone.now(),
        )
        self._note(task=self.task, body="À faire.")
        self._highlight(task=self.task, study_later=True)

        url = reverse(
            "study:task_notes", args=[self.part.slug, self.task.slug]
        )
        for status in ("", "todo", "done", "study"):
            with self.subTest(status=status):
                page = self.client.get(url, {"status": status} if status else {})
                self.assertEqual(page.context["study_count"], 2)

        filtered = self.client.get(url, {"q": "étudier"})
        self.assertEqual(filtered.context["study_count"], 1)

    def test_notes_and_highlights_keep_their_capture_order(self):
        now = timezone.now()
        older_note = self._note(
            task=self.task,
            body="Ancienne note.",
            created_at=now - timezone.timedelta(days=2),
        )
        newer_note = self._note(
            task=self.task,
            body="Nouvelle note.",
            created_at=now,
        )
        older_highlight = self._highlight(
            task=self.task,
            created_at=now - timezone.timedelta(days=3),
        )
        newer_highlight = self._highlight(
            task=self.task,
            start_offset=20,
            end_offset=40,
            created_at=now - timezone.timedelta(hours=1),
        )

        page = self.client.get(
            reverse("study:task_notes", args=[self.part.slug, self.task.slug])
        )

        self.assertEqual(page.context["notes"], [newer_note, older_note])
        self.assertEqual(
            page.context["highlights"],
            [newer_highlight, older_highlight],
        )
        self.assertEqual(
            [section["key"] for section in page.context["notes_sections"]],
            ["today", "week"],
        )

    def test_search_result_count_is_exact_on_both_sides_of_the_limit(self):
        Annotation.objects.bulk_create(
            Annotation(
                user=self.user,
                task=self.task,
                kind=AnnotationKind.NOTE,
                body=f"Recherche exacte {index}.",
            )
            for index in range(100)
        )
        url = reverse("study:annotation_search")

        exact = self.client.get(url, {"q": "Recherche exacte"})
        self.assertEqual(exact.context["result_count"], 100)
        self.assertEqual(len(exact.context["results"]), 100)
        self.assertFalse(exact.context["result_limit_reached"])
        self.assertNotContains(exact, "Affinez votre recherche")

        Annotation.objects.bulk_create(
            Annotation(
                user=self.user,
                task=self.task,
                kind=AnnotationKind.NOTE,
                body=f"Recherche exacte {index}.",
            )
            for index in range(100, 137)
        )
        truncated = self.client.get(url, {"q": "Recherche exacte"})
        self.assertEqual(truncated.context["result_count"], 137)
        self.assertEqual(len(truncated.context["results"]), 100)
        self.assertTrue(truncated.context["result_limit_reached"])
        self.assertContains(truncated, "Affinez votre recherche")

    def test_search_task_options_include_retired_annotated_tasks(self):
        self._note(task=self.retired, body="Note archivée.")
        unused = factories.make_task(part=self.part, slug="tache-5")
        Annotation.objects.create(
            user=self.other,
            task=unused,
            kind=AnnotationKind.NOTE,
            body="Note d'un autre apprenant.",
        )

        page = self.client.get(reverse("study:annotation_search"))

        options = list(page.context["task_options"])
        self.assertEqual([task.pk for task in options], [self.retired.pk])
        self.assertContains(
            page,
            f"{self.retired.part.short_name} · {self.retired.name}",
        )

    def test_search_filters_stay_private_to_their_owner(self):
        mine = self._note(task=self.task, body="Connecteur cependant.")
        Annotation.objects.create(
            user=self.other,
            task=self.task,
            kind=AnnotationKind.NOTE,
            body="Connecteur cependant, mais privé.",
        )

        page = self.client.get(
            reverse("study:annotation_search"), {"q": "cependant"}
        )

        self.assertEqual([item.pk for item in page.context["results"]], [mine.pk])
        self.assertEqual(page.context["result_count"], 1)


class NotesNavigationTests(TestCase):
    """The shell highlights Notes everywhere the section actually goes."""

    def setUp(self):
        self.user = factories.make_user("notes-nav-owner")
        self.client.force_login(self.user)
        self.part = factories.make_part(slug="eo")
        self.task = factories.make_task(part=self.part, slug="tache-3")

    def test_every_notes_route_lights_up_the_notes_tab(self):
        task_args = [self.part.slug, self.task.slug]
        urls = [
            reverse("study:notes_overview"),
            reverse("study:general_notes"),
            reverse("study:custom_notes"),
            reverse("study:comprehension_notes", args=["ecrite"]),
            reverse("study:comprehension_notes", args=["orale"]),
            reverse("study:task_notes", args=task_args),
            reverse("study:annotation_search"),
            reverse("study:annotation_study"),
            reverse("study:general_annotation_study"),
            reverse("study:custom_annotation_study"),
            reverse("study:comprehension_annotation_study", args=["ecrite"]),
            reverse("study:task_annotation_study", args=task_args),
        ]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.context["active_nav_area"], "notes")
                self.assertContains(response, 'data-active-area="notes"')

    def test_task_notes_shell_shares_the_task_the_view_resolved(self):
        response = self.client.get(
            reverse(
                "study:task_notes", args=[self.part.slug, self.task.slug]
            )
        )

        self.assertEqual(response.context["annotation_task"], self.task)
        self.assertEqual(response.context["content_task"], self.task)
        self.assertEqual(response.context["task"], self.task)

    def test_search_task_filter_is_not_read_as_a_content_scope(self):
        response = self.client.get(
            reverse("study:annotation_search"), {"task": str(self.task.pk)}
        )

        self.assertIsNone(response.context["content_task"])
        self.assertEqual(response.context["selected_task_id"], self.task.pk)

    def test_shell_reports_no_scope_for_anonymous_and_foreign_pages(self):
        self.client.logout()
        response = self.client.get(reverse("study:login"))

        self.assertEqual(response.context["active_nav_area"], "")
        self.assertIsNone(response.context["content_task"])


class NotesQueryBudgetTests(TestCase):
    """Notes pages cost the same whatever a learner has collected.

    The budgets are deliberately absolute: a page that grows a query per note,
    per task or per folder is the regression these guard against.
    """

    def setUp(self):
        self.user = factories.make_user("notes-budget-owner")
        self.client.force_login(self.user)
        self.part = factories.make_part(slug="eo")
        self.written = factories.make_part(slug="ee")
        self.task = factories.make_task(part=self.part, slug="tache-3")
        self.seed_round = 0

    def _seed(self, *, tasks, per_scope):
        extra = [
            factories.make_task(part=self.written, slug=f"tache-{index}")
            for index in range(1, tasks + 1)
        ]
        self.seed_round += 1
        rows = []
        for index in range(per_scope):
            for task in [self.task, *extra]:
                rows.append(
                    Annotation(
                        user=self.user,
                        task=task,
                        kind=(
                            AnnotationKind.HIGHLIGHT
                            if index % 2
                            else AnnotationKind.NOTE
                        ),
                        body=f"Note {task.slug} {index}.",
                        quote="Passage relevé." if index % 2 else "",
                        source_path=(
                            f"/expression/{task.part.slug}/{task.slug}/"
                        ),
                        source_key=f"seed:{self.seed_round}",
                        start_offset=index if index % 2 else None,
                        end_offset=index + 10 if index % 2 else None,
                        study_later=index % 3 == 0,
                    )
                )
            rows.append(
                Annotation(
                    user=self.user,
                    kind=AnnotationKind.NOTE,
                    body=f"Note personnelle {index}.",
                )
            )
            for mode in ("ecrite", "orale"):
                rows.append(
                    Annotation(
                        user=self.user,
                        kind=AnnotationKind.NOTE,
                        body=f"Note {mode} {index}.",
                        source_path=f"/comprehension/{mode}/tests/t1/",
                    )
                )
            rows.append(
                Annotation(
                    user=self.user,
                    kind=AnnotationKind.NOTE,
                    body=f"Note générale {index}.",
                    source_path="/vocabulaire/",
                )
            )
        Annotation.objects.bulk_create(rows)

    def _pages(self):
        task_args = [self.part.slug, self.task.slug]
        return {
            "notes_overview": reverse("study:notes_overview"),
            "general_notes": reverse("study:general_notes"),
            "custom_notes": reverse("study:custom_notes"),
            "comprehension_notes": reverse(
                "study:comprehension_notes", args=["ecrite"]
            ),
            "task_notes": reverse("study:task_notes", args=task_args),
            "annotation_search": reverse("study:annotation_search"),
            "annotation_study": reverse("study:annotation_study"),
            "task_annotation_study": reverse(
                "study:task_annotation_study", args=task_args
            ),
        }

    def _counts(self):
        results = {}
        for name, url in self._pages().items():
            self.client.get(url)
            with CaptureQueriesContext(connection) as queries:
                response = self.client.get(url)
            results[name] = len(queries.captured_queries)
            self.assertEqual(response.status_code, 200, name)
        return results

    def test_page_cost_is_flat_in_items_and_tasks(self):
        self._seed(tasks=1, per_scope=1)
        small = self._counts()
        self._seed(tasks=5, per_scope=12)
        large = self._counts()

        # Two of every budget below are the session and the signed-in user.
        self.assertEqual(
            large,
            {
                "notes_overview": 5,
                "general_notes": 5,
                "custom_notes": 5,
                "comprehension_notes": 5,
                "task_notes": 6,
                "annotation_search": 5,
                "annotation_study": 3,
                "task_annotation_study": 4,
            },
        )
        # Only the search page moves, and only by the one count it runs once a
        # result set is truncated past its 100-row limit.
        self.assertEqual(small | {"annotation_search": 5}, large)

    def test_status_filtered_folder_costs_one_extra_count_at_most(self):
        self._seed(tasks=2, per_scope=6)
        url = reverse("study:general_notes")

        for status, budget in (("", 5), ("study", 5), ("todo", 6), ("done", 6)):
            with self.subTest(status=status):
                self.client.get(url, {"status": status})
                with CaptureQueriesContext(connection) as queries:
                    self.client.get(url, {"status": status})
                self.assertEqual(len(queries.captured_queries), budget)

    def test_search_only_counts_when_the_result_set_is_truncated(self):
        self._seed(tasks=1, per_scope=4)
        url = reverse("study:annotation_search")

        self.client.get(url, {"q": "personnelle"})
        with CaptureQueriesContext(connection) as small:
            self.client.get(url, {"q": "personnelle"})
        self.assertEqual(len(small.captured_queries), 4)

        Annotation.objects.bulk_create(
            Annotation(
                user=self.user,
                kind=AnnotationKind.NOTE,
                body=f"Note personnelle en masse {index}.",
            )
            for index in range(120)
        )
        self.client.get(url, {"q": "personnelle"})
        with CaptureQueriesContext(connection) as truncated:
            self.client.get(url, {"q": "personnelle"})
        self.assertEqual(len(truncated.captured_queries), 5)

    def test_card_actions_do_not_walk_relations_one_row_at_a_time(self):
        self._seed(tasks=1, per_scope=1)
        note = Annotation.objects.filter(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.NOTE,
        ).first()
        toggle_url = reverse("study:annotation_study_toggle", args=[note.pk])
        complete_url = reverse(
            "study:annotation_complete_toggle", args=[note.pk]
        )
        notes_url = reverse(
            "study:task_notes", args=[self.part.slug, self.task.slug]
        )

        self.client.post(toggle_url, {"study_later": "1"})
        with CaptureQueriesContext(connection) as fallback:
            response = self.client.post(toggle_url, {"study_later": "0"})
        self.assertRedirects(
            response, f"{notes_url}?tab=notes", fetch_redirect_response=False
        )
        self.assertEqual(len(fallback.captured_queries), 4)

        with CaptureQueriesContext(connection) as with_next:
            response = self.client.post(
                complete_url, {"completed": "1", "next": notes_url}
            )
        self.assertRedirects(
            response, notes_url, fetch_redirect_response=False
        )
        self.assertEqual(len(with_next.captured_queries), 4)

        with CaptureQueriesContext(connection) as ajax:
            response = self.client.post(
                complete_url,
                {"completed": "0"},
                HTTP_X_REQUESTED_WITH="fetch",
            )
        self.assertEqual(response.json()["completed"], False)
        self.assertEqual(len(ajax.captured_queries), 4)

    def test_deleting_on_fetch_skips_the_redirect_lookup(self):
        self._seed(tasks=1, per_scope=2)
        highlight = Annotation.objects.filter(
            user=self.user,
            kind=AnnotationKind.HIGHLIGHT,
        ).first()

        with CaptureQueriesContext(connection) as queries:
            response = self.client.post(
                reverse("study:annotation_delete", args=[highlight.pk]),
                HTTP_X_REQUESTED_WITH="fetch",
            )

        self.assertEqual(response.json()["deleted"], True)
        self.assertEqual(
            response.json()["scope"], f"task:{highlight.task_id}"
        )
        self.assertEqual(len(queries.captured_queries), 4)

    def test_shell_adds_no_aggregates_to_a_notes_page(self):
        self._seed(tasks=3, per_scope=5)

        response = self.client.get(reverse("study:general_notes"))

        for removed in (
            "nav_due_total",
            "nav_counts",
            "nav_revisit_count",
            "total_cards",
        ):
            with self.subTest(key=removed):
                self.assertNotIn(removed, response.context)
