from django.db.models import Q


def get_multi_value_query_param(query_params, key):
    values = []
    for item in query_params.getlist(key):
        if item is None:
            continue
        values.extend([part.strip() for part in str(item).split(",") if part.strip()])
    return values


def apply_destination_filters(queryset, query_params, *, include_status=False):
    search = query_params.get("search", "").strip()
    if search:
        queryset = queryset.filter(
            Q(name__icontains=search)
            | Q(country__icontains=search)
            | Q(region__icontains=search)
            | Q(tagline__icontains=search)
            | Q(description__icontains=search)
            | Q(tags__name__icontains=search)
        )

    destination_types = get_multi_value_query_param(query_params, "destination_type")
    if destination_types:
        queryset = queryset.filter(destination_type__in=destination_types)

    countries = get_multi_value_query_param(query_params, "country_code")
    if countries:
        queryset = queryset.filter(country_code__in=countries)

    budget_tiers = get_multi_value_query_param(query_params, "budget_tier")
    if budget_tiers:
        queryset = queryset.filter(budget_tier__in=budget_tiers)

    difficulties = (
        get_multi_value_query_param(query_params, "difficulty_level")
        or get_multi_value_query_param(query_params, "difficulty")
    )
    if difficulties:
        queryset = queryset.filter(difficulty_level__in=difficulties)

    tag_slugs = get_multi_value_query_param(query_params, "tag")
    if tag_slugs:
        queryset = queryset.filter(tags__slug__in=tag_slugs)

    months = []
    for item in get_multi_value_query_param(query_params, "best_travel_month"):
        try:
            month = int(item)
        except (TypeError, ValueError):
            continue
        if 1 <= month <= 12:
            months.append(month)
    if months:
        queryset = queryset.filter(best_travel_months__overlap=months)

    regions = get_multi_value_query_param(query_params, "region")
    if regions:
        queryset = queryset.filter(region__in=regions)

    if include_status:
        statuses = get_multi_value_query_param(query_params, "status")
        if statuses:
            queryset = queryset.filter(status__in=statuses)

    return queryset.distinct()


def _apply_search_filter(queryset, search, fields):
    if not search:
        return queryset

    condition = Q()
    for field in fields:
        condition |= Q(**{f"{field}__icontains": search})
    return queryset.filter(condition)


def _apply_multi_value_filter(queryset, query_params, parameter, field=None):
    values = get_multi_value_query_param(query_params, parameter)
    if values:
        queryset = queryset.filter(**{f"{field or parameter}__in": values})
    return queryset


def _get_boolean_query_param(query_params, *parameters):
    for parameter in parameters:
        value = query_params.get(parameter)
        if value is None:
            continue
        normalized_value = value.strip().lower()
        if normalized_value in {"true", "1", "yes"}:
            return True
        if normalized_value in {"false", "0", "no"}:
            return False
    return None


def apply_attraction_filters(queryset, query_params):
    """Apply client-facing filters to a destination's attractions."""
    queryset = _apply_search_filter(
        queryset,
        query_params.get("search", "").strip(),
        ("name", "description", "address"),
    )
    for parameter in ("attraction_type", "budget_tier", "best_time_of_day"):
        queryset = _apply_multi_value_filter(queryset, query_params, parameter)

    entrance_fee_required = _get_boolean_query_param(query_params, "entrance_fee_required")
    if entrance_fee_required is not None:
        queryset = queryset.filter(entrance_fee_required=entrance_fee_required)
    is_featured = _get_boolean_query_param(query_params, "is_featured", "featured")
    if is_featured is not None:
        queryset = queryset.filter(is_featured=is_featured)
    return queryset


def apply_activity_filters(queryset, query_params):
    """Apply client-facing filters to a destination's activities."""
    queryset = _apply_search_filter(
        queryset,
        query_params.get("search", "").strip(),
        ("name", "description"),
    )
    for parameter in ("activity_type", "budget_tier", "difficulty_level"):
        queryset = _apply_multi_value_filter(queryset, query_params, parameter)
    queryset = _apply_multi_value_filter(queryset, query_params, "difficulty", "difficulty_level")

    booking_required = _get_boolean_query_param(query_params, "booking_required")
    if booking_required is not None:
        queryset = queryset.filter(booking_required=booking_required)
    is_featured = _get_boolean_query_param(query_params, "is_featured", "featured")
    if is_featured is not None:
        queryset = queryset.filter(is_featured=is_featured)
    return queryset


def apply_cuisine_filters(queryset, query_params):
    """Apply client-facing filters to a destination's cuisines."""
    queryset = _apply_search_filter(
        queryset,
        query_params.get("search", "").strip(),
        ("name", "cuisine_type", "description"),
    )
    for parameter in ("cuisine_type", "spice_level", "meal_type"):
        queryset = _apply_multi_value_filter(queryset, query_params, parameter)

    for parameter, aliases in (
        ("is_vegetarian_friendly", ("is_vegetarian_friendly", "vegetarian_friendly")),
        ("is_featured", ("is_featured", "featured")),
    ):
        value = _get_boolean_query_param(query_params, *aliases)
        if value is not None:
            queryset = queryset.filter(**{parameter: value})
    return queryset
