from django.test import SimpleTestCase

from trips.agents.planning_agent.agents import ADKAgent
from trips.agents.planning_agent.helpers import _parse_json_object
from trips.agents.planning_agent.schema import (
    TripItineraryDesignResponse,
    TripPreparationResponse,
)
from trips.choices import PlanningStep


class PlanningAgentSchemaTests(SimpleTestCase):
    def test_itinerary_agent_enforces_its_output_schema(self):
        agent = ADKAgent().root_agent(PlanningStep.ITINERARY, trip={})

        self.assertIs(agent.output_schema, TripItineraryDesignResponse)

    def test_preparation_agent_enforces_its_output_schema(self):
        agent = ADKAgent().root_agent(PlanningStep.PREPARATION, trip={})

        self.assertIs(agent.output_schema, TripPreparationResponse)


class ParseAgentJsonObjectTests(SimpleTestCase):
    def test_parses_json_inside_markdown_fence(self):
        result = _parse_json_object('```json\n{"is_itinerary_complete": true}\n```')

        self.assertEqual(result, {"is_itinerary_complete": True})

    def test_recovers_valid_object_with_extra_closing_brace(self):
        result = _parse_json_object('{"is_itinerary_complete": true}}')

        self.assertEqual(result, {"is_itinerary_complete": True})

    def test_recovers_valid_object_with_trailing_commentary(self):
        result = _parse_json_object(
            '{"is_itinerary_complete": true}\nHere is your itinerary.'
        )

        self.assertEqual(result, {"is_itinerary_complete": True})

    def test_uses_first_complete_object_when_response_is_repeated(self):
        result = _parse_json_object(
            '{"is_itinerary_complete": true}\n'
            '{"is_itinerary_complete": false}'
        )

        self.assertEqual(result, {"is_itinerary_complete": True})

    def test_rejects_malformed_first_object(self):
        result = _parse_json_object('{"is_itinerary_complete": true,}')

        self.assertIsNone(result)
