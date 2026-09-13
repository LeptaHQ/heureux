from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.db import connection, transaction
from django.db.migrations.executor import MigrationExecutor
from django.test import RequestFactory, SimpleTestCase, TestCase
from django.urls import NoReverseMatch, Resolver404, resolve, reverse
from django.utils import timezone

from study import content_loader as content, queue, srs
from study.account_services import provision_user_study_data
from study.management.commands.import_content import Command, PHRASE_ID_MERGES
from study.models import (
    Annotation, AnnotationKind, Card, CardState, OralStateSnapshot, PersonalResponse,
    Phrase, PhraseTier, Prompt, Rating, Response, ReviewLog, ReviewSession,
)
from study.oral_history import annotation_owners, personal_versions, preferred_personal, save_personal
from study.progress import subject_progress_by_response
from study.routing import prompt_detail_url, subject_group_url
from . import factories


def response_data(response, *, key=None, members=None, group="eo/tache-3/example"):
    prompts = members or list(response.prompts.all())
    return content.ResponseData(
        content_key=key or response.content_key,
        body_hash=response.body_hash,
        theme=response.theme.name,
        family=response.family.name,
        prompt=response.prompt,
        reformulation=response.reformulation,
        position=response.position,
        position_claire=response.position_claire,
        nuance=response.nuance,
        conclusion=response.conclusion,
        body=response.body,
        body_html=response.body_html,
        arguments=[],
        prompts=[
            content.PromptData(
                content_key=prompt.content_key, theme=prompt.theme.name,
                number=prompt.number, text=prompt.text, family=prompt.family.name,
                is_canonical=prompt.content_key == (key or response.content_key),
            )
            for prompt in prompts
        ],
        semantic_group=group,
        semantic_rationale="Explicit fixture partition.",
    )


class OralManifestTests(SimpleTestCase):
    keys = ("culture:p1", "culture:p2", "culture:p3")

    def manifest(self):
        return {
            "version": 1, "task": "eo/tache-3", "groups": [
                {"id": "equivalent", "canonical": self.keys[1],
                 "members": list(self.keys[:2]), "rationale": "Same proposition."},
                {"id": "distinct", "canonical": self.keys[2],
                 "members": [self.keys[2]], "rationale": "Different obligation."},
            ],
        }

    def load(self, payload):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "semantic.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            return content.load_oral_semantic_groups("eo/tache-3", self.keys, path=path)

    def test_partition_includes_singletons_and_nonfirst_canonical(self):
        groups = self.load(self.manifest())
        self.assertEqual(groups[0].canonical, self.keys[1])
        self.assertEqual(groups[1].members, (self.keys[2],))

    def test_rejects_incomplete_duplicate_unknown_and_unordered_partitions(self):
        invalid = []
        data = self.manifest()
        data["groups"].pop()
        invalid.append(data)
        data = self.manifest()
        data["groups"][1]["members"].append(self.keys[0])
        invalid.append(data)
        data = self.manifest()
        data["groups"][0]["members"].reverse()
        invalid.append(data)
        data = self.manifest()
        data["groups"][0]["members"].append("sante:p999")
        invalid.append(data)
        data = self.manifest()
        data["groups"][0]["canonical"] = self.keys[2]
        invalid.append(data)
        for field, value in (("id", "not valid"), ("id", "distinct"), ("rationale", "")):
            data = self.manifest()
            data["groups"][0][field] = value
            invalid.append(data)
        for field, value in (("task", "eo/tache-2"), ("version", True), ("version", 2)):
            data = self.manifest()
            data[field] = value
            invalid.append(data)
        for payload in invalid:
            with self.subTest(payload=payload), self.assertRaises(ValueError):
                self.load(payload)

    def test_missing_manifest_is_not_a_fallback(self):
        with TemporaryDirectory() as directory, self.assertRaises(FileNotFoundError):
            content.load_oral_semantic_groups(
                "eo/tache-3", self.keys, path=Path(directory) / "absent.json",
            )

    def test_published_storage_inventory_remains_complete(self):
        eo2 = content.parse_tache_two_storage_responses()
        eo3 = content.parse_response_storage()
        self.assertEqual((len(eo2), sum(len(row.prompts) for row in eo2)), (175, 348))
        self.assertEqual((len(eo3), sum(len(row.prompts) for row in eo3)), (130, 167))

    def test_semantic_corpora_preserve_all_515_original_models(self):
        for storage, semantic in (
            (content.parse_tache_two_storage_responses(), content.parse_tache_two_responses()),
            (content.parse_response_storage(), content.parse_responses()),
        ):
            originals = {
                prompt.content_key: (prompt.text, content._oral_model_content(response))
                for response in storage for prompt in response.prompts
            }
            actual = {
                prompt.content_key: (prompt.text, prompt.model_content)
                for response in semantic for prompt in response.prompts
            }
            self.assertEqual(actual, originals)
            self.assertEqual(len({response.semantic_group for response in semantic}), len(semantic))
            groups_by_body = {}
            for response in semantic:
                for prompt in response.prompts:
                    groups_by_body.setdefault(prompt.model_content["body_hash"], set()).add(response.content_key)
            self.assertTrue(any(len(groups) > 1 for groups in groups_by_body.values()))
            self.assertTrue(any(
                len({prompt.model_content["body_hash"] for prompt in response.prompts}) > 1
                for response in semantic
            ))


