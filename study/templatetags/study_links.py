from django import template

from study.routing import subject_group_url

register = template.Library()
register.simple_tag(subject_group_url)
