import json
import re
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from uuid import UUID

from asgiref.sync import async_to_sync
from django.db import transaction
from django.db.models import Max

from destinations.models import Activity, Attraction, Cuisine
from trips.models import (
    TripAgentConversationSession,
    TripAgentMessage,
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
        "preference_context": (agent_context.get("preference_qna") or {}).get("context"),
        "selected_recommendations": {
            "attractions": _serialize_selected_attractions(_recommendation_ids(recommendations, "attraction")),
            "activities": _serialize_selected_activities(recommendations.get("activity_ids", [])),
            "cuisines": _serialize_selected_cuisines(_recommendation_ids(recommendations, "cuisine")),
        },
        "recommendation_messages": recommendations.get("messages", {}),
        "itinerary_design": agent_context.get("itinerary_design") or {},
    }


def _recommendation_ids(recommendations, item_type):
    if item_type == "attraction":
        return recommendations.get("attraction_ids") or recommendations.get("tour_spot_ids") or []
    if item_type == "cuisine":
        return recommendations.get("cuisine_ids") or recommendations.get("food_item_ids") or []
    return recommendations.get(f"{item_type}_ids") or []


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
            "picking_reason_list": item.picking_reason_list,
            "tip_list": item.tip_list,
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
    messages = recommendations.get("messages") if isinstance(recommendations.get("messages"), dict) else {}
    normalized_recommendations = {
        "is_discovery_complete": recommendations.get("is_discovery_complete", False),
        "attraction_ids": recommendations.get("attraction_ids") or recommendations.get("tour_spot_ids", []),
        "activity_ids": recommendations.get("activity_ids", []),
        "cuisine_ids": recommendations.get("cuisine_ids") or recommendations.get("food_item_ids", []),
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

    agent_context = trip.agent_context or {}
    agent_context["recommendations"] = normalized_recommendations

    with transaction.atomic():
        trip_recommendations, _ = TripRecommendations.objects.update_or_create(
            trip=trip,
            defaults={
                "attraction_recommendation_message": normalized_recommendations["messages"]["attractions"],
                "cusine_recommendation_message": normalized_recommendations["messages"]["cuisines"],
                "activity_recommendation_message": normalized_recommendations["messages"]["activities"],
                "session_id": str(session.id),
                "is_finalized": True,
                "metadata": {
                    "external_session_id": session.external_session_id,
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

        trip.agent_context = agent_context
        trip.current_step = max(trip.current_step, 4)
        trip.is_recommendation_complete = True
        trip.updated_by = user
        trip.save(
            update_fields=[
                "agent_context",
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
                "session_id": str(session.id),
                "is_finalized": True,
                "metadata": {
                    "external_session_id": session.external_session_id,
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

        agent_context = trip.agent_context or {}
        agent_context["itinerary_design"] = normalized_itinerary
        trip.agent_context = agent_context
        trip.current_step = max(trip.current_step, 5)
        trip.is_itinerary_design_complete = True
        trip.updated_by = user
        trip.save(
            update_fields=[
                "agent_context",
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
                "is_finalized": True,
                "session_id": str(session.id),
                "metadata": {
                    "external_session_id": session.external_session_id,
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
                        TripPreparationPackingItem.CATEGORY_CHOICES,
                        TripPreparationPackingItem.OTHER,
                    ),
                    priority=_choice_or_default(
                        item.get("priority"),
                        TripPreparationPackingItem.PRIORITY_CHOICES,
                        TripPreparationPackingItem.RECOMMENDED,
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
                        TripRequiredDocumentItem.REQUIRED_LEVEL_CHOICES,
                        TripRequiredDocumentItem.RECOMMENDED,
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
                        TripHeadsUpInfoItem.CATEGORY_CHOICES,
                        TripHeadsUpInfoItem.OTHER,
                    ),
                    severity=_choice_or_default(
                        item.get("severity"),
                        TripHeadsUpInfoItem.SEVERITY_CHOICES,
                        TripHeadsUpInfoItem.LOW,
                    ),
                    additional_note=item.get("details") or "",
                    sort_order=index,
                )
                for index, item in enumerate(normalized_preparation["heads_up"], start=1)
                if item.get("title")
            ]
        )

        agent_context = trip.agent_context or {}
        agent_context["trip_preparation"] = normalized_preparation
        trip.agent_context = agent_context
        trip.current_step = max(trip.current_step, 6)
        trip.is_trip_preparation_complete = True
        trip.updated_by = user
        trip.save(
            update_fields=[
                "agent_context",
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
