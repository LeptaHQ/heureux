import hashlib
import json
from pathlib import Path

from django.test import SimpleTestCase

from study.catalogue import registry as catalogue
from study.catalogue import loader as content
from study.tests.culture_fixtures import LEISURE_SPLIT_GROUPS
from study.tests.eo2_review_fixtures import (
    ACCOMMODATION_FOLLOWUP_FIELDS, PUBLISHED_ARCHIVE_INDEX, PUBLISHED_LAYOUT_SHA, REVIEWED_GROUPS,
)


# Editions immediately before the leisure dialogue review, not the latest revision.
LEISURE_ARCHIVE_INDEX = {
    "acquaintance-hiking-walking-club": 1,
    "acquaintance-recent-cinema-film": 2,
    "bookshop-public-game-participation": 2,
    "canada-cinema-employee-friend": 1,
    "canadian-press-newsagent-selection": 1,
    "canadian-tourist-office-restful-weekend": 2,
    "colleague-association-dance-classes": 2,
    "colleague-board-game-club": 2,
    "colleague-invitation-unspecified-show": 0,
    "colleague-looking-for-sports-partner": 2,
    "colleague-recommended-city-weekend": 1,
    "colleague-unusable-music-festival-tickets": 1,
    "cultural-center-reception-activities": 2,
    "employee-yoga-colleague-organizer": 0,
    "experienced-blogger-start-travel-blog": 1,
    "friend-birthday-party-on-boat": 2,
    "friend-canada-cross-country-skiing": 1,
    "friend-choose-film-ticket-already-held": 2,
    "friend-choose-television-series": 2,
    "friend-city-for-cultural-magazine-article": 3,
    "friend-concert-invitation": 1,
    "friend-cooking-workshop-experience": 2,
    "friend-entertain-visiting-nephews": 4,
    "friend-films-for-association-review": 1,
    "friend-music-festival-organizer": 1,
    "friend-reading-for-literary-review": 2,
    "friend-shows-for-association-article": 1,
    "friend-sister-birthday-gift": 1,
    "friend-sports-center-club-membership": 0,
    "friend-tv-game-participation": 0,
    "friend-unspecified-artistic-activity": 2,
    "friend-weekend-getaway-advice": 2,
    "friend-weekly-theatre-class": 0,
    "guitar-teacher-lesson-enrollment": 1,
    "holiday-region-tourist-office": 1,
    "local-acquaintance-birthday-restaurant-choice": 2,
    "municipal-library-document-borrowing": 2,
    "municipal-pool-learn-swimming-reception": 1,
    "music-school-course-information": 0,
    "neighbor-community-sports-instructor": 1,
    "neighbor-friends-countryside-outing-advice": 1,
    "neighbor-gardening-activity-organizer": 2,
    "neighbor-home-music-tutor-advice": 0,
    "neighbor-municipal-pool-information": 2,
    "neighbor-party-planning-advice": 1,
    "neighbor-photography-association-class": 0,
    "neighbor-vancouver-running-race": 2,
    "neighborhood-library-membership": 1,
    "plan-friends-birthday-with-birthday-person": 2,
    "retirement-party-invitation": 2,
    "sport-club-reception-choose-activity": 3,
    "station-stranger-mountain-passion": 1,
    "toy-library-membership": 2,
}
LEISURE_NOTE_OR_REPLY_ONLY = {
    "new-quebec-resident-first-party",
    "newcomer-neighbor-partner-surprise-birthday",
}


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
        self.history = json.loads((
            content.QUESTION_BANK_DIR / "dialogue_history/locations.json"
        ).read_text())["groups"]
        self.archived_editions = PUBLISHED_ARCHIVE_INDEX | LEISURE_ARCHIVE_INDEX
        self.recorded_models = {
            group: self.history[group]["revisions"][self.archived_editions[group]]
            if group in self.archived_editions else visible(row)
            for group, row in self.raw.items()
        }

    def test_nine_historical_blue_themes_and_their_equivalents_keep_the_recorded_review(self):
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
        current_theme_by_group = {
            group: slug for slug, groups in LEISURE_SPLIT_GROUPS.items()
            for group in groups
        }
        for slug, groups in self.manifest["themes"].items():
            actual = {row.group for key, row in dialogues.items() if mapping[key] == slug}
            self.assertEqual(
                actual,
                LEISURE_SPLIT_GROUPS[slug] if slug == "arts-loisirs" else set(groups),
            )
            for group in groups:
                self.assertEqual(
                    {mapping[key] for key, row in dialogues.items() if row.group == group},
                    {current_theme_by_group.get(group, slug)},
                )
        for group, audit in reviewed.items():
            with self.subTest(group=group):
                if group not in self.archived_editions and group not in LEISURE_NOTE_OR_REPLY_ONLY:
                    self.assertEqual(fingerprint(self.raw[group]), audit["after_sha"])
                if group not in self.archived_editions:
                    self.assertEqual(fingerprint(self.hints[group]), audit["after_hints_sha"])
                for field in ("objective", "known", "reason"):
                    self.assertTrue(audit[field].strip())
                if not audit["changed"]:
                    self.assertEqual(audit["before_sha"], audit["after_sha"])
                if not audit["hints_changed"]:
                    self.assertEqual(audit["before_hints_sha"], audit["after_hints_sha"])
                self.assertEqual(len(self.raw[group]["questions"]), 8)
        self.assertEqual(
            fingerprint([self.recorded_models[group] for group in sorted(REVIEWED_GROUPS)]),
            PUBLISHED_LAYOUT_SHA,
        )

    def test_substantive_scenario_fixes_remain_grounded_in_the_prompt_and_replies(self):
        for regression in self.manifest["regressions"]:
            with self.subTest(**regression):
                superseded = regression["group"] in self.archived_editions
                fields = regression["field"].split(".")
                # New reviews validate current replies, notes and cues; old visible wording stays archived.
                if superseded and (fields[-1] == "answer" or fields[0] in {"note", "notes", "hints"}):
                    continue
                if fields[0] == "hints":
                    cues = self.hints[regression["group"]]
                    self.assertEqual(len(cues), regression["expected_count"])
                    for language in ("french", "english"):
                        self.assertEqual(
                            [cue[language] for cue in cues],
                            regression[f"expected_{language}_order"],
                        )
                    continue
                actual = (
                    self.recorded_models[regression["group"]]
                    if superseded else self.raw[regression["group"]]
                )
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

    def test_yellow_models_outside_authorized_accommodation_followups_remain_untouched(self):
        reviewed = set(self.manifest["reviewed"]) | ACCOMMODATION_FOLLOWUP_FIELDS.keys()
        protected = {group: row for group, row in self.raw.items() if group not in reviewed}
        self.assertEqual(len(protected), 55)
        self.assertEqual(
            fingerprint(protected),
            "d516b6ea2368e1dd3d92c40824cfce5a2465dfeb2abfad27054df751c43f872f",
        )
        hints = json.loads(content.TACHE_TWO_SUBJECT_HINTS_PATH.read_text())["groups"]
        self.assertEqual(
            fingerprint({group: hints[group] for group in protected}),
            "e429d7af0d3c76fa48599cc694987263cffec5f532cb7ebfe67edf146f8c5262",
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
                after = self.recorded_models[group]
                if index is None:
                    self.assertEqual(fingerprint(after), audit["before_visible_sha"])
                    continue
                before = history["groups"][group]["revisions"][index]
                self.assertEqual(fingerprint(before), audit["before_visible_sha"])
                self.assertEqual(set(before), {"group", "opening", "closing", "questions"})
                self.assertTrue(all("answer" not in row for row in before["questions"]))
                texts = {row["question"] for row in after["questions"]}
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
            and not path.is_relative_to(root / "translations")
        }
        self.assertEqual(fingerprint(immutable), self.manifest["immutable_content_sha"])

    def test_leisure_rewrites_keep_the_exact_pre_edit_annotation_layouts(self):
        snapshots = [self.recorded_models[group] for group in sorted(LEISURE_ARCHIVE_INDEX)]
        self.assertEqual(
            fingerprint(snapshots),
            "eab4784964b67e74a562866906bfe2d4414afeb6b8dad699dfec582b393b2861",
        )

    def test_known_unknown_and_reply_driven_goals_stay_distinct_in_employment_and_education(self):
        colleague = self.recorded_models["acquaintance-new-job-overall-experience"]["questions"]
        self.assertIn("horaires", colleague[2]["question"])
        self.assertIn("décaler", colleague[2]["question"])
        overtime = self.recorded_models["canadian-work-hours-home-country-comparison"]["questions"][7]
        self.assertTrue(overtime["question"].startswith("T'arrive-t-il"))
        orientation = self.recorded_models["new-employee-company-orientation"]["questions"][1]
        self.assertIn("without explaining how to reach them", orientation["condition"])
        teacher = self.recorded_models["french-teacher-study-abroad-advice"]["questions"]
        self.assertIn("différences", teacher[0]["question"])
        self.assertIn("Quels critères", teacher[1]["question"])
        self.assertNotIn("mon domaine", teacher[1]["question"])
        game = self.recorded_models["french-teacher-language-school-student-game"]["questions"]
        self.assertIn("À quelle date", game[0]["question"])
        self.assertIn("principe du jeu", game[1]["question"])
        self.assertEqual(game[3]["follow_up_to"], 2)
        self.assertEqual(game[4]["follow_up_to"], 2)
        self.assertIn("Y a-t-il des récompenses", game[6]["question"])
        stay = self.recorded_models["friend-child-language-stay-abroad"]["questions"]
        self.assertIn("âges et niveaux", stay[2]["question"])
        self.assertIn("Où logeait", stay[4]["question"])
        self.assertEqual(stay[5]["follow_up_to"], 5)
