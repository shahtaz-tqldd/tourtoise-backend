from types import SimpleNamespace

from django.test import SimpleTestCase

from trips.choices import PlanningStep
from trips.services.services import get_trip_planning_progress


class PlanningProgressTests(SimpleTestCase):
    def test_stale_saved_artifacts_do_not_count_as_complete(self):
        trip = SimpleNamespace(
            metadata={
                "invalidated_planning_steps": [
                    PlanningStep.RECOMMENDATION,
                    PlanningStep.ITINERARY,
                    PlanningStep.PREPARATION,
                ]
            },
            current_step=PlanningStep.RECOMMENDATION,
            agent_active=True,
            is_qna_complete=True,
            is_recommendation_complete=True,
            is_itinerary_design_complete=True,
            is_trip_preparation_complete=True,
            trip_recommendations=object(),
            trip_itinerary=object(),
            structured_preparation=object(),
        )

        progress = get_trip_planning_progress(trip)

        self.assertTrue(progress["is_qna_complete"])
        self.assertFalse(progress["is_recommendation_complete"])
        self.assertFalse(progress["is_itinerary_design_complete"])
        self.assertFalse(progress["is_trip_preparation_complete"])
        self.assertEqual(
            progress["stale_steps"],
            [
                PlanningStep.RECOMMENDATION,
                PlanningStep.ITINERARY,
                PlanningStep.PREPARATION,
            ],
        )
