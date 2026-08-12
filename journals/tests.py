from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from journals.models import (
    ContentReport,
    ContentReportStatus,
    ContentReportTarget,
    Journal,
    JournalComment,
    JournalImage,
    JournalReaction,
    SavedJournal,
)
from notification.models import Notification


User = get_user_model()


class JournalApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.author = User.objects.create_user(email="author@example.com", password="testpass123")
        self.reader = User.objects.create_user(email="reader@example.com", password="testpass123")
        self.public_journal = self.create_journal(self.author, "Public journey content", "public")
        self.private_journal = self.create_journal(self.author, "Private notes content", "private")

    def create_journal(self, author, content, visibility):
        return Journal.objects.create(
            author=author,
            content=content,
            visibility=visibility,
            created_by=author,
            updated_by=author,
        )

    def test_public_feed_does_not_expose_private_journals(self):
        response = self.client.get("/api/v1/journals/list/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["meta"]["count"], 1)
        self.assertEqual(response.data["data"][0]["content"], "Public journey content")
        self.assertNotIn("saves_count", response.data["data"][0])

    def test_public_feed_returns_comment_and_reaction_counts_without_saves_count(self):
        JournalComment.objects.create(
            journal=self.public_journal,
            author=self.reader,
            text="A comment",
            created_by=self.reader,
            updated_by=self.reader,
        )
        JournalReaction.objects.create(
            journal=self.public_journal,
            user=self.reader,
            created_by=self.reader,
            updated_by=self.reader,
        )
        SavedJournal.objects.create(
            journal=self.public_journal,
            user=self.reader,
            created_by=self.reader,
            updated_by=self.reader,
        )

        response = self.client.get("/api/v1/journals/list/")

        journal = response.data["data"][0]
        self.assertEqual(journal["comments_count"], 1)
        self.assertEqual(journal["reactions_count"], 1)
        self.assertNotIn("saves_count", journal)

    def test_user_list_only_includes_private_journals_for_owner(self):
        url = f"/api/v1/journals/users/{self.author.id}/list/"
        reader_response = self.client.get(url)
        self.client.force_authenticate(self.author)
        owner_response = self.client.get(url)

        self.assertEqual(reader_response.data["meta"]["count"], 1)
        self.assertEqual(owner_response.data["meta"]["count"], 2)

    def test_private_journal_detail_is_hidden_from_other_users(self):
        self.client.force_authenticate(self.reader)

        response = self.client.get(f"/api/v1/journals/{self.private_journal.id}/detail/")

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_create_journal_with_tags_and_image_urls(self):
        self.client.force_authenticate(self.author)

        response = self.client.post(
            "/api/v1/journals/create/",
            {
                "content": "A week by the sea.",
                "visibility": "public",
                "tags": ["Beach", " beach ", "Food"],
                "image_urls": ["https://example.com/island.jpg"],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(response.data["data"]["tags"], ["Beach", "Food"])
        self.assertEqual(response.data["data"]["images"][0]["image_url"], "https://example.com/island.jpg")

    def test_only_author_can_update_or_delete_journal(self):
        self.client.force_authenticate(self.reader)
        update_response = self.client.patch(
            f"/api/v1/journals/{self.public_journal.id}/update/",
            {"content": "Changed"},
            format="json",
        )
        delete_response = self.client.delete(f"/api/v1/journals/{self.public_journal.id}/delete/")

        self.assertEqual(update_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(delete_response.status_code, status.HTTP_404_NOT_FOUND)
        self.public_journal.refresh_from_db()
        self.assertEqual(self.public_journal.content, "Public journey content")

    def test_owner_can_remove_an_image_during_update(self):
        image = JournalImage.objects.create(
            journal=self.public_journal,
            image_url="https://example.com/old.jpg",
            created_by=self.author,
        )
        self.client.force_authenticate(self.author)

        response = self.client.patch(
            f"/api/v1/journals/{self.public_journal.id}/update/",
            {"remove_image_ids": [str(image.id)]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(JournalImage.objects.filter(pk=image.pk).exists())

    def test_save_and_remove_are_idempotent(self):
        self.client.force_authenticate(self.reader)
        url = f"/api/v1/journals/{self.public_journal.id}/save/"

        self.client.post(url)
        second_save = self.client.post(url)
        self.assertEqual(second_save.status_code, status.HTTP_200_OK)
        self.assertEqual(SavedJournal.objects.count(), 1)

        self.client.delete(url)
        second_delete = self.client.delete(url)
        self.assertEqual(second_delete.status_code, status.HTTP_200_OK)
        self.assertEqual(SavedJournal.objects.count(), 0)

    def test_react_and_unreact_are_idempotent(self):
        self.client.force_authenticate(self.reader)
        url = f"/api/v1/journals/{self.public_journal.id}/react/"

        self.client.post(url)
        second_react = self.client.post(url)
        self.assertEqual(second_react.status_code, status.HTTP_200_OK)
        self.assertEqual(second_react.data["data"]["reactions_count"], 1)
        self.assertEqual(JournalReaction.objects.count(), 1)

        detail_response = self.client.get(f"/api/v1/journals/{self.public_journal.id}/detail/")
        self.assertTrue(detail_response.data["data"]["is_reacted"])
        self.assertEqual(detail_response.data["data"]["reactions_count"], 1)

        self.client.delete(url)
        second_delete = self.client.delete(url)
        self.assertEqual(second_delete.status_code, status.HTTP_200_OK)
        self.assertEqual(second_delete.data["data"]["reactions_count"], 0)
        self.assertEqual(JournalReaction.objects.count(), 0)


class JournalCommentApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.author = User.objects.create_user(email="author@example.com", password="testpass123")
        self.commenter = User.objects.create_user(email="commenter@example.com", password="testpass123")
        self.other = User.objects.create_user(email="other@example.com", password="testpass123")
        self.journal = Journal.objects.create(
            author=self.author,
            content="Travel notes",
            created_by=self.author,
            updated_by=self.author,
        )

    def test_comment_and_reply_flow(self):
        self.client.force_authenticate(self.commenter)
        comments_url = f"/api/v1/journals/{self.journal.id}/comments/"
        comment_response = self.client.post(comments_url, {"text": "Great trip"}, format="json")
        comment_id = comment_response.data["data"]["id"]
        replies_url = f"/api/v1/journals/{self.journal.id}/comments/{comment_id}/replies/"

        reply_response = self.client.post(
            replies_url,
            {"image_url": "https://example.com/reply.jpg"},
            format="json",
        )
        comments_response = self.client.get(comments_url)
        replies_response = self.client.get(replies_url)

        self.assertEqual(comment_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(reply_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(comments_response.data["data"][0]["replies_count"], 1)
        self.assertEqual(replies_response.data["meta"]["count"], 1)

    def test_empty_comment_is_rejected(self):
        self.client.force_authenticate(self.commenter)

        response = self.client.post(
            f"/api/v1/journals/{self.journal.id}/comments/",
            {"text": "   "},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_only_comment_author_can_delete_comment_or_reply(self):
        comment = JournalComment.objects.create(
            journal=self.journal,
            author=self.commenter,
            text="My comment",
            created_by=self.commenter,
            updated_by=self.commenter,
        )
        url = f"/api/v1/journals/comments/{comment.id}/delete/"
        self.client.force_authenticate(self.other)
        denied_response = self.client.delete(url)
        self.client.force_authenticate(self.commenter)
        deleted_response = self.client.delete(url)

        self.assertEqual(denied_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(deleted_response.status_code, status.HTTP_200_OK)
        self.assertFalse(JournalComment.objects.filter(pk=comment.pk).exists())

    def test_only_comment_author_can_update_comment_or_reply(self):
        comment = JournalComment.objects.create(
            journal=self.journal,
            author=self.commenter,
            text="My comment",
            created_by=self.commenter,
            updated_by=self.commenter,
        )
        url = f"/api/v1/journals/comments/{comment.id}/update/"
        self.client.force_authenticate(self.other)
        denied_response = self.client.patch(url, {"text": "Denied"}, format="json")
        self.client.force_authenticate(self.commenter)
        updated_response = self.client.patch(url, {"text": "Updated"}, format="json")

        self.assertEqual(denied_response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(updated_response.status_code, status.HTTP_200_OK)
        self.assertEqual(updated_response.data["data"]["text"], "Updated")
        comment.refresh_from_db()
        self.assertEqual(comment.text, "Updated")


class ContentReportApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.author = User.objects.create_user(
            email="reported-author@example.com",
            password="testpass123",
        )
        self.commenter = User.objects.create_user(
            email="reported-commenter@example.com",
            password="testpass123",
        )
        self.reporter = User.objects.create_user(
            email="content-reporter@example.com",
            password="testpass123",
        )
        self.journal = Journal.objects.create(
            author=self.author,
            content="Reported travel journal",
            created_by=self.author,
            updated_by=self.author,
        )
        self.comment = JournalComment.objects.create(
            journal=self.journal,
            author=self.commenter,
            text="Reported comment",
            created_by=self.commenter,
            updated_by=self.commenter,
        )

    def test_authenticated_user_can_report_another_users_journal_and_comment(self):
        self.client.force_authenticate(user=self.reporter)

        journal_response = self.client.post(
            f"/api/v1/journals/{self.journal.id}/report/",
            {"reason": "This journal violates the rules."},
            format="json",
        )
        comment_response = self.client.post(
            f"/api/v1/journals/comments/{self.comment.id}/report/",
            {"reason": "This comment is abusive."},
            format="json",
        )

        self.assertEqual(journal_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(comment_response.status_code, status.HTTP_201_CREATED)
        self.assertEqual(ContentReport.objects.count(), 2)
        self.assertEqual(journal_response.data["data"]["target_type"], "journal")
        self.assertEqual(comment_response.data["data"]["target_type"], "comment")

    def test_user_cannot_report_own_content_or_duplicate_pending_report(self):
        self.client.force_authenticate(user=self.author)
        own_journal = self.client.post(
            f"/api/v1/journals/{self.journal.id}/report/",
            {"reason": "Own journal"},
            format="json",
        )

        self.client.force_authenticate(user=self.commenter)
        own_comment = self.client.post(
            f"/api/v1/journals/comments/{self.comment.id}/report/",
            {"reason": "Own comment"},
            format="json",
        )

        self.client.force_authenticate(user=self.reporter)
        first = self.client.post(
            f"/api/v1/journals/{self.journal.id}/report/",
            {"reason": "First report"},
            format="json",
        )
        duplicate = self.client.post(
            f"/api/v1/journals/{self.journal.id}/report/",
            {"reason": "Duplicate report"},
            format="json",
        )

        self.assertEqual(own_journal.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(own_comment.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(first.status_code, status.HTTP_201_CREATED)
        self.assertEqual(duplicate.status_code, status.HTTP_400_BAD_REQUEST)

    def test_report_requires_authentication_and_nonblank_reason(self):
        url = f"/api/v1/journals/{self.journal.id}/report/"
        anonymous = self.client.post(url, {"reason": "Reason"}, format="json")
        self.client.force_authenticate(user=self.reporter)
        blank = self.client.post(url, {"reason": "   "}, format="json")

        self.assertEqual(anonymous.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(blank.status_code, status.HTTP_400_BAD_REQUEST)


class AdminContentReportApiTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.admin = User.objects.create_user(
            email="journal-admin@example.com",
            password="testpass123",
            is_staff=True,
        )
        self.author = User.objects.create_user(
            email="moderated-author@example.com",
            password="testpass123",
        )
        self.commenter = User.objects.create_user(
            email="moderated-commenter@example.com",
            password="testpass123",
        )
        self.reporter = User.objects.create_user(
            email="moderation-reporter@example.com",
            password="testpass123",
        )
        self.journal = Journal.objects.create(
            author=self.author,
            content="Journal under moderation",
            created_by=self.author,
            updated_by=self.author,
        )
        self.comment = JournalComment.objects.create(
            journal=self.journal,
            author=self.commenter,
            text="Comment under moderation",
            created_by=self.commenter,
            updated_by=self.commenter,
        )
        self.list_url = "/api/v1/admin/journals/reports/"

    def create_report(self, target_type):
        values = {
            "reporter": self.reporter,
            "target_type": target_type,
            "reason": "Reported content",
            "created_by": self.reporter,
            "updated_by": self.reporter,
        }
        if target_type == ContentReportTarget.JOURNAL:
            values["journal"] = self.journal
        else:
            values["comment"] = self.comment
        return ContentReport.objects.create(**values)

    def test_staff_admin_can_list_and_filter_reports(self):
        journal_report = self.create_report(ContentReportTarget.JOURNAL)
        self.create_report(ContentReportTarget.COMMENT)
        self.client.force_authenticate(user=self.admin)

        response = self.client.get(self.list_url, {"target_type": "journal", "status": "pending"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.data["meta"]["count"], 1)
        row = response.data["data"][0]
        self.assertEqual(row["id"], str(journal_report.id))
        self.assertEqual(row["target"]["content"], self.journal.content)
        self.assertEqual(row["reporter"]["email"], self.reporter.email)

    @patch("notification.services.emit_notification")
    def test_accepting_journal_report_requires_comment_soft_deletes_and_notifies(
        self, _emit_notification
    ):
        report = self.create_report(ContentReportTarget.JOURNAL)
        self.author.profile.total_journal_count = 1
        self.author.profile.save(update_fields=["total_journal_count"])
        self.client.force_authenticate(user=self.admin)
        url = f"{self.list_url}{report.id}/review/"

        missing_comment = self.client.patch(url, {"action": "accept"}, format="json")
        with self.captureOnCommitCallbacks(execute=True):
            accepted = self.client.patch(
                url,
                {
                    "action": "accept",
                    "admin_comment": "This content breached our community rules.",
                },
                format="json",
            )

        self.assertEqual(missing_comment.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(accepted.status_code, status.HTTP_200_OK)
        report.refresh_from_db()
        self.journal.refresh_from_db()
        self.author.profile.refresh_from_db()
        self.assertEqual(report.status, ContentReportStatus.ACCEPTED)
        self.assertIsNotNone(self.journal.deleted_at)
        self.assertEqual(self.author.profile.total_journal_count, 0)
        notification = Notification.objects.get(
            recipient=self.author,
            metadata__moderation_report_id=str(report.id),
        )
        self.assertEqual(notification.message, "This content breached our community rules.")
        self.assertEqual(self.client.get("/api/v1/journals/list/").data["meta"]["count"], 0)
        self.assertEqual(
            self.client.get(f"/api/v1/journals/{self.journal.id}/detail/").status_code,
            status.HTTP_404_NOT_FOUND,
        )

    @patch("notification.services.emit_notification")
    def test_accepting_comment_report_hides_comment_and_notifies_commenter(
        self, _emit_notification
    ):
        report = self.create_report(ContentReportTarget.COMMENT)
        self.client.force_authenticate(user=self.admin)

        with self.captureOnCommitCallbacks(execute=True):
            response = self.client.patch(
                f"{self.list_url}{report.id}/review/",
                {"action": "accept", "admin_comment": "This comment was inappropriate."},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.comment.refresh_from_db()
        self.assertIsNotNone(self.comment.deleted_at)
        comments = self.client.get(f"/api/v1/journals/{self.journal.id}/comments/")
        self.assertEqual(comments.data["meta"]["count"], 0)
        self.assertTrue(
            Notification.objects.filter(
                recipient=self.commenter,
                metadata__moderation_report_id=str(report.id),
                message="This comment was inappropriate.",
            ).exists()
        )

    def test_rejecting_report_keeps_content_visible_and_repeated_review_is_blocked(self):
        report = self.create_report(ContentReportTarget.JOURNAL)
        self.client.force_authenticate(user=self.admin)
        url = f"{self.list_url}{report.id}/review/"

        rejected = self.client.patch(url, {"action": "reject"}, format="json")
        repeated = self.client.patch(
            url,
            {"action": "accept", "admin_comment": "Try to remove after review."},
            format="json",
        )

        self.assertEqual(rejected.status_code, status.HTTP_200_OK)
        self.assertEqual(repeated.status_code, status.HTTP_400_BAD_REQUEST)
        self.journal.refresh_from_db()
        self.assertIsNone(self.journal.deleted_at)

    def test_regular_user_cannot_access_admin_report_apis(self):
        report = self.create_report(ContentReportTarget.JOURNAL)
        self.client.force_authenticate(user=self.reporter)

        list_response = self.client.get(self.list_url)
        review_response = self.client.patch(
            f"{self.list_url}{report.id}/review/",
            {"action": "reject"},
            format="json",
        )

        self.assertEqual(list_response.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(review_response.status_code, status.HTTP_403_FORBIDDEN)
