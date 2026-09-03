import json

from django.test import SimpleTestCase, TestCase
from django.urls import reverse

from study import content_loader as content
from study.account_services import provision_user_study_data
from study.management.commands.import_content import Command
from study.models import (
    Annotation,
    AnnotationKind,
    CardState,
    PersonalResponse,
    PersonalWritingResponse,
    Task,
    WritingSujet,
    WritingSujetCompletion,
)
from study.templatetags.study_markdown import french_wordcount

from . import factories


class EeWritingContentTests(SimpleTestCase):
    def test_displayed_word_count_uses_the_validated_french_rules(self):
        text = "Aujourd’hui, l’auteur explique qu’un week-end bien organisé aide."
        self.assertEqual(
            french_wordcount(text),
            content._ee_word_count(text),
        )

    def test_final_equivalence_counts_match_the_audited_corpora(self):
        expected = {
            1: (34, 86, 86),
            2: (33, 83, 88),
            3: (32, 86, 84),
        }
        for tache, counts in expected.items():
            group_count, grouped_count, distinct_count = counts
            groups = content.load_ee_equivalent_groups(tache)
            with self.subTest(tache=tache):
                self.assertEqual(len(groups), group_count)
                self.assertEqual(
                    sum(len(group.members) for group in groups),
                    grouped_count,
                )
                self.assertEqual(
                    138 - grouped_count + group_count,
                    distinct_count,
                )

    def test_every_distinct_tache_one_and_two_subject_has_a_valid_response(self):
        expected = {1: (86, 60, 120), 2: (88, 120, 150)}
        for tache, (canonical_count, minimum, maximum) in expected.items():
            with self.subTest(tache=tache):
                categories = content.load_ee_writing_categories(tache)
                sujets = [
                    sujet
                    for category in categories
                    for sujet in category.sujets
                ]
                canonical = [sujet for sujet in sujets if sujet.versions]
                versions = [
                    version
                    for sujet in canonical
                    for version in sujet.versions
                ]

                self.assertEqual(len(categories), 11)
                self.assertEqual(len(sujets), 138)
                self.assertEqual(len(canonical), canonical_count)
                self.assertTrue(versions)
                self.assertTrue(
                    all(
                        minimum <= content._ee_word_count(version.body) <= maximum
                        for version in versions
                    )
                )
                self.assertEqual(
                    {version.origin for version in versions},
                    {"author", "original"},
                )
                for sujet in canonical:
                    origins = [version.origin for version in sujet.versions]
                    if "author" in origins:
                        self.assertEqual(origins[0], "author")
                        self.assertEqual(
                            origins,
                            sorted(
                                origins,
                                key={"author": 0, "original": 1}.get,
                            ),
                        )

    def test_every_equivalent_occurrence_points_to_one_canonical_slug(self):
        for tache in (1, 2):
            with self.subTest(tache=tache):
                categories = content.load_ee_writing_categories(tache)
                sujets = {
                    sujet.source_key: sujet
                    for category in categories
                    for sujet in category.sujets
                }
                canonical_by_key = content.ee_canonical_by_content_key(tache)

                for key, sujet in sujets.items():
                    canonical_key = canonical_by_key.get(key, key)
                    self.assertEqual(
                        sujet.canonical_slug,
                        content.ee_writing_sujet_slug(canonical_key),
                    )
                    self.assertEqual(
                        bool(sujet.versions),
                        key == canonical_key,
                    )


