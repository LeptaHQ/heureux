"""Grants are issued only while rendering authorized server-side French sources."""

from html import unescape

from django import template
from django.conf import settings
from django.utils.html import format_html, strip_tags

from study.french_audio import normalize_text, source_grant


register = template.Library()


@register.simple_tag(takes_context=True)
def speech_attrs(context, text, private=True, user_id=None):
    if not settings.FRENCH_AUDIO_ENABLED:
        return format_html('data-speech-private="{}"', "true" if private else "false")
    request = context.get("request")
    if request and request.user.is_authenticated:
        user_id = request.user.pk
    text = normalize_text(unescape(strip_tags(str(text or "").replace("<br>", " ").replace("<br />", " "))))
    token = source_grant(text, user_id, private=private)
    if not token:
        return ""
    return format_html(
        'data-speech-grant="{}" data-speech-text="{}" data-speech-private="{}"',
        token, text, "true" if private else "false",
    )
