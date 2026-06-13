import csv
import io
from unittest.mock import patch

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from django.utils import timezone

from accounts.models import User
from destinations.api.v1.admin.serializers import (
    AdminDestinationBulkUploadSerializer,
    AdminDestinationDetailSerializer,
    AdminDestinationWriteSerializer,
)
from destinations.api.v1.client.serializers import (
    ClientDestinationDetailSerializer,
    ClientDestinationListSerializer,
)
from destinations.choices import BudgetTier, DestinationType, Status
from destinations.models import (
    Activity,
    ActivityImage,
    Attraction,
    AttractionImage,
    Cuisine,
    CuisineImage,
    Destination,
    DestinationTag,
)
from destinations.tasks import upload_destination_gallery_image, upload_model_image


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


class DestinationImageUploadTaskTests(TestCase):
    def test_model_image_upload_skips_missing_pending_file(self):
        destination = Destination.objects.create(
            name="Pokhara",
            country="Nepal",
            country_code="NPL",
            destination_type=DestinationType.CITY,
            latitude=28.2096,
            longitude=83.9856,
            tagline="Lakeside city",
            overview="Gateway to the Annapurna region.",
            cover_image="https://example.com/original.jpg",
            min_stay_days=2,
            max_stay_days=5,
            budget_tier=BudgetTier.MID,
            currency="Nepalese Rupee",
            currency_code="NPR",
        )

        with patch("destinations.tasks.upload_image") as upload_image_mock:
            result = upload_model_image.run(
                storage_path="pending_uploads/cloudinary/missing.jpg",
                app_label="destinations",
                model_name="Destination",
                object_id=str(destination.pk),
                field_name="cover_image",
                folder="tourtoise/destinations/covers",
                public_id="pokhara-cover",
            )

        destination.refresh_from_db()
        self.assertEqual(result["result"], "skipped")
        self.assertEqual(result["reason"], "pending_file_missing")
        self.assertEqual(destination.cover_image, "https://example.com/original.jpg")
        upload_image_mock.assert_not_called()

    def test_gallery_image_upload_skips_missing_pending_file(self):
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
            currency="Nepalese Rupee",
            currency_code="NPR",
        )

        with patch("destinations.tasks.upload_image") as upload_image_mock:
            result = upload_destination_gallery_image.run(
                storage_path="pending_uploads/cloudinary/missing.jpg",
                destination_id=str(destination.pk),
                folder="tourtoise/destinations/gallery",
                public_id="kathmandu-gallery-1",
                sort_order=1,
            )

        self.assertEqual(result["result"], "skipped")
        self.assertEqual(result["reason"], "pending_file_missing")
        self.assertEqual(destination.images.count(), 0)
        upload_image_mock.assert_not_called()


class ClientDestinationListSerializerTests(TestCase):
    def test_returns_compact_client_list_payload(self):
        current_month = timezone.localdate().month
        destination = Destination.objects.create(
            name="Pokhra Nepal",
            country="Thailand",
            country_code="THA",
            region="Pokhra",
            destination_type=DestinationType.BEACH,
            latitude=28.2096,
            longitude=83.9856,
            tagline="Lakeside city",
            overview="Gateway to the Annapurna region.",
            cover_image="https://example.com/cover.jpg",
            min_stay_days=2,
            max_stay_days=5,
            budget_tier=BudgetTier.MID,
            local_languages=["Thai", "English"],
            best_travel_months=[current_month],
            currency="Thai Baht",
            currency_code="THB",
            status=Status.PUBLISHED,
        )
        life = DestinationTag.objects.create(name="Life", category="experience")
        comen = DestinationTag.objects.create(name="Comen", category="vibe")
        destination.tags.add(life, comen)

        data = ClientDestinationListSerializer(destination).data

        self.assertEqual(
            set(data.keys()),
            {
                "name",
                "slug",
                "country",
                "region",
                "destination_type",
                "cover_image",
                "is_now_best_time",
                "tags",
            },
        )
        self.assertEqual(data["name"], "Pokhra Nepal")
        self.assertEqual(data["country"], "Thailand")
        self.assertEqual(data["region"], "Pokhra")
        self.assertEqual(data["destination_type"], "beach")
        self.assertEqual(data["cover_image"], "https://example.com/cover.jpg")
        self.assertTrue(data["is_now_best_time"])
        self.assertEqual(data["tags"], ["Life", "Comen"])

    def test_returns_cloudinary_cover_image_thumbnail(self):
        destination = Destination.objects.create(
            name="Lombok",
            country="Indonesia",
            country_code="IDN",
            region="West Nusa Tenggara",
            destination_type=DestinationType.ISLAND,
            latitude=-8.6500,
            longitude=116.3249,
            tagline="Island escape",
            overview="Beaches and volcanoes.",
            cover_image=(
                "https://res.cloudinary.com/dqyv780cz/image/upload/"
                "v1781276591/tourtoise/destinations/gallery/lombok.jpg"
            ),
            min_stay_days=2,
            max_stay_days=5,
            budget_tier=BudgetTier.MID,
            best_travel_months=[],
            currency="Indonesian Rupiah",
            currency_code="IDR",
            status=Status.PUBLISHED,
        )

        data = ClientDestinationListSerializer(destination).data

        self.assertEqual(
            data["cover_image"],
            "https://res.cloudinary.com/dqyv780cz/image/upload/c_scale,w_600/"
            "v1781276591/tourtoise/destinations/gallery/lombok.jpg",
        )


