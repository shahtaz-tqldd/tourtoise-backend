import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID

from asgiref.sync import async_to_sync
from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.utils import timezone

from destinations.models import Activity, Attraction, Cuisine
from trips.choices import (
    HeadsUpType,
    PackingItemsType,
    PlanningStep,
    PriorityType,
    RequiredType,
    SeverityType,
    TripStatus,
)
from trips.models import (
    TripAgentMessage,
    TripConversationMessage,
    TripConversationSession,
    TripPlanningSession,
    TripPlanningStepSession,
    TripActivityRecommendationItem,
    TripAttractionRecommendationItem,
    TripCuisineRecommendationItem,
    TripHeadsUpInfoItem,
    TripItinerary,
    TripItineraryBudget,
    TripItineraryDay,
    TripItineraryDayItem,
    TripPreparation,
    TripRecommendations,
    TripRoutePlanItem,
    TripPreparationPackingItem,
    TripRequiredDocumentItem,
)

PLANNING_STEP_ORDER = (
    PlanningStep.PREFERENCE,
    PlanningStep.RECOMMENDATION,
    PlanningStep.ITINERARY,
    PlanningStep.PREPARATION,
    PlanningStep.OVERVIEW,
)

PLANNING_STEP_LABELS = {
    PlanningStep.PREFERENCE: "Preference Q&A",
    PlanningStep.RECOMMENDATION: "Recommendations",
    PlanningStep.ITINERARY: "Itinerary design",
    PlanningStep.PREPARATION: "Trip preparation",
    PlanningStep.OVERVIEW: "Overview",
}

PLANNING_DOWNSTREAM_STEPS = {
    PlanningStep.RECOMMENDATION: (
        PlanningStep.RECOMMENDATION,
        PlanningStep.ITINERARY,
        PlanningStep.PREPARATION,
    ),
    PlanningStep.ITINERARY: (
        PlanningStep.ITINERARY,
        PlanningStep.PREPARATION,
    ),
    PlanningStep.PREPARATION: (PlanningStep.PREPARATION,),
}


def get_or_create_planning_session(trip, user):
    planning_session, _ = TripPlanningSession.objects.get_or_create(
        trip=trip,
        defaults={
            "user": user,
            "created_by": user,
            "updated_by": user,
        },
    )
    return planning_session


def get_or_create_conversation_session(trip, user, plan_ready=None):
    """Compatibility wrapper for the dedicated trip-chat service."""
    from trips.services.trip_chat import get_or_create_conversation_session as get_session

    return get_session(trip, user, plan_ready=plan_ready)


def get_or_create_planning_step_session(trip, user, step=None, current_step=None):
    step = step or current_step
    legacy_steps = {
        1: PlanningStep.PREFERENCE,
        2: PlanningStep.PREFERENCE,
        3: PlanningStep.RECOMMENDATION,
        4: PlanningStep.ITINERARY,
        5: PlanningStep.PREPARATION,
        6: PlanningStep.COMPLETED,
        "1": PlanningStep.PREFERENCE,
        "2": PlanningStep.PREFERENCE,
        "3": PlanningStep.RECOMMENDATION,
        "4": PlanningStep.ITINERARY,
        "5": PlanningStep.PREPARATION,
        "6": PlanningStep.COMPLETED,
    }
    step = legacy_steps.get(step, step or PlanningStep.PREFERENCE)
    planning_session = get_or_create_planning_session(trip, user)
    session, _ = TripPlanningStepSession.objects.get_or_create(
        planning_session=planning_session,
        step=step,
        defaults={
            "trip": trip,
            "user": user,
            "created_by": user,
            "updated_by": user,
        },
    )
    return session


def get_or_create_agent_conversation_session(trip, user, step=None, current_step=None):
    """Compatibility wrapper for callers using the old planning-session name."""
    return get_or_create_planning_step_session(
        trip,
        user,
        step=step,
        current_step=current_step,
    )


def create_agent_message(session, sender, content="", metadata=None, user=None):
    actor = user or session.user
    return TripAgentMessage.objects.create(
        session=session,
        sender=sender,
        content=content or "",
        metadata=metadata or {},
        created_by=actor,
        updated_by=actor,
    )


def create_conversation_message(
    session,
    sender,
    content="",
    metadata=None,
    user=None,
    read_at=None,
):
    """Compatibility wrapper for the dedicated trip-chat service."""
    from trips.services.trip_chat import create_conversation_message as create_message

    return create_message(
        session=session,
        sender=sender,
        content=content,
        metadata=metadata,
        user=user,
        read_at=read_at,
    )


def invalidate_trip_planning(trip, from_step, user=None):
    """Mark generated artifacts stale while keeping them recoverable until regeneration."""
    affected_steps = PLANNING_DOWNSTREAM_STEPS.get(from_step, ())
    if not affected_steps:
        return trip

    metadata = dict(trip.metadata or {})
    invalidated_steps = set(metadata.get("invalidated_planning_steps") or [])
    invalidated_steps.update(affected_steps)
    metadata["invalidated_planning_steps"] = sorted(invalidated_steps)

    field_by_step = {
        PlanningStep.RECOMMENDATION: "is_recommendation_complete",
        PlanningStep.ITINERARY: "is_itinerary_design_complete",
        PlanningStep.PREPARATION: "is_trip_preparation_complete",
    }
    update_fields = ["metadata", "current_step", "updated_at"]
    for step in affected_steps:
        field_name = field_by_step[step]
        setattr(trip, field_name, False)
        update_fields.append(field_name)

    trip.metadata = metadata
    if not trip.is_qna_complete:
        trip.current_step = PlanningStep.PREFERENCE
    elif from_step in {PlanningStep.ITINERARY, PlanningStep.PREPARATION} and not (
        trip.is_recommendation_complete
    ):
        trip.current_step = PlanningStep.RECOMMENDATION
    elif from_step == PlanningStep.PREPARATION and not trip.is_itinerary_design_complete:
        trip.current_step = PlanningStep.ITINERARY
    else:
        trip.current_step = from_step
    if user is not None:
        trip.updated_by = user
        update_fields.append("updated_by")
    trip.save(update_fields=list(dict.fromkeys(update_fields)))

    session_updates = {
        "is_active": True,
        "external_session_id": "",
        "updated_at": timezone.now(),
    }
    if user is not None:
        session_updates["updated_by"] = user
    TripPlanningSession.objects.filter(trip=trip).update(
        is_active=True,
        updated_at=timezone.now(),
        **({"updated_by": user} if user is not None else {}),
    )
    TripPlanningStepSession.objects.filter(
        trip=trip,
        step__in=affected_steps,
    ).update(**session_updates)
    return trip


def restart_trip_preference_planning(trip, user):
    """Start a fresh preference round and invalidate every generated downstream step."""
    invalidate_trip_planning(trip, PlanningStep.RECOMMENDATION, user=user)
    metadata = dict(trip.metadata or {})
    metadata.pop("preference_qna", None)
    trip.metadata = metadata
    trip.is_qna_complete = False
    trip.current_step = PlanningStep.PREFERENCE
    trip.agent_active = True
    trip.updated_by = user
    trip.save(
        update_fields=[
            "metadata",
            "is_qna_complete",
            "current_step",
            "agent_active",
            "updated_by",
            "updated_at",
        ]
    )
    TripPlanningStepSession.objects.filter(
        trip=trip,
        step=PlanningStep.PREFERENCE,
    ).update(
        is_active=True,
        external_session_id="",
        updated_by=user,
        updated_at=timezone.now(),
    )
    return trip


