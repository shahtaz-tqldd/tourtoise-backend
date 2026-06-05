import json

from asgiref.sync import async_to_sync
from django.db.models import Max

from destinations.models import Activity, Attraction, Cuisine
from trips.models import TripAgentConversationSession, TripAgentMessage


def get_or_create_agent_conversation_session(trip, user, current_step=2):
    session = (
        TripAgentConversationSession.objects.filter(
            trip=trip,
            user=user,
            current_step=current_step,
            is_active=True,
        )
        .order_by("-updated_at")
        .first()
    )
    if session:
        return session

    return TripAgentConversationSession.objects.create(
        trip=trip,
        user=user,
        current_step=current_step,
        created_by=user,
        updated_by=user,
    )


def create_agent_message(session, sender, content="", payload=None, user=None):
    next_sequence = (session.messages.aggregate(max_sequence=Max("sequence"))["max_sequence"] or 0) + 1
    actor = user or session.user
    return TripAgentMessage.objects.create(
        session=session,
        trip=session.trip,
        sender=sender,
        step=session.current_step,
        sequence=next_sequence,
        content=content or "",
        payload=payload or {},
        created_by=actor,
        updated_by=actor,
    )


def build_trip_snapshot(trip):
    destinations = []
    trip_destinations = getattr(trip, "prefetched_trip_destinations", None)
    if trip_destinations is None:
        trip_destinations = trip.trip_destinations.select_related("destination").order_by("sort_order")

    for trip_destination in trip_destinations:
        destination = trip_destination.destination
        destinations.append(
            {
                "id": str(destination.id),
                "name": destination.name,
                "country": destination.country,
                "region": destination.region,
                "type": destination.destination_type,
                "overview": destination.overview,
                "budget_tier": destination.budget_tier,
                "difficulty": destination.difficulty,
                "min_stay_days": destination.min_stay_days,
                "max_stay_days": destination.max_stay_days,
                "best_travel_months": destination.best_travel_months,
                "getting_around": destination.getting_around,
                "visa_notes": destination.visa_notes,
                "cultural_tips": destination.cultural_tips,
            }
        )

    return {
        "trip_id": str(trip.id),
        "duration_days": trip.duration_days,
        "travelers_count": trip.travelers_count,
        "traveler_type": trip.traveler_type,
        "origin_city": trip.origin_city,
        "origin_country": trip.origin_country,
        "budget": str(trip.total_budget) if trip.total_budget is not None else None,
        "destinations": destinations,
    }


def run_plan_agent_for_session(
    session,
    user_query,
    preferences=None,
    trip_snapshot=None,
    destination_id=None,
    trip_context=None,
):
    from trips.agents.planning_agent import PlanAgentClient

    client = PlanAgentClient(
        session.trip,
        current_step=session.current_step,
        destination_id=str(destination_id) if destination_id else None,
        trip_context=trip_context,
    )
    result = async_to_sync(client.run_agent)(
        user_query=user_query,
        user_id=str(session.user_id),
        session_id=session.external_session_id or None,
        preferences=preferences,
        trip_snapshot=trip_snapshot,
    )

    external_session_id = result.get("session_id") or ""
    if external_session_id and session.external_session_id != external_session_id:
        session.external_session_id = external_session_id
        session.save(update_fields=["external_session_id", "updated_at"])

    return result


def build_initial_agent_query(preferences, trip_snapshot):
    return (
        "The traveler just submitted these initial trip preferences and trip snapshot. "
        "Ask the single most useful follow-up question for step 2 preference intake.\n"
        f"Preferences: {json.dumps(preferences, default=str)}\n"
        f"Trip snapshot: {json.dumps(trip_snapshot, default=str)}"
    )


def build_followup_agent_query(message, preferences, trip_snapshot):
    return (
        f"Traveler answer: {message}\n"
        "Use the stored conversation, preferences, and trip snapshot to either ask the next single "
        "follow-up question or finish with the final context.\n"
        f"Preferences: {json.dumps(preferences, default=str)}\n"
        f"Trip snapshot: {json.dumps(trip_snapshot, default=str)}"
    )