class ClientDestinationDetailSerializerTests(TestCase):
    def test_returns_child_lists_with_images_without_ids(self):
        destination = Destination.objects.create(
            name="Pokhara",
            country="Nepal",
            country_code="NPL",
            region="Gandaki",
            destination_type=DestinationType.CITY,
            latitude=28.2096,
            longitude=83.9856,
            tagline="Lakeside city",
            overview="Gateway to the Annapurna region.",
            cover_image="https://example.com/destination.jpg",
            min_stay_days=2,
            max_stay_days=5,
            budget_tier=BudgetTier.MID,
            local_languages=["Nepali", "English"],
            best_travel_months=[10, 11],
            currency="Nepalese Rupee",
            currency_code="NPR",
            status=Status.PUBLISHED,
        )
        attraction = Attraction.objects.create(
            destination=destination,
            name="Phewa Lake",
            attraction_type="natural_site",
            description="A scenic freshwater lake.",
        )
        activity = Activity.objects.create(
            destination=destination,
            name="Paragliding",
            activity_type="adventure",
            description="Tandem paragliding over the valley.",
            budget_tier=BudgetTier.PREMIUM,
        )
        cuisine = Cuisine.objects.create(
            destination=destination,
            name="Newari Khaja",
            description="Traditional mixed platter.",
        )
        AttractionImage.objects.create(
            attraction=attraction,
            image_url="https://example.com/attraction.jpg",
            caption="Lake view",
        )
        ActivityImage.objects.create(
            activity=activity,
            image_url="https://example.com/activity.jpg",
            caption="In flight",
        )
        CuisineImage.objects.create(
            cuisine=cuisine,
            image_url="https://example.com/cuisine.jpg",
            caption="Khaja set",
        )

        data = ClientDestinationDetailSerializer(destination).data

        self.assertEqual(data["attractions"][0]["name"], "Phewa Lake")
        self.assertEqual(
            data["attractions"][0]["images"][0]["image_url"],
            "https://example.com/attraction.jpg",
        )
        self.assertEqual(data["activities"][0]["name"], "Paragliding")
        self.assertEqual(
            data["activities"][0]["images"][0]["image_url"],
            "https://example.com/activity.jpg",
        )
        self.assertEqual(data["cuisines"][0]["name"], "Newari Khaja")
        self.assertEqual(
            data["cuisines"][0]["images"][0]["image_url"],
            "https://example.com/cuisine.jpg",
        )

        for item in data["attractions"] + data["activities"] + data["cuisines"]:
            self.assertNotIn("id", item)
            for image in item["images"]:
                self.assertNotIn("id", image)


