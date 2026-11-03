from django import template


register = template.Library()


@register.simple_tag
def eo3_gloss(language, field, identity=None):
    if not language:
        return ""
    key = field if identity in (None, "") else f"argument-{identity}-{field}"
    return language["fields"].get(key, "")
