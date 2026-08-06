from calendar import monthrange
from datetime import date, datetime, time, timedelta

from django.db.models import Count
from django.db.models.functions import TruncDate, TruncMonth
from django.utils import timezone
from rest_framework.generics import GenericAPIView
from rest_framework.permissions import IsAuthenticated

from accounts.models import User
from accounts.permissions import IsSuperAdmin
from analytics.api.v1.admin.serializers import UserGrowthQuerySerializer
from app.utils.response import APIResponse
from chat.models import ChatMessage
from journals.models import Journal
from trips.choices import TripStatus
from trips.models import Trip, TripConversationMessage


def _month_start(value):
    return value.replace(day=1)


def _shift_month(value, months):
    month_index = value.year * 12 + value.month - 1 + months
    return date(month_index // 12, month_index % 12 + 1, 1)


def _aware_start(value):
    value = datetime.combine(value, time.min)
    return timezone.make_aware(value, timezone.get_current_timezone())


def _growth_percentage(queryset, now):
    current_start = now - timedelta(days=30)
    previous_start = now - timedelta(days=60)
    current_count = queryset.filter(created_at__gte=current_start, created_at__lt=now).count()
    previous_count = queryset.filter(
        created_at__gte=previous_start,
        created_at__lt=current_start,
    ).count()

    if previous_count == 0:
        return 100.0 if current_count else 0.0
    return round(((current_count - previous_count) / previous_count) * 100, 2)


class OverviewStatsAPIView(GenericAPIView):
    """Dashboard totals, current-month activity, and rolling 30-day growth."""

    permission_classes = [IsAuthenticated, IsSuperAdmin]

    def get(self, request, *args, **kwargs):
        now = timezone.now()
        current_month_start = _aware_start(_month_start(timezone.localdate()))

        users = User.objects.all()
        trips = Trip.objects.all()
        journals = Journal.objects.all()
        chat_messages = ChatMessage.objects.all()
        trip_messages = TripConversationMessage.objects.all()

        chat_total = chat_messages.count()
        trip_message_total = trip_messages.count()
        chat_this_month = chat_messages.filter(
            created_at__gte=current_month_start,
            created_at__lt=now,
        ).count()
        trip_messages_this_month = trip_messages.filter(
            created_at__gte=current_month_start,
            created_at__lt=now,
        ).count()

        # The combined percentage is calculated from the combined message counts,
        # rather than averaging the two models' individual percentages.
        current_30_start = now - timedelta(days=30)
        previous_30_start = now - timedelta(days=60)
        current_message_count = (
            chat_messages.filter(created_at__gte=current_30_start, created_at__lt=now).count()
            + trip_messages.filter(created_at__gte=current_30_start, created_at__lt=now).count()
        )
        previous_message_count = (
            chat_messages.filter(created_at__gte=previous_30_start, created_at__lt=current_30_start).count()
            + trip_messages.filter(created_at__gte=previous_30_start, created_at__lt=current_30_start).count()
        )
        if previous_message_count == 0:
            message_growth = 100.0 if current_message_count else 0.0
        else:
            message_growth = round(
                ((current_message_count - previous_message_count) / previous_message_count) * 100,
                2,
            )

        return APIResponse.success(
            data={
                "users": {
                    "total": users.count(),
                    "this_month": users.filter(
                        created_at__gte=current_month_start,
                        created_at__lt=now,
                    ).count(),
                    "growth_percentage_30_days": _growth_percentage(users, now),
                },
                "trips": {
                    "total_planned": trips.count(),
                    "completed": trips.filter(status=TripStatus.COMPLETED).count(),
                    "growth_percentage_30_days": _growth_percentage(trips, now),
                },
                "journals": {
                    "total": journals.count(),
                    "this_month": journals.filter(
                        created_at__gte=current_month_start,
                        created_at__lt=now,
                    ).count(),
                    "growth_percentage_30_days": _growth_percentage(journals, now),
                },
                "ai_messages": {
                    "total": chat_total + trip_message_total,
                    "this_month": chat_this_month + trip_messages_this_month,
                    "growth_percentage_30_days": message_growth,
                },
            },
            message="Overview stats fetched successfully.",
        )


class UserGrowthAPIView(GenericAPIView):
    """User registrations by month, or by day when `month=YYYY-MM` is supplied."""

    permission_classes = [IsAuthenticated, IsSuperAdmin]
    serializer_class = UserGrowthQuerySerializer

    def get(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        selected_month = serializer.validated_data.get("month")

        if selected_month:
            data = self._daily_growth(selected_month)
            granularity = "day"
        else:
            data = self._monthly_growth()
            granularity = "month"

        return APIResponse.success(
            data={"granularity": granularity, "points": data},
            message="User growth fetched successfully.",
        )

    def _monthly_growth(self):
        current_month = _month_start(timezone.localdate())
        first_month = _shift_month(current_month, -11)
        end_month = _shift_month(current_month, 1)
        counts = {
            item["period"]: item["count"]
            for item in User.objects.filter(
                created_at__gte=_aware_start(first_month),
                created_at__lt=_aware_start(end_month),
            )
            .annotate(period=TruncMonth("created_at"))
            .values("period")
            .annotate(count=Count("id"))
            .order_by("period")
        }

        points = []
        for offset in range(12):
            period = _shift_month(first_month, offset)
            aware_period = _aware_start(period)
            points.append(
                {
                    "period": period.strftime("%Y-%m"),
                    "label": period.strftime("%b %Y"),
                    "count": counts.get(aware_period, 0),
                }
            )
        return points

    def _daily_growth(self, selected_month):
        next_month = _shift_month(selected_month, 1)
        counts = {
            item["period"]: item["count"]
            for item in User.objects.filter(
                created_at__gte=_aware_start(selected_month),
                created_at__lt=_aware_start(next_month),
            )
            .annotate(period=TruncDate("created_at"))
            .values("period")
            .annotate(count=Count("id"))
            .order_by("period")
        }

        return [
            {
                "period": selected_month.replace(day=day).isoformat(),
                "label": str(day),
                "count": counts.get(selected_month.replace(day=day), 0),
            }
            for day in range(1, monthrange(selected_month.year, selected_month.month)[1] + 1)
        ]
