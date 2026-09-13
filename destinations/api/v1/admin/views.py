from uuid import UUID

from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.generics import GenericAPIView
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.renderers import JSONRenderer
from django.shortcuts import get_object_or_404
from django.db import transaction

from accounts.permissions import IsSuperAdmin
from app.base.pagination import CustomPagination
from vector_store.services.vectorize import DestinationVectorService
from app.utils.cloudinary import delete_image
from app.utils.response import APIResponse
from destinations.api.v1.admin.serializers import (
    AdminActivityBulkUploadSerializer,
    AdminActivityListSerializer,
    AdminActivitySerializer,
    AdminAttractionBulkUploadSerializer,
    AdminAttractionListSerializer,
    AdminAttractionSerializer,
    AdminCuisineBulkUploadSerializer,
    AdminCuisineListSerializer,
    AdminCuisineSerializer,
    AdminDestinationBulkUploadSerializer,
    AdminDestinationDetailSerializer,
    AdminDestinationListSerializer,
    AdminDestinationShortDetailSerializer,
    AdminDestinationWriteSerializer,
    BULK_ACTIVITY_TEMPLATE,
    BULK_ATTRACTION_TEMPLATE,
    BULK_CUISINE_TEMPLATE,
    BULK_DESTINATION_TEMPLATE,
)
from destinations.api.v1.query import apply_destination_filters
from destinations.models import Activity, Attraction, Cuisine, Destination
from destinations.tasks import process_vector_operations
from vector_store.models import VectorDocument

from destinations.api.v1.admin.bulk_export import RESOURCE_ALIASES, build_bulk_download


class BulkCSVRenderer(JSONRenderer):
    media_type = "text/csv"
    format = "csv"


class BulkXLSXRenderer(JSONRenderer):
    media_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    format = "xlsx"


class DestinationBulkParameterMixin:
    id_parameters = (
        "destination_ids",
        "activity_ids",
        "cuisine_ids",
        "attraction_ids",
    )
    resource_id_parameters = {
        "destinations": "destination_ids",
        "activities": "activity_ids",
        "cuisines": "cuisine_ids",
        "attractions": "attraction_ids",
    }

    def get_bulk_resource(self, request):
        resource_value = request.query_params.get("type", "destination").strip().lower()
        resource = RESOURCE_ALIASES.get(resource_value)
        if not resource:
            raise ValidationError(
                {"type": "Choose destination, activities, cuisines, or attractions."}
            )
        return resource

    def get_selected_ids(self, request):
        return {
            parameter: self._parse_ids(request, parameter)
            for parameter in self.id_parameters
        }

    def _parse_ids(self, request, parameter):
        values = []
        for raw_value in request.query_params.getlist(parameter):
            values.extend(part.strip() for part in raw_value.split(",") if part.strip())

        parsed = []
        seen = set()
        for value in values:
            try:
                item_id = UUID(value)
            except (TypeError, ValueError, AttributeError) as exc:
                raise ValidationError({parameter: f"'{value}' is not a valid UUID."}) from exc
            if item_id not in seen:
                parsed.append(item_id)
                seen.add(item_id)
        return parsed


