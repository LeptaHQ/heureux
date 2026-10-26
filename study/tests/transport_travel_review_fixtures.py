from study.tests.travel_fixtures import TRAVEL_GROUPS


TRANSPORT_GROUPS = {
    "newcomer-city-transit-service",
    "canada-car-breakdown-insurer",
    "private-owner-used-car-purchase",
    "holiday-car-rental-agency",
    "ottawa-newcomer-cycling-friend",
    "friend-carpooling-offer",
    "neighbor-regular-carpool-invitation",
    "bicycle-rental-model-and-terms",
    "canadian-city-resident-advice-transit",
    "friend-used-electric-bicycle-sale",
    "colleague-montreal-work-week-transit",
}
REVIEWED_GROUPS = TRANSPORT_GROUPS | TRAVEL_GROUPS["voyages"]
FIRST_ARCHIVE_GROUPS = {
    "holiday-car-rental-agency",
    "colleague-known-region-holiday",
    "newcomer-city-transit-service",
    "party-new-acquaintance-trip-report",
    "friend-seaside-holiday-advice",
    "colleague-canada-tour-next-summer",
    "canadian-city-resident-advice-transit",
    "travel-agency-canada-cruise",
    "colleague-montreal-work-week-transit",
    "canada-car-breakdown-insurer",
    "ottawa-newcomer-cycling-friend",
    "invite-friend-countryside-stay",
}


def remove_transport_travel_review_archives(document):
    for group in REVIEWED_GROUPS:
        if group in FIRST_ARCHIVE_GROUPS:
            del document["groups"][group]
        else:
            document["groups"][group]["revisions"].pop()
