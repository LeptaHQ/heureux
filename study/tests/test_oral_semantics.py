from dataclasses import replace
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import SimpleTestCase, TestCase
from django.urls import reverse
from django.utils import timezone

from study import content_loader as content
from study.account_services import provision_user_study_data
from study.management.commands.import_content import Command
from study.models import (
    Annotation, AnnotationKind, Card, CardState, OralStateSnapshot, PersonalResponse,
    Prompt, Rating, Response, ReviewLog, ReviewSession,
)
from study.oral_history import annotation_owners, personal_versions, preferred_personal, save_personal
from study.progress import subject_progress_by_response
from study.routing import prompt_detail_url
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
        self.assertEqual(session.previous_review_id, log.pk)
        self.assertEqual(OralStateSnapshot.objects.filter(kind="session").count(), 1)
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

    def test_directory_and_model_variants_keep_noncanonical_first_publication(self):
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
        all_page = self.client.get(url)
        page = self.client.get(url, {"deduplicate": "1"})
        self.assertEqual(all_page.context["display_count"], 2)
        self.assertEqual(page.context["display_count"], 1)
        self.assertEqual(page.context["groups"][0]["subjects"][0]["prompt"].pk, first_prompt.pk)
        detail = self.client.get(prompt_detail_url(first_prompt), {"model": "1"})
        self.assertContains(detail, "The first original model")
        self.assertNotContains(detail, "The second original model")
        self.assertIn(f"prompt={first_prompt.pk}", detail.context["response_review_url"])
        self.assertIn("model=1", detail.context["response_review_url"])
        self.assertEqual(len(detail.context["oral_model_variants"]), 2)

    def test_preserved_personal_history_restores_copy_without_cross_user_access(self):
        first, donor = self.make_card(), self.make_card()
        own = PersonalResponse.objects.create(user=self.users[0], response=first.response, position="Own")
        alternative = PersonalResponse.objects.create(user=self.users[0], response=donor.response, position="Alternative")
        foreign = PersonalResponse.objects.create(user=self.users[1], response=donor.response, position="Foreign private")
        self.import_rows([response_data(
            first.response, members=[first.response.canonical_prompt, donor.response.canonical_prompt],
        )])
        self.client.force_login(self.users[0])
        url = reverse("study:oral_response_history", args=["eo", "tache-3", first.response_id])
        page = self.client.get(url)
        self.assertContains(page, "Own")
        self.assertContains(page, "Alternative")
        self.assertNotContains(page, "Foreign private")
        self.assertEqual(self.client.post(url, {"personal_id": foreign.pk}).status_code, 404)
        restored = self.client.post(url, {"personal_id": alternative.pk})
        self.assertEqual(restored.status_code, 302)
        own.refresh_from_db()
        alternative.refresh_from_db()
        self.assertEqual(own.position, "Alternative")
        self.assertEqual(alternative.position, "Alternative")
        archived = OralStateSnapshot.objects.get(kind="personal", source_id=own.pk)
        self.assertEqual(archived.payload["fields"]["position"], "Own")
        self.assertEqual(self.client.post(url, {"snapshot_id": archived.pk}).status_code, 302)
        own.refresh_from_db()
        self.assertEqual(own.position, "Own")

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
        original_card_ids = set(Card.objects.values_list("pk", flat=True))
        call_command("import_content", stdout=StringIO())
        self.assertEqual(list(PersonalResponse.objects.order_by("pk").values()), original_versions)
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
