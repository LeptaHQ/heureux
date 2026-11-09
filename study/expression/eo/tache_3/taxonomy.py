"""Strict, immutable display categories; source identities are never reassigned."""

from collections.abc import Mapping
from dataclasses import dataclass
import json
from pathlib import Path
import re
from types import MappingProxyType

from study.catalogue import loader as content


@dataclass(frozen=True)
class DisplayTheme:
    slug: str
    label: str
    order: int


@dataclass(frozen=True)
class DisplayCategory:
    theme: DisplayTheme
    slug: str
    label: str
    group: str
    order: int


@dataclass(frozen=True)
class SubjectTaxonomy:
    themes: tuple[DisplayTheme, ...]
    by_group: Mapping[str, DisplayCategory]
    by_source: Mapping[str, DisplayCategory]


def load_eo_tache_three_taxonomy(path: Path | None = None, *, responses=None) -> SubjectTaxonomy:
    data = json.loads(
        (path or content.EO_TACHE_THREE_DIR / "subject_taxonomy.json").read_text(
            encoding="utf-8"
        ),
        object_pairs_hook=content._unique_json_fields,
    )
    if (
        not isinstance(data, dict)
        or set(data) != {"version", "task", "themes"}
        or type(data["version"]) is not int or data["version"] != 1
        or data["task"] != "eo/tache-3"
        or not isinstance(data["themes"], list) or not data["themes"]
    ):
        raise ValueError("EO3 taxonomy requires version 1 and exact task eo/tache-3")
    responses = content.parse_responses() if responses is None else responses
    members = {
        response.semantic_group: tuple(p.content_key for p in response.prompts)
        for response in responses
    }
    themes, by_group, by_source = [], {}, {}
    slugs, orders = set(), set()

    def label(value):
        return isinstance(value, str) and value == value.strip() and bool(value)

    def slug(value):
        return isinstance(value, str) and re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value)

    for row in data["themes"]:
        if not isinstance(row, dict) or set(row) != {"slug", "label", "order", "subthemes"}:
            raise ValueError("EO3 taxonomy theme has invalid fields")
        if (
            not slug(row["slug"]) or row["slug"] in slugs or not label(row["label"])
            or type(row["order"]) is not int or row["order"] < 1 or row["order"] in orders
            or not isinstance(row["subthemes"], list) or not row["subthemes"]
        ):
            raise ValueError("EO3 taxonomy theme has invalid or duplicate metadata")
        slugs.add(row["slug"])
        orders.add(row["order"])
        theme = DisplayTheme(row["slug"], row["label"], row["order"])
        themes.append(theme)
        subslugs = set()
        for index, subtheme in enumerate(row["subthemes"]):
            if (
                not isinstance(subtheme, dict) or set(subtheme) != {"slug", "label", "groups"}
                or not slug(subtheme["slug"]) or subtheme["slug"] in subslugs
                or not label(subtheme["label"])
                or not isinstance(subtheme["groups"], list) or not subtheme["groups"]
            ):
                raise ValueError("EO3 taxonomy subtheme has invalid or duplicate metadata")
            subslugs.add(subtheme["slug"])
            for group in subtheme["groups"]:
                if not isinstance(group, str) or group not in members or group in by_group:
                    raise ValueError("EO3 taxonomy has unknown or duplicate semantic group")
                category = DisplayCategory(theme, subtheme["slug"], subtheme["label"], group, index)
                by_group[group] = category
                for key in members[group]:
                    if key in by_source:
                        raise ValueError("EO3 taxonomy source belongs to multiple groups")
                    by_source[key] = category
    if set(by_group) != set(members):
        raise ValueError("EO3 taxonomy must cover every semantic group exactly once")
    return SubjectTaxonomy(
        tuple(sorted(themes, key=lambda theme: theme.order)),
        MappingProxyType(by_group), MappingProxyType(by_source),
    )