class EeTacheThreeUnifiedResponseTests(SimpleTestCase):
    def test_themed_responses_collapse_only_audited_equivalent_groups(self):
        responses = content.parse_ee_tache_three_responses()
        prompt_to_response = {
            prompt.content_key: response.content_key
            for response in responses
            for prompt in response.prompts
        }

        self.assertEqual(len(responses), 84)
        self.assertEqual(len(prompt_to_response), 138)
        self.assertEqual(
            set(prompt_to_response),
            set(content.load_ee_subject_keys(3)),
        )
        for response in responses:
            self.assertEqual(
                [
                    prompt.content_key
                    for prompt in response.prompts
                    if prompt.is_canonical
                ],
                [response.content_key],
            )
        for group in content.load_ee_equivalent_groups(3):
            for member in group.members:
                self.assertEqual(
                    prompt_to_response[member],
                    group.canonical,
                )

    def test_author_overrides_and_all_tache_three_models_respect_part_limits(self):
        author = content.load_ee_tache_three_author_responses()
        responses = content.parse_ee_tache_three_responses()

        self.assertEqual(len(author), 10)
        for response in responses:
            with self.subTest(response=response.content_key):
                self.assertLessEqual(
                    40,
                    content._ee_word_count(response.position),
                )
                self.assertLessEqual(
                    content._ee_word_count(response.position),
                    60,
                )
                self.assertLessEqual(
                    80,
                    content._ee_word_count(response.position_claire),
                )
                self.assertLessEqual(
                    content._ee_word_count(response.position_claire),
                    120,
                )

    def test_source_defects_are_exposed_without_inventing_a_second_view(self):
        responses = {
            response.content_key: response
            for response in content.parse_ee_tache_three_responses()
        }
        prompts = {
            prompt.content_key: prompt
            for response in responses.values()
            for prompt in response.prompts
        }

        self.assertIn(
            "Les deux documents publiés sont identiques",
            responses["ee-tache3:mai:combinaison-3-bis"].position,
        )
        self.assertIn(
            "Un seul document traite réellement",
            responses["ee-tache3:decembre:combinaison-10"].position,
        )
        self.assertEqual(
            prompts["ee-tache3:avril:combinaison-11"].text,
            "Les effets des jeux vidéo (sur le cerveau et le comportement "
            "des enfants)",
        )
        invalid = next(
            combinaison
            for month in content.load_ee_tache_three_months()
            for combinaison in month.combinaisons
            if combinaison.content_key
            == "ee-tache3:decembre:combinaison-10"
        )
        self.assertTrue(invalid.document1_invalid)

    def test_author_vocabulary_is_drawn_from_the_effective_authored_response(self):
        responses = {
            response.content_key: response
            for response in content.parse_ee_tache_three_responses()
        }
        author_keys = set(content.load_ee_tache_three_author_responses())
        entries_by_key = {}
        for path in content.EE_TACHE_THREE_VOCABULARY_DIR.glob("*.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            for row in payload["responses"]:
                entries_by_key[row["response_key"]] = row["entries"]

        for content_key in author_keys:
            effective = content._ee_tache_three_normalize(
                responses[content_key].position
                + " "
                + responses[content_key].position_claire
            )
            with self.subTest(content_key=content_key):
                self.assertEqual(len(entries_by_key[content_key]), 30)
                for entry in entries_by_key[content_key]:
                    self.assertIn(
                        content._ee_tache_three_normalize(entry["example"]),
                        effective,
                    )

    def test_every_retired_tache_three_vocabulary_id_has_a_canonical_target(self):
        merges = content.ee_tache_three_phrase_id_merges()
        entries_by_key = {}
        for path in content.EE_TACHE_THREE_VOCABULARY_DIR.glob("*.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            for row in payload["responses"]:
                entries_by_key[row["response_key"]] = row["entries"]

        self.assertEqual(len(merges), 1620)
        self.assertTrue(all(source != target for source, target in merges.items()))
        for group in content.load_ee_equivalent_groups(3):
            canonical_ids = {
                entry["id"] for entry in entries_by_key[group.canonical]
            }
            for member in group.members:
                if member == group.canonical:
                    continue
                source_ids = {
                    entry["id"] for entry in entries_by_key[member]
                }
                with self.subTest(group=group.id, member=member):
                    self.assertEqual(len(source_ids), 30)
                    self.assertEqual(
                        {merges[source_id] for source_id in source_ids},
                        canonical_ids,
                    )


class EeAnonymousPhraseMigrationTests(TestCase):
    def test_anonymous_alias_schedule_survives_first_account_claim(self):
        source_id, target_id = next(
            iter(content.ee_tache_three_phrase_id_merges().items())
        )
        target_phrase = factories.make_phrase(tier="subject")
        target_phrase.phrase_id = target_id
        target_phrase.save(update_fields=["phrase_id"])
        source_phrase = factories.make_phrase(
            category=target_phrase.category,
            tier="subject",
        )
        source_phrase.phrase_id = source_id
        source_phrase.is_active = False
        source_phrase.save(update_fields=["phrase_id", "is_active"])
        target_card = factories.make_phrase_card(
            user=None,
            phrase=target_phrase,
        )
        factories.make_phrase_card(
            user=None,
            phrase=source_phrase,
            state=CardState.REVIEW,
            reps=11,
            interval_days=31,
        )

        Command()._reconcile_phrase_cards()
        target_card.refresh_from_db()
        self.assertIsNone(target_card.user_id)
        self.assertEqual(target_card.reps, 11)
        self.assertEqual(target_card.interval_days, 31)

        user = factories.make_user("first-ee-account")
        provision_user_study_data(user)
        target_card.refresh_from_db()
        self.assertEqual(target_card.user_id, user.pk)
        self.assertEqual(target_card.reps, 11)
        self.assertEqual(target_card.interval_days, 31)


class EeWritingImportPreservationTests(TestCase):
    def setUp(self):
        self.part = factories.make_part("ee")
        self.task = factories.make_task(self.part, "tache-1")
        self.command = Command()
        self.task_by_slug = {"ee/tache-1": self.task}
        self.categories = content.load_ee_writing_categories(1)
        self.user = factories.make_user("ee-writing-import")

    def test_matching_legacy_sujet_keeps_its_identity_and_private_draft(self):
        source = next(
            sujet
            for category in self.categories
            for sujet in category.sujets
            if sujet.versions
        )
        legacy = factories.make_writing_sujet(
            self.task,
            slug="legacy-sujet",
            prompt=source.prompt,
        )
        personal = PersonalWritingResponse.objects.create(
            user=self.user,
            sujet=legacy,
            body="Brouillon privé à préserver.",
        )

        self.command._import_writing_sujets(
            self.categories,
            self.task_by_slug,
        )

        migrated = WritingSujet.objects.get(
            task=self.task,
            slug=source.slug,
        )
        personal.refresh_from_db()
        self.assertEqual(migrated.pk, legacy.pk)
        self.assertEqual(personal.sujet_id, migrated.pk)

    def test_alias_private_state_moves_to_the_canonical_sujet(self):
        group = content.load_ee_equivalent_groups(1)[0]
        canonical_slug = content.ee_writing_sujet_slug(group.canonical)
        alias_slug = content.ee_writing_sujet_slug(
            next(member for member in group.members if member != group.canonical)
        )
        alias = factories.make_writing_sujet(
            self.task,
            slug=alias_slug,
            prompt="Alias historique.",
        )
        personal = PersonalWritingResponse.objects.create(
            user=self.user,
            sujet=alias,
            body="Version écrite sur l’alias.",
        )
        completion = WritingSujetCompletion.objects.create(
            user=self.user,
            sujet=alias,
        )
        annotation = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.HIGHLIGHT,
            quote="Version écrite",
            source_path="/expression/ecrite/tache-1/sujets/",
            source_key=f"writing-sujet:{alias.pk}:personal",
            start_offset=0,
            end_offset=14,
        )

        self.command._import_writing_sujets(
            self.categories,
            self.task_by_slug,
        )

        canonical = WritingSujet.objects.get(
            task=self.task,
            slug=canonical_slug,
        )
        personal.refresh_from_db()
        completion.refresh_from_db()
        annotation.refresh_from_db()
        self.assertEqual(personal.sujet_id, canonical.pk)
        self.assertEqual(completion.sujet_id, canonical.pk)
        self.assertEqual(
            annotation.source_key,
            f"writing-sujet:{canonical.pk}:personal",
        )

    def test_response_alias_annotations_move_to_the_canonical_key(self):
        theme = factories.make_theme("ee-alias-theme", task=self.task)
        source = factories.make_response(theme=theme)
        target = factories.make_response(theme=theme)
        source.content_key = "ee-tache3:mars:combinaison-8"
        source.save(update_fields=["content_key"])
        target.content_key = "ee-tache3:janvier:combinaison-19"
        target.save(update_fields=["content_key"])
        annotation = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.HIGHLIGHT,
            quote="À mon avis",
            source_path="/expression/ecrite/tache-3/sujets/1/",
            source_key=f"response:{source.content_key}",
            start_offset=0,
            end_offset=10,
        )
        self.command._response_sources = {
            target.content_key: {source.pk, target.pk},
        }
        PersonalResponse.objects.create(
            user=self.user,
            response=target,
            arguments=[{"idea": "Ancienne version"}],
        )
        PersonalResponse.objects.create(
            user=self.user,
            response=source,
            arguments=[{"idea": "Version alias la plus récente"}],
        )

        self.command._reconcile_personal_responses(
            {target.content_key: target}
        )
        self.command._reconcile_response_annotations(
            {target.content_key: target}
        )

        annotation.refresh_from_db()
        personal = PersonalResponse.objects.get(user=self.user)
        self.assertEqual(personal.response_id, target.pk)
        self.assertEqual(
            personal.arguments,
            [{"idea": "Version alias la plus récente"}],
        )
        self.assertEqual(
            annotation.source_key,
            f"response:{target.content_key}",
        )

    def test_alias_vocabulary_schedule_and_annotation_move_to_canonical(self):
        source_id, target_id = next(
            iter(content.ee_tache_three_phrase_id_merges().items())
        )
        target_phrase = factories.make_phrase(tier="subject")
        target_phrase.phrase_id = target_id
        target_phrase.save(update_fields=["phrase_id"])
        source_phrase = factories.make_phrase(
            category=target_phrase.category,
            tier="subject",
        )
        source_phrase.phrase_id = source_id
        source_phrase.save(update_fields=["phrase_id"])
        target_card = factories.make_phrase_card(
            user=self.user,
            phrase=target_phrase,
        )
        factories.make_phrase_card(
            user=self.user,
            phrase=source_phrase,
            state=CardState.REVIEW,
            reps=9,
            interval_days=24,
        )
        annotation = Annotation.objects.create(
            user=self.user,
            task=self.task,
            kind=AnnotationKind.HIGHLIGHT,
            quote="Expression",
            source_path="/expression/ecrite/tache-3/sujets/1/",
            source_key=f"phrase:{source_id}:catalog",
            start_offset=0,
            end_offset=10,
        )

        self.command._reconcile_phrase_cards()

        target_card.refresh_from_db()
        annotation.refresh_from_db()
        self.assertEqual(target_card.reps, 9)
        self.assertEqual(target_card.interval_days, 24)
        self.assertEqual(
            annotation.source_key,
            f"phrase:{target_id}:catalog",
        )


class EeWritingPageTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        command = Command()
        task_by_slug = command._import_sections(content.load_sections())
        for tache in (1, 2):
            command._import_writing_sujets(
                content.load_ee_writing_categories(tache),
                task_by_slug,
                task_key=f"ee/tache-{tache}",
            )
        cls.tasks = {
            tache: task_by_slug[f"ee/tache-{tache}"]
            for tache in (1, 2)
        }
        cls.user = factories.make_user("ee-writing-pages")

    def setUp(self):
        self.client.force_login(self.user)

    def test_both_tasks_are_available_and_group_all_occurrences_by_theme(self):
        for tache, distinct in ((1, 86), (2, 88)):
            task = self.tasks[tache]
            with self.subTest(tache=tache):
                self.assertTrue(task.available)
                response = self.client.get(
                    reverse(
                        "study:task_detail",
                        args=[task.part.slug, task.slug],
                    )
                )

                self.assertEqual(response.status_code, 200)
                self.assertTemplateUsed(
                    response,
                    "study/ee_writing_subjects.html",
                )
                self.assertEqual(response.context["category_count"], 11)
                self.assertEqual(response.context["sujet_count"], 138)
                self.assertEqual(response.context["distinct_count"], distinct)
                self.assertEqual(response.context["response_count"], distinct)
                self.assertContains(response, "data-t1-table-theme", count=11)
                self.assertContains(response, "data-t1-table-subject", count=138)
                self.assertContains(response, "data-subject-directory-search")
                self.assertContains(response, 'target="_blank"')
                self.assertContains(response, "publications liées")
                self.assertContains(
                    response,
                    (
                        "Visez idéalement 80 à 100 mots"
                        if tache == 1
                        else "La narration prime sur l’argumentation"
                    ),
                )
                self.assertContains(response, content.EE_ASTUCES_URL)

    def test_equivalent_sujets_share_personal_response_and_completion(self):
        for tache in (1, 2):
            task = self.tasks[tache]
            group = content.load_ee_equivalent_groups(tache)[0]
            canonical_slug = content.ee_writing_sujet_slug(group.canonical)
            alias_slug = content.ee_writing_sujet_slug(
                next(member for member in group.members if member != group.canonical)
            )
            canonical = WritingSujet.objects.get(
                task=task,
                slug=canonical_slug,
            )
            alias = WritingSujet.objects.get(task=task, slug=alias_slug)
            edit_url = reverse(
                "study:writing_sujet_edit",
                args=[task.part.slug, task.slug, alias.pk],
            )
            completion_url = reverse(
                "study:writing_sujet_completion",
                args=[task.part.slug, task.slug, alias.pk],
            )

            with self.subTest(tache=tache):
                saved = self.client.post(
                    edit_url,
                    {"action": "save", "body": "Ma réponse personnelle partagée."},
                )
                self.assertEqual(saved.status_code, 302)
                self.assertTrue(
                    PersonalWritingResponse.objects.filter(
                        user=self.user,
                        sujet=canonical,
                    ).exists()
                )
                self.assertFalse(
                    PersonalWritingResponse.objects.filter(
                        user=self.user,
                        sujet=alias,
                    ).exists()
                )

                detail = self.client.get(
                    reverse(
                        "study:writing_sujet_detail",
                        args=[task.part.slug, task.slug, alias.pk],
                    )
                )
                self.assertEqual(detail.context["progress_sujet"], canonical)
                self.assertContains(detail, "Ma réponse personnelle partagée.")
                self.assertContains(detail, "Sujets équivalents")
                self.assertContains(detail, "progression sont partagées")

                completed = self.client.post(
                    completion_url,
                    {"completed": "1"},
                    HTTP_X_REQUESTED_WITH="fetch",
                )
                self.assertEqual(completed.status_code, 200)
                self.assertTrue(
                    WritingSujetCompletion.objects.filter(
                        user=self.user,
                        sujet=canonical,
                    ).exists()
                )
                self.assertFalse(
                    WritingSujetCompletion.objects.filter(
                        user=self.user,
                        sujet=alias,
                    ).exists()
                )

    def test_equivalent_writing_paths_share_and_canonicalize_highlights(self):
        task = self.tasks[1]
        group = content.load_ee_equivalent_groups(1)[0]
        canonical = WritingSujet.objects.get(
            task=task,
            slug=content.ee_writing_sujet_slug(group.canonical),
        )
        alias = WritingSujet.objects.get(
            task=task,
            slug=content.ee_writing_sujet_slug(
                next(
                    member
                    for member in group.members
                    if member != group.canonical
                )
            ),
        )
        canonical_path = reverse(
            "study:writing_sujet_detail",
            args=[task.part.slug, task.slug, canonical.pk],
        )
        alias_path = reverse(
            "study:writing_sujet_detail",
            args=[task.part.slug, task.slug, alias.pk],
        )
        source_key = f"writing-sujet:{canonical.pk}:model-1"

        created = self.client.post(
            reverse("study:annotation_create"),
            {
                "kind": AnnotationKind.HIGHLIGHT,
                "quote": "Réponse",
                "start_offset": "0",
                "end_offset": "7",
                "prefix": "",
                "suffix": "",
                "source_path": f"{alias_path}?saved=1",
                "source_key": source_key,
                "source_title": "Sujet équivalent",
                "task_id": str(task.pk),
                "overlap_ids": "",
            },
        )

        self.assertEqual(created.status_code, 201)
        annotation = Annotation.objects.get(pk=created.json()["id"])
        self.assertEqual(annotation.source_path, canonical_path)
        for source_path in (canonical_path, alias_path):
            with self.subTest(source_path=source_path):
                response = self.client.get(
                    reverse("study:annotations_for_source"),
                    {"source_path": source_path},
                )
                self.assertEqual(
                    [row["id"] for row in response.json()["highlights"]],
                    [annotation.pk],
                )

        alias_edit_path = reverse(
            "study:writing_sujet_edit",
            args=[task.part.slug, task.slug, alias.pk],
        )
        canonical_edit_path = reverse(
            "study:writing_sujet_edit",
            args=[task.part.slug, task.slug, canonical.pk],
        )
        edited = self.client.post(
            reverse("study:annotation_create"),
            {
                "kind": AnnotationKind.HIGHLIGHT,
                "quote": "modèle",
                "start_offset": "8",
                "end_offset": "14",
                "prefix": "",
                "suffix": "",
                "source_path": alias_edit_path,
                "source_key": source_key,
                "source_title": "Édition équivalente",
                "task_id": str(task.pk),
                "overlap_ids": "",
            },
        )
        edit_annotation = Annotation.objects.get(pk=edited.json()["id"])
        self.assertEqual(edit_annotation.source_path, canonical_edit_path)
        response = self.client.get(
            reverse("study:annotations_for_source"),
            {"source_path": canonical_path},
        )
        self.assertEqual(
            {row["id"] for row in response.json()["highlights"]},
            {annotation.pk, edit_annotation.pk},
        )

    def test_dashboard_repeats_canonical_completion_for_every_occurrence(self):
        task = self.tasks[1]
        group = content.load_ee_equivalent_groups(1)[0]
        canonical = WritingSujet.objects.get(
            task=task,
            slug=content.ee_writing_sujet_slug(group.canonical),
        )
        WritingSujetCompletion.objects.create(
            user=self.user,
            sujet=canonical,
        )

        response = self.client.get(reverse("study:dashboard"))
        written = next(
            skill
            for skill in response.context["skills"]
            if skill["key"] == "ee"
        )

        self.assertEqual(
            written["detail"],
            f"{len(group.members)}/276 sujets",
        )
