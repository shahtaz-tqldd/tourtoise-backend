# Destination discovery agent

Turtle Chat is a Google ADK agent for destination discovery and decision-making. It can:

- recommend up to three destinations using profile and conversation preferences;
- answer destination questions with relational and semantic application data;
- compare two or three destinations;
- refine recommendations without discarding existing constraints; and
- return a structured handoff when the user chooses a destination.

It deliberately does not create itineraries. `ChatQuestionAPIView` stores the ADK session
ID in `ChatSession.metadata`, allowing references such as “it” and refinements such as
“cheaper options” to retain their conversational context.

## Data policy

`search_destinations` and `get_destination_details` query published PostgreSQL records and
are authoritative for IDs and structured facts. `semantic_destination_search` uses the
existing vector store for broad and descriptive questions and returns supporting context.
If semantic search is unavailable, the agent can continue with relational results.

The signed-in user is closed over by the tool factory, so profile, saved-destination, and
trip-history access cannot be redirected to a different user by model-provided arguments.

## Response contract

The response is validated by `DiscoveryAgentResponse`. Its user-facing message is saved as
the agent chat message; recommendation cards, intent, usage data, and an optional planning
handoff are saved in message metadata. The handoff is also copied into session metadata for
the trip-planning module to consume.
