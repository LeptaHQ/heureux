import re

from django import template
from django.utils.safestring import mark_safe
from markdown_it import MarkdownIt

from study.content_loader import _ee_word_count

register = template.Library()

_renderer = MarkdownIt(
    "commonmark",
    {
        "breaks": True,
        "html": False,
        "linkify": False,
    },
).enable(["strikethrough", "table"])


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
    rendered = _renderer.renderInline(str(value)).replace(
        "<code>",
        '<code lang="fr">',
    )
    rendered = re.sub(
        r"«([^»]+)»",
        r'<span lang="fr">«\1»</span>',
        rendered,
    )
    return mark_safe(rendered)


@register.filter(name="french_wordcount")
def french_wordcount(value):
    return _ee_word_count(str(value or ""))
