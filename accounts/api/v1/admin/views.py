from django.db import transaction
from django.db.models import BigIntegerField, Count, OuterRef, Q, Subquery, Value
from django.db.models.functions import Coalesce
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import status
from rest_framework.generics import GenericAPIView
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated

from app.base.pagination import CustomPagination
from app.utils.response import APIResponse
from accounts.api.v1.admin.serializers import (
    AccountListSerializer,
    AdminCreditRequestSerializer,
    AdminDetailsSerializer,
    AdminLoginSerializer,
    UpdateAdminInfoSerializer,
    UpdateAdminPasswordSerializer,
    ReviewCreditRequestSerializer,
)
from accounts.choices import CreditRequestStatus, CreditTransactionType
from accounts.models import CreditRequest, User, UserCredit
from accounts.permissions import IsAdmin, IsSuperAdmin
from accounts.services.credit import CreditService
from chat.models import ChatMessage
from journals.models import Journal
from trips.models import Trip, TripConversationMessage


def _related_count(queryset, *, user_field):
    return Subquery(
        queryset.filter(**{user_field: OuterRef("pk")})
        .order_by()
        .values(user_field)
        .annotate(total=Count("id"))
        .values("total")[:1],
        output_field=BigIntegerField(),
    )


class AdminLoginAPIView(GenericAPIView):
    """
    Admin login API.

    Frontend request:
    - Method: POST
    - Content-Type: application/json
    - Body: `email`, `password`

    Frontend response:
    - 200 success with `access_token` and `refresh_token`.
    - Non-staff users are rejected even when credentials are valid.
    """

    serializer_class = AdminLoginSerializer

    def post(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        return APIResponse.success(
            data=serializer.validated_data,
            message="Admin logged in.",
        )


class AdminDetailsAPIView(GenericAPIView):
    """
    Current admin details API.

    Frontend request:
    - Method: GET
    - Headers: authenticated bearer token from admin login.

    Frontend response:
    - 200 success with the current admin account summary.
    """

    permission_classes = [IsAuthenticated, IsAdmin]
    serializer_class = AdminDetailsSerializer

    def get(self, request, *args, **kwargs):
        return APIResponse.success(
            data=self.get_serializer(request.user).data,
            message="Admin details fetched successfully.",
        )


class UpdateAdminInfoAPIView(GenericAPIView):
    """Update the authenticated admin's full name and Cloudinary avatar."""

    permission_classes = [IsAuthenticated, IsAdmin]
    serializer_class = UpdateAdminInfoSerializer
    parser_classes = [MultiPartParser, FormParser, JSONParser]

    def patch(self, request, *args, **kwargs):
        serializer = self.get_serializer(
            request.user,
            data=request.data,
            partial=True,
            context={"request": request},
        )
        serializer.is_valid(raise_exception=True)
        admin = serializer.save()
        return APIResponse.success(
            data=AdminDetailsSerializer(admin).data,
            message="Admin information updated successfully.",
        )


class UpdateAdminPasswordAPIView(GenericAPIView):
    """Change the authenticated admin's password after current-password validation."""

    permission_classes = [IsAuthenticated, IsAdmin]
    serializer_class = UpdateAdminPasswordSerializer

    def patch(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return APIResponse.success(message="Admin password updated successfully.")


class AccountListAPIView(GenericAPIView):
    """
    Admin account list API.

    Frontend request:
    - Method: GET
    - Query params:
      `page`, `page_size`
      `search=john`
      `status=ACTIVE,PREMIUM`
      `is_email_verified=true`
      `public_profile=true`
    - Multiple filters can be combined in the same request.

    Frontend response:
    - 200 success with paginated account rows.
    - Staff and superadmin accounts are excluded.
    - Each row includes trip, credit, journal, general-chat message, and trip-chat
      message counts.
    """

    permission_classes = [IsAuthenticated, IsSuperAdmin]
    serializer_class = AccountListSerializer
    pagination_class = CustomPagination

    def get_queryset(self):
        integer_output = BigIntegerField()
        queryset = (
            User.objects.filter(is_staff=False, is_superuser=False)
            .select_related("profile")
            .annotate(
                trip_plan_count=Coalesce(
                    _related_count(Trip.objects.all(), user_field="user_id"),
                    Value(0),
                    output_field=integer_output,
                ),
                credit_balance=Coalesce(
                    Subquery(
                        UserCredit.objects.filter(user_id=OuterRef("pk")).values("balance")[:1],
                        output_field=integer_output,
                    ),
                    Value(0),
                    output_field=integer_output,
                ),
                chat_message_count=Coalesce(
                    _related_count(
                        ChatMessage.objects.all(),
                        user_field="session__user_id",
                    ),
                    Value(0),
                    output_field=integer_output,
                ),
                trip_message_count=Coalesce(
                    _related_count(
                        TripConversationMessage.objects.all(),
                        user_field="session__user_id",
                    ),
                    Value(0),
                    output_field=integer_output,
                ),
                journal_count=Coalesce(
                        _related_count(
                            Journal.objects.filter(deleted_at__isnull=True),
                            user_field="author_id",
                        ),
                    Value(0),
                    output_field=integer_output,
                ),
            )
            .order_by("-created_at")
        )

        search = self.request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(email__icontains=search)
                | Q(name__icontains=search)
                | Q(profile__username__icontains=search)
                | Q(profile__city__icontains=search)
                | Q(profile__country_of_residence__icontains=search)
            )

        statuses = self._get_multi_values("status")
        if statuses:
            queryset = queryset.filter(status__in=statuses)

        is_email_verified = self._get_boolean("is_email_verified")
        if is_email_verified is not None:
            queryset = queryset.filter(is_email_verified=is_email_verified)

        public_profile = self._get_boolean("public_profile")
        if public_profile is not None:
            queryset = queryset.filter(profile__is_public_profile=public_profile)

        return queryset

    def get(self, request, *args, **kwargs):
        queryset = self.get_queryset()
        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)
        serializer = self.get_serializer(page, many=True)
        return APIResponse.success(
            data=serializer.data,
            meta={
                "count": paginator.page.paginator.count,
                "page": paginator.page.number,
                "page_size": paginator.get_page_size(request),
                "num_pages": paginator.page.paginator.num_pages,
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
            },
            message="Accounts fetched successfully.",
        )

    def _get_multi_values(self, key):
        values = []
        for item in self.request.query_params.getlist(key):
            values.extend([part.strip() for part in str(item).split(",") if part.strip()])
        return values

    def _get_boolean(self, key):
        value = self.request.query_params.get(key)
        if value is None or value == "":
            return None
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
        return None


