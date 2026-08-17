import logging

from asgiref.sync import sync_to_async
from google.adk.tools import FunctionTool

from vector_store.services.vectorize import DestinationVectorService
from destinations.models import Activity, Attraction, Cuisine
from vector_store.models import VectorDocument


logger = logging.getLogger(__name__)


def fetch_destination_items_tool(destination_ids: str | list[str]):
    """Create a trip-scoped catalog tool that cannot query unrelated destinations."""

    allowed_destination_ids = _unique_strings(
        destination_ids if isinstance(destination_ids, list) else [destination_ids]
    )

    async def fetch_destination_items(search_query: str = "", limit_per_type: int = 6):
        """
        Fetches personalized tour spots, activities, and food items for every trip destination.
        Uses vector search when search_query is provided, and falls back to destination item lists.

        Args:
            search_query: Short preference/search query for vector matching.
            limit_per_type: Maximum items per item type.
        """
        return await sync_to_async(_fetch_all_destination_items, thread_sensitive=True)(
            allowed_destination_ids,
            search_query,
            limit_per_type,
        )

    return FunctionTool(fetch_destination_items)


def _fetch_all_destination_items(destination_ids, search_query="", limit_per_type=6):
    return {
        "destinations": [
            {
                "destination_id": destination_id,
                **_fetch_destination_items(
                    destination_id,
                    search_query=search_query,
                    limit_per_type=limit_per_type,
                ),
            }
            for destination_id in destination_ids
        ]
    }


def _fetch_destination_items(destination_id: str, search_query: str = "", limit_per_type: int = 6):
    limit_per_type = _safe_limit(limit_per_type)
    search_query = _compact_text(search_query, limit=500)
    vector_candidates = _fetch_vector_candidates(destination_id, search_query, limit_per_type)

    def serialize_attraction(attraction):
        return {
            "id": str(attraction.id),
            "name": attraction.name,
            "attraction_type": attraction.attraction_type,
            "description": _compact_text(attraction.description),
            "address": attraction.address,
            "budget_tier": attraction.budget_tier,
            "avg_duration_hours": attraction.avg_duration_hours,
            "best_time_of_day": attraction.best_time_of_day,
            "picking_reasons": _compact_list(attraction.picking_reasons),
            "notes": _compact_list(attraction.notes),
            "tags": [tag.name for tag in attraction.tags.all()],
            "entrance_fee_required": attraction.entrance_fee_required,
            "approx_entrance_fee": attraction.approx_entrance_fee,
        }

    def serialize_activity(activity):
        return {
            "id": str(activity.id),
            "name": activity.name,
            "activity_type": activity.activity_type,
            "description": _compact_text(activity.description),
            "difficulty_level": activity.difficulty_level,
            "budget_tier": activity.budget_tier,
            "approx_cost": str(activity.approx_cost)
            if activity.approx_cost is not None
            else None,
            "duration_hours": activity.duration_hours,
            "best_months": activity.best_months,
            "picking_reasons": _compact_list(activity.picking_reasons),
            "notes": _compact_list(activity.notes),
            "booking_required": activity.booking_required,
        }

    def serialize_cuisine(cuisine):
        return {
            "id": str(cuisine.id),
            "name": cuisine.name,
            "cuisine_type": cuisine.cuisine_type,
            "description": _compact_text(cuisine.description),
            "spice_level": cuisine.spice_level,
            "meal_type": cuisine.meal_type,
            "is_vegetarian_friendly": cuisine.is_vegetarian_friendly,
            "is_featured": cuisine.is_featured,
            "approx_cost": cuisine.approx_cost,
            "picking_reasons": _compact_list(cuisine.picking_reasons),
            "notes": _compact_list(cuisine.notes),
        }

    attraction_ids = vector_candidates.get("attraction_ids") or []
    activity_ids = vector_candidates.get("activity_ids") or []
    cuisine_ids = vector_candidates.get("cuisine_ids") or []

    attractions = _ordered_items(
        Attraction.objects.filter(destination_id=destination_id).prefetch_related("tags"),
        attraction_ids,
        fallback_order=("-is_featured", "sort_order", "name"),
        limit=limit_per_type,
    )
    activities = _ordered_items(
        Activity.objects.filter(destination_id=destination_id),
        activity_ids,
        fallback_order=("-is_featured", "name"),
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
        "retrieval": {
            "semantic_ranking_used": bool(vector_candidates.get("used")),
            "items_are_ranked": bool(vector_candidates.get("used")),
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
    has_matches = False

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
        has_matches = True

    return {
        "used": has_matches,
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
        return 6
    return min(max(value, 1), 12)


def _compact_text(value, *, limit=600):
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 1].rstrip()}…"


def _compact_list(value, *, limit=5):
    if not isinstance(value, list):
        return []
    return [_compact_text(item, limit=240) for item in value[:limit] if item]


def _unique_strings(values):
    return list(dict.fromkeys(str(value) for value in values if value))
