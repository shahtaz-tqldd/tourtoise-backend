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
After gathering these, the agent synthesises a "trip persona" and presents 3–4 short clarifying questions — things like "Would you rather have one big highlight per day or lots of smaller experiences?" — to confirm it understood correctly. Once the user answers, the persona is locked internally and drives every subsequent recommendation.

## Stage 3 — Spots, food & activities (agent recommends, user curates)
The agent now proposes a shortlist against the locked persona and budget. Each item shows an estimated cost so the user understands the budget impact. The user can freely add, swap, or remove items. When the selection is finalised, the system runs a budget check — if it's over, the agent flags the gap and suggests either trimming the list or adjusting the budget. This is the only stage where budget negotiation happens. When the user is happy, they explicitly lock the shortlist.

## Stage 4 — Day-wise itinerary (agent generates, user refines)
With the locked shortlist, the agent builds the actual day plan — routing by proximity, respecting travel times, and distributing the shortlisted items across the days. Each day card shows: morning / afternoon / evening slots, what to eat, what to do, and rough travel times between stops. The user can reorder or swap within a day. If a change is significant enough, they can request a re-optimise and the agent regenerates the affected days. Once satisfied, the user locks the itinerary.

## Stage 5 — Pre-trip checklist (after itinerary is locked)
Only now does the agent ask about documents and packing — because now it knows exactly where they're going and what they're doing. The checklist is generated from the itinerary: if there's a visa-required country, passport validity comes up; if there's hiking, it recommends gear. The agent asks targeted questions (e.g., "Your passport — is it valid past [date + 6 months]?"). The user can tick off items and add their own.

## Stage 6 — Summary & save
The agent produces a clean trip summary: destination, dates, total estimated spend, full itinerary, and the checklist. This is also where the shareable link or PDF export is offered. Confirming saves the trip to the user's account and lands them on their "My trips" dashboard.
