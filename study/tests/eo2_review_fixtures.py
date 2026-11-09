import copy
import hashlib
import json

from study.catalogue import loader as content

from study.tests.housing_work_fixtures import ORIGINAL_WORK_GROUPS
from study.tests.transport_travel_review_fixtures import (
    FIRST_ARCHIVE_GROUPS,
    REVIEWED_GROUPS as TRANSPORT_TRAVEL_GROUPS,
)


WORK_GROUPS = ORIGINAL_WORK_GROUPS - {
    "retirement-party-invitation", "colleague-management-promotion-party",
}
SCHOOL_GROUPS = {
    "newcomer-canada-private-french-teacher",
    "french-teacher-study-abroad-advice",
    "language-school-new-language",
    "parent-after-school-activity-advice",
    "friend-child-language-stay-abroad",
    "edmonton-newcomer-neighbor-schools",
    "french-teacher-language-school-student-game",
    "friend-planned-canadian-studies",
    "fellow-parent-first-school-fete",
    "french-class-survey-francophone-student",
    "calgary-university-adult-language-courses",
}
WORK_SCHOOL_GROUPS = WORK_GROUPS | SCHOOL_GROUPS
REVIEWED_GROUPS = WORK_SCHOOL_GROUPS | TRANSPORT_TRAVEL_GROUPS
PUBLISHED_LAYOUT_SHA = "4984ed2190a11c8649f97c9cc8d20e444b1aec5265674428677116659966b44a"
PUBLISHED_ARCHIVE_INDEX = {
    "acquaintance-new-job-overall-experience": 2,
    "bicycle-rental-model-and-terms": 1,
    "calgary-university-adult-language-courses": 2,
    "canada-car-breakdown-insurer": 0,
    "canadian-city-resident-advice-transit": 0,
    "canadian-work-hours-home-country-comparison": 2,
    "colleague-canada-tour-next-summer": 0,
    "colleague-canada-trip-report": 1,
    "colleague-internal-job-change": 1,
    "colleague-known-region-holiday": 0,
    "colleague-montreal-work-week-transit": 0,
    "director-canada-fortnight-training": 1,
    "edmonton-newcomer-neighbor-schools": 3,
    "fellow-parent-first-school-fete": 3,
    "former-colleague-new-job-to-change-employment": 1,
    "french-class-survey-francophone-student": 2,
    "french-teacher-language-school-student-game": 3,
    "french-teacher-study-abroad-advice": 3,
    "friend-association-work-experience": 2,
    "friend-canada-partner-birthday-trip": 1,
    "friend-carpooling-offer": 1,
    "friend-child-language-stay-abroad": 4,
    "friend-first-workday-report": 1,
    "friend-mountain-holiday-advice": 1,
    "friend-planned-canadian-studies": 2,
    "friend-seaside-holiday-advice": 0,
    "friend-upcoming-canada-trip-advice": 1,
    "friend-upcoming-job-interview-advice": 1,
    "friend-used-electric-bicycle-sale": 1,
    "friend-visited-countries-destination-choice": 1,
    "holiday-car-rental-agency": 0,
    "interlocutor-planned-mountain-trip": 1,
    "invite-friend-countryside-stay": 0,
    "language-school-new-language": 3,
    "neighbor-regular-carpool-invitation": 1,
    "new-colleague-quebec-career-migration": 1,
    "new-employee-company-orientation": 2,
    "newcomer-canada-friend-job-market": 1,
    "newcomer-canada-private-french-teacher": 2,
    "newcomer-city-transit-service": 0,
    "ottawa-newcomer-cycling-friend": 0,
    "parent-after-school-activity-advice": 1,
    "party-new-acquaintance-trip-report": 0,
    "private-owner-used-car-purchase": 1,
    "recruiter-scheduled-interview-preparation": 2,
    "supervisor-overseas-job-offer": 3,
    "travel-agency-canada-cruise": 0,
    "travel-agency-canada-stay": 1,
    "travel-agency-choose-holiday-destination": 2,
    "visit-friend-canada-december-preparation": 1,
}

