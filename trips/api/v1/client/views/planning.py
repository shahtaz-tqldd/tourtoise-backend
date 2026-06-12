from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated

from app.utils.response import APIResponse
from destinations.api.v1.client.serializers import (
    ClientActivitySerializer,
    ClientAttractionSerializer,
    ClientCuisineSerializer,
)
from destinations.models import Activity, Attraction, Cuisine
from trips.api.v1.client.serializers import (
    TripAgentActiveSerializer,
    TripAgentCreateMessageSerializer,
    TripAgentMessageListQuerySerializer,
    TripAgentMessageSerializer,
)
from trips.choices import AgentMessageSender, TripStatus
from trips.models import (
    TripAgentConversationSession,
    TripAgentMessage,
    TripItinerary,
    TripPreparation,
    TripRecommendations,
)
from trips.services import (
    build_initial_agent_query,
    build_itinerary_agent_query,
    build_itinerary_planning_context,
    build_preparation_agent_query,
    build_recommendations_agent_query,
    build_trip_snapshot,
    create_agent_message,
    get_or_create_agent_conversation_session,
    run_plan_agent_for_session as _run_plan_agent_for_session,
    update_trip_agent_context_from_qna,
    update_trip_agent_context_from_itinerary,
    update_trip_agent_context_from_preparation,
    update_trip_agent_context_from_recommendations,
    update_user_profile_from_agent_preferences,
)

from .mixin import UserTripQuerysetMixin, TripPaginationMixin


def run_plan_agent_for_session(*args, **kwargs):
    from trips.api.v1.client import views

    patched_runner = getattr(views, "run_plan_agent_for_session", None)
    if patched_runner is not None and patched_runner is not run_plan_agent_for_session:
        return patched_runner(*args, **kwargs)
    return _run_plan_agent_for_session(*args, **kwargs)


