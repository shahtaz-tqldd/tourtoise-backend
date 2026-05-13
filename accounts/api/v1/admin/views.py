from django.db.models import Q
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated

from app.base.pagination import CustomPagination
from app.utils.response import APIResponse
from accounts.api.v1.admin.serializers import AccountListSerializer
from accounts.models import User
from accounts.permissions import IsSuperAdmin


class AccountListAPIView(GenericAPIView):
    """
    Admin account list API.

    Frontend request:
    - Method: GET
    - Query params:
      `page`, `page_size`
      `search=john`
      `status=ACTIVE,PREMIUM`
      `travel_style=ADVENTURE,BUDGET`
      `is_staff=true`
      `is_superuser=false`
      `is_email_verified=true`
      `public_profile=true`
    - Multiple filters can be combined in the same request.

    Frontend response:
    - 200 success with paginated account rows.
    - Each row includes `id`, profile summary fields, access flags, and last activity metadata.
    """

    permission_classes = [IsAuthenticated, IsSuperAdmin]
    serializer_class = AccountListSerializer
    pagination_class = CustomPagination

    def get_queryset(self):
        queryset = User.objects.select_related("profile").order_by("-created_at")

        search = self.request.query_params.get("search", "").strip()
        if search:
            queryset = queryset.filter(
                Q(email__icontains=search)
                | Q(name__icontains=search)
                | Q(phone__icontains=search)
                | Q(profile__username__icontains=search)
                | Q(profile__city__icontains=search)
                | Q(profile__country_of_residence__icontains=search)
            )

        statuses = self._get_multi_values("status")
        if statuses:
            queryset = queryset.filter(status__in=statuses)

        travel_styles = self._get_multi_values("travel_style")
        if travel_styles:
            queryset = queryset.filter(profile__travel_style__in=travel_styles)

        is_staff = self._get_boolean("is_staff")
        if is_staff is not None:
            queryset = queryset.filter(is_staff=is_staff)

        is_superuser = self._get_boolean("is_superuser")
        if is_superuser is not None:
            queryset = queryset.filter(is_superuser=is_superuser)

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
