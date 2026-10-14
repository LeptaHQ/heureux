import hashlib
import json

from django.test import SimpleTestCase

from study import catalogue, content_loader as content


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

    def test_all_four_completed_themes_remain_exactly_as_approved(self):
        rows = {
            row["group"]: row
            for path in (content.QUESTION_BANK_DIR / "dialogues").glob("*.json")
            for row in json.loads(path.read_text())["dialogues"]
        }
        expected = {
            "arrivee": "b3f62225759c57d763f3af704a1a1756d7d83700d5b9c061b8b5b2de52304802",
            "logement": "e650f8cfbd4e5c653958e7601692e2d4d0549302f09a4e9b9bdfa7f53f240847",
            "vie-quartier": "b0bb2d04da6c1d713977b3b79a17b01af15a3fe890ffbe0f128986e5a2b8f5b3",
            "travail": "5529b40e35c4d3fd44ca29e4fc103345feebe67ca35618a24091b59d716b8752",
        }
        for theme, digest in expected.items():
            with self.subTest(theme=theme):
                groups = {
                    row.group for key, row in self.dialogues.items() if self.themes[key] == theme
                }
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
                1: ("parcours", "depuis combien de temps", "cours particuliers"),
                4: ("bureau", "à domicile", "en ligne"),
                5: ("jours", "heures", "fréquence"),
                6: ("tarif", "heure de cours", "supports de travail"),
                7: ("cours d'essai", "à la séance", "forfait"),
                8: ("annuler", "déplacer", "délai", "déjà payée"),
            },
            "language-school-new-language": {
                3: ("formation en enseignement", "débutants", "pratiquer l'oral"),
                4: ("sur place", "en ligne"),
                5: ("jours", "heures", "dure une séance"),
                6: ("coûte", "semaines"),
                7: ("manuel", "supports de cours", "achat supplémentaire"),
                8: ("cours d'essai", "m'inscrire"),
            },
            "calgary-university-adult-language-courses": {
                4: ("campus", "en ligne", "dépend-il du niveau"),
                5: ("semaines", "heures de cours", "par semaine"),
                6: ("jours", "heures", "soir", "week-end"),
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
        self.assertIn("hebdomadaire d'une heure", private.questions[4].answer)
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
        self.assertIn("binôme", school.questions[2].answer)
        self.assertIn("diplôme en enseignement des langues", school.questions[2].answer)
        self.assertIn("en direct", school.questions[3].answer)
        self.assertNotIn("18 h", school.questions[3].answer)
        self.assertIn("Sur place", school.questions[4].answer)
        self.assertIn("18 h à 19 h 30", school.questions[4].answer)
        self.assertIn("samedi de 9 h à midi", school.questions[4].answer)
        self.assertIn("mercredi de 18 h à 21 h", school.questions[4].answer)
        self.assertIn("240 $ pour huit semaines", school.questions[5].answer)
        self.assertIn("25 $", school.questions[6].answer)
        self.assertEqual(school.questions[6].follow_up_to, 6)
        university = self.by_group["calgary-university-adult-language-courses"]
        self.assertIn("Calgary", university.note)
        self.assertIn("sans statut d'étudiant", university.questions[1].answer)
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
        self.assertIn("No destination, field or teaching language is imposed", teacher.note)
        self.assertIn("not as an admissions or immigration officer", teacher.note)
        self.assertIsNone(teacher.questions[0].follow_up_to)
        for phrase in ("échange universitaire", "diplôme complet", "améliorer la langue"):
            self.assertIn(phrase, teacher.questions[0].question)
        self.assertIn("Quels pays", teacher.questions[1].question)
        self.assertIn("Comment estimer", teacher.questions[4].question)
        self.assertIn("les repas", teacher.questions[4].question)
        self.assertIn("estimations de vie courante", teacher.questions[4].answer)
        self.assertIn("devis", teacher.questions[4].answer)
        self.assertEqual(teacher.questions[3].follow_up_to, 3)
        self.assertIn("pour un cursus en français", teacher.questions[2].answer)
        self.assertIn("French-language study", teacher.questions[3].condition)
        for phrase in ("compréhension", "rédaction", "présentations"):
            self.assertIn(phrase, teacher.questions[3].question)
        self.assertIn("pourrais prétendre", teacher.questions[5].question)
        self.assertIn("éventuelle autorisation", teacher.questions[6].question)
        self.assertIn("service des étudiants internationaux", teacher.questions[6].answer)
        self.assertIn("autorités du pays visé", teacher.questions[6].answer)
        self.assertIn("dates d'admission varient", teacher.questions[7].answer)

    def test_parents_and_neighbours_share_experience_without_assuming_child_eligibility(self):
        neighbour = self.by_group["edmonton-newcomer-neighbor-schools"]
        self.assertIn("Edmonton", neighbour.note)
        self.assertIn("already have accommodation", neighbour.note)
        self.assertIn("ages and language needs are not stated", neighbour.note)
        self.assertIn("not admissions rules", neighbour.note)
        self.assertIn("not admissions rules or verified current fees", neighbour.note)
        self.assertIn("Adapt school levels", neighbour.note)
        self.assertIn("écoles primaires et secondaires", neighbour.questions[0].question)
        self.assertIn("à pied ou en bus", neighbour.questions[0].question)
        self.assertIn("près du parc", neighbour.questions[0].answer)
        self.assertIn("près de la bibliothèque", neighbour.questions[0].answer)
        self.assertIn("disponibilité", neighbour.questions[2].question)
        self.assertIn("premières semaines", neighbour.questions[3].question)
        self.assertIn("école de mes enfants", neighbour.questions[3].answer)
        self.assertIn("vérifier officiellement", neighbour.questions[6].question)
        self.assertIn("avant de préparer le dossier", neighbour.questions[6].question)
        self.assertIn("confirmez la liste", neighbour.questions[7].answer)
        parent = self.by_group["parent-after-school-activity-advice"]
        self.assertIn("ages are not", parent.note)
        self.assertIn("Pour le dessin, j'ai payé", parent.questions[5].answer)
        self.assertIn("multisports", parent.questions[0].answer)
        self.assertIn("multisports le vendredi", parent.questions[3].answer)
        self.assertIn("tarifs actuels", parent.questions[7].answer)
        stay = self.by_group["friend-child-language-stay-abroad"]
        self.assertIn("considering a similar stay", stay.note)
        self.assertNotIn("yours has not", stay.note)
        self.assertIn("A host family is not guaranteed", stay.note)
        self.assertIn("not a current admissions or travel rule", stay.note)
        self.assertIn("association de parents", stay.questions[1].answer)
        self.assertIn("école de langues de Seattle", stay.questions[1].answer)
        self.assertIn("conditions actuelles", stay.questions[5].answer)
        self.assertIn("responsable du séjour", stay.questions[6].answer)
        self.assertIn("jour et nuit", stay.questions[6].answer)
        self.assertIn("coûté au total", stay.questions[7].question)
        self.assertEqual(stay.questions[4].follow_up_to, 4)
        self.assertNotIn("famille d'accueil", stay.questions[3].question)
        self.assertIn("conditions d'accueil", stay.questions[3].question)
        self.assertIn("visité le logement", stay.questions[3].answer)
        self.assertNotIn("test de langue", stay.questions[5].answer)
        self.assertIn("sont anglophones", neighbour.questions[1].answer)
        self.assertIn("Au primaire de mes enfants", neighbour.questions[5].answer)
        self.assertIn("l'an dernier", neighbour.questions[5].answer)
        self.assertIn("Confirmez le tarif actuel", neighbour.questions[5].answer)

    def test_game_scoring_and_future_study_plans_follow_the_actual_reply(self):
        game = self.by_group["french-teacher-language-school-student-game"]
        self.assertIn("already a student", game.note)
        self.assertIn("prizes or fees", game.note)
        self.assertNotIn("équipes", game.questions[0].question)
        self.assertIn("participants", game.questions[0].question)
        self.assertIn("équipes", game.questions[0].answer)
        self.assertNotIn("équipes", game.questions[1].answer)
        self.assertIn("quatre personnes", game.questions[2].answer)
        self.assertIn("gagnent-elles des points", game.questions[3].question)
        self.assertEqual(game.questions[3].follow_up_to, 1)
        self.assertIn("départager", game.questions[3].answer)
        self.assertIn("téléphone", game.questions[4].question)
        self.assertIn("chaque membre", game.questions[5].question)
        self.assertIn("à quel tarif", game.questions[7].question)
        self.assertNotIn("souvenir", " ".join(question.question for question in game.questions))
        friend = self.by_group["friend-planned-canadian-studies"]
        self.assertIn("they are leaving, not you", friend.note)
        self.assertIn("programme", friend.questions[1].question)
        self.assertIn("ville", friend.questions[2].question)
        self.assertEqual(friend.questions[3].follow_up_to, 3)
        self.assertIn("logements que j'ai repérés", friend.questions[3].answer)
        self.assertNotIn("Montréal", friend.questions[3].question)
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
        self.assertIn("où et quand", survey.questions[5].question)
        self.assertIn("concert details", survey.questions[6].condition)
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
        self.assertIn("beginner-group details", self.by_group[
            "language-school-new-language"
        ].questions[1].condition)

    def test_pistes_match_reordered_questions_and_do_not_supply_reply_only_facts(self):
        expected = {
            "newcomer-canada-private-french-teacher": {
                6: "Hourly rate and included learning materials",
                7: "Trial lesson and paying per lesson or as a package",
                8: "Rescheduling or cancellation deadline and handling of prepaid lessons",
            },
            "edmonton-newcomer-neighbor-schools": {
                1: "Primary and secondary school locations and access on foot or by bus",
                2: "Schools offering teaching in French",
                5: "Sports, music activities and clubs: lunchtime or after-school schedules",
                6: "Childcare on days without after-school activities: closing time and fee",
                7: "Official catchment-school verification",
                8: "Enrolment contact and generally required documents",
            },
            "french-class-survey-francophone-student": {
                2: "Institution and year of study",
                5: "Balancing work or volunteering with exam revision",
                6: "Main hobby, location and times",
            },
            "french-teacher-language-school-student-game": {
                4: "Scoring: correct answers or speed",
                5: "Permitted use of mobile phones",
                6: "Prize for each winning-team member",
            },
            "friend-planned-canadian-studies": {
                2: "Chosen programme and specialization",
                3: "Proposed city and institution",
                4: "Appeal of Sherbrooke for studies and life there",
                5: "Admission progress: application, waiting or decision received",
            },
            "friend-child-language-stay-abroad": {
                4: "Accommodation and checks on hosting arrangements",
                7: "Supervision during outings and contact if a problem arises",
                8: "Total cost and items included in the price",
            },
            "fellow-parent-first-school-fete": {
                3: "Seating at the show and recommended arrival time",
                6: "Buffet and whether families must bring something",
                7: "Stall needing volunteers and contact for offering to help",
                8: "Indoor arrangements in bad weather",
            },
            "parent-after-school-activity-advice": {
                2: "Eligible ages and grouping by age",
            },
            "language-school-new-language": {
                3: "Teacher training and speaking practice with beginners",
                4: "Classes on site or also online",
                5: "Class days, times and lesson length",
            },
            "calgary-university-adult-language-courses": {
                4: "Campus and online options by level",
            },
            "french-teacher-study-abroad-advice": {
                1: "Exchange, full degree or language stay",
                2: "Destinations suited to the field, language skills and budget",
                5: "Estimating the budget: studies, housing, meals, insurance and travel",
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
        self.assertIn("réglé à l'avance", private.questions[6].answer)
        self.assertNotIn("annul", private.questions[6].answer)
        self.assertEqual(private.questions[7].follow_up_to, 7)
        self.assertIn("advance payment", private.questions[7].condition)
        self.assertIn("vingt-quatre heures", private.questions[7].answer)
        self.assertIn("crédit pour une autre séance", private.questions[7].answer)
        self.assertIn("après ce délai", private.questions[7].answer)
        self.assertIn("comptée comme utilisée", private.questions[7].answer)
        self.assertIn("sauf urgence", private.questions[7].answer)
        school = self.by_group["edmonton-newcomer-neighbor-schools"]
        self.assertIn("le midi ou après les cours", school.questions[4].question)
        self.assertIn("patinage le mercredi", school.questions[4].answer)
        self.assertIn("au secondaire", school.questions[4].answer)
        self.assertNotIn("garderie", school.questions[4].answer)
        self.assertTrue(school.questions[5].question.startswith("Les jours sans activité"))
        self.assertIn("jusqu'à quelle heure", school.questions[5].question)
        self.assertIn("à quel tarif", school.questions[5].question)
        self.assertEqual(school.questions[5].follow_up_to, 5)
        self.assertIn("after-school gaps", school.questions[5].condition)
        self.assertIn("18 h", school.questions[5].answer)
        self.assertIn("par mois et par enfant", school.questions[5].answer)

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