FINAL_PASS_FIELDS = {
    "friend-seaside-holiday-advice": (
        ("dialogue", "questions", 0, "answer"), ("dialogue", "questions", 3, "answer"),
    ),
    "friend-used-electric-bicycle-sale": (
        ("dialogue", "questions", 7, "question"),
        ("hints", 7, "french"), ("hints", 7, "english"),
    ),
    "friend-canada-partner-birthday-trip": (("dialogue", "questions", 5, "answer"),),
    "interlocutor-planned-mountain-trip": (
        ("dialogue", "questions", 1, "answer"), ("dialogue", "questions", 6, "answer"),
    ),
    "french-class-survey-francophone-student": (
        ("dialogue", "note"), ("dialogue", "questions", 0, "question"),
        ("dialogue", "questions", 0, "answer"),
        ("hints", 0, "french"), ("hints", 0, "english"),
    ),
    "former-colleague-new-job-to-change-employment": (
        ("dialogue", "questions", 4, "question"), ("dialogue", "questions", 4, "answer"),
        ("hints", 4, "french"), ("hints", 4, "english"),
    ),
    "new-colleague-quebec-career-migration": (
        ("dialogue", "questions", 7, "question"),
        ("hints", 7, "french"), ("hints", 7, "english"),
    ),
    "travel-agency-canada-cruise": (
        ("dialogue", "questions", 3, "question"),
        ("hints", 3, "french"), ("hints", 3, "english"),
    ),
    "invite-friend-countryside-stay": (
        ("dialogue", "questions", 7, "question"), ("dialogue", "questions", 7, "answer"),
        ("hints", 7, "french"), ("hints", 7, "english"),
    ),
    "travel-agency-choose-holiday-destination": (
        ("dialogue", "questions", 3, "question"), ("dialogue", "questions", 3, "answer"),
        ("hints", 3, "french"), ("hints", 3, "english"),
    ),
    "private-owner-used-car-purchase": (
        ("dialogue", "questions", 2, "question"),
        ("hints", 2, "french"), ("hints", 2, "english"),
    ),
    "holiday-car-rental-agency": (("dialogue", "questions", 2, "answer"),),
    "friend-carpooling-offer": (("dialogue", "questions", 4, "answer"),),
}

TRAINING_FOLLOWUP_FIELDS = {
    "director-canada-fortnight-training": (
        ("dialogue", "note"),
        ("dialogue", "questions", 1, "question"), ("dialogue", "questions", 1, "answer"),
        ("dialogue", "questions", 2, "question"), ("dialogue", "questions", 2, "answer"),
        ("dialogue", "questions", 2, "condition"),
        ("dialogue", "questions", 3, "topic"), ("dialogue", "questions", 3, "question"),
        ("dialogue", "questions", 3, "answer"),
        ("dialogue", "questions", 4, "topic"), ("dialogue", "questions", 4, "question"),
        ("dialogue", "questions", 4, "answer"),
        ("dialogue", "questions", 5, "topic"), ("dialogue", "questions", 5, "question"),
        ("dialogue", "questions", 5, "answer"),
        ("dialogue", "questions", 7, "question"), ("dialogue", "questions", 7, "answer"),
        ("dialogue", "questions", 7, "condition"),
        ("hints", 1, "french"), ("hints", 1, "english"),
        ("hints", 2, "french"), ("hints", 2, "english"),
        ("hints", 3, "french"), ("hints", 3, "english"),
        ("hints", 4, "french"), ("hints", 4, "english"),
        ("hints", 5, "french"), ("hints", 5, "english"),
        ("hints", 7, "french"), ("hints", 7, "english"),
    ),
}

FIRST_DAY_FOLLOWUP_FIELDS = {
    "friend-first-workday-report": (
        ("dialogue", "questions", 4, "question"),
        ("dialogue", "questions", 4, "answer"),
        ("dialogue", "questions", 4, "condition"),
        ("hints", 4, "french"), ("hints", 4, "english"),
    ),
}

