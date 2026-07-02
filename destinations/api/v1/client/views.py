from rest_framework.generics import GenericAPIView
from django.db.models import BooleanField, Exists, F, OuterRef, Prefetch, Value, Window
from django.db.models.functions import RowNumber
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.permissions import IsAuthenticated

from app.base.pagination import CustomPagination
from app.utils.response import APIResponse
from destinations.api.v1.client.serializers import (
    ClientActivitySerializer,
    ClientAttractionSerializer,
    ClientCuisineSerializer,
    ClientDestinationDetailSerializer,
    ClientDestinationListSerializer,
    ClientDestinationShortDetailSerializer,
    DestinationSaveSerializer,
)
from destinations.api.v1.query import (
    apply_activity_filters,
    apply_attraction_filters,
    apply_cuisine_filters,
    apply_destination_filters,
)
from destinations.models import Activity, Attraction, Cuisine, Destination, SavedDestination


def _limited_child_queryset(model, order_by):
    return (
        model.objects.prefetch_related("images")
        .annotate(
            detail_row_number=Window(
                expression=RowNumber(),
                partition_by=[F("destination_id")],
                order_by=order_by,
            )
        )
        .filter(detail_row_number__lte=3)
    )


class DestinationPaginationMixin:
    pagination_class = CustomPagination

    def paginate_with_meta(self, queryset, serializer_class, *, message="Destinations fetched successfully."):
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
            message=message,
        )

    def with_is_saved(self, queryset):
        user = self.request.user
        if not user.is_authenticated:
            return queryset.annotate(is_saved=Value(False, output_field=BooleanField()))
        return queryset.annotate(
            is_saved=Exists(
                SavedDestination.objects.filter(
                    user=user,
                    destination=OuterRef("pk"),
                )
            )
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
        queryset = self.with_is_saved(queryset)
        return apply_destination_filters(queryset, self.request.query_params, include_status=False)

    def get(self, request, *args, **kwargs):
        return self.paginate_with_meta(self.get_queryset(), ClientDestinationListSerializer)


class ClientDestinationDetailAPIView(DestinationPaginationMixin, GenericAPIView):
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
        queryset = self.with_is_saved(
            Destination.objects.filter(status="published")
            .prefetch_related(
                "tags",
                "images",
                Prefetch(
                    "attractions",
                    queryset=_limited_child_queryset(
                        Attraction,
                        [F("sort_order").asc(), F("name").asc()],
                    ),
                ),
                Prefetch(
                    "activities",
                    queryset=_limited_child_queryset(
                        Activity,
                        [F("name").asc()],
                    ),
                ),
                Prefetch(
                    "cuisines",
                    queryset=_limited_child_queryset(
                        Cuisine,
                        [F("is_featured").desc(), F("name").asc()],
                    ),
                ),
            )
        )
        return get_object_or_404(
            queryset,
            slug=self.kwargs["slug"],
        )

    def get(self, request, *args, **kwargs):
        destination = self.get_object()
        return APIResponse.success(
            data=ClientDestinationDetailSerializer(
                destination,
                context={"request": request},
            ).data,
            message="Destination fetched successfully.",
        )


class ClientDestinationShortDetailAPIView(GenericAPIView):
    """
    Client destination short detail API.

    Frontend request:
    - Method: GET
    - URL param: `slug` from the client list API.

    Frontend response:
    - 200 success with name, cover_image, and description for a published destination.
    """

    def get_object(self):
        return get_object_or_404(
            Destination.objects.filter(status="published").prefetch_related("tags"),
            slug=self.kwargs["slug"],
        )

    def get(self, request, *args, **kwargs):
        destination = self.get_object()
        return APIResponse.success(
            data=ClientDestinationShortDetailSerializer(
                destination,
                context={"request": request},
            ).data,
            message="Destination short detail fetched successfully.",
        )


class ClientDestinationChildListAPIView(DestinationPaginationMixin, GenericAPIView):
    """Base client API for a published destination's paginated child resources."""

    model = None
    serializer_class = None
    filter_queryset = None
    resource_label = ""

    def get_destination(self):
        if not hasattr(self, "_destination"):
            self._destination = get_object_or_404(
                Destination.objects.filter(status="published"),
                slug=self.kwargs["slug"],
            )
        return self._destination

    def get_queryset(self):
        queryset = self.model.objects.filter(destination=self.get_destination()).prefetch_related("images")
        return self.filter_queryset(queryset, self.request.query_params)

    def get(self, request, *args, **kwargs):
        return self.paginate_with_meta(
            self.get_queryset(),
            self.serializer_class,
            message=f"{self.resource_label} fetched successfully.",
        )


class ClientDestinationAttractionListAPIView(ClientDestinationChildListAPIView):
    """GET attractions for a destination slug.

    Filters: page, page_size, search, attraction_type, budget_tier,
    best_time_of_day, entrance_fee_required, is_featured.
    """

    model = Attraction
    serializer_class = ClientAttractionSerializer
    filter_queryset = staticmethod(apply_attraction_filters)
    resource_label = "Attractions"


class ClientDestinationActivityListAPIView(ClientDestinationChildListAPIView):
    """GET activities for a destination slug.

    Filters: page, page_size, search, activity_type, budget_tier,
    difficulty_level (or difficulty), booking_required, is_featured.
    """

    model = Activity
    serializer_class = ClientActivitySerializer
    filter_queryset = staticmethod(apply_activity_filters)
    resource_label = "Activities"


class ClientDestinationCuisineListAPIView(ClientDestinationChildListAPIView):
    """GET cuisines for a destination slug.

    Filters: page, page_size, search, cuisine_type, spice_level, meal_type,
    is_vegetarian_friendly (or vegetarian_friendly), is_featured (or featured).
    """

    model = Cuisine
    serializer_class = ClientCuisineSerializer
    filter_queryset = staticmethod(apply_cuisine_filters)
    resource_label = "Cuisines"


class ClientSavedDestinationListAPIView(DestinationPaginationMixin, GenericAPIView):
    """
    User saved destination list API.

    Frontend request:
    - Method: GET
    - Headers: authenticated bearer token
    - Query params: `page`, `page_size`

    Frontend response:
    - 200 success with paginated destination rows saved by the current user.
    """

    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        queryset = (
            Destination.objects.filter(
                status="published",
                saved_by_users__user=self.request.user,
            )
            .prefetch_related("tags")
            .order_by("-saved_by_users__created_at")
        )
        return self.with_is_saved(queryset)

    def get(self, request, *args, **kwargs):
        return self.paginate_with_meta(self.get_queryset(), ClientDestinationListSerializer)


class ClientDestinationSaveAPIView(GenericAPIView):
    """
    Save or remove a destination from the authenticated user's saved list.

    Frontend request:
    - Method: POST
    - Headers: authenticated bearer token
    - Body: `{ "save": true }` to save, `{ "save": false }` to remove.

    Frontend response:
    - 200 success with `saved` reflecting the final state.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = DestinationSaveSerializer

    def get_destination(self):
        return get_object_or_404(
            Destination.objects.filter(status="published"),
            slug=self.kwargs["destination_slug"],
        )

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        destination = self.get_destination()
        should_save = serializer.validated_data["save"]

        if should_save:
            SavedDestination.objects.get_or_create(
                user=request.user,
                destination=destination,
                defaults={
                    "created_by": request.user,
                    "updated_by": request.user,
                },
            )
            message = "Destination saved successfully."
        else:
            SavedDestination.objects.filter(
                user=request.user,
                destination=destination,
            ).delete()
            message = "Destination removed from saved list successfully."

        return APIResponse.success(
            data={
                "slug": destination.slug,
                "saved": should_save,
            },
            message=message,
            status=status.HTTP_200_OK,
        )