class TripAgentInitAPIView(UserTripQuerysetMixin, GenericAPIView):
    """
    Activate/update trip planning agent preferences for the current trip step.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TripAgentActiveSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)

        trip = get_object_or_404(
            self.get_trip_queryset(),
            pk=serializer.validated_data["trip_id"],
        )
        normalized_payload = serializer.normalized_preferences()

        if not serializer.validated_data["let_agent_decide"]:
            trip.agent_active = False
            trip.agent_active_failed_message = ""
            trip.preferences = {"agent_customization": normalized_payload}
            trip.updated_by = request.user
            trip.save(
                update_fields=[
                    "agent_active",
                    "agent_active_failed_message",
                    "preferences",
                    "updated_by",
                    "updated_at",
                ]
            )
            update_user_profile_from_agent_preferences(request.user, normalized_payload)
            return APIResponse.success(
                data={
                    "agent_active": False,
                    "agent_active_failed_message": "",
                    "agent_message": "Agent is not active because let_agent_decide is false.",
                },
                message="Trip agent preferences updated successfully.",
            )

        trip_snapshot = build_trip_snapshot(trip)
        session = get_or_create_agent_conversation_session(trip, request.user, current_step=2)
        create_agent_message(
            session=session,
            sender=AgentMessageSender.USER,
            content="Initial trip preferences submitted.",
            payload={
                "preferences": normalized_payload,
                "trip_snapshot": trip_snapshot,
            },
            user=request.user,
        )
        plan_agent_response = run_plan_agent_for_session(
            session=session,
            user_query=build_initial_agent_query(normalized_payload, trip_snapshot),
            preferences=normalized_payload,
            trip_snapshot=trip_snapshot,
        )
        qna_response = plan_agent_response["response"]
        agent_message = qna_response.get("question") or qna_response.get("context") or ""
        if qna_response.get("question"):
            session.qna_count += 1
            session.updated_by = request.user
            session.save(update_fields=["qna_count", "updated_by", "updated_at"])
        create_agent_message(
            session=session,
            sender=AgentMessageSender.AGENT,
            content=agent_message,
            payload={
                "qna_response": qna_response,
                "cost": plan_agent_response.get("cost"),
                "total_tokens": plan_agent_response.get("total_tokens"),
            },
            user=request.user,
        )

        trip.preferences = {"agent_customization": normalized_payload}
        trip.agent_active = True        
        trip.updated_by = request.user
        trip.save(
            update_fields=[
                "preferences",
                "agent_active",
                "updated_by",
                "updated_at",
            ]
        )
        
        update_trip_agent_context_from_qna(trip, plan_agent_response, session, request.user)

        update_user_profile_from_agent_preferences(request.user, normalized_payload)

        return APIResponse.success(
            data={
                "session_id": str(session.id),
                "agent_active": trip.agent_active,
                "agent_message": agent_message,
                "is_qna_complete": qna_response.get("is_qna_complete", False),
                "context": qna_response.get("context"),
                "current_step": trip.current_step,
            },
            message="Trip agent preferences updated successfully.",
        )


class TripAgentCreateMessageAPIView(UserTripQuerysetMixin, GenericAPIView):
    """
    Save a trip agent message and advance the trip planning flow.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TripAgentCreateMessageSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        trip = get_object_or_404(
            self.get_trip_queryset(),
            pk=serializer.validated_data["trip_id"],
        )
        current_step = serializer.validated_data["current_step"]
        session_id = serializer.validated_data.get("session_id")
        if session_id:
            session = get_object_or_404(
                TripAgentConversationSession.objects.filter(
                    trip=trip,
                    user=request.user,
                    current_step=current_step,
                ),
                pk=session_id,
            )
        else:
            session = get_or_create_agent_conversation_session(trip, request.user, current_step=current_step)

        create_agent_message(
            session=session,
            sender=AgentMessageSender.USER,
            content=serializer.validated_data["message"],
            user=request.user,
        )

        
        plan_agent_response = run_plan_agent_for_session(
            session=session,
            user_query=serializer.validated_data["message"]
        )
        qna_response = plan_agent_response["response"]
        agent_message = qna_response.get("question") or qna_response.get("context") or ""

        if qna_response.get("question"):
            session.qna_count += 1
            session.updated_by = request.user
            session.save(update_fields=["qna_count", "updated_by", "updated_at"])

        create_agent_message(
            session=session,
            sender=AgentMessageSender.AGENT,
            content=agent_message,
            payload={
                "qna_response": qna_response,
                "cost": plan_agent_response.get("cost"),
                "total_tokens": plan_agent_response.get("total_tokens"),
                "intention": plan_agent_response.get("intention"),
            },
            user=request.user,
        )

        trip.updated_by = request.user
        trip.save(update_fields=["updated_by", "updated_at"])
        is_step_complete = update_trip_agent_context_from_qna(trip, plan_agent_response, session, request.user)

        return APIResponse.success(
            data={
                "agent_message": agent_message,
                "session_id": str(session.id),
                "is_qna_complete": qna_response.get("is_qna_complete", False),
                "is_step_complete": is_step_complete,
                "context": qna_response.get("context"),
                "current_step": trip.current_step,
            },
            message="Trip agent message created successfully.",
        )


