from django.db import transaction
from django.db.models import Max
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.generics import GenericAPIView
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated

from app.utils.cloudinary import delete_file
from app.utils.response import APIResponse
from trips.api.v1.client.serializers import (
    TripHeadsUpInfoItemSerializer,
    TripPreparationPackingItemSerializer,
    TripRequiredDocumentItemSerializer,
)
from trips.models import (
    TripHeadsUpInfoItem,
    TripPreparation,
    TripPreparationPackingItem,
    TripRequiredDocumentItem,
)

from .mixin import UserTripQuerysetMixin


class TripPreparationItemMixin(UserTripQuerysetMixin):
    model = None
    serializer_class = None
    lookup_url_kwarg = "item_id"
    list_message = "Trip preparation items fetched successfully."
    create_message = "Trip preparation item created successfully."
    detail_message = "Trip preparation item fetched successfully."
    update_message = "Trip preparation item updated successfully."
    delete_message = "Trip preparation item deleted successfully."
    reorder_message = "Trip preparation item orders updated successfully."

    def get_preparation(self, create=False):
        trip = self.get_trip_by_id()
        if create:
            preparation, _ = TripPreparation.objects.get_or_create(trip=trip)
            return preparation
        return getattr(trip, "structured_preparation", None)

    def get_queryset(self):
        preparation = self.get_preparation()
        if not preparation:
            return self.model.objects.none()
        return self.model.objects.filter(preparation=preparation)

    def get_object(self):
        return get_object_or_404(
            self.get_queryset(),
            pk=self.kwargs[self.lookup_url_kwarg],
        )

    def get_serializer_context(self):
        context = super().get_serializer_context()
        preparation = self.get_preparation(create=self.request.method == "POST")
        if preparation:
            context["preparation"] = preparation
        return context

    def update_changed_orders(self, changed_orders):
        order_map = self._validate_changed_orders(changed_orders)
        queryset = self.get_queryset()
        items = list(queryset.filter(pk__in=order_map.keys()))

        if len(items) != len(order_map):
            raise ValidationError({"changed_orders": "One or more item IDs are invalid for this trip."})

        self._validate_sort_order_conflicts(order_map)

        with transaction.atomic():
            self._move_items_to_temporary_orders(items, queryset)
            for item in items:
                item.sort_order = order_map[str(item.pk)]
            self.model.objects.bulk_update(items, ["sort_order"])

        return self.get_queryset()

    def _validate_changed_orders(self, changed_orders):
        if not isinstance(changed_orders, list):
            raise ValidationError({"changed_orders": "Expected a list of order changes."})

        order_map = {}
        seen_orders = set()
        for item in changed_orders:
            if not isinstance(item, dict):
                raise ValidationError({"changed_orders": "Each order change must be an object."})

            item_id = str(item.get("id", "")).strip()
            sort_order = item.get("sort_order")

            if not item_id or sort_order is None:
                raise ValidationError({"changed_orders": "Each item must include id and sort_order."})

            if item_id in order_map:
                raise ValidationError({"changed_orders": "Duplicate IDs are not allowed."})

            try:
                sort_order = int(sort_order)
            except (TypeError, ValueError):
                raise ValidationError({"changed_orders": "sort_order must be an integer."})

            if sort_order < 0:
                raise ValidationError({"changed_orders": "sort_order must be zero or greater."})

            if sort_order in seen_orders:
                raise ValidationError({"changed_orders": "Duplicate sort_order values are not allowed."})

            order_map[item_id] = sort_order
            seen_orders.add(sort_order)

        if not order_map:
            raise ValidationError({"changed_orders": "At least one order change is required."})

        return order_map

    def _validate_sort_order_conflicts(self, order_map):
        existing_conflict = (
            self.get_queryset()
            .filter(sort_order__in=order_map.values())
            .exclude(pk__in=order_map.keys())
            .exists()
        )
        if existing_conflict:
            raise ValidationError(
                {"changed_orders": "sort_order values must not conflict with unchanged items."}
            )

    def _move_items_to_temporary_orders(self, items, queryset):
        max_sort_order = queryset.aggregate(Max("sort_order"))["sort_order__max"] or 0
        for index, item in enumerate(items, start=1):
            item.sort_order = max_sort_order + index
        self.model.objects.bulk_update(items, ["sort_order"])


