from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path

from django.test import SimpleTestCase

from study.content_loader import (
    CONTENT_DIR,
    EE_MONTH_ORDER,
    EE_TACHE_CONTENT_PREFIXES,
    EE_TACHE_DIRS,
    ee_canonical_by_content_key,
    ee_subject_content_key,
    ee_theme_by_content_key,
    load_ee_equivalent_groups,
    load_ee_subject_keys,
    load_ee_subject_themes,
)

EE_TACHES = (1, 2, 3)
EXPECTED_PER_MONTH = {
    "janvier": 15,
    "mars": 14,
    "avril": 20,
    "mai": 8,
    "juin": 5,
    "juillet": 19,
    "aout": 16,
    "septembre": 6,
    "octobre": 4,
    "novembre": 12,
    "decembre": 19,
}
ICON_SPRITE = (
    Path(__file__).resolve().parent.parent
    / "static"
    / "study"
    / "icons"
    / "ui-icons.svg"
)


def _sprite_icons() -> set:
    text = ICON_SPRITE.read_text(encoding="utf-8")
    return {name for name in re.findall(r'id="icon-([a-z0-9-]+)"', text)}


class EeCorpusTests(SimpleTestCase):
    """The 2025 corpus must stay complete and consistent across the tâches."""

    def test_every_tache_publishes_the_same_138_combinaisons(self):
        total = sum(EXPECTED_PER_MONTH.values())
        self.assertEqual(total, 138)
        for tache in EE_TACHES:
            with self.subTest(tache=tache):
                keys = load_ee_subject_keys(tache)
                self.assertEqual(len(keys), total)
                self.assertEqual(len(set(keys)), total)
                prefix = EE_TACHE_CONTENT_PREFIXES[tache]
                self.assertTrue(all(key.startswith(prefix) for key in keys))

    def test_month_counts_match_the_published_source(self):
        for tache in EE_TACHES:
            keys = load_ee_subject_keys(tache)
            prefix = EE_TACHE_CONTENT_PREFIXES[tache]
            for month_slug, expected in EXPECTED_PER_MONTH.items():
                with self.subTest(tache=tache, month=month_slug):
                    found = [
                        key
                        for key in keys
                        if key.startswith(f"{prefix}{month_slug}:")
                    ]
                    self.assertEqual(len(found), expected)

    def test_fevrier_2025_is_absent_everywhere(self):
        self.assertNotIn("fevrier", EE_MONTH_ORDER)
        for tache in EE_TACHES:
            with self.subTest(tache=tache):
                self.assertFalse(
                    [
                        key
                        for key in load_ee_subject_keys(tache)
                        if ":fevrier:" in key
                    ]
                )

    def test_the_three_taches_describe_the_same_combinaisons(self):
        suffixes = {
            tache: [key.split(":", 1)[1] for key in load_ee_subject_keys(tache)]
            for tache in EE_TACHES
        }
        self.assertEqual(suffixes[1], suffixes[2])
        self.assertEqual(suffixes[1], suffixes[3])

    def test_duplicate_combinaison_numbers_stay_distinguishable(self):
        # Mai 2025 publishes two panels both labelled "Combinaison 3".
        for tache in EE_TACHES:
            with self.subTest(tache=tache):
                prefix = EE_TACHE_CONTENT_PREFIXES[tache]
                keys = set(load_ee_subject_keys(tache))
                self.assertIn(f"{prefix}mai:combinaison-3", keys)
                self.assertIn(f"{prefix}mai:combinaison-3-bis", keys)

    def test_content_key_helper_matches_the_stored_keys(self):
        self.assertEqual(
            ee_subject_content_key(2, "janvier", "Combinaison 7"),
            "ee-tache2:janvier:combinaison-7",
        )
        self.assertEqual(
            ee_subject_content_key(3, "mai", "Combinaison 3-bis"),
            "ee-tache3:mai:combinaison-3-bis",
        )

    def test_prompts_are_never_empty(self):
        for tache in (1, 2):
            directory = EE_TACHE_DIRS[tache] / "subjects"
            for month_slug in EE_MONTH_ORDER:
                payload = json.loads(
                    (directory / f"{month_slug}.json").read_text(encoding="utf-8")
                )
                self.assertEqual(payload["count"], len(payload["sujets"]))
                for row in payload["sujets"]:
                    with self.subTest(tache=tache, key=row["key"]):
                        self.assertTrue(row["prompt"].strip())


