# Trip Planning Frontend API

Base path: `/api/v1/trips/`

All endpoints require an authenticated user. Responses use the common wrapper:

```json
{
  "status": 200,
  "success": true,
  "message": "Message",
  "data": {}
}
```

## Planning Flow

Planning steps are sequential:

1. `preference` - activate the planning agent and complete preference Q&A.
2. `recommendation` - generate attraction, activity, and cuisine recommendations.
3. `itinerary` - generate day-wise itinerary, route plan, and rough budget.
4. `preparation` - generate packing, documents, and heads-up checklist.
5. `overview` - review the plan and activate it.

Every planning step response may include:

```json
{
  "progress": {
    "current_step": "recommendation",
    "agent_active": true,
    "is_qna_complete": true,
    "is_recommendation_complete": false,
    "is_itinerary_design_complete": false,
    "is_trip_preparation_complete": false
  },
  "flow": [
    {
      "step": "preference",
      "label": "Preference Q&A",
      "is_complete": true,
      "is_current": false,
      "can_open": true,
      "can_generate": false
    }
  ],
  "activation": {
    "can_activate": false,
    "blocking_steps": ["Generate the trip itinerary."]
  }
}
```

## Trip List For Destination

Use the normal trip list endpoint. The backend supports filtering by destination slug.

`GET /api/v1/trips/list/?destination_slug=paris`

Response item shape:

```json
{
  "id": "uuid",
  "title": "Paris Weekend",
  "status": "draft",
  "visibility": "private",
  "start_date": "2026-09-01",
  "end_date": "2026-09-04",
  "nights": 3,
  "duration_days": 4,
  "travelers_count": 2,
  "traveler_type": "couple",
  "primary_destination": {
    "name": "Paris",
    "country": "France",
    "region": "Ile-de-France",
    "cover_image": "https://..."
  },
  "share_url": null
}
```

## Short Trip Details

`GET /api/v1/trips/{trip_id}/short-details/`

Use this for a compact planning header or trip card.

```json
{
  "id": "uuid",
  "title": "Paris Weekend",
  "status": "draft",
  "visibility": "private",
  "current_step": "preference",
  "start_date": "2026-09-01",
  "end_date": "2026-09-04",
  "duration_days": 4,
  "budget_tier": "comfort",
  "budget_currency": "USD",
  "travelers_count": 2,
  "traveler_type": "couple",
  "preferences": {},
  "start_location": {
    "address": "Hotel address",
    "city": "Dhaka",
    "country": "Bangladesh",
    "longitude": 90.4125,
    "latitude": 23.8103
  },
  "trip_destinations": [],
  "planning_stats": {
    "agent_active": true,
    "is_qna_complete": false,
    "is_recommendation_complete": false,
    "is_itinerary_design_complete": false,
    "is_trip_preparation_complete": false
  }
}
```

## Activate Planning Agent

`POST /api/v1/trips/planning/agent-init/`

Call after the user creates a trip and provides initial preferences.

Request:

```json
{
  "trip_id": "uuid",
  "let_agent_decide": false,
  "travel_pace": "balanced",
  "accommodation_preference": "mid_range",
  "interest_tags": ["history", "local food", "nature"],
  "dietary_needs": ["halal"],
  "dietary_other": "",
  "mobility_constraints": ["avoid long stairs"],
  "mobility_other": ""
}
```

Response:

```json
{
  "session_id": "uuid",
  "agent_active": true,
  "preferences": {
    "session_id": "uuid",
    "travel_pace": "balanced",
    "dietary_needs": ["halal"],
    "interest_tags": ["history", "local food", "nature"],
    "mobility_constraints": ["avoid long stairs"],
    "accommodation_preference": "mid_range",
    "accommotation_preference": "mid_range"
  },
  "agent_message": "What would make this trip feel successful?",
  "is_step_complete": false,
  "is_qna_complete": false,
  "progress": {},
  "flow": []
}
```

## Create Preference Message

`POST /api/v1/trips/planning/create-message/`

Request:

```json
{
  "trip_id": "uuid",
  "session_id": "uuid",
  "message": "I want a relaxed trip with food, neighborhoods, and one scenic place per day."
}
```

Response:

```json
{
  "session_id": "uuid",
  "agent_message": "short agent question or completed context",
  "is_step_complete": true,
  "is_qna_complete": true,
  "progress": {},
  "flow": []
}
```

When `is_qna_complete` becomes `true`, move the UI to `recommendation`.

## Get Planning Step

`GET /api/v1/trips/planning/?trip_id={trip_id}&step={step}`

Valid `step` values:

- `preference`
- `recommendation`
- `itinerary`
- `preparation`
- `overview`

### Preference

Returns the latest preference session and messages.

```json
{
  "session": {
    "id": "uuid",
    "step": "preference",
    "is_active": true,
    "external_session_id": "adk-session-id"
  },
  "preferences": {},
  "agent_active": true,
  "is_step_complete": false,
  "is_qna_complete": false,
  "messages": [
    {
      "id": "uuid",
      "session_id": "uuid",
      "sender": "agent",
      "content": "Question text",
      "created_at": "2026-07-22T10:00:00Z"
    }
  ],
  "progress": {},
  "flow": []
}
```