def get_invalidated_planning_steps(trip):
    invalidated = set((trip.metadata or {}).get("invalidated_planning_steps") or [])
    return [step for step in PLANNING_STEP_ORDER if step in invalidated]


def _clear_step_invalidation(metadata, step):
    invalidated_steps = set(metadata.get("invalidated_planning_steps") or [])
    invalidated_steps.discard(step)
    if invalidated_steps:
        metadata["invalidated_planning_steps"] = sorted(invalidated_steps)
    else:
        metadata.pop("invalidated_planning_steps", None)


def get_trip_planning_progress(trip):
    agent_context = trip.metadata or {}
    preference_qna = (
        agent_context.get("preference_qna")
        if isinstance(agent_context.get("preference_qna"), dict)
        else {}
    )
    recommendations = (
        agent_context.get("recommendations")
        if isinstance(agent_context.get("recommendations"), dict)
        else {}
    )
    itinerary_design = (
        agent_context.get("itinerary_design")
        if isinstance(agent_context.get("itinerary_design"), dict)
        else {}
    )
    trip_preparation = (
        agent_context.get("trip_preparation")
        if isinstance(agent_context.get("trip_preparation"), dict)
        else {}
    )

    stale_steps = get_invalidated_planning_steps(trip)
    recommendation_is_current = PlanningStep.RECOMMENDATION not in stale_steps
    itinerary_is_current = PlanningStep.ITINERARY not in stale_steps
    preparation_is_current = PlanningStep.PREPARATION not in stale_steps
    has_saved_recommendations = (
        recommendation_is_current and _has_related_object(trip, "trip_recommendations")
    )
    has_saved_itinerary = itinerary_is_current and _has_related_object(trip, "trip_itinerary")
    has_saved_preparation = (
        preparation_is_current and _has_related_object(trip, "structured_preparation")
    )

    return {
        "current_step": trip.current_step,
        "agent_active": trip.agent_active,
        "stale_steps": stale_steps,
        "is_qna_complete": bool(trip.is_qna_complete or preference_qna.get("context")),
        "is_recommendation_complete": bool(
            recommendation_is_current
            and (
                trip.is_recommendation_complete
                or recommendations.get("is_discovery_complete")
                or has_saved_recommendations
            )
        ),
        "is_itinerary_design_complete": bool(
            itinerary_is_current
            and (
                trip.is_itinerary_design_complete
                or itinerary_design.get("is_itinerary_complete")
                or has_saved_itinerary
            )
        ),
        "is_trip_preparation_complete": bool(
            preparation_is_current
            and (
                trip.is_trip_preparation_complete
                or trip_preparation.get("is_preparation_complete")
                or has_saved_preparation
            )
        ),
    }


def is_trip_plan_ready(trip):
    progress = get_trip_planning_progress(trip)
    return all(
        (
            progress["is_qna_complete"],
            progress["is_recommendation_complete"],
            progress["is_itinerary_design_complete"],
            progress["is_trip_preparation_complete"],
        )
    )


def get_trip_planning_flow(trip, progress=None):
    progress = progress or get_trip_planning_progress(trip)
    return [
        {
            "step": PlanningStep.PREFERENCE,
            "label": PLANNING_STEP_LABELS[PlanningStep.PREFERENCE],
            "is_complete": progress["is_qna_complete"],
            "is_stale": False,
            "is_current": trip.current_step == PlanningStep.PREFERENCE,
            "can_open": True,
            "can_generate": not progress["is_qna_complete"],
        },
        {
            "step": PlanningStep.RECOMMENDATION,
            "label": PLANNING_STEP_LABELS[PlanningStep.RECOMMENDATION],
            "is_complete": progress["is_recommendation_complete"],
            "is_stale": PlanningStep.RECOMMENDATION in progress["stale_steps"],
            "is_current": trip.current_step == PlanningStep.RECOMMENDATION,
            "can_open": progress["is_qna_complete"],
            "can_generate": progress["is_qna_complete"],
        },
        {
            "step": PlanningStep.ITINERARY,
            "label": PLANNING_STEP_LABELS[PlanningStep.ITINERARY],
            "is_complete": progress["is_itinerary_design_complete"],
            "is_stale": PlanningStep.ITINERARY in progress["stale_steps"],
            "is_current": trip.current_step == PlanningStep.ITINERARY,
            "can_open": progress["is_recommendation_complete"],
            "can_generate": progress["is_recommendation_complete"],
        },
        {
            "step": PlanningStep.PREPARATION,
            "label": PLANNING_STEP_LABELS[PlanningStep.PREPARATION],
            "is_complete": progress["is_trip_preparation_complete"],
            "is_stale": PlanningStep.PREPARATION in progress["stale_steps"],
            "is_current": trip.current_step == PlanningStep.PREPARATION,
            "can_open": progress["is_itinerary_design_complete"],
            "can_generate": progress["is_itinerary_design_complete"],
        },
        {
            "step": PlanningStep.OVERVIEW,
            "label": PLANNING_STEP_LABELS[PlanningStep.OVERVIEW],
            "is_complete": (
                progress["is_itinerary_design_complete"]
                and progress["is_trip_preparation_complete"]
            ),
            "is_stale": bool(progress["stale_steps"]),
            "is_current": trip.current_step == PlanningStep.OVERVIEW,
            "can_open": True,
            "can_generate": False,
        },
    ]


def get_step_blocking_errors(trip, step):
    progress = get_trip_planning_progress(trip)
    blocking_errors = []

    if step == PlanningStep.RECOMMENDATION:
        if progress["is_recommendation_complete"]:
            return []
        if not progress["is_qna_complete"]:
            blocking_errors.append("Complete preference Q&A before requesting recommendations.")
        if not _trip_has_destinations(trip):
            blocking_errors.append("Add at least one destination before requesting recommendations.")
    elif step == PlanningStep.ITINERARY:
        if progress["is_itinerary_design_complete"]:
            return []
        if not progress["is_recommendation_complete"]:
            blocking_errors.append("Generate recommendations before requesting an itinerary.")
    elif step == PlanningStep.PREPARATION:
        if progress["is_trip_preparation_complete"]:
            return []
        if not progress["is_itinerary_design_complete"]:
            blocking_errors.append("Generate the itinerary before requesting trip preparation.")

    return blocking_errors


def get_activation_blocking_errors(trip, progress=None):
    progress = progress or get_trip_planning_progress(trip)
    blocking_errors = []

    if trip.status not in {TripStatus.DRAFT, TripStatus.PLANNING}:
        blocking_errors.append("Trip status must be draft or planning.")
    if not progress["is_itinerary_design_complete"]:
        blocking_errors.append("Generate the trip itinerary.")
    if not progress["is_trip_preparation_complete"]:
        blocking_errors.append("Generate the trip preparation checklist.")

    return blocking_errors


def build_planning_response_meta(trip):
    progress = get_trip_planning_progress(trip)
    activation_blocking_errors = get_activation_blocking_errors(trip, progress=progress)
    planning_session = _get_related_object(trip, "planning_session")
    return {
        "planning_session_id": str(planning_session.id) if planning_session else None,
        "progress": progress,
        "flow": get_trip_planning_flow(trip, progress=progress),
        "activation": {
            "can_activate": not activation_blocking_errors,
            "blocking_steps": activation_blocking_errors,
        },
    }


