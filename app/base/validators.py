from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from django.core.exceptions import ValidationError


def validate_timezone_name(value):
    try:
        ZoneInfo(value)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise ValidationError("Enter a valid IANA timezone, such as Asia/Dhaka.") from exc


def validate_bio_word_count(value):
    if len(value.split()) > 60:
        raise ValidationError(
            "Bio cannot contain more than 60 words.",
            code="max_words",
        )