JOB_SEARCH_FOLLOWUP_FIELDS = {
    "newcomer-canada-friend-job-market": (
        ("dialogue", "note"), ("dialogue", "opening"),
        ("dialogue", "questions", 0, "question"), ("dialogue", "questions", 0, "answer"),
        ("dialogue", "questions", 1, "question"), ("dialogue", "questions", 1, "answer"),
        ("dialogue", "questions", 2, "question"), ("dialogue", "questions", 2, "answer"),
        ("dialogue", "questions", 3, "question"), ("dialogue", "questions", 3, "answer"),
        ("dialogue", "questions", 3, "condition"),
        ("dialogue", "questions", 6, "question"), ("dialogue", "questions", 6, "answer"),
        ("dialogue", "questions", 7, "question"), ("dialogue", "questions", 7, "answer"),
        ("hints", 0, "french"), ("hints", 0, "english"),
        ("hints", 1, "french"), ("hints", 1, "english"),
        ("hints", 2, "french"), ("hints", 2, "english"),
        ("hints", 3, "french"), ("hints", 3, "english"),
        ("hints", 6, "french"), ("hints", 6, "english"),
        ("hints", 7, "french"), ("hints", 7, "english"),
    ),
}

BEGINNER_COURSE_FOLLOWUP_FIELDS = {
    "language-school-new-language": (
        ("dialogue", "questions", 1, "question"),
        ("dialogue", "questions", 1, "condition"),
        ("hints", 1, "french"), ("hints", 1, "english"),
    ),
}

AFTER_SCHOOL_FOLLOWUP_FIELDS = {
    "parent-after-school-activity-advice": (
        ("dialogue", "questions", 2, "question"),
        ("hints", 2, "french"), ("hints", 2, "english"),
    ),
}

CHILD_STAY_FOLLOWUP_FIELDS = {
    "friend-child-language-stay-abroad": (
        ("dialogue", "note"), ("dialogue", "opening"), ("dialogue", "closing"),
        ("dialogue", "questions", 0, "topic"), ("dialogue", "questions", 0, "question"),
        ("dialogue", "questions", 0, "answer"),
        ("dialogue", "questions", 1, "topic"), ("dialogue", "questions", 1, "question"),
        ("dialogue", "questions", 1, "answer"), ("dialogue", "questions", 1, "follow_up_to"),
        ("dialogue", "questions", 1, "condition"),
        ("dialogue", "questions", 2, "topic"), ("dialogue", "questions", 2, "question"),
        ("dialogue", "questions", 2, "answer"),
        ("dialogue", "questions", 4, "question"),
        ("dialogue", "questions", 5, "question"), ("dialogue", "questions", 5, "answer"),
        ("dialogue", "questions", 5, "condition"),
        ("dialogue", "questions", 7, "answer"),
        ("hints", 0, "french"), ("hints", 0, "english"),
        ("hints", 1, "french"), ("hints", 1, "english"),
        ("hints", 2, "french"), ("hints", 2, "english"),
        ("hints", 4, "french"), ("hints", 4, "english"),
        ("hints", 5, "french"), ("hints", 5, "english"),
    ),
}

SCHOOL_NEIGHBOUR_FOLLOWUP_FIELDS = {
    "edmonton-newcomer-neighbor-schools": (
        ("dialogue", "note"),
        ("dialogue", "questions", 0, "question"), ("dialogue", "questions", 0, "answer"),
        ("dialogue", "questions", 2, "topic"), ("dialogue", "questions", 2, "question"),
        ("dialogue", "questions", 2, "answer"),
        ("dialogue", "questions", 3, "question"), ("dialogue", "questions", 3, "answer"),
        ("dialogue", "questions", 4, "topic"), ("dialogue", "questions", 4, "question"),
        ("dialogue", "questions", 4, "answer"),
        ("dialogue", "questions", 5, "question"), ("dialogue", "questions", 5, "answer"),
        ("dialogue", "questions", 5, "follow_up_to"), ("dialogue", "questions", 5, "condition"),
        ("dialogue", "questions", 6, "topic"), ("dialogue", "questions", 6, "question"),
        ("dialogue", "questions", 6, "answer"),
        ("dialogue", "questions", 6, "follow_up_to"), ("dialogue", "questions", 6, "condition"),
        ("hints", 0, "french"), ("hints", 0, "english"),
        ("hints", 2, "french"), ("hints", 2, "english"),
        ("hints", 3, "french"), ("hints", 3, "english"),
        ("hints", 4, "french"), ("hints", 4, "english"),
        ("hints", 5, "french"), ("hints", 5, "english"),
        ("hints", 6, "french"), ("hints", 6, "english"),
    ),
}

