from django.contrib.auth import get_user_model
from django.test import TestCase
from rest_framework import status
from rest_framework.test import APIClient

from journals.models import Journal, JournalComment, JournalImage, SavedJournal


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
