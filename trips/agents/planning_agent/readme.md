## Stage 1 — Trip parameters (form input)
this is just structured data collection. 
Fields: 
- destination (pre-filled from the page)
- start date
- duration in days
- traveller type (solo / couple / family / group)
- traveller count (for family and group open this fields and pick number otherwise for solo: 1, couple: 2)
- total budget with currency dropdown currency
- accommodation preference

## Stage 2 — Traveller profile
Now the agent speaks. It collects qualitative preferences 
- travel pace (relaxed / moderate / packed)
- interest tags (food, history, nature, nightlife, adventure, shopping)
- dietary needs, and mobility constraints. 
After gathering these, the agent asks exactly one high-value, destination-aware clarifying question (for example, "Would you rather have one big highlight per day or lots of smaller experiences?"). The answer is combined with the structured preferences into a compact trip persona that drives later recommendations.

## Stage 3 — Spots, food & activities (agent recommends, user curates)
The agent now proposes a destination-catalog-backed shortlist against the locked persona and budget, covering every destination in a multi-destination trip. IDs are accepted only when they belong to one of the trip's destinations. The user can add, swap, or remove items before itinerary generation.

## Stage 4 — Day-wise itinerary (agent generates, user refines)
With the shortlist, the agent builds the day plan — routing by proximity, respecting travel times, and distributing shortlisted items across every trip day. The budget includes accommodation and is checked against `total_budget`; overages are reported explicitly. The user can reorder or swap itinerary items, which marks only preparation as stale.

## Stage 5 — Pre-trip checklist (after itinerary is locked)
Only now does the agent generate documents and packing guidance, because it knows where the traveler is going and what they are doing. If there is hiking it recommends gear; uncertain entry requirements remain conditional. Regeneration preserves checked packing items and uploaded documents when names still match (and always preserves uploaded documents).

## Stage 6 — Summary & save
The agent produces a clean trip summary: destination, dates, total estimated spend, full itinerary, and the checklist. This is also where the shareable link or PDF export is offered. Confirming saves the trip to the user's account and lands them on their "My trips" dashboard.
