from django import template
from study.models import SubjectBookmark

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

    if not hasattr(request, "_subject_bookmarks"):
        request._subject_bookmarks = {}
    scope = (request.user.pk, task.pk, target_type)
    if scope not in request._subject_bookmarks:
        target = "response" if target_type == "response" else "sujet"
        task_filter = (
            {"response__theme__task": task} if target == "response"
            else {"sujet__task": task}
        )
        request._subject_bookmarks[scope] = set(
            SubjectBookmark.objects.filter(
                user=request.user, **task_filter,
            ).order_by().values_list(f"{target}_id", flat=True)
        )
    key = f"{target_type}:{target_id}"
    return {
        "target_type": target_type,
        "target_id": target_id,
        "key": key,
        "bookmarked": target_id in request._subject_bookmarks[scope],
        "subject_label": label,
        "part": task.part,
        "task": task,
        "csrf_token": context.get("csrf_token"),
    }