class OralRollingSchemaTests(TestCase):
    def test_0050_workers_can_insert_after_additive_oral_migrations(self):
        user = factories.make_user("old-oral-worker")
        existing = factories.make_spine_card(user=user)
        old_apps = MigrationExecutor(connection).loader.project_state([
            ("study", "0050_course_exposure_projection"),
        ]).apps
        old_personal = old_apps.get_model("study", "PersonalResponse").objects.create(
            user_id=user.pk, response_id=existing.response_id, position="Existing worker",
        )
        self.assertTrue(PersonalResponse.objects.get(pk=old_personal.pk).is_active)
        old_response = old_apps.get_model("study", "Response").objects.create(
            content_key="old-worker-response", body_hash="0" * 64,
            theme_id=existing.response.theme_id, family_id=existing.response.family_id,
            prompt="Old worker source", body="Original body", body_html="<p>Original body</p>",
        )
        response = Response.objects.get(pk=old_response.pk)
        self.assertEqual(response.semantic_group, "")
        self.assertEqual(response.semantic_rationale, "")
        self.assertEqual(response.semantic_state_revision, "")
        old_prompt = old_apps.get_model("study", "Prompt").objects.create(
            content_key="old-worker-prompt", response_id=response.pk,
            theme_id=response.theme_id, family_id=response.family_id,
            number=900001, text="Old worker prompt", is_canonical=True,
        )
        self.assertEqual(Prompt.objects.get(pk=old_prompt.pk).model_content, {})
        old_card = old_apps.get_model("study", "Card").objects.create(
            user_id=user.pk, response_id=response.pk, card_type="spine",
        )
        self.assertEqual(Card.objects.get(pk=old_card.pk).projection_review_boundary, 0)
        old_log = old_apps.get_model("study", "ReviewLog").objects.create(
            user_id=user.pk, card_id=old_card.pk, rating=Rating.GOOD,
            state_before=CardState.NEW, state_after=CardState.LEARNING,
        )
        self.assertEqual(ReviewLog.objects.get(pk=old_log.pk).card_id, old_card.pk)


