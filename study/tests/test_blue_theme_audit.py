import hashlib
import json
from pathlib import Path

from django.test import SimpleTestCase

from study import catalogue, content_loader as content


def fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode(),
    ).hexdigest()


def visible(model):
    return {
        "group": model["group"], "opening": model["opening"], "closing": model["closing"],
        "questions": [
            {key: value for key, value in row.items() if key != "answer"}
            for row in model["questions"]
        ],
    }


class BlueThemeAuditTests(SimpleTestCase):
    def setUp(self):
        catalogue.clear_catalogue_cache()
        self.addCleanup(catalogue.clear_catalogue_cache)
        self.manifest = json.loads(
            Path(__file__).with_name("blue_audit_fixtures.json").read_text(),
        )
        self.raw = {
            row["group"]: row
            for path in (content.QUESTION_BANK_DIR / "dialogues").glob("*.json")
            for row in json.loads(path.read_text())["dialogues"]
        }
        self.hints = json.loads(content.TACHE_TWO_SUBJECT_HINTS_PATH.read_text())["groups"]

    def test_all_nine_blue_themes_and_every_equivalent_have_a_recorded_review(self):
        self.assertEqual({slug: len(groups) for slug, groups in self.manifest["themes"].items()}, {
            "travail": 13, "ecole-etudes": 11, "transports": 11,
            "voyages": 15, "sport": 11, "arts-loisirs": 15,
            "fetes": 13, "escapades-tourisme": 7, "culture-medias": 11,
        })
        reviewed = self.manifest["reviewed"]
        self.assertEqual(len(reviewed), 107)
        self.assertEqual(set(reviewed), set().union(*map(set, self.manifest["themes"].values())))
        _, mapping = catalogue.tache_two_subject_themes()
        dialogues = catalogue.tache_two_dialogues()
        for slug, groups in self.manifest["themes"].items():
            actual = {row.group for key, row in dialogues.items() if mapping[key] == slug}
            self.assertEqual(actual, set(groups))
        for group, audit in reviewed.items():
            with self.subTest(group=group):
                self.assertEqual(fingerprint(self.raw[group]), audit["after_sha"])
                self.assertEqual(fingerprint(self.hints[group]), audit["after_hints_sha"])
                for field in ("objective", "known", "reason"):
                    self.assertTrue(audit[field].strip())
                if not audit["changed"]:
                    self.assertEqual(audit["before_sha"], audit["after_sha"])
                if not audit["hints_changed"]:
                    self.assertEqual(audit["before_hints_sha"], audit["after_hints_sha"])
                self.assertEqual(len(self.raw[group]["questions"]), 8)

    def test_substantive_scenario_fixes_remain_grounded_in_the_prompt_and_replies(self):
        for regression in self.manifest["regressions"]:
            with self.subTest(**regression):
                if regression["field"] == "hints":
                    cues = self.hints[regression["group"]]
                    self.assertEqual(len(cues), regression["expected_count"])
                    for language in ("french", "english"):
                        self.assertEqual(
                            [cue[language] for cue in cues],
                            regression[f"expected_{language}_order"],
                        )
                    continue
                actual = self.raw[regression["group"]]
                fields = regression["field"].split(".")
                if "expected_order" in regression:
                    self.assertEqual(fields[0], "questions")
                    self.assertEqual(
                        [question[fields[1]] for question in actual["questions"]],
                        regression["expected_order"],
                    )
                    continue
                if "question_index" in regression:
                    actual = actual["questions"][regression["question_index"] - 1]
                    if fields[0] == "questions":
                        fields = fields[1:]
                for field in fields:
                    actual = actual[field]
                if "expected_value" in regression:
                    self.assertEqual(actual, regression["expected_value"])
                for text in regression.get("required_strings", []):
                    self.assertIn(text, actual)
                for text in regression.get("forbidden_strings", []):
                    self.assertNotIn(text, actual)

    def test_the_fifty_seven_yellow_models_and_their_pistes_are_untouched(self):
        protected = {group: row for group, row in self.raw.items() if group not in self.manifest["reviewed"]}
        self.assertEqual(len(protected), 57)
        self.assertEqual(fingerprint(protected), self.manifest["protected_models_sha"])
        hints = json.loads(content.TACHE_TWO_SUBJECT_HINTS_PATH.read_text())["groups"]
        self.assertEqual(
            fingerprint({group: hints[group] for group in protected}),
            self.manifest["protected_hints_sha"],
        )

    def test_all_previous_layouts_are_retained_without_simulated_answers(self):
        history = json.loads((
            content.QUESTION_BANK_DIR / "dialogue_history/locations.json"
        ).read_text())
        original = {
            "version": 1,
            "groups": {
                group: {
                    "replacements": history["groups"][group]["replacements"],
                    "revisions": history["groups"][group]["revisions"][:count],
                }
                for group, count in self.manifest["history_prefixes"].items()
            },
        }
        self.assertEqual(fingerprint(original), self.manifest["original_history_sha"])
        for group, audit in self.manifest["reviewed"].items():
            with self.subTest(group=group):
                index = audit["archive_index"]
                if index is None:
                    self.assertEqual(fingerprint(visible(self.raw[group])), audit["before_visible_sha"])
                    continue
                before = history["groups"][group]["revisions"][index]
                self.assertEqual(fingerprint(before), audit["before_visible_sha"])
                self.assertEqual(set(before), {"group", "opening", "closing", "questions"})
                self.assertTrue(all("answer" not in row for row in before["questions"]))
                texts = {row["question"] for row in self.raw[group]["questions"]}
                self.assertEqual(
                    sum(row["question"] in texts for row in before["questions"]),
                    audit["retained_questions"],
                )

    def test_source_consignes_classification_reusable_banks_and_vocabulary_remain_exact(self):
        root = content.QUESTION_BANK_DIR
        immutable = {
            str(path.relative_to(root)): json.loads(path.read_text())
            for path in sorted(root.rglob("*.json"))
            if path.parent.name not in {"dialogues", "dialogue_history"}
            and path != content.TACHE_TWO_SUBJECT_HINTS_PATH
        }
        self.assertEqual(fingerprint(immutable), self.manifest["immutable_content_sha"])

    def test_known_unknown_and_reply_driven_goals_stay_distinct_in_employment_and_education(self):
        colleague = self.raw["acquaintance-new-job-overall-experience"]["questions"]
        self.assertIn("horaires", colleague[2]["question"])
        self.assertIn("décaler", colleague[2]["question"])
        overtime = self.raw["canadian-work-hours-home-country-comparison"]["questions"][7]
        self.assertTrue(overtime["question"].startswith("T'arrive-t-il"))
        orientation = self.raw["new-employee-company-orientation"]["questions"][1]
        self.assertIn("without explaining how to reach them", orientation["condition"])
        teacher = self.raw["french-teacher-study-abroad-advice"]["questions"]
        self.assertIn("différences", teacher[0]["question"])
        self.assertIn("Quels critères", teacher[1]["question"])
        self.assertNotIn("mon domaine", teacher[1]["question"])
        game = self.raw["french-teacher-language-school-student-game"]["questions"]
        self.assertIn("À quelle date", game[0]["question"])
        self.assertIn("principe du jeu", game[1]["question"])
        self.assertEqual(game[3]["follow_up_to"], 2)
        self.assertEqual(game[4]["follow_up_to"], 2)
        self.assertIn("Y a-t-il des récompenses", game[6]["question"])
        stay = self.raw["friend-child-language-stay-abroad"]["questions"]
        self.assertIn("âges et niveaux", stay[2]["question"])
        self.assertIn("Où logeait", stay[4]["question"])
        self.assertEqual(stay[5]["follow_up_to"], 5)
