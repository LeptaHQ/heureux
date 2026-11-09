from django import template
from django.urls import reverse

from study.catalogue import registry as catalogue
from study.navigation import routing

register = template.Library()


@register.simple_tag
def subject_display_category(prompt):
    if ":p" not in prompt.content_key:
        return None
    return catalogue.eo_tache_three_taxonomy().by_source.get(prompt.content_key)


@register.simple_tag(takes_context=True)
def subject_link(context, url):
    return routing.subject_selection_url(url, context.get("request"))


@register.simple_tag(takes_context=True)
def subject_url(context, view_name, *args, fragment=None):
    return subject_link(context, reverse(view_name, args=args, fragment=fragment))


@register.simple_tag(takes_context=True)
def subject_group_url(context, part_slug, task_slug, theme_slug, family_slug=None):
    return subject_link(
        context,
        routing.subject_group_url(part_slug, task_slug, theme_slug, family_slug),
    )