CAREER_QUESTION_FOLLOWUP_FIELDS = {
    "friend-planned-canadian-studies": (("dialogue", "questions", 3, "question"),),
}

SURVEY_ROUTINE_FOLLOWUP_FIELDS = {
    "french-class-survey-francophone-student": (
        ("dialogue", "note"),
        ("dialogue", "questions", 2, "question"), ("dialogue", "questions", 2, "answer"),
        ("dialogue", "questions", 3, "topic"), ("dialogue", "questions", 3, "question"),
        ("dialogue", "questions", 3, "answer"),
        ("dialogue", "questions", 4, "question"), ("dialogue", "questions", 4, "answer"),
        ("dialogue", "questions", 4, "follow_up_to"), ("dialogue", "questions", 4, "condition"),
        ("dialogue", "questions", 5, "topic"), ("dialogue", "questions", 5, "question"),
        ("dialogue", "questions", 5, "answer"),
        ("dialogue", "questions", 5, "follow_up_to"), ("dialogue", "questions", 5, "condition"),
        ("dialogue", "questions", 6, "question"), ("dialogue", "questions", 6, "answer"),
        ("dialogue", "questions", 6, "follow_up_to"), ("dialogue", "questions", 6, "condition"),
        ("hints", 2, "french"), ("hints", 2, "english"),
        ("hints", 3, "french"), ("hints", 3, "english"),
        ("hints", 4, "french"), ("hints", 4, "english"),
        ("hints", 5, "french"), ("hints", 5, "english"),
        ("hints", 6, "french"), ("hints", 6, "english"),
    ),
}

SESSION_EXTENT_FOLLOWUP_FIELDS = {
    "calgary-university-adult-language-courses": (("dialogue", "questions", 4, "question"),),
}

WORK_COMPARISON_CLOSING_FIELDS = {
    "canadian-work-hours-home-country-comparison": (("dialogue", "closing"),),
}

DAILY_DUTIES_FOLLOWUP_FIELDS = {
    "former-colleague-new-job-to-change-employment": (("dialogue", "questions", 1, "question"),),
}

RECRUITER_RICH_FOLLOWUP_FIELDS = {
    "recruiter-scheduled-interview-preparation": (
        ("dialogue", "note"),
        ("dialogue", "questions", 1, "question"), ("dialogue", "questions", 1, "answer"),
        ("dialogue", "questions", 1, "condition"),
        ("dialogue", "questions", 3, "topic"), ("dialogue", "questions", 3, "question"),
        ("dialogue", "questions", 3, "answer"),
        ("dialogue", "questions", 4, "topic"), ("dialogue", "questions", 4, "question"),
        ("dialogue", "questions", 4, "answer"),
        ("dialogue", "questions", 5, "topic"), ("dialogue", "questions", 5, "question"),
        ("dialogue", "questions", 5, "answer"),
        ("dialogue", "questions", 6, "topic"), ("dialogue", "questions", 6, "question"),
        ("dialogue", "questions", 6, "follow_up_to"), ("dialogue", "questions", 6, "condition"),
        ("dialogue", "questions", 7, "topic"),
        ("hints", 1, "french"), ("hints", 1, "english"),
        ("hints", 3, "french"), ("hints", 3, "english"),
        ("hints", 4, "french"), ("hints", 4, "english"),
        ("hints", 5, "french"), ("hints", 5, "english"),
        ("hints", 6, "french"), ("hints", 6, "english"),
    ),
}

INTERNAL_PAY_FOLLOWUP_FIELDS = {
    "colleague-internal-job-change": (
        ("dialogue", "questions", 4, "question"),
        ("dialogue", "questions", 5, "question"), ("dialogue", "questions", 5, "condition"),
        ("hints", 4, "french"), ("hints", 4, "english"),
        ("hints", 5, "french"), ("hints", 5, "english"),
    ),
}

