import logging
from typing import Optional

from asgiref.sync import sync_to_async
from django.db.models import Q
from google.adk.tools import FunctionTool

from vector_store.services.vectorize import DestinationVectorService
from destinations.choices import Status
from destinations.models import Destination


logger = logging.getLogger(__name__)


def discovery_tools(user):
    """Build user-scoped tools for one discovery-agent request."""

    async def get_traveller_profile():
        """Return the signed-in traveller's preferences, saved places, and prior trips."""
        return await sync_to_async(_get_traveller_profile, thread_sensitive=True)(user.id)

    async def search_destinations(
        query: str = "",
        month: Optional[int] = None,
        destination_type: Optional[str] = None,
        budget_tier: Optional[str] = None,
        duration_days: Optional[int] = None,
        limit: int = 10,
    ):
        """Precisely filter published destinations using validated relational data.

        Args:
            query: Optional name, country, region, tag, or descriptive keyword.
            month: Travel month as an integer from 1 through 12.
            destination_type: Such as city, beach, mountain, cultural, nature, island, or village.
            budget_tier: One of budget, mid, or premium.
            duration_days: Available trip duration in days.
            limit: Maximum results, capped at 20.
        """
        return await sync_to_async(_search_destinations, thread_sensitive=True)(
            user.id,
            query=query,
            month=month,
            destination_type=destination_type,
            budget_tier=budget_tier,
            duration_days=duration_days,
            limit=limit,
        )

    async def get_destination_details(destination_ids: list[str]):
        """Return authoritative details, attractions, activities, and cuisines for 1-3 destination IDs."""
        return await sync_to_async(_get_destination_details, thread_sensitive=True)(
            user.id, destination_ids
        )

    async def semantic_destination_search(
        query: str,
        destination_id: Optional[str] = None,
        limit: int = 8,
    ):
        """Search embedded destination content for broad or descriptive travel questions.

        Semantic results are supporting context, not authoritative structured facts.
        Pass destination_id when the question is about one resolved destination.
        """
        return await sync_to_async(_semantic_destination_search, thread_sensitive=True)(
            query=query,
            destination_id=destination_id,
            limit=limit,
        )

    return [
        FunctionTool(get_traveller_profile),
        FunctionTool(search_destinations),
        FunctionTool(get_destination_details),
        FunctionTool(semantic_destination_search),
    ]


def _get_traveller_profile(user_id):
    from accounts.models import User

    user = User.objects.select_related("profile").get(pk=user_id)
    profile = user.profile
    return {
        "name": user.name,
        "departure_location": profile.location or None,
        "preferred_currency": profile.preferred_currency,
        "travel_interests": profile.travel_interests or [],
        "dietary_preferences": profile.dietary_preferences or [],
        "travel_pace": profile.travel_pace or None,
        "mobility_constraints": profile.mobility_constraints or [],
        "visited_countries": profile.visited_country_list or [],
    }


def _visited_context(user_id):
    from accounts.models import UserProfile
    from trips.choices import TripStatus
    from trips.models import TripDestination

    countries = UserProfile.objects.get(user_id=user_id).visited_country_list or []
    destination_ids = TripDestination.objects.filter(
        trip__user_id=user_id,
        trip__status__in=[
            TripStatus.IN_PROGRESS,
            TripStatus.COMPLETED,
            TripStatus.ARCHIVED,
        ],
    ).values_list("destination_id", flat=True)
    return countries, destination_ids


