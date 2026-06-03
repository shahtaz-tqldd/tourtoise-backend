# AI Trip Planning Feature — User Flow & Product Design

## Overview

This feature allows users to create an end-to-end travel plan for a selected destination with the help of an AI travel agent.

The journey starts from a destination detail page. The user provides basic trip parameters, the agent collects qualitative travel preferences, recommends suitable places/foods/activities, builds a day-wise itinerary, generates a pre-trip checklist, and finally saves the completed trip plan to the user’s account.

The goal is to make trip planning feel guided, personal, editable, and practical.

---

# Core User Journey

```text
Destination Details
    ↓
Stage 1: Trip Parameters
    ↓
Stage 2: Traveller Profile
    ↓
Stage 3: Spots, Food & Activities
    ↓
Stage 4: Day-wise Itinerary
    ↓
Stage 5: Pre-trip Checklist
    ↓
Stage 6: Summary & Save
    ↓
My Trips Dashboard
```

---

# Entry Point

## Destination Details Page

The user visits a destination page where they can see basic information about the destination.

Example information:

* Destination name
* Short description
* Best time to visit
* Estimated budget range
* Recommended duration
* Popular experiences
* Weather notes
* Travel tips
* Safety or visa notes, if applicable

Primary CTA:

```text
Start Planning Trip
```

When the user clicks this button, the trip planning flow begins.

---

# Stage 1 — Trip Parameters

## Purpose

This stage collects structured trip data required to start planning.

This should feel like a simple form, not a conversation. The goal is to collect the minimum required details before the agent begins planning.

---

## Input Fields

### Destination

Pre-filled from the destination detail page.

Example:

```text
Bali, Indonesia
```

The user may not need to edit this unless destination switching is supported.

---

### Start Date

The user selects the trip start date.

Used for:

* Season-aware recommendations
* Weather-sensitive planning
* Availability assumptions
* Checklist deadlines
* Passport/visa validity checks

---

### Duration in Days

The user enters or selects the number of trip days.

Used for:

* Itinerary length
* Activity distribution
* Route pacing
* Budget estimation

Example:

```text
5 days
```

---

### Traveller Type

The user selects the type of trip.

Options:

* Solo
* Couple
* Family
* Group

This affects activity recommendations, accommodation suggestions, pacing, safety notes, and food choices.

---

### Traveller Count

Traveller count should behave dynamically.

Rules:

* If traveller type is `Solo`, traveller count is automatically set to `1`.
* If traveller type is `Couple`, traveller count is automatically set to `2`.
* If traveller type is `Family` or `Group`, show a traveller count field.

Example:

```text
Traveller type: Family
Traveller count: 4
```

---

### Total Budget

The user enters their total estimated budget for the trip.

Budget should include a currency dropdown.

Example:

```text
Budget: 1200 USD
```

Currency options can include:

* USD
* EUR
* GBP
* BDT
* INR
* THB
* IDR
* SGD
* AED

The budget will be used later to control recommendations and validate the selected shortlist.

---

### Accommodation Preference

The user selects their preferred accommodation style.

Options:

* Budget hotel
* Mid-range hotel
* Luxury hotel
* Resort
* Hostel
* Apartment / Airbnb-style stay
* Family-friendly stay
* No preference

This helps the agent estimate cost and recommend suitable stay areas.

---

## Stage Output

At the end of Stage 1, the system stores the structured trip setup.

Example output:

```json
{
  "destination": "Bali, Indonesia",
  "start_date": "2026-08-10",
  "duration_days": 5,
  "traveller_type": "Couple",
  "traveller_count": 2,
  "budget": {
    "amount": 1200,
    "currency": "USD"
  },
  "accommodation_preference": "Mid-range hotel"
}
```

CTA:

```text
Continue
```

---

# Stage 2 — Traveller Profile

## Purpose

This is where the agent starts interacting with the user.

The goal is to understand the user’s qualitative travel preferences: how they like to travel, what they care about, and what constraints the plan must respect.

This stage should feel conversational, lightweight, and personalized.

---

## Agent Opening Message

Example:

```text
Great. I have your basic trip details.

Now I’ll understand what kind of trip experience you want so I can recommend the right places, food, activities, and pace.
```

---

## Preference Inputs

### Travel Pace

Options:

* Relaxed
* Moderate
* Packed

Meaning:

* `Relaxed`: fewer activities, more rest time, slower movement.
* `Moderate`: balanced plan with enough activities and breathing room.
* `Packed`: more attractions and activities per day.

---

### Interest Tags

The user selects interests from a list.

Options:

* Food
* History
* Nature
* Nightlife
* Adventure
* Shopping
* Culture
* Beaches
* Photography
* Local experiences
* Family-friendly activities
* Luxury experiences
* Hidden gems

Multiple selection should be allowed.

---

### Dietary Needs

The user can choose one or more dietary preferences.

Options:

* No restriction
* Vegetarian
* Vegan
* Halal
* Gluten-free
* Seafood allergy
* Nut allergy
* Avoid pork
* Other

If `Other` is selected, show a text input.

---

### Mobility Constraints

The user can select physical or accessibility-related constraints.

Options:

* No mobility constraints
* Avoid long walking
* Avoid stairs
* Wheelchair-friendly places preferred
* Senior-friendly plan
* Kid-friendly pacing
* Avoid intense physical activities
* Other

If `Other` is selected, show a text input.

---

## Agent Persona Synthesis

After collecting preferences, the agent creates a short internal travel persona.

Example:

```text
You seem like a balanced couple traveler who prefers a moderate pace, scenic nature, local food, and cultural experiences. You want a trip that feels full but not exhausting, with comfortable accommodation and some flexibility each day.
```

---

## Clarifying Questions

The agent should then ask 3–4 short clarifying questions to make sure it understood the user correctly.

Example questions:

1. Would you rather have one big highlight per day or several smaller experiences?
2. Do you prefer popular must-see places, hidden gems, or a mix of both?
3. Should the plan prioritize comfort or maximum exploration?
4. Would you like food stops to be local and casual, or more premium and curated?

The user can answer quickly through buttons or short text.

---

## Persona Lock

Once the user answers, the agent finalizes the trip persona.

This persona is locked internally and used for all future recommendations.

The persona should influence:

* Spot recommendations
* Food recommendations
* Activity recommendations
* Budget distribution
* Itinerary pacing
* Route planning
* Checklist generation

---

## Stage Output

Example output:

```json
{
  "travel_pace": "Moderate",
  "interest_tags": ["Food", "Nature", "Culture", "Beaches"],
  "dietary_needs": ["Halal"],
  "mobility_constraints": ["Avoid long walking"],
  "trip_persona": {
    "summary": "Balanced couple travelers who prefer scenic places, cultural experiences, halal-friendly food, and a moderate pace without too much walking.",
    "planning_style": "Comfortable but experience-rich",
    "priority": "Balanced route, scenic highlights, local food, and realistic daily pacing"
  }
}
```

CTA:

```text
Looks good, continue
```

Alternative CTA:

```text
Edit preferences
```

---

# Stage 3 — Spots, Food & Activities

## Purpose

The agent recommends a curated shortlist of places, food experiences, and activities based on:

* Destination
* Trip duration
* Budget
* Traveller type
* Traveller count
* Accommodation preference
* Travel pace
* Interest tags
* Dietary needs
* Mobility constraints
* Locked trip persona

This stage is where the user curates what they actually want included in the trip.

---

## Agent Recommendation Message

Example:

```text
Based on your trip style and budget, I’ve shortlisted places, food experiences, and activities that fit your travel persona.

You can add, remove, or swap anything before I create your day-wise itinerary.
```

---

## Recommendation Categories

The shortlist should be grouped into three major categories.

---

## 1. Spots to Visit

Each spot card should include:

* Name
* Short description
* Why it fits the user
* Estimated cost
* Estimated time required
* Best time to visit
* Location/area
* Tags
* Recommendation level

Example card:

```text
Uluwatu Temple

Why it fits:
A scenic cultural landmark with ocean views and sunset experience.

Estimated cost:
$8–12 per person

Time needed:
2–3 hours

Best time:
Late afternoon / sunset

Tags:
Culture, Scenic, Sunset

Recommendation:
Highly recommended
```

User actions:

* Add
* Remove
* Replace
* Mark as must-visit
* View cheaper alternative
* View less crowded alternative

---

## 2. Food Experiences

Each food card should include:

* Food or restaurant type
* Description
* Dietary suitability
* Estimated cost
* Best meal time
* Area
* Tags

Example card:

```text
Local seafood dinner

Why it fits:
A relaxed dinner experience near the beach with local flavor.

Estimated cost:
$15–30 per person

Dietary note:
Halal-friendly alternatives available

Best time:
Dinner

Tags:
Food, Local, Beachside
```