class OralImportPreservationTests(TestCase):
    def make_card(self):
        card = factories.make_spine_card(user=self.users[0])
        prompt = card.response.canonical_prompt
        key = f"{prompt.theme.slug}:p{prompt.number}"
        Prompt.objects.filter(pk=prompt.pk).update(content_key=key)
        card.response.content_key = key
        card.response.save(update_fields=["content_key"])
        return card

    def import_rows(self, rows):
        themes = {theme.name: theme for theme in factories.Theme.objects.all()}
        families = {family.name: family for family in factories.Family.objects.all()}
        command = Command()
        mapping = command._import_responses(rows, themes, families)
        command._import_prompts(rows, mapping, themes, families)
        command._reconcile_personal_responses(mapping)
        command._reconcile_response_annotations(mapping)
        for user in self.users:
            command._sync_cards(mapping, user=user)
        command._reconcile_response_cards(mapping)
        command._reconcile_oral_review_sessions()
        return mapping

    def setUp(self):
        self.users = [factories.make_user("oral-a"), factories.make_user("oral-b")]

    def test_simultaneous_split_merge_retains_all_versions_logs_and_schedules(self):
        source = self.make_card()
        donor = self.make_card()
        original = source.response
        alias = Prompt.objects.create(
            response=original, theme=original.theme, family=original.family,
            content_key=f"{original.theme.slug}:p999", number=999, text="Distinct obligation",
        )
        now = timezone.now()
        source.state, source.reps, source.last_reviewed = CardState.REVIEW, 7, now
        source.subject_completed_at = now
        source.save()
        log = ReviewLog.objects.create(
            user=self.users[0], card=donor, rating=Rating.GOOD,
            state_before=CardState.NEW, state_after=CardState.LEARNING,
        )
        session = ReviewSession.objects.create(
            user=self.users[0], current_card=donor, previous_card=donor,
            previous_review=log, scope={"kind": "spine", "response": str(donor.response_id)},
        )
        versions = []
        for user in self.users:
            for response in (original, donor.response):
                versions.append(PersonalResponse.objects.create(
                    user=user, response=response,
                    position=f"Private {user.pk}/{response.pk}",
                ))
        original_versions = list(PersonalResponse.objects.order_by("pk").values())
        original_card = Card.objects.values().get(pk=source.pk)
        first = response_data(
            original, members=[original.canonical_prompt, donor.response.canonical_prompt],
        )
        second = response_data(
            original, key=alias.content_key, members=[alias], group="eo/tache-3/split",
        )
        mapping = self.import_rows([first, second])
        self.assertEqual(list(PersonalResponse.objects.order_by("pk").values()), original_versions)
        donor.response.refresh_from_db()
        self.assertEqual(donor.response.semantic_owner_id, original.pk)
        self.assertTrue(ReviewLog.objects.filter(pk=log.pk, card=donor).exists())
        session.refresh_from_db()
        self.assertEqual(session.current_card_id, source.pk)
        self.assertEqual(session.previous_card_id, donor.pk)
        self.assertIsNone(session.previous_review_id)
        self.assertTrue(OralStateSnapshot.objects.filter(
            kind="session", payload__fields__previous_review_id=log.pk,
        ).exists())
        for user in self.users:
            self.assertEqual(personal_versions(mapping[first.content_key], user).count(), 2)
            self.assertEqual(preferred_personal(mapping[first.content_key], user).response_id, original.pk)
            split = Card.objects.get(response=mapping[second.content_key], user=user)
            self.assertEqual(split.state, CardState.NEW)
            self.assertIsNone(split.subject_completed_at)
        snapshot = OralStateSnapshot.objects.get(kind="card", source_id=source.pk)
        self.assertEqual(snapshot.payload["fields"]["reps"], original_card["reps"])
        self.assertEqual(snapshot.payload["fields"]["subject_completed_at"], now.isoformat())
        count = OralStateSnapshot.objects.filter(kind="card").count()
        Card.objects.filter(pk=source.pk).update(reps=42, subject_completed_at=None)
        save_personal(original, self.users[0], {"position": "Later user edit"})
        self.import_rows([replace(first, semantic_rationale="Rationale clarification"), second])
        source.refresh_from_db()
        self.assertEqual(source.reps, 42)
        self.assertIsNone(source.subject_completed_at)
        self.assertEqual(PersonalResponse.objects.get(user=self.users[0], response=original).position, "Later user edit")
        self.assertEqual(OralStateSnapshot.objects.filter(kind="card").count(), count)
        self.assertEqual(OralStateSnapshot.objects.filter(kind="personal").count(), 1)

    def test_incoming_alias_canonical_never_steals_old_canonical_owner(self):
        card = self.make_card()
        original = card.response
        alias = Prompt.objects.create(
            response=original, theme=original.theme, family=original.family,
            content_key=f"{original.theme.slug}:p999", number=999, text="Independent prompt",
        )
        mapping = self.import_rows([
            response_data(original, key=alias.content_key, members=[alias]),
            response_data(original, members=[original.canonical_prompt], group="eo/tache-3/owner"),
        ])
        self.assertEqual(mapping[original.content_key].pk, original.pk)
        self.assertNotEqual(mapping[alias.content_key].pk, original.pk)
        self.assertTrue(Response.objects.filter(pk=original.pk, content_key=original.content_key).exists())

    def test_projection_blocks_old_canonical_undo_but_allows_new_review_at_same_time(self):
        target, donor = self.make_card(), self.make_card()
        at = timezone.now()
        _, old_log = srs.review(target, Rating.GOOD, now=at, return_log=True)
        donor.state, donor.reps, donor.interval_days = CardState.REVIEW, 45, 90
        donor.last_reviewed = at
        donor.save()
        session = ReviewSession.objects.create(
            user=self.users[0], previous_card=target, previous_review=old_log,
            scope={"kind": "spine", "response": str(target.response_id)},
        )
        data = response_data(
            target.response,
            members=[target.response.canonical_prompt, donor.response.canonical_prompt],
        )
        self.import_rows([data])
        projected = Card.objects.values().get(pk=target.pk)
        self.assertEqual(projected["projection_review_boundary"], old_log.pk)
        donor.refresh_from_db()
        self.assertEqual(donor.projection_review_boundary, 0)
        snapshots = list(OralStateSnapshot.objects.order_by("pk").values())
        self.client.force_login(self.users[0])
        url = reverse("study:review_undo")
        session.refresh_from_db()
        self.assertIsNone(session.previous_review_id)
        self.assertFalse(self.client.post(url).json()["undone"])
        self.assertEqual(Card.objects.values().get(pk=target.pk), projected)
        self.assertTrue(ReviewLog.objects.filter(pk=old_log.pk).exists())
        self.assertEqual(list(OralStateSnapshot.objects.order_by("pk").values()), snapshots)

        target.refresh_from_db()
        _, new_log = srs.review(target, Rating.GOOD, now=at, return_log=True)
        self.assertEqual(new_log.reviewed_at, old_log.reviewed_at)
        self.assertGreater(new_log.pk, target.projection_review_boundary)
        ReviewSession.objects.filter(pk=session.pk).update(
            previous_review=new_log, previous_card=target, current_card=None,
        )
        self.import_rows([replace(data, semantic_rationale="Clarified rationale only.")])
        target.refresh_from_db()
        self.assertEqual(target.projection_review_boundary, old_log.pk)
        self.assertEqual(self.client.post(url).status_code, 200)
        target.refresh_from_db()
        self.assertEqual((target.state, target.reps, target.interval_days), (CardState.REVIEW, 45, 90))
        self.assertTrue(ReviewLog.objects.filter(pk=old_log.pk).exists())
        self.assertFalse(ReviewLog.objects.filter(pk=new_log.pk).exists())
        ReviewSession.objects.filter(pk=session.pk).update(
            previous_review=old_log, previous_card=target,
        )
        self.assertEqual(self.client.post(url).status_code, 409)

        _, between_projections = srs.review(target, Rating.GOOD, now=at, return_log=True)
        ReviewSession.objects.filter(pk=session.pk).update(
            previous_review=between_projections, previous_card=target,
        )
        next_donor = self.make_card()
        next_donor.state, next_donor.reps, next_donor.interval_days = CardState.REVIEW, 100, 180
        next_donor.last_reviewed = at
        next_donor.save()
        expanded = replace(data, prompts=[
            *data.prompts,
            replace(response_data(next_donor.response).prompts[0], is_canonical=False),
        ])
        self.import_rows([expanded])
        target.refresh_from_db()
        self.assertEqual(target.projection_review_boundary, between_projections.pk)
        session.refresh_from_db()
        self.assertIsNone(session.previous_review_id)
        ReviewSession.objects.filter(pk=session.pk).update(
            previous_review=between_projections, previous_card=target,
        )
        self.assertEqual(self.client.post(url).status_code, 409)
        target.refresh_from_db()
        self.assertEqual((target.reps, target.interval_days), (100, 180))
        self.assertTrue(ReviewLog.objects.filter(pk=between_projections.pk).exists())

    def test_old_worker_cannot_undo_across_cutover_but_its_later_grade_can_be_undone(self):
        target, donor = self.make_card(), self.make_card()
        at = timezone.now()
        _, original_log = srs.review(target, Rating.GOOD, now=at, return_log=True)
        donor.state, donor.reps, donor.interval_days = CardState.REVIEW, 45, 90
        donor.last_reviewed = at
        donor.save()
        old_apps = MigrationExecutor(connection).loader.project_state([
            ("study", "0050_course_exposure_projection"),
        ]).apps
        OldSession = old_apps.get_model("study", "ReviewSession")
        OldCard = old_apps.get_model("study", "Card")
        OldLog = old_apps.get_model("study", "ReviewLog")
        OldSession.objects.create(
            user_id=self.users[0].pk, previous_card_id=target.pk,
            previous_review_id=original_log.pk,
            scope={"kind": "spine", "response": str(target.response_id)},
        )
        data = response_data(
            target.response, members=[target.response.canonical_prompt, donor.response.canonical_prompt],
        )
        self.import_rows([data])
        with transaction.atomic():
            queued_old_session = OldSession.objects.select_for_update().get(user_id=self.users[0].pk)
            # The published Undo endpoint calls undo_last only when this pointer exists.
            self.assertIsNone(queued_old_session.previous_review_id)
        target.refresh_from_db()
        self.assertEqual((target.reps, target.interval_days), (45, 90))
        self.assertTrue(ReviewLog.objects.filter(pk=original_log.pk).exists())

        with transaction.atomic():
            old_session = OldSession.objects.select_for_update().get(user_id=self.users[0].pk)
            old_card = OldCard.objects.select_for_update().get(pk=target.pk)
            before = srs._snapshot(old_card)
            old_card.reps += 1
            old_card.interval_days = 225
            old_card.last_reviewed = at
            old_card.save(update_fields=["reps", "interval_days", "last_reviewed"])
            new_log = OldLog.objects.create(
                user_id=self.users[0].pk, card_id=target.pk, reviewed_at=at,
                rating=Rating.GOOD, state_before=CardState.REVIEW, state_after=CardState.REVIEW,
                interval_before=90, interval_after=225, card_before=before,
            )
            old_session.previous_review_id = new_log.pk
            old_session.save(update_fields=["previous_review"])
        self.import_rows([replace(data, semantic_rationale="Rationale-only rollout retry.")])
        target.refresh_from_db()
        self.assertEqual(target.projection_review_boundary, original_log.pk)
        self.assertGreater(new_log.pk, target.projection_review_boundary)
        self.client.force_login(self.users[0])
        self.assertTrue(self.client.post(reverse("study:review_undo")).json()["undone"])
        target.refresh_from_db()
        self.assertEqual((target.reps, target.interval_days), (45, 90))
        self.assertTrue(ReviewLog.objects.filter(pk=original_log.pk).exists())
        self.assertFalse(ReviewLog.objects.filter(pk=new_log.pk).exists())

    def test_donor_only_version_can_reset_to_original_without_changing_donor(self):
        for task_slug in ("tache-2", "tache-3"):
            with self.subTest(task=task_slug):
                task = factories.make_task(slug=task_slug)
                theme = factories.make_theme(f"reset-{task_slug}", task=task)
                target = factories.make_response(theme=theme)
                donor = factories.make_response(theme=theme)
                for index, response in enumerate((target, donor), 1):
                    prompt = response.canonical_prompt
                    key = (
                        f"tache2:janvier:batch-01:subject-{index:02d}" if task_slug == "tache-2"
                        else f"{theme.slug}:p{prompt.number}"
                    )
                    prompt.content_key = key
                    prompt.save(update_fields=["content_key"])
                    response.content_key = key
                    response.save(update_fields=["content_key"])
                selected = target.canonical_prompt
                data = response_data(
                    target, members=[selected, donor.canonical_prompt],
                    group=f"eo/{task_slug}/donor-reset",
                )
                data.arguments = [content.ArgumentData(1, "Original model question", "", "", "")]
                version = PersonalResponse.objects.create(
                    user=self.users[0], response=donor, position="Donor-only personal version",
                    arguments=[{
                        "order": 1, "idea": "Private question", "developpement": "",
                        "exemple": "", "consequence": "",
                    }],
                )
                original_version = PersonalResponse.objects.values().get(pk=version.pk)
                self.import_rows([data])
                self.client.force_login(self.users[0])
                detail_url = prompt_detail_url(selected)
                edit_url = reverse("study:edit_response", args=["eo", task_slug, selected.pk])
                self.assertTrue(self.client.get(detail_url).context["response_content"].is_personal)
                edit = self.client.get(edit_url)
                self.assertTrue(edit.context["has_personal_response"])
                self.assertContains(edit, 'value="reset"')
                self.assertEqual(self.client.post(edit_url, {"action": "reset"}).status_code, 302)
                marker = PersonalResponse.objects.get(user=self.users[0], response=target)
                self.assertFalse(marker.is_active)
                self.assertEqual(PersonalResponse.objects.values().get(pk=version.pk), original_version)
                detail = self.client.get(detail_url)
                self.assertFalse(detail.context["response_content"].is_personal)
                self.assertEqual(detail.context["response_content"].arguments[0].idea, "Original model question")
                self.assertNotContains(detail, "Donor-only personal version")
                self.assertNotIn("oral_history_url", detail.context)
                self.assertFalse(self.client.get(edit_url).context["has_personal_response"])

    def test_occurrence_path_overrides_old_shared_highlight_namespace(self):
        card = self.make_card()
        original = card.response
        alias = Prompt.objects.create(
            response=original, theme=original.theme, family=original.family,
            content_key=f"{original.theme.slug}:p999", number=999, text="Distinct obligation",
        )
        annotation = Annotation.objects.create(
            user=self.users[0], task=original.theme.task, kind=AnnotationKind.HIGHLIGHT,
            quote="Original selected words", start_offset=0, end_offset=23,
            source_key=f"response:{original.content_key}",
            source_path=prompt_detail_url(alias),
        )
        original_annotation = Annotation.objects.values().get(pk=annotation.pk)
        mapping = self.import_rows([
            response_data(original, members=[original.canonical_prompt]),
            response_data(original, key=alias.content_key, members=[alias], group="eo/tache-3/split"),
        ])
        self.assertEqual(Annotation.objects.values().get(pk=annotation.pk), original_annotation)
        self.assertEqual(annotation_owners([annotation])[annotation.pk], mapping[alias.content_key].pk)
        progress = subject_progress_by_response(self.users[0], [row.pk for row in mapping.values()])
        self.assertFalse(progress[original.pk].has_highlight)
        self.assertTrue(progress[mapping[alias.content_key].pk].has_highlight)

    def test_directory_displays_one_current_response_for_the_selected_publication(self):
        first, second = self.make_card(), self.make_card()
        first_prompt, second_prompt = first.response.canonical_prompt, second.response.canonical_prompt
        data = response_data(
            second.response, members=[first_prompt, second_prompt], group="eo/tache-3/variants",
        )
        first_model = content._oral_model_content(response_data(first.response))
        second_model = content._oral_model_content(response_data(second.response))
        first_model["position"] = "The first original model"
        second_model["position"] = "The second original model"
        data.prompts = [
            replace(data.prompts[0], model_content=first_model),
            replace(data.prompts[1], model_content=second_model),
        ]
        self.import_rows([data])
        self.client.force_login(self.users[0])
        url = reverse("study:task_browse", args=["eo", "tache-3"])
        all_page = self.client.get(url, {"deduplicate": "0"})
        page = self.client.get(url)
        self.assertEqual(all_page.context["display_count"], 2)
        self.assertEqual(page.context["display_count"], 1)
        self.assertEqual(page.context["publication_count"], 2)
        self.assertContains(page, "2 publications")
        self.assertContains(page, "data-subject-deduplication-toggle", count=1)
        self.assertEqual(page.context["subject_themes"][0]["subjects"][0]["prompt"].pk, first_prompt.pk)
        detail = self.client.get(prompt_detail_url(first_prompt))
        self.assertContains(detail, "The first original model")
        self.assertNotContains(detail, "The second original model")
        self.assertIn(f"prompt={first_prompt.pk}", detail.context["response_review_url"])
        self.assertNotIn("model=", detail.context["response_review_url"])
        self.assertNotIn("personal=", detail.context["response_review_url"])
        self.assertNotIn("oral_model_variants", detail.context)
        self.assertNotContains(detail, "Versions du sujet")
        self.assertContains(
            detail, f'data-annotation-source-key="subject-sidebar:{first_prompt.content_key}"'
        )

    def test_nested_directory_deduplicates_in_displayed_family_order(self):
        canonical, earlier_family = self.make_card(), self.make_card()
        family = factories.make_family("earlier-visible-family")
        family.order = 0
        family.save(update_fields=["order"])
        earlier_prompt = earlier_family.response.canonical_prompt
        earlier_prompt.family = family
        earlier_prompt.save(update_fields=["family"])
        data = response_data(
            canonical.response,
            members=[canonical.response.canonical_prompt, earlier_prompt],
        )
        self.import_rows([data])
        self.client.force_login(self.users[0])
        url = reverse("study:task_browse", args=["eo", "tache-3"])
        all_page = self.client.get(url)
        first_displayed = all_page.context["subject_themes"][0]["families"][0]["subjects"][0]["prompt"]
        self.assertEqual(first_displayed.pk, earlier_prompt.pk)
        page = self.client.get(url, {"deduplicate": "1"})
        self.assertEqual(page.context["display_count"], 1)
        self.assertEqual(page.context["subject_themes"][0]["subjects"][0]["prompt"].pk, first_displayed.pk)
        self.assertNotContains(page, "Voir le thème et ses révisions")

    def test_history_and_version_selectors_are_removed_without_deleting_personal_data(self):
        first, donor = self.make_card(), self.make_card()
        own = PersonalResponse.objects.create(user=self.users[0], response=first.response, position="Own")
        alternative = PersonalResponse.objects.create(user=self.users[0], response=donor.response, position="Alternative")
        foreign = PersonalResponse.objects.create(user=self.users[1], response=donor.response, position="Foreign private")
        self.import_rows([response_data(
            first.response, members=[first.response.canonical_prompt, donor.response.canonical_prompt],
        )])
        before = list(PersonalResponse.objects.order_by("pk").values())
        self.client.force_login(self.users[0])
        prompt = first.response.canonical_prompt
        detail_url = prompt_detail_url(prompt)
        page = self.client.get(detail_url)
        self.assertContains(page, "Own")
        self.assertNotContains(page, "Alternative")
        self.assertNotContains(page, "Foreign private")
        for task_slug in ("tache-2", "tache-3"):
            url = f"/expression/orale/{task_slug}/historique/{first.response_id}/"
            with self.assertRaises(Resolver404):
                resolve(url)
            with self.assertRaises(NoReverseMatch):
                reverse("study:oral_response_history", args=["eo", task_slug, first.response_id])
            removed = self.client.get(url)
            self.assertEqual(removed.status_code, 404)
            self.assertNotIn("Location", removed.headers)
            self.assertEqual(self.client.post(url, {"personal_id": alternative.pk}).status_code, 404)
        for parameters in (
            {"model": "1"}, {"personal": alternative.pk},
            {"personal": foreign.pk}, {"model": "1", "reset": "1"},
        ):
            self.assertEqual(self.client.get(detail_url, parameters).status_code, 404)
            self.assertEqual(self.client.get(
                reverse("study:task_review", args=["eo", "tache-3"]), parameters
            ).status_code, 404)
        self.assertEqual(list(PersonalResponse.objects.order_by("pk").values()), before)

    def test_saved_review_scope_drops_obsolete_version_selection(self):
        from study.views.review import _resolved_review_scope

        card = self.make_card()
        session = ReviewSession.objects.create(
            user=self.users[0], current_card=card,
            scope={"kind": "spine", "response": str(card.response_id), "model": "1", "personal": "12"},
        )
        request = RequestFactory().get(reverse("study:review_next"))
        scope, changed = _resolved_review_scope(request, session)
        self.assertTrue(changed)
        self.assertEqual(scope, {"kind": "spine", "response": str(card.response_id)})

    def test_null_user_legacy_schedule_is_preserved_without_fanning_out(self):
        first = self.make_card()
        legacy = Card.objects.create(
            user=None, response=first.response, card_type=first.card_type,
            state=CardState.REVIEW, reps=8, subject_completed_at=timezone.now(),
        )
        alias = Prompt.objects.create(
            response=first.response, theme=first.response.theme, family=first.response.family,
            content_key=f"{first.response.theme.slug}:p999", number=999, text="Separate task",
        )
        self.users.append(None)
        mapping = self.import_rows([
            response_data(first.response, members=[first.response.canonical_prompt]),
            response_data(first.response, key=alias.content_key, members=[alias], group="eo/tache-3/split"),
        ])
        legacy.refresh_from_db()
        self.assertEqual(legacy.reps, 8)
        self.assertIsNone(Card.objects.get(
            user=None, response=mapping[alias.content_key],
        ).subject_completed_at)
        self.assertTrue(OralStateSnapshot.objects.filter(
            user=None, kind="card", source_id=legacy.pk,
        ).exists())

    def test_search_matches_all_publications_and_groups_before_limit(self):
        rows = []
        first_prompt_ids = []
        for index in range(15):
            first, canonical = self.make_card(), self.make_card()
            first_prompt = first.response.canonical_prompt
            canonical_prompt = canonical.response.canonical_prompt
            first_prompt.text = f"Needle variant {index}"
            canonical_prompt.text = f"Needle canonical {index}"
            first_prompt_ids.append(first_prompt.pk)
            rows.append(response_data(
                canonical.response, members=[first_prompt, canonical_prompt],
                group=f"eo/tache-3/search-{index}",
            ))
        self.import_rows(rows)
        self.client.force_login(self.users[0])
        url = reverse("study:task_search", args=["eo", "tache-3"])
        page = self.client.get(url, {"q": "Needle", "scope": "subjects", "deduplicate": "1"})
        self.assertEqual(page.context["prompt_result_count"], 15)
        self.assertEqual([prompt.pk for prompt in page.context["prompt_results"]], first_prompt_ids[:12])
        page = self.client.get(url, {"q": "variant", "scope": "subjects", "deduplicate": "1"})
        self.assertEqual(page.context["prompt_result_count"], 15)
        self.assertTrue(all(not prompt.is_canonical for prompt in page.context["prompt_results"]))


