NEIGHBOURHOOD_GROUPS = {
    "vie-quartier": {
        "friend-holiday-apartment-watch",
        "grocery-store-home-delivery",
        "help-friend-post-parcel",
        "medical-secretary-temporary-replacement-doctor",
        "visit-colleague-minor-accident",
    },
    "garde-enfants-animaux": {
        "child-friends-family-holiday-invitation",
        "colleague-babysitter-referral-needs",
        "friend-three-year-old-weekend-care",
        "neighbor-child-one-day-care",
        "neighbor-dog-care-week-paid",
        "neighbor-home-childcare-provider-referral",
        "trusted-person-temporary-pet-care",
    },
    "benevolat-associations": {
        "animal-protection-association-invitation",
        "friend-homeless-meal-volunteering",
        "neighbor-environmental-association-volunteering",
        "volunteer-local-association-information-office",
    },
    "sorties-spectacles": {
        "host-foreign-friends-city-advice",
    },
    "loisirs-clubs-jeux": {
        "friend-entertain-visiting-nephews",
    },
}

ALL_NEIGHBOURHOOD_GROUPS = frozenset().union(*NEIGHBOURHOOD_GROUPS.values())