INTERVIEW_CLOTHING_FOLLOWUP_FIELDS = {
    "friend-upcoming-job-interview-advice": (
        ("dialogue", "questions", 4, "question"), ("dialogue", "questions", 4, "answer"),
        ("dialogue", "questions", 4, "condition"),
        ("hints", 4, "french"), ("hints", 4, "english"),
    ),
}

LODGING_DISCOUNT_FOLLOWUP_FIELDS = {
    "quebec-region-accommodation-tourist-office": (
        ("dialogue", "questions", 5, "question"), ("dialogue", "questions", 5, "answer"),
        ("hints", 5, "french"), ("hints", 5, "english"),
    ),
}

HOUSE_FACILITIES_FOLLOWUP_FIELDS = {
    "colleague-summer-house-rental": (
        ("dialogue", "questions", 4, "question"), ("dialogue", "questions", 4, "answer"),
        ("hints", 4, "french"), ("hints", 4, "english"),
    ),
}

ACCOMMODATION_FOLLOWUP_FIELDS = LODGING_DISCOUNT_FOLLOWUP_FIELDS | HOUSE_FACILITIES_FOLLOWUP_FIELDS

# -1 identifies a model with no archived layout before its later replacement.
FOLLOWUP_ARCHIVE_INDEX = PUBLISHED_ARCHIVE_INDEX | {
    "quebec-region-accommodation-tourist-office": -1,
    "colleague-summer-house-rental": 1,
}

FOLLOWUP_FIELDS = (
    TRAINING_FOLLOWUP_FIELDS | FIRST_DAY_FOLLOWUP_FIELDS
    | JOB_SEARCH_FOLLOWUP_FIELDS | BEGINNER_COURSE_FOLLOWUP_FIELDS
    | AFTER_SCHOOL_FOLLOWUP_FIELDS | CHILD_STAY_FOLLOWUP_FIELDS
    | SCHOOL_NEIGHBOUR_FOLLOWUP_FIELDS
    | CAREER_QUESTION_FOLLOWUP_FIELDS
    | SURVEY_ROUTINE_FOLLOWUP_FIELDS
    | SESSION_EXTENT_FOLLOWUP_FIELDS
    | WORK_COMPARISON_CLOSING_FIELDS
    | DAILY_DUTIES_FOLLOWUP_FIELDS
    | RECRUITER_RICH_FOLLOWUP_FIELDS
    | INTERNAL_PAY_FOLLOWUP_FIELDS
    | INTERVIEW_CLOTHING_FOLLOWUP_FIELDS
    | ACCOMMODATION_FOLLOWUP_FIELDS
)
FOLLOWUP_GROUPS = set(FOLLOWUP_FIELDS)
FOLLOWUP_PROTECTED_SHA = "586b0920641213bb36ad2afacc07fb4ee0600edf35e738efedec1918f92168b0"

