from django import template
from study.expression.bookmarks import subject_bookmark_ids

register = template.Library()


@register.inclusion_tag("study/expression/partials/subject_bookmark_form.html", takes_context=True)
def subject_bookmark(context, *, response_id=None, sujet_id=None, label=""):
    request = context.get("request")
    task = context.get("task")
    if request is None or not request.user.is_authenticated or task is None:
        return {}
    if response_id:
        target_type, target_id = "response", response_id
    elif sujet_id:
        target_type, target_id = "writing-sujet", sujet_id
    else:
        return {}

    key = f"{target_type}:{target_id}"
    return {
        "target_type": target_type,
        "target_id": target_id,
        "key": key,
        "bookmarked": target_id in subject_bookmark_ids(request, task, target_type),
        "subject_label": label,
        "part": task.part,
        "task": task,
        "csrf_token": context.get("csrf_token"),
    }