User actions:

* Add
* Remove
* Replace
* Need halal option
* Need vegetarian option
* Make it cheaper
* Make it premium

---

## 3. Activities

Each activity card should include:

* Activity name
* Description
* Estimated cost
* Difficulty level
* Time needed
* Required preparation
* Tags

Example card:

```text
Rice terrace walk

Why it fits:
A scenic nature experience that matches your interest in calm outdoor activities.

Estimated cost:
$5–10 per person

Difficulty:
Easy to moderate

Time needed:
1–2 hours

Tags:
Nature, Photography, Local Experience
```

User actions:

* Add
* Remove
* Replace
* Too expensive
* Too tiring
* Make it family-friendly
* Add to must-do list

---

# User Curation

The user can freely curate the shortlist.

Allowed actions:

* Add new item
* Remove recommended item
* Swap an item
* Mark an item as must-have
* Mark an item as optional
* Mark an item as avoid
* Ask why something is recommended
* Ask for cheaper alternatives
* Ask for less crowded alternatives
* Add a custom place/activity/food item

---

# Budget Check

After the user finalizes the shortlist, the system runs a budget validation.

This is the only stage where budget negotiation happens.

The system checks:

* Accommodation estimate
* Food estimate
* Activity estimate
* Local transport estimate
* Buffer amount
* Total estimated spend

---

## If Budget Fits

Show:

```text
Your selected experiences fit within your estimated budget.
```

CTA:

```text
Lock shortlist
```

---

## If Budget Exceeds

Show:

```text
Your selected experiences are estimated to exceed your budget by around $180.
```

The agent suggests options:

1. Remove or replace expensive activities.
2. Choose more budget-friendly food options.
3. Reduce paid attractions.
4. Increase the total budget.
5. Keep the plan but mark the overage clearly.

Example:

```text
To stay within budget, I recommend replacing the snorkeling tour with a free beach morning and choosing local restaurants for two dinners.
```

User actions:

* Trim recommendations
* Increase budget
* Keep as is
* Ask agent to optimize budget
* Manually edit shortlist

---

# Shortlist Lock

Once the user is satisfied, they explicitly lock the shortlist.

CTA:

```text
Lock shortlist and create itinerary
```

The locked shortlist becomes the foundation for the day-wise itinerary.

---

## Stage Output

Example output:

```json
{
  "locked_shortlist": {
    "spots": [
      {
        "name": "Uluwatu Temple",
        "status": "must_visit",
        "estimated_cost": 20
      },
      {
        "name": "Tegallalang Rice Terrace",
        "status": "selected",
        "estimated_cost": 15
      }
    ],
    "foods": [
      {
        "name": "Local seafood dinner",
        "status": "selected",
        "estimated_cost": 60
      }
    ],
    "activities": [
      {
        "name": "Rice terrace walk",
        "status": "selected",
        "estimated_cost": 20
      }
    ]
  },
  "budget_status": {
    "within_budget": true,
    "estimated_total": 1080,
    "budget": 1200,
    "currency": "USD"
  }
}
```

---

# Stage 4 — Day-wise Itinerary

## Purpose

The agent uses the locked shortlist to generate a practical day-wise trip plan.

The itinerary should respect:

* Travel dates
* Duration
* Travel pace
* Traveller type
* Traveller count
* Budget
* Accommodation preference
* Locked trip persona
* Locked shortlist
* Travel time between stops
* Place proximity
* Opening hours, if available
* Meal timing
* Rest time
* Arrival/departure constraints

---

## Agent Itinerary Message

Example:

```text
I’ve created your day-wise itinerary using your locked shortlist.

I grouped nearby places together, avoided unnecessary backtracking, and kept the pace moderate based on your travel style.
```

---

# Day Card Structure

Each day should be shown as a separate card.

Each day card includes:

* Day number
* Date
* Day theme
* Morning slot
* Afternoon slot
* Evening slot
* Food recommendations
* Travel time between stops
* Estimated daily cost
* Notes
* Backup suggestion

---

## Example Day Card

