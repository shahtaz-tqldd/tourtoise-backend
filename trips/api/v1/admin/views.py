from django.db.models import (
    BigIntegerField,
    Count,
    FloatField,
    OuterRef,
    Prefetch,
    Q,
    Subquery,
    Sum,
    Value,
)
from django.db.models.functions import Cast, Coalesce
from django.shortcuts import get_object_or_404
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated

from accounts.permissions import IsSuperAdmin
from app.base.pagination import CustomPagination
from app.utils.response import APIResponse
from trips.api.v1.admin.serializers import AdminTripDetailSerializer, AdminTripListSerializer
from trips.models import Trip, TripAgentMessage, TripConversationMessage, TripDestination


def _sum_message_metadata(queryset, *, trip_field, metadata_key, output_field):
    """Return one aggregate metadata value for the outer trip."""
    return Subquery(
        queryset.filter(**{trip_field: OuterRef("pk")})
        .order_by()
        .values(trip_field)
        .annotate(total=Sum(Cast(f"metadata__{metadata_key}", output_field=output_field)))
        .values("total")[:1],
        output_field=output_field,
    )


def _related_count(queryset, *, trip_field):
    return Subquery(
        queryset.filter(**{trip_field: OuterRef("pk")})
        .order_by()
        .values(trip_field)
        .annotate(total=Count("id"))
        .values("total")[:1],
        output_field=BigIntegerField(),
    )


class TripPaginationMixin:
    pagination_class = CustomPagination

    def paginate_with_meta(self, queryset, serializer_class):
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, self.request, view=self)
        serializer = serializer_class(page, many=True, context={"request": self.request})
        return APIResponse.success(
            data=serializer.data,
            meta={
                "count": paginator.page.paginator.count,
                "page": paginator.page.number,
                "page_size": paginator.get_page_size(self.request),
                "num_pages": paginator.page.paginator.num_pages,
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
            },
            message="Trips fetched successfully.",
        )


class AdminTripListAPIView(TripPaginationMixin, GenericAPIView):
    """
    Admin trip list API.

    Frontend request:
    - Method: GET
    - Headers: authenticated bearer token with superadmin access
    - Query params:
      `page`, `page_size`
      `search=summer`
      `status=draft,ready`
      `visibility=private,public`
      `planning_source=agent,hybrid`
      `user_email=traveler@example.com`
      `destination_name=Dhaka`
      `country=Bangladesh`
      `region=Asia`
    - Multiple filters can be combined.

    Frontend response:
    - 200 success with paginated trip rows for admin dashboards.
    - Each row includes planning and trip-chat cost/token totals, plus the number
      of persisted post-planning conversation messages.
    """

    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get_queryset(self):
        planning_messages = TripAgentMessage.objects.all()
        conversation_messages = TripConversationMessage.objects.all()
        float_output = FloatField()
        integer_output = BigIntegerField()

        queryset = (
            Trip.objects.select_related("user", "user__profile")
            .prefetch_related(
                Prefetch(
                    "trip_destinations",
                    queryset=TripDestination.objects.filter(is_primary=True).select_related(
                        "destination",
                    ),
                    to_attr="prefetched_primary_destinations",
                ),
            )
            .annotate(
                planning_cost=Coalesce(
                    _sum_message_metadata(
                        planning_messages,
                        trip_field="session__trip_id",
                        metadata_key="cost",
                        output_field=float_output,
                    ),
                    Value(0.0),
                    output_field=float_output,
                ),
                planning_total_tokens=Coalesce(
                    _sum_message_metadata(
                        planning_messages,
                        trip_field="session__trip_id",
                        metadata_key="total_tokens",
                        output_field=integer_output,
                    ),
                    Value(0),
                    output_field=integer_output,
                ),
                trip_chat_cost=Coalesce(
                    _sum_message_metadata(
                        conversation_messages,
                        trip_field="session__trip_id",
                        metadata_key="cost",
                        output_field=float_output,
                    ),
                    Value(0.0),
                    output_field=float_output,
                ),
                trip_chat_total_tokens=Coalesce(
                    _sum_message_metadata(
                        conversation_messages,
                        trip_field="session__trip_id",
                        metadata_key="total_tokens",
                        output_field=integer_output,
                    ),
                    Value(0),
                    output_field=integer_output,
                ),
                conversation_messages_count=Coalesce(
                    _related_count(
                        conversation_messages,
                        trip_field="session__trip_id",
                    ),
                    Value(0),
                    output_field=integer_output,
                ),
            )
            .order_by("-updated_at")
        )
        params = self.request.query_params

        search = params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(title__icontains=search)
                | Q(user__email__icontains=search)
                | Q(user__name__icontains=search)
                | Q(trip_destinations__destination__name__icontains=search)
            )

        statuses = self._get_multi_values("status")
        if statuses:
            queryset = queryset.filter(status__in=statuses)

        planning_sources = self._get_multi_values("planning_source")
        if planning_sources:
            queryset = queryset.filter(planning_source__in=planning_sources)

        user_email = params.get("user_email", "").strip()
        if user_email:
            queryset = queryset.filter(user__email__icontains=user_email)

        queryset = self._filter_by_destination_values(
            queryset,
            param_name="destination_name",
            destination_field="name",
        )
        queryset = self._filter_by_destination_values(
            queryset,
            param_name="country",
            destination_field="country",
        )
        queryset = self._filter_by_destination_values(
            queryset,
            param_name="region",
            destination_field="region",
        )

        return queryset.distinct()

    def get(self, request, *args, **kwargs):
        return self.paginate_with_meta(self.get_queryset(), AdminTripListSerializer)

    def _get_multi_values(self, key):
        values = []
        for item in self.request.query_params.getlist(key):
            values.extend([part.strip() for part in str(item).split(",") if part.strip()])
        return values

    def _filter_by_destination_values(self, queryset, *, param_name, destination_field):
        values = self._get_multi_values(param_name)
        if not values:
            return queryset

        lookup = f"trip_destinations__destination__{destination_field}__icontains"
        condition = Q()
        for value in values:
            condition |= Q(**{lookup: value})
        return queryset.filter(condition)


class AdminTripDetailAPIView(GenericAPIView):
    """
    Admin trip detail API.

    Frontend request:
    - Method: GET
    - Headers: authenticated bearer token with superadmin access
    - URL param: `trip_id`

    Frontend response:
    - 200 success with the full trip record for inspection.
    """

    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request, *args, **kwargs):
        trip = get_object_or_404(Trip.objects.select_related("user"), pk=self.kwargs["trip_id"])
        return APIResponse.success(
            data=AdminTripDetailSerializer(trip).data,
            message="Trip fetched successfully.",
        )
