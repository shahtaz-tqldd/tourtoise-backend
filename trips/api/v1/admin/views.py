from django.db.models import Q
from django.shortcuts import get_object_or_404
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated

from accounts.permissions import IsSuperAdmin
from app.base.pagination import CustomPagination
from app.utils.response import APIResponse
from trips.api.v1.admin.serializers import AdminTripDetailSerializer, AdminTripListSerializer
from trips.models import Trip


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
      `visibility=private,link_only`
      `planning_source=agent,hybrid`
      `user_email=traveler@example.com`
    - Multiple filters can be combined.

    Frontend response:
    - 200 success with paginated trip rows for admin dashboards.
    """

    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get_queryset(self):
        queryset = Trip.objects.select_related("user").order_by("-updated_at")
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

        visibilities = self._get_multi_values("visibility")
        if visibilities:
            queryset = queryset.filter(visibility__in=visibilities)

        planning_sources = self._get_multi_values("planning_source")
        if planning_sources:
            queryset = queryset.filter(planning_source__in=planning_sources)

        user_email = params.get("user_email", "").strip()
        if user_email:
            queryset = queryset.filter(user__email__icontains=user_email)

        return queryset.distinct()

    def get(self, request, *args, **kwargs):
        return self.paginate_with_meta(self.get_queryset(), AdminTripListSerializer)

    def _get_multi_values(self, key):
        values = []
        for item in self.request.query_params.getlist(key):
            values.extend([part.strip() for part in str(item).split(",") if part.strip()])
        return values


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
