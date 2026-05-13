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
            | Q(overview__icontains=search)
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

    difficulties = get_multi_value_query_param(query_params, "difficulty")
    if difficulties:
        queryset = queryset.filter(difficulty__in=difficulties)

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

        data_sources = get_multi_value_query_param(query_params, "data_source")
        if data_sources:
            queryset = queryset.filter(data_source__in=data_sources)

    return queryset.distinct()
