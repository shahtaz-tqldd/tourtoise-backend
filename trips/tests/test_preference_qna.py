from django.test import SimpleTestCase

from trips.services.services import (
    build_final_preference_agent_query,
    build_initial_agent_query,
    build_itinerary_agent_query,
    build_preparation_agent_query,
    build_recommendations_agent_query,
    finalize_preference_response,
    normalize_initial_preference_response,
)


class PreferenceQNAFlowTests(SimpleTestCase):
    def setUp(self):
        self.preferences = {
            "travel_pace": "balanced",
            "interest_tags": ["history", "nature"],
            "dietary_needs": ["halal"],
        }
        self.trip_snapshot = {
            "destinations": [{"name": "Kyoto", "country": "Japan"}],
            "duration_days": 4,
        }

    def test_initial_response_always_asks_one_question(self):
        agent_response = {
            "response": {
                "question": None,
                "is_qna_complete": True,
                "context": "The model tried to complete early.",
            }
        }

        result = normalize_initial_preference_response(
            agent_response,
            self.preferences,
            self.trip_snapshot,
        )

        self.assertFalse(result["response"]["is_qna_complete"])
        self.assertIsNone(result["response"]["context"])
        self.assertIn("Kyoto", result["response"]["question"])
        self.assertEqual(result["response"]["question"].count("?"), 1)

    def test_first_answer_always_completes_qna(self):
        agent_response = {
            "response": {
                "question": "Would you prefer another option?",
                "is_qna_complete": False,
                "context": None,
            }
        }

        result = finalize_preference_response(
            agent_response,
            "Street food, temples, and a quiet garden each day.",
            self.preferences,
            self.trip_snapshot,
        )

        self.assertTrue(result["response"]["is_qna_complete"])
        self.assertIsNone(result["response"]["question"])
        self.assertIn("Street food", result["response"]["context"])
        self.assertIn("Dietary needs: halal", result["response"]["context"])

    def test_multiple_model_questions_are_replaced_with_one_question(self):
        agent_response = {
            "response": {
                "question": "Do you like museums? Which foods do you enjoy?",
                "is_qna_complete": False,
                "context": None,
            }
        }

        result = normalize_initial_preference_response(
            agent_response,
            self.preferences,
            self.trip_snapshot,
        )

        self.assertEqual(result["response"]["question"].count("?"), 1)
        self.assertIn("ideal day", result["response"]["question"])

    def test_phase_prompts_make_the_single_question_contract_explicit(self):
        initial_query = build_initial_agent_query(self.preferences, self.trip_snapshot)
        final_query = build_final_preference_agent_query(
            "A slow day with markets and local food.",
            self.preferences,
            self.trip_snapshot,
        )

        self.assertIn("PREFERENCE_INTAKE_PHASE: ASK_ONE_QUESTION", initial_query)
        self.assertIn("Do not complete Q&A", initial_query)
        self.assertIn("PREFERENCE_INTAKE_PHASE: FINALIZE_AFTER_ANSWER", final_query)
        self.assertIn("Do not ask another question", final_query)

    def test_generation_queries_do_not_duplicate_serialized_context(self):
        marker = "UNIQUE_CONTEXT_MARKER"
        context = {"marker": marker}

        recommendation_query = build_recommendations_agent_query(
            context,
            context,
            ["destination-1", "destination-2"],
        )
        itinerary_query = build_itinerary_agent_query(context)
        preparation_query = build_preparation_agent_query(context)

        self.assertNotIn(marker, recommendation_query)
        self.assertNotIn(marker, itinerary_query)
        self.assertNotIn(marker, preparation_query)