class OralCorpusUpgradeTests(TestCase):
    def test_real_corpus_upgrade_preserves_private_rows_and_is_idempotent(self):
        with (
            patch.object(content, "parse_responses", content.parse_response_storage),
            patch.object(content, "parse_tache_two_responses", content.parse_tache_two_storage_responses),
        ):
            call_command("import_content", stdout=StringIO())
        users = [factories.make_user("upgrade-a"), factories.make_user("upgrade-b")]
        for user in users:
            provision_user_study_data(user)
        semantic = content.parse_tache_two_responses() + content.parse_responses()
        owner_by_key = {
            prompt.content_key: response.content_key
            for response in semantic for prompt in response.prompts
        }
        oral_responses = list(Response.objects.filter(content_key__in=owner_by_key))
        old_ids = {response.content_key: response.pk for response in oral_responses}
        for user in users:
            for response in oral_responses:
                PersonalResponse.objects.create(
                    user=user, response=response,
                    position=f"Original private work {user.pk}/{response.content_key}",
                )
        split_storage = next(
            response for response in content.parse_tache_two_storage_responses()
            if len({owner_by_key[prompt.content_key] for prompt in response.prompts}) > 1
        )
        source_response = Response.objects.get(content_key=split_storage.content_key)
        card = Card.objects.get(user=users[0], response=source_response)
        card.state, card.reps = CardState.REVIEW, 11
        card.subject_completed_at = timezone.now()
        card.save()
        log = ReviewLog.objects.create(
            user=users[0], card=card, rating=Rating.GOOD,
            state_before=CardState.NEW, state_after=CardState.REVIEW,
        )
        original_versions = list(PersonalResponse.objects.order_by("pk").values())
        old_phrase_key, target_phrase_key = next(iter(PHRASE_ID_MERGES.items()))
        for phrase_key in (old_phrase_key, target_phrase_key):
            Annotation.objects.create(
                user=users[0], task=source_response.theme.task,
                kind=AnnotationKind.HIGHLIGHT, source_key=f"phrase:{phrase_key}:catalog",
                source_path="/legacy-vocabulary/", quote="Preserved selection",
                start_offset=0, end_offset=19,
            )
        original_annotations = list(Annotation.objects.order_by("pk").values())
        local_phrase = Phrase.objects.filter(tier=PhraseTier.RESPONSE, is_active=True).first()
        production = Card.objects.get(user=users[0], phrase=local_phrase, card_type="phrase_prod")
        recognition, _ = Card.objects.get_or_create(
            user=users[0], phrase=local_phrase, card_type="phrase_recog",
        )
        recognition.state, recognition.reps = CardState.REVIEW, 22
        recognition.last_reviewed = timezone.now()
        recognition.save()
        original_card_ids = set(Card.objects.values_list("pk", flat=True))
        call_command("import_content", stdout=StringIO())
        self.assertEqual(list(PersonalResponse.objects.order_by("pk").values()), original_versions)
        self.assertEqual(list(Annotation.objects.order_by("pk").values()), original_annotations)
        production.refresh_from_db()
        self.assertEqual(production.reps, 0)
        self.assertTrue(original_card_ids <= set(Card.objects.values_list("pk", flat=True)))
        self.assertTrue(ReviewLog.objects.filter(pk=log.pk, card=card).exists())
        for key, pk in old_ids.items():
            source = Response.objects.get(pk=pk)
            self.assertEqual(source.content_key, key)
            target = Response.objects.get(content_key=owner_by_key[key])
            self.assertEqual(source.semantic_owner_id or source.pk, target.pk)
        target_ids = dict(Response.objects.filter(
            semantic_group__gt="", is_active=True,
        ).values_list("content_key", "pk"))
        owner = owner_by_key[split_storage.content_key]
        for prompt in split_storage.prompts:
            target = owner_by_key[prompt.content_key]
            if target != owner:
                self.assertIsNone(Card.objects.get(
                    user=users[0], response_id=target_ids[target],
                ).subject_completed_at)
        target_card = Card.objects.get(user=users[0], response_id=target_ids[owner])
        Card.objects.filter(pk=target_card.pk).update(reps=99, subject_completed_at=None)
        count = OralStateSnapshot.objects.count()
        call_command("import_content", stdout=StringIO())
        target_card.refresh_from_db()
        self.assertEqual(target_card.reps, 99)
        self.assertIsNone(target_card.subject_completed_at)
        self.assertEqual(OralStateSnapshot.objects.count(), count)
        self.assertEqual(list(PersonalResponse.objects.order_by("pk").values()), original_versions)
        self.client.force_login(users[0])
        from study.views.review import _review_card_payload
        for group in semantic:
            if len({prompt.theme for prompt in group.prompts}) < 2:
                continue
            for source in group.prompts:
                prompt = Prompt.objects.select_related("theme__task__part", "family").get(
                    content_key=source.content_key,
                )
                task = prompt.theme.task
                for scope_name, scope_value in (
                    ("theme", prompt.theme.slug), ("family", prompt.family.slug),
                ):
                    scope = {"part": "eo", "task": task.slug, scope_name: scope_value}
                    spine = queue.scoped_cards({**scope, "kind": "spine"}, user=users[0]).get(
                        response_id=prompt.response_id,
                    )
                    expected_vocab = set(Phrase.objects.filter(
                        tier=PhraseTier.SUBJECT, source_prompts=prompt, is_active=True,
                    ).values_list("pk", flat=True))
                    scoped_vocab = set(queue.scoped_cards(
                        {**scope, "kind": "vocab", "prompt": str(prompt.pk)}, user=users[0],
                    ).values_list("phrase_id", flat=True))
                    self.assertTrue(expected_vocab)
                    self.assertEqual(scoped_vocab, expected_vocab)
                    payload = _review_card_payload(spine, users[0], scope)
                    self.assertEqual(
                        getattr(payload["canonical_prompt"], scope_name + "_id"),
                        getattr(prompt, scope_name + "_id"),
                    )
                    if task.slug == "tache-3":
                        segment = "themes" if scope_name == "theme" else "familles"
                        removed = self.client.get(
                            f"/expression/orale/tache-3/{segment}/{scope_value}/",
                            {"deduplicate": "1"},
                        )
                        self.assertEqual(removed.status_code, 404)
                        self.assertNotIn("Location", removed.headers)
                        destination = subject_group_url(
                            "eo", task.slug, prompt.theme.slug,
                            prompt.family.slug if scope_name == "family" else None,
                        )
                        directory_page = self.client.get(destination, {"deduplicate": "0"})
                        source_group = next(
                            group for group in directory_page.context["subject_themes"]
                            if group["slug"] == prompt.theme.slug
                        )
                        source_family = next(
                            family for family in source_group["families"]
                            if family["slug"] == prompt.family.slug
                        )
                        self.assertIn(prompt.pk, [row["prompt"].pk for row in source_family["subjects"]])
                        continue
                    route = "study:theme_detail" if scope_name == "theme" else "study:task_family_detail"
                    page = self.client.get(reverse(route, args=["eo", task.slug, scope_value]), {"deduplicate": "1"})
                    displayed = [row["prompt"] for row in page.context["rows"] if row["prompt"].response_id == prompt.response_id]
                    self.assertEqual(len(displayed), 1)
                    expected = Prompt.objects.filter(
                        response_id=prompt.response_id, is_active=True,
                        **{scope_name + "_id": getattr(prompt, scope_name + "_id")},
                    ).order_by("theme__order", "number", "pk").first()
                    self.assertEqual(displayed[0].pk, expected.pk)