def build_trip_snapshot(trip, *, purpose="discovery"):
    destinations = []
    trip_destinations = getattr(trip, "prefetched_trip_destinations", None)
    if trip_destinations is None:
        trip_destinations = trip.trip_destinations.select_related("destination").order_by("sort_order")

    for trip_destination in trip_destinations:
        destination = trip_destination.destination
        destination_data = {
            "id": str(destination.id),
            "name": destination.name,
            "description": _compact_text(destination.description),
            "country": destination.country,
            "country_code": destination.country_code,
            "region": destination.region,
            "type": destination.destination_type,
            "budget_tier": destination.budget_tier,
            "currency_code": destination.currency_code,
            "min_stay_days": destination.min_stay_days,
            "max_stay_days": destination.max_stay_days,
            "best_travel_months": destination.best_travel_months,
            "is_primary": trip_destination.is_primary,
            "arrival_date": (
                trip_destination.arrival_date.isoformat()
                if trip_destination.arrival_date
                else None
            ),
            "departure_date": (
                trip_destination.departure_date.isoformat()
                if trip_destination.departure_date
                else None
            ),
        }
        if purpose in {"itinerary", "preparation"}:
            destination_data["getting_around"] = _compact_text(destination.getting_around)
        if purpose == "preparation":
            destination_data["visa_notes"] = _compact_text(destination.visa_notes)
            destination_data["notes"] = _compact_list(destination.notes)
        destinations.append(destination_data)

    return {
        "trip_id": str(trip.id),
        "start_date": trip.start_date.isoformat() if trip.start_date else None,
        "end_date": trip.end_date.isoformat() if trip.end_date else None,
        "duration_days": trip.duration_days,
        "travelers_count": trip.travelers_count,
        "traveler_type": trip.traveler_type,
        "origin_city": trip.origin_city,
        "origin_country": trip.origin_country,
        "budget_tier": trip.budget_tier,
        "total_budget": (
            str(trip.total_budget) if trip.total_budget is not None else None
        ),
        "budget_currency": trip.budget_currency,
        "destinations": destinations,
    }


def _has_related_object(instance, relation_name):
    try:
        return getattr(instance, relation_name) is not None
    except ObjectDoesNotExist:
        return False


def _trip_has_destinations(trip):
    prefetched = getattr(trip, "prefetched_trip_destinations", None)
    if prefetched is not None:
        return bool(prefetched)
    return trip.trip_destinations.exists()