```text
Day 2 — Culture, Nature & Sunset

Morning:
Visit Tegallalang Rice Terrace
Estimated time: 1.5–2 hours

Lunch:
Local Balinese lunch near Ubud
Estimated cost: $10–15 per person

Afternoon:
Visit Ubud Palace and nearby local market
Estimated time: 2 hours

Evening:
Uluwatu Temple sunset experience
Estimated travel time: 1.5 hours from Ubud

Dinner:
Seafood dinner near Jimbaran

Estimated daily cost:
$120–160 for 2 travelers

Agent note:
This day is experience-rich, but still balanced. If you want a slower pace, I can move Uluwatu to another day.
```

---

# User Refinement Actions

The user can edit the itinerary before locking it.

Allowed actions:

* Reorder stops within a day
* Move an item to another day
* Remove an item
* Swap an item
* Replace food recommendation
* Add rest time
* Add free time
* Add custom activity
* Change the day’s pace
* Ask why the route is arranged this way
* Ask for cheaper options
* Ask for less travel time
* Ask for more local experiences

---

# Re-optimization

If the user makes a significant change, the system should offer itinerary re-optimization.

Examples of significant changes:

* Moving a far-away spot to another day
* Adding too many activities to one day
* Removing a major anchor activity
* Changing accommodation area
* Changing travel pace
* Reducing/increasing duration
* Changing budget significantly

CTA:

```text
Re-optimize affected days
```

The agent should regenerate only the affected day or days, not the entire trip unless necessary.

---

# Itinerary Lock

Once the user is satisfied, they lock the itinerary.

CTA:

```text
Lock itinerary
```

After this stage, the day-wise route becomes the confirmed plan.

The user should still be able to edit later from the trip dashboard, but locking means the app can now generate checklist items based on the confirmed itinerary.

---

## Stage Output

Example output:

```json
{
  "itinerary": [
    {
      "day": 1,
      "date": "2026-08-10",
      "theme": "Arrival and relaxed beach evening",
      "slots": {
        "morning": [],
        "afternoon": [
          {
            "type": "arrival",
            "title": "Arrive and check in"
          }
        ],
        "evening": [
          {
            "type": "spot",
            "title": "Seminyak Beach sunset"
          },
          {
            "type": "food",
            "title": "Local seafood dinner"
          }
        ]
      },
      "estimated_cost": 90,
      "estimated_travel_time": "45 minutes"
    }
  ],
  "status": "itinerary_locked"
}
```

---

# Stage 5 — Pre-trip Checklist

## Purpose

The pre-trip checklist is generated only after the itinerary is locked.

This is because the checklist depends on what the user will actually do during the trip.

For example:

* If the trip is international, passport/visa checks may be needed.
* If hiking is included, hiking gear should be suggested.
* If beach activities are included, swimwear and sunscreen should be suggested.
* If temple visits are included, modest clothing may be suggested.
* If adventure activities are included, insurance or safety preparation may be recommended.

---

## Agent Checklist Message

Example:

```text
Now that your itinerary is locked, I’ll prepare your document and packing checklist based on your destination, dates, and planned activities.
```

---

# Checklist Categories

## 1. Documents

Possible checklist items:

* Passport
* Visa
* Flight tickets
* Hotel booking confirmation
* Activity booking confirmation
* Travel insurance
* Emergency contacts
* Local permits
* Driving license
* International driving permit
* Copies of important documents

---

## 2. Packing

Possible checklist items:

* Weather-appropriate clothing
* Comfortable walking shoes
* Swimwear
* Sunscreen
* Sunglasses
* Rain jacket or umbrella
* Power adapter
* Portable charger
* Medicine
* Toiletries
* Day bag
* Reusable water bottle

---

## 3. Itinerary-specific Items

Generated from actual planned activities.

Examples:

### If hiking is included

* Hiking shoes
* Light backpack
* Water bottle
* Quick-dry clothes

### If beach activities are included

* Swimwear
* Waterproof phone pouch
* Sunscreen
* Towel

### If temple visits are included

* Modest clothing
* Scarf or sarong
* Comfortable sandals

### If adventure activities are included

* Safety confirmation
* Travel insurance check
* Extra clothes
* Waterproof bag

---

# Targeted Agent Questions

The agent should ask only necessary questions.

Example:

```text
Your trip may require passport validation. Is your passport valid for at least 6 months after your return date?
```

Options:

* Yes
* No
* Not sure

Another example:

```text
You have a few outdoor activities in the plan. Do you already have comfortable walking shoes?
```

Options:

* Yes
* No
* Add to checklist

---

# Privacy Note

The system should avoid collecting unnecessary sensitive information.

For passport validation, the app should ask:

```text
Is your passport valid for at least 6 months after your return date?
```

Instead of asking:

```text
Enter your passport number.
```

Only collect sensitive document numbers if there is a strong product reason and proper security is implemented.

---

# Checklist Actions

The user can:

* Tick off checklist items
* Add custom items
* Remove irrelevant items
* Mark item as important
* Add reminder
* Group by category
* Filter incomplete items

---

## Stage Output

Example output:

```json
{
  "checklist": {
    "documents": [
      {
        "title": "Passport valid for at least 6 months after return date",
        "status": "pending",
        "priority": "high"
      },
      {
        "title": "Hotel booking confirmation",
        "status": "pending",
        "priority": "medium"
      }
    ],
    "packing": [
      {
        "title": "Comfortable walking shoes",
        "status": "pending",
        "priority": "high"
      },
      {
        "title": "Sunscreen",
        "status": "pending",
        "priority": "medium"
      }
    ],
    "custom": []
  }
}
```

---

# Stage 6 — Summary & Save

## Purpose

The final stage gives the user a clean summary of the completed trip plan before saving.

This is the confirmation stage.

The user should be able to review the full plan, export it, share it, or save it to their account.

---

## Summary Content

The summary should include:

* Destination
* Travel dates
* Duration
* Traveller type
* Traveller count
* Budget
* Estimated total spend
* Accommodation preference
* Trip persona
* Selected spots
* Selected food experiences
* Selected activities
* Full day-wise itinerary
* Pre-trip checklist

---

## Example Summary

```text
Bali Trip Plan

Dates:
August 10–14, 2026

Duration:
5 days

Travelers:
Couple, 2 travelers

Budget:
1200 USD

Estimated Spend:
1080 USD

Trip Style:
Moderate-paced couple trip focused on nature, food, culture, and beaches.

Selected Experiences:
- Uluwatu Temple
- Tegallalang Rice Terrace
- Seminyak Beach
- Local seafood dinner
- Rice terrace walk

Checklist:
- Passport validity check
- Hotel booking confirmation
- Comfortable walking shoes
- Sunscreen
- Swimwear
```

---

# Final Actions

Available actions:

```text
Save trip
Export as PDF
Create shareable link
Edit itinerary
Edit checklist
```

Primary CTA:

```text
Save trip
```

When the user confirms, the trip is saved to their account.

---

# After Save

After saving, the user is redirected to the `My Trips` dashboard.

The saved trip should appear with a status.

Possible statuses:

* Draft
* Planned
* Upcoming
* Active
* Completed

Example:

```text
Bali Trip
August 10–14, 2026
Status: Planned
```

---

# My Trips Dashboard

The dashboard allows users to manage all their trips.

Each trip card can show:

* Destination
* Dates
* Duration
* Status
* Completion progress
* Estimated budget
* Next important task

Example:

```text
Bali Trip
5 days · 2 travelers · Planned

Next task:
Complete passport validity check

Planning progress:
85%
```

---

# Saved Trip Detail Page

After opening a saved trip, the user can access:

## 1. Overview

Shows trip summary, dates, budget, and status.

## 2. Itinerary

Shows the full day-wise plan.

## 3. Map

Shows places grouped by day and route.

## 4. Budget

Shows estimated spend by category.

## 5. Checklist

Shows documents, packing, and custom tasks.

## 6. Agent Chat

Allows the user to continue modifying or asking questions about the trip.

---

# Agent Behavior Rules

## 1. Ask only what is necessary

The agent should avoid asking too many questions upfront.

It should collect enough information to make a useful recommendation, then improve through user feedback.

---

## 2. Always explain major recommendations

For every major place, food, activity, or route decision, the agent should be able to explain why it was recommended.

Example:

```text
I recommended Uluwatu Temple because it matches your interest in culture and scenic sunset views, and it fits well with your moderate pace.
```

---

## 3. Keep user control high

The user should always be able to:

* Add
* Remove
* Swap
* Edit
* Reorder
* Regenerate
* Re-optimize

The trip should never feel fully controlled by the agent.

---

## 4. Do not regenerate everything unnecessarily

When the user changes one day, only regenerate the affected day if possible.

When the user changes the shortlist, regenerate only the itinerary sections affected by the new selection.

---

## 5. Budget negotiation happens only in Stage 3

The budget check should happen after the user curates the shortlist.

If the plan is over budget, the agent should suggest tradeoffs before the itinerary is generated.