# Counts and digests frozen from eo2-realness-baseline.json, captured at
# bec7605 before the all-theme review. These identify editions, not today's
# prose: a changed public layout must survive at its append-only archive index.
PRE_REALNESS_ARCHIVE_COUNTS = {
    'acquaintance-hiking-walking-club': 0,
    'acquaintance-new-job-overall-experience': 3,
    'acquaintance-recent-cinema-film': 1,
    'animal-protection-association-invitation': 2,
    'bicycle-rental-model-and-terms': 2,
    'bookshop-public-game-participation': 1,
    'calgary-university-adult-language-courses': 4,
    'camping-reception-stay-preparation': 0,
    'canada-car-breakdown-insurer': 1,
    'canada-cinema-employee-friend': 0,
    'canada-newcomer-apartment-procedure-unspecified-adviser': 1,
    'canada-newcomer-municipal-settlement-service': 0,
    'canada-newcomer-settlement-friend': 0,
    'canadian-city-resident-advice-transit': 1,
    'canadian-friend-long-time-catch-up': 0,
    'canadian-friend-wedding-guest-preparation': 0,
    'canadian-press-newsagent-selection': 1,
    'canadian-tourist-office-restful-weekend': 1,
    'canadian-work-hours-home-country-comparison': 4,
    'child-friends-family-holiday-invitation': 4,
    'colleague-association-dance-classes': 1,
    'colleague-babysitter-referral-needs': 4,
    'colleague-board-game-club': 1,
    'colleague-canada-tour-next-summer': 1,
    'colleague-canada-trip-report': 2,
    'colleague-internal-job-change': 3,
    'colleague-invitation-unspecified-show': 0,
    'colleague-known-region-holiday': 1,
    'colleague-looking-for-sports-partner': 1,
    'colleague-management-promotion-party': 1,
    'colleague-montreal-work-week-transit': 1,
    'colleague-recommended-city-weekend': 0,
    'colleague-summer-house-rental': 3,
    'colleague-unusable-music-festival-tickets': 0,
    'colleague-wedding-report': 1,
    'cultural-center-reception-activities': 1,
    'director-canada-fortnight-training': 3,
    'edmonton-newcomer-neighbor-schools': 5,
    'employee-yoga-colleague-organizer': 0,
    'estate-agent-advertised-apartment-purchase': 2,
    'estate-agent-advertised-apartment-unspecified': 2,
    'estate-agent-housing-options': 1,
    'experienced-blogger-start-travel-blog': 1,
    'fellow-parent-first-school-fete': 4,
    'former-colleague-new-job-to-change-employment': 3,
    'french-class-survey-francophone-student': 4,
    'french-teacher-canadian-new-year-customs': 0,
    'french-teacher-language-school-student-game': 4,
    'french-teacher-study-abroad-advice': 4,
    'friend-association-work-experience': 3,
    'friend-birthday-party-on-boat': 1,
    'friend-canada-cross-country-skiing': 1,
    'friend-canada-partner-birthday-trip': 2,
    'friend-canadian-weekend-customs': 0,
    'friend-carpooling-offer': 2,
    'friend-child-language-stay-abroad': 6,
    'friend-choose-film-ticket-already-held': 1,
    'friend-choose-television-series': 1,
    'friend-choose-tonight-outing': 1,
    'friend-city-for-cultural-magazine-article': 1,
    'friend-city-housing-search-advice': 1,
    'friend-concert-invitation': 0,
    'friend-cooking-workshop-experience': 1,
    'friend-entertain-visiting-nephews': 3,
    'friend-films-for-association-review': 1,
    'friend-first-workday-report': 3,
    'friend-holiday-apartment-watch': 5,
    'friend-homeless-meal-volunteering': 4,
    'friend-mountain-holiday-advice': 2,
    'friend-moving-abroad-sale': 0,
    'friend-music-festival-organizer': 0,
    'friend-new-ottawa-restaurant': 1,
    'friend-planned-canadian-studies': 4,
    'friend-reading-for-literary-review': 1,
    'friend-seaside-holiday-advice': 1,
    'friend-shows-for-association-article': 1,
    'friend-sister-birthday-gift': 1,
    'friend-sports-center-club-membership': 0,
    'friend-three-year-old-weekend-care': 4,
    'friend-tv-game-participation': 0,
    'friend-two-years-quebec-expatriation-experience': 0,
    'friend-unspecified-artistic-activity': 1,
    'friend-upcoming-canada-trip-advice': 2,
    'friend-upcoming-job-interview-advice': 3,
    'friend-used-electric-bicycle-sale': 2,
    'friend-visited-countries-destination-choice': 2,
    'friend-weekend-getaway-advice': 1,
    'friend-weekly-theatre-class': 0,
    'furniture-delivery-service': 1,
    'grocery-store-home-delivery': 6,
    'guitar-teacher-lesson-enrollment': 1,
    'help-friend-find-rental-needs': 1,
    'help-friend-moving-day': 0,
    'help-friend-post-parcel': 5,
    'help-transport-heavy-objects-no-vehicle': 2,
    'holiday-car-rental-agency': 1,
    'holiday-region-tourist-office': 0,
    'home-chef-family-meal': 1,
    'host-foreign-friends-city-advice': 3,
    'hotel-host-services': 0,
    'hotel-reception-room-booking': 0,
    'interlocutor-planned-mountain-trip': 2,
    'invite-friend-countryside-stay': 1,
    'language-school-new-language': 5,
    'local-acquaintance-birthday-restaurant-choice': 1,
    'medical-secretary-temporary-replacement-doctor': 3,
    'municipal-cultural-service-city-activities': 1,
    'municipal-library-document-borrowing': 1,
    'municipal-pool-learn-swimming-reception': 0,
    'museum-group-visit-reception': 1,
    'music-school-course-information': 0,
    'neighbor-child-one-day-care': 3,
    'neighbor-community-sports-instructor': 1,
    'neighbor-dog-care-week-paid': 4,
    'neighbor-environmental-association-volunteering': 3,
    'neighbor-friends-countryside-outing-advice': 1,
    'neighbor-gardening-activity-organizer': 1,
    'neighbor-home-childcare-provider-referral': 3,
    'neighbor-home-music-tutor-advice': 0,
    'neighbor-municipal-cultural-outings': 1,
    'neighbor-municipal-pool-information': 1,
    'neighbor-party-planning-advice': 1,
    'neighbor-photography-association-class': 0,
    'neighbor-regular-carpool-invitation': 2,
    'neighbor-seaside-house-rental': 1,
    'neighbor-vancouver-running-race': 1,
    'neighborhood-library-membership': 1,
    'new-city-friend-low-budget-outings': 1,
    'new-colleague-quebec-career-migration': 2,
    'new-employee-company-orientation': 3,
    'new-neighbor-evening-entertainment': 2,
    'new-quebec-resident-first-party': 0,
    'new-resident-neighbor-neighborhood-orientation': 0,
    'newcomer-canada-friend-job-market': 3,
    'newcomer-canada-private-french-teacher': 3,
    'newcomer-city-transit-service': 1,
    'newcomer-colleague-meet-people': 0,
    'newcomer-local-acquaintance-meet-people': 1,
    'newcomer-neighbor-partner-surprise-birthday': 1,
    'offered-room-in-existing-shared-apartment': 1,
    'ottawa-newcomer-cycling-friend': 1,
    'owner-holiday-letting-estate-agency-advice': 1,
    'parent-after-school-activity-advice': 3,
    'party-new-acquaintance-trip-report': 1,
    'plan-friends-birthday-with-birthday-person': 1,
    'private-owner-used-car-purchase': 2,
    'quebec-newcomer-estate-agency-housing-procedures': 2,
    'quebec-region-accommodation-tourist-office': 1,
    'recruiter-scheduled-interview-preparation': 4,
    'retirement-party-invitation': 1,
    'specialist-agency-day-excursions': 1,
    'sport-club-reception-choose-activity': 1,
    'station-stranger-mountain-passion': 1,
    'supervisor-overseas-job-offer': 4,
    'tourist-office-city-discovery-with-friends': 1,
    'tourist-office-low-budget-weekend': 1,
    'toy-library-membership': 1,
    'travel-agency-canada-cruise': 1,
    'travel-agency-canada-stay': 2,
    'travel-agency-choose-holiday-destination': 3,
    'trusted-person-temporary-pet-care': 3,
    'visit-colleague-minor-accident': 5,
    'visit-friend-canada-december-preparation': 2,
    'volunteer-local-association-information-office': 4,
}


