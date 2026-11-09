from types import SimpleNamespace

from django.template.loader import render_to_string
from django.test import SimpleTestCase
from django.urls import reverse


class CollectionComponentTests(SimpleTestCase):
    @staticmethod
    def render_cases():
        progress = {
            "status": "active", "label": "En cours", "completed": 1,
            "total": 3, "percent": 33, "explicitly_completed": False,
        }
        part = SimpleNamespace(slug="eo", name="Oral", short_name="EO")
        task = SimpleNamespace(slug="tache-2", name="Tâche 2", short_label="EO2")
        theme = SimpleNamespace(
            display_name='Famille & "amis"', color="#123456", icon="book",
        )
        item = SimpleNamespace(
            summary=SimpleNamespace(progress=progress), theme=theme,
            data=SimpleNamespace(name=theme.display_name, icon=theme.icon),
            url="/vocabulaire/?theme=famille&lot=1",
            section_counts=[{
                "count": 2, "short_title": "mots", "title": "Mots utiles",
            }],
            progress_unit="lots terminés", phrase_count=4,
            word_count=1, expression_count=2, fragment_count=1,
        )
        context = {
            "part": part, "task": task, "themes": [item],
            "summary": progress, "csrf_token": "a" * 64,
        }
        yield "task-card", "study/vocabulary/task_vocabulary.html", context
        yield "theme-card", "study/vocabulary/theme_vocabulary_directory.html", context
        for count in (0, 4):
            fallback = SimpleNamespace(**{
                **vars(item), "section_counts": [], "phrase_count": count,
            })
            yield (
                f"theme-card-fallback-{count}",
                "study/vocabulary/theme_vocabulary_directory.html",
                {**context, "themes": [fallback]},
            )
        memory = SimpleNamespace(
            number=1, icon="book", label="Collection 01", title="Mes projets",
            subtitle="Des questions utiles.", category_count=2, question_count=4,
        )
        yield (
            "memory-card",
            "study/expression/eo/tache_2/partials/tache_two_memory_list.html",
            {**context, "memories": [{"memory": memory, "progress": progress}]},
        )
        prompt = SimpleNamespace(
            pk=5, response_id=8, number=1, text='Un sujet & "une question"',
            family=SimpleNamespace(name="Famille"), detail_url="/sujets/5/",
            vocabulary_count=4, vocabulary_batch_count=1,
            vocabulary_progress=progress, review_url="/revision/?lot=1&mode=fr",
        )
        for kind in ("eo3", "eo2", "writing"):
            subject = SimpleNamespace(
                prompt=prompt if kind == "eo3" else prompt.text,
                progress=progress, response_id=8, content_key="test:p1",
                title=prompt.text, month_slug="janvier", batch_number=1,
                number=1, number_label="01", month_name="Janvier", question_count=4,
                source=SimpleNamespace(source_key="test:p1", month_name="Janvier", year=2025),
                sujet=SimpleNamespace(pk=9), version_count=2,
            )
            yield (
                f"subject-table-{kind}",
                "study/expression/partials/subject_collection_table.html",
                {**context, "kind": kind, "subjects": [subject], "title": theme.display_name,
                 "secondary_label": "Questions"},
            )
        yield (
            "vocabulary-table", "study/vocabulary/partials/vocabulary_subject_table.html",
            {**context, "prompts": [prompt], "title": theme.display_name},
        )
        yield (
            "vocabulary-table-empty", "study/vocabulary/partials/vocabulary_subject_table.html",
            {**context, "prompts": [], "title": theme.display_name},
        )
        topic = SimpleNamespace(
            slug="projets", label="Parler de ses projets", french="Je souhaite…",
            status="active", learned=False, essential=True,
            url="/formulations/projets/", progress_url="/formulations/projets/appris/",
        )
        subdivision = SimpleNamespace(
            category=SimpleNamespace(slug="famille", title=theme.display_name, icon="book"),
            progress=progress, count=3, completed=1, topics=[topic],
            reference_label="Vocabulaire", reference_count=4,
            reference_url="/formulations/famille/vocabulaire/",
        )
        yield (
            "formulation-table",
            "study/expression/ee/formulations/formulation_directory.html",
            {**context, "tache": 1, "progress": progress,
             "tables": [SimpleNamespace(slug="themes", title="Thèmes", items=[subdivision])]},
        )

    def test_collection_variants_keep_native_structure_and_completion_tokens(self):
        for name, template, context in self.render_cases():
            with self.subTest(component=name):
                markup = render_to_string(template, context)
                self.assertNotIn("<script>", markup)
                if "table" in name:
                    self.assertIn("<table ", markup)
                    self.assertIn('<caption class="sr-only">', markup)
                    self.assertIn("<colgroup>", markup)
                    self.assertIn('<th scope="col"', markup)
                    if name.startswith("subject-table") or name == "formulation-table":
                        self.assertIn('name="csrfmiddlewaretoken" value="' + "a" * 64, markup)
                else:
                    self.assertIn("memory-entry--active", markup)
                    self.assertIn('aria-label="33 % terminé"', markup)
                    self.assertIn("1/3", markup)

    def test_card_variants_preserve_facts_accessibility_and_filters(self):
        cases = {
            name: render_to_string(template, context)
            for name, template, context in self.render_cases()
            if "card" in name
        }
        for name in ("task-card", "theme-card"):
            markup = cases[name]
            self.assertIn("data-theme-vocabulary-directory-item", markup)
            self.assertIn('data-theme-vocabulary-status="active"', markup)
            self.assertIn('Famille &amp; &quot;amis&quot;', markup)
        self.assertIn("<b>2</b> mots", cases["task-card"])
        self.assertIn("<b>2</b> Mots utiles", cases["theme-card"])
        self.assertIn("<b>0</b> fiches", cases["theme-card-fallback-0"])
        self.assertIn("<b>1</b> mots", cases["theme-card-fallback-4"])
        self.assertIn("<b>2</b> expressions", cases["theme-card-fallback-4"])
        self.assertIn("<b>1</b> fragments", cases["theme-card-fallback-4"])
        self.assertIn(
            reverse("study:task_memory_detail", args=("eo", "tache-2", 1)),
            cases["memory-card"],
        )
        self.assertIn("Collection 01", cases["memory-card"])
        self.assertIn("Des questions utiles.", cases["memory-card"])

    def test_table_variants_keep_their_own_sorting_and_form_context(self):
        cases = {
            name: (template, context)
            for name, template, context in self.render_cases()
        }
        for name in ("subject-table-eo3", "subject-table-eo2", "vocabulary-table"):
            template, context = cases[name]
            with self.subTest(component=name):
                markup = render_to_string(template, context)
                self.assertIn("data-nested-sort-table", markup)
                self.assertIn('data-nested-table-sort="subject"', markup)
                self.assertIn('data-nested-table-sort="progress"', markup)
                if name.startswith("subject-table"):
                    self.assertIn('role="rowgroup"', markup)
                else:
                    self.assertNotIn('role="rowgroup"', markup)
        template, context = cases["subject-table-eo3"]
        self.assertNotIn("t1-table__questions-column", render_to_string(template, context))
        template, context = cases["subject-table-eo2"]
        self.assertIn("t1-table__questions-column", render_to_string(template, context))
        _template, context = cases["formulation-table"]
        markup = render_to_string(
            "study/expression/ee/formulations/partials/formulation_subtopic_table.html",
            {**context, "item": context["tables"][0].items[0]},
        )
        self.assertNotIn("data-nested-sort-table", markup)
        self.assertIn("data-formulation-reference-row", markup)
        self.assertIn("data-formulation-progress-form", markup)
        self.assertIn('name="csrfmiddlewaretoken" value="' + "a" * 64, markup)
