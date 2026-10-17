CULTURE_GROUPS = {
    "arts-loisirs": {
        "colleague-association-dance-classes",
        "friend-cooking-workshop-experience",
        "friend-weekly-theatre-class",
        "guitar-teacher-lesson-enrollment",
        "music-school-course-information",
        "neighbor-home-music-tutor-advice",
        "neighbor-photography-association-class",
    },
    "culture-medias": {
        "acquaintance-recent-cinema-film",
        "canadian-press-newsagent-selection",
        "experienced-blogger-start-travel-blog",
        "friend-choose-film-ticket-already-held",
        "friend-choose-television-series",
        "friend-city-for-cultural-magazine-article",
        "friend-films-for-association-review",
        "friend-reading-for-literary-review",
        "friend-shows-for-association-article",
        "municipal-library-document-borrowing",
        "neighborhood-library-membership",
    },
    "sorties-spectacles": {
        "friend-choose-tonight-outing",
        "friend-new-ottawa-restaurant",
        "host-foreign-friends-city-advice",
        "municipal-cultural-service-city-activities",
        "museum-group-visit-reception",
        "neighbor-municipal-cultural-outings",
        "new-city-friend-low-budget-outings",
        "new-neighbor-evening-entertainment",
        "tourist-office-city-discovery-with-friends",
    },
    "spectacles-festivals": {
        "canada-cinema-employee-friend",
        "colleague-invitation-unspecified-show",
        "colleague-unusable-music-festival-tickets",
        "friend-concert-invitation",
        "friend-music-festival-organizer",
    },
    "loisirs-clubs-jeux": {
        "bookshop-public-game-participation",
        "colleague-board-game-club",
        "cultural-center-reception-activities",
        "friend-canadian-weekend-customs",
        "friend-entertain-visiting-nephews",
        "friend-tv-game-participation",
        "friend-unspecified-artistic-activity",
        "neighbor-gardening-activity-organizer",
        "toy-library-membership",
    },
}

ALL_CULTURE_GROUPS = frozenset().union(*CULTURE_GROUPS.values())

LEISURE_SPLIT_GROUPS = {
    slug: groups for slug, groups in CULTURE_GROUPS.items()
    if slug != "culture-medias"
}
ALL_LEISURE_SPLIT_GROUPS = frozenset().union(*LEISURE_SPLIT_GROUPS.values())
PREVIOUS_LEISURE_GROUPS = {
    "arts-loisirs": (
        CULTURE_GROUPS["arts-loisirs"] | CULTURE_GROUPS["loisirs-clubs-jeux"]
    ) - {"friend-entertain-visiting-nephews"},
    "sorties-spectacles": (
        CULTURE_GROUPS["sorties-spectacles"] | CULTURE_GROUPS["spectacles-festivals"]
    ) | {"friend-entertain-visiting-nephews"},
}

ORIGINAL_ARTS_GROUPS = {
    "bookshop-public-game-participation",
    "canadian-press-newsagent-selection",
    "colleague-association-dance-classes",
    "colleague-board-game-club",
    "cultural-center-reception-activities",
    "experienced-blogger-start-travel-blog",
    "friend-canadian-weekend-customs",
    "friend-city-for-cultural-magazine-article",
    "friend-cooking-workshop-experience",
    "friend-reading-for-literary-review",
    "friend-tv-game-participation",
    "friend-unspecified-artistic-activity",
    "friend-weekly-theatre-class",
    "guitar-teacher-lesson-enrollment",
    "municipal-cultural-service-city-activities",
    "municipal-library-document-borrowing",
    "music-school-course-information",
    "neighbor-gardening-activity-organizer",
    "neighbor-home-music-tutor-advice",
    "neighbor-municipal-cultural-outings",
    "neighbor-photography-association-class",
    "neighborhood-library-membership",
    "toy-library-membership",
}