Once the shortlist is locked, the itinerary should follow the approved budget direction.

---

## 6. Checklist happens after itinerary lock

The checklist should be generated after the itinerary is confirmed because the checklist depends on the actual plan.

---

# Recommended Trip Status Flow

```text
Draft Created
    ↓
Parameters Completed
    ↓
Persona Locked
    ↓
Shortlist Locked
    ↓
Itinerary Locked
    ↓
Checklist Created
    ↓
Trip Saved
    ↓
Upcoming
    ↓
Active
    ↓
Completed
```

---

# Suggested Data Model

## Trip

```json
{
  "id": "trip_001",
  "user_id": "user_001",
  "destination_id": "destination_001",
  "status": "planned",
  "start_date": "2026-08-10",
  "duration_days": 5,
  "traveller_type": "Couple",
  "traveller_count": 2,
  "budget_amount": 1200,
  "budget_currency": "USD",
  "accommodation_preference": "Mid-range hotel",
  "created_at": "2026-06-03T10:00:00Z",
  "updated_at": "2026-06-03T10:00:00Z"
}
```

---

## Traveller Profile

```json
{
  "trip_id": "trip_001",
  "travel_pace": "Moderate",
  "interest_tags": ["Food", "Nature", "Culture", "Beaches"],
  "dietary_needs": ["Halal"],
  "mobility_constraints": ["Avoid long walking"],
  "persona_summary": "Balanced couple travelers who prefer scenic places, culture, halal-friendly food, and a moderate pace."
}
```

---

## Shortlist Item

```json
{
  "id": "item_001",
  "trip_id": "trip_001",
  "type": "spot",
  "name": "Uluwatu Temple",
  "description": "Scenic cultural temple with ocean views.",
  "status": "must_visit",
  "estimated_cost": 20,
  "currency": "USD",
  "estimated_duration": "2-3 hours",
  "tags": ["Culture", "Sunset", "Scenic"]
}
```

---

## Itinerary Day

```json
{
  "id": "day_001",
  "trip_id": "trip_001",
  "day_number": 1,
  "date": "2026-08-10",
  "theme": "Arrival and relaxed beach evening",
  "estimated_cost": 90,
  "estimated_travel_time": "45 minutes"
}
```

---

## Itinerary Item

```json
{
  "id": "itinerary_item_001",
  "day_id": "day_001",
  "slot": "evening",
  "type": "spot",
  "title": "Seminyak Beach sunset",
  "description": "A relaxed first evening near the beach.",
  "start_time": "17:00",
  "end_time": "18:30",
  "estimated_cost": 0,
  "travel_time_from_previous": "20 minutes"
}
```

---

## Checklist Item

```json
{
  "id": "checklist_001",
  "trip_id": "trip_001",
  "category": "documents",
  "title": "Passport valid for at least 6 months after return date",
  "status": "pending",
  "priority": "high",
  "source": "agent_generated"
}
```

---

# MVP Scope

For the MVP, the feature should include:

## Must Have

* Start planning from destination page
* Trip parameter form
* Traveller profile collection
* Agent-generated persona summary
* Spot, food, and activity recommendations
* User shortlist curation
* Budget check
* Locked shortlist
* Day-wise itinerary generation
* Basic itinerary editing
* Checklist generation
* Save trip to account
* My Trips dashboard

---

## Should Have

* PDF export
* Shareable trip link
* Map view
* Re-optimize affected days
* Custom checklist items
* Budget breakdown
* Agent explanation for recommendations

---

## Later Enhancements

* Real-time weather-aware suggestions
* Flight and hotel booking integration
* Activity booking integration
* Collaborative planning with friends/family
* Offline itinerary access
* During-trip mode
* Live route changes
* Expense tracking
* Calendar sync
* Notification reminders
* Multi-city trip planning

---

# MVP Success Criteria

The feature is successful if users can:

1. Start a trip plan from a destination page.
2. Provide basic trip details quickly.
3. Feel understood by the agent.
4. Receive relevant recommendations.
5. Customize spots, food, and activities.
6. Understand the budget impact.
7. Generate a realistic day-wise itinerary.
8. Receive a useful checklist.
9. Save and revisit the trip later.

---

# Final Product Principle

The feature should not feel like a form generator or a one-time AI response.

It should feel like a guided planning workspace where the user and agent build the trip together step by step.

The agent recommends, explains, and optimizes.

The user decides, edits, and locks.