def run_plan_agent_for_session(
    session,
    user_query,
    preferences=None,
    trip_snapshot=None,
    destination_id=None,
    trip_context=None,
):
    from trips.agents.planning_agent import PlanAgentClient

    if isinstance(destination_id, (list, tuple)):
        scoped_destination_ids = [str(item) for item in destination_id]
    else:
        scoped_destination_ids = str(destination_id) if destination_id else None

    client = PlanAgentClient(
        session.trip,
        planning_step=session.step,
        destination_id=scoped_destination_ids,
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


def build_trip_guide_context(trip):
    """Build the authoritative saved-plan context used by post-planning chat."""
    context = build_itinerary_planning_context(trip)

    itinerary = _get_related_object(trip, "trip_itinerary")
    if itinerary:
        # The relational itinerary reflects any edits made after AI planning.
        days = []
        for day in itinerary.itinerary_days.prefetch_related("day_items").all():
            days.append(
                {
                    "day": day.day,
                    "date": day.date.isoformat() if day.date else None,
                    "title": day.title,
                    "summary": day.summary,
                    "items": [
                        {
                            "time": item.time.isoformat() if item.time else None,
                            "title": item.title,
                            "description": item.description,
                            "notes": item.notes,
                            "item_type": item.item_type,
                            "estimated_cost": item.estimated_cost,
                        }
                        for item in day.day_items.all()
                    ],
                }
            )

        routes = [
            {
                "date": route.date.isoformat() if route.date else None,
                "start_time": route.start_time.isoformat() if route.start_time else None,
                "from": route.from_point,
                "to": route.to_point,
                "transport_mode": route.transport_mode,
                "estimated_duration": route.estimated_duration,
                "estimated_cost": route.estimated_cost,
                "notes": route.notes,
            }
            for route in itinerary.route_plan_items.all()
        ]
        budget = getattr(itinerary, "rough_budget", None)
        context["itinerary"] = {
            "title": itinerary.title,
            "summary": itinerary.summary,
            "message": itinerary.message,
            "days": days,
            "routes": routes,
            "budget": {
                "currency": trip.budget_currency,
                "accommodation": budget.accommodation,
                "transport": budget.transport,
                "food": budget.food,
                "activities": budget.activities,
                "tickets_or_entry": budget.tickets_or_entry,
                "miscellaneous": budget.miscellaneous,
                "total": budget.total_estimated_budget,
                "note": budget.budget_note,
            }
            if budget
            else None,
        }

    preparation = _get_related_object(trip, "structured_preparation")
    if preparation:
        context["preparation"] = {
            "title": preparation.title,
            "summary": preparation.summary,
            "message": preparation.message,
            "packing_items": [
                {
                    "item": item.item,
                    "quantity": item.quantity,
                    "category": item.category,
                    "priority": item.priority,
                    "is_packed": item.is_packed,
                    "notes": item.additional_notes,
                }
                for item in preparation.packing_items.all()
            ],
            "required_documents": [
                {
                    "name": document.document_name,
                    "required_level": document.required_level,
                    "is_packed": document.is_packed,
                    "notes": document.additional_note,
                }
                for document in preparation.required_documents.all()
            ],
            "heads_up": [
                {
                    "title": item.title,
                    "category": item.category,
                    "severity": item.severity,
                    "notes": item.additional_note,
                }
                for item in preparation.heads_up.all()
            ],
        }

    return context


def run_guide_agent_for_session(session, user_query):
    """Compatibility wrapper for the dedicated trip-chat service."""
    from trips.services.trip_chat import run_guide_agent_for_session as run_agent

    return run_agent(session, user_query)


def build_initial_agent_query(preferences, trip_snapshot):
    return (
        "PREFERENCE_INTAKE_PHASE: ASK_ONE_QUESTION\n"
        "The traveler just submitted their trip preferences. Ask exactly one concise, "
        "destination-aware question that fills the most useful remaining gap for choosing "
        "attractions, activities, and cuisines. Do not complete Q&A in this response."
    )


def build_final_preference_agent_query(answer, preferences, trip_snapshot):
    return (
        "PREFERENCE_INTAKE_PHASE: FINALIZE_AFTER_ANSWER\n"
        "This is the traveler's answer to the one and only follow-up question. "
        "Do not ask another question. Set is_qna_complete to true and return a concise, "
        "practical context that combines this answer with the existing preferences and "
        "destination details for attraction, activity, and cuisine recommendations.\n"
        f"Traveler answer: {answer}"
    )


def normalize_initial_preference_response(agent_response, preferences, trip_snapshot):
    """Guarantee that preference initialization yields one question, never completion."""
    if not isinstance(agent_response, dict):
        agent_response = {}
    response = agent_response.get("response")
    if not isinstance(response, dict):
        response = {}
    question = str(response.get("question") or "").strip()
    generic_fallbacks = {
        "Could you tell me what kind of trip experience you prefer?",
        "Could you share your travel preferences?",
    }
    if (
        not question
        or question in generic_fallbacks
        or question.count("?") != 1
    ):
        question = _fallback_preference_question(preferences, trip_snapshot)

    agent_response["response"] = {
        "question": question,
        "is_qna_complete": False,
        "context": None,
    }
    return agent_response


def finalize_preference_response(agent_response, answer, preferences, trip_snapshot):
    """Guarantee that the first traveler answer closes preference Q&A."""
    if not isinstance(agent_response, dict):
        agent_response = {}
    response = agent_response.get("response")
    if not isinstance(response, dict):
        response = {}
    context = str(response.get("context") or "").strip()
    if not context:
        context = _fallback_preference_context(answer, preferences, trip_snapshot)

    agent_response["response"] = {
        "question": None,
        "is_qna_complete": True,
        "context": context,
    }
    return agent_response


def _fallback_preference_question(preferences, trip_snapshot):
    destinations = [
        str(item.get("name")).strip()
        for item in (trip_snapshot or {}).get("destinations", [])
        if isinstance(item, dict) and item.get("name")
    ]
    destination = ", ".join(destinations) or "your destination"
    interests = [
        str(item).strip()
        for item in (preferences or {}).get("interest_tags", [])
        if item
    ]
    question_start = (
        f"Keeping your interest in {' and '.join(interests[:2])} in mind, what"
        if interests
        else "What"
    )
    return (
        f"{question_start} would your ideal day in {destination} include—"
        "places you want to see, activities you enjoy, and foods you want to try or avoid?"
    )


def _fallback_preference_context(answer, preferences, trip_snapshot):
    preferences = preferences or {}
    parts = [f'Traveler answer: "{str(answer).strip()}".']
    preference_labels = (
        ("Travel pace", "travel_pace"),
        ("Interests", "interest_tags"),
        ("Dietary needs", "dietary_needs"),
        ("Mobility constraints", "mobility_constraints"),
        ("Accommodation preference", "accommodation_preference"),
    )
    for label, key in preference_labels:
        value = preferences.get(key)
        if isinstance(value, list):
            value = ", ".join(str(item).strip() for item in value if item)
        if value:
            parts.append(f"{label}: {value}.")

    destinations = [
        str(item.get("name")).strip()
        for item in (trip_snapshot or {}).get("destinations", [])
        if isinstance(item, dict) and item.get("name")
    ]
    if destinations:
        parts.append(f"Destinations: {', '.join(destinations)}.")
    return " ".join(parts)


def build_recommendations_agent_query(preferences, trip_snapshot, destination_id):
    return (
        "Generate step 3 trip recommendations for the selected destination. "
        "Use the destination item tool, the trip snapshot, and the saved preference context. "
        "Return only the structured recommendation JSON. "
        f"The destination-scoped tool is bound to destination ID {destination_id}."
    )


def build_itinerary_agent_query(trip_context):
    return (
        "Generate step 4 itinerary design from this compact trip planning context. "
        "Use the provided trip data directly as the source of truth. "
        "Return only the structured itinerary JSON."
    )


def build_preparation_agent_query(trip_context):
    return (
        "Generate step 5 trip preparation from this compact trip planning context. "
        "Use the provided trip data directly as the source of truth. "
        "Return only the structured preparation JSON."
    )


def build_itinerary_planning_context(trip):
    agent_context = trip.metadata or {}
    trip_snapshot = build_trip_snapshot(trip, purpose="itinerary")
    recommendation_ids, recommendation_messages = _selected_recommendation_state(
        trip,
        agent_context,
    )

    return {
        **trip_snapshot,
        "title": trip.title,
        "nights": trip.nights,
        "start_location": {
            "address": trip.start_location_address,
            "latitude": trip.start_location_latitude,
            "longitude": trip.start_location_longitude,
        },
        "preferences": trip.preferences or {},
        "preference_context": (agent_context.get("preference_qna") or {}).get("context"),
        "selected_recommendations": {
            "attractions": _serialize_selected_attractions(recommendation_ids["attraction_ids"]),
            "activities": _serialize_selected_activities(recommendation_ids["activity_ids"]),
            "cuisines": _serialize_selected_cuisines(recommendation_ids["cuisine_ids"]),
        },
        "recommendation_messages": recommendation_messages,
    }


def build_preparation_planning_context(trip):
    """Build a preparation-specific context without resending recommendation descriptions."""
    agent_context = trip.metadata or {}
    itinerary = (
        TripItinerary.objects.filter(trip=trip)
        .prefetch_related("itinerary_days__day_items", "route_plan_items")
        .first()
    )
    return {
        **build_trip_snapshot(trip, purpose="preparation"),
        "title": trip.title,
        "nights": trip.nights,
        "start_location": {
            "address": trip.start_location_address,
            "latitude": trip.start_location_latitude,
            "longitude": trip.start_location_longitude,
        },
        "preferences": trip.preferences or {},
        "preference_context": (agent_context.get("preference_qna") or {}).get("context"),
        "itinerary": _serialize_itinerary_for_agent(itinerary) if itinerary else {},
    }


def _selected_recommendation_state(trip, agent_context):
    saved = _get_related_object(trip, "trip_recommendations")
    if saved:
        recommendation_ids = {
            "attraction_ids": [
                str(item.attraction_id)
                for item in saved.attraction_items.all()
                if item.attraction_id
            ],
            "activity_ids": [str(item.activity_id) for item in saved.activity_items.all()],
            "cuisine_ids": [str(item.cuisine_id) for item in saved.cuisine_items.all()],
        }
        messages = {
            "attractions": saved.attraction_recommendation_message,
            "activities": saved.activity_recommendation_message,
            "cuisines": saved.cusine_recommendation_message,
        }
        return recommendation_ids, messages

    recommendations = agent_context.get("recommendations") or {}
    return (
        {
            "attraction_ids": _recommendation_ids(recommendations, "attraction"),
            "activity_ids": _recommendation_ids(recommendations, "activity"),
            "cuisine_ids": _recommendation_ids(recommendations, "cuisine"),
        },
        recommendations.get("messages", {}),
    )


def _recommendation_ids(recommendations, item_type):
    if item_type == "attraction":
        ids = recommendations.get("attraction_ids") or recommendations.get("tour_spot_ids") or []
        return _valid_uuid_strings(ids)
    if item_type == "cuisine":
        ids = recommendations.get("cuisine_ids") or recommendations.get("food_item_ids") or []
        return _valid_uuid_strings(ids)
    return _valid_uuid_strings(recommendations.get(f"{item_type}_ids") or [])


def _valid_uuid_strings(values):
    valid_ids = []
    seen = set()
    for value in values or []:
        try:
            parsed = str(UUID(str(value)))
        except (TypeError, ValueError, AttributeError):
            continue
        if parsed not in seen:
            valid_ids.append(parsed)
            seen.add(parsed)
    return valid_ids


def _serialize_selected_attractions(selected_ids):
    items = Attraction.objects.filter(id__in=selected_ids).prefetch_related("tags")
    item_map = {str(item.id): item for item in items}
    return [
        {
            "id": str(item.id),
            "name": item.name,
            "type": item.attraction_type,
            "description": _compact_text(item.description),
            "how_to_reach": _compact_text(item.how_to_reach),
            "address": item.address,
            "latitude": item.latitude,
            "longitude": item.longitude,
            "budget_tier": item.budget_tier,
            "avg_duration_hours": item.avg_duration_hours,
            "best_time_of_day": item.best_time_of_day,
            "picking_reasons": _compact_list(item.picking_reasons),
            "notes": _compact_list(item.notes),
            "tags": [tag.name for tag in item.tags.all()],
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
            "description": _compact_text(item.description),
            "difficulty_level": item.difficulty_level,
            "budget_tier": item.budget_tier,
            "approx_cost": str(item.approx_cost) if item.approx_cost is not None else None,
            "duration_hours": item.duration_hours,
            "best_months": item.best_months,
            "picking_reasons": _compact_list(item.picking_reasons),
            "notes": _compact_list(item.notes),
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
            "description": _compact_text(item.description),
            "spice_level": item.spice_level,
            "meal_type": item.meal_type,
            "is_vegetarian_friendly": item.is_vegetarian_friendly,
            "is_featured": item.is_featured,
            "approx_cost": item.approx_cost,
            "picking_reasons": _compact_list(item.picking_reasons),
            "notes": _compact_list(item.notes),
        }
        for item_id in selected_ids
        if (item := item_map.get(str(item_id)))
    ]


def _serialize_itinerary_for_agent(itinerary):
    days = []
    for day in itinerary.itinerary_days.all():
        days.append(
            {
                "day": day.day,
                "date": day.date.isoformat() if day.date else None,
                "title": day.title,
                "items": [
                    {
                        "time": item.time.isoformat() if item.time else None,
                        "title": item.title,
                        "item_type": item.item_type,
                        "description": _compact_text(item.description, limit=300),
                        "notes": _compact_text(item.notes, limit=240),
                    }
                    for item in day.day_items.all()
                ],
            }
        )

    routes = [
        {
            "date": route.date.isoformat() if route.date else None,
            "from": route.from_point,
            "to": route.to_point,
            "transport_mode": route.transport_mode,
            "estimated_duration": str(route.estimated_duration) if route.estimated_duration else None,
        }
        for route in itinerary.route_plan_items.all()
    ]
    return {
        "title": itinerary.title,
        "summary": _compact_text(itinerary.summary),
        "days": days,
        "routes": routes,
    }


def _get_related_object(instance, relation_name):
    try:
        return getattr(instance, relation_name)
    except ObjectDoesNotExist:
        return None


def _compact_text(value, *, limit=600):
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1].rstrip()}…"


