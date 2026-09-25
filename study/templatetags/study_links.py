from django import template
from django.urls import reverse

from study import routing

register = template.Library()


@register.simple_tag
def annotation_source_url(annotation):
    if annotation.source_key.startswith("phrase:"):
        return reverse("study:annotation_source", args=[annotation.pk])
    return annotation.source_path


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
