from django.test import SimpleTestCase

from study.templatetags.study_markdown import render_markdown, render_markdown_inline


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