class AdminDestinationDetailSerializerTests(TestCase):
    def test_returns_child_lists_with_ids_and_images(self):
        destination = Destination.objects.create(
            name="Pokhara Admin",
            country="Nepal",
            country_code="NPL",
            region="Gandaki",
            destination_type=DestinationType.CITY,
            latitude=28.2096,
            longitude=83.9856,
            tagline="Lakeside city",
            overview="Gateway to the Annapurna region.",
            cover_image="https://example.com/destination.jpg",
            min_stay_days=2,
            max_stay_days=5,
            budget_tier=BudgetTier.MID,
            local_languages=["Nepali", "English"],
            best_travel_months=[10, 11],
            currency="Nepalese Rupee",
            currency_code="NPR",
            status=Status.PUBLISHED,
        )
        attraction = Attraction.objects.create(
            destination=destination,
            name="World Peace Pagoda",
            attraction_type="monument",
            description="Hilltop monument with wide views.",
        )
        activity = Activity.objects.create(
            destination=destination,
            name="Lake Kayaking",
            activity_type="water_sports",
            description="Kayaking on the lake.",
            budget_tier=BudgetTier.MID,
        )
        cuisine = Cuisine.objects.create(
            destination=destination,
            name="Thakali Set",
            description="Traditional rice meal.",
        )
        attraction_image = AttractionImage.objects.create(
            attraction=attraction,
            image_url="https://example.com/admin-attraction.jpg",
        )
        activity_image = ActivityImage.objects.create(
            activity=activity,
            image_url="https://example.com/admin-activity.jpg",
        )
        cuisine_image = CuisineImage.objects.create(
            cuisine=cuisine,
            image_url="https://example.com/admin-cuisine.jpg",
        )

        data = AdminDestinationDetailSerializer(destination).data

        self.assertEqual(data["attractions"][0]["id"], str(attraction.id))
        self.assertEqual(str(data["attractions"][0]["destination"]), str(destination.id))
        self.assertEqual(data["attractions"][0]["images"][0]["id"], str(attraction_image.id))
        self.assertEqual(data["activities"][0]["id"], str(activity.id))
        self.assertEqual(str(data["activities"][0]["destination"]), str(destination.id))
        self.assertEqual(data["activities"][0]["images"][0]["id"], str(activity_image.id))
        self.assertEqual(data["cuisines"][0]["id"], str(cuisine.id))
        self.assertEqual(str(data["cuisines"][0]["destination"]), str(destination.id))
        self.assertEqual(data["cuisines"][0]["images"][0]["id"], str(cuisine_image.id))


class AdminDestinationWriteSerializerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            email="admin-write@example.com",
            password="password",
        )
        self.request = type("Request", (), {"user": self.user, "FILES": {}})()

    def test_create_does_not_require_country_or_currency_code(self):
        serializer = AdminDestinationWriteSerializer(
            data={
                "name": "Chiang Mai",
                "country": "Thailand",
                "destination_type": DestinationType.CULTURAL,
                "latitude": 18.7883,
                "longitude": 98.9853,
                "tagline": "Northern culture hub",
                "overview": "Temples, food, and mountain access.",
                "cover_image": "https://example.com/chiang-mai.jpg",
                "budget_tier": BudgetTier.MID,
                "currency": "Thai Baht",
            }
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        self.assertNotIn("country_code", serializer.validated_data)
        self.assertNotIn("currency_code", serializer.validated_data)

    @patch("destinations.api.v1.admin.serializers.delete_image")
    def test_update_removes_gallery_images_by_id_from_cloudinary_and_database(self, delete_image_mock):
        destination = Destination.objects.create(
            name="Pokhara",
            country="Nepal",
            country_code="NPL",
            region="Gandaki",
            destination_type=DestinationType.CITY,
            latitude=28.2096,
            longitude=83.9856,
            tagline="Lakeside city",
            overview="Gateway to the Annapurna region.",
            cover_image="https://example.com/destination.jpg",
            min_stay_days=2,
            max_stay_days=5,
            budget_tier=BudgetTier.MID,
            currency="Nepalese Rupee",
            currency_code="NPR",
            status=Status.PUBLISHED,
        )
        image = DestinationImage.objects.create(
            destination=destination,
            image_url="https://res.cloudinary.com/demo/image/upload/v1/tourtoise/gallery/pokhara.jpg",
        )

        serializer = AdminDestinationWriteSerializer(
            destination,
            data={"removed_gallery_image_ids": [str(image.id)]},
            partial=True,
            context={"request": self.request},
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        serializer.save()

        self.assertFalse(DestinationImage.objects.filter(id=image.id).exists())
        delete_image_mock.assert_called_once_with(image_url=image.image_url)


class AdminDestinationBulkUploadSerializerTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_superuser(
            email="admin@example.com",
            password="password",
        )
        self.request = type("Request", (), {"user": self.user})()

    def test_csv_bulk_upload_creates_destinations_and_children_with_image_urls(self):
        columns = [
            "record_type",
            "destination_key",
            "name",
            "country",
            "country_code",
            "region",
            "destination_type",
            "latitude",
            "longitude",
            "tagline",
            "overview",
            "cover_image",
            "image_urls",
            "image_captions",
            "tags",
            "min_stay_days",
            "max_stay_days",
            "budget_tier",
            "difficulty",
            "local_languages",
            "best_travel_months",
            "currency",
            "currency_code",
            "status",
            "data_source",
            "attraction_type",
            "activity_type",
            "description",
            "meal_type",
        ]
        csv_content = self._csv(
            columns,
            [
                {
                    "record_type": "destination",
                    "destination_key": "pokhara-npl",
                    "name": "Pokhara",
                    "country": "Nepal",
                    "country_code": "NPL",
                    "region": "Gandaki",
                    "destination_type": "city",
                    "latitude": "28.2096",
                    "longitude": "83.9856",
                    "tagline": "Lakeside city",
                    "overview": "Gateway to Annapurna",
                    "cover_image": "https://example.com/pokhara.jpg",
                    "image_urls": "https://example.com/gallery.jpg",
                    "image_captions": "Gallery view",
                    "tags": "Lake:experience;Adventure:activity",
                    "min_stay_days": "2",
                    "max_stay_days": "5",
                    "budget_tier": "mid",
                    "difficulty": "easy",
                    "local_languages": "Nepali;English",
                    "best_travel_months": "10;11",
                    "currency": "Nepalese Rupee",
                    "currency_code": "NPR",
                    "status": "draft",
                    "data_source": "manual",
                },
                {
                    "record_type": "attraction",
                    "destination_key": "pokhara-npl",
                    "name": "Phewa Lake",
                    "cover_image": "https://example.com/phewa.jpg",
                    "image_urls": "https://example.com/phewa-gallery.jpg",
                    "image_captions": "Lake photo",
                    "attraction_type": "natural_site",
                    "description": "A scenic freshwater lake.",
                },
                {
                    "record_type": "activity",
                    "destination_key": "pokhara-npl",
                    "name": "Paragliding",
                    "cover_image": "https://example.com/paragliding.jpg",
                    "activity_type": "adventure",
                    "description": "Tandem paragliding over the valley.",
                    "budget_tier": "premium",
                },
                {
                    "record_type": "cuisine",
                    "destination_key": "pokhara-npl",
                    "name": "Thakali Set",
                    "cover_image": "https://example.com/thakali.jpg",
                    "description": "Traditional rice meal.",
                    "meal_type": "lunch",
                },
            ],
        )
        upload = SimpleUploadedFile(
            "destinations.csv",
            csv_content.encode("utf-8"),
            content_type="text/csv",
        )
        serializer = AdminDestinationBulkUploadSerializer(
            data={"file": upload},
            context={"request": self.request},
        )

        self.assertTrue(serializer.is_valid(), serializer.errors)
        result = serializer.save()

        destination = Destination.objects.get(name="Pokhara")
        self.assertEqual(result["created"]["destinations"], 1)
        self.assertEqual(result["created"]["attractions"], 1)
        self.assertEqual(result["created"]["activities"], 1)
        self.assertEqual(result["created"]["cuisines"], 1)
        self.assertEqual(destination.country_code, "NPL")
        self.assertEqual(destination.images.first().image_url, "https://example.com/gallery.jpg")
        self.assertEqual(destination.attractions.first().images.first().image_url, "https://example.com/phewa-gallery.jpg")
        self.assertEqual(destination.tags.count(), 2)

    def test_rejects_existing_destination_slug(self):
        Destination.objects.create(
            name="Pokhara",
            country="Nepal",
            country_code="NPL",
            destination_type=DestinationType.CITY,
            latitude=28.2096,
            longitude=83.9856,
            tagline="Existing",
            overview="Existing destination.",
            cover_image="https://example.com/existing.jpg",
            budget_tier=BudgetTier.MID,
            currency="Nepalese Rupee",
            currency_code="NPR",
        )
        csv_content = """record_type,destination_key,name,country,country_code,destination_type,latitude,longitude,tagline,overview,cover_image,budget_tier,currency,currency_code
destination,pokhara-npl,Pokhara,Nepal,NPL,city,28.2096,83.9856,Lakeside city,Gateway to Annapurna,https://example.com/pokhara.jpg,mid,Nepalese Rupee,NPR
"""
        upload = SimpleUploadedFile(
            "destinations.csv",
            csv_content.encode("utf-8"),
            content_type="text/csv",
        )
        serializer = AdminDestinationBulkUploadSerializer(
            data={"file": upload},
            context={"request": self.request},
        )

        self.assertFalse(serializer.is_valid())
        self.assertIn("Destination already exists", str(serializer.errors))

    def _csv(self, columns, rows):
        output = io.StringIO()
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
        return output.getvalue()
