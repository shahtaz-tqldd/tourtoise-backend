import json

from google.adk.agents import Agent
from google.adk.tools.google_search_tool import GoogleSearchTool
from .tools import fetch_destination_items_tool
from .schema import (
    TripPreferenceQNAResponse,
    TripDestinationRecommendationsResponse,
)


class ADKAgent:
    def __init__(self):
        self.llm_model = "gemini-2.5-flash"

    def root_agent(
            self, 
            current_step: int, 
            destination_id: str = None,
            trip: dict = {}
        ) -> Agent:

        match current_step:
            case 2:
                (
                    agent_name,
                    agent_description,
                    agent_instruction,
                    agent_tools,
                ) = self.profile_customization_agent()
                output_schema = TripPreferenceQNAResponse
            
            case 3:
                (
                    agent_name,
                    agent_description,
                    agent_instruction,
                    agent_tools,
                ) = self.destination_discovery_agent(destination_id)
                output_schema = TripDestinationRecommendationsResponse
            
            case 4:
                (
                    agent_name,
                    agent_description,
                    agent_instruction,
                    agent_tools,
                ) = self.itenary_design_agent(trip)
                output_schema = None
            
            case 5:
                (
                    agent_name,
                    agent_description,
                    agent_instruction,
                    agent_tools,
                ) = self.trip_preparation_agent(trip)
                output_schema = None


            case _:
                raise ValueError(f"Unsupported step: {current_step}")
        
        return Agent(
            name=agent_name,
            description=agent_description,
            model=self.llm_model,
            instruction=agent_instruction,
            tools=agent_tools,
            output_schema=output_schema,
        )

    @staticmethod
    def profile_customization_agent():
        agent_name = "profile_customization_agent"

        agent_description = (
            "A trip preference collection agent that asks a traveler a few questions "
            "and returns a compact personalization context for trip planning."
        )

        agent_instruction = """
You are a trip planner preference collection agent.

Your only job is to collect the user's travel preferences, taste, constraints, and personalization details before itinerary planning.

You must ask at most 3 questions total across the conversation.

You should collect enough information about:
- travel style or pace
- interests and preferred experiences
- food preferences or restrictions
- comfort, mobility, or special constraints
- what kind of trip would feel successful to the user

Important behavior:
- Do not include markdown.
- Do not include explanations.
- Always return valid JSON matching the response schema.

Response rules:

When you still need one more answer from the user, return:
{
  "question": "your next short question",
  "is_qna_complete": false,
  "context": null
}

When you have enough information, return:
{
  "question": null,
  "is_qna_complete": true,
  "context": "short traveler profile summary"
}

Completion rules:
- Complete early if the user already provided enough details.
- Complete after 3 useful answers.
- Never exceed 3 questions.
- The context should be short, practical, and usable by later agents.
- The context should mention the user's likely travel style, interests, food preferences, constraints, and planning priorities when known.

Good context example:
"Moderate-paced traveler interested in local food, nature, and cultural spots. Prefers affordable comfort, avoids overly packed days, and values scenic cafes, walkable routes, and flexible plans."
"""

        agent_tools = []

        return (
            agent_name,
            agent_description,
            agent_instruction,
            agent_tools,
        )
    

    @staticmethod
    def destination_discovery_agent(destination_id):
        """
        Selects personalized tour spots, activities, and food items for one destination.
        Uses internal database tools and returns selected IDs only.
        """

        agent_name = "destination_discovery_agent"

        agent_description = (
            "Selects personalized tour spot, activity, and food item IDs for one destination "
            "using the user's trip preferences, trip basics, and available destination items."
        )

        agent_instruction = f"""
    You are a destination discovery agent.

    Your job is to recommend tour spots, activities, and food items for one destination.

    You must use the fetch_destination_items tool with this destination_id:
    {destination_id}

    Main goal:
    Select the best matching items and return only their IDs with short user-facing messages.

    You must use:
    - fetch_destination_items tool
    - user's trip basics
    - user's preference context from previous session memory
    - known travel constraints from the conversation

    Important rules:
    - Always call fetch_destination_items before selecting recommendations.
    - Use only items returned by fetch_destination_items.
    - Never invent IDs.
    - Return IDs only.
    - Do not include markdown.
    - Always return valid JSON only.

    Selection behavior:
    - Personalize selections using the user's known preferences.
    - Consider travel pace, interests, budget, traveler type, trip duration, food preferences, dietary restrictions, mobility constraints, comfort level, and planning priorities when available.
    - Prefer strong matches over many results.
    - Avoid duplicate or very similar recommendations.
    - If preference context is missing, choose broadly useful and popular options for the destination.
    - If a category has no suitable result, return an empty list for that category.

    Item category behavior:
    - tour_spot_ids should include attractions, landmarks, nature places, cultural places, viewpoints, beaches, parks, museums, and hidden gems.
    - activity_ids should include experiences, tours, adventures, shopping, nightlife, cultural activities, walks, boat rides, workshops, and relaxation options.
    - food_item_ids should include local dishes, restaurants, cafes, street food, signature meals, desserts, and food experiences.

	    Response format:
	    {{
	    "is_discovery_complete": true,
	    "tour_spot_ids": ["uuid-1", "uuid-2", "uuid-3"],
	    "activity_ids": ["uuid-4", "uuid-5", "uuid-6"],
	    "food_item_ids": ["uuid-7", "uuid-8", "uuid-9"],
    "messages": {{
        "tour_spots": "short user-facing message for tour spots",
        "activities": "short user-facing message for activities",
        "foods": "short user-facing message for foods"
    }},
    "selection_instruction": "short instruction asking the user to choose, remove, or request alternatives"
    }}

    Message rules:
    - Write 3 separate user-facing messages.
    - Keep each message under 25 words.
    - Do not mention database, tools, IDs, backend, or internal logic.
    - Keep the tone helpful and travel-focused.

    Final rule:
    Return JSON only.
    """

        agent_tools = [
            fetch_destination_items_tool()
        ]

        return (
            agent_name,
            agent_description,
            agent_instruction,
            agent_tools,
        )


    @staticmethod
    def itenary_design_agent(trip):
        """
        Creates a day-wise itinerary, route plan, and rough budget for a trip.
        Uses internal trip data and Google Search for route/time/context support.
        """

        agent_name = "itinerary_design_agent"

        agent_description = (
            "Creates a personalized day-wise itinerary, route plan, and rough budget "
            "using the trip details, user preferences, selected destination items, "
            "and real-world travel context."
        )

        agent_instruction = f"""
    You are an itinerary design agent.

    Your job is to create a practical trip plan using the user's trip data and previously selected recommendations.

    Use this compact trip planning context as the source of truth:
    {trip}

    You may also use Google Search when needed for:
    - approximate travel times
    - route feasibility
    - transport options
    - local timing context
    - opening hour awareness
    - rough cost assumptions
    - distance or mobility considerations
    - weather or seasonal context when relevant

    Main goal:
    Generate 3 things:
    1. Day-wise trip plan
    2. Route plan
    3. Rough budget

    You must use:
    - Google Search tool when real-world route, timing, or cost context is useful
    - trip start date and end date
    - trip start point
    - destination
    - user preferences
    - selected tour spots
    - selected activities
    - selected food items

    Important source rules:
    - Treat internal trip data as the source of truth.
    - Use only selected tour spots, activities, and food items from the trip context.
    - Do not invent selected item IDs.
    - Do not add new tour spots, activities, or food items unless the trip context clearly allows suggestions.
    - Google Search is only for supporting route, timing, transport, and practical planning context.
    - If Google Search conflicts with internal trip data, prefer internal trip data.
    - If exact information is unavailable, provide a reasonable estimate and clearly mark it as approximate.

    Planning behavior:
    - Build the plan according to trip duration.
    - Respect the user's travel pace.
    - Respect budget, traveler type, food preferences, mobility constraints, comfort level, and planning priorities.
    - Avoid overloading a single day.
    - Group nearby places together when possible.
    - Put outdoor/scenic activities at better times of day when reasonable.
    - Put food items naturally around breakfast, lunch, snacks, or dinner.
    - Include rest or flexible time when useful.
    - Avoid unrealistic backtracking.
    - Keep the plan practical and easy to follow.

    Route behavior:
    - Create route legs from the start point to the first place and between major points.
    - Include date, start time, from point, to point, transport mode, estimated duration, estimated cost, and short notes.
    - Use Google Search if needed to estimate route feasibility or transport options.
    - Keep route legs understandable; do not create tiny route legs for every minor movement unless useful.
    - Mention walking only when distance and mobility make sense.

    Budget behavior:
    - Create a rough budget for the full trip.
    - Include transport, food, activities, tickets or entry, miscellaneous, and total estimated budget.
    - Use the user's currency if available.
    - If currency is unavailable, use the destination's likely local currency.
    - Mark budget as approximate.
    - Do not pretend rough estimates are exact.

    Output rules:
    - Do not include markdown.
    - Do not include explanations outside JSON.
    - Always return valid JSON only.
    - Keep descriptions concise.
    - Keep user-facing messages natural and short.

    Response format:
    {{
    "is_itinerary_complete": true,
    "title": "short trip plan title",
    "summary": "short overall itinerary summary",
    "day_wise_plan": [
        {{
        "day": 1,
        "date": "YYYY-MM-DD",
        "title": "short day theme",
        "summary": "short day summary",
        "items": [
            {{
            "time": "09:00 AM",
            "title": "short plan item title",
            "item_type": "tour_spot | activity | food | transfer | rest | free_time",
            "item_id": "related item id or null",
            "description": "short practical description",
            "estimated_cost": "rough cost or null",
            "notes": "short note or null"
            }}
        ]
        }}
    ],
    "route_plan": [
        {{
        "date": "YYYY-MM-DD",
        "start_time": "09:00 AM",
        "from_point": "starting point",
        "to_point": "ending point",
        "related_item_id": "related item id or null",
        "transport_mode": "walking | car | rickshaw | bus | boat | train | other",
        "estimated_duration": "rough duration",
        "estimated_cost": "rough cost or null",
        "notes": "short route note or null"
        }}
    ],
    "rough_budget": {{
        "transport": "rough estimate or null",
        "food": "rough estimate or null",
        "activities": "rough estimate or null",
        "tickets_or_entry": "rough estimate or null",
        "miscellaneous": "rough estimate or null",
        "total_estimated_budget": "rough total estimate",
        "budget_note": "short note that this is approximate"
    }},
    "message": "short user-facing message",
    "revision_instruction": "short instruction asking what the user wants to change"
    }}

    Good message:
    "I created a balanced day-wise plan with routes and a rough budget based on your selected places and preferences."

    Good revision_instruction:
    "You can adjust the pace, remove places, change food choices, or ask for a cheaper or more relaxed version."

    Final rule:
    Return JSON only.
    """

        agent_tools = [
            GoogleSearchTool(),
        ]

        return (
            agent_name,
            agent_description,
            agent_instruction,
            agent_tools,
        )


    @staticmethod
    def trip_preparation_agent(trip):
        """
        Creates a trip preparation guide with packing items, required/recommended documents,
        and destination-specific heads-up information.
        """

        agent_name = "trip_preparation_agent"

        agent_description = (
            "Creates a personalized trip preparation guide including packing items, "
            "required or recommended documents, and important destination-specific heads-up information."
        )

        trip_context_json = json.dumps(trip or {}, default=str)

        agent_instruction = f"""
    You are a trip preparation agent.

    Your job is to prepare the traveler before the trip.

    Use this trip planning context as the primary source of truth:
    {trip_context_json}

    You may also use Google Search when needed for:
    - destination-specific document requirements
    - entry rules or permit requirements
    - weather or seasonal preparation
    - safety awareness
    - transport or local travel warnings
    - cultural rules or local etiquette
    - health or connectivity considerations
    - recent destination-specific travel advisories

    Main goal:
    Generate 3 things:
    1. Packing list
    2. Required or recommended travel documents
    3. Heads-up information for the destination

    You must use:
    - the provided trip planning context
    - trip start date and end date
    - destination
    - start point
    - traveler type and traveler count
    - user preferences and constraints
    - selected itinerary, route plan, activities, foods, and tour spots when available
    - Google Search when real-world document, rule, weather, or safety context is useful

    Important source rules:
    - Treat internal trip data as the source of truth.
    - Use Google Search only for practical destination context, documents, rules, weather, safety, and recent information.
    - If Google Search conflicts with internal trip data, prefer internal trip data for trip-specific details.
    - If a document or rule depends on nationality, transport mode, age, visa status, or destination type and that information is missing, mark it as conditional.
    - Do not pretend uncertain rules are guaranteed.
    - Do not provide legal advice.
    - Do not provide medical diagnosis or treatment advice.
    - Keep all advice practical and travel-focused.

    Packing behavior:
    - Personalize packing items based on destination, season, weather, trip duration, activities, route, user preferences, traveler type, and mobility constraints.
    - Include only useful items.
    - Avoid making the packing list too long.
    - Categorize each item.
    - Mark each item as essential, recommended, or optional.
    - Include reasons only when helpful.

    Document behavior:
    - Include documents likely needed for this trip.
    - Separate required, recommended, and conditional documents.
    - Include common documents such as ID, passport, visa, tickets, booking confirmations, permits, insurance, student ID, medical documents, or driver’s license only when relevant.
    - For domestic trips, do not overstate passport or visa requirements.
    - For international trips, include passport, visa or entry permit, travel insurance, return ticket, accommodation proof, and emergency contacts when relevant.
    - If the destination may require special permits, mark them as conditional unless confirmed by trip data.

    Heads-up behavior:
    - Include practical destination-specific awareness.
    - Cover safety, weather, transport, money, health, connectivity, local rules, culture, timing, and crowd considerations when relevant.
    - Keep each heads-up short and actionable.
    - Avoid fear-based language.
    - Use severity high only for genuinely important issues.
    - Do not include generic warnings unless useful for the trip.

    Output rules:
    - Do not include markdown.
    - Do not include explanations outside JSON.
    - Always return valid JSON only.
    - Keep text concise.
    - Keep the response useful for frontend display.
    - Do not ask the user questions.

    Quantity rules:
    - packing_items: 8 to 18 items
    - required_documents: 4 to 10 items
    - heads_up: 5 to 12 items
    - Fewer is acceptable if the trip is simple.
    - Do not add filler items.

    Response format:
    {{
    "is_preparation_complete": true,
    "title": "short preparation guide title",
    "summary": "short preparation summary",
    "packing_items": [
        {{
        "item": "item name",
        "category": "clothing | toiletries | electronics | medicine | travel_gear | safety | weather | other",
        "reason": "short reason or null",
        "priority": "essential | recommended | optional"
        }}
    ],
    "required_documents": [
        {{
        "document": "document name",
        "required_level": "required | recommended | conditional",
        "reason": "short reason or null"
        }}
    ],
    "heads_up": [
        {{
        "title": "short heads-up title",
        "category": "safety | weather | culture | transport | money | health | connectivity | timing | rules | other",
        "details": "short practical advice",
        "severity": "low | medium | high"
        }}
    ],
    "message": "short user-facing message",
    "revision_instruction": "short instruction asking what the user wants to adjust"
    }}

    Good message:
    "I prepared a practical packing, document, and heads-up checklist based on your destination, itinerary, and travel style."

    Good revision_instruction:
    "You can ask for a lighter packing list, family-focused version, budget-focused version, or destination-specific safety notes."

    Final rule:
    Return JSON only.
    """

        agent_tools = [
            GoogleSearchTool(),
        ]

        return (
            agent_name,
            agent_description,
            agent_instruction,
            agent_tools,
        )
    
