from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from accounts.choices import CreditTransactionType
from accounts.models import User


class GrantInitialCreditsCommandTests(TestCase):
    def test_grants_legacy_users_and_is_idempotent(self):
        legacy_user = User(email="legacy-credits@example.com")
        legacy_user.set_password("testpass123")
        legacy_user.save()
        initialized_user = User.objects.create_user(
            email="initialized-credits@example.com",
            password="testpass123",
        )

        first_output = StringIO()
        call_command("grant_initial_credits", stdout=first_output)
        call_command("grant_initial_credits", stdout=StringIO())

        legacy_user.refresh_from_db()
        initialized_user.refresh_from_db()
        self.assertEqual(legacy_user.credit.balance, 100)
        self.assertEqual(initialized_user.credit.balance, 100)
        self.assertEqual(
            legacy_user.credit.transactions.filter(
                transaction_type=CreditTransactionType.INITIAL_GRANT
            ).count(),
            1,
        )
        self.assertEqual(
            initialized_user.credit.transactions.filter(
                transaction_type=CreditTransactionType.INITIAL_GRANT
            ).count(),
            1,
        )
        self.assertIn("granted to 1 user(s)", first_output.getvalue())
        self.assertIn("1 already initialized user(s) skipped", first_output.getvalue())