class TripPreparationItemListCreateAPIView(TripPreparationItemMixin, GenericAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        return APIResponse.success(
            data=self.get_serializer(self.get_queryset(), many=True).data,
            message=self.list_message,
        )

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = serializer.save()
        return APIResponse.success(
            data=self.get_serializer(item).data,
            message=self.create_message,
            status=status.HTTP_201_CREATED,
        )

    def patch(self, request, *args, **kwargs):
        items = self.update_changed_orders(request.data.get("changed_orders"))
        return APIResponse.success(
            data=self.get_serializer(items, many=True).data,
            message=self.reorder_message,
        )


class TripPreparationItemDetailAPIView(TripPreparationItemMixin, GenericAPIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        return APIResponse.success(
            data=self.get_serializer(self.get_object()).data,
            message=self.detail_message,
        )

    def patch(self, request, *args, **kwargs):
        if "changed_orders" in request.data:
            items = self.update_changed_orders(request.data["changed_orders"])
            return APIResponse.success(
                data=self.get_serializer(items, many=True).data,
                message=self.reorder_message,
            )

        item = self.get_object()
        serializer = self.get_serializer(item, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        item = serializer.save()
        return APIResponse.success(
            data=self.get_serializer(item).data,
            message=self.update_message,
        )

    def delete(self, request, *args, **kwargs):
        self.get_object().delete()
        return APIResponse.success(message=self.delete_message)


class TripPreparationPackingItemListCreateAPIView(TripPreparationItemListCreateAPIView):
    model = TripPreparationPackingItem
    serializer_class = TripPreparationPackingItemSerializer
    list_message = "Trip packing items fetched successfully."
    create_message = "Trip packing item created successfully."
    reorder_message = "Trip packing item orders updated successfully."


class TripPreparationPackingItemDetailAPIView(TripPreparationItemDetailAPIView):
    model = TripPreparationPackingItem
    serializer_class = TripPreparationPackingItemSerializer
    lookup_url_kwarg = "packing_item_id"
    detail_message = "Trip packing item fetched successfully."
    update_message = "Trip packing item updated successfully."
    delete_message = "Trip packing item deleted successfully."
    reorder_message = "Trip packing item orders updated successfully."


class TripRequiredDocumentItemListCreateAPIView(TripPreparationItemListCreateAPIView):
    model = TripRequiredDocumentItem
    serializer_class = TripRequiredDocumentItemSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    list_message = "Trip required documents fetched successfully."
    create_message = "Trip required document created successfully."
    reorder_message = "Trip required document orders updated successfully."


class TripRequiredDocumentItemDetailAPIView(TripPreparationItemDetailAPIView):
    model = TripRequiredDocumentItem
    serializer_class = TripRequiredDocumentItemSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    lookup_url_kwarg = "document_id"
    detail_message = "Trip required document fetched successfully."
    update_message = "Trip required document updated successfully."
    delete_message = "Trip required document deleted successfully."
    reorder_message = "Trip required document orders updated successfully."


class TripRequiredDocumentFileDeleteAPIView(TripRequiredDocumentItemDetailAPIView):
    delete_message = "Trip required document file deleted successfully."

    def delete(self, request, *args, **kwargs):
        item = self.get_object()
        delete_file(public_id=item.document_url_public_id, file_url=item.document_url)
        item.document_file_name = ""
        item.document_url = None
        item.document_url_public_id = ""
        item.save(update_fields=["document_file_name", "document_url", "document_url_public_id"])
        return APIResponse.success(
            data=self.get_serializer(item).data,
            message=self.delete_message,
        )


class TripHeadsUpInfoItemListCreateAPIView(TripPreparationItemListCreateAPIView):
    model = TripHeadsUpInfoItem
    serializer_class = TripHeadsUpInfoItemSerializer
    list_message = "Trip heads-up items fetched successfully."
    create_message = "Trip heads-up item created successfully."
    reorder_message = "Trip heads-up item orders updated successfully."


class TripHeadsUpInfoItemDetailAPIView(TripPreparationItemDetailAPIView):
    model = TripHeadsUpInfoItem
    serializer_class = TripHeadsUpInfoItemSerializer
    lookup_url_kwarg = "heads_up_item_id"
    detail_message = "Trip heads-up item fetched successfully."
    update_message = "Trip heads-up item updated successfully."
    delete_message = "Trip heads-up item deleted successfully."
    reorder_message = "Trip heads-up item orders updated successfully."
