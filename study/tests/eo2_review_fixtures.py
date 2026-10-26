import copy

from study.tests.test_tache_two_work_school_review import REVIEWED_GROUPS as WORK_SCHOOL_GROUPS
from study.tests.transport_travel_review_fixtures import (
    REVIEWED_GROUPS as TRANSPORT_TRAVEL_GROUPS,
    remove_transport_travel_review_archives,
)


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


def final_pass_projection(dialogues, hints):
    snapshot = {
        group: {"dialogue": copy.deepcopy(row), "hints": copy.deepcopy(hints[group])}
        for group, row in dialogues.items()
    }
    for group, paths in FINAL_PASS_FIELDS.items():
        for path in paths:
            value = snapshot[group]
            for key in path[:-1]:
                value = value[key]
            value[path[-1]] = "<final-reviewed-field>"
    return snapshot


def remove_latest_review_archives(document):
    for group in WORK_SCHOOL_GROUPS:
        document["groups"][group]["revisions"].pop()
    remove_transport_travel_review_archives(document)
