from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.models import UserProfile


User = get_user_model()


class RegisterApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = "/api/v1/accounts/register/"

    def test_register_allows_multiple_users_without_username(self):
        first_response = self.client.post(
            self.url,
            {
                "email": "first@example.com",
                "password": "testpass123",
                "confirm_password": "testpass123",
            },
            format="json",
        )
        second_response = self.client.post(
            self.url,
            {
                "email": "second@example.com",
                "password": "testpass123",
                "confirm_password": "testpass123",
            },
            format="json",
        )

        self.assertEqual(first_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(second_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(User.objects.count(), 2)
        self.assertEqual(UserProfile.objects.filter(username__isnull=True).count(), 2)

    def test_register_returns_validation_error_for_duplicate_username(self):
        existing_user = User.objects.create_user(email="existing@example.com", password="testpass123")
        existing_user.profile.username = "taken"
        existing_user.profile.save(update_fields=["username"])

        response = self.client.post(
            self.url,
            {
                "email": "new@example.com",
                "username": "taken",
                "password": "testpass123",
                "confirm_password": "testpass123",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertFalse(response.data["success"])
        self.assertEqual(response.data["message"], "Registration failed.")
        self.assertIn("username", response.data["errors"])
        self.assertIn("already taken", str(response.data["errors"]["username"]))
