"""Template context shared across the authenticated application shell."""

from .models import ReviewSession
from .views.helpers import active_task_for_request


COMPREHENSION_ROUTES = {
    "comprehension_hub",
    "comprehension_overview",
    "comprehension_group",
    "comprehension_test",
    "comprehension_question_study",
    "comprehension_start",
    "comprehension_question",
    "comprehension_results",
    "comprehension_oral_overview",
    "comprehension_oral_test",
    "comprehension_oral_question_study",
    "comprehension_oral_start",
    "comprehension_oral_question",
    "comprehension_oral_results",
    "comprehension_vocabulary",
    "comprehension_test_vocabulary",
    "comprehension_oral_vocabulary",
    "comprehension_oral_test_vocabulary",
}
LEARNING_ROUTES = {
    "learn",
    "learn_lesson",
    "learn_lesson_progress",
    "learn_lesson_start",
}
EXPRESSION_ROUTES = {
    "expression",
    "part_detail",
    "task_detail",
    "task_browse",
    "task_memories",
    "task_memory_detail",
    "tache_two_theme_vocabulary",
    "tache_two_theme_vocabulary_detail",
    "task_subject_batch",
    "task_subject_detail",
    "theme_detail",
    "task_family_detail",
    "response_detail",
    "edit_response",
    "writing_sujet_detail",
    "writing_sujet_edit",
    "task_review_hub",
    "task_phrases",
    "task_vocabulary_theme",
    "task_vocabulary_category",
}
NOTES_ROUTES = {
    "notes_overview",
    "general_notes",
    "custom_notes",
    "comprehension_notes",
    "task_notes",
    "annotation_search",
    "annotation_study",
    "general_annotation_study",
    "custom_annotation_study",
    "comprehension_annotation_study",
    "task_annotation_study",
}
STATS_ROUTES = {"stats", "part_stats", "task_stats"}
# Routes where ``?task=`` selects rows to list rather than naming a content
# scope: the notes search filters on a task id, so reading it as a slug would
# only ever cost a lookup that misses.
TASK_PARAM_ROUTES_WITHOUT_SCOPE = {"annotation_search"}


def _empty_globals():
    return {
        "app_name": "Heureux",
        "annotation_task": None,
        "content_task": None,
        "active_nav_area": "",
    }


def _explicit_task(request):
    """Resolve only task scope explicitly encoded by the current page."""
    match = request.resolver_match
    kwargs = match.kwargs if match else {}
    part_slug = kwargs.get("part_slug")
    task_slug = kwargs.get("task_slug")
    if match and match.url_name in {
        "tache_two_theme_vocabulary",
        "tache_two_theme_vocabulary_detail",
    }:
        part_slug = "eo"
        task_slug = "tache-2"

    data = (
        {}
        if match and match.url_name in TASK_PARAM_ROUTES_WITHOUT_SCOPE
        else (request.POST if request.method == "POST" else request.GET)
    )
    part_slug = part_slug or (data.get("part") or "").strip()
    task_slug = task_slug or (data.get("task") or "").strip()

    if not task_slug and match and match.url_name == "review":
        saved_scope = ReviewSession.load(request.user).scope
        if isinstance(saved_scope, dict):
            part_slug = saved_scope.get("part")
            task_slug = saved_scope.get("task")

    # Views that route by task resolve the same row; the request-scoped cache
    # means the shell reads it back instead of querying for it again.
    return active_task_for_request(request, part_slug, task_slug)


def _active_nav_area(request):
    match = request.resolver_match
    route_name = match.url_name if match else ""
    if route_name == "dashboard":
        return "home"
    if route_name in LEARNING_ROUTES:
        return "learn"
    if route_name in COMPREHENSION_ROUTES:
        return "comprehension"
    if route_name in EXPRESSION_ROUTES:
        return "expression"
    if route_name in NOTES_ROUTES:
        return "notes"
    if route_name in STATS_ROUTES:
        return "stats"
    if route_name in {
        "review",
        "part_review",
        "task_review",
        "comprehension_vocabulary_review",
        "comprehension_oral_vocabulary_review",
        "revisit_list",
        "part_revisit_list",
        "task_revisit_list",
    }:
        data = request.POST if request.method == "POST" else request.GET
        scope = {
            key: (data.get(key) or "").strip()
            for key in ("kind", "content")
        }
        if not any(scope.values()) and route_name in {
            "review",
            "part_review",
            "task_review",
        }:
            saved_scope = ReviewSession.load(request.user).scope
            if isinstance(saved_scope, dict):
                scope.update(
                    {
                        key: (saved_scope.get(key) or "").strip()
                        for key in ("kind", "content")
                    }
                )
            if not any(scope.values()):
                return "expression"
        if route_name in {
            "comprehension_vocabulary_review",
            "comprehension_oral_vocabulary_review",
        }:
            return "comprehension"
        if route_name in {
            "part_review",
            "task_review",
            "part_revisit_list",
            "task_revisit_list",
        }:
            return "expression"
        if (
            scope["kind"] in {"spine", "theme_vocab"}
            or scope["content"] == "spine"
        ):
            return "expression"
        return ""
    return ""


def study_globals(request):
    """The handful of values every authenticated study page's shell needs.

    This runs on every page, so it stays free of aggregates: the navigation
    renders plain links, and each page computes the counts it displays itself.
    """
    match = request.resolver_match
    if (
        not request.user.is_authenticated
        or not match
        or match.namespace != "study"
    ):
        return _empty_globals()

    task = _explicit_task(request)
    return {
        "app_name": "Heureux",
        "annotation_task": task,
        "content_task": task,
        "active_nav_area": _active_nav_area(request),
    }
