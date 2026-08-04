from django.contrib.auth import get_user_model
from django.test import override_settings
from django.test import TestCase
from django.utils import timezone
from rest_framework import status
from rest_framework.test import APIClient
from datetime import timedelta

from accounts.choices import AccountProvider, AccountStatus
from accounts.models import UserProfile
from accounts.tasks import permanently_delete_expired_accounts


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


class DeleteAccountApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email="delete-me@example.com",
            password="testpass123",
        )

    def test_delete_account_marks_deactivated_without_disabling_user(self):
        self.client.force_authenticate(user=self.user)

        response = self.client.delete("/api/v1/accounts/settings/delete-account/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertEqual(self.user.status, AccountStatus.DEACTIVATED)
        self.assertIsNotNone(self.user.deleted_at)

    def test_password_login_reactivates_pending_deleted_account(self):
        self.user.mark_deleted()

        response = self.client.post(
            "/auth/accounts/login/",
            {"email": "delete-me@example.com", "password": "testpass123"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.user.refresh_from_db()
        self.assertTrue(self.user.is_active)
        self.assertEqual(self.user.status, AccountStatus.ACTIVE)
        self.assertIsNone(self.user.deleted_at)
        self.assertIn("access_token", response.data["data"])

    def test_cleanup_deletes_only_expired_accounts_still_deactivated(self):
        expired_user = User.objects.create_user(
            email="expired@example.com",
            password="testpass123",
        )
        expired_user.mark_deleted()
        expired_user.deleted_at = timezone.now() - timedelta(days=15)
        expired_user.save(update_fields=["deleted_at"])

        restored_user = User.objects.create_user(
            email="restored@example.com",
            password="testpass123",
        )
        restored_user.mark_deleted()
        restored_user.deleted_at = timezone.now() - timedelta(days=15)
        restored_user.save(update_fields=["deleted_at"])
        restored_user.reactivate()

        pending_user = User.objects.create_user(
            email="pending@example.com",
            password="testpass123",
        )
        pending_user.mark_deleted()
        pending_user.deleted_at = timezone.now() - timedelta(days=13)
        pending_user.save(update_fields=["deleted_at"])

        deleted_count = permanently_delete_expired_accounts()

        self.assertEqual(deleted_count, 1)
        self.assertFalse(User.objects.filter(id=expired_user.id).exists())
        self.assertTrue(User.objects.filter(id=restored_user.id).exists())
        self.assertTrue(User.objects.filter(id=pending_user.id).exists())


@override_settings(FIREBASE_VERIFY_ID_TOKEN=False)
class GoogleLoginApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.url = "/auth/accounts/google/"
        self.payload = {
            "provider": "google",
            "firebase_id_token": "firebase-id-token",
            "google_access_token": None,
            "firebase_uid": "firebase-uid-123",
            "email": "user@example.com",
            "email_verified": True,
            "name": "User Name",
            "photo_url": "https://example.com/avatar.png",
            "phone_number": None,
        }

    def test_google_login_creates_account_and_returns_tokens(self):
        response = self.client.post(self.url, self.payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.data["success"])
        self.assertIn("access_token", response.data["data"])
        self.assertIn("refresh_token", response.data["data"])

        user = User.objects.get(email="user@example.com")
        self.assertEqual(user.provider, AccountProvider.GOOGLE)
        self.assertEqual(user.firebase_uid, "firebase-uid-123")
        self.assertTrue(user.is_email_verified)
        self.assertFalse(user.has_usable_password())
        self.assertEqual(user.profile.username, "user")
        self.assertEqual(user.profile.avatar_url, "https://example.com/avatar.png")

    def test_google_login_updates_existing_email_account(self):
        user = User.objects.create_user(email="user@example.com", password="testpass123")

        response = self.client.post(self.url, self.payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        user.refresh_from_db()
        self.assertEqual(User.objects.count(), 1)
        self.assertEqual(user.provider, AccountProvider.GOOGLE)
        self.assertEqual(user.firebase_uid, "firebase-uid-123")
        self.assertEqual(user.profile.username, "user")

    def test_google_login_does_not_replace_existing_avatar(self):
        user = User.objects.create_user(email="user@example.com", password="testpass123")
        user.profile.avatar_url = "https://example.com/custom-avatar.png"
        user.profile.save(update_fields=["avatar_url"])

        response = self.client.post(self.url, self.payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        user.profile.refresh_from_db()
        self.assertEqual(user.profile.avatar_url, "https://example.com/custom-avatar.png")

    def test_google_login_reactivates_pending_deleted_account(self):
        user = User.objects.create_user(email="user@example.com", password="testpass123")
        user.mark_deleted()

        response = self.client.post(self.url, self.payload, format="json")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        user.refresh_from_db()
        self.assertTrue(user.is_active)
        self.assertEqual(user.status, AccountStatus.ACTIVE)
        self.assertIsNone(user.deleted_at)