class DestinationPaginationMixin:
    pagination_class = CustomPagination
    vector_source_type = None

    def paginate_with_meta(
        self,
        queryset,
        serializer_class,
        *,
        message="Destinations fetched successfully.",
    ):
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, self.request, view=self)
        serializer_context = self.get_serializer_context()
        if self.vector_source_type:
            serializer_context["trained_source_ids"] = (
                DestinationVectorService.get_indexed_source_ids(
                    self.vector_source_type,
                    (item.pk for item in page),
                )
            )
        serializer = serializer_class(page, many=True, context=serializer_context)
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
    list_serializer_class = None
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
        return self.model.objects.filter(destination=destination).prefetch_related("images")

    def get_serializer_context(self):
        context = super().get_serializer_context()
        context["destination"] = self.get_destination()
        return context

    def get(self, request, *args, **kwargs):
        return self.paginate_with_meta(
            self.get_queryset(),
            self.list_serializer_class or self.serializer_class,
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
            self.model.objects.prefetch_related("images"),
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
        if getattr(item, "cover_image", ""):
            delete_image(image_url=item.cover_image)
        for image in item.images.all():
            delete_image(image_url=image.image_url)
        item.delete()
        return APIResponse.success(message=f"{self.resource_label} deleted successfully.")


class DestinationChildBulkTemplateAPIView(GenericAPIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]
    template_data = None
    resource_label = ""

    def get(self, request, *args, **kwargs):
        return APIResponse.success(
            data=self.template_data,
            message=f"{self.resource_label} bulk template fetched successfully.",
        )


class DestinationChildBulkUploadAPIView(GenericAPIView):
    permission_classes = [IsAuthenticated, IsSuperAdmin]
    parser_classes = [MultiPartParser, FormParser]
    serializer_class = None
    resource_label = ""

    def get_destination(self):
        if hasattr(self, "_destination"):
            return self._destination
        self._destination = get_object_or_404(Destination, pk=self.kwargs["destination_id"])
        return self._destination

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(
            data=request.data,
            context={
                "request": request,
                "destination": self.get_destination(),
            },
        )
        serializer.is_valid(raise_exception=True)
        result = serializer.save()
        return APIResponse.success(
            data=result,
            message=f"Bulk {self.resource_label.lower()} created successfully.",
            status=status.HTTP_201_CREATED,
        )


class DestinationAttractionListCreateAPIView(DestinationChildListCreateAPIView):
    model = Attraction
    serializer_class = AdminAttractionSerializer
    list_serializer_class = AdminAttractionListSerializer
    vector_source_type = VectorDocument.SourceType.ATTRACTION
    resource_label = "Attractions"
    singular_label = "Attraction"


class DestinationAttractionDetailAPIView(DestinationChildDetailAPIView):
    model = Attraction
    serializer_class = AdminAttractionSerializer
    lookup_kwarg = "attraction_id"
    resource_label = "Attraction"


class DestinationAttractionBulkTemplateAPIView(DestinationChildBulkTemplateAPIView):
    template_data = BULK_ATTRACTION_TEMPLATE
    resource_label = "Attractions"


class DestinationAttractionBulkUploadAPIView(DestinationChildBulkUploadAPIView):
    serializer_class = AdminAttractionBulkUploadSerializer
    resource_label = "Attractions"


class DestinationActivityListCreateAPIView(DestinationChildListCreateAPIView):
    model = Activity
    serializer_class = AdminActivitySerializer
    list_serializer_class = AdminActivityListSerializer
    vector_source_type = VectorDocument.SourceType.ACTIVITY
    resource_label = "Activities"
    singular_label = "Activity"


class DestinationActivityDetailAPIView(DestinationChildDetailAPIView):
    model = Activity
    serializer_class = AdminActivitySerializer
    lookup_kwarg = "activity_id"
    resource_label = "Activity"


class DestinationActivityBulkTemplateAPIView(DestinationChildBulkTemplateAPIView):
    template_data = BULK_ACTIVITY_TEMPLATE
    resource_label = "Activities"


class DestinationActivityBulkUploadAPIView(DestinationChildBulkUploadAPIView):
    serializer_class = AdminActivityBulkUploadSerializer
    resource_label = "Activities"


class DestinationCuisineListCreateAPIView(DestinationChildListCreateAPIView):
    model = Cuisine
    serializer_class = AdminCuisineSerializer
    list_serializer_class = AdminCuisineListSerializer
    vector_source_type = VectorDocument.SourceType.CUISINE
    resource_label = "Cuisines"
    singular_label = "Cuisine"


class DestinationCuisineDetailAPIView(DestinationChildDetailAPIView):
    model = Cuisine
    serializer_class = AdminCuisineSerializer
    lookup_kwarg = "cuisine_id"
    resource_label = "Cuisine"


class DestinationCuisineBulkTemplateAPIView(DestinationChildBulkTemplateAPIView):
    template_data = BULK_CUISINE_TEMPLATE
    resource_label = "Cuisines"


class DestinationCuisineBulkUploadAPIView(DestinationChildBulkUploadAPIView):
    serializer_class = AdminCuisineBulkUploadSerializer
    resource_label = "Cuisines"


class DestinationVectorRetrainAPIView(GenericAPIView):
    """Queue an asynchronous rebuild of one resource's vector documents."""

    permission_classes = [IsAuthenticated, IsSuperAdmin]
    model = None
    lookup_kwarg = ""
    source_type = ""
    resource_label = ""

    def get_object(self):
        filters = {"pk": self.kwargs[self.lookup_kwarg]}
        if self.model is not Destination:
            filters["destination_id"] = self.kwargs["destination_id"]
        return get_object_or_404(self.model, **filters)

    def post(self, request, *args, **kwargs):
        instance = self.get_object()
        destination_id = (
            instance.id if self.model is Destination else instance.destination_id
        )
        process_vector_operations.delay(
            [
                {
                    "action": "index",
                    "source_type": self.source_type,
                    "source_id": str(instance.id),
                    "destination_id": str(destination_id),
                }
            ]
        )
        return APIResponse.success(
            data={
                "id": str(instance.id),
                "source_type": self.source_type,
                "retraining_queued": True,
            },
            message=f"{self.resource_label} re-training queued successfully.",
            status=status.HTTP_202_ACCEPTED,
        )


class DestinationRetrainAPIView(DestinationVectorRetrainAPIView):
    model = Destination
    lookup_kwarg = "destination_id"
    source_type = VectorDocument.SourceType.DESTINATION
    resource_label = "Destination"


class DestinationAttractionRetrainAPIView(DestinationVectorRetrainAPIView):
    model = Attraction
    lookup_kwarg = "attraction_id"
    source_type = VectorDocument.SourceType.ATTRACTION
    resource_label = "Attraction"


class DestinationActivityRetrainAPIView(DestinationVectorRetrainAPIView):
    model = Activity
    lookup_kwarg = "activity_id"
    source_type = VectorDocument.SourceType.ACTIVITY
    resource_label = "Activity"


class DestinationCuisineRetrainAPIView(DestinationVectorRetrainAPIView):
    model = Cuisine
    lookup_kwarg = "cuisine_id"
    source_type = VectorDocument.SourceType.CUISINE
    resource_label = "Cuisine"


class DestinationCreateAPIView(GenericAPIView):
    """
    Admin create destination API.

    Frontend request:
    - Method: POST
    - Content-Type: multipart/form-data
    - Send scalar fields normally: name, country, destination_type, latitude, longitude,
      tagline, description, min_stay_days, max_stay_days, budget_tier, difficulty_level,
      currency, currency_code, status, region, getting_around, visa_notes, notes.
    - Send array/object fields as JSON strings in multipart:
      `tags=[{"name":"Beach","category":"experience"}]`
      `attractions=[{"name":"Phewa Lake","attraction_type":"natural_site","description":"..."}]`
      `activities=[{"name":"Paragliding","activity_type":"adventure","description":"...","budget_tier":"premium"}]`
      `cuisines=[{"name":"Thakali Set","description":"..."}]`
      `local_languages=["English","Thai"]`
      `best_travel_months=[11,12,1]`
      `notes=["Dress modestly at temples","Carry cash for local markets"]`
    - Send one `cover_image_file` for the main image, or a plain `cover_image` URL.
    - Send child cover image files by index, for example `attractions[0].cover_image_file`.
    - Send repeated `gallery_images` files for gallery uploads.
    - Child create/update endpoints accept repeated `images` files and `removed_images=["https://..."]`.

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


class DestinationBulkTemplateAPIView(GenericAPIView):
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


class DestinationBulkUploadAPIView(GenericAPIView):
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


class DestinationBulkDownloadAPIView(DestinationBulkParameterMixin, GenericAPIView):
    """Download existing destination data in round-trip-compatible CSV or XLSX files."""

    permission_classes = [IsAuthenticated, IsSuperAdmin]
    # DRF treats the `format` query parameter as renderer selection before `get()`.
    # Register both download formats even though successful responses are HttpResponse.
    renderer_classes = [JSONRenderer, BulkCSVRenderer, BulkXLSXRenderer]

    def get(self, request, *args, **kwargs):
        resource = self.get_bulk_resource(request)

        file_format = request.query_params.get("format", "xlsx").strip().lower()
        if file_format not in {"csv", "xlsx"}:
            raise ValidationError({"format": "Choose csv or xlsx."})

        return build_bulk_download(
            resource=resource,
            file_format=file_format,
            selected_ids=self.get_selected_ids(request),
        )


class DestinationBatchTrainAPIView(DestinationBulkParameterMixin, GenericAPIView):
    """Queue vector training for a selected resource type and optional IDs."""

    permission_classes = [IsAuthenticated, IsSuperAdmin]
    resource_models = {
        "destinations": Destination,
        "activities": Activity,
        "cuisines": Cuisine,
        "attractions": Attraction,
    }
    resource_source_types = {
        "activities": "activity",
        "cuisines": "cuisine",
        "attractions": "attraction",
    }

    def post(self, request, *args, **kwargs):
        resource = self.get_bulk_resource(request)
        selected_ids = self.get_selected_ids(request)
        requested_ids = selected_ids[self.resource_id_parameters[resource]]
        model = self.resource_models[resource]
        queryset = model.objects.all()
        if requested_ids:
            queryset = queryset.filter(id__in=requested_ids)

        if resource == "destinations":
            records = list(queryset.values_list("id", flat=True))
            operations = [
                {
                    "action": "index_tree",
                    "source_type": "destination",
                    "source_id": str(item_id),
                    "destination_id": str(item_id),
                }
                for item_id in records
            ]
        else:
            records = list(queryset.values_list("id", "destination_id"))
            source_type = self.resource_source_types[resource]
            operations = [
                {
                    "action": "index",
                    "source_type": source_type,
                    "source_id": str(item_id),
                    "destination_id": str(destination_id),
                }
                for item_id, destination_id in records
            ]

        if operations:
            process_vector_operations.delay(operations)

        queued_ids = [operation["source_id"] for operation in operations]
        queued_id_set = set(queued_ids)
        return APIResponse.success(
            data={
                "type": resource,
                "requested_count": len(requested_ids) if requested_ids else len(operations),
                "queued_count": len(operations),
                "queued_ids": queued_ids,
                "not_found_ids": [
                    str(item_id)
                    for item_id in requested_ids
                    if str(item_id) not in queued_id_set
                ],
            },
            message="Batch training queued successfully.",
            status=status.HTTP_202_ACCEPTED,
        )


class DestinationBatchDeleteAPIView(DestinationBulkParameterMixin, GenericAPIView):
    """Delete explicitly selected destination resources and their hosted images."""

    permission_classes = [IsAuthenticated, IsSuperAdmin]
    resource_models = DestinationBatchTrainAPIView.resource_models

    def post(self, request, *args, **kwargs):
        return self.delete(request, *args, **kwargs)

    def delete(self, request, *args, **kwargs):
        resource = self.get_bulk_resource(request)
        selected_ids = self.get_selected_ids(request)
        requested_ids = selected_ids[self.resource_id_parameters[resource]]
        parameter = self.resource_id_parameters[resource]
        if not requested_ids:
            raise ValidationError(
                {parameter: f"Provide at least one ID to batch delete {resource}."}
            )

        model = self.resource_models[resource]
        queryset = self._delete_queryset(model, requested_ids)
        with transaction.atomic():
            items = list(queryset.select_for_update())
            deleted_ids = [str(item.id) for item in items]
            image_urls = self._image_urls(items)
            model.objects.filter(id__in=[item.id for item in items]).delete()

        for image_url in image_urls:
            delete_image(image_url=image_url)

        deleted_id_set = set(deleted_ids)
        return APIResponse.success(
            data={
                "type": resource,
                "requested_count": len(requested_ids),
                "deleted_count": len(deleted_ids),
                "deleted_ids": deleted_ids,
                "not_found_ids": [
                    str(item_id)
                    for item_id in requested_ids
                    if str(item_id) not in deleted_id_set
                ],
            },
            message="Batch delete completed successfully.",
        )

    def _delete_queryset(self, model, requested_ids):
        queryset = model.objects.filter(id__in=requested_ids).prefetch_related("images")
        if model is Destination:
            queryset = queryset.prefetch_related(
                "attractions__images",
                "activities__images",
                "cuisines__images",
            )
        return queryset

    def _image_urls(self, items):
        urls = []
        for item in items:
            self._append_item_images(urls, item)
            if isinstance(item, Destination):
                for relation in ("attractions", "activities", "cuisines"):
                    for child in getattr(item, relation).all():
                        self._append_item_images(urls, child)
        return list(dict.fromkeys(urls))

    def _append_item_images(self, urls, item):
        if item.cover_image:
            urls.append(item.cover_image)
        urls.extend(image.image_url for image in item.images.all() if image.image_url)


class DestinationUpdateAPIView(GenericAPIView):
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


class DestinationDeleteAPIView(GenericAPIView):
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


class DestinationListAPIView(DestinationPaginationMixin, GenericAPIView):
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
      `difficulty_level=easy,moderate`
      `tag=heritage,romantic`
      `best_travel_month=10,11`
      `status=draft,published`
      `region=South Asia`
    - Multiple filters can be combined in the same request.

    Frontend response:
    - 200 success with paginated destination rows.
    - Each row includes `id` and `is_trained_completed` so admin can identify
      resources that currently have vector documents.
    """

    permission_classes = [IsAuthenticated, IsSuperAdmin]
    vector_source_type = VectorDocument.SourceType.DESTINATION

    def get_queryset(self):
        queryset = Destination.objects.prefetch_related("tags", "images").order_by("-created_at")
        return apply_destination_filters(queryset, self.request.query_params, include_status=True)

    def get(self, request, *args, **kwargs):
        return self.paginate_with_meta(self.get_queryset(), AdminDestinationListSerializer)


class DestinationDetailAPIView(GenericAPIView):
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


class DestinationShortDetailAPIView(GenericAPIView):
    """
    Admin destination short detail API.

    Frontend request:
    - Method: GET
    - URL param: `destination_id` (UUID).

    Frontend response:
    - 200 success with compact destination details including name, tagline, cover image, and tags.
    """

    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get_object(self):
        return get_object_or_404(
            Destination.objects.prefetch_related("tags"),
            pk=self.kwargs["destination_id"],
        )

    def get(self, request, *args, **kwargs):
        destination = self.get_object()
        return APIResponse.success(
            data=AdminDestinationShortDetailSerializer(destination).data,
            message="Destination short detail fetched successfully.",
        )
