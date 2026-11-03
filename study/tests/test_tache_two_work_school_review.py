import copy
import hashlib
import json

from django.test import SimpleTestCase

from study import catalogue, content_loader as content
from study.tache_two_dialogues import dialogue_response
from study.tests.eo2_review_fixtures import (
    DAILY_DUTIES_FOLLOWUP_FIELDS, INTERNAL_PAY_FOLLOWUP_FIELDS, INTERVIEW_CLOTHING_FOLLOWUP_FIELDS,
    ACCOMMODATION_FOLLOWUP_FIELDS,
    PUBLISHED_ARCHIVE_INDEX, RECRUITER_RICH_FOLLOWUP_FIELDS,
    SCHOOL_GROUPS, SESSION_EXTENT_FOLLOWUP_FIELDS,
    SURVEY_ROUTINE_FOLLOWUP_FIELDS,
    TRANSPORT_TRAVEL_GROUPS, WORK_COMPARISON_CLOSING_FIELDS, WORK_GROUPS,
    WORK_SCHOOL_GROUPS as REVIEWED_GROUPS,
    final_pass_projection, remove_followup_archives, remove_latest_review_archives,
)


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode(),
    ).hexdigest()


class WorkSchoolDialogueReviewTests(SimpleTestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        catalogue.clear_catalogue_cache()
        cls.dialogues = catalogue.tache_two_dialogues()
        cls.by_group = {row.group: row for row in cls.dialogues.values()}
        _, cls.themes = catalogue.tache_two_subject_themes()
        cls.raw = {
            row["group"]: row
            for path in (content.QUESTION_BANK_DIR / "dialogues").glob("*.json")
            for row in json.loads(path.read_text())["dialogues"]
        }
        cls.hints = json.loads(content.TACHE_TWO_SUBJECT_HINTS_PATH.read_text())["groups"]
        cls.history_document = json.loads(
            (content.QUESTION_BANK_DIR / "dialogue_history/locations.json").read_text(),
        )

    @classmethod
    def tearDownClass(cls):
        catalogue.clear_catalogue_cache()
        super().tearDownClass()

    def test_current_themes_keep_all_twenty_four_models_and_forty_seven_publications(self):
        for theme, groups, count in (
            ("travail", WORK_GROUPS, 28), ("ecole-etudes", SCHOOL_GROUPS, 19),
        ):
            rows = [row for key, row in self.dialogues.items() if self.themes[key] == theme]
            self.assertEqual({row.group for row in rows}, groups)
            self.assertEqual(len(rows), count)
            for row in rows:
                self.assertEqual(len(row.questions), 8)
                self.assertEqual(len(self.hints[row.group]), 8)
                self.assertIn("merci", row.closing.casefold())

    def test_dialogues_and_cues_outside_authorized_reviews_and_later_accommodation_changes_remain_published(self):
        reviewed = REVIEWED_GROUPS | TRANSPORT_TRAVEL_GROUPS | ACCOMMODATION_FOLLOWUP_FIELDS.keys()
        unrelated = {
            "dialogues": {key: row for key, row in self.raw.items() if key not in reviewed},
            "hints": {key: rows for key, rows in self.hints.items() if key not in reviewed},
        }
        self.assertEqual(
            fingerprint(unrelated),
            "908a24c5d012b4e75320da40cd3ef0fefee1c56eb2fe9fb744a8950c3bac04b9",
        )
        self.assertEqual(
            fingerprint(sorted((key, row["register"]) for key, row in self.raw.items())),
            "11b2868eb895bf97db1f6d38f4e757d9f2d2d0a0c859de9c3bad6e866c21e9d4",
        )

    def test_exact_previous_published_layouts_are_archived_without_internal_replies(self):
        snapshots = [
            self.history_document["groups"][group]["revisions"][PUBLISHED_ARCHIVE_INDEX[group]]
            for group in sorted(REVIEWED_GROUPS)
        ]
        self.assertEqual(
            fingerprint(snapshots),
            "520927a18855e58fe036fc03fba1c4cea18189be742bddbb70a3a02255e589bd",
        )
        for snapshot in snapshots:
            self.assertEqual(len(snapshot["questions"]), 8)
            for question in snapshot["questions"]:
                self.assertNotIn("answer", question)

    def test_every_earlier_archive_and_geographic_substitution_is_untouched(self):
        previous = copy.deepcopy(self.history_document)
        remove_latest_review_archives(previous)
        self.assertEqual(
            fingerprint(previous),
            "774c33725f0ef5bee59983fcc44f222c824abc6b3b3e75d5e680911e8e810a8d",
        )

    def test_none_of_the_twenty_four_learner_models_contains_examiner_replies(self):
        for group in REVIEWED_GROUPS:
            dialogue = self.by_group[group]
            value = dialogue_response(dialogue)
            self.assertEqual([a.idea for a in value.arguments], [q.question for q in dialogue.questions])
            self.assertTrue(all(
                not any((a.developpement, a.exemple, a.consequence)) for a in value.arguments
            ))
            self.assertFalse(value.position)
            self.assertFalse(value.position_claire)
            self.assertFalse(value.nuance)

    def test_career_rephrase_changes_only_the_requested_question_and_keeps_all_cues(self):
        group = "friend-planned-canadian-studies"
        row = copy.deepcopy(self.raw[group])
        self.assertEqual(
            row["questions"][3]["question"],
            "Qu'est-ce que cette formation apportera à ta carrière ?",
        )
        row["questions"][3]["question"] = "<reviewed-career-question>"
        self.assertEqual(
            fingerprint({"dialogue": row, "hints": self.hints[group]}),
            "a0e0e4f557fe556b7976f8292d0d064c133320f5003dfec7c9d2192590a5f6f4",
        )
        self.assertEqual(
            {key for key, row in self.dialogues.items() if row.group == group},
            {"tache2:octobre:batch-09:subject-42"},
        )

    def test_career_rephrase_preserves_other_models_except_authorized_later_changes(self):
        group = "friend-planned-canadian-studies"
        edited = (
            {group} | SURVEY_ROUTINE_FOLLOWUP_FIELDS.keys() | SESSION_EXTENT_FOLLOWUP_FIELDS.keys()
            | WORK_COMPARISON_CLOSING_FIELDS.keys()
            | DAILY_DUTIES_FOLLOWUP_FIELDS.keys()
            | RECRUITER_RICH_FOLLOWUP_FIELDS.keys()
            | INTERNAL_PAY_FOLLOWUP_FIELDS.keys()
            | INTERVIEW_CLOTHING_FOLLOWUP_FIELDS.keys()
            | ACCOMMODATION_FOLLOWUP_FIELDS.keys()
        )
        self.assertEqual(len(self.raw.keys() - edited), 154)
        self.assertEqual(
            fingerprint({
                "dialogues": {g: row for g, row in self.raw.items() if g not in edited},
                "hints": {g: cues for g, cues in self.hints.items() if g not in edited},
            }),
            "8f81644b87d736eceaaf8867bb171f8aa3b64a06d797b36e440a9dd9d0032c22",
        )

    def test_career_rephrase_archives_the_published_layout_without_replies_or_older_changes(self):
        group = "friend-planned-canadian-studies"
        revisions = self.history_document["groups"][group]["revisions"]
        self.assertEqual(len(revisions), 4)
        self.assertEqual(
            fingerprint(revisions[3]),
            "700180a0ab97570a826e4e9b8dc2b9fb93e762c99d9c2e21d7e8d9cf10529c31",
        )
        self.assertTrue(all("answer" not in q for q in revisions[3]["questions"]))
        previous = copy.deepcopy(self.history_document)
        previous["groups"][group]["revisions"].pop()
        for changed in (
            SURVEY_ROUTINE_FOLLOWUP_FIELDS | SESSION_EXTENT_FOLLOWUP_FIELDS
            | WORK_COMPARISON_CLOSING_FIELDS
            | DAILY_DUTIES_FOLLOWUP_FIELDS
            | RECRUITER_RICH_FOLLOWUP_FIELDS
            | INTERNAL_PAY_FOLLOWUP_FIELDS
            | INTERVIEW_CLOTHING_FOLLOWUP_FIELDS
        ):
            previous["groups"][changed]["revisions"] = (
                previous["groups"][changed]["revisions"][:PUBLISHED_ARCHIVE_INDEX[changed] + 1]
            )
        remove_followup_archives(previous, ACCOMMODATION_FOLLOWUP_FIELDS)
        self.assertEqual(
            fingerprint(previous),
            "a8e2f902a91d7c1c16cbc506cae2f6f65d9e5a38f7e8e2a8d5e403a3c0c7917d",
        )

    def test_survey_replaces_the_extra_activity_question_with_a_commute_after_institution(self):
        group = "french-class-survey-francophone-student"
        row = self.by_group[group]
        self.assertEqual(
            row.questions[2].question,
            "Comment vous rendez-vous en cours, et combien de temps dure le trajet ?",
        )
        self.assertIsNone(row.questions[2].follow_up_to)
        self.assertIn("le bus", row.questions[2].answer)
        self.assertIn("vingt minutes", row.questions[2].answer)
        self.assertEqual(sum(q.topic == "Loisirs" for q in row.questions), 2)
        self.assertEqual(row.questions[5].follow_up_to, 5)
        self.assertIn("travel to classes", row.note)
        self.assertEqual(
            self.hints[group][2]["english"], "Transport to classes and journey time",
        )

    def test_survey_retains_all_seven_other_questions_replies_and_cues_when_reordered(self):
        group = "french-class-survey-francophone-student"
        row = copy.deepcopy(self.raw[group])
        original_order = (0, 1, 3, 4, 5, 6, 2, 7)
        row["questions"] = [row["questions"][index] for index in original_order]
        row["questions"][4]["follow_up_to"] = 4
        row["questions"][6] = "<replaced-survey-question>"
        row["note"] = "<reviewed-survey-note>"
        cues = [copy.deepcopy(self.hints[group][index]) for index in original_order]
        cues[6] = "<replaced-survey-cue>"
        self.assertEqual(
            fingerprint({"dialogue": row, "hints": cues}),
            "3e88f3b101ec3bf1d23beccea4c3895209847bca460b309ea575393ffe1db259",
        )
        projected = final_pass_projection(self.raw, self.hints)[group]
        self.assertEqual(projected["dialogue"]["questions"][0]["question"], "<final-reviewed-field>")
        self.assertEqual(projected["dialogue"]["questions"][2]["question"], "<final-reviewed-field>")
        self.assertEqual(projected["hints"][0]["english"], "<final-reviewed-field>")
        self.assertEqual(projected["hints"][2]["english"], "<final-reviewed-field>")

    def test_survey_replacement_preserves_other_models_except_authorized_later_changes(self):
        group = "french-class-survey-francophone-student"
        edited = (
            {group} | SESSION_EXTENT_FOLLOWUP_FIELDS.keys() | WORK_COMPARISON_CLOSING_FIELDS.keys()
            | DAILY_DUTIES_FOLLOWUP_FIELDS.keys()
            | RECRUITER_RICH_FOLLOWUP_FIELDS.keys()
            | INTERNAL_PAY_FOLLOWUP_FIELDS.keys()
            | INTERVIEW_CLOTHING_FOLLOWUP_FIELDS.keys()
            | ACCOMMODATION_FOLLOWUP_FIELDS.keys()
        )
        self.assertEqual(len(self.raw.keys() - edited), 155)
        self.assertEqual(
            fingerprint({
                "dialogues": {g: row for g, row in self.raw.items() if g not in edited},
                "hints": {g: cues for g, cues in self.hints.items() if g not in edited},
            }),
            "18b1bf454de34a2d3ee91e4df04df7e666e28e9121f8849bd37654ae96072539",
        )
        self.assertEqual(
            {key for key, row in self.dialogues.items() if row.group == group},
            {"tache2:decembre:batch-08:subject-36"},
        )

    def test_survey_published_layout_is_archived_without_replies_or_older_history_changes(self):
        group = "french-class-survey-francophone-student"
        revisions = self.history_document["groups"][group]["revisions"]
        self.assertEqual(len(revisions), 4)
        self.assertEqual(
            fingerprint(revisions[3]),
            "ff70342012491263c1ccb003225dd2e7034d2130834208d9a3deae5e79ceb5f8",
        )
        self.assertTrue(all("answer" not in q for q in revisions[3]["questions"]))
        previous = copy.deepcopy(self.history_document)
        previous["groups"][group]["revisions"].pop()
        for changed in (
            SESSION_EXTENT_FOLLOWUP_FIELDS | WORK_COMPARISON_CLOSING_FIELDS
            | DAILY_DUTIES_FOLLOWUP_FIELDS
            | RECRUITER_RICH_FOLLOWUP_FIELDS
            | INTERNAL_PAY_FOLLOWUP_FIELDS
            | INTERVIEW_CLOTHING_FOLLOWUP_FIELDS
        ):
            previous["groups"][changed]["revisions"] = (
                previous["groups"][changed]["revisions"][:PUBLISHED_ARCHIVE_INDEX[changed] + 1]
            )
        remove_followup_archives(previous, ACCOMMODATION_FOLLOWUP_FIELDS)
        self.assertEqual(
            fingerprint(previous),
            "d7cf731e33b3d70132645c2bdbf1c5b5990330fb5acf34841dde668401e000c9",
        )

    def test_session_extent_rephrase_changes_only_the_requested_question(self):
        group = "calgary-university-adult-language-courses"
        row = copy.deepcopy(self.raw[group])
        question = row["questions"][4]["question"]
        self.assertEqual(
            question,
            "Une session s'étend sur combien de semaines, "
            "et combien d'heures de cours y a-t-il par semaine ?",
        )
        previous = self.history_document["groups"][group]["revisions"][3]["questions"][4]["question"]
        self.assertEqual(question.split(", ", 1)[1], previous.split(", ", 1)[1])
        row["questions"][4]["question"] = "<reviewed-session-question>"
        self.assertEqual(
            fingerprint({"dialogue": row, "hints": self.hints[group]}),
            "853be3e45497ab97003184d8b7ef5272cd398cff21497773acfc8c04544d2c44",
        )

    def test_session_extent_rephrase_preserves_other_models_except_authorized_later_changes(self):
        group = "calgary-university-adult-language-courses"
        edited = (
            {group} | WORK_COMPARISON_CLOSING_FIELDS.keys() | DAILY_DUTIES_FOLLOWUP_FIELDS.keys()
            | RECRUITER_RICH_FOLLOWUP_FIELDS.keys()
            | INTERNAL_PAY_FOLLOWUP_FIELDS.keys()
            | INTERVIEW_CLOTHING_FOLLOWUP_FIELDS.keys()
            | ACCOMMODATION_FOLLOWUP_FIELDS.keys()
        )
        self.assertEqual(len(self.raw.keys() - edited), 156)
        self.assertEqual(
            fingerprint({
                "dialogues": {g: row for g, row in self.raw.items() if g not in edited},
                "hints": {g: cues for g, cues in self.hints.items() if g not in edited},
            }),
            "52aafdaa22eb42c70413483a2f47b40237e7f96afbab7686c24da9bc7fbbae0a",
        )
        self.assertEqual(
            {key for key, row in self.dialogues.items() if row.group == group},
            {"tache2:decembre:batch-09:subject-45"},
        )

    def test_session_extent_archives_the_published_layout_without_replies_or_older_changes(self):
        group = "calgary-university-adult-language-courses"
        revisions = self.history_document["groups"][group]["revisions"]
        self.assertEqual(len(revisions), 4)
        self.assertEqual(
            fingerprint(revisions[3]),
            "8f4ef04975a1a1a05320fe056a4222273fa5ed1da3bf34790d599f13d16d407a",
        )
        self.assertTrue(all("answer" not in q for q in revisions[3]["questions"]))
        previous = copy.deepcopy(self.history_document)
        previous["groups"][group]["revisions"].pop()
        for changed in (
            WORK_COMPARISON_CLOSING_FIELDS | DAILY_DUTIES_FOLLOWUP_FIELDS
            | RECRUITER_RICH_FOLLOWUP_FIELDS
            | INTERNAL_PAY_FOLLOWUP_FIELDS
            | INTERVIEW_CLOTHING_FOLLOWUP_FIELDS
        ):
            previous["groups"][changed]["revisions"] = (
                previous["groups"][changed]["revisions"][:PUBLISHED_ARCHIVE_INDEX[changed] + 1]
            )
        remove_followup_archives(previous, ACCOMMODATION_FOLLOWUP_FIELDS)
        self.assertEqual(
            fingerprint(previous),
            "92ecea7474f4b7516ff605f7e93713a2772a2c2002d6f77110c77cad3d8a9064",
        )

    def test_work_comparison_closing_changes_only_the_thanks_not_questions_replies_note_or_cues(self):
        group = "canadian-work-hours-home-country-comparison"
        row = copy.deepcopy(self.raw[group])
        self.assertEqual(
            row["closing"],
            "Merci, Pierre ! C'est intéressant de comparer nos expériences professionnelles.",
        )
        row["closing"] = "<reviewed-work-closing>"
        self.assertEqual(
            fingerprint({"dialogue": row, "hints": self.hints[group]}),
            "79e85f144b4263f32056f92692693bd9c2201526d841d1e527d6c5149b22a155",
        )
        self.assertIn("not nationwide Canadian rules", row["note"])

    def test_work_comparison_closing_preserves_other_models_except_the_authorized_duties_rephrase(self):
        group = "canadian-work-hours-home-country-comparison"
        edited = (
            {group} | DAILY_DUTIES_FOLLOWUP_FIELDS.keys() | RECRUITER_RICH_FOLLOWUP_FIELDS.keys()
            | INTERNAL_PAY_FOLLOWUP_FIELDS.keys()
            | INTERVIEW_CLOTHING_FOLLOWUP_FIELDS.keys()
            | ACCOMMODATION_FOLLOWUP_FIELDS.keys()
        )
        self.assertEqual(len(self.raw.keys() - edited), 157)
        self.assertEqual(
            fingerprint({
                "dialogues": {g: row for g, row in self.raw.items() if g not in edited},
                "hints": {g: cues for g, cues in self.hints.items() if g not in edited},
            }),
            "afdae0a41521fc2aca3c49863c9e0a3f503cc5ce6b881d2bf52ca2bec5178ef9",
        )
        self.assertEqual(
            {key for key, row in self.dialogues.items() if row.group == group},
            {
                "tache2:fevrier:batch-05:subject-25", "tache2:mars:batch-03:subject-15",
                "tache2:septembre:batch-03:subject-15", "tache2:octobre:batch-02:subject-10",
            },
        )

    def test_work_comparison_closing_archives_exact_published_layout_without_older_changes(self):
        group = "canadian-work-hours-home-country-comparison"
        revisions = self.history_document["groups"][group]["revisions"]
        self.assertEqual(len(revisions), 4)
        self.assertEqual(
            fingerprint(revisions[3]),
            "00cab633eae02aec8898a4183f1001153b3572c729e32c2c07be9d567c1d37fc",
        )
        self.assertTrue(all("answer" not in q for q in revisions[3]["questions"]))
        previous = copy.deepcopy(self.history_document)
        previous["groups"][group]["revisions"].pop()
        for changed in (
            DAILY_DUTIES_FOLLOWUP_FIELDS | RECRUITER_RICH_FOLLOWUP_FIELDS
            | INTERNAL_PAY_FOLLOWUP_FIELDS
            | INTERVIEW_CLOTHING_FOLLOWUP_FIELDS
        ):
            previous["groups"][changed]["revisions"] = (
                previous["groups"][changed]["revisions"][:PUBLISHED_ARCHIVE_INDEX[changed] + 1]
            )
        remove_followup_archives(previous, ACCOMMODATION_FOLLOWUP_FIELDS)
        self.assertEqual(
            fingerprint(previous),
            "a558ac280c91a75fe9c88bf345b3dfada6c8a3b4a0d80120af797827c308b96d",
        )

    def test_daily_duties_rephrase_changes_only_the_question_not_reply_condition_or_cues(self):
        group = "former-colleague-new-job-to-change-employment"
        row = copy.deepcopy(self.raw[group])
        self.assertEqual(
            row["questions"][1]["question"], "Quelles tâches remplissent tes journées ?",
        )
        row["questions"][1]["question"] = "<reviewed-duties-question>"
        self.assertEqual(
            fingerprint({"dialogue": row, "hints": self.hints[group]}),
            "12960e30b5c7e94cae349c04b059c15f254e66796263e88ce026dd5a39bd43a5",
        )
        projected = final_pass_projection(self.raw, self.hints)[group]
        self.assertEqual(projected["dialogue"]["questions"][1]["question"], "<final-reviewed-field>")
        self.assertEqual(projected["dialogue"]["questions"][4]["question"], "<final-reviewed-field>")

    def test_daily_duties_rephrase_preserves_other_models_except_the_authorized_recruiter_update(self):
        group = "former-colleague-new-job-to-change-employment"
        edited = (
            {group} | RECRUITER_RICH_FOLLOWUP_FIELDS.keys() | INTERNAL_PAY_FOLLOWUP_FIELDS.keys()
            | INTERVIEW_CLOTHING_FOLLOWUP_FIELDS.keys()
            | ACCOMMODATION_FOLLOWUP_FIELDS.keys()
        )
        self.assertEqual(len(self.raw.keys() - edited), 158)
        self.assertEqual(
            fingerprint({
                "dialogues": {g: row for g, row in self.raw.items() if g not in edited},
                "hints": {g: cues for g, cues in self.hints.items() if g not in edited},
            }),
            "cbe2eaaaacab36d4c7d60acd65526ac158d41769ce40c72fddb682864a725e54",
        )
        self.assertEqual(
            {key for key, row in self.dialogues.items() if row.group == group},
            {"tache2:mai:batch-05:subject-24", "tache2:novembre:batch-02:subject-09"},
        )

    def test_daily_duties_rephrase_archives_published_layout_without_replies_or_older_changes(self):
        group = "former-colleague-new-job-to-change-employment"
        revisions = self.history_document["groups"][group]["revisions"]
        self.assertEqual(len(revisions), 3)
        self.assertEqual(
            fingerprint(revisions[2]),
            "bfecb2f2d2c04ade6baaaf50f0882ac177a8e1b91fcc42fecbb69e92eca15bed",
        )
        self.assertTrue(all("answer" not in q for q in revisions[2]["questions"]))
        previous = copy.deepcopy(self.history_document)
        previous["groups"][group]["revisions"].pop()
        for changed in (
            RECRUITER_RICH_FOLLOWUP_FIELDS | INTERNAL_PAY_FOLLOWUP_FIELDS
            | INTERVIEW_CLOTHING_FOLLOWUP_FIELDS
        ):
            previous["groups"][changed]["revisions"] = (
                previous["groups"][changed]["revisions"][:PUBLISHED_ARCHIVE_INDEX[changed] + 1]
            )
        remove_followup_archives(previous, ACCOMMODATION_FOLLOWUP_FIELDS)
        self.assertEqual(
            fingerprint(previous),
            "6d8b644680f6b050b6cd1f27d5694480fc55b4faf367726958c4a27e362b69d6",
        )

    def test_richer_recruiter_questions_keep_eight_precise_preparation_goals(self):
        group = "recruiter-scheduled-interview-preparation"
        row = self.by_group[group]
        self.assertEqual(len(row.questions), 8)
        expected = {
            1: "À quelle heure dois-je me présenter, et combien de temps durera l'entretien ?",
            3: "Avec qui aurai-je l'entretien, et quelles fonctions ces personnes occupent-elles dans l'entreprise ?",
            5: "Quels aspects de mon expérience ou quelles compétences souhaitez-vous particulièrement approfondir pendant l'entretien ?",
            6: "Pour la mise en situation, quel type de tâche devrai-je réaliser, et faut-il préparer quelque chose à l'avance ?",
        }
        for index, text in expected.items():
            self.assertEqual(row.questions[index].question, text)
        self.assertEqual(row.questions[6].follow_up_to, 5)
        self.assertEqual(row.questions[6].topic, row.questions[4].topic)
        self.assertIn("task details or advance preparation", row.questions[6].condition)
        self.assertIn("quarante-cinq minutes", row.questions[1].answer)
        self.assertIn("relation avec les clients", row.questions[5].answer)
        self.assertIn("already scheduled", row.note)
        self.assertIn("skip details already supplied in the invitation", row.note)
        self.assertEqual(
            fingerprint(final_pass_projection(self.raw, self.hints)[group]),
            "28b42620902c40fb89203c9a6ad68d2138a640246700c876015500a5173a5100",
        )
        old = self.history_document["groups"][group]["revisions"][3]["questions"]
        for before, after in ((0, 0), (2, 2), (5, 4), (7, 7)):
            self.assertEqual(old[before]["question"], row.questions[after].question)

    def test_richer_recruiter_preserves_models_except_authorized_later_changes_and_keeps_coordonner(self):
        group = "recruiter-scheduled-interview-preparation"
        edited = (
            {group} | INTERNAL_PAY_FOLLOWUP_FIELDS.keys() | INTERVIEW_CLOTHING_FOLLOWUP_FIELDS.keys()
            | ACCOMMODATION_FOLLOWUP_FIELDS.keys()
        )
        self.assertEqual(
            fingerprint({
                "dialogues": {g: row for g, row in self.raw.items() if g not in edited},
                "hints": {g: cues for g, cues in self.hints.items() if g not in edited},
            }),
            "3a3e9d2f8a428b28ab7c58cf9a824f47e0e48ed5f17073ed182d599c7e5ebc5b",
        )
        self.assertEqual(
            self.by_group["colleague-internal-job-change"].questions[1].question,
            "Pour coordonner ces projets, avec quels services travaillez-vous le plus souvent ?",
        )
        self.assertEqual(
            {key for key, row in self.dialogues.items() if row.group == group},
            {"tache2:juin:batch-02:subject-06"},
        )

    def test_richer_recruiter_archives_exact_published_layout_without_older_changes(self):
        group = "recruiter-scheduled-interview-preparation"
        revisions = self.history_document["groups"][group]["revisions"]
        self.assertEqual(len(revisions), 4)
        self.assertEqual(
            fingerprint(revisions[3]),
            "5a409f255eb54c02fbe5a7b6cbdf12bf367ff6316e6e08ad50cdefa8d9de885c",
        )
        self.assertTrue(all("answer" not in q for q in revisions[3]["questions"]))
        previous = copy.deepcopy(self.history_document)
        previous["groups"][group]["revisions"].pop()
        for changed in INTERNAL_PAY_FOLLOWUP_FIELDS | INTERVIEW_CLOTHING_FOLLOWUP_FIELDS:
            previous["groups"][changed]["revisions"] = (
                previous["groups"][changed]["revisions"][:PUBLISHED_ARCHIVE_INDEX[changed] + 1]
            )
        remove_followup_archives(previous, ACCOMMODATION_FOLLOWUP_FIELDS)
        self.assertEqual(
            fingerprint(previous),
            "acadf0e936dae1584f28fd2227c34d30bf4e9a5c1bfc28cbb222d8b723eba9a8",
        )

    def test_internal_pay_replacements_preserve_every_other_field_and_keep_coordonner(self):
        group = "colleague-internal-job-change"
        row = copy.deepcopy(self.raw[group])
        hints = copy.deepcopy(self.hints[group])
        self.assertEqual(
            row["questions"][4]["question"],
            "Si ce n'est pas indiscret, votre salaire a-t-il augmenté avec ce changement de poste et, si oui, d'environ combien ?",
        )
        self.assertEqual(
            row["questions"][5]["question"],
            "Quel montant peut atteindre cette prime, et comment est-elle calculée ?",
        )
        self.assertEqual(row["questions"][5]["follow_up_to"], 5)
        self.assertIn("amount or calculation details", row["questions"][5]["condition"])
        self.assertEqual(
            row["questions"][1]["question"],
            "Pour coordonner ces projets, avec quels services travaillez-vous le plus souvent ?",
        )
        for index, field in ((4, "question"), (5, "question"), (5, "condition")):
            row["questions"][index][field] = "<reviewed-pay-field>"
        for index in (4, 5):
            for language in ("french", "english"):
                hints[index][language] = "<reviewed-pay-field>"
        self.assertEqual(
            fingerprint({"dialogue": row, "hints": hints}),
            "fd45e86123b0bcc91abcaf92c41afd37fc78447c72bed95379385b872df86cad",
        )

    def test_internal_pay_update_preserves_other_models_except_authorized_later_changes(self):
        group = "colleague-internal-job-change"
        edited = (
            {group} | INTERVIEW_CLOTHING_FOLLOWUP_FIELDS.keys() | ACCOMMODATION_FOLLOWUP_FIELDS.keys()
        )
        self.assertEqual(
            fingerprint({
                "dialogues": {g: row for g, row in self.raw.items() if g not in edited},
                "hints": {g: cues for g, cues in self.hints.items() if g not in edited},
            }),
            "87e6ea9ce156bde0baaf31d06c61e92f3dced9ca4faf02d04840ca1cf398a905",
        )
        self.assertEqual(
            {key for key, row in self.dialogues.items() if row.group == group},
            {"tache2:juin:batch-03:subject-15"},
        )

    def test_internal_pay_update_archives_published_layout_without_touching_older_history(self):
        group = "colleague-internal-job-change"
        revisions = self.history_document["groups"][group]["revisions"]
        self.assertEqual(len(revisions), 3)
        self.assertEqual(
            fingerprint(revisions[2]),
            "8f4b18109300a92c91a8f016ca20e64be6ee5a512e55b9e816ab91f1769c1ae2",
        )
        self.assertTrue(all("answer" not in q for q in revisions[2]["questions"]))
        previous = copy.deepcopy(self.history_document)
        previous["groups"][group]["revisions"].pop()
        for changed in INTERVIEW_CLOTHING_FOLLOWUP_FIELDS:
            previous["groups"][changed]["revisions"] = (
                previous["groups"][changed]["revisions"][:PUBLISHED_ARCHIVE_INDEX[changed] + 1]
            )
        remove_followup_archives(previous, ACCOMMODATION_FOLLOWUP_FIELDS)
        self.assertEqual(
            fingerprint(previous),
            "af47db3e5a94173725439f4c32fe4c9466d5ae664a3dffebd661f23640a7a3fb",
        )

    def test_interview_clothing_followup_gives_actionable_advice_without_an_inside_contact(self):
        group = "friend-upcoming-job-interview-advice"
        dialogue = self.by_group[group]
        question = dialogue.questions[4]
        self.assertEqual(
            question.question,
            "Y a-t-il des vêtements ou des accessoires à éviter pour ne pas faire mauvaise impression ?",
        )
        self.assertEqual(question.follow_up_to, 4)
        self.assertEqual(question.topic, dialogue.questions[3].topic)
        self.assertEqual(question.condition, "If clothing advice does not yet explain what to avoid.")
        self.assertIn("J'éviterais", question.answer)
        self.assertIn("accessoires trop voyants", question.answer)
        self.assertEqual(self.hints[group][4], {
            "french": "Vêtements et accessoires à éviter pour l'entretien",
            "english": "Clothes and accessories to avoid for the interview",
        })
        projection = {"dialogue": copy.deepcopy(self.raw[group]), "hints": copy.deepcopy(self.hints[group])}
        for path in INTERVIEW_CLOTHING_FOLLOWUP_FIELDS[group]:
            node = projection
            for key in path[:-1]:
                node = node[key]
            node[path[-1]] = "<reviewed-clothing-field>"
        self.assertEqual(
            fingerprint(projection),
            "58dd28f4f13f8b7ac364d97a0f85c971d0c34314663c31482ea0d7cdaa0475bb",
        )

    def test_interview_clothing_replacement_preserves_other_models_except_later_accommodation_changes(self):
        group = "friend-upcoming-job-interview-advice"
        edited = {group} | ACCOMMODATION_FOLLOWUP_FIELDS.keys()
        self.assertEqual(
            fingerprint({
                "dialogues": {g: row for g, row in self.raw.items() if g not in edited},
                "hints": {g: cues for g, cues in self.hints.items() if g not in edited},
            }),
            "0166a25341c3698adc08d4ca51fcacc021a2b1fb3b5b6a647bc4b49333f9a7e2",
        )
        self.assertEqual(
            {key for key, row in self.dialogues.items() if row.group == group},
            {
                "tache2:juillet:batch-08:subject-34",
                "tache2:septembre:batch-05:subject-21",
                "tache2:septembre:batch-06:subject-26",
            },
        )

    def test_interview_clothing_replacement_archives_only_the_published_layout(self):
        group = "friend-upcoming-job-interview-advice"
        revisions = self.history_document["groups"][group]["revisions"]
        self.assertEqual(len(revisions), 3)
        self.assertEqual(
            fingerprint(revisions[2]),
            "ff68273ff972832965ecc5853dde10ad45e50b0df403039b2f2f44db068d1b88",
        )
        self.assertTrue(all("answer" not in question for question in revisions[2]["questions"]))
        previous = copy.deepcopy(self.history_document)
        previous["groups"][group]["revisions"].pop()
        remove_followup_archives(previous, ACCOMMODATION_FOLLOWUP_FIELDS)
        self.assertEqual(
            fingerprint(previous),
            "9084fa89a2ec63042dd893686661571b92ed878c25b245937a5d169e3b366ff8",
        )

    def test_first_day_has_an_actual_difficulty_and_a_response_to_it(self):
        row = self.by_group["friend-first-workday-report"]
        self.assertIn("première journée", row.questions[0].question)
        self.assertIn("premières tâches", row.questions[4].question)
        self.assertIn("quelqu'un t'a montré", row.questions[4].question)
        self.assertNotIn("logiciel", row.questions[4].question)
        self.assertIn("modifier une commande", row.questions[5].answer)
        self.assertNotIn("rappelé", row.questions[5].answer)
        self.assertEqual(row.questions[6].follow_up_to, 6)
        self.assertIn("dans ce cas-là", row.questions[6].question)
        self.assertIn("rappelé le client ensemble", row.questions[6].answer)
        self.assertNotIn("encourageant", row.closing)

    def test_recruiter_and_friend_are_asked_different_preparation_questions(self):
        recruiter = self.by_group["recruiter-scheduled-interview-preparation"]
        friend = self.by_group["friend-upcoming-job-interview-advice"]
        self.assertIn("sur place ou à distance", recruiter.questions[0].question)
        self.assertIn("mise en situation", recruiter.questions[4].answer)
        self.assertEqual(recruiter.questions[6].follow_up_to, 5)
        self.assertIn("préparer quelque chose à l'avance", recruiter.questions[6].question)
        self.assertIn("CV", recruiter.questions[7].question)
        self.assertIn("motivation ou mes points faibles", friend.questions[2].question)
        self.assertIn("question me surprend", friend.questions[5].question)
        self.assertIn("reformuler", friend.questions[5].answer)
        self.assertNotIn("questions du recruteur", recruiter.questions[6].question)

    def test_association_work_explores_actual_work_without_assuming_unpaid_status(self):
        row = self.by_group["friend-association-work-experience"]
        self.assertIn("principales tâches", row.questions[1].question)
        self.assertEqual(row.questions[2].follow_up_to, 2)
        self.assertIn("bénévole se désiste", row.questions[2].question)
        self.assertIn("adaptons l'activité", row.questions[2].answer)
        self.assertIn("rémunéré", row.questions[6].question)
        self.assertIn("bénévolement", row.questions[6].question)
        self.assertIn("emploi salarié", row.questions[6].answer)
        self.assertIn("sentiment d'être utile", row.questions[7].question)

    def test_internal_move_keeps_coordination_remote_work_and_bonus_criteria_distinct(self):
        row = self.by_group["colleague-internal-job-change"]
        self.assertIn("coordonne les projets", row.questions[0].answer)
        self.assertNotIn("service client", row.questions[0].answer)
        self.assertIn("avec quels services", row.questions[1].question)
        self.assertIn("télétravail", row.questions[3].question)
        self.assertIn("décision urgente", row.questions[3].question)
        self.assertNotIn("délais", row.questions[4].answer)
        self.assertEqual(row.questions[5].follow_up_to, 5)
        self.assertIn("montant", row.questions[5].question)
        self.assertIn("calculée", row.questions[5].question)
        self.assertIn("5 % du salaire annuel", row.questions[5].answer)

    def test_newcomer_conditions_are_advertised_examples_not_countrywide_promises(self):
        row = self.by_group["newcomer-canada-friend-job-market"]
        self.assertIn("profils de développeurs", row.questions[0].question)
        self.assertIn("tests techniques", row.questions[3].question)
        self.assertIn("IRCC", row.questions[4].answer)
        self.assertIn("Service Canada", row.questions[5].answer)
        self.assertIn("brut", row.questions[6].question)
        self.assertIn("annuel", row.questions[6].question)
        for detail in ("sur place", "hybride", "télétravail"):
            self.assertIn(detail, row.questions[7].question)
        self.assertIn("salary figures are illustrative", row.note)

    def test_private_teacher_and_school_separate_method_qualification_and_booking(self):
        private = self.by_group["newcomer-canada-private-french-teacher"]
        school = self.by_group["language-school-new-language"]
        self.assertIn("formation avez-vous suivie", private.questions[0].question)
        self.assertIn("mieux parler au quotidien", private.questions[1].question)
        self.assertIn("rejouons la conversation", private.questions[1].answer)
        self.assertIn("niveau au départ", private.questions[2].question)
        self.assertIn("annuler ou déplacer", private.questions[7].question)
        self.assertEqual(private.questions[7].follow_up_to, 7)
        self.assertIn("formation", school.questions[2].question)
        self.assertIn("jeux de rôle", school.questions[3].question)
        self.assertIn("sur place ou en ligne", school.questions[4].question)

    def test_school_and_parent_information_stays_with_the_actual_interlocutor(self):
        neighbour = self.by_group["edmonton-newcomer-neighbor-schools"]
        parent = self.by_group["parent-after-school-activity-advice"]
        self.assertIn("D'après votre expérience", neighbour.questions[3].question)
        self.assertIn("nouveaux élèves", neighbour.questions[4].question)
        self.assertIsNone(neighbour.questions[4].follow_up_to)
        self.assertIn("conseil scolaire", neighbour.questions[0].answer)
        self.assertIn("faites confirmer la liste", neighbour.questions[7].answer)
        self.assertIn("D'après ce que vous avez vu", parent.questions[4].question)
        self.assertIn("j'ai vu l'animatrice", parent.questions[4].answer)
        self.assertIn("tarifs actuels", parent.questions[7].answer)

    def test_child_stay_and_study_project_use_experience_not_guaranteed_admission(self):
        stay = self.by_group["friend-child-language-stay-abroad"]
        project = self.by_group["friend-planned-canadian-studies"]
        self.assertIn("Tom est-il parti", stay.questions[2].question)
        self.assertIn("combien de temps", stay.questions[2].question)
        self.assertIn("hébergement logeait Tom", stay.questions[4].question)
        self.assertEqual(stay.questions[5].follow_up_to, 5)
        self.assertIn("il nous disait", stay.questions[5].answer.lower())
        self.assertIn("Quel programme", project.questions[0].question)
        self.assertIn("ville", project.questions[1].question)
        self.assertIn("conditionnelle", project.questions[4].answer)
        self.assertIn("si je l'obtiens", project.questions[5].answer)
        self.assertNotIn("maîtrise", project.questions[3].question)

    def test_game_and_survey_establish_format_before_following_the_reply(self):
        game = self.by_group["french-teacher-language-school-student-game"]
        survey = self.by_group["french-class-survey-francophone-student"]
        self.assertIn("principe du jeu", game.questions[0].question)
        self.assertIn("niveaux", game.questions[1].question)
        self.assertEqual(game.questions[2].follow_up_to, 1)
        self.assertEqual(game.questions[3].follow_up_to, 1)
        self.assertIn("points", game.questions[3].question)
        self.assertIn("date", game.questions[5].question)
        self.assertIn("où la pratiquez-vous", survey.questions[6].question)
        self.assertEqual(survey.questions[5].follow_up_to, 5)
        self.assertIn("cette activité", survey.questions[5].question)
        self.assertNotIn("chorale", survey.questions[6].question)
