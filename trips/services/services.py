import json
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID

from asgiref.sync import async_to_sync
from django.db import transaction

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
    if plan_ready is None:
        plan_ready = is_trip_plan_ready(trip)
    conversation_session, _ = TripConversationSession.objects.get_or_create(
        trip=trip,
        defaults={
            "user": user,
            "is_active": plan_ready,
            "created_by": user,
            "updated_by": user,
        },
    )
    if plan_ready and not conversation_session.is_active:
        conversation_session.is_active = True
        conversation_session.updated_by = user
        conversation_session.save(update_fields=["is_active", "updated_by", "updated_at"])
    return conversation_session


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
    actor = user or session.user
    return TripConversationMessage.objects.create(
        session=session,
        sender=sender,
        content=content or "",
        metadata=metadata or {},
        read_at=read_at,
        created_by=actor,
        updated_by=actor,
    )


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

    has_saved_recommendations = TripRecommendations.objects.filter(trip=trip).exists()
    has_saved_itinerary = TripItinerary.objects.filter(trip=trip).exists()
    has_saved_preparation = TripPreparation.objects.filter(trip=trip).exists()

    return {
        "current_step": trip.current_step,
        "agent_active": trip.agent_active,
        "is_qna_complete": bool(trip.is_qna_complete or preference_qna.get("context")),
        "is_recommendation_complete": bool(
            trip.is_recommendation_complete
            or recommendations.get("is_discovery_complete")
            or has_saved_recommendations
        ),
        "is_itinerary_design_complete": bool(
            trip.is_itinerary_design_complete
            or itinerary_design.get("is_itinerary_complete")
            or has_saved_itinerary
        ),
        "is_trip_preparation_complete": bool(
            trip.is_trip_preparation_complete
            or trip_preparation.get("is_preparation_complete")
            or has_saved_preparation
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


def get_trip_planning_flow(trip):
    progress = get_trip_planning_progress(trip)
    return [
        {
            "step": PlanningStep.PREFERENCE,
            "label": PLANNING_STEP_LABELS[PlanningStep.PREFERENCE],
            "is_complete": progress["is_qna_complete"],
            "is_current": trip.current_step == PlanningStep.PREFERENCE,
            "can_open": True,
            "can_generate": not progress["is_qna_complete"],
        },
        {
            "step": PlanningStep.RECOMMENDATION,
            "label": PLANNING_STEP_LABELS[PlanningStep.RECOMMENDATION],
            "is_complete": progress["is_recommendation_complete"],
            "is_current": trip.current_step == PlanningStep.RECOMMENDATION,
            "can_open": progress["is_qna_complete"],
            "can_generate": progress["is_qna_complete"],
        },
        {
            "step": PlanningStep.ITINERARY,
            "label": PLANNING_STEP_LABELS[PlanningStep.ITINERARY],
            "is_complete": progress["is_itinerary_design_complete"],
            "is_current": trip.current_step == PlanningStep.ITINERARY,
            "can_open": progress["is_recommendation_complete"],
            "can_generate": progress["is_recommendation_complete"],
        },
        {
            "step": PlanningStep.PREPARATION,
            "label": PLANNING_STEP_LABELS[PlanningStep.PREPARATION],
            "is_complete": progress["is_trip_preparation_complete"],
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
        if not trip.trip_destinations.exists():
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


def get_activation_blocking_errors(trip):
    progress = get_trip_planning_progress(trip)
    blocking_errors = []

    if trip.status not in {TripStatus.DRAFT, TripStatus.PLANNING}:
        blocking_errors.append("Trip status must be draft or planning.")
    if not progress["is_itinerary_design_complete"]:
        blocking_errors.append("Generate the trip itinerary.")
    if not progress["is_trip_preparation_complete"]:
        blocking_errors.append("Generate the trip preparation checklist.")

    return blocking_errors


def build_planning_response_meta(trip):
    activation_blocking_errors = get_activation_blocking_errors(trip)
    planning_session = getattr(trip, "planning_session", None)
    return {
        "planning_session_id": str(planning_session.id) if planning_session else None,
        "progress": get_trip_planning_progress(trip),
        "flow": get_trip_planning_flow(trip),
        "activation": {
            "can_activate": not activation_blocking_errors,
            "blocking_steps": activation_blocking_errors,
        },
    }


def build_trip_snapshot(trip):
    destinations = []
    trip_destinations = getattr(trip, "prefetched_trip_destinations", None)
    if trip_destinations is None:
        trip_destinations = trip.trip_destinations.select_related("destination").order_by("sort_order")

    for trip_destination in trip_destinations:
        destination = trip_destination.destination
        destinations.append(
            {
                "name": destination.name,
                "description": destination.description,
                "country": destination.country,
                "region": destination.region,
                "type": destination.destination_type,
                "budget_tier": destination.budget_tier,
                "min_stay_days": destination.min_stay_days,
                "max_stay_days": destination.max_stay_days,
                "best_travel_months": destination.best_travel_months,
                "getting_around": destination.getting_around,
                "visa_notes": destination.visa_notes,
                "notes": destination.notes,
            }
        )

    return {
        "trip_id": str(trip.id),
        "duration_days": trip.duration_days,
        "travelers_count": trip.travelers_count,
        "traveler_type": trip.traveler_type,
        "origin_city": trip.origin_city,
        "origin_country": trip.origin_country,
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
        planning_step=session.step,
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


def build_trip_guide_context(trip):
    """Build the authoritative saved-plan context used by post-planning chat."""
    context = build_itinerary_planning_context(trip)

    recommendations = getattr(trip, "trip_recommendations", None)
    if recommendations:
        attraction_ids = list(
            recommendations.attraction_items.exclude(attraction=None).values_list(
                "attraction_id", flat=True
            )
        )
        activity_ids = list(
            recommendations.activity_items.values_list("activity_id", flat=True)
        )
        cuisine_ids = list(
            recommendations.cuisine_items.values_list("cuisine_id", flat=True)
        )
        context["selected_recommendations"] = {
            "attractions": _serialize_selected_attractions(attraction_ids),
            "activities": _serialize_selected_activities(activity_ids),
            "cuisines": _serialize_selected_cuisines(cuisine_ids),
        }
        context["recommendation_messages"] = {
            "attractions": recommendations.attraction_recommendation_message,
            "activities": recommendations.activity_recommendation_message,
            "cuisines": recommendations.cusine_recommendation_message,
        }

    itinerary = getattr(trip, "trip_itinerary", None)
    if itinerary:
        # The relational itinerary reflects any edits made after AI planning.
        context.pop("itinerary_design", None)
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

    preparation = getattr(trip, "structured_preparation", None)
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
    from trips.agents.guide_agent import GuideAgentClient

    client = GuideAgentClient(
        session.trip,
        trip_context=build_trip_guide_context(session.trip),
    )
    result = async_to_sync(client.run_agent)(
        user_query=user_query,
        user_id=str(session.user_id),
        session_id=session.external_session_id or None,
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


def build_preparation_agent_query(trip_context):
    return (
        "Generate step 5 trip preparation from this compact trip planning context. "
        "Use the provided trip data directly as the source of truth. Return only the structured preparation JSON.\n"
        f"Trip planning context: {json.dumps(trip_context or {}, default=str)}"
    )


def build_itinerary_planning_context(trip):
    agent_context = trip.metadata or {}
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
        "preference_context": (agent_context.get("preference_qna") or {}).get("context"),
        "selected_recommendations": {
            "attractions": _serialize_selected_attractions(_recommendation_ids(recommendations, "attraction")),
            "activities": _serialize_selected_activities(_recommendation_ids(recommendations, "activity")),
            "cuisines": _serialize_selected_cuisines(_recommendation_ids(recommendations, "cuisine")),
        },
        "recommendation_messages": recommendations.get("messages", {}),
        "itinerary_design": agent_context.get("itinerary_design") or {},
    }


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
    items = Attraction.objects.filter(id__in=selected_ids).prefetch_related("tags", "images")
    item_map = {str(item.id): item for item in items}
    return [
        {
            "id": str(item.id),
            "name": item.name,
            "type": item.attraction_type,
            "description": item.description,
            "how_to_reach": item.how_to_reach,
            "address": item.address,
            "latitude": item.latitude,
            "longitude": item.longitude,
            "budget_tier": item.budget_tier,
            "avg_duration_hours": item.avg_duration_hours,
            "best_time_of_day": item.best_time_of_day,
            "picking_reasons": item.picking_reasons,
            "notes": item.notes,
            "tags": [tag.name for tag in item.tags.all()],
            "images": [image.image_url for image in item.images.all()],
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
            "duration_hours": item.duration_hours,
            "best_season": item.best_season,
            "picking_reasons": item.picking_reasons,
            "notes": item.notes,
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
            "spice_level": item.spice_level,
            "meal_type": item.meal_type,
            "is_vegetarian_friendly": item.is_vegetarian_friendly,
            "is_featured": item.is_featured,
            "approx_cost": item.approx_cost,
            "picking_reasons": item.picking_reasons,
            "notes": item.notes,
        }
        for item_id in selected_ids
        if (item := item_map.get(str(item_id)))
    ]


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
    normalized_recommendations = {
        "is_discovery_complete": recommendations.get("is_discovery_complete", False),
        "attraction_ids": _valid_uuid_strings(
            recommendations.get("attraction_ids") or recommendations.get("tour_spot_ids", [])
        ),
        "activity_ids": _valid_uuid_strings(recommendations.get("activity_ids", [])),
        "cuisine_ids": _valid_uuid_strings(
            recommendations.get("cuisine_ids") or recommendations.get("food_item_ids", [])
        ),
        "messages": {
            "attractions": messages.get("attractions") or messages.get("tour_spots") or "",
            "activities": messages.get("activities") or "",
            "cuisines": messages.get("cuisines") or messages.get("foods") or "",
        },
        "session_id": str(session.id),
        "external_session_id": session.external_session_id,
    }

    if not recommendations.get("is_discovery_complete"):
        trip.updated_by = user
        trip.save(update_fields=["updated_by", "updated_at"])
        return normalized_recommendations

    agent_context = trip.metadata or {}
    agent_context["recommendations"] = normalized_recommendations

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

        attraction_ids = set(
            str(item.id)
            for item in Attraction.objects.filter(id__in=normalized_recommendations["attraction_ids"])
        )
        activity_ids = set(
            str(item.id)
            for item in Activity.objects.filter(id__in=normalized_recommendations["activity_ids"])
        )
        cuisine_ids = set(
            str(item.id)
            for item in Cuisine.objects.filter(id__in=normalized_recommendations["cuisine_ids"])
        )

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


def update_trip_agent_context_from_itinerary(trip, agent_response, session, user):
    itinerary = agent_response.get("response") or {}
    normalized_itinerary = {
        "is_itinerary_complete": itinerary.get("is_itinerary_complete", False),
        "title": itinerary.get("title", ""),
        "summary": itinerary.get("summary", ""),
        "day_wise_plan": itinerary.get("day_wise_plan") if isinstance(itinerary.get("day_wise_plan"), list) else [],
        "route_plan": itinerary.get("route_plan") if isinstance(itinerary.get("route_plan"), list) else [],
        "rough_budget": itinerary.get("rough_budget") if isinstance(itinerary.get("rough_budget"), dict) else {},
        "message": itinerary.get("message", ""),
        "session_id": str(session.id),
        "external_session_id": session.external_session_id,
    }

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
        agent_context["itinerary_design"] = normalized_itinerary
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
        return Decimal(number_match.group(0).replace(",", ""))
    except InvalidOperation:
        return None


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
    normalized_preparation = {
        "is_preparation_complete": preparation.get("is_preparation_complete", False),
        "title": preparation.get("title", ""),
        "summary": preparation.get("summary", ""),
        "packing_items": preparation.get("packing_items", []),
        "required_documents": preparation.get("required_documents", []),
        "heads_up": preparation.get("heads_up", []),
        "message": preparation.get("message", ""),
        "session_id": str(session.id),
        "external_session_id": session.external_session_id,
    }

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

        structured_preparation.packing_items.all().delete()
        structured_preparation.required_documents.all().delete()
        structured_preparation.heads_up.all().delete()

        TripPreparationPackingItem.objects.bulk_create(
            [
                TripPreparationPackingItem(
                    preparation=structured_preparation,
                    item=item.get("item", ""),
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
                    additional_notes=item.get("reason") or "",
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
                    document_name=item.get("document", ""),
                    required_level=_choice_or_default(
                        item.get("required_level"),
                        RequiredType.choices,
                        RequiredType.RECOMMENDED,
                    ),
                    additional_note=item.get("reason") or "",
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
                    title=item.get("title", ""),
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
                    additional_note=item.get("details") or "",
                    sort_order=index,
                )
                for index, item in enumerate(normalized_preparation["heads_up"], start=1)
                if item.get("title")
            ]
        )

        agent_context = trip.metadata or {}
        agent_context["trip_preparation"] = normalized_preparation
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