def _fingerprint(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True).encode(),
    ).hexdigest()


def pre_realness_history(document):
    """Select the real retained prefix before applying an older edition projection."""
    previous = copy.deepcopy(document)
    previous["groups"] = {
        group: {
            **copy.deepcopy(document["groups"][group]),
            "revisions": copy.deepcopy(document["groups"][group]["revisions"][:count]),
        }
        for group, count in PRE_REALNESS_ARCHIVE_COUNTS.items() if count
    }
    assert _fingerprint(previous) == (
        "d8e52c65157716ee96cef1f17f4ecb2816aaee5d0ab070fcc30a46ddf1db7d24"
    ), "An earlier archive or geographic replacement changed"
    return previous


def preserved_public_layouts():
    """Return original public editions from actual archives or unchanged current rows."""
    raw = {
        row["group"]: row
        for path in (content.QUESTION_BANK_DIR / "dialogues").glob("*.json")
        for row in json.loads(path.read_text())["dialogues"]
    }
    history = json.loads(
        (content.QUESTION_BANK_DIR / "dialogue_history/locations.json").read_text(),
    )
    pre_realness_history(history)
    assert set(raw) == set(PRE_REALNESS_ARCHIVE_COUNTS)
    assert set(history["groups"]) <= set(raw)
    # The host-friend transit variant now uses tu directly, rather than asking
    # the learner to adapt a neighbour's vous model in a publication note.
    assert _fingerprint(sorted(
        (group, row["register"]) for group, row in raw.items()
    )) == "d37ae3561719f64c5a211ccb93012d37b90a08f2ec832397605ccac871d9755a"
    layouts = {}
    for group, count in PRE_REALNESS_ARCHIVE_COUNTS.items():
        archive = history["groups"].get(group, {})
        revisions = archive.get("revisions", [])
        if not count and archive:
            assert archive["replacements"] == [], group
        for revision in revisions[count:]:
            assert revisions.count(revision) == 1, group
            assert set(revision) == {"group", "opening", "closing", "questions"}, group
            assert revision["group"] == group, group
            assert len(revision["questions"]) == 8, group
            assert all(
                set(question) <= {"topic", "question", "follow_up_to", "condition"}
                for question in revision["questions"]
            ), group
        row = raw[group]
        current = {
            "group": group, "opening": row["opening"], "closing": row["closing"],
            "questions": [
                {key: value for key, value in question.items() if key != "answer"}
                for question in row["questions"]
            ],
        }
        before = revisions[count] if len(revisions) > count else current
        assert all("answer" not in question for question in before["questions"]), group
        layouts[group] = before
    assert _fingerprint(layouts) == (
        "0cde977a27dd27f96b2902d310897f119f58738a1cbe3e3d5ebc6e8f19b8fe8d"
    ), "A pre-review public layout was lost or changed"
    return layouts