def build_recommendations_agent_query(preferences, trip_snapshot, destination_id):
    return (
        "Generate step 3 trip recommendations for the selected destination. "
        "Use the destination item tool, the trip snapshot, and the saved preference context. "
        "Return only the structured recommendation JSON.\n"
        f"Destination ID: {destination_id}\n"
        f"Preferences: {json.dumps(preferences or {}, default=str)}\n"
        f"Trip snapshot: {json.dumps(trip_snapshot or {}, default=str)}"
    )


def build_itinerary_agent_query(trip_context):
    return (
        "Generate step 4 itinerary design from this compact trip planning context. "
        "Use the provided trip data directly as the source of truth. Return only the structured itinerary JSON.\n"
        f"Trip planning context: {json.dumps(trip_context or {}, default=str)}"
    )


def build_itinerary_planning_context(trip):
    agent_context = trip.agent_context or {}
    recommendations = agent_context.get("recommendations") or {}
    trip_snapshot = build_trip_snapshot(trip)

    return {
        **trip_snapshot,
        "title": trip.title,
        "start_date": trip.start_date.isoformat() if trip.start_date else None,
        "end_date": trip.end_date.isoformat() if trip.end_date else None,
        "nights": trip.nights,
        "budget_currency": trip.budget_currency,
        "start_location": {
            "address": trip.start_location_address,
            "latitude": trip.start_location_latitude,
            "longitude": trip.start_location_longitude,
        },
        "preferences": trip.preferences or {},
        "constraints": trip.constraints or {},
        "preference_context": (agent_context.get("preference_qna") or {}).get("context"),
        "selected_recommendations": {
            "tour_spots": _serialize_selected_attractions(recommendations.get("tour_spot_ids", [])),
            "activities": _serialize_selected_activities(recommendations.get("activity_ids", [])),
            "food_items": _serialize_selected_cuisines(recommendations.get("food_item_ids", [])),
        },
        "recommendation_messages": recommendations.get("messages", {}),
    }


def _serialize_selected_attractions(selected_ids):
    items = Attraction.objects.filter(id__in=selected_ids)
    item_map = {str(item.id): item for item in items}
    return [
        {
            "id": str(item.id),
            "name": item.name,
            "type": item.attraction_type,
            "description": item.description,
            "address": item.address,
            "latitude": item.latitude,
            "longitude": item.longitude,
            "budget_tier": item.budget_tier,
            "avg_duration_hours": item.avg_duration_hours,
            "best_time_of_day": item.best_time_of_day,
            "entrance_fee_required": item.entrance_fee_required,
            "approx_entrance_fee": item.approx_entrance_fee,
        }
        for item_id in selected_ids
        if (item := item_map.get(str(item_id)))
    ]


def _serialize_selected_activities(selected_ids):
    items = Activity.objects.filter(id__in=selected_ids)
    item_map = {str(item.id): item for item in items}
    return [
        {
            "id": str(item.id),
            "name": item.name,
            "type": item.activity_type,
            "description": item.description,
            "difficulty_level": item.difficulty_level,
            "budget_tier": item.budget_tier,
            "approx_cost": str(item.approx_cost) if item.approx_cost is not None else None,
            "cost_unit": item.cost_unit,
            "duration_hours": item.duration_hours,
            "best_season": item.best_season,
            "booking_required": item.booking_required,
        }
        for item_id in selected_ids
        if (item := item_map.get(str(item_id)))
    ]


def _serialize_selected_cuisines(selected_ids):
    items = Cuisine.objects.filter(id__in=selected_ids)
    item_map = {str(item.id): item for item in items}
    return [
        {
            "id": str(item.id),
            "name": item.name,
            "type": item.cuisine_type,
            "description": item.description,
            "ingredients_note": item.ingredients_note,
            "spice_level": item.spice_level,
            "meal_type": item.meal_type,
            "is_vegetarian_friendly": item.is_vegetarian_friendly,
            "is_must_try": item.is_must_try,
            "approx_price_range": item.approx_price_range,
        }
        for item_id in selected_ids
        if (item := item_map.get(str(item_id)))
    ]


