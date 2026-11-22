from study.models import SubjectBookmark


def subject_bookmark_ids(request, task, target_type):
    if not hasattr(request, "_subject_bookmarks"):
        request._subject_bookmarks = {}
    key = (request.user.pk, task.pk, target_type)
    if key not in request._subject_bookmarks:
        target = {"response": "response", "writing-sujet": "sujet"}[target_type]
        task_lookup = "response__theme__task" if target == "response" else "sujet__task"
        request._subject_bookmarks[key] = set(
            SubjectBookmark.objects.filter(user=request.user, **{task_lookup: task})
            .order_by().values_list(f"{target}_id", flat=True)
        )
    return request._subject_bookmarks[key]