def assert_review_preservation(test):
    """Supersede old exclusion scopes with exact append-only public/history checks."""
    test.assertEqual(len(preserved_public_layouts()), 164)
    hints = json.loads(content.TACHE_TWO_SUBJECT_HINTS_PATH.read_text())["groups"]
    test.assertEqual(set(hints), set(PRE_REALNESS_ARCHIVE_COUNTS))
    for group, cues in hints.items():
        with test.subTest(group=group):
            test.assertEqual(len(cues), 8)
            for cue in cues:
                test.assertEqual(set(cue), {"french", "english"})
                test.assertTrue(all(isinstance(value, str) and value.strip()
                                    for value in cue.values()))


def final_pass_projection(dialogues, hints):
    snapshot = {
        group: {"dialogue": copy.deepcopy(row), "hints": copy.deepcopy(hints[group])}
        for group, row in dialogues.items()
    }
    for fields in (FINAL_PASS_FIELDS, FOLLOWUP_FIELDS):
        for group, paths in fields.items():
            for path in paths:
                value = snapshot[group]
                for key in path[:-1]:
                    value = value[key]
                value[path[-1]] = "<final-reviewed-field>"
    return snapshot


def remove_latest_review_archives(document):
    remove_followup_archives(
        document, FOLLOWUP_ARCHIVE_INDEX.keys() - PUBLISHED_ARCHIVE_INDEX.keys(),
    )
    for group, index in PUBLISHED_ARCHIVE_INDEX.items():
        if group in FIRST_ARCHIVE_GROUPS:
            del document["groups"][group]
        else:
            document["groups"][group]["revisions"] = document["groups"][group]["revisions"][:index]


def remove_followup_archives(document, groups=None):
    for group in FOLLOWUP_ARCHIVE_INDEX if groups is None else groups:
        index = FOLLOWUP_ARCHIVE_INDEX[group]
        if index < 0:
            if group in document["groups"]:
                del document["groups"][group]
        else:
            document["groups"][group]["revisions"] = document["groups"][group]["revisions"][:index + 1]
