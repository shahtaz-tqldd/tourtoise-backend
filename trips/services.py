def build_agent_active_response(trip, normalized_payload):
    """
    Placeholder for the real trip-planning agent call.
    """
    return {
        "agent_active": True,
        "agent_active_failed_message": "",
        "agent_message": "Would you rather have one big highlight per day or lots of smaller experiences?",
    }


def update_user_profile_from_agent_preferences(user, normalized_payload):
    profile = getattr(user, "profile", None)
    if not profile:
        return None

    profile.travel_interests = normalized_payload["interest_tags"]
    profile.dietary_preferences = normalized_payload["dietary_needs"]
    profile.travel_pace = normalized_payload["travel_pace"]
    profile.mobility_constraints = normalized_payload["mobility_constraints"]
    profile.save(
        update_fields=[
            "travel_interests",
            "dietary_preferences",
            "travel_pace",
            "mobility_constraints",
        ]
    )
    return profile
