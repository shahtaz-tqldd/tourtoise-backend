from datetime import date

from rest_framework import serializers


class UserGrowthQuerySerializer(serializers.Serializer):
    month = serializers.RegexField(
        regex=r"^\d{4}-(0[1-9]|1[0-2])$",
        required=False,
        help_text="Optional month in YYYY-MM format.",
    )

    def validate_month(self, value):
        year, month = map(int, value.split("-"))
        if year == 9999:
            raise serializers.ValidationError("Month must be earlier than 9999-01.")
        try:
            return date(year, month, 1)
        except ValueError as exc:
            raise serializers.ValidationError("Enter a valid month in YYYY-MM format.") from exc
