import copy
import hashlib
import json

from django.test import SimpleTestCase

from study import catalogue, content_loader as content
from study.tests.eo2_review_fixtures import (
    FOLLOWUP_GROUPS, FOLLOWUP_PROTECTED_SHA, remove_followup_archives,
)
from study.tests.housing_work_fixtures import ORIGINAL_HOUSING_GROUPS
from study.tests.neighbourhood_fixtures import ALL_NEIGHBOURHOOD_GROUPS


class TacheTwoEducationCorpusTests(SimpleTestCase):
    def setUp(self):
        catalogue.clear_catalogue_cache()
        self.addCleanup(catalogue.clear_catalogue_cache)
        self.dialogues = catalogue.tache_two_dialogues()
        self.by_group = {row.group: row for row in self.dialogues.values()}
        _, self.themes = catalogue.tache_two_subject_themes()
        self.groups = {
            row.group for key, row in self.dialogues.items()
            if self.themes[key] == "ecole-etudes"
        }
        self.hints = json.loads(content.TACHE_TWO_SUBJECT_HINTS_PATH.read_text())["groups"]
        self.history = json.loads(
            (content.QUESTION_BANK_DIR / "dialogue_history/locations.json").read_text(),
        )["groups"]

    def test_education_covers_eleven_models_and_nineteen_publications(self):
        publications = [
            row for key, row in self.dialogues.items() if self.themes[key] == "ecole-etudes"
        ]
        self.assertEqual(len(publications), 19)
        self.assertEqual(len(self.groups), 11)
        for group in self.groups:
            with self.subTest(group=group):
                self.assertEqual(len(self.by_group[group].questions), 8)
                self.assertEqual(len(self.hints[group]), 8)
                self.assertIn(group, self.history)

    def test_complete_beginner_course_wording_preserves_other_questions_and_held_drafts(self):
        group = "language-school-new-language"
        row = self.by_group[group]
        self.assertEqual(
            row.questions[1].question,
            "Pour l'espagnol, proposez-vous des cours pour débutants complets ?",
        )
        self.assertEqual(row.questions[1].follow_up_to, 1)
        self.assertIn("beginner-course details", row.questions[1].condition)
        self.assertIn("sans connaissances préalables", row.questions[1].answer)
        self.assertEqual(self.hints[group][1], {
            "french": "Cours d'espagnol pour débutants complets",
            "english": "Spanish courses for complete beginners",
        })
        revisions = self.history[group]["revisions"]
        self.assertEqual(len(revisions), 5)
        self.assertEqual(
            hashlib.sha256(json.dumps(revisions[4], ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
            "7160b3e6dea76952306b4f7c9226b5cda78a2995bad422b6a477d371e33f318c",
        )
        for index, question in enumerate(row.questions):
            if index != 1:
                self.assertEqual(question.question, revisions[4]["questions"][index]["question"])
        original = {"version": 1, "groups": copy.deepcopy(self.history)}
        remove_followup_archives(original)
        self.assertEqual(
            hashlib.sha256(json.dumps(original, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
            "36a1200196a6395e28183bbaf39dcc356af054a04fdaafffd49f2653e78ebd7b",
        )
        raw = {
            item["group"]: item
            for path in (content.QUESTION_BANK_DIR / "dialogues").glob("*.json")
            for item in json.loads(path.read_text())["dialogues"]
        }
        unrelated = {
            "dialogues": {g: item for g, item in raw.items() if g not in FOLLOWUP_GROUPS},
            "hints": {g: cues for g, cues in self.hints.items() if g not in FOLLOWUP_GROUPS},
        }
        self.assertEqual(
            hashlib.sha256(json.dumps(unrelated, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
            FOLLOWUP_PROTECTED_SHA,
        )

    def test_activity_location_and_staff_pickup_wording_preserves_other_held_drafts(self):
        group = "parent-after-school-activity-advice"
        row = self.by_group[group]
        self.assertEqual(
            row.questions[2].question,
            "Où se déroulent les activités, et un animateur vient-il chercher les enfants à l'école pour les accompagner jusqu'au lieu de l'activité ?",
        )
        self.assertIn("un animateur accompagne", row.questions[2].answer)
        self.assertEqual(self.hints[group][2], {
            "french": "Lieu des activités et trajet depuis l'école avec un animateur",
            "english": "Activity venue and a staff escort from school",
        })
        revisions = self.history[group]["revisions"]
        self.assertEqual(len(revisions), 3)
        self.assertEqual(
            hashlib.sha256(json.dumps(revisions[2], ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
            "03e8655150deedec85f3a37885bcc9835552c9541a968ebd1952b622e176cd3c",
        )
        for index, question in enumerate(row.questions):
            if index != 2:
                self.assertEqual(question.question, revisions[2]["questions"][index]["question"])
        original = {"version": 1, "groups": copy.deepcopy(self.history)}
        remove_followup_archives(original)
        self.assertEqual(
            hashlib.sha256(json.dumps(original, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
            "36a1200196a6395e28183bbaf39dcc356af054a04fdaafffd49f2653e78ebd7b",
        )
        raw = {
            item["group"]: item
            for path in (content.QUESTION_BANK_DIR / "dialogues").glob("*.json")
            for item in json.loads(path.read_text())["dialogues"]
        }
        unrelated = {
            "dialogues": {g: item for g, item in raw.items() if g not in FOLLOWUP_GROUPS},
            "hints": {g: cues for g, cues in self.hints.items() if g not in FOLLOWUP_GROUPS},
        }
        self.assertEqual(
            hashlib.sha256(json.dumps(unrelated, ensure_ascii=False, sort_keys=True).encode()).hexdigest(),
            FOLLOWUP_PROTECTED_SHA,
        )

    def test_exact_pre_audit_layouts_remain_archived_without_hidden_answers(self):
        snapshots = []
        for group in sorted(self.groups):
            index = 1 if group == "friend-child-language-stay-abroad" else 0
            before = self.history[group]["revisions"][index]
            snapshots.append(before)
            with self.subTest(group=group):
                self.assertEqual(set(before), {"group", "opening", "closing", "questions"})
                self.assertEqual(len(before["questions"]), 8)
                for question in before["questions"]:
                    self.assertLessEqual(
                        set(question), {"topic", "question", "follow_up_to", "condition"},
                    )
                if index == 0:
                    self.assertEqual(self.history[group]["replacements"], [])
        snapshot = json.dumps(snapshots, ensure_ascii=False, sort_keys=True).encode()
        self.assertEqual(
            hashlib.sha256(snapshot).hexdigest(),
            "36ad1d99e10d84cf8d9bfb5fd45c26a78c4294e705bbbbf8b10dcb47babf1d6c",
        )
        stay = self.history["friend-child-language-stay-abroad"]
        self.assertEqual(stay["replacements"][0], ["En Irlande, à Dublin", "Aux États-Unis, à Seattle"])
        school = self.by_group["language-school-new-language"]
        self.assertNotEqual(self.history[school.group]["revisions"][0]["closing"], school.closing)
        self.assertIn("cours d'essai", school.closing)

    def test_the_three_unrelated_completed_themes_remain_exactly_as_approved(self):
        rows = {
            row["group"]: row
            for path in (content.QUESTION_BANK_DIR / "dialogues").glob("*.json")
            for row in json.loads(path.read_text())["dialogues"]
        }
        expected = {
            "arrivee": "eeb337d3fd34d07c863b10f58fa4da53bae6f1b91822e56eaa8042170a48e278",
            "logement": "5856b77b61128d6d2b988dd3a589762ca8d8a5a7a04b1c6f8a17a3ba4b73a744",
            "vie-quartier": "3de4534126cd6233e3805ee89724c63644ee928b1b82f29acdcd51a3d5318c4c",
        }
        for theme, digest in expected.items():
            with self.subTest(theme=theme):
                groups = (
                    ALL_NEIGHBOURHOOD_GROUPS if theme == "vie-quartier" else
                    ORIGINAL_HOUSING_GROUPS if theme == "logement" else
                    {row.group for key, row in self.dialogues.items() if self.themes[key] == theme}
                )
                snapshot = json.dumps(
                    sorted((rows[group] for group in groups), key=lambda row: row["group"]),
                    ensure_ascii=False, sort_keys=True,
                ).encode()
                self.assertEqual(hashlib.sha256(snapshot).hexdigest(), digest)

    def test_exact_first_review_layouts_remain_available_after_the_second_pass(self):
        rewritten = self.groups - {
            "newcomer-canada-private-french-teacher", "parent-after-school-activity-advice",
        }
        snapshots = []
        for group in sorted(rewritten):
            index = 2 if group == "friend-child-language-stay-abroad" else 1
            snapshots.append(self.history[group]["revisions"][index])
        snapshot = json.dumps(snapshots, ensure_ascii=False, sort_keys=True).encode()
        self.assertEqual(
            hashlib.sha256(snapshot).hexdigest(),
            "ea2355bba05be043e8c1002fdeb547b33b62e85e1fed369b2ebf97f71e35f941",
        )

    def test_course_questions_name_experience_schedules_volume_and_extra_costs(self):
        expected = {
            "newcomer-canada-private-french-teacher": {
                1: ("formation", "depuis combien de temps", "cours particuliers"),
                4: ("bureau", "à domicile", "en ligne"),
                5: ("rythme de cours", "horaires"),
                6: ("tarif", "heure de cours", "supports de travail"),
                7: ("cours d'essai", "à la séance", "forfait"),
                8: ("annuler", "déplacer", "délai", "déjà payée"),
            },
            "language-school-new-language": {
                3: ("formation", "enseignants", "débutants"),
                4: ("pratique la langue", "binôme", "jeux de rôle"),
                5: ("créneaux", "sur place", "en ligne"),
                6: ("coûte", "semaines"),
                7: ("manuel", "supports de cours", "achat supplémentaire"),
                8: ("cours d'essai", "m'inscrire"),
            },
            "calgary-university-adult-language-courses": {
                4: ("campus", "en ligne", "dépend-il du niveau"),
                5: ("semaines", "heures de cours", "par semaine"),
                6: ("horaires", "soirée", "samedi"),
            },
            "parent-after-school-activity-advice": {
                1: ("sport", "dessin", "théâtre"),
                2: ("âges", "groupe d'âge"),
                4: ("jours", "commencent-elles", "se terminent-elles"),
            },
        }
        for group, questions in expected.items():
            for number, phrases in questions.items():
                with self.subTest(group=group, question=number):
                    for phrase in phrases:
                        self.assertIn(phrase, self.by_group[group].questions[number - 1].question)

    def test_private_school_and_university_course_replies_stay_distinct_and_coherent(self):
        private = self.by_group["newcomer-canada-private-french-teacher"]
        self.assertIn("individual lessons", private.note)
        self.assertIn("formation en enseignement", private.questions[0].answer)
        self.assertIn("huit ans", private.questions[0].answer)
        self.assertIn("lundi à 18 h", private.questions[4].answer)
        self.assertIn("jeudi à 19 h", private.questions[4].answer)
        self.assertIn("Une heure par semaine", private.questions[4].answer)
        self.assertIn("40 $", private.questions[5].answer)
        self.assertIn("exercices", private.questions[6].answer)
        self.assertIn("trente minutes", private.questions[6].answer)
        self.assertIn("cours particuliers depuis huit ans", private.questions[0].answer)
        self.assertIn("cinq heures à 180 $", private.questions[6].answer)
        self.assertIn("exercices et documents compris", private.questions[5].answer)
        self.assertIn("entretien oral", private.questions[2].answer)
        self.assertIn("exercice écrit", private.questions[2].answer)
        self.assertIn("bilan mensuel", private.questions[2].answer)
        school = self.by_group["language-school-new-language"]
        self.assertIn("neither a particular language nor private-only lessons", school.note)
        self.assertIn("anglais", school.questions[0].answer)
        self.assertIn("binôme", school.questions[3].answer)
        self.assertIn("diplôme en enseignement des langues", school.questions[2].answer)
        self.assertNotIn("18 h", school.questions[3].answer)
        self.assertIn("l'enseignant vous aide", school.questions[3].answer.lower())
        self.assertIn("Sur place", school.questions[4].answer)
        self.assertIn("18 h à 19 h 30", school.questions[4].answer)
        self.assertIn("samedi de 9 h à midi", school.questions[4].answer)
        self.assertIn("mercredi de 18 h à 21 h", school.questions[4].answer)
        self.assertIn("240 $ pour huit semaines", school.questions[5].answer)
        self.assertIn("25 $", school.questions[6].answer)
        self.assertEqual(school.questions[6].follow_up_to, 6)
        university = self.by_group["calgary-university-adult-language-courses"]
        self.assertIn("Calgary", university.note)
        self.assertIn("sans statut d'étudiant", university.questions[0].answer)
        self.assertIn("sinon", university.questions[2].answer)
        self.assertIn("groupe débutant", university.questions[2].answer)
        self.assertIn("groupes avancés sont sur le campus", university.questions[3].answer)
        self.assertIn("Douze semaines", university.questions[4].answer)
        self.assertIn("trois heures", university.questions[4].answer)
        for phrase in ("mardi", "jeudi", "18 h 30 à 20 h", "samedi de 9 h à midi"):
            self.assertIn(phrase, university.questions[5].answer)
        self.assertIn("350 $", university.questions[6].answer)
        self.assertIn("35 $ de plus", university.questions[6].answer)

    def test_teacher_advice_does_not_impose_french_study_or_guarantee_official_requirements(self):
        teacher = self.by_group["french-teacher-study-abroad-advice"]
        self.assertIn("No destination, field, budget or teaching language is established", teacher.note)
        self.assertIn("not as an admissions or immigration officer", teacher.note)
        self.assertIsNone(teacher.questions[0].follow_up_to)
        for phrase in ("comment choisir", "échange universitaire", "diplôme complet", "séjour linguistique"):
            self.assertIn(phrase, teacher.questions[0].question)
        self.assertIn("Pour comparer deux programmes", teacher.questions[1].question)
        self.assertNotIn("mon domaine", teacher.questions[1].question)
        self.assertIn("À part les frais de scolarité", teacher.questions[4].question)
        self.assertIn("logement", teacher.questions[4].question)
        self.assertIn("assurance", teacher.questions[4].question)
        self.assertIn("les repas", teacher.questions[4].answer)
        self.assertIn("estimations de l'établissement", teacher.questions[4].answer)
        self.assertEqual(teacher.questions[3].follow_up_to, 3)
        self.assertIn("pour un cursus en français", teacher.questions[2].answer)
        self.assertIn("French-language study", teacher.questions[3].condition)
        self.assertIn("m'entraîner avec vous", teacher.questions[3].question)
        for phrase in ("extrait de cours", "résumé", "présentation"):
            self.assertIn(phrase, teacher.questions[3].answer)
        self.assertIn("critères", teacher.questions[5].question)
        self.assertIn("éligibilité", teacher.questions[5].answer)
        self.assertIn("éventuelle autorisation", teacher.questions[6].question)
        self.assertIn("service des étudiants internationaux", teacher.questions[6].answer)
        self.assertIn("autorités du pays choisi", teacher.questions[6].answer)
        self.assertIn("dates d'admission varient", teacher.questions[7].answer)

    def test_parents_and_neighbours_share_experience_without_assuming_child_eligibility(self):
        neighbour = self.by_group["edmonton-newcomer-neighbor-schools"]
        self.assertIn("Edmonton", neighbour.note)
        self.assertIn("already have accommodation", neighbour.note)
        self.assertIn("ages and language needs are not stated", neighbour.note)
        self.assertIn("not admissions rules", neighbour.note)
        self.assertIn("not admissions rules or verified current fees", neighbour.note)
        self.assertIn("Adapt school levels", neighbour.note)
        self.assertIn("écoles du quartier", neighbour.questions[0].question)
        self.assertIn("notre adresse", neighbour.questions[0].question)
        self.assertIn("à pied ou en bus", neighbour.questions[2].question)
        self.assertIn("près du parc", neighbour.questions[2].answer)
        self.assertIn("près de la bibliothèque", neighbour.questions[2].answer)
        self.assertIn("D'après votre expérience", neighbour.questions[3].question)
        self.assertIn("premiers jours", neighbour.questions[4].question)
        self.assertIn("école de mes enfants", neighbour.questions[4].answer)
        self.assertIn("conseil scolaire", neighbour.questions[0].answer)
        self.assertIn("confirmer la liste", neighbour.questions[7].answer)
        parent = self.by_group["parent-after-school-activity-advice"]
        self.assertIn("ages are not", parent.note)
        self.assertIn("Pour le dessin, j'ai payé", parent.questions[5].answer)
        self.assertIn("multisports", parent.questions[0].answer)
        self.assertIn("multisports le vendredi", parent.questions[3].answer)
        self.assertIn("tarifs actuels", parent.questions[7].answer)
        stay = self.by_group["friend-child-language-stay-abroad"]
        self.assertIn("Tom is your friend's child; Jerry is yours", stay.note)
        self.assertIn("Canada and Tom's age are already known", stay.note)
        self.assertIn("not current eligibility or availability", stay.note)
        self.assertIn("association recommandée", stay.questions[0].answer)
        self.assertEqual(stay.questions[1].follow_up_to, 1)
        self.assertIn("Confirm Jerry's requirements with the provider", stay.note)
        self.assertIn("responsable du séjour", stay.questions[6].answer)
        self.assertIn("jour et nuit", stay.questions[6].answer)
        self.assertIn("coûté au total", stay.questions[7].question)
        self.assertEqual(stay.questions[5].follow_up_to, 5)
        self.assertNotIn("famille d'accueil", stay.questions[4].question)
        self.assertIn("conditions d'accueil", stay.questions[4].question)
        self.assertIn("visité le logement", stay.questions[4].answer)
        self.assertNotIn("test de langue", stay.questions[2].answer)
        self.assertIn("sont anglophones", neighbour.questions[1].answer)
        self.assertIn("Au primaire de mes enfants", neighbour.questions[6].answer)
        self.assertIn("l'an dernier", neighbour.questions[6].answer)
        self.assertIn("Confirmez le tarif actuel", neighbour.questions[6].answer)

    def test_game_scoring_and_future_study_plans_follow_the_actual_reply(self):
        game = self.by_group["french-teacher-language-school-student-game"]
        self.assertIn("already a student", game.note)
        self.assertIn("prizes or fees", game.note)
        self.assertIn("principe du jeu", game.questions[0].question)
        self.assertNotIn("équipes", game.questions[0].question)
        self.assertIn("participants", game.questions[0].question)
        self.assertIn("équipes", game.questions[0].answer)
        self.assertNotIn("équipes", game.questions[1].answer)
        self.assertIn("quatre personnes", game.questions[2].answer)
        self.assertIn("gagnent-elles des points", game.questions[3].question)
        self.assertEqual(game.questions[3].follow_up_to, 1)
        self.assertIn("départager", game.questions[3].answer)
        self.assertIn("téléphone", game.questions[4].question)
        self.assertIn("À quelle date", game.questions[5].question)
        self.assertIn("Y a-t-il des récompenses", game.questions[6].question)
        self.assertIn("chaque membre", game.questions[6].answer)
        self.assertIn("à quel tarif", game.questions[7].question)
        self.assertNotIn("souvenir", " ".join(question.question for question in game.questions))
        friend = self.by_group["friend-planned-canadian-studies"]
        self.assertIn("Your friend, not you", friend.note)
        self.assertIn("programme", friend.questions[0].question)
        self.assertIn("ville", friend.questions[1].question)
        self.assertEqual(friend.questions[2].follow_up_to, 2)
        self.assertIn("logements que j'ai repérés", friend.questions[2].answer)
        self.assertNotIn("Montréal", friend.questions[2].question)
        self.assertIn("apportera à ta carrière", friend.questions[3].question)
        self.assertNotIn("maîtrise", friend.questions[3].question)
        self.assertIn("prépares encore ton dossier", friend.questions[4].question)
        self.assertIn("tu attends une réponse", friend.questions[4].question)
        self.assertIn("déjà reçu une", friend.questions[4].question)
        self.assertIn("conditionnelle", friend.questions[4].answer)
        self.assertIn("si je l'obtiens", friend.questions[5].answer)

    def test_survey_focuses_on_activities_and_school_fete_help_is_optional(self):
        survey = self.by_group["french-class-survey-francophone-student"]
        self.assertIn("établissement", survey.questions[1].question)
        self.assertIn("année", survey.questions[1].question)
        self.assertNotIn("depuis", survey.questions[1].question)
        self.assertIn("travaux pratiques", survey.questions[2].question)
        self.assertIn("combien de temps", survey.questions[3].question)
        self.assertIn("six heures par semaine", survey.questions[3].answer)
        self.assertEqual(survey.questions[4].follow_up_to, 4)
        self.assertIn("conciliez-vous cette activité", survey.questions[4].question)
        self.assertIn("work or volunteering", survey.questions[4].condition)
        self.assertIn("un soir par semaine", survey.questions[4].answer)
        self.assertIn("où la pratiquez-vous", survey.questions[5].question)
        self.assertIn("moments de la semaine", survey.questions[6].question)
        self.assertIn("schedule", survey.questions[6].condition)
        self.assertNotIn("chorale", survey.questions[6].question)
        fete = self.by_group["fellow-parent-first-school-fete"]
        self.assertIn("Si je souhaite aider", fete.questions[6].question)
        self.assertIn("à qui m'adresser", fete.questions[6].question)
        self.assertIn("secrétariat", fete.questions[6].answer)
        self.assertIn("without explaining seating", fete.questions[2].condition)
        self.assertTrue(fete.questions[2].question.startswith("Y aura-t-il des places assises"))
        self.assertIn("heure conseillez-vous", fete.questions[2].question)
        self.assertIn("ouverture à 14 h", fete.questions[2].answer)
        self.assertIn("places ne se réservent pas", fete.questions[2].answer)
        self.assertIn("prices remain unclear", fete.questions[4].condition)
        self.assertIn("Dans la cour", fete.questions[1].answer)
        self.assertTrue(fete.questions[5].question.startswith("Y a-t-il un buffet"))
        self.assertIn("facultatif", fete.questions[5].question)
        self.assertIn("sans obligation", fete.questions[5].answer)
        self.assertNotIn("proposer mon aide", fete.closing)
        self.assertIn("beginner-course details", self.by_group[
            "language-school-new-language"
        ].questions[1].condition)

    def test_pistes_match_reordered_questions_and_do_not_supply_reply_only_facts(self):
        expected = {
            "newcomer-canada-private-french-teacher": {
                6: "Hourly rate and included learning materials",
                7: "Trial before choosing individual lessons or a package",
                8: "Rescheduling or cancellation deadline and handling of prepaid lessons",
            },
            "edmonton-newcomer-neighbor-schools": {
                1: "Where to check local schools for your address and enrolment eligibility",
                2: "Schools offering teaching in French",
                3: "School locations and getting there on foot or by bus",
                4: "Experience of teachers: explanations and help for pupils",
                5: "New pupils' first days: help from a classmate or teacher",
                6: "Sports, music activities and clubs: lunchtime or after-school schedules",
                7: "Childcare on days without after-school activities: closing time and fee",
                8: "Enrolment contact and checking the required documents",
            },
            "french-class-survey-francophone-student": {
                2: "Institution and year of study",
                5: "Balancing work or volunteering with exam revision",
                6: "Favourite free-time activity and where it takes place",
                7: "When the activity fits into the week",
            },
            "french-teacher-language-school-student-game": {
                1: "Game concept and tasks to complete in French",
                4: "Scoring: correct answers or speed",
                5: "Permitted use of mobile phones",
                6: "Date, times and meeting point",
                7: "Any prizes for the winners",
            },
            "friend-planned-canadian-studies": {
                1: "Chosen programme and specialization",
                2: "Proposed city and institution",
                3: "Appeal of Sherbrooke for studies and life there",
                4: "How the course supports future career plans",
                5: "Admission progress: application, waiting or decision received",
            },
            "friend-child-language-stay-abroad": {
                3: "Timing and length of Tom's stay",
                5: "Tom's accommodation and checks on hosting arrangements",
                7: "Supervision during outings and contact if a problem arises",
                8: "Total cost and items included in the price",
            },
            "fellow-parent-first-school-fete": {
                3: "Seating at the show and recommended arrival time",
                6: "Buffet and whether families must bring something",
                7: "Stall needing volunteers and contact for offering to help",
                8: "Backup plan if rain prevents outdoor activities",
            },
            "parent-after-school-activity-advice": {
                2: "Eligible ages and grouping by age",
            },
            "language-school-new-language": {
                3: "Training of teachers working with beginners",
                4: "Pair work, group work or role-play practice",
                5: "On-site or online time slots for the group",
            },
            "calgary-university-adult-language-courses": {
                4: "Campus and online options by level",
            },
            "french-teacher-study-abroad-advice": {
                1: "Choosing between an exchange, a full degree and a language stay",
                2: "Comparing course content, teaching language and recognition of the qualification",
                5: "Costs to budget for beyond tuition fees",
            },
        }
        for group, questions in expected.items():
            for number, english in questions.items():
                with self.subTest(group=group, question=number):
                    self.assertEqual(self.hints[group][number - 1]["english"], english)
        age = self.hints["parent-after-school-activity-advice"][1]
        self.assertIn("âge", age["french"])
        self.assertNotIn("niveau", age["french"])
        self.assertNotIn("ability", age["english"])

    def test_paid_lesson_and_school_care_relances_address_specific_unanswered_constraints(self):
        private = self.by_group["newcomer-canada-private-french-teacher"]
        self.assertIsNone(private.questions[6].follow_up_to)
        self.assertIn("à l'avance", private.questions[6].answer)
        self.assertNotIn("annul", private.questions[6].answer)
        self.assertEqual(private.questions[7].follow_up_to, 7)
        self.assertIn("advance payment", private.questions[7].condition)
        self.assertIn("vingt-quatre heures", private.questions[7].answer)
        self.assertIn("crédit pour une autre séance", private.questions[7].answer)
        self.assertIn("après ce délai", private.questions[7].answer)
        self.assertIn("comptée comme utilisée", private.questions[7].answer)
        self.assertIn("sauf urgence", private.questions[7].answer)
        school = self.by_group["edmonton-newcomer-neighbor-schools"]
        self.assertIn("le midi ou après les cours", school.questions[5].question)
        self.assertIn("patinage le mercredi", school.questions[5].answer)
        self.assertIn("au secondaire", school.questions[5].answer)
        self.assertNotIn("garderie", school.questions[5].answer)
        self.assertTrue(school.questions[6].question.startswith("Les jours sans activité"))
        self.assertIn("jusqu'à quelle heure", school.questions[6].question)
        self.assertIn("à quel tarif", school.questions[6].question)
        self.assertEqual(school.questions[6].follow_up_to, 6)
        self.assertIn("after-school gaps", school.questions[6].condition)
        self.assertIn("18 h", school.questions[6].answer)
        self.assertIn("par mois et par enfant", school.questions[6].answer)

    def test_exact_second_review_layouts_remain_archived_after_specificity_edits(self):
        revisions = {
            "newcomer-canada-private-french-teacher": 1,
            "edmonton-newcomer-neighbor-schools": 2,
            "fellow-parent-first-school-fete": 2,
            "language-school-new-language": 2,
        }
        snapshots = [
            self.history[group]["revisions"][revisions[group]] for group in sorted(revisions)
        ]
        snapshot = json.dumps(snapshots, ensure_ascii=False, sort_keys=True).encode()
        self.assertEqual(
            hashlib.sha256(snapshot).hexdigest(),
            "5a7238731b05960164d6e104503129da60b217b00a75b47571159633455f1f6b",
        )