def _compact_list(value, *, limit=5):
    if not isinstance(value, list):
        return []
    return [_compact_text(item, limit=240) for item in value[:limit] if item]


def update_trip_agent_context_from_qna(trip, agent_response, session, user):
    qna_response = agent_response.get("response") or {}
    context = qna_response.get("context", None)
    is_qna_complete = qna_response.get("is_qna_complete", False)
    
    if not is_qna_complete or not context:
        return False

    agent_context = trip.metadata or {}
    agent_context["preference_qna"] = {
        "context": str(context).strip(),
        "session_id": str(session.id),
        "external_session_id": session.external_session_id,
    }

    trip.metadata = agent_context
    trip.current_step = PlanningStep.RECOMMENDATION
    trip.updated_by = user
    trip.is_qna_complete = is_qna_complete
    trip.save(update_fields=["metadata", "current_step", "is_qna_complete", "updated_by", "updated_at"])

    session.is_active = False
    session.updated_by = user
    session.save(update_fields=["is_active", "updated_by", "updated_at"])
    return True


def update_trip_agent_context_from_recommendations(trip, agent_response, session, user):
    recommendations = agent_response.get("response") or {}
    messages = recommendations.get("messages") if isinstance(recommendations.get("messages"), dict) else {}
    destination_ids = _trip_destination_ids(trip)
    max_items_per_type = max(len(destination_ids), 1) * 5
    normalized_recommendations = {
        "is_discovery_complete": recommendations.get("is_discovery_complete", False),
        "attraction_ids": _valid_uuid_strings(
            recommendations.get("attraction_ids") or recommendations.get("tour_spot_ids", [])
        )[:max_items_per_type],
        "activity_ids": _valid_uuid_strings(
            recommendations.get("activity_ids", [])
        )[:max_items_per_type],
        "cuisine_ids": _valid_uuid_strings(
            recommendations.get("cuisine_ids") or recommendations.get("food_item_ids", [])
        )[:max_items_per_type],
        "messages": {
            "attractions": _compact_text(
                messages.get("attractions") or messages.get("tour_spots") or "",
                limit=300,
            ),
            "activities": _compact_text(messages.get("activities") or "", limit=300),
            "cuisines": _compact_text(
                messages.get("cuisines") or messages.get("foods") or "",
                limit=300,
            ),
        },
        "session_id": str(session.id),
        "external_session_id": session.external_session_id,
    }

    if not recommendations.get("is_discovery_complete"):
        normalized_recommendations["validation_errors"] = [
            "The agent did not mark destination discovery complete."
        ]
        trip.updated_by = user
        trip.save(update_fields=["updated_by", "updated_at"])
        return normalized_recommendations

    attraction_ids = {
        str(item_id)
        for item_id in Attraction.objects.filter(
            id__in=normalized_recommendations["attraction_ids"],
            destination_id__in=destination_ids,
        ).values_list("id", flat=True)
    }
    activity_ids = {
        str(item_id)
        for item_id in Activity.objects.filter(
            id__in=normalized_recommendations["activity_ids"],
            destination_id__in=destination_ids,
        ).values_list("id", flat=True)
    }
    cuisine_ids = {
        str(item_id)
        for item_id in Cuisine.objects.filter(
            id__in=normalized_recommendations["cuisine_ids"],
            destination_id__in=destination_ids,
        ).values_list("id", flat=True)
    }
    normalized_recommendations["attraction_ids"] = [
        item_id
        for item_id in normalized_recommendations["attraction_ids"]
        if item_id in attraction_ids
    ]
    normalized_recommendations["activity_ids"] = [
        item_id
        for item_id in normalized_recommendations["activity_ids"]
        if item_id in activity_ids
    ]
    normalized_recommendations["cuisine_ids"] = [
        item_id
        for item_id in normalized_recommendations["cuisine_ids"]
        if item_id in cuisine_ids
    ]

    if not any(
        normalized_recommendations[key]
        for key in ("attraction_ids", "activity_ids", "cuisine_ids")
    ):
        normalized_recommendations["is_discovery_complete"] = False
        normalized_recommendations["validation_errors"] = [
            "The agent did not return any valid catalog item IDs for this trip's destinations."
        ]
        return normalized_recommendations

    agent_context = trip.metadata or {}
    agent_context["recommendations"] = normalized_recommendations
    _clear_step_invalidation(agent_context, PlanningStep.RECOMMENDATION)

    with transaction.atomic():
        trip_recommendations, _ = TripRecommendations.objects.update_or_create(
            trip=trip,
            defaults={
                "attraction_recommendation_message": normalized_recommendations["messages"]["attractions"],
                "cusine_recommendation_message": normalized_recommendations["messages"]["cuisines"],
                "activity_recommendation_message": normalized_recommendations["messages"]["activities"],
                "external_session_id": session.external_session_id,
                "metadata": {
                    "session_id": str(session.id),
                },
            },
        )
        TripAttractionRecommendationItem.objects.filter(recommendation=trip_recommendations).delete()
        TripActivityRecommendationItem.objects.filter(recommendation=trip_recommendations).delete()
        TripCuisineRecommendationItem.objects.filter(recommendation=trip_recommendations).delete()

        TripAttractionRecommendationItem.objects.bulk_create(
            [
                TripAttractionRecommendationItem(recommendation=trip_recommendations, attraction_id=item_id)
                for item_id in normalized_recommendations["attraction_ids"]
                if str(item_id) in attraction_ids
            ]
        )
        TripActivityRecommendationItem.objects.bulk_create(
            [
                TripActivityRecommendationItem(recommendation=trip_recommendations, activity_id=item_id)
                for item_id in normalized_recommendations["activity_ids"]
                if str(item_id) in activity_ids
            ]
        )
        TripCuisineRecommendationItem.objects.bulk_create(
            [
                TripCuisineRecommendationItem(recommendation=trip_recommendations, cuisine_id=item_id)
                for item_id in normalized_recommendations["cuisine_ids"]
                if str(item_id) in cuisine_ids
            ]
        )

        trip.metadata = agent_context
        trip.current_step = PlanningStep.ITINERARY
        trip.is_recommendation_complete = True
        trip.updated_by = user
        trip.save(
            update_fields=[
                "metadata",
                "current_step",
                "is_recommendation_complete",
                "updated_by",
                "updated_at",
            ]
        )

    session.is_active = False
    session.updated_by = user
    session.save(update_fields=["is_active", "updated_by", "updated_at"])
    return agent_context["recommendations"]


