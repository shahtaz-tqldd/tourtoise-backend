from django.shortcuts import get_object_or_404
from uuid import UUID
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated

from app.utils.response import APIResponse
from accounts.choices import CreditTransactionType
from accounts.services.credit import CreditService, InsufficientCreditsError
from analytics.choices import AIUsageType
from analytics.services.ai_usage import record_ai_usage
from destinations.api.v1.client.serializers import (
    ClientActivitySerializer,
    ClientAttractionSerializer,
    ClientCuisineSerializer,
)
from destinations.models import Activity, Attraction, Cuisine
from trips.api.v1.client.serializers import (
    TripAgentActiveSerializer,
    TripAgentCreateMessageSerializer,
    TripAgentMessageSerializer,
    TripPlanningTripQuerySerializer,
)
from trips.choices import AgentMessageSender, TripStatus, PlanningStep
from trips.models import (
    TripAgentMessage,
    TripItinerary,
    TripPlanningStepSession,
    TripPreparation,
    TripRecommendations,
)
from trips.services.notifications import schedule_trip_notifications
from trips.services.services import (
    build_final_preference_agent_query,
    build_initial_agent_query,
    build_itinerary_agent_query,
    build_itinerary_planning_context,
    build_planning_response_meta,
    build_preparation_agent_query,
    build_recommendations_agent_query,
    build_trip_snapshot,
    create_agent_message,
    get_activation_blocking_errors,
    get_or_create_conversation_session,
    get_or_create_planning_session,
    get_or_create_planning_step_session,
    finalize_preference_response,
    get_step_blocking_errors,
    get_trip_planning_flow,
    get_trip_planning_progress,
    normalize_initial_preference_response,
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


def insufficient_credits_response(exc):
    return APIResponse.error(
        errors={"credit": [str(exc)]},
        message="Insufficient credits.",
        status=status.HTTP_402_PAYMENT_REQUIRED,
    )


def preflight_agent_credits(user, amount):
    try:
        CreditService.ensure_credits(user=user, amount=amount)
    except InsufficientCreditsError as exc:
        return insufficient_credits_response(exc)
    return None


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

        credit_error = preflight_agent_credits(
            request.user,
            CreditService.PREFERENCE_QUESTION_COST,
        )
        if credit_error:
            return credit_error

        normalized_payload = serializer.normalized_preferences()

        trip_snapshot = build_trip_snapshot(trip)

        try:
            with CreditService.charge_agent_generation(
                user=request.user,
                amount=CreditService.PREFERENCE_QUESTION_COST,
                transaction_type=CreditTransactionType.TRIP_PLAN,
                description="Trip preference question generation",
                metadata={"step": PlanningStep.PREFERENCE, "trip_id": str(trip.id)},
            ):
                session = get_or_create_planning_step_session(
                    trip,
                    request.user,
                    step=PlanningStep.PREFERENCE,
                )

                create_agent_message(
                    session=session,
                    sender=AgentMessageSender.SYSTEM,
                    content="Trip planning",
                    metadata={
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
        except InsufficientCreditsError as exc:
            return insufficient_credits_response(exc)
        plan_agent_response = normalize_initial_preference_response(
            plan_agent_response,
            normalized_payload,
            trip_snapshot,
        )
        qna_response = plan_agent_response["response"]
        agent_message = qna_response.get("question") or qna_response.get("context") or ""

        create_agent_message(
            session=session,
            sender=AgentMessageSender.AGENT,
            content=agent_message,
            metadata={
                "cost": plan_agent_response.get("cost"),
                "total_tokens": plan_agent_response.get("total_tokens"),
            },
            user=request.user,
        )

        preferences = {
            "session_id": str(session.id),
            **normalized_payload,
        }
        trip.preferences = preferences
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

        update_user_profile_from_agent_preferences(request.user, normalized_payload)
        is_step_complete = update_trip_agent_context_from_qna(
            trip,
            plan_agent_response,
            session,
            request.user,
        )
        trip.refresh_from_db(fields=[
            "metadata",
            "current_step",
            "is_qna_complete",
            "updated_at",
        ])

        return APIResponse.success(
            data={
                "planning_session_id": str(session.planning_session_id),
                "session_id": str(session.id),
                "agent_active": trip.agent_active,
                "preferences": preferences,
                "agent_message": agent_message,
                "is_step_complete": is_step_complete,
                "is_qna_complete": is_step_complete,
                "progress": get_trip_planning_progress(trip),
                "flow": get_trip_planning_flow(trip),
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

        if get_trip_planning_progress(trip)["is_qna_complete"]:
            return APIResponse.error(
                message="Preference Q&A is already complete for this trip.",
                status=status.HTTP_400_BAD_REQUEST,
            )

        credit_error = preflight_agent_credits(
            request.user,
            CreditService.PREFERENCE_QUESTION_COST,
        )
        if credit_error:
            return credit_error

        session_id = serializer.validated_data.get("session_id")
        if session_id:
            session = get_object_or_404(
                TripPlanningStepSession.objects.filter(
                    trip=trip,
                    user=request.user,
                    step=PlanningStep.PREFERENCE,
                    is_active=True,
                ),
                pk=session_id,
            )
        else:
            session = get_or_create_planning_step_session(
                trip,
                request.user,
                step=PlanningStep.PREFERENCE,
            )

        try:
            preferences = trip.preferences or {}
            trip_snapshot = build_trip_snapshot(trip)
            answer = serializer.validated_data["message"]
            with CreditService.charge_agent_generation(
                user=request.user,
                amount=CreditService.PREFERENCE_QUESTION_COST,
                transaction_type=CreditTransactionType.TRIP_PLAN,
                description="Trip preference question generation",
                metadata={"step": PlanningStep.PREFERENCE, "trip_id": str(trip.id)},
            ):
                create_agent_message(
                    session=session,
                    sender=AgentMessageSender.USER,
                    content=answer,
                    user=request.user,
                )

                plan_agent_response = run_plan_agent_for_session(
                    session=session,
                    user_query=build_final_preference_agent_query(
                        answer,
                        preferences,
                        trip_snapshot,
                    ),
                    preferences=preferences,
                    trip_snapshot=trip_snapshot,
                )
        except InsufficientCreditsError as exc:
            return insufficient_credits_response(exc)
        plan_agent_response = finalize_preference_response(
            plan_agent_response,
            answer,
            preferences,
            trip_snapshot,
        )
        qna_response = plan_agent_response["response"]
        agent_message = qna_response.get("question", None)
        system_message = qna_response.get("context", None)

        content = agent_message or system_message or ""
        sender = AgentMessageSender.AGENT if agent_message else AgentMessageSender.SYSTEM

        create_agent_message(
            session=session,
            sender=sender,
            content=content,
            metadata={
                "cost": plan_agent_response.get("cost"),
                "total_tokens": plan_agent_response.get("total_tokens"),
            },
            user=request.user,
        )

        trip.updated_by = request.user
        trip.save(update_fields=["updated_by", "updated_at"])
        is_step_complete = update_trip_agent_context_from_qna(
            trip,
            plan_agent_response,
            session,
            request.user,
        )

        return APIResponse.success(
            data={
                "planning_session_id": str(session.planning_session_id),
                "session_id": str(session.id),
                "agent_message": content,
                "is_step_complete": is_step_complete,
                "is_qna_complete": is_step_complete,
                "progress": get_trip_planning_progress(trip),
                "flow": get_trip_planning_flow(trip),
            },
            message="Trip agent message created successfully.",
        )


class TripPlanningRecommendationsAPIView(UserTripQuerysetMixin, GenericAPIView):
    """
    Get trip recommendations
    Query params:
    - `trip_id` required
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TripPlanningTripQuerySerializer

    def get(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        trip = get_object_or_404(self.get_trip_queryset(), pk=serializer.validated_data["trip_id"])
        blocking_errors = get_step_blocking_errors(trip, PlanningStep.RECOMMENDATION)
        if blocking_errors:
            return APIResponse.error(
                errors={"blocking_steps": blocking_errors},
                message=blocking_errors[0],
                status=status.HTTP_400_BAD_REQUEST,
            )

        progress = get_trip_planning_progress(trip)
        if progress["is_recommendation_complete"]:
            saved_recommendations = self._get_saved_recommendations(trip)
            if saved_recommendations:
                return APIResponse.success(
                    data={
                        **self._serialize_saved_recommendations(saved_recommendations),
                        **build_planning_response_meta(trip),
                    },
                    message="Trip recommendations fetched successfully.",
                )

            existing_recommendations = (trip.metadata or {}).get("recommendations")
            if existing_recommendations and existing_recommendations.get("is_discovery_complete"):
                return APIResponse.success(
                    data={
                        **self._serialize_recommendations(existing_recommendations),
                        **build_planning_response_meta(trip),
                    },
                    message="Trip recommendations fetched successfully.",
                )

        trip_destination = self._get_recommendation_destination(trip)
        if not trip_destination:
            return APIResponse.error(
                message="Add a destination to this trip before requesting recommendations.",
                status=status.HTTP_400_BAD_REQUEST,
            )

        credit_error = preflight_agent_credits(
            request.user,
            CreditService.RECOMMENDATION_COST,
        )
        if credit_error:
            return credit_error

        destination_id = str(trip_destination.destination_id)
        trip_snapshot = build_trip_snapshot(trip)
        preferences = {
            "trip_preferences": trip.preferences or {},
            "preference_context": (trip.metadata or {}).get("preference_qna", {}).get("context"),
        }

        try:
            with CreditService.charge_agent_generation(
                user=request.user,
                amount=CreditService.RECOMMENDATION_COST,
                transaction_type=CreditTransactionType.TRIP_PLAN,
                description="Trip recommendation generation",
                metadata={"step": PlanningStep.RECOMMENDATION, "trip_id": str(trip.id)},
            ) as credit_transaction:
                session = get_or_create_planning_step_session(trip, request.user, current_step=3)
                create_agent_message(
                    session=session,
                    sender=AgentMessageSender.USER,
                    content="Generate trip recommendations.",
                    metadata={
                        "destination_id": destination_id,
                        "preferences": preferences,
                        "trip_snapshot": trip_snapshot,
                    },
                    user=request.user,
                )

                plan_agent_response = run_plan_agent_for_session(
                    session=session,
                    user_query=build_recommendations_agent_query(
                        preferences,
                        trip_snapshot,
                        destination_id,
                    ),
                    preferences=preferences,
                    trip_snapshot=trip_snapshot,
                    destination_id=destination_id,
                )
                record_ai_usage(
                    user=request.user,
                    trip=trip,
                    usage_type=AIUsageType.TRIP_PLANNING,
                    cost=plan_agent_response.get("cost") or 0,
                    tokens=plan_agent_response.get("total_tokens") or 0,
                )
            credit_spent = abs(credit_transaction.amount) if credit_transaction else 0
        except InsufficientCreditsError as exc:
            return insufficient_credits_response(exc)
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
            metadata={
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
                meta={"credit_spent": credit_spent},
            )

        return APIResponse.success(
            data={
                **self._serialize_recommendations(recommendations),
                **build_planning_response_meta(trip),
            },
            meta={"credit_spent": credit_spent},
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
        activity_ids = self._recommendation_ids(recommendations, "activity")
        cuisine_ids = self._recommendation_ids(recommendations, "cuisine")
        return {
            "is_recommendation_complete": recommendations.get("is_discovery_complete", False),
            "attractions": self._serialize_items(
                Attraction.objects.filter(id__in=attraction_ids).prefetch_related("images"),
                attraction_ids,
                ClientAttractionSerializer,
            ),
            "activities": self._serialize_items(
                Activity.objects.filter(id__in=activity_ids).prefetch_related("images"),
                activity_ids,
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
            "session_id": (recommendations.metadata or {}).get("session_id"),
            "external_session_id": recommendations.external_session_id,
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
            return self._valid_uuid_strings(
                recommendations.get("attraction_ids") or recommendations.get("tour_spot_ids") or []
            )
        if item_type == "cuisine":
            return self._valid_uuid_strings(
                recommendations.get("cuisine_ids") or recommendations.get("food_item_ids") or []
            )
        return self._valid_uuid_strings(recommendations.get(f"{item_type}_ids") or [])

    def _serialize_items(self, queryset, selected_ids, serializer_class):
        item_map = {str(item.id): item for item in queryset}
        ordered_items = [item_map[str(item_id)] for item_id in selected_ids if str(item_id) in item_map]
        return serializer_class(ordered_items, many=True, context={"request": self.request}).data

    def _valid_uuid_strings(self, values):
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


class TripPlanningItinerariesAPIView(UserTripQuerysetMixin, GenericAPIView):
    """
    Get trip itinerary design

    Query params:
    - `trip_id` required
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TripPlanningTripQuerySerializer

    def get(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        trip = get_object_or_404(self.get_trip_queryset(), pk=serializer.validated_data["trip_id"])
        blocking_errors = get_step_blocking_errors(trip, PlanningStep.ITINERARY)
        if blocking_errors:
            return APIResponse.error(
                errors={"blocking_steps": blocking_errors},
                message=blocking_errors[0],
                status=status.HTTP_400_BAD_REQUEST,
            )

        progress = get_trip_planning_progress(trip)
        if progress["is_itinerary_design_complete"]:
            saved_itinerary = self._get_saved_itinerary(trip)
            if saved_itinerary:
                return APIResponse.success(
                    data={
                        **self._serialize_saved_itinerary(saved_itinerary),
                        **build_planning_response_meta(trip),
                    },
                    message="Trip itinerary fetched successfully.",
                )

        recommendations = (trip.metadata or {}).get("recommendations")
        if not recommendations or not recommendations.get("is_discovery_complete"):
            return APIResponse.error(
                message="Generate trip recommendations before requesting an itinerary.",
                status=status.HTTP_400_BAD_REQUEST,
            )

        credit_error = preflight_agent_credits(
            request.user,
            CreditService.ITINERARY_COST,
        )
        if credit_error:
            return credit_error

        trip_context = build_itinerary_planning_context(trip)

        try:
            with CreditService.charge_agent_generation(
                user=request.user,
                amount=CreditService.ITINERARY_COST,
                transaction_type=CreditTransactionType.TRIP_PLAN,
                description="Trip itinerary generation",
                metadata={"step": PlanningStep.ITINERARY, "trip_id": str(trip.id)},
            ) as credit_transaction:
                session = get_or_create_planning_step_session(trip, request.user, current_step=4)
                create_agent_message(
                    session=session,
                    sender=AgentMessageSender.USER,
                    content="Generate trip itinerary.",
                    metadata={
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
                record_ai_usage(
                    user=request.user,
                    trip=trip,
                    usage_type=AIUsageType.TRIP_PLANNING,
                    cost=plan_agent_response.get("cost") or 0,
                    tokens=plan_agent_response.get("total_tokens") or 0,
                )
            credit_spent = abs(credit_transaction.amount) if credit_transaction else 0
        except InsufficientCreditsError as exc:
            return insufficient_credits_response(exc)
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
            metadata={
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
                meta={"credit_spent": credit_spent},
            )

        saved_itinerary = self._get_saved_itinerary(trip)
        return APIResponse.success(
            data={
                **(self._serialize_saved_itinerary(saved_itinerary) if saved_itinerary else itinerary),
                **build_planning_response_meta(trip),
            },
            meta={"credit_spent": credit_spent},
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
            "session_id": (itinerary.metadata or {}).get("session_id"),
            "external_session_id": itinerary.external_session_id,
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
    serializer_class = TripPlanningTripQuerySerializer

    def get(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        trip = get_object_or_404(self.get_trip_queryset(), pk=serializer.validated_data["trip_id"])
        blocking_errors = get_step_blocking_errors(trip, PlanningStep.PREPARATION)
        if blocking_errors:
            return APIResponse.error(
                errors={"blocking_steps": blocking_errors},
                message=blocking_errors[0],
                status=status.HTTP_400_BAD_REQUEST,
            )

        progress = get_trip_planning_progress(trip)
        if progress["is_trip_preparation_complete"]:
            saved_preparation = self._get_saved_preparation(trip)
            if saved_preparation:
                return APIResponse.success(
                    data={
                        **self._serialize_saved_preparation(saved_preparation),
                        **build_planning_response_meta(trip),
                    },
                    message="Trip preparation fetched successfully.",
                )

        credit_error = preflight_agent_credits(
            request.user,
            CreditService.PREPARATION_COST,
        )
        if credit_error:
            return credit_error

        trip_context = build_itinerary_planning_context(trip)

        try:
            with CreditService.charge_agent_generation(
                user=request.user,
                amount=CreditService.PREPARATION_COST,
                transaction_type=CreditTransactionType.TRIP_PLAN,
                description="Trip preparation generation",
                metadata={"step": PlanningStep.PREPARATION, "trip_id": str(trip.id)},
            ) as credit_transaction:
                session = get_or_create_planning_step_session(trip, request.user, current_step=5)
                create_agent_message(
                    session=session,
                    sender=AgentMessageSender.USER,
                    content="Generate trip preparation.",
                    metadata={
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
                record_ai_usage(
                    user=request.user,
                    trip=trip,
                    usage_type=AIUsageType.TRIP_PLANNING,
                    cost=plan_agent_response.get("cost") or 0,
                    tokens=plan_agent_response.get("total_tokens") or 0,
                )
            credit_spent = abs(credit_transaction.amount) if credit_transaction else 0
        except InsufficientCreditsError as exc:
            return insufficient_credits_response(exc)
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
            metadata={
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
                meta={"credit_spent": credit_spent},
            )

        saved_preparation = self._get_saved_preparation(trip)
        return APIResponse.success(
            data={
                **(self._serialize_saved_preparation(saved_preparation) if saved_preparation else preparation),
                **build_planning_response_meta(trip),
            },
            meta={"credit_spent": credit_spent},
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
            "session_id": (preparation.metadata or {}).get("session_id"),
            "external_session_id": preparation.external_session_id,
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
            "document": (
                {
                    "file_name": item.document_file_name,
                    "url": item.document_url,
                    "public_id": item.document_url_public_id,
                }
                if item.document_url
                else None
            ),
            "document_file_name": item.document_file_name,
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
    serializer_class = TripPlanningTripQuerySerializer

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
        agent_context = trip.metadata or {}
        recommendations = (
            agent_context.get("recommendations")
            if isinstance(agent_context.get("recommendations"), dict)
            else {}
        )
        itinerary = (
            agent_context.get("itinerary_design")
            if isinstance(agent_context.get("itinerary_design"), dict)
            else {}
        )
        preparation = (
            agent_context.get("trip_preparation")
            if isinstance(agent_context.get("trip_preparation"), dict)
            else {}
        )

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
        progress = get_trip_planning_progress(trip)

        planning_progress = {
            "current_step": trip.current_step,
            "is_qna_complete": progress["is_qna_complete"],
            "is_recommendation_complete": progress["is_recommendation_complete"],
            "is_itinerary_complete": progress["is_itinerary_design_complete"],
            "is_preparation_complete": progress["is_trip_preparation_complete"],
        }
        activation_blocking_steps = get_activation_blocking_errors(trip)
        can_activate = not activation_blocking_steps

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
                    "tier": trip.budget_tier,
                    "currency": trip.budget_currency,
                },
            },
            "destinations": destinations,
            "planning_progress": planning_progress,
            "flow": get_trip_planning_flow(trip),
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
                "blocking_steps": activation_blocking_steps,
            },
        }

    def _activation_blocking_steps(self, trip, planning_progress):
        return get_activation_blocking_errors(trip)


class TripPlanningAPIView(
    TripPaginationMixin,
    TripPlanningRecommendationsAPIView,
    TripPlanningItinerariesAPIView,
    TripPlanningPrepartionAPIView,
    TripPlanningOverviewAPIView,
):
    """
    Get trip planning data by step.

    Query params:
    - `trip_id` required
    - `step` -> "preference"|"recommendation"|"itinerary"|"preparation"|"overview" required
    - `session_id` optional for `step=preference`
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TripPlanningTripQuerySerializer

    def get(self, request, *args, **kwargs):
        step = request.query_params.get("step")
        if step not in {
            PlanningStep.PREFERENCE,
            PlanningStep.RECOMMENDATION,
            PlanningStep.ITINERARY,
            PlanningStep.PREPARATION,
            PlanningStep.OVERVIEW,
        }:
            return APIResponse.error(
                message="Valid step is required.",
                errors={
                    "step": [
                        "Use one of: preference, recommendation, itinerary, preparation, overview."
                    ]
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        if step == PlanningStep.PREFERENCE:
            return self._get_preference_messages(request)
        if step == PlanningStep.RECOMMENDATION:
            return TripPlanningRecommendationsAPIView.get(self, request, *args, **kwargs)
        if step == PlanningStep.ITINERARY:
            return TripPlanningItinerariesAPIView.get(self, request, *args, **kwargs)
        if step == PlanningStep.PREPARATION:
            return TripPlanningPrepartionAPIView.get(self, request, *args, **kwargs)
        return TripPlanningOverviewAPIView.get(self, request, *args, **kwargs)

    def _get_preference_messages(self, request):
        serializer = self.get_serializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)

        trip = get_object_or_404(self.get_trip_queryset(), pk=serializer.validated_data["trip_id"])
        sessions = TripPlanningStepSession.objects.filter(
            trip=trip,
            user=request.user,
            step=PlanningStep.PREFERENCE,
        ).order_by("-updated_at")

        session_id = request.query_params.get("session_id")
        if session_id:
            sessions = sessions.filter(pk=session_id)

        session = sessions.first()
        if not session:
            return APIResponse.success(
                data={
                    "session": None,
                    "messages": [],
                    "preferences": trip.preferences or {},
                },
                message="Trip preference messages fetched successfully.",
            )

        messages = TripAgentMessage.objects.filter(session=session).order_by("created_at")
        preference = trip.preferences
        agent_active = trip.agent_active
        is_step_complete = trip.is_qna_complete
        is_recommendation_complete = trip.is_recommendation_complete
        
        return APIResponse.success(
            data={
                **preference,
                "session": {
                    "id": str(session.id),
                    "planning_session_id": str(session.planning_session_id),
                    "step": session.step,
                    "is_active": session.is_active,
                    "external_session_id": session.external_session_id,
                },
                "preferences": preference or {},
                "agent_active": agent_active,
                "is_step_complete": is_step_complete,
                "is_qna_complete": is_step_complete,
                "is_recommendation_complete": is_recommendation_complete,
                "messages": TripAgentMessageSerializer(messages, many=True).data,
                "progress": get_trip_planning_progress(trip),
                "flow": get_trip_planning_flow(trip),
            },
            message="Trip preference messages fetched successfully.",
        )


class ActivateTripPlanAPIView(UserTripQuerysetMixin, GenericAPIView):
    """
    Mark a completed draft/planning trip plan as ready.

    Body:
    - `trip_id` required
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TripPlanningTripQuerySerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        trip = get_object_or_404(self.get_trip_queryset(), pk=serializer.validated_data["trip_id"])
        if trip.status == TripStatus.READY:
            conversation_session = get_or_create_conversation_session(
                trip, request.user, plan_ready=True
            )
            schedule_trip_notifications(trip, request.user)
            return APIResponse.success(
                data={
                    "id": str(trip.id),
                    "status": trip.status,
                    "current_step": trip.current_step,
                    "conversation_session_id": str(conversation_session.id),
                },
                message="Trip plan is already active.",
            )

        blocking_errors = get_activation_blocking_errors(trip)
        if blocking_errors:
            return APIResponse.error(
                errors={"blocking_steps": blocking_errors},
                message=blocking_errors[0],
                status=status.HTTP_400_BAD_REQUEST,
            )

        trip.status = TripStatus.READY
        trip.current_step = PlanningStep.COMPLETED
        trip.updated_by = request.user
        trip.save(update_fields=["status", "current_step", "updated_by", "updated_at"])

        planning_session = get_or_create_planning_session(trip, request.user)
        planning_session.is_active = False
        planning_session.updated_by = request.user
        planning_session.save(update_fields=["is_active", "updated_by", "updated_at"])

        conversation_session = get_or_create_conversation_session(
            trip, request.user, plan_ready=True
        )
        schedule_trip_notifications(trip, request.user)

        return APIResponse.success(
            data={
                "id": str(trip.id),
                "status": trip.status,
                "current_step": trip.current_step,
                "conversation_session_id": str(conversation_session.id),
            },
            message="Trip plan activated successfully.",
        )
