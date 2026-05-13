from rest_framework.generics import GenericAPIView
from django.shortcuts import get_object_or_404

from app.base.pagination import CustomPagination
from app.utils.response import APIResponse
from destinations.api.v1.client.serializers import (
    ClientDestinationDetailSerializer,
    ClientDestinationListSerializer,
)
from destinations.api.v1.query import apply_destination_filters
from destinations.models import Destination


class DestinationPaginationMixin:
    pagination_class = CustomPagination

    def paginate_with_meta(self, queryset, serializer_class):
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, self.request, view=self)
        serializer = serializer_class(page, many=True)
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
            message="Destinations fetched successfully.",
        )


class ClientDestinationListAPIView(DestinationPaginationMixin, GenericAPIView):
    """
    Client destination list API.

    Frontend request:
    - Method: GET
    - Query params:
      `page`, `page_size`
      `search=beach`
      `destination_type=beach,island`
      `country_code=IDN,THA`
      `budget_tier=budget,mid`
      `difficulty=easy`
      `tag=family,romantic`
      `best_travel_month=11,12`
      `region=Southeast Asia`
    - Multiple filters can be combined together.
    - Only published destinations are returned to clients.

    Frontend response:
    - 200 success with paginated destination rows.
    - Each row uses `slug` instead of `id`.
    """

    def get_queryset(self):
        queryset = (
            Destination.objects.filter(status="published")
            .prefetch_related("tags")
            .order_by("name")
        )
        return apply_destination_filters(queryset, self.request.query_params, include_status=False)

    def get(self, request, *args, **kwargs):
        return self.paginate_with_meta(self.get_queryset(), ClientDestinationListSerializer)


class ClientDestinationDetailAPIView(GenericAPIView):
    """
    Client destination detail API.

    Frontend request:
    - Method: GET
    - URL param: `slug` from the client list API.

    Frontend response:
    - 200 success with the full published destination payload.
    - No internal `id` is exposed to the client.
    """

    def get_object(self):
        return get_object_or_404(
            Destination.objects.filter(status="published")
            .prefetch_related("tags", "images"),
            slug=self.kwargs["slug"],
        )

    def get(self, request, *args, **kwargs):
        destination = self.get_object()
        return APIResponse.success(
            data=ClientDestinationDetailSerializer(destination).data,
            message="Destination fetched successfully.",
        )