class TripAgentMessageListAPIView(TripPaginationMixin, UserTripQuerysetMixin, GenericAPIView):
    """
    List persisted trip-agent conversation messages.

    Query params:
    - `trip_id` required
    - `step` optional, e.g. `step=2`
    - `page`, `page_size` optional pagination params
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TripAgentMessageListQuerySerializer

    def get(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        trip_id = serializer.validated_data["trip_id"]

        trip = get_object_or_404(self.get_trip_queryset(), pk=trip_id)
        queryset = TripAgentMessage.objects.filter(
            trip=trip,
            session__user=request.user,
        ).select_related("session")

        step = serializer.validated_data.get("step")
        if step:
            queryset = queryset.filter(step=step)

        queryset = queryset.order_by("session__created_at", "sequence", "created_at")
        return self.paginate_with_meta(
            queryset,
            TripAgentMessageSerializer,
            message="Trip agent messages fetched successfully.",
        )


class TripPlanningRecommendationsAPIView(UserTripQuerysetMixin, GenericAPIView):
    """
    Get trip recommendations
    Query params:
    - `trip_id` required
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TripAgentMessageListQuerySerializer

    def get(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        trip = get_object_or_404(self.get_trip_queryset(), pk=serializer.validated_data["trip_id"])
        if trip.is_recommendation_complete:
            saved_recommendations = self._get_saved_recommendations(trip)
            if saved_recommendations:
                return APIResponse.success(
                    data=self._serialize_saved_recommendations(saved_recommendations),
                    message="Trip recommendations fetched successfully.",
                )

            existing_recommendations = (trip.agent_context or {}).get("recommendations")
            if existing_recommendations and existing_recommendations.get("is_discovery_complete"):
                return APIResponse.success(
                    data=self._serialize_recommendations(existing_recommendations),
                    message="Trip recommendations fetched successfully.",
                )

        trip_destination = self._get_recommendation_destination(trip)
        if not trip_destination:
            return APIResponse.error(
                message="Add a destination to this trip before requesting recommendations.",
                status=status.HTTP_400_BAD_REQUEST,
            )

        destination_id = str(trip_destination.destination_id)
        trip_snapshot = build_trip_snapshot(trip)
        preferences = {
            "trip_preferences": trip.preferences or {},
            "preference_context": (trip.agent_context or {}).get("preference_qna", {}).get("context"),
        }

        session = get_or_create_agent_conversation_session(trip, request.user, current_step=3)
        create_agent_message(
            session=session,
            sender=AgentMessageSender.USER,
            content="Generate trip recommendations.",
            payload={
                "destination_id": destination_id,
                "preferences": preferences,
                "trip_snapshot": trip_snapshot,
            },
            user=request.user,
        )

        plan_agent_response = run_plan_agent_for_session(
            session=session,
            user_query=build_recommendations_agent_query(preferences, trip_snapshot, destination_id),
            preferences=preferences,
            trip_snapshot=trip_snapshot,
            destination_id=destination_id,
        )
        recommendations = update_trip_agent_context_from_recommendations(
            trip,
            plan_agent_response,
            session,
            request.user,
        )

        create_agent_message(
            session=session,
            sender=AgentMessageSender.AGENT,
            content="Trip recommendations generated.",
            payload={
                "recommendations": recommendations,
                "cost": plan_agent_response.get("cost"),
                "total_tokens": plan_agent_response.get("total_tokens"),
                "intention": plan_agent_response.get("intention"),
            },
            user=request.user,
        )

        if not recommendations.get("is_discovery_complete"):
            return APIResponse.error(
                errors=recommendations,
                message="Trip agent recommendations could not be generated.",
                status=status.HTTP_502_BAD_GATEWAY,
            )

        return APIResponse.success(
            data=self._serialize_recommendations(recommendations),
            message="Trip recommendations created successfully.",
        )

    def _get_recommendation_destination(self, trip):
        trip_destinations = getattr(trip, "prefetched_trip_destinations", None)
        if trip_destinations is None:
            trip_destinations = trip.trip_destinations.select_related("destination").order_by("sort_order")
        return next((item for item in trip_destinations if item.is_primary), None) or next(
            iter(trip_destinations),
            None,
        )

    def _serialize_recommendations(self, recommendations):
        attraction_ids = self._recommendation_ids(recommendations, "attraction")
        cuisine_ids = self._recommendation_ids(recommendations, "cuisine")
        return {
            "is_recommendation_complete": recommendations.get("is_discovery_complete", False),
            "attractions": self._serialize_items(
                Attraction.objects.filter(id__in=attraction_ids).prefetch_related("images"),
                attraction_ids,
                ClientAttractionSerializer,
            ),
            "activities": self._serialize_items(
                Activity.objects.filter(id__in=recommendations.get("activity_ids", [])).prefetch_related("images"),
                recommendations.get("activity_ids", []),
                ClientActivitySerializer,
            ),
            "cuisines": self._serialize_items(
                Cuisine.objects.filter(id__in=cuisine_ids).prefetch_related("images"),
                cuisine_ids,
                ClientCuisineSerializer,
            ),
            "messages": self._serialize_recommendation_messages(recommendations.get("messages", {})),
            "session_id": recommendations.get("session_id"),
            "external_session_id": recommendations.get("external_session_id"),
        }

    def _get_saved_recommendations(self, trip):
        try:
            return (
                TripRecommendations.objects.prefetch_related(
                    "attraction_items__attraction__images",
                    "activity_items__activity__images",
                    "cuisine_items__cuisine__images",
                )
                .get(trip=trip)
            )
        except TripRecommendations.DoesNotExist:
            return None

    def _serialize_saved_recommendations(self, recommendations):
        attractions = [
            item.attraction
            for item in recommendations.attraction_items.all()
            if item.attraction_id and item.attraction
        ]
        activities = [item.activity for item in recommendations.activity_items.all()]
        cuisines = [item.cuisine for item in recommendations.cuisine_items.all()]

        return {
            "is_recommendation_complete": True,
            "attractions": ClientAttractionSerializer(
                attractions,
                many=True,
                context={"request": self.request},
            ).data,
            "activities": ClientActivitySerializer(
                activities,
                many=True,
                context={"request": self.request},
            ).data,
            "cuisines": ClientCuisineSerializer(
                cuisines,
                many=True,
                context={"request": self.request},
            ).data,
            "messages": {
                "attractions": recommendations.attraction_recommendation_message,
                "activities": recommendations.activity_recommendation_message,
                "cuisines": recommendations.cusine_recommendation_message,
            },
            "session_id": recommendations.session_id,
            "external_session_id": (recommendations.metadata or {}).get("external_session_id"),
        }

    def _serialize_recommendation_messages(self, messages):
        messages = messages if isinstance(messages, dict) else {}
        return {
            "attractions": messages.get("attractions") or messages.get("tour_spots") or "",
            "activities": messages.get("activities") or "",
            "cuisines": messages.get("cuisines") or messages.get("foods") or "",
        }

    def _recommendation_ids(self, recommendations, item_type):
        if item_type == "attraction":
            return recommendations.get("attraction_ids") or recommendations.get("tour_spot_ids") or []
        if item_type == "cuisine":
            return recommendations.get("cuisine_ids") or recommendations.get("food_item_ids") or []
        return recommendations.get(f"{item_type}_ids") or []

    def _serialize_items(self, queryset, selected_ids, serializer_class):
        item_map = {str(item.id): item for item in queryset}
        ordered_items = [item_map[str(item_id)] for item_id in selected_ids if str(item_id) in item_map]
        return serializer_class(ordered_items, many=True, context={"request": self.request}).data


class TripPlanningItinerariesAPIView(UserTripQuerysetMixin, GenericAPIView):
    """
    Get trip itinerary design

    Query params:
    - `trip_id` required
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TripAgentMessageListQuerySerializer

    def get(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        trip = get_object_or_404(self.get_trip_queryset(), pk=serializer.validated_data["trip_id"])
        if trip.is_itinerary_design_complete:
            saved_itinerary = self._get_saved_itinerary(trip)
            if saved_itinerary:
                return APIResponse.success(
                    data=self._serialize_saved_itinerary(saved_itinerary),
                    message="Trip itinerary fetched successfully.",
                )

        recommendations = (trip.agent_context or {}).get("recommendations")
        if not recommendations or not recommendations.get("is_discovery_complete"):
            return APIResponse.error(
                message="Generate trip recommendations before requesting an itinerary.",
                status=status.HTTP_400_BAD_REQUEST,
            )

        trip_context = build_itinerary_planning_context(trip)

        session = get_or_create_agent_conversation_session(trip, request.user, current_step=4)
        create_agent_message(
            session=session,
            sender=AgentMessageSender.USER,
            content="Generate trip itinerary.",
            payload={
                "trip_context": trip_context,
            },
            user=request.user,
        )

        plan_agent_response = run_plan_agent_for_session(
            session=session,
            user_query=build_itinerary_agent_query(trip_context),
            preferences=trip.preferences or {},
            trip_snapshot=trip_context,
            trip_context=trip_context,
        )
        itinerary = update_trip_agent_context_from_itinerary(
            trip,
            plan_agent_response,
            session,
            request.user,
        )

        create_agent_message(
            session=session,
            sender=AgentMessageSender.AGENT,
            content=itinerary.get("message", ""),
            payload={
                "itinerary": itinerary,
                "cost": plan_agent_response.get("cost"),
                "total_tokens": plan_agent_response.get("total_tokens"),
                "intention": plan_agent_response.get("intention"),
            },
            user=request.user,
        )

        if not itinerary.get("is_itinerary_complete"):
            return APIResponse.error(
                errors=itinerary,
                message="Trip agent itinerary could not be generated.",
                status=status.HTTP_502_BAD_GATEWAY,
            )

        saved_itinerary = self._get_saved_itinerary(trip)
        return APIResponse.success(
            data=self._serialize_saved_itinerary(saved_itinerary) if saved_itinerary else itinerary,
            message="Trip itinerary created successfully.",
        )

    def _get_saved_itinerary(self, trip):
        try:
            return (
                TripItinerary.objects.prefetch_related(
                    "route_plan_items",
                    "itinerary_days__day_items",
                )
                .select_related("rough_budget")
                .get(trip=trip)
            )
        except TripItinerary.DoesNotExist:
            return None

    def _serialize_saved_itinerary(self, itinerary):
        return {
            "id": str(itinerary.id),
            "title": itinerary.title,
            "summary": itinerary.summary,
            "message": itinerary.message,
            "session_id": itinerary.session_id,
            "is_finalized": itinerary.is_finalized,
            "route_plan_items": [
                self._serialize_route_plan_item(item)
                for item in itinerary.route_plan_items.all()
            ],
            "itinerary_days": [
                self._serialize_itinerary_day(day)
                for day in itinerary.itinerary_days.all()
            ],
            "rough_budget": self._serialize_itinerary_budget(getattr(itinerary, "rough_budget", None)),
            "metadata": itinerary.metadata or {},
        }

    def _serialize_route_plan_item(self, item):
        return {
            "id": item.id,
            "date": item.date.isoformat() if item.date else None,
            "notes": item.notes,
            "to_point": item.to_point,
            "from_point": item.from_point,
            "start_time": item.start_time.isoformat() if item.start_time else None,
            "transport_mode": item.transport_mode,
            "estimated_cost": str(item.estimated_cost) if item.estimated_cost is not None else None,
            "estimated_duration": str(item.estimated_duration) if item.estimated_duration else None,
        }

    def _serialize_itinerary_day(self, day):
        return {
            "id": day.id,
            "day": day.day,
            "date": day.date.isoformat() if day.date else None,
            "title": day.title,
            "summary": day.summary,
            "day_items": [
                self._serialize_itinerary_day_item(item)
                for item in day.day_items.all()
            ],
        }

    def _serialize_itinerary_day_item(self, item):
        return {
            "id": item.id,
            "time": item.time.isoformat() if item.time else None,
            "notes": item.notes,
            "title": item.title,
            "item_id": str(item.item_id) if item.item_id else None,
            "item_type": item.item_type,
            "description": item.description,
            "estimated_cost": str(item.estimated_cost) if item.estimated_cost is not None else None,
        }

    def _serialize_itinerary_budget(self, budget):
        if not budget:
            return None
        return {
            "id": str(budget.id),
            "transport": str(budget.transport) if budget.transport is not None else None,
            "food": str(budget.food) if budget.food is not None else None,
            "activities": str(budget.activities) if budget.activities is not None else None,
            "tickets_or_entry": str(budget.tickets_or_entry) if budget.tickets_or_entry is not None else None,
            "miscellaneous": str(budget.miscellaneous) if budget.miscellaneous is not None else None,
            "total_estimated_budget": (
                str(budget.total_estimated_budget)
                if budget.total_estimated_budget is not None
                else None
            ),
            "budget_note": budget.budget_note,
            "metadata": budget.metadata or {},
        }


class TripPlanningPrepartionAPIView(UserTripQuerysetMixin, GenericAPIView):
    """
    Get trip preparation guide

    Query params:
    - `trip_id` required
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TripAgentMessageListQuerySerializer

    def get(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        trip = get_object_or_404(self.get_trip_queryset(), pk=serializer.validated_data["trip_id"])
        if trip.is_trip_preparation_complete:
            saved_preparation = self._get_saved_preparation(trip)
            if saved_preparation:
                return APIResponse.success(
                    data=self._serialize_saved_preparation(saved_preparation),
                    message="Trip preparation fetched successfully.",
                )

        trip_context = build_itinerary_planning_context(trip)

        session = get_or_create_agent_conversation_session(trip, request.user, current_step=5)
        create_agent_message(
            session=session,
            sender=AgentMessageSender.USER,
            content="Generate trip preparation.",
            payload={
                "trip_context": trip_context,
            },
            user=request.user,
        )

        plan_agent_response = run_plan_agent_for_session(
            session=session,
            user_query=build_preparation_agent_query(trip_context),
            preferences=trip.preferences or {},
            trip_snapshot=trip_context,
            trip_context=trip_context,
        )
        preparation = update_trip_agent_context_from_preparation(
            trip,
            plan_agent_response,
            session,
            request.user,
        )

        create_agent_message(
            session=session,
            sender=AgentMessageSender.AGENT,
            content=preparation.get("message", ""),
            payload={
                "trip_preparation": preparation,
                "cost": plan_agent_response.get("cost"),
                "total_tokens": plan_agent_response.get("total_tokens"),
                "intention": plan_agent_response.get("intention"),
            },
            user=request.user,
        )

        if not preparation.get("is_preparation_complete"):
            return APIResponse.error(
                errors=preparation,
                message="Trip agent preparation could not be generated.",
                status=status.HTTP_502_BAD_GATEWAY,
            )

        saved_preparation = self._get_saved_preparation(trip)
        return APIResponse.success(
            data=self._serialize_saved_preparation(saved_preparation) if saved_preparation else preparation,
            message="Trip preparation created successfully.",
        )

    def _get_saved_preparation(self, trip):
        try:
            return (
                TripPreparation.objects.prefetch_related(
                    "packing_items",
                    "required_documents",
                    "heads_up",
                )
                .get(trip=trip)
            )
        except TripPreparation.DoesNotExist:
            return None

    def _serialize_saved_preparation(self, preparation):
        return {
            "id": str(preparation.id),
            "title": preparation.title,
            "summary": preparation.summary,
            "message": preparation.message,
            "is_finalized": preparation.is_finalized,
            "session_id": preparation.session_id,
            "packing_items": [
                self._serialize_packing_item(item)
                for item in preparation.packing_items.all()
            ],
            "required_documents": [
                self._serialize_required_document(item)
                for item in preparation.required_documents.all()
            ],
            "heads_up": [
                self._serialize_heads_up(item)
                for item in preparation.heads_up.all()
            ],
            "metadata": preparation.metadata or {},
        }

    def _serialize_packing_item(self, item):
        return {
            "id": str(item.id),
            "item": item.item,
            "quantity": item.quantity,
            "category": item.category,
            "priority": item.priority,
            "sort_order": item.sort_order,
            "additional_notes": item.additional_notes,
        }

    def _serialize_required_document(self, item):
        return {
            "id": str(item.id),
            "document_name": item.document_name,
            "document_url": item.document_url,
            "document_url_public_id": item.document_url_public_id,
            "required_level": item.required_level,
            "sort_order": item.sort_order,
            "additional_note": item.additional_note,
        }

    def _serialize_heads_up(self, item):
        return {
            "id": str(item.id),
            "title": item.title,
            "category": item.category,
            "severity": item.severity,
            "sort_order": item.sort_order,
            "additional_note": item.additional_note,
        }


class TripPlanningOverviewAPIView(UserTripQuerysetMixin, GenericAPIView):
    """
    Get a bird's-eye planning overview.

    Query params:
    - `trip_id` required
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TripAgentMessageListQuerySerializer

    def get(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        trip = get_object_or_404(self.get_trip_queryset(), pk=serializer.validated_data["trip_id"])
        overview = self._build_overview(trip)

        return APIResponse.success(
            data=overview,
            message="Trip planning overview fetched successfully.",
        )

    def _build_overview(self, trip):
        agent_context = trip.agent_context or {}
        recommendations = agent_context.get("recommendations") or {}
        itinerary = agent_context.get("itinerary_design") or {}
        preparation = agent_context.get("trip_preparation") or {}

        destinations = [
            {
                "id": str(trip_destination.destination.id),
                "name": trip_destination.destination.name,
                "country": trip_destination.destination.country,
                "is_primary": trip_destination.is_primary,
            }
            for trip_destination in getattr(trip, "prefetched_trip_destinations", [])
        ]

        day_wise_plan = itinerary.get("day_wise_plan") if isinstance(itinerary.get("day_wise_plan"), list) else []
        route_plan = itinerary.get("route_plan") if isinstance(itinerary.get("route_plan"), list) else []
        rough_budget = itinerary.get("rough_budget") if isinstance(itinerary.get("rough_budget"), dict) else {}

        planning_progress = {
            "current_step": trip.current_step,
            "is_qna_complete": bool((agent_context.get("preference_qna") or {}).get("context")),
            "is_recommendation_complete": trip.is_recommendation_complete
            or bool(recommendations.get("is_discovery_complete")),
            "is_itinerary_complete": bool(itinerary.get("is_itinerary_complete")),
            "is_preparation_complete": bool(preparation.get("is_preparation_complete")),
        }
        can_activate = (
            trip.status in {TripStatus.DRAFT, TripStatus.PLANNING}
            and planning_progress["is_itinerary_complete"]
            and planning_progress["is_preparation_complete"]
        )

        return {
            "trip": {
                "id": str(trip.id),
                "title": trip.title,
                "status": trip.status,
                "start_date": trip.start_date.isoformat() if trip.start_date else None,
                "end_date": trip.end_date.isoformat() if trip.end_date else None,
                "duration_days": trip.duration_days,
                "travelers_count": trip.travelers_count,
                "traveler_type": trip.traveler_type,
                "origin": {
                    "city": trip.origin_city,
                    "country": trip.origin_country,
                    "start_location": trip.start_location_address,
                },
                "budget": {
                    "amount": str(trip.total_budget) if trip.total_budget is not None else None,
                    "currency": trip.budget_currency,
                },
            },
            "destinations": destinations,
            "planning_progress": planning_progress,
            "recommendations_overview": {
                "attractions_count": len(
                    recommendations.get("attraction_ids") or recommendations.get("tour_spot_ids") or []
                ),
                "activities_count": len(recommendations.get("activity_ids") or []),
                "cuisines_count": len(
                    recommendations.get("cuisine_ids") or recommendations.get("food_item_ids") or []
                ),
            },
            "itinerary_overview": {
                "title": itinerary.get("title", ""),
                "summary": itinerary.get("summary", ""),
                "days_count": len(day_wise_plan),
                "route_legs_count": len(route_plan),
                "total_estimated_budget": rough_budget.get("total_estimated_budget"),
                "budget_note": rough_budget.get("budget_note"),
            },
            "preparation_overview": {
                "title": preparation.get("title", ""),
                "summary": preparation.get("summary", ""),
                "packing_items_count": len(preparation.get("packing_items") or []),
                "documents_count": len(preparation.get("required_documents") or []),
                "heads_up_count": len(preparation.get("heads_up") or []),
            },
            "activation": {
                "can_activate": can_activate,
                "target_status": TripStatus.READY.value,
                "blocking_steps": self._activation_blocking_steps(trip, planning_progress),
            },
        }

    def _activation_blocking_steps(self, trip, planning_progress):
        blocking_steps = []
        if trip.status not in {TripStatus.DRAFT, TripStatus.PLANNING}:
            blocking_steps.append("Trip status must be draft or planning.")
        if not planning_progress["is_itinerary_complete"]:
            blocking_steps.append("Generate the trip itinerary.")
        if not planning_progress["is_preparation_complete"]:
            blocking_steps.append("Generate the trip preparation checklist.")
        return blocking_steps


class ActivateTripPlanAPIView(UserTripQuerysetMixin, GenericAPIView):
    """
    Mark a completed draft/planning trip plan as ready.

    Body:
    - `trip_id` required
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TripAgentMessageListQuerySerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        trip = get_object_or_404(self.get_trip_queryset(), pk=serializer.validated_data["trip_id"])
        agent_context = trip.agent_context or {}
        itinerary = agent_context.get("itinerary_design") or {}
        preparation = agent_context.get("trip_preparation") or {}

        if trip.status == TripStatus.READY:
            return APIResponse.success(
                data={
                    "id": str(trip.id),
                    "status": trip.status,
                    "current_step": trip.current_step,
                },
                message="Trip plan is already active.",
            )

        if trip.status not in {TripStatus.DRAFT, TripStatus.PLANNING}:
            return APIResponse.error(
                message="Only draft or planning trips can be activated.",
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not itinerary.get("is_itinerary_complete"):
            return APIResponse.error(
                message="Generate trip itinerary before activating the plan.",
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not preparation.get("is_preparation_complete"):
            return APIResponse.error(
                message="Generate trip preparation before activating the plan.",
                status=status.HTTP_400_BAD_REQUEST,
            )

        trip.status = TripStatus.READY
        trip.current_step = max(trip.current_step, 6)
        trip.updated_by = request.user
        trip.save(update_fields=["status", "current_step", "updated_by", "updated_at"])

        return APIResponse.success(
            data={
                "id": str(trip.id),
                "status": trip.status,
                "current_step": trip.current_step,
            },
            message="Trip plan activated successfully.",
        )