class AdminCreditRequestListAPIView(GenericAPIView):
    """Return all credit requests, newest first, with optional status filtering."""

    permission_classes = [IsAuthenticated, IsAdmin]
    serializer_class = AdminCreditRequestSerializer
    pagination_class = CustomPagination

    def get(self, request, *args, **kwargs):
        queryset = CreditRequest.objects.select_related(
            "user__profile", "reviewed_by__profile"
        )
        request_status = request.query_params.get("status")
        if request_status:
            valid_statuses = {choice.value for choice in CreditRequestStatus}
            if request_status not in valid_statuses:
                return APIResponse.error(
                    errors={"status": ["Invalid credit request status."]},
                    message="Invalid credit request status.",
                    status=status.HTTP_400_BAD_REQUEST,
                )
            queryset = queryset.filter(status=request_status)

        paginator = self.pagination_class()
        page = paginator.paginate_queryset(queryset, request, view=self)
        return APIResponse.success(
            data=self.get_serializer(page, many=True).data,
            meta={
                "count": paginator.page.paginator.count,
                "page": paginator.page.number,
                "page_size": paginator.get_page_size(request),
                "num_pages": paginator.page.paginator.num_pages,
                "next": paginator.get_next_link(),
                "previous": paginator.get_previous_link(),
            },
            message="Credit requests fetched successfully.",
        )


class AdminCreditRequestReviewAPIView(GenericAPIView):
    """Approve a pending request with credits, or reject it."""

    permission_classes = [IsAuthenticated, IsAdmin]
    serializer_class = ReviewCreditRequestSerializer

    def patch(self, request, pk, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        with transaction.atomic():
            credit_request = get_object_or_404(
                CreditRequest.objects.select_for_update(of=("self",)).select_related(
                    "user__profile", "reviewed_by__profile"
                ),
                pk=pk,
            )
            if credit_request.status != CreditRequestStatus.PENDING:
                return APIResponse.error(
                    errors={"detail": ["This credit request has already been reviewed."]},
                    message="This credit request has already been reviewed.",
                    status=status.HTTP_400_BAD_REQUEST,
                )

            action = serializer.validated_data["action"]
            credit_request.status = (
                CreditRequestStatus.APPROVED
                if action == "approve"
                else CreditRequestStatus.REJECTED
            )
            credit_request.reviewed_by = request.user
            credit_request.reviewed_at = timezone.now()
            update_fields = ["status", "reviewed_by", "reviewed_at", "updated_at"]

            if action == "approve":
                amount = serializer.validated_data["amount"]
                credit_transaction = CreditService.add_credits(
                    user=credit_request.user,
                    amount=amount,
                    transaction_type=CreditTransactionType.ADMIN_ADJUSTMENT,
                    description="Approved credit request",
                    metadata={"credit_request_id": str(credit_request.id)},
                )
                credit_request.approved_amount = amount
                credit_request.credit_transaction = credit_transaction
                update_fields.extend(["approved_amount", "credit_transaction"])

            credit_request.save(update_fields=update_fields)

        return APIResponse.success(
            data=AdminCreditRequestSerializer(credit_request).data,
            message=f"Credit request {credit_request.status} successfully.",
        )