def update_trip_agent_context_from_qna(trip, agent_response, session, user):
    qna_response = agent_response.get("response") or {}
    context = qna_response.get("context")
    if not qna_response.get("is_qna_complete") or not context:
        return False

    agent_context = trip.agent_context or {}
    agent_context["preference_qna"] = {
        "context": context,
        "session_id": str(session.id),
        "external_session_id": session.external_session_id,
        "total_questions": session.qna_count,
    }
    trip.agent_context = agent_context
    trip.current_step = max(trip.current_step, 3)
    trip.updated_by = user
    trip.save(update_fields=["agent_context", "current_step", "updated_by", "updated_at"])

    session.is_active = False
    session.updated_by = user
    session.save(update_fields=["is_active", "updated_by", "updated_at"])
    return True


def update_trip_agent_context_from_recommendations(trip, agent_response, session, user):
    recommendations = agent_response.get("response") or {}
    if not recommendations.get("is_discovery_complete"):
        trip.agent_message = "Trip recommendations could not be generated yet."
        trip.updated_by = user
        trip.save(update_fields=["agent_message", "updated_by", "updated_at"])
        return {
            "is_discovery_complete": False,
            "tour_spot_ids": recommendations.get("tour_spot_ids", []),
            "activity_ids": recommendations.get("activity_ids", []),
            "food_item_ids": recommendations.get("food_item_ids", []),
            "messages": recommendations.get("messages", {}),
            "selection_instruction": recommendations.get("selection_instruction", ""),
            "session_id": str(session.id),
            "external_session_id": session.external_session_id,
        }

    agent_context = trip.agent_context or {}
    agent_context["recommendations"] = {
        "is_discovery_complete": recommendations.get("is_discovery_complete", False),
        "tour_spot_ids": recommendations.get("tour_spot_ids", []),
        "activity_ids": recommendations.get("activity_ids", []),
        "food_item_ids": recommendations.get("food_item_ids", []),
        "messages": recommendations.get("messages", {}),
        "selection_instruction": recommendations.get("selection_instruction", ""),
        "session_id": str(session.id),
        "external_session_id": session.external_session_id,
    }
    trip.agent_context = agent_context
    trip.current_step = max(trip.current_step, 4)
    trip.agent_message = agent_context["recommendations"]["selection_instruction"]
    trip.updated_by = user
    trip.save(update_fields=["agent_context", "current_step", "agent_message", "updated_by", "updated_at"])

    session.is_active = False
    session.updated_by = user
    session.save(update_fields=["is_active", "updated_by", "updated_at"])
    return agent_context["recommendations"]


def update_trip_agent_context_from_itinerary(trip, agent_response, session, user):
    itinerary = agent_response.get("response") or {}
    if not itinerary.get("is_itinerary_complete"):
        trip.agent_message = "Trip itinerary could not be generated yet."
        trip.updated_by = user
        trip.save(update_fields=["agent_message", "updated_by", "updated_at"])
        return {
            "is_itinerary_complete": False,
            "title": itinerary.get("title", ""),
            "summary": itinerary.get("summary", ""),
            "day_wise_plan": itinerary.get("day_wise_plan", []),
            "route_plan": itinerary.get("route_plan", []),
            "rough_budget": itinerary.get("rough_budget", {}),
            "message": itinerary.get("message", ""),
            "revision_instruction": itinerary.get("revision_instruction", ""),
            "session_id": str(session.id),
            "external_session_id": session.external_session_id,
        }

    agent_context = trip.agent_context or {}
    agent_context["itinerary_design"] = {
        "is_itinerary_complete": itinerary.get("is_itinerary_complete", False),
        "title": itinerary.get("title", ""),
        "summary": itinerary.get("summary", ""),
        "day_wise_plan": itinerary.get("day_wise_plan", []),
        "route_plan": itinerary.get("route_plan", []),
        "rough_budget": itinerary.get("rough_budget", {}),
        "message": itinerary.get("message", ""),
        "revision_instruction": itinerary.get("revision_instruction", ""),
        "session_id": str(session.id),
        "external_session_id": session.external_session_id,
    }
    trip.agent_context = agent_context
    trip.current_step = max(trip.current_step, 5)
    trip.agent_message = agent_context["itinerary_design"]["revision_instruction"]
    trip.updated_by = user
    trip.save(update_fields=["agent_context", "current_step", "agent_message", "updated_by", "updated_at"])

    session.is_active = False
    session.updated_by = user
    session.save(update_fields=["is_active", "updated_by", "updated_at"])
    return agent_context["itinerary_design"]


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
