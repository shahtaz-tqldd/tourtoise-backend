import csv
import io
from datetime import date

from django.db.models import Prefetch
from django.http import HttpResponse

from destinations.api.v1.admin.serializers import (
    BULK_ACTIVITY_TEMPLATE,
    BULK_ATTRACTION_TEMPLATE,
    BULK_CUISINE_TEMPLATE,
    BULK_DESTINATION_TEMPLATE,
)
from destinations.models import Activity, Attraction, Cuisine, Destination


RESOURCE_ALIASES = {
    "destination": "destinations",
    "destinations": "destinations",
    "activity": "activities",
    "activities": "activities",
    "attraction": "attractions",
    "attractions": "attractions",
    "cuisine": "cuisines",
    "cuisines": "cuisines",
}

CHILD_CONFIG = {
    "attractions": (Attraction, BULK_ATTRACTION_TEMPLATE),
    "activities": (Activity, BULK_ACTIVITY_TEMPLATE),
    "cuisines": (Cuisine, BULK_CUISINE_TEMPLATE),
}


def build_bulk_download(*, resource, file_format, selected_ids):
    """Build a response whose rows can be consumed by the matching bulk uploader."""
    if resource == "destinations":
        rows_by_sheet = _destination_rows(selected_ids)
        template = BULK_DESTINATION_TEMPLATE
    else:
        rows_by_sheet, template = _child_rows(resource, selected_ids)

    if file_format == "csv":
        content = _csv_content(resource, template, rows_by_sheet)
        content_type = "text/csv; charset=utf-8"
    else:
        content = _xlsx_content(template, rows_by_sheet)
        content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

    filename = f"tourtoise-{resource}-{date.today().isoformat()}.{file_format}"
    response = HttpResponse(content, content_type=content_type)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def _destination_rows(selected_ids):
    attraction_queryset = _child_queryset(Attraction, selected_ids.get("attraction_ids"))
    activity_queryset = _child_queryset(Activity, selected_ids.get("activity_ids"))
    cuisine_queryset = _child_queryset(Cuisine, selected_ids.get("cuisine_ids"))

    queryset = Destination.objects.all()
    if selected_ids.get("destination_ids"):
        queryset = queryset.filter(id__in=selected_ids["destination_ids"])
    destinations = queryset.prefetch_related(
        "tags",
        "images",
        Prefetch("attractions", queryset=attraction_queryset, to_attr="bulk_attractions"),
        Prefetch("activities", queryset=activity_queryset, to_attr="bulk_activities"),
        Prefetch("cuisines", queryset=cuisine_queryset, to_attr="bulk_cuisines"),
    )

    rows = {name: [] for name in BULK_DESTINATION_TEMPLATE["xlsx_sheets"]}
    for destination in destinations:
        rows["destinations"].append(_destination_row(destination))
        rows["attractions"].extend(
            _child_row(item, destination.slug) for item in destination.bulk_attractions
        )
        rows["activities"].extend(
            _child_row(item, destination.slug) for item in destination.bulk_activities
        )
        rows["cuisines"].extend(
            _child_row(item, destination.slug) for item in destination.bulk_cuisines
        )
    return rows


def _child_queryset(model, ids=None):
    queryset = model.objects.all().prefetch_related("images")
    if model is Attraction:
        queryset = queryset.prefetch_related("tags")
    if ids:
        queryset = queryset.filter(id__in=ids)
    return queryset


def _child_rows(resource, selected_ids):
    model, template = CHILD_CONFIG[resource]
    id_key = {
        "attractions": "attraction_ids",
        "activities": "activity_ids",
        "cuisines": "cuisine_ids",
    }[resource]
    queryset = _child_queryset(model, selected_ids.get(id_key)).select_related("destination")
    if selected_ids.get("destination_ids"):
        queryset = queryset.filter(destination_id__in=selected_ids["destination_ids"])
    return {resource: [_child_row(item) for item in queryset]}, template


