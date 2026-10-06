from django.test import SimpleTestCase

from study.templatetags.study_markdown import (
    render_markdown,
    render_markdown_inline,
    render_markdown_prose,
)


class InlineMarkdownTests(SimpleTestCase):
    def test_french_quotation_markup_does_not_rewrite_link_attributes(self):
        self.assertEqual(
            render_markdown_inline('[Example](https://example.test "«quoted»")'),
            '<a href="https://example.test" title="«quoted»">Example</a>',
        )

    def test_french_quotation_markup_does_not_rewrite_image_alt_text(self):
        self.assertEqual(
            render_markdown_inline('![«quoted»](https://example.test/image.png)'),
            '<img src="https://example.test/image.png" alt="«quoted»" />',
        )

    def test_french_text_and_code_remain_escaped_and_marked(self):
        self.assertEqual(
            render_markdown_inline('« <test> & words » and `a/b`'),
            '<span lang="fr">« &lt;test&gt; &amp; words »</span> '
            'and <code lang="fr">a/<wbr>b</code>',
        )

    def test_french_link_text_is_marked_without_changing_its_title(self):
        self.assertEqual(
            render_markdown_inline('[«bonjour»](https://example.test "«title»")'),
            '<a href="https://example.test" title="«title»">'
            '<span lang="fr">«bonjour»</span></a>',
        )

    def test_inline_html_and_code_are_never_rendered_as_raw_html(self):
        self.assertEqual(
            render_markdown_inline('Keep `<script>x</script>` literal.'),
            'Keep <code lang="fr">&lt;script&gt;x&lt;/<wbr>script&gt;</code> literal.',
        )
        self.assertNotIn("<script>", render_markdown_inline("<script>alert(1)</script>"))

    def test_block_markdown_keeps_its_existing_rendering(self):
        self.assertEqual(
            render_markdown('«quoted» and `a/b`'),
            '<p>«quoted» and <code>a/b</code></p>\n',
        )


class ProseMarkdownTests(SimpleTestCase):
    def test_learner_prose_supports_emphasis_lists_and_headings(self):
        self.assertEqual(
            render_markdown_prose(
                "## Présentation\nJe suis **Cornelius**, *ingénieur*.\n\n- Cornell\n- Microsoft"
            ),
            "<h2>Présentation</h2>\n"
            "<p>Je suis <strong>Cornelius</strong>, <em>ingénieur</em>.</p>\n"
            "<ul>\n<li>Cornell</li>\n<li>Microsoft</li>\n</ul>\n",
        )

    def test_line_breaks_match_django_linebreaks_text_nodes(self):
        self.assertEqual(
            render_markdown_prose("Bonjour,\nje m’appelle Cornelius.\n\nMerci."),
            "<p>Bonjour,<br>je m’appelle Cornelius.</p>\n<p>Merci.</p>\n",
        )

    def test_indented_paragraphs_stay_prose_instead_of_code(self):
        rendered = render_markdown_prose("\tJe vis aux États-Unis.\n    Depuis six ans.")
        self.assertEqual(rendered, "<p>Je vis aux États-Unis.<br>Depuis six ans.</p>\n")
        self.assertNotIn("<code>", rendered)

    def test_raw_html_and_script_links_are_not_rendered(self):
        rendered = render_markdown_prose(
            "<script>alert(1)</script> [lien](javascript:alert(1))"
        )
        self.assertNotIn("<script>", rendered)
        self.assertNotIn("<a ", rendered)
        self.assertIn("&lt;script&gt;", rendered)

    def test_empty_prose_renders_nothing(self):
        self.assertEqual(render_markdown_prose(""), "")
        self.assertEqual(render_markdown_prose(None), "")