def _trip_destination_ids(trip):
    prefetched = getattr(trip, "prefetched_trip_destinations", None)
    if prefetched is not None:
        return [item.destination_id for item in prefetched]
    return list(trip.trip_destinations.values_list("destination_id", flat=True))


def update_trip_agent_context_from_itinerary(trip, agent_response, session, user):
    itinerary = agent_response.get("response") or {}
    day_wise_plan = _normalize_itinerary_days(
        trip,
        itinerary.get("day_wise_plan"),
    )
    route_plan = _normalize_route_plan(trip, itinerary.get("route_plan"))
    rough_budget = _normalize_rough_budget(trip, itinerary.get("rough_budget"))
    title = _compact_text(itinerary.get("title", ""), limit=180)
    normalized_itinerary = {
        "is_itinerary_complete": bool(
            itinerary.get("is_itinerary_complete", False)
            and title
            and _itinerary_covers_trip_duration(trip, day_wise_plan)
            and rough_budget.get("total_estimated_budget") is not None
        ),
        "title": title,
        "summary": _compact_text(itinerary.get("summary", ""), limit=1200),
        "day_wise_plan": day_wise_plan,
        "route_plan": route_plan,
        "rough_budget": rough_budget,
        "message": _compact_text(itinerary.get("message", ""), limit=500),
        "session_id": str(session.id),
        "external_session_id": session.external_session_id,
    }

    if not normalized_itinerary["is_itinerary_complete"]:
        validation_errors = []
        if not title:
            validation_errors.append("The itinerary title is missing.")
        if not _itinerary_covers_trip_duration(trip, day_wise_plan):
            validation_errors.append("The itinerary does not contain every trip day in order.")
        if rough_budget.get("total_estimated_budget") is None:
            validation_errors.append("The itinerary budget total is missing or invalid.")
        normalized_itinerary["validation_errors"] = validation_errors or [
            "The agent did not mark the itinerary complete."
        ]

    if not normalized_itinerary["is_itinerary_complete"]:
        trip.updated_by = user
        trip.save(update_fields=["updated_by", "updated_at"])
        return normalized_itinerary

    with transaction.atomic():
        structured_itinerary, _ = TripItinerary.objects.update_or_create(
            trip=trip,
            defaults={
                "title": normalized_itinerary["title"],
                "summary": normalized_itinerary["summary"],
                "message": normalized_itinerary["message"],
                "external_session_id": session.external_session_id,
                "metadata": {
                    "session_id": str(session.id),
                },
            },
        )

        structured_itinerary.route_plan_items.all().delete()
        structured_itinerary.itinerary_days.all().delete()

        TripRoutePlanItem.objects.bulk_create(
            [
                TripRoutePlanItem(
                    itinerary=structured_itinerary,
                    date=_parse_date_value(item.get("date")),
                    start_time=_parse_time_value(item.get("start_time")),
                    from_point=item.get("from_point") or "",
                    to_point=item.get("to_point") or "",
                    transport_mode=item.get("transport_mode") or "",
                    estimated_duration=_parse_duration_value(item.get("estimated_duration")),
                    estimated_cost=_parse_decimal_value(item.get("estimated_cost")),
                    notes=item.get("notes") or "",
                )
                for item in normalized_itinerary["route_plan"]
                if item.get("from_point") and item.get("to_point")
            ]
        )

        created_days = set()
        for day_data in normalized_itinerary["day_wise_plan"]:
            day_number = _parse_positive_int(day_data.get("day"))
            if not day_number or day_number in created_days or not day_data.get("title"):
                continue
            created_days.add(day_number)

            itinerary_day = TripItineraryDay.objects.create(
                itinerary=structured_itinerary,
                day=day_number,
                date=_parse_date_value(day_data.get("date")),
                title=day_data.get("title") or "",
                summary=day_data.get("summary") or "",
            )
            day_items = day_data.get("items") if isinstance(day_data.get("items"), list) else []
            TripItineraryDayItem.objects.bulk_create(
                [
                    TripItineraryDayItem(
                        trip_itinerary_day=itinerary_day,
                        time=_parse_time_value(item.get("time")),
                        title=item.get("title") or "",
                        item_type=item.get("item_type") or "",
                        item_id=_parse_uuid_value(item.get("item_id")),
                        description=item.get("description") or "",
                        estimated_cost=_parse_decimal_value(item.get("estimated_cost")),
                        notes=item.get("notes") or "",
                    )
                    for item in day_items
                    if item.get("title")
                ]
            )

        rough_budget = normalized_itinerary["rough_budget"]
        TripItineraryBudget.objects.update_or_create(
            itinerary=structured_itinerary,
            defaults={
                "accommodation": _parse_decimal_value(rough_budget.get("accommodation")),
                "transport": _parse_decimal_value(rough_budget.get("transport")),
                "food": _parse_decimal_value(rough_budget.get("food")),
                "activities": _parse_decimal_value(rough_budget.get("activities")),
                "tickets_or_entry": _parse_decimal_value(rough_budget.get("tickets_or_entry")),
                "miscellaneous": _parse_decimal_value(rough_budget.get("miscellaneous")),
                "total_estimated_budget": _parse_decimal_value(rough_budget.get("total_estimated_budget")),
                "budget_note": rough_budget.get("budget_note") or "",
                "metadata": {
                    "raw_budget": rough_budget,
                },
                "created_by": user,
                "updated_by": user,
            },
        )

        agent_context = trip.metadata or {}
        agent_context["itinerary_design"] = {
            "is_itinerary_complete": True,
            "title": normalized_itinerary["title"],
            "summary": normalized_itinerary["summary"],
            "message": normalized_itinerary["message"],
            "session_id": str(session.id),
            "external_session_id": session.external_session_id,
        }
        _clear_step_invalidation(agent_context, PlanningStep.ITINERARY)
        trip.metadata = agent_context
        trip.current_step = PlanningStep.PREPARATION
        trip.is_itinerary_design_complete = True
        trip.updated_by = user
        trip.save(
            update_fields=[
                "metadata",
                "current_step",
                "is_itinerary_design_complete",
                "updated_by",
                "updated_at",
            ]
        )

        session.is_active = False
        session.updated_by = user
        session.save(update_fields=["is_active", "updated_by", "updated_at"])

    return normalized_itinerary


def _itinerary_covers_trip_duration(trip, day_wise_plan):
    if not day_wise_plan:
        return False
    expected_days = trip.duration_days or len(day_wise_plan)
    return [item["day"] for item in day_wise_plan] == list(range(1, expected_days + 1))


