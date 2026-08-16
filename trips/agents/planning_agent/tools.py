import logging

from asgiref.sync import sync_to_async
from google.adk.tools import FunctionTool

from vector_store.services.vectorize import DestinationVectorService
from destinations.models import Activity, Attraction, Cuisine
from vector_store.models import VectorDocument


logger = logging.getLogger(__name__)


def fetch_destination_items_tool():
    async def fetch_destination_items(destination_id: str, search_query: str = "", limit_per_type: int = 8):
        """
        Fetches personalized tour spots, activities, and food items for one destination.
        Uses vector search when search_query is provided, and falls back to destination item lists.

        Args:
            destination_id: The ID of the destination for which to fetch items.
            search_query: Short preference/search query for vector matching.
            limit_per_type: Maximum items per item type.
        """
        return await sync_to_async(_fetch_destination_items, thread_sensitive=True)(
            destination_id,
            search_query,
            limit_per_type,
        )

    return FunctionTool(fetch_destination_items)


def fetch_trip_planning_context_tool():
    async def fetch_trip_planning_context(trip_id: str):
        """
        Fetches trip planning context for a trip.

        Args:
            trip_id: The ID of the trip for which to fetch context.
        """
        return await sync_to_async(_fetch_trip_planning_context, thread_sensitive=True)(trip_id)

    return FunctionTool(fetch_trip_planning_context)


def _fetch_trip_planning_context(trip_id: str):
    from trips.models import Trip
    from trips.services.services import build_itinerary_planning_context

    trip = Trip.objects.get(pk=trip_id)
    return build_itinerary_planning_context(trip)


def _fetch_destination_items(destination_id: str, search_query: str = "", limit_per_type: int = 8):
    limit_per_type = _safe_limit(limit_per_type)
    vector_candidates = _fetch_vector_candidates(destination_id, search_query, limit_per_type)

    def serialize_attraction(attraction):
        return {
            "id": str(attraction.id),
            "name": attraction.name,
            "attraction_type": attraction.attraction_type,
            "description": attraction.description,
            "how_to_reach": attraction.how_to_reach,
            "address": attraction.address,
            "budget_tier": attraction.budget_tier,
            "avg_duration_hours": attraction.avg_duration_hours,
            "best_time_of_day": attraction.best_time_of_day,
            "picking_reasons": attraction.picking_reasons,
            "notes": attraction.notes,
            "tags": [tag.name for tag in attraction.tags.all()],
            "images": [image.image_url for image in attraction.images.all()],
            "entrance_fee_required": attraction.entrance_fee_required,
            "approx_entrance_fee": attraction.approx_entrance_fee,
        }

    def serialize_activity(activity):
        return {
            "id": str(activity.id),
            "name": activity.name,
            "activity_type": activity.activity_type,
            "description": activity.description,
            "difficulty_level": activity.difficulty_level,
            "budget_tier": activity.budget_tier,
            "approx_cost": str(activity.approx_cost)
            if activity.approx_cost is not None
            else None,
            "duration_hours": activity.duration_hours,
            "best_months": activity.best_months,
            "picking_reasons": activity.picking_reasons,
            "notes": activity.notes,
            "booking_required": activity.booking_required,
        }

    def serialize_cuisine(cuisine):
        return {
            "id": str(cuisine.id),
            "name": cuisine.name,
            "cuisine_type": cuisine.cuisine_type,
            "description": cuisine.description,
            "spice_level": cuisine.spice_level,
            "meal_type": cuisine.meal_type,
            "is_vegetarian_friendly": cuisine.is_vegetarian_friendly,
            "is_featured": cuisine.is_featured,
            "approx_cost": cuisine.approx_cost,
            "picking_reasons": cuisine.picking_reasons,
            "notes": cuisine.notes,
        }

    attraction_ids = vector_candidates.get("attraction_ids") or []
    activity_ids = vector_candidates.get("activity_ids") or []
    cuisine_ids = vector_candidates.get("cuisine_ids") or []

    attractions = _ordered_items(
        Attraction.objects.filter(destination_id=destination_id).prefetch_related("tags", "images"),
        attraction_ids,
        fallback_order=("name",),
        limit=limit_per_type,
    )
    activities = _ordered_items(
        Activity.objects.filter(destination_id=destination_id),
        activity_ids,
        fallback_order=("name",),
        limit=limit_per_type,
    )
    cuisines = _ordered_items(
        Cuisine.objects.filter(destination_id=destination_id),
        cuisine_ids,
        fallback_order=("-is_featured", "name"),
        limit=limit_per_type,
    )

    return {
        "attractions": [serialize_attraction(item) for item in attractions],
        "activities": [serialize_activity(item) for item in activities],
        "cuisines": [serialize_cuisine(item) for item in cuisines],
        "vector_search": {
            "used": bool(vector_candidates.get("used")),
            "query": search_query or "",
            "matches": vector_candidates.get("matches", []),
        },
    }


def _fetch_vector_candidates(destination_id: str, search_query: str, limit_per_type: int):
    search_query = (search_query or "").strip()
    if not search_query:
        return {"used": False, "matches": []}

    try:
        results = DestinationVectorService().search(
            search_query,
            limit=limit_per_type * 3,
            source_types=[
                VectorDocument.SourceType.ATTRACTION,
                VectorDocument.SourceType.ACTIVITY,
                VectorDocument.SourceType.CUISINE,
            ],
            destination_id=destination_id,
        )
    except Exception as exc:
        logger.warning(
            "Planning vector search failed; falling back to relational destination items. "
            "destination_id=%s error_type=%s",
            destination_id,
            type(exc).__name__,
        )
        return {"used": False, "matches": []}

    candidate_ids = {
        "attraction_ids": [],
        "activity_ids": [],
        "cuisine_ids": [],
    }
    matches = []

    for result in results:
        if result.source_type == VectorDocument.SourceType.ATTRACTION:
            key = "attraction_ids"
        elif result.source_type == VectorDocument.SourceType.ACTIVITY:
            key = "activity_ids"
        elif result.source_type == VectorDocument.SourceType.CUISINE:
            key = "cuisine_ids"
        else:
            continue

        if len(candidate_ids[key]) >= limit_per_type or result.source_id in candidate_ids[key]:
            continue

        candidate_ids[key].append(result.source_id)
        matches.append(
            {
                "source_type": result.source_type,
                "source_id": result.source_id,
                "distance": result.distance,
                "text_rank": result.text_rank,
                "rrf_score": result.rrf_score,
                "name": result.metadata.get("name"),
            }
        )

    return {
        "used": bool(matches),
        "matches": matches,
        **candidate_ids,
    }


def _ordered_items(queryset, selected_ids, fallback_order, limit):
    selected_ids = [str(item_id) for item_id in selected_ids or []]
    ordered = []

    if selected_ids:
        item_map = {str(item.id): item for item in queryset.filter(id__in=selected_ids)}
        ordered = [item_map[item_id] for item_id in selected_ids if item_id in item_map]

    if len(ordered) >= limit:
        return ordered[:limit]

    selected_set = {str(item.id) for item in ordered}
    fallback_items = [
        item
        for item in queryset.exclude(id__in=selected_set).order_by(*fallback_order)[: limit - len(ordered)]
    ]
    return ordered + fallback_items


def _safe_limit(value):
    try:
        value = int(value)
    except (TypeError, ValueError):
        return 8
    return min(max(value, 1), 20)
