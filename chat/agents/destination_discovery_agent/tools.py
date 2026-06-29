from asgiref.sync import sync_to_async
from google.adk.tools import FunctionTool

from destinations.models import Activity, Attraction, Cuisine


def fetch_destination_items_tool():
    async def fetch_destination_items(destination_id: str):
        """
        Fetches personalized tour spots, activities, and food items for one destination.

        Args:
            destination_id: The ID of the destination for which to fetch items.
        """
        return await sync_to_async(_fetch_destination_items, thread_sensitive=True)(destination_id)

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
    from trips.services import build_itinerary_planning_context

    trip = Trip.objects.get(pk=trip_id)
    return build_itinerary_planning_context(trip)


def _fetch_destination_items(destination_id: str):
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
            "picking_reason_list": attraction.picking_reason_list,
            "tip_list": attraction.tip_list,
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
            "cost_unit": activity.cost_unit,
            "duration_hours": activity.duration_hours,
            "best_season": activity.best_season,
        }

    def serialize_cuisine(cuisine):
        return {
            "id": str(cuisine.id),
            "name": cuisine.name,
            "cuisine_type": cuisine.cuisine_type,
            "description": cuisine.description,
            "ingredients_note": cuisine.ingredients_note,
            "spice_level": cuisine.spice_level,
            "meal_type": cuisine.meal_type,
            "is_vegetarian_friendly": cuisine.is_vegetarian_friendly,
            "is_must_try": cuisine.is_must_try,
            "approx_price_range": cuisine.approx_price_range,
        }

    attractions = (
        Attraction.objects.filter(destination_id=destination_id)
        .prefetch_related("tags", "images")
        .order_by("name")
    )
    activities = Activity.objects.filter(destination_id=destination_id).order_by("name")
    cuisines = Cuisine.objects.filter(destination_id=destination_id).order_by("-is_must_try", "name")

    return {
        "attractions": [serialize_attraction(item) for item in attractions],
        "activities": [serialize_activity(item) for item in activities],
        "cuisines": [serialize_cuisine(item) for item in cuisines],
    }