def _normalize_rough_budget(trip, value):
    value = value if isinstance(value, dict) else {}
    component_names = (
        "accommodation",
        "transport",
        "food",
        "activities",
        "tickets_or_entry",
        "miscellaneous",
    )
    components = {
        name: _parse_decimal_value(value.get(name))
        for name in component_names
    }
    supplied_total = _parse_decimal_value(value.get("total_estimated_budget"))
    component_values = [amount for amount in components.values() if amount is not None]
    component_total = sum(component_values, Decimal("0")) if component_values else None
    calculated_total = (
        component_total
        if len(component_values) == len(component_names)
        else supplied_total if supplied_total is not None else component_total
    )

    budget_note = _compact_text(value.get("budget_note"), limit=1000)
    if trip.total_budget is not None and calculated_total is not None:
        difference = calculated_total - trip.total_budget
        if difference > 0:
            overage_note = (
                f"Estimated total is {difference:.2f} {trip.budget_currency} above the "
                f"{trip.total_budget:.2f} {trip.budget_currency} target."
            )
            budget_note = f"{budget_note} {overage_note}".strip()

    return {
        **{
            name: str(amount) if amount is not None else None
            for name, amount in components.items()
        },
        "total_estimated_budget": (
            str(calculated_total) if calculated_total is not None else None
        ),
        "budget_note": budget_note,
    }


def get_itinerary_budget_status(trip, budget):
    target = trip.total_budget
    estimated = budget.total_estimated_budget if budget else None
    if target is None or estimated is None:
        return {
            "target_total": str(target) if target is not None else None,
            "estimated_total": str(estimated) if estimated is not None else None,
            "currency": trip.budget_currency,
            "is_within_budget": None,
            "difference": None,
        }

    difference = target - estimated
    return {
        "target_total": str(target),
        "estimated_total": str(estimated),
        "currency": trip.budget_currency,
        "is_within_budget": difference >= 0,
        "difference": str(abs(difference)),
    }


def _normalize_itinerary_days(trip, values):
    if not isinstance(values, list):
        return []

    recommendation_ids, _ = _selected_recommendation_state(trip, trip.metadata or {})
    allowed_item_ids = {
        "attraction": set(recommendation_ids["attraction_ids"]),
        "activity": set(recommendation_ids["activity_ids"]),
        "cuisine": set(recommendation_ids["cuisine_ids"]),
    }
    max_day = trip.duration_days or 365
    normalized_days = []
    seen_days = set()

    for day_data in values[:max_day]:
        if not isinstance(day_data, dict):
            continue
        day_number = _parse_positive_int(day_data.get("day"))
        title = _compact_text(day_data.get("title"), limit=180)
        if not day_number or day_number > max_day or day_number in seen_days or not title:
            continue

        expected_date = trip.start_date + timedelta(days=day_number - 1) if trip.start_date else None
        parsed_date = _parse_date_value(day_data.get("date"))
        if expected_date and (not parsed_date or parsed_date != expected_date):
            parsed_date = expected_date

        items = []
        raw_items = day_data.get("items") if isinstance(day_data.get("items"), list) else []
        for item in raw_items[:12]:
            if not isinstance(item, dict):
                continue
            item_title = _compact_text(item.get("title"), limit=180)
            if not item_title:
                continue
            item_type = str(item.get("item_type") or "free_time").strip().lower()
            if item_type not in {
                "attraction",
                "activity",
                "cuisine",
                "transfer",
                "rest",
                "free_time",
            }:
                item_type = "free_time"
            item_id = str(_parse_uuid_value(item.get("item_id")) or "") or None
            if item_type not in allowed_item_ids or item_id not in allowed_item_ids[item_type]:
                item_id = None
            items.append(
                {
                    "time": item.get("time"),
                    "title": item_title,
                    "item_type": item_type,
                    "item_id": item_id,
                    "description": _compact_text(item.get("description"), limit=600),
                    "estimated_cost": item.get("estimated_cost"),
                    "notes": _compact_text(item.get("notes"), limit=400),
                }
            )

        normalized_days.append(
            {
                "day": day_number,
                "date": parsed_date.isoformat() if parsed_date else None,
                "title": title,
                "summary": _compact_text(day_data.get("summary"), limit=600),
                "items": items,
            }
        )
        seen_days.add(day_number)

    return sorted(normalized_days, key=lambda item: item["day"])


def _normalize_route_plan(trip, values):
    if not isinstance(values, list):
        return []

    max_routes = min(max((trip.duration_days or 1) * 8, 8), 120)
    normalized_routes = []
    for item in values[:max_routes]:
        if not isinstance(item, dict):
            continue
        from_point = _compact_text(item.get("from_point"), limit=255)
        to_point = _compact_text(item.get("to_point"), limit=255)
        if not from_point or not to_point:
            continue
        route_date = _parse_date_value(item.get("date"))
        if (
            route_date
            and trip.start_date
            and trip.end_date
            and not trip.start_date <= route_date <= trip.end_date
        ):
            route_date = None
        normalized_routes.append(
            {
                "date": route_date.isoformat() if route_date else None,
                "start_time": item.get("start_time"),
                "from_point": from_point,
                "to_point": to_point,
                "transport_mode": _compact_text(item.get("transport_mode"), limit=50),
                "estimated_duration": item.get("estimated_duration"),
                "estimated_cost": item.get("estimated_cost"),
                "notes": _compact_text(item.get("notes"), limit=500),
            }
        )
    return normalized_routes


def _parse_date_value(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.date()
    if hasattr(value, "isoformat") and not isinstance(value, str):
        return value
    try:
        return datetime.strptime(str(value).strip()[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def _parse_time_value(value):
    if not value:
        return None
    if isinstance(value, datetime):
        return value.time()
    if hasattr(value, "hour") and hasattr(value, "minute") and not isinstance(value, str):
        return value

    value = str(value).strip()
    for time_format in ("%I:%M %p", "%I %p", "%H:%M:%S", "%H:%M"):
        try:
            return datetime.strptime(value.upper(), time_format).time()
        except ValueError:
            continue
    return None


def _parse_decimal_value(value):
    if value in (None, ""):
        return None
    if isinstance(value, Decimal):
        return value
    number_match = re.search(r"-?\d+(?:,\d{3})*(?:\.\d+)?|-?\d+(?:\.\d+)?", str(value))
    if not number_match:
        return None
    try:
        parsed = Decimal(number_match.group(0).replace(",", ""))
    except InvalidOperation:
        return None
    return parsed if parsed >= 0 else None


def _parse_duration_value(value):
    if not value:
        return None
    if isinstance(value, timedelta):
        return value

    text = str(value).strip().lower()
    clock_match = re.match(r"^(?P<hours>\d+):(?P<minutes>\d{1,2})(?::(?P<seconds>\d{1,2}))?$", text)
    if clock_match:
        return timedelta(
            hours=int(clock_match.group("hours")),
            minutes=int(clock_match.group("minutes")),
            seconds=int(clock_match.group("seconds") or 0),
        )

    hours = minutes = 0
    hour_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:h|hr|hrs|hour|hours)", text)
    minute_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:m|min|mins|minute|minutes)", text)
    if hour_match:
        hours = float(hour_match.group(1))
    if minute_match:
        minutes = float(minute_match.group(1))
    if hours or minutes:
        return timedelta(minutes=int(hours * 60 + minutes))

    number_match = re.search(r"\d+(?:\.\d+)?", text)
    if number_match:
        return timedelta(minutes=int(float(number_match.group(0))))
    return None


def _parse_uuid_value(value):
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError):
        return None


