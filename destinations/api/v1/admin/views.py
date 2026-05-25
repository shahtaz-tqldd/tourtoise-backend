from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from django.shortcuts import get_object_or_404

from accounts.permissions import IsSuperAdmin
from app.base.pagination import CustomPagination
from app.utils.cloudinary import delete_image
from app.utils.response import APIResponse
from destinations.api.v1.admin.serializers import (
    AdminActivitySerializer,
    AdminAttractionSerializer,
    AdminCuisineSerializer,
    AdminDestinationBulkUploadSerializer,
    AdminDestinationDetailSerializer,
    AdminDestinationListSerializer,
    AdminDestinationWriteSerializer,
    BULK_DESTINATION_TEMPLATE,
)
from destinations.api.v1.query import apply_destination_filters
from destinations.models import Activity, Attraction, Cuisine, Destination


class DestinationPaginationMixin:
    pagination_class = CustomPagination

    def paginate_with_meta(
        self,
        queryset,
        serializer_class,
        *,
        message="Destinations fetched successfully.",
    ):
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
            message=message,
        )


class DestinationChildListCreateAPIView(DestinationPaginationMixin, GenericAPIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]
    parser_classes = [JSONParser, FormParser, MultiPartParser]
    model = None
    serializer_class = None
    related_name = ""
    resource_label = ""
    singular_label = ""

    def get_destination(self):
        if hasattr(self, "_destination"):
            return self._destination
        self._destination = get_object_or_404(Destination, pk=self.kwargs["destination_id"])
        return self._destination

    def get_queryset(self):
        destination = self.get_destination()
        return self.model.objects.filter(destination=destination)

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["destination"] = self.get_destination()
        return context

    def get(self, request, *args, **kwargs):
        return self.paginate_with_meta(
            self.get_queryset(),
            self.serializer_class,
            message=f"{self.resource_label} fetched successfully.",
        )

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = serializer.save()
        return APIResponse.success(
            data=self.get_serializer(item).data,
            message=f"{self.singular_label} created successfully.",
            status=status.HTTP_201_CREATED,
        )