def _search_destinations(
    user_id,
    *,
    query="",
    month=None,
    destination_type=None,
    budget_tier=None,
    duration_days=None,
    limit=10,
):
    queryset = Destination.objects.filter(status=Status.PUBLISHED).prefetch_related("tags")
    if query and query.strip():
        query = query.strip()
        queryset = queryset.filter(
            Q(name__icontains=query)
            | Q(country__icontains=query)
            | Q(region__icontains=query)
            | Q(description__icontains=query)
            | Q(tags__name__icontains=query)
        )
    if month is not None:
        try:
            month = int(month)
        except (TypeError, ValueError):
            month = None
        if month and 1 <= month <= 12:
            queryset = queryset.filter(best_travel_months__contains=[month])
    if destination_type:
        queryset = queryset.filter(destination_type=destination_type)
    if budget_tier:
        queryset = queryset.filter(budget_tier=budget_tier)
    if duration_days:
        queryset = queryset.filter(min_stay_days__lte=duration_days)

    try:
        safe_limit = min(max(int(limit), 1), 20)
    except (TypeError, ValueError):
        safe_limit = 10
    return [_serialize_destination(item) for item in queryset.distinct()[:safe_limit]]


def _get_destination_details(user_id, destination_ids):
    ids = [str(value) for value in (destination_ids or [])[:3]]
    destinations = (
        Destination.objects.filter(id__in=ids, status=Status.PUBLISHED)
        .prefetch_related("tags", "attractions__tags", "activities", "cuisines")
    )
    visited_countries, visited_destination_ids = _visited_context(user_id)
    visited_destination_ids = {str(value) for value in visited_destination_ids}
    result = []
    for destination in destinations:
        data = _serialize_destination(destination)
        data.update(
            {
                "description": destination.description,
                "picking_reasons": destination.picking_reasons or [],
                "getting_around": destination.getting_around or None,
                "visa_notes": destination.visa_notes or None,
                "previously_visited": (
                    str(destination.id) in visited_destination_ids
                    or destination.country in visited_countries
                ),
                "attractions": [
                    {
                        "id": str(item.id),
                        "name": item.name,
                        "type": item.attraction_type,
                        "budget_tier": item.budget_tier or None,
                        "duration_hours": item.avg_duration_hours,
                        "description": item.description,
                        "tags": [tag.name for tag in item.tags.all()],
                    }
                    for item in destination.attractions.all()[:12]
                ],
                "activities": [
                    {
                        "id": str(item.id),
                        "name": item.name,
                        "type": item.activity_type,
                        "difficulty": item.difficulty_level,
                        "budget_tier": item.budget_tier,
                        "description": item.description,
                    }
                    for item in destination.activities.all()[:12]
                ],
                "cuisines": [
                    {
                        "id": str(item.id),
                        "name": item.name,
                        "type": item.cuisine_type or None,
                        "vegetarian_friendly": item.is_vegetarian_friendly,
                        "description": item.description,
                    }
                    for item in destination.cuisines.all()[:12]
                ],
            }
        )
        result.append(data)
    return result


def _serialize_destination(destination):
    return {
        "id": str(destination.id),
        "slug": destination.slug,
        "name": destination.name,
        "country": destination.country,
        "region": destination.region or None,
        "destination_type": destination.destination_type,
        "budget_tier": destination.budget_tier,
        "difficulty_level": destination.difficulty_level,
        "min_stay_days": destination.min_stay_days,
        "max_stay_days": destination.max_stay_days,
        "best_travel_months": destination.best_travel_months or [],
        "tags": [tag.name for tag in destination.tags.all()],
    }


def _semantic_destination_search(*, query, destination_id=None, limit=8):
    try:
        safe_limit = min(max(int(limit), 1), 12)
        results = DestinationVectorService().search(
            query,
            limit=safe_limit,
            destination_id=destination_id,
        )
    except Exception as exc:
        logger.warning("Destination semantic search unavailable: %s", type(exc).__name__)
        return {"available": False, "results": []}
    return {
        "available": True,
        "results": [
            {
                "source_type": item.source_type,
                "source_id": item.source_id,
                "content": item.content,
                "distance": (
                    round(item.distance, 4) if item.distance is not None else None
                ),
                "text_rank": item.text_rank,
                "rrf_score": item.rrf_score,
            }
            for item in results
        ],
    }
