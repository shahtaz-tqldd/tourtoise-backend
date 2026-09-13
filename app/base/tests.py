from io import BytesIO
from unittest.mock import patch

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from PIL import Image
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import User
from app.base.models import TourtoiseConfig


def image_upload(name="logo.png"):
    content = BytesIO()
    Image.new("RGB", (2, 2), "white").save(content, format="PNG")
    return SimpleUploadedFile(name, content.getvalue(), content_type="image/png")


class TourtoiseConfigApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.config = TourtoiseConfig.objects.create(
            title="Tourtoise",
            privacy_policy="Privacy",
            terms_of_service="Terms",
            data_deletion_policy="Deletion",
            cookie_policy="Cookies",
            meta_title="Travel better",
        )

    def test_get_returns_only_multiple_requested_sections(self):
        response = self.client.get(
            "/api/v1/config/",
            {"branding": "true", "seo": "true"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(set(response.data["data"]), {"branding", "seo"})
        self.assertEqual(response.data["data"]["branding"]["title"], "Tourtoise")
        self.assertEqual(response.data["data"]["seo"]["meta_title"], "Travel better")

    def test_get_legal_document_returns_all_four_documents(self):
        response = self.client.get("/api/v1/config/", {"legal_document": "true"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            set(response.data["data"]["legal_document"]),
            {
                "privacy_policy",
                "terms_of_service",
                "data_deletion_policy",
                "cookie_policy",
            },
        )

    def test_document_type_returns_only_requested_document(self):
        response = self.client.get(
            "/api/v1/config/",
            {"legal_document": "true", "document_type": "privacy_policy"},
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            response.data["data"]["legal_document"],
            {"privacy_policy": "Privacy"},
        )

    def test_invalid_document_type_is_rejected(self):
        response = self.client.get(
            "/api/v1/config/",
            {"document_type": "not-a-document"},
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("app.api.v1.serializers.delete_image")
    @patch("app.api.v1.serializers.upload_image")
    def test_superadmin_can_update_fields_and_replace_logo(self, upload_image, delete_image):
        admin = User.objects.create_superuser("admin@example.com", "testpass123")
        self.client.force_authenticate(admin)
        self.config.logo = "https://res.cloudinary.com/demo/image/upload/old-logo.png"
        self.config.save(update_fields=["logo"])
        upload_image.return_value = {
            "url": "https://res.cloudinary.com/demo/image/upload/new-logo.png",
            "public_id": "new-logo",
        }

        response = self.client.patch(
            "/api/v1/admin/config/",
            {
                "title": "New Tourtoise",
                "maintenance_mode": True,
                "logo": image_upload(),
            },
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.config.refresh_from_db()
        self.assertEqual(self.config.title, "New Tourtoise")
        self.assertTrue(self.config.maintenance_mode)
        self.assertEqual(
            self.config.logo,
            "https://res.cloudinary.com/demo/image/upload/new-logo.png",
        )
        self.assertEqual(self.config.updated_by, admin)
        upload_image.assert_called_once()
        delete_image.assert_called_once_with(
            image_url="https://res.cloudinary.com/demo/image/upload/old-logo.png"
        )

    def test_update_requires_superadmin(self):
        response = self.client.patch(
            "/api/v1/admin/config/",
            {"title": "Not allowed"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_401_UNAUTHORIZED)
