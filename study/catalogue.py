"""Process-local catalogues for source-controlled bundled expression content.

Requests share frozen parser records and read-only indexes, never ORM objects
or learner state. Deploys that change bundled content must restart workers;
tests that replace loaders must clear these caches before and after patching.
Use content_loader directly for custom paths, validation and content imports.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from types import MappingProxyType

from . import content_loader as content


@lru_cache(maxsize=1)
def tache_two_subject_months() -> tuple[content.TacheTwoSubjectMonthData, ...]:
    return content.load_tache_two_subject_months()


@lru_cache(maxsize=1)
def tache_two_subject_themes() -> tuple[
    tuple[content.TacheTwoThemeData, ...], Mapping[str, str]
]:
    themes, mapping = content.load_tache_two_subject_themes()
    return themes, MappingProxyType(mapping)


@lru_cache(maxsize=3)
def task_memoires(
    part_slug: str, task_slug: str
) -> tuple[content.QuestionBankData, ...]:
    directory, namespace = content.MEMOIRE_TASKS[(part_slug, task_slug)]
    return content.load_question_banks(directory, key_namespace=namespace)


@lru_cache(maxsize=1)
def eo_tache_three_family_labels() -> Mapping[tuple[str, str], str]:
    return MappingProxyType(content.load_eo_tache_three_family_labels())


@lru_cache(maxsize=1)
def ee_tache_three_months() -> tuple[content.EeTacheThreeMonth, ...]:
    return content.load_ee_tache_three_months()


@lru_cache(maxsize=3)
def ee_subject_keys(tache: int) -> tuple[str, ...]:
    return content.load_ee_subject_keys(tache)


@lru_cache(maxsize=3)
def ee_subject_themes(tache: int) -> tuple[
    tuple[content.EeSubjectThemeData, ...], Mapping[str, str]
]:
    themes, mapping = content.load_ee_subject_themes(tache)
    return themes, MappingProxyType(mapping)


@lru_cache(maxsize=2)
def ee_writing_categories(tache: int) -> tuple[content.WritingCategoryData, ...]:
    return content.load_ee_writing_categories(tache)


@lru_cache(maxsize=1)
def ee_tache_three_sources_by_key() -> Mapping[
    str, tuple[content.EeTacheThreeMonth, content.EeTacheThreeCombinaison]
]:
    return MappingProxyType(
        {
            combinaison.content_key: (month, combinaison)
            for month in ee_tache_three_months()
            for combinaison in month.combinaisons
        }
    )


@lru_cache(maxsize=2)
def ee_writing_sources_by_slug(
    tache: int,
) -> Mapping[str, content.WritingSujetData]:
    return MappingProxyType(
        {
            source.slug: source
            for category in ee_writing_categories(tache)
            for source in category.sujets
        }
    )


def clear_catalogue_cache() -> None:
    """Discard all shared catalogue entries, including their derived indexes."""
    tache_two_subject_months.cache_clear()
    tache_two_subject_themes.cache_clear()
    task_memoires.cache_clear()
    eo_tache_three_family_labels.cache_clear()
    ee_tache_three_months.cache_clear()
    ee_subject_keys.cache_clear()
    ee_subject_themes.cache_clear()
    ee_writing_categories.cache_clear()
    ee_tache_three_sources_by_key.cache_clear()
    ee_writing_sources_by_slug.cache_clear()
