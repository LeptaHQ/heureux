import re

from django import template
from django.utils.safestring import mark_safe
from markdown_it import MarkdownIt
from markdown_it.common.utils import escapeHtml

from study.content_loader import _ee_word_count

register = template.Library()


def _make_renderer():
    return MarkdownIt(
        "commonmark",
        {
            "breaks": True,
            "html": False,
            "linkify": False,
        },
    ).enable(["strikethrough", "table"])


def _french_text(tokens, index, options, env):
    return re.sub(
        r"«([^»]+)»",
        r'<span lang="fr">«\1»</span>',
        escapeHtml(tokens[index].content),
    )


def _french_inline_code(tokens, index, options, env):
    content = escapeHtml(tokens[index].content).replace("/", "/<wbr>")
    return f'<code lang="fr">{content}</code>'


_renderer = _make_renderer()
_inline_renderer = _make_renderer()
_inline_renderer.renderer.rules["text"] = _french_text
_inline_renderer.renderer.rules["code_inline"] = _french_inline_code


@register.filter(name="markdown")
def render_markdown(value):
    if not value:
        return ""
    # Raw HTML is disabled, so only renderer-generated markup is marked safe.
    return mark_safe(_renderer.render(str(value)))


@register.filter(name="markdown_inline")
def render_markdown_inline(value):
    if not value:
        return ""
    return mark_safe(_inline_renderer.renderInline(str(value)))


@register.filter(name="french_wordcount")
def french_wordcount(value):
    return _ee_word_count(str(value or ""))
