from django.core.exceptions import ValidationError
from django.test import TestCase

from destinations.choices import BudgetTier, DestinationType
from destinations.models import Destination, DestinationTag


class DestinationModelTests(TestCase):
    def test_best_travel_months_are_sorted_and_deduplicated_on_save(self):
        destination = Destination.objects.create(
            name="Kathmandu",
            country="Nepal",
            country_code="NPL",
            destination_type=DestinationType.CITY,
            latitude=27.7172,
            longitude=85.3240,
            tagline="Historic capital",
            overview="A cultural and historical destination.",
            cover_image="https://example.com/cover.jpg",
            min_stay_days=2,
            max_stay_days=5,
            budget_tier=BudgetTier.MID,
            local_languages=["Nepali", "English"],
            best_travel_months=[10, 3, 10, 1],
            currency="Nepalese Rupee",
            currency_code="NPR",
        )

        self.assertEqual(destination.best_travel_months, [1, 3, 10])

    def test_best_travel_months_validate_range(self):
        destination = Destination(
            name="Pokhara",
            country="Nepal",
            country_code="NPL",
            destination_type=DestinationType.CITY,
            latitude=28.2096,
            longitude=83.9856,
            tagline="Lakeside city",
            overview="Gateway to the Annapurna region.",
            cover_image="https://example.com/cover.jpg",
            min_stay_days=2,
            max_stay_days=5,
            budget_tier=BudgetTier.MID,
            local_languages=["Nepali", "English"],
            best_travel_months=[0, 13],
            currency="Nepalese Rupee",
            currency_code="NPR",
        )

        with self.assertRaises(ValidationError):
            destination.full_clean()

    def test_tags_use_direct_many_to_many_relationship(self):
        destination = Destination.objects.create(
            name="Bhaktapur",
            country="Nepal",
            country_code="NPL",
            destination_type=DestinationType.CULTURAL,
            latitude=27.6720,
            longitude=85.4298,
            tagline="Ancient Newar city",
            overview="Well-preserved heritage destination.",
            cover_image="https://example.com/cover.jpg",
            min_stay_days=1,
            max_stay_days=3,
            budget_tier=BudgetTier.MID,
            local_languages=["Nepali", "English"],
            best_travel_months=[10, 11],
            currency="Nepalese Rupee",
            currency_code="NPR",
        )
        tag = DestinationTag.objects.create(name="Heritage", category="experience")

        destination.tags.add(tag)

        self.assertEqual(list(destination.tags.all()), [tag])