def _parse_positive_int(value):
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def update_trip_agent_context_from_preparation(trip, agent_response, session, user):
    preparation = agent_response.get("response") or {}
    packing_items = _deduplicate_dict_items(
        _dict_list(preparation.get("packing_items"), limit=24),
        key="item",
    )
    required_documents = _deduplicate_dict_items(
        _dict_list(preparation.get("required_documents"), limit=15),
        key="document",
    )
    heads_up = _deduplicate_dict_items(
        _dict_list(preparation.get("heads_up"), limit=20),
        key="title",
    )
    normalized_preparation = {
        "is_preparation_complete": bool(
            preparation.get("is_preparation_complete", False)
            and packing_items
            and required_documents
            and heads_up
        ),
        "title": _compact_text(preparation.get("title", ""), limit=180),
        "summary": _compact_text(preparation.get("summary", ""), limit=1200),
        "packing_items": packing_items,
        "required_documents": required_documents,
        "heads_up": heads_up,
        "message": _compact_text(preparation.get("message", ""), limit=500),
        "session_id": str(session.id),
        "external_session_id": session.external_session_id,
    }

    if not normalized_preparation["is_preparation_complete"]:
        validation_errors = []
        if not packing_items:
            validation_errors.append("The packing list is missing.")
        if not required_documents:
            validation_errors.append("The document checklist is missing.")
        if not heads_up:
            validation_errors.append("The destination heads-up list is missing.")
        normalized_preparation["validation_errors"] = validation_errors or [
            "The agent did not mark trip preparation complete."
        ]

    if not normalized_preparation["is_preparation_complete"]:
        trip.updated_by = user
        trip.save(update_fields=["updated_by", "updated_at"])
        return normalized_preparation

    with transaction.atomic():
        structured_preparation, _ = TripPreparation.objects.update_or_create(
            trip=trip,
            defaults={
                "title": normalized_preparation["title"],
                "summary": normalized_preparation["summary"],
                "message": normalized_preparation["message"],
                "external_session_id": session.external_session_id,
                "metadata": {
                    "session_id": str(session.id),
                },
            },
        )

        existing_packing = {
            _normalized_item_name(item.item): item
            for item in structured_preparation.packing_items.all()
        }
        existing_documents = {
            _normalized_item_name(item.document_name): item
            for item in structured_preparation.required_documents.all()
        }
        generated_packing_names = {
            _normalized_item_name(item.get("item"))
            for item in normalized_preparation["packing_items"]
        }
        generated_document_names = {
            _normalized_item_name(item.get("document"))
            for item in normalized_preparation["required_documents"]
        }

        # Preserve material user state if a regenerated checklist omits a completed
        # item or an uploaded document.
        for name, item in existing_packing.items():
            if name not in generated_packing_names and item.is_packed:
                normalized_preparation["packing_items"].append(
                    {
                        "item": item.item,
                        "category": item.category,
                        "priority": item.priority,
                        "reason": item.additional_notes,
                    }
                )
        for name, item in existing_documents.items():
            if name not in generated_document_names and (item.document_url or item.is_packed):
                normalized_preparation["required_documents"].append(
                    {
                        "document": item.document_name,
                        "required_level": item.required_level,
                        "reason": item.additional_note,
                    }
                )

        structured_preparation.packing_items.all().delete()
        structured_preparation.required_documents.all().delete()
        structured_preparation.heads_up.all().delete()

        TripPreparationPackingItem.objects.bulk_create(
            [
                TripPreparationPackingItem(
                    preparation=structured_preparation,
                    item=_compact_text(item.get("item", ""), limit=180),
                    quantity=(
                        existing_packing[_normalized_item_name(item.get("item"))].quantity
                        if _normalized_item_name(item.get("item")) in existing_packing
                        else 1
                    ),
                    category=_choice_or_default(
                        item.get("category"),
                        PackingItemsType.choices,
                        PackingItemsType.OTHER,
                    ),
                    priority=_choice_or_default(
                        item.get("priority"),
                        PriorityType.choices,
                        PriorityType.RECOMMENDED,
                    ),
                    additional_notes=_compact_text(item.get("reason"), limit=600),
                    is_packed=(
                        existing_packing[_normalized_item_name(item.get("item"))].is_packed
                        if _normalized_item_name(item.get("item")) in existing_packing
                        else False
                    ),
                    sort_order=index,
                )
                for index, item in enumerate(normalized_preparation["packing_items"], start=1)
                if item.get("item")
            ]
        )

        TripRequiredDocumentItem.objects.bulk_create(
            [
                TripRequiredDocumentItem(
                    preparation=structured_preparation,
                    document_name=_compact_text(item.get("document", ""), limit=180),
                    document_file_name=(
                        existing_documents[
                            _normalized_item_name(item.get("document"))
                        ].document_file_name
                        if _normalized_item_name(item.get("document")) in existing_documents
                        else ""
                    ),
                    document_url=(
                        existing_documents[
                            _normalized_item_name(item.get("document"))
                        ].document_url
                        if _normalized_item_name(item.get("document")) in existing_documents
                        else None
                    ),
                    document_url_public_id=(
                        existing_documents[
                            _normalized_item_name(item.get("document"))
                        ].document_url_public_id
                        if _normalized_item_name(item.get("document")) in existing_documents
                        else ""
                    ),
                    is_packed=(
                        existing_documents[
                            _normalized_item_name(item.get("document"))
                        ].is_packed
                        if _normalized_item_name(item.get("document")) in existing_documents
                        else False
                    ),
                    required_level=_choice_or_default(
                        item.get("required_level"),
                        RequiredType.choices,
                        RequiredType.RECOMMENDED,
                    ),
                    additional_note=_compact_text(item.get("reason"), limit=600),
                    sort_order=index,
                )
                for index, item in enumerate(normalized_preparation["required_documents"], start=1)
                if item.get("document")
            ]
        )

        TripHeadsUpInfoItem.objects.bulk_create(
            [
                TripHeadsUpInfoItem(
                    preparation=structured_preparation,
                    title=_compact_text(item.get("title", ""), limit=180),
                    category=_choice_or_default(
                        item.get("category"),
                        HeadsUpType.choices,
                        HeadsUpType.OTHER,
                    ),
                    severity=_choice_or_default(
                        item.get("severity"),
                        SeverityType.choices,
                        SeverityType.LOW,
                    ),
                    additional_note=_compact_text(item.get("details"), limit=1000),
                    sort_order=index,
                )
                for index, item in enumerate(normalized_preparation["heads_up"], start=1)
                if item.get("title")
            ]
        )

        agent_context = trip.metadata or {}
        agent_context["trip_preparation"] = {
            "is_preparation_complete": True,
            "title": normalized_preparation["title"],
            "summary": normalized_preparation["summary"],
            "message": normalized_preparation["message"],
            "session_id": str(session.id),
            "external_session_id": session.external_session_id,
        }
        _clear_step_invalidation(agent_context, PlanningStep.PREPARATION)
        trip.metadata = agent_context
        trip.current_step = PlanningStep.OVERVIEW
        trip.is_trip_preparation_complete = True
        trip.updated_by = user
        trip.save(
            update_fields=[
                "metadata",
                "current_step",
                "is_trip_preparation_complete",
                "updated_by",
                "updated_at",
            ]
        )

        session.is_active = False
        session.updated_by = user
        session.save(update_fields=["is_active", "updated_by", "updated_at"])

    return normalized_preparation


def _dict_list(value, *, limit):
    if not isinstance(value, list):
        return []
    return [item for item in value[:limit] if isinstance(item, dict)]


def _deduplicate_dict_items(items, *, key):
    deduplicated = []
    seen = set()
    for item in items:
        normalized_key = _normalized_item_name(item.get(key))
        if normalized_key and normalized_key not in seen:
            deduplicated.append(item)
            seen.add(normalized_key)
    return deduplicated


def _normalized_item_name(value):
    return " ".join(str(value or "").casefold().split())


def _choice_or_default(value, choices, default):
    value = value.strip().lower() if isinstance(value, str) else value
    valid_values = {choice_value for choice_value, _ in choices}
    return value if value in valid_values else default


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