class DestinationChildDetailAPIView(GenericAPIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]
    parser_classes = [JSONParser, FormParser, MultiPartParser]
    model = None
    serializer_class = None
    lookup_kwarg = ""
    resource_label = ""

    def get_destination(self):
        if hasattr(self, "_destination"):
            return self._destination
        self._destination = get_object_or_404(Destination, pk=self.kwargs["destination_id"])
        return self._destination

    def get_object(self):
        return get_object_or_404(
            self.model,
            pk=self.kwargs[self.lookup_kwarg],
            destination=self.get_destination(),
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["destination"] = self.get_destination()
        return context

    def get(self, request, *args, **kwargs):
        item = self.get_object()
        return APIResponse.success(
            data=self.serializer_class(item).data,
            message=f"{self.resource_label} fetched successfully.",
        )

    def patch(self, request, *args, **kwargs):
        item = self.get_object()
        serializer = self.get_serializer(item, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        item = serializer.save()
        return APIResponse.success(
            data=self.serializer_class(item).data,
            message=f"{self.resource_label} updated successfully.",
        )

    def delete(self, request, *args, **kwargs):
        item = self.get_object()
        item.delete()
        return APIResponse.success(message=f"{self.resource_label} deleted successfully.")


class AdminDestinationAttractionListCreateAPIView(DestinationChildListCreateAPIView):
    model = Attraction
    serializer_class = AdminAttractionSerializer
    resource_label = "Attractions"
    singular_label = "Attraction"


class AdminDestinationAttractionDetailAPIView(DestinationChildDetailAPIView):
    model = Attraction
    serializer_class = AdminAttractionSerializer
    lookup_kwarg = "attraction_id"
    resource_label = "Attraction"


class AdminDestinationActivityListCreateAPIView(DestinationChildListCreateAPIView):
    model = Activity
    serializer_class = AdminActivitySerializer
    resource_label = "Activities"
    singular_label = "Activity"


class AdminDestinationActivityDetailAPIView(DestinationChildDetailAPIView):
    model = Activity
    serializer_class = AdminActivitySerializer
    lookup_kwarg = "activity_id"
    resource_label = "Activity"


class AdminDestinationCuisineListCreateAPIView(DestinationChildListCreateAPIView):
    model = Cuisine
    serializer_class = AdminCuisineSerializer
    resource_label = "Cuisines"
    singular_label = "Cuisine"


class AdminDestinationCuisineDetailAPIView(DestinationChildDetailAPIView):
    model = Cuisine
    serializer_class = AdminCuisineSerializer
    lookup_kwarg = "cuisine_id"
    resource_label = "Cuisine"


class AdminDestinationCreateAPIView(GenericAPIView):
    """
    Admin create destination API.

    Frontend request:
    - Method: POST
    - Content-Type: multipart/form-data
    - Send scalar fields normally: name, country, destination_type, latitude, longitude,
      tagline, overview, min_stay_days, max_stay_days, budget_tier, difficulty, currency,
      status, data_source, region, getting_around, visa_notes.
    - Send array/object fields as JSON strings in multipart:
      `tags=[{"name":"Beach","category":"experience"}]`
      `attractions=[{"name":"Phewa Lake","attraction_type":"natural_site","description":"..."}]`
      `activities=[{"name":"Paragliding","activity_type":"adventure","description":"...","budget_tier":"premium"}]`
      `cuisines=[{"name":"Thakali Set","description":"..."}]`
      `local_languages=["English","Thai"]`
      `best_travel_months=[11,12,1]`
      `cultural_tips=["Dress modestly at temples","Carry cash for local markets"]`
    - Send one `cover_image_file` for the main image, or a plain `cover_image` URL.
    - Send child cover image files by index, for example `attractions[0].cover_image_file`.
    - Send repeated `gallery_images` files for gallery uploads.

    Frontend response:
    - 201 success with the created destination object including `id`, `slug`, nested `tags`, and `images`.
    """

    permission_classes = [IsAuthenticated, IsSuperAdmin]
    serializer_class = AdminDestinationWriteSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        destination = serializer.save()
        return APIResponse.success(
            data=AdminDestinationDetailSerializer(destination).data,
            message="Destination created successfully.",
            status=status.HTTP_201_CREATED,
        )


class AdminDestinationBulkTemplateAPIView(GenericAPIView):
    """
    Admin bulk destination template API.

    Frontend request:
    - Method: GET

    Frontend response:
    - 200 success with CSV columns, XLSX sheet headers, example rows, and allowed enum values.
    """

    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request, *args, **kwargs):
        return APIResponse.success(
            data=BULK_DESTINATION_TEMPLATE,
            message="Bulk destination template fetched successfully.",
        )


class AdminDestinationBulkUploadAPIView(GenericAPIView):
    """
    Admin bulk destination upload API.

    Frontend request:
    - Method: POST
    - Content-Type: multipart/form-data
    - Send `file` as a `.xlsx` workbook or combined `.csv`.
    - XLSX sheets: destinations, attractions, activities, cuisines.
    - CSV uses `record_type` values: destination, attraction, activity, cuisine.
    - All image fields are URL strings. No image file uploads are processed here.

    Frontend response:
    - 201 success with created counts and created destination ids.
    """

    permission_classes = [IsAuthenticated, IsSuperAdmin]
    serializer_class = AdminDestinationBulkUploadSerializer
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        result = serializer.save()
        return APIResponse.success(
            data=result,
            message="Bulk destinations created successfully.",
            status=status.HTTP_201_CREATED,
        )


class AdminDestinationUpdateAPIView(GenericAPIView):
    """
    Admin update destination API.

    Frontend request:
    - Method: PATCH
    - URL param: `destination_id` (UUID from admin list/detail API).
    - Content-Type: multipart/form-data
    - Send only fields you want to change.
    - Array/object fields still come as JSON strings in multipart.
    - Send `cover_image_file` to replace the main image.
    - Send `clear_cover_image=true` to remove the current main image.
    - Send repeated `gallery_images` files to append new gallery images.
    - Send `remove_image_urls=["https://...","https://..."]` to delete existing gallery images.
    - To replace a child cover image, send the child id list and matching indexed file:
      `attractions=[{"id":"..."}]` with `attractions[0].cover_image_file`.

    Frontend response:
    - 200 success with the fully updated destination object.
    """

    permission_classes = [IsAuthenticated, IsSuperAdmin]
    serializer_class = AdminDestinationWriteSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def get_object(self):
        return get_object_or_404(
            Destination.objects.prefetch_related("tags", "images"),
            pk=self.kwargs["destination_id"],
        )

    def patch(self, request, *args, **kwargs):
        destination = self.get_object()
        serializer = self.get_serializer(
            destination,
            data=request.data,
            partial=True,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        destination = serializer.save()
        return APIResponse.success(
            data=AdminDestinationDetailSerializer(destination).data,
            message="Destination updated successfully.",
        )


class AdminDestinationDeleteAPIView(GenericAPIView):
    """
    Admin delete destination API.

    Frontend request:
    - Method: DELETE
    - URL param: `destination_id` (UUID from admin list/detail API).
    - No request body is required.

    Frontend response:
    - 200 success with no data payload.
    - Cloudinary cover image and gallery images are removed before the record is deleted.
    """

    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get_object(self):
        return get_object_or_404(
            Destination.objects.prefetch_related("images"),
            pk=self.kwargs["destination_id"],
        )

    def delete(self, request, *args, **kwargs):
        destination = self.get_object()
        if destination.cover_image:
            delete_image(image_url=destination.cover_image)
        for image in destination.images.all():
            delete_image(image_url=image.image_url)
        destination.delete()
        return APIResponse.success(message="Destination deleted successfully.")


class AdminDestinationListAPIView(DestinationPaginationMixin, GenericAPIView):
    """
    Admin destination list API.

    Frontend request:
    - Method: GET
    - Query params:
      `page`, `page_size`
      `search=nepal`
      `destination_type=city,beach`
      `country_code=NPL,THA`
      `budget_tier=budget,mid`
      `difficulty=easy,moderate`
      `tag=heritage,romantic`
      `best_travel_month=10,11`
      `status=draft,published`
      `data_source=manual`
      `region=South Asia`
    - Multiple filters can be combined in the same request.

    Frontend response:
    - 200 success with paginated destination rows.
    - Each row includes `id` so admin can call update/delete APIs.
    """

    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get_queryset(self):
        queryset = Destination.objects.prefetch_related("tags", "images").order_by("-created_at")
        return apply_destination_filters(queryset, self.request.query_params, include_status=True)

    def get(self, request, *args, **kwargs):
        return self.paginate_with_meta(self.get_queryset(), AdminDestinationListSerializer)


class AdminDestinationDetailAPIView(GenericAPIView):
    """
    Admin destination detail API.

    Frontend request:
    - Method: GET
    - URL param: `destination_id` (UUID).

    Frontend response:
    - 200 success with the full destination object.
    - Includes internal `id`, nested `tags`, nested `images`, and destination child resources.
    """

    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get_object(self):
        return get_object_or_404(
            Destination.objects.prefetch_related(
                "tags",
                "images",
                "attractions__images",
                "activities__images",
                "cuisines__images",
            ),
            pk=self.kwargs["destination_id"],
        )

    def get(self, request, *args, **kwargs):
        destination = self.get_object()
        return APIResponse.success(
            data=AdminDestinationDetailSerializer(destination).data,
            message="Destination fetched successfully.",
        )
