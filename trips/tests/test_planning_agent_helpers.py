from django.test import SimpleTestCase

from trips.agents.planning_agent.helpers import _parse_json_object


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