def _destination_row(destination):
    return {
        "record_type": "destination",
        "destination_key": destination.slug,
        "name": destination.name,
        "country": destination.country,
        "country_code": destination.country_code,
        "region": destination.region,
        "destination_type": destination.destination_type,
        "latitude": destination.latitude,
        "longitude": destination.longitude,
        "tagline": destination.tagline,
        "description": destination.description,
        "cover_image": destination.cover_image,
        **_image_values(destination),
        "tags": _tags(destination),
        "min_stay_days": destination.min_stay_days,
        "max_stay_days": destination.max_stay_days,
        "budget_tier": destination.budget_tier,
        "difficulty_level": destination.difficulty_level,
        "local_languages": _joined(destination.local_languages),
        "best_travel_months": _joined(destination.best_travel_months),
        "currency": destination.currency,
        "currency_code": destination.currency_code,
        "getting_around": destination.getting_around,
        "visa_notes": destination.visa_notes,
        "notes": _joined(destination.notes),
        "picking_reasons": _joined(destination.picking_reasons),
        "status": destination.status,
    }


def _child_row(item, destination_key=None):
    row = {
        "record_type": item._meta.model_name,
        "destination_key": destination_key or item.destination.slug,
        "name": item.name,
        "description": item.description,
        "cover_image": item.cover_image,
        **_image_values(item),
        "picking_reasons": _joined(item.picking_reasons),
        "notes": _joined(item.notes),
        "is_featured": _boolean(item.is_featured),
    }
    if isinstance(item, Attraction):
        row.update(
            {
                "attraction_type": item.attraction_type,
                "how_to_reach": item.how_to_reach,
                "latitude": item.latitude,
                "longitude": item.longitude,
                "address": item.address,
                "tags": _tags(item),
                "budget_tier": item.budget_tier,
                "avg_duration_hours": item.avg_duration_hours,
                "best_time_of_day": item.best_time_of_day,
                "best_months": _joined(item.best_months),
                "entrance_fee_required": _boolean(item.entrance_fee_required),
                "approx_entrance_fee": item.approx_entrance_fee,
                "sort_order": item.sort_order,
            }
        )
    elif isinstance(item, Activity):
        row.update(
            {
                "activity_type": item.activity_type,
                "difficulty_level": item.difficulty_level,
                "budget_tier": item.budget_tier,
                "approx_cost": item.approx_cost,
                "duration_hours": item.duration_hours,
                "best_months": _joined(item.best_months),
                "booking_required": _boolean(item.booking_required),
            }
        )
    else:
        row.update(
            {
                "cuisine_type": item.cuisine_type,
                "spice_level": item.spice_level,
                "meal_type": item.meal_type,
                "is_vegetarian_friendly": _boolean(item.is_vegetarian_friendly),
                "approx_cost": item.approx_cost,
            }
        )
    return row


def _image_values(item):
    images = list(item.images.all())
    return {
        "image_urls": _joined(image.image_url for image in images),
        "image_captions": _joined(image.caption for image in images),
    }


def _tags(item):
    return _joined(f"{tag.name}:{tag.category}" for tag in item.tags.all())


def _joined(values):
    return ";".join(str(value) for value in (values or []) if value not in (None, ""))


def _boolean(value):
    return "true" if value else "false"


def _csv_content(resource, template, rows_by_sheet):
    output = io.StringIO(newline="")
    writer = csv.writer(output)
    columns = template["csv_columns"]
    writer.writerow(columns)
    if resource == "destinations":
        for sheet_name in ("destinations", "attractions", "activities", "cuisines"):
            for row in rows_by_sheet[sheet_name]:
                writer.writerow([_cell(row.get(column)) for column in columns])
    else:
        for row in rows_by_sheet[resource]:
            writer.writerow([_cell(row.get(column)) for column in columns])
    return "\ufeff" + output.getvalue()


def _xlsx_content(template, rows_by_sheet):
    from openpyxl import Workbook

    workbook = Workbook(write_only=True)
    for sheet_name, columns in template["xlsx_sheets"].items():
        worksheet = workbook.create_sheet(title=sheet_name)
        worksheet.append(columns)
        for row in rows_by_sheet.get(sheet_name, []):
            worksheet.append([_cell(row.get(column)) for column in columns])
    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


def _cell(value):
    return "" if value is None else value
