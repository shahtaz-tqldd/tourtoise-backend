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
    run_plan_agent_for_session,
    update_trip_agent_context_from_qna,
    update_trip_agent_context_from_itinerary,
    update_trip_agent_context_from_preparation,
    update_trip_agent_context_from_recommendations,
    update_user_profile_from_agent_preferences,
)

from .mixin import UserTripQuerysetMixin, TripPaginationMixin


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

        trip.preferences = normalized_payload
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
        existing_recommendations = (trip.agent_context or {}).get("recommendations")
        if existing_recommendations:
            return APIResponse.success(
                data=self._serialize_recommendations(existing_recommendations),
                message="Trip agent recommendations fetched successfully.",
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
            content=recommendations.get("selection_instruction", ""),
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
            message="Trip agent recommendations created successfully.",
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
        return {
            "is_discovery_complete": recommendations.get("is_discovery_complete", False),
            "tour_spots": self._serialize_items(
                Attraction.objects.filter(id__in=recommendations.get("tour_spot_ids", [])).prefetch_related("images"),
                recommendations.get("tour_spot_ids", []),
                ClientAttractionSerializer,
            ),
            "activities": self._serialize_items(
                Activity.objects.filter(id__in=recommendations.get("activity_ids", [])).prefetch_related("images"),
                recommendations.get("activity_ids", []),
                ClientActivitySerializer,
            ),
            "food_items": self._serialize_items(
                Cuisine.objects.filter(id__in=recommendations.get("food_item_ids", [])).prefetch_related("images"),
                recommendations.get("food_item_ids", []),
                ClientCuisineSerializer,
            ),
            "messages": recommendations.get("messages", {}),
            "selection_instruction": recommendations.get("selection_instruction", ""),
            "session_id": recommendations.get("session_id"),
            "external_session_id": recommendations.get("external_session_id"),
        }

    def _serialize_items(self, queryset, selected_ids, serializer_class):
        item_map = {str(item.id): item for item in queryset}
        ordered_items = [item_map[item_id] for item_id in selected_ids if item_id in item_map]
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
        existing_itinerary = (trip.agent_context or {}).get("itinerary_design")
        if existing_itinerary:
            return APIResponse.success(
                data=existing_itinerary,
                message="Trip agent itinerary fetched successfully.",
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
            content=itinerary.get("message") or itinerary.get("revision_instruction", ""),
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

        return APIResponse.success(
            data=itinerary,
            message="Trip agent itinerary created successfully.",
        )


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
        existing_preparation = (trip.agent_context or {}).get("trip_preparation")
        if existing_preparation:
            return APIResponse.success(
                data=existing_preparation,
                message="Trip agent preparation fetched successfully.",
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
            content=preparation.get("message") or preparation.get("revision_instruction", ""),
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

        return APIResponse.success(
            data=preparation,
            message="Trip agent preparation created successfully.",
        )


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
            "is_recommendation_complete": bool(recommendations.get("is_discovery_complete")),
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
                "tour_spots_count": len(recommendations.get("tour_spot_ids") or []),
                "activities_count": len(recommendations.get("activity_ids") or []),
                "food_items_count": len(recommendations.get("food_item_ids") or []),
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
