from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated

from app.utils.response import APIResponse
from trips.api.v1.client.serializers import TripNoteSerializer
from trips.models import TripNote

from .mixin import UserTripQuerysetMixin


class TripNoteCreateAPIView(UserTripQuerysetMixin, GenericAPIView):
    """
    Create trip note API.

    Frontend request:
    - Method: POST
    - Headers: authenticated bearer token
    - URL param: `trip_id`
    - Content-Type: application/json
    - Body:
      `content`
      Optional:
      `images`: [{ "image_url": "...", "caption": "", "sort_order": 1 }]

    Frontend response:
    - 201 success with the created note and images.
    """

    permission_classes = [IsAuthenticated]
    serializer_class = TripNoteSerializer

    def post(self, request, *args, **kwargs):
        trip = self.get_trip_by_id()
        serializer = self.get_serializer(data=request.data, context={"request": request, "trip": trip})
        serializer.is_valid(raise_exception=True)
        note = serializer.save()
        return APIResponse.success(
            data=TripNoteSerializer(note).data,
            message="Trip note created successfully.",
            status=status.HTTP_201_CREATED,
        )


class TripNoteListAPIView(UserTripQuerysetMixin, GenericAPIView):
    """
    List trip notes API.

    Frontend request:
    - Method: GET
    - Headers: authenticated bearer token
    - URL param: `trip_id`

    Frontend response:
    - 200 success with notes for the trip ordered newest first.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        trip = self.get_trip_by_id()
        notes = TripNote.objects.filter(trip=trip).prefetch_related("trip_note_images")
        return APIResponse.success(
            data=TripNoteSerializer(notes, many=True).data,
            message="Trip notes fetched successfully.",
        )


class TripNoteDetailAPIView(UserTripQuerysetMixin, GenericAPIView):
    """
    Get trip note detail API.

    Frontend request:
    - Method: GET
    - Headers: authenticated bearer token
    - URL params: `trip_id`, `note_id`

    Frontend response:
    - 200 success with the note and images.
    """

    permission_classes = [IsAuthenticated]

    def get_object(self):
        trip = self.get_trip_by_id()
        return get_object_or_404(
            TripNote.objects.prefetch_related("trip_note_images"),
            trip=trip,
            pk=self.kwargs["note_id"],
        )

    def get(self, request, *args, **kwargs):
        return APIResponse.success(
            data=TripNoteSerializer(self.get_object()).data,
            message="Trip note fetched successfully.",
        )


class TripNoteUpdateAPIView(TripNoteDetailAPIView):
    """
    Update trip note API.

    Frontend request:
    - Method: PATCH
    - Headers: authenticated bearer token
    - URL params: `trip_id`, `note_id`
    - Content-Type: application/json
    - Send only note fields that should change.
    - Send `images` to replace the existing image list.

    Frontend response:
    - 200 success with the updated note and images.
    """

    serializer_class = TripNoteSerializer

    def patch(self, request, *args, **kwargs):
        note = self.get_object()
        serializer = self.get_serializer(
            note,
            data=request.data,
            partial=True,
            context={"request": request, "trip": note.trip},
        )
        serializer.is_valid(raise_exception=True)
        note = serializer.save()
        return APIResponse.success(
            data=TripNoteSerializer(note).data,
            message="Trip note updated successfully.",
        )


class TripNoteDeleteAPIView(UserTripQuerysetMixin, GenericAPIView):
    """
    Delete trip note API.

    Frontend request:
    - Method: DELETE
    - Headers: authenticated bearer token
    - URL params: `trip_id`, `note_id`
    - No request body is required.

    Frontend response:
    - 200 success with no data payload.
    """

    permission_classes = [IsAuthenticated]

    def delete(self, request, *args, **kwargs):
        trip = self.get_trip_by_id()
        note = get_object_or_404(TripNote, trip=trip, pk=self.kwargs["note_id"])
        note.delete()
        return APIResponse.success(message="Trip note deleted successfully.")