### Recommendation

Requires preference Q&A completion. The first call generates and saves recommendations; later calls return saved data.

```json
{
  "is_recommendation_complete": true,
  "attractions": [],
  "activities": [],
  "cuisines": [],
  "messages": {
    "attractions": "I picked scenic and cultural places that fit your pace.",
    "activities": "These activities match your interests and budget.",
    "cuisines": "These food picks respect your dietary preferences."
  },
  "session_id": "uuid",
  "external_session_id": "adk-session-id",
  "progress": {},
  "flow": [],
  "activation": {}
}
```

### Itinerary

Requires recommendations. The first call generates and saves itinerary data.

```json
{
  "id": "uuid",
  "title": "Balanced Paris Plan",
  "summary": "A relaxed city plan with food, culture, and scenic breaks.",
  "message": "I created a balanced day-wise plan.",
  "session_id": "uuid",
  "external_session_id": "adk-session-id",
  "route_plan_items": [
    {
      "id": 1,
      "date": "2026-09-01",
      "from_point": "Hotel",
      "to_point": "Louvre Museum",
      "start_time": "09:00:00",
      "transport_mode": "metro",
      "estimated_duration": "0:25:00",
      "estimated_cost": "3.00",
      "notes": "Approximate fare."
    }
  ],
  "itinerary_days": [
    {
      "id": 1,
      "day": 1,
      "date": "2026-09-01",
      "title": "Culture and cafes",
      "summary": "A low-stress first day.",
      "day_items": [
        {
          "id": 1,
          "time": "09:30:00",
          "title": "Louvre Museum",
          "item_type": "attraction",
          "item_id": "uuid",
          "description": "Visit selected highlights.",
          "estimated_cost": "25.00",
          "notes": "Book ahead."
        }
      ]
    }
  ],
  "rough_budget": {
    "transport": "30.00",
    "food": "180.00",
    "activities": "120.00",
    "tickets_or_entry": "80.00",
    "miscellaneous": "50.00",
    "total_estimated_budget": "460.00",
    "budget_note": "Approximate estimate."
  },
  "progress": {},
  "flow": [],
  "activation": {}
}
```

### Preparation

Requires itinerary generation.

```json
{
  "id": "uuid",
  "title": "Paris Preparation",
  "summary": "Documents, packing, and practical notes for the trip.",
  "message": "I prepared a practical checklist.",
  "packing_items": [
    {
      "id": "uuid",
      "item": "Comfortable walking shoes",
      "quantity": 1,
      "category": "clothing",
      "priority": "essential",
      "sort_order": 1,
      "additional_notes": "Useful for walkable neighborhoods."
    }
  ],
  "required_documents": [
    {
      "id": "uuid",
      "document_name": "Passport",
      "document": null,
      "required_level": "conditional",
      "sort_order": 1,
      "additional_note": "Needed for international travel."
    }
  ],
  "heads_up": [
    {
      "id": "uuid",
      "title": "Museum booking",
      "category": "timing",
      "severity": "medium",
      "sort_order": 1,
      "additional_note": "Popular museums may need advance booking."
    }
  ],
  "progress": {},
  "flow": [],
  "activation": {}
}
```

### Overview

Use this as the final review screen.

```json
{
  "trip": {},
  "destinations": [],
  "planning_progress": {
    "current_step": "overview",
    "is_qna_complete": true,
    "is_recommendation_complete": true,
    "is_itinerary_complete": true,
    "is_preparation_complete": true
  },
  "flow": [],
  "recommendations_overview": {
    "attractions_count": 5,
    "activities_count": 3,
    "cuisines_count": 4
  },
  "itinerary_overview": {
    "title": "Balanced Paris Plan",
    "summary": "A relaxed city plan.",
    "days_count": 4,
    "route_legs_count": 8,
    "total_estimated_budget": "460.00",
    "budget_note": "Approximate estimate."
  },
  "preparation_overview": {
    "title": "Paris Preparation",
    "summary": "Practical checklist.",
    "packing_items_count": 12,
    "documents_count": 6,
    "heads_up_count": 8
  },
  "activation": {
    "can_activate": true,
    "target_status": "ready",
    "blocking_steps": []
  }
}
```

## Activate Trip

`POST /api/v1/trips/planning/activate/`

Request:

```json
{
  "trip_id": "uuid"
}
```

Response:

```json
{
  "id": "uuid",
  "status": "ready",
  "current_step": "completed"
}
```

Activation requires:

- trip status is `draft` or `planning`
- itinerary exists
- preparation exists

If activation is blocked:

```json
{
  "status": 400,
  "success": false,
  "message": "Generate the trip itinerary.",
  "errors": {
    "blocking_steps": ["Generate the trip itinerary."]
  }
}
```