class EeSubjectThemeTests(SimpleTestCase):
    def test_every_subject_belongs_to_exactly_one_known_theme(self):
        for tache in EE_TACHES:
            with self.subTest(tache=tache):
                themes, mapping = load_ee_subject_themes(tache)
                slugs = {theme.slug for theme in themes}
                keys = load_ee_subject_keys(tache)
                self.assertEqual(set(mapping), set(keys))
                self.assertEqual(len(mapping), len(keys))
                self.assertTrue(set(mapping.values()) <= slugs)

    def test_theme_taxonomies_are_well_formed(self):
        icons = _sprite_icons()
        for tache in EE_TACHES:
            themes, _mapping = load_ee_subject_themes(tache)
            with self.subTest(tache=tache):
                slugs = [theme.slug for theme in themes]
                self.assertEqual(len(slugs), len(set(slugs)))
                self.assertEqual(
                    sorted(theme.order for theme in themes),
                    list(range(1, len(themes) + 1)),
                )
                for theme in themes:
                    self.assertIn(theme.icon, icons)
                    self.assertTrue(theme.name.strip())

    def test_no_theme_is_left_empty(self):
        for tache in EE_TACHES:
            themes, mapping = load_ee_subject_themes(tache)
            used = set(mapping.values())
            for theme in themes:
                with self.subTest(tache=tache, theme=theme.slug):
                    self.assertIn(theme.slug, used)

    def test_theme_lookup_covers_every_subject(self):
        for tache in EE_TACHES:
            with self.subTest(tache=tache):
                by_key = ee_theme_by_content_key(tache)
                self.assertEqual(
                    set(by_key), set(load_ee_subject_keys(tache))
                )

    def test_missing_subject_is_rejected(self):
        themes, mapping = load_ee_subject_themes(1)
        trimmed = dict(mapping)
        trimmed.pop(next(iter(trimmed)))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "subject_themes.json"
            path.write_text(
                json.dumps(
                    {
                        "themes": [
                            {
                                "slug": theme.slug,
                                "name": theme.name,
                                "icon": theme.icon,
                                "order": theme.order,
                            }
                            for theme in themes
                        ],
                        "subjects": trimmed,
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError) as error:
                load_ee_subject_themes(1, path)
        self.assertIn("missing", str(error.exception))


class EeEquivalentGroupTests(SimpleTestCase):
    def test_groups_load_and_stay_within_their_theme(self):
        for tache in EE_TACHES:
            _themes, mapping = load_ee_subject_themes(tache)
            groups = load_ee_equivalent_groups(tache)
            with self.subTest(tache=tache):
                self.assertTrue(groups)
                for group in groups:
                    self.assertGreaterEqual(len(group.members), 2)
                    self.assertIn(group.canonical, group.members)
                    for member in group.members:
                        self.assertEqual(mapping[member], group.theme)

    def test_a_subject_belongs_to_at_most_one_group(self):
        for tache in EE_TACHES:
            groups = load_ee_equivalent_groups(tache)
            members = [
                member for group in groups for member in group.members
            ]
            with self.subTest(tache=tache):
                self.assertEqual(len(members), len(set(members)))

    def test_canonical_is_the_earliest_published_member(self):
        for tache in EE_TACHES:
            order = {
                key: index
                for index, key in enumerate(load_ee_subject_keys(tache))
            }
            for group in load_ee_equivalent_groups(tache):
                with self.subTest(tache=tache, group=group.id):
                    self.assertEqual(
                        group.canonical,
                        min(group.members, key=order.__getitem__),
                    )

    def test_canonical_lookup_maps_every_grouped_subject(self):
        for tache in EE_TACHES:
            groups = load_ee_equivalent_groups(tache)
            canonical_by_key = ee_canonical_by_content_key(tache)
            with self.subTest(tache=tache):
                self.assertEqual(
                    len(canonical_by_key),
                    sum(len(group.members) for group in groups),
                )
                for group in groups:
                    for member in group.members:
                        self.assertEqual(
                            canonical_by_key[member], group.canonical
                        )

    def test_cross_theme_members_are_rejected(self):
        _themes, mapping = load_ee_subject_themes(1)
        first = next(iter(mapping))
        other = next(key for key, slug in mapping.items() if slug != mapping[first])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "equivalent_groups.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "groups": [
                            {
                                "id": "invalid-cross-theme",
                                "theme": mapping[first],
                                "canonical": first,
                                "members": [first, other],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError) as error:
                load_ee_equivalent_groups(1, path)
        self.assertIn("crosses theme boundaries", str(error.exception))

    def test_divergent_wording_is_rejected(self):
        _themes, mapping = load_ee_subject_themes(1)
        theme = mapping["ee-tache1:janvier:combinaison-1"]
        sibling = next(
            key
            for key, slug in mapping.items()
            if slug == theme and key != "ee-tache1:janvier:combinaison-1"
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "equivalent_groups.json"
            path.write_text(
                json.dumps(
                    {
                        "version": 1,
                        "groups": [
                            {
                                "id": "invalid-wording",
                                "theme": theme,
                                "canonical": "ee-tache1:janvier:combinaison-1",
                                "members": [
                                    "ee-tache1:janvier:combinaison-1",
                                    sibling,
                                ],
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            with self.assertRaises(ValueError) as error:
                load_ee_equivalent_groups(1, path)
        message = str(error.exception)
        self.assertTrue(
            "does not share its canonical wording" in message
            or "canonical must be" in message
        )

    def test_unsupported_version_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "equivalent_groups.json"
            path.write_text(
                json.dumps({"version": 2, "groups": []}), encoding="utf-8"
            )
            with self.assertRaises(ValueError) as error:
                load_ee_equivalent_groups(2, path)
        self.assertIn("version 1", str(error.exception))

    def test_group_ids_are_slugs_and_unique_within_a_tache(self):
        for tache in EE_TACHES:
            ids = [group.id for group in load_ee_equivalent_groups(tache)]
            with self.subTest(tache=tache):
                self.assertEqual(len(ids), len(set(ids)))
                for group_id in ids:
                    self.assertRegex(group_id, r"^[a-z0-9]+(?:-[a-z0-9]+)*$")

    def test_content_files_live_where_the_loader_expects_them(self):
        for tache in EE_TACHES:
            directory = EE_TACHE_DIRS[tache]
            with self.subTest(tache=tache):
                self.assertTrue(directory.is_relative_to(CONTENT_DIR))
                self.assertTrue((directory / "subject_themes.json").exists())
                self.assertTrue((directory / "equivalent_groups.json").exists())
