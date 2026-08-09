from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from accounts.choices import CreditRequestStatus, CreditTransactionType
from accounts.models import CreditRequest
from chat.choices import ChatMessageSender
from chat.models import ChatMessage, ChatSession
from journals.models import Journal
from trips.choices import AgentMessageSender
from trips.models import Trip, TripConversationMessage, TripConversationSession


User = get_user_model()


class AccountListApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_superuser(
            email="admin@example.com",
            password="testpass123",
        )
        self.staff = User.objects.create_user(
            email="staff@example.com",
            password="testpass123",
            is_staff=True,
        )
        self.user = User.objects.create_user(
            email="traveler@example.com",
            password="testpass123",
            name="Traveler",
            phone="+880123456789",
        )
        self.client.force_authenticate(user=self.admin)

    def test_includes_activity_counts_and_excludes_admin_accounts(self):
        first_trip = Trip.objects.create(user=self.user, title="First Trip")
        Trip.objects.create(user=self.user, title="Second Trip")

        chat_session = ChatSession.objects.create(user=self.user)
        for sender in (ChatMessageSender.USER, ChatMessageSender.AGENT):
            ChatMessage.objects.create(
                session=chat_session,
                sender=sender,
                content="General chat message",
            )

        trip_session = TripConversationSession.objects.create(
            trip=first_trip,
            user=self.user,
        )
        for sender in (
            AgentMessageSender.USER,
            AgentMessageSender.AGENT,
            AgentMessageSender.SYSTEM,
        ):
            TripConversationMessage.objects.create(
                session=trip_session,
                sender=sender,
                content="Trip chat message",
            )

        Journal.objects.create(author=self.user, content="First journal")
        Journal.objects.create(author=self.user, content="Second journal")
        self.user.credit.balance = 73
        self.user.credit.save(update_fields=["balance"])

        response = self.client.get("/api/v1/admin/accounts/list/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["meta"]["count"], 1)
        row = response.data["data"][0]
        self.assertEqual(row["email"], self.user.email)
        self.assertEqual(row["trip_plan_count"], 2)
        self.assertEqual(row["credit"], 73)
        self.assertEqual(
            row["message_count"],
            {"chat_message": 2, "trip_message": 3},
        )
        self.assertEqual(row["journal_count"], 2)
        for removed_field in (
            "phone",
            "travel_pace",
            "is_staff",
            "is_superuser",
        ):
            self.assertNotIn(removed_field, row)

    def test_returns_zero_counts_for_user_without_activity(self):
        response = self.client.get("/api/v1/admin/accounts/list/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["meta"]["count"], 1)
        row = response.data["data"][0]
        self.assertEqual(row["trip_plan_count"], 0)
        self.assertEqual(row["credit"], 100)
        self.assertEqual(
            row["message_count"],
            {"chat_message": 0, "trip_message": 0},
        )
        self.assertEqual(row["journal_count"], 0)


class UpdateAdminApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_superuser(
            email="admin-update@example.com",
            password="CurrentPass123!",
        )
        self.user = User.objects.create_user(
            email="regular-update@example.com",
            password="CurrentPass123!",
        )

    @patch("accounts.api.v1.admin.serializers.delete_image")
    @patch("accounts.api.v1.admin.serializers.upload_image")
    def test_admin_can_update_fullname_and_avatar(self, upload_image, delete_image):
        self.client.force_authenticate(user=self.admin)
        self.admin.profile.avatar_url = (
            "https://res.cloudinary.com/demo/image/upload/v1/admins/old-avatar.jpg"
        )
        self.admin.profile.save(update_fields=["avatar_url"])
        upload_image.return_value = {
            "url": "https://res.cloudinary.com/demo/image/upload/v2/admins/new-avatar.webp",
            "public_id": "admins/new-avatar",
        }
        avatar = SimpleUploadedFile(
            "avatar.gif",
            (
                b"GIF87a\x01\x00\x01\x00\x80\x00\x00\x00\x00\x00"
                b"\xff\xff\xff!\xf9\x04\x01\x00\x00\x00\x00,\x00\x00"
                b"\x00\x00\x01\x00\x01\x00\x00\x02\x02D\x01\x00;"
            ),
            content_type="image/gif",
        )

        response = self.client.patch(
            "/api/v1/admin/accounts/update-info/",
            {"fullname": "Updated Admin", "avatar": avatar},
            format="multipart",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.admin.refresh_from_db()
        self.admin.profile.refresh_from_db()
        self.assertEqual(self.admin.name, "Updated Admin")
        self.assertEqual(
            self.admin.profile.avatar_url,
            "https://res.cloudinary.com/demo/image/upload/v2/admins/new-avatar.webp",
        )
        self.assertEqual(response.data["data"]["name"], "Updated Admin")
        self.assertEqual(response.data["data"]["avatar_url"], self.admin.profile.avatar_url)
        upload_image.assert_called_once()
        delete_image.assert_called_once_with(
            image_url="https://res.cloudinary.com/demo/image/upload/v1/admins/old-avatar.jpg",
        )

    def test_admin_can_change_password(self):
        self.client.force_authenticate(user=self.admin)

        response = self.client.patch(
            "/api/v1/admin/accounts/update-password/",
            {
                "current_password": "CurrentPass123!",
                "new_password": "NewAdminPass456!",
                "confirm_new_password": "NewAdminPass456!",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password("NewAdminPass456!"))

    def test_password_update_validates_current_password_and_confirmation(self):
        self.client.force_authenticate(user=self.admin)

        wrong_current = self.client.patch(
            "/api/v1/admin/accounts/update-password/",
            {
                "current_password": "WrongCurrentPass!",
                "new_password": "NewAdminPass456!",
                "confirm_new_password": "NewAdminPass456!",
            },
            format="json",
        )
        mismatched_confirmation = self.client.patch(
            "/api/v1/admin/accounts/update-password/",
            {
                "current_password": "CurrentPass123!",
                "new_password": "NewAdminPass456!",
                "confirm_new_password": "DifferentPass456!",
            },
            format="json",
        )

        self.assertEqual(wrong_current.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("current_password", wrong_current.data)
        self.assertEqual(mismatched_confirmation.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("confirm_new_password", mismatched_confirmation.data)

    def test_regular_user_cannot_update_admin_info_or_password(self):
        self.client.force_authenticate(user=self.user)

        info_response = self.client.patch(
            "/api/v1/admin/accounts/update-info/",
            {"fullname": "Not Admin"},
            format="json",
        )
        password_response = self.client.patch(
            "/api/v1/admin/accounts/update-password/",
            {
                "current_password": "CurrentPass123!",
                "new_password": "NewRegularPass456!",
                "confirm_new_password": "NewRegularPass456!",
            },
            format="json",
        )

        self.assertEqual(info_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(password_response.status_code, status.HTTP_403_FORBIDDEN)


class AdminCreditRequestApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            email="credit-admin@example.com",
            password="testpass123",
            is_staff=True,
        )
        self.user = User.objects.create_user(
            email="credit-applicant@example.com",
            password="testpass123",
        )
        self.other_user = User.objects.create_user(
            email="other-credit-applicant@example.com",
            password="testpass123",
        )
        self.list_url = "/api/v1/admin/accounts/credit-requests/"

    def test_admin_can_list_all_requests_and_filter_by_status(self):
        pending = CreditRequest.objects.create(user=self.user, reason="Pending reason")
        CreditRequest.objects.create(
            user=self.other_user,
            reason="Rejected reason",
            status=CreditRequestStatus.REJECTED,
            reviewed_by=self.admin,
        )
        self.client.force_authenticate(user=self.admin)

        all_response = self.client.get(self.list_url)
        pending_response = self.client.get(self.list_url, {"status": "pending"})

        self.assertEqual(all_response.status_code, status.HTTP_200_OK)
        self.assertEqual(all_response.data["meta"]["count"], 2)
        self.assertEqual(pending_response.data["meta"]["count"], 1)
        self.assertEqual(pending_response.data["data"][0]["id"], str(pending.id))
        self.assertEqual(pending_response.data["data"][0]["user"]["email"], self.user.email)

    def test_admin_approval_adds_credits_and_ledger_transaction(self):
        credit_request = CreditRequest.objects.create(user=self.user, reason="Plan more trips")
        starting_balance = self.user.credit.balance
        self.client.force_authenticate(user=self.admin)

        response = self.client.patch(
            f"{self.list_url}{credit_request.id}/review/",
            {"action": "approve", "amount": 45},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        credit_request.refresh_from_db()
        self.user.credit.refresh_from_db()
        self.assertEqual(credit_request.status, CreditRequestStatus.APPROVED)
        self.assertEqual(credit_request.approved_amount, 45)
        self.assertEqual(credit_request.reviewed_by, self.admin)
        self.assertIsNotNone(credit_request.reviewed_at)
        self.assertEqual(self.user.credit.balance, starting_balance + 45)
        ledger_entry = credit_request.credit_transaction
        self.assertEqual(ledger_entry.transaction_type, CreditTransactionType.ADMIN_ADJUSTMENT)
        self.assertEqual(ledger_entry.amount, 45)
        self.assertEqual(ledger_entry.metadata["credit_request_id"], str(credit_request.id))

        repeated = self.client.patch(
            f"{self.list_url}{credit_request.id}/review/",
            {"action": "approve", "amount": 45},
            format="json",
        )
        self.assertEqual(repeated.status_code, status.HTTP_400_BAD_REQUEST)
        self.user.credit.refresh_from_db()
        self.assertEqual(self.user.credit.balance, starting_balance + 45)

    def test_admin_can_reject_without_changing_balance(self):
        credit_request = CreditRequest.objects.create(user=self.user, reason="Not enough")
        starting_balance = self.user.credit.balance
        self.client.force_authenticate(user=self.admin)

        response = self.client.patch(
            f"{self.list_url}{credit_request.id}/review/",
            {"action": "reject"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        credit_request.refresh_from_db()
        self.user.credit.refresh_from_db()
        self.assertEqual(credit_request.status, CreditRequestStatus.REJECTED)
        self.assertIsNone(credit_request.approved_amount)
        self.assertEqual(self.user.credit.balance, starting_balance)

    def test_approval_requires_positive_amount_and_regular_users_are_forbidden(self):
        credit_request = CreditRequest.objects.create(user=self.user, reason="Credits")
        self.client.force_authenticate(user=self.admin)

        missing_amount = self.client.patch(
            f"{self.list_url}{credit_request.id}/review/",
            {"action": "approve"},
            format="json",
        )
        zero_amount = self.client.patch(
            f"{self.list_url}{credit_request.id}/review/",
            {"action": "approve", "amount": 0},
            format="json",
        )
        self.client.force_authenticate(user=self.user)
        forbidden_list = self.client.get(self.list_url)
        forbidden_review = self.client.patch(
            f"{self.list_url}{credit_request.id}/review/",
            {"action": "reject"},
            format="json",
        )

        self.assertEqual(missing_amount.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(zero_amount.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(forbidden_list.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(forbidden_review.status_code, status.HTTP_403_FORBIDDEN)
