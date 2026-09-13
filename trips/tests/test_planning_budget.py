from decimal import Decimal
from types import SimpleNamespace

from django.test import SimpleTestCase

from trips.services.services import _normalize_rough_budget


class PlanningBudgetNormalizationTests(SimpleTestCase):
    def test_sums_complete_breakdown_and_flags_target_overage(self):
        trip = SimpleNamespace(
            total_budget=Decimal("500.00"),
            budget_currency="USD",
        )

        result = _normalize_rough_budget(
            trip,
            {
                "accommodation": "300",
                "transport": "100",
                "food": "80",
                "activities": "40",
                "tickets_or_entry": "20",
                "miscellaneous": "10",
                "total_estimated_budget": "1",  # Ignore bad model arithmetic.
                "budget_note": "Approximate prices.",
            },
        )

        self.assertEqual(result["total_estimated_budget"], "550")
        self.assertIn("50.00 USD above", result["budget_note"])

    def test_rejects_negative_budget_components(self):
        trip = SimpleNamespace(total_budget=None, budget_currency="USD")

        result = _normalize_rough_budget(
            trip,
            {"transport": "-25", "total_estimated_budget": "100"},
        )

        self.assertIsNone(result["transport"])
        self.assertEqual(result["total_estimated_budget"], "100")
