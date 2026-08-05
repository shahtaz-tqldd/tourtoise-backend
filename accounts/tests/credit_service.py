from datetime import datetime, timezone as datetime_timezone

from django.test import TestCase

from accounts.choices import AccountStatus, CreditTransactionType
from accounts.models import CreditTransaction, User
from accounts.services.credit import CreditService, InsufficientCreditsError


class CreditServiceTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            email="credits@example.com",
            password="testpass123",
        )
        self.account = self.user.credit
        self.account.balance = 50
        self.account.save(update_fields=["balance"])
        self.account.transactions.all().delete()

    def test_new_user_receives_initial_100_credits(self):
        new_user = User.objects.create_user(
            email="initial-credits@example.com",
            password="testpass123",
        )

        self.assertEqual(new_user.credit.balance, 100)
        initial_grant = new_user.credit.transactions.get(
            transaction_type=CreditTransactionType.INITIAL_GRANT
        )
        self.assertEqual(initial_grant.amount, 100)

    def test_add_and_spend_credits_update_balance_and_ledger(self):
        added = CreditService.add_credits(
            user=self.user,
            amount=10,
            transaction_type=CreditTransactionType.ADMIN_ADJUSTMENT,
        )
        spent = CreditService.spend_credits(
            user=self.user,
            amount=15,
            transaction_type=CreditTransactionType.TRIP_PLAN,
        )

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, 45)
        self.assertEqual(added.amount, 10)
        self.assertEqual(spent.amount, -15)

    def test_spend_credits_rejects_insufficient_balance(self):
        with self.assertRaises(InsufficientCreditsError):
            CreditService.spend_credits(
                user=self.user,
                amount=51,
                transaction_type=CreditTransactionType.TRIP_PLAN,
            )

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, 50)
        self.assertFalse(CreditTransaction.objects.exists())

    def test_failed_agent_generation_is_refunded(self):
        with self.assertRaises(RuntimeError):
            with CreditService.charge_agent_generation(
                user=self.user,
                amount=2,
                transaction_type=CreditTransactionType.AGENT_CHAT,
                description="Test generation",
            ):
                raise RuntimeError("Agent unavailable")

        self.account.refresh_from_db()
        self.assertEqual(self.account.balance, 50)
        self.assertEqual(
            list(self.account.transactions.values_list("transaction_type", "amount")),
            [
                (CreditTransactionType.REFUND, 2),
                (CreditTransactionType.AGENT_CHAT, -2),
            ],
        )

    def test_premium_user_bypasses_credit_checks_and_spending(self):
        self.user.status = AccountStatus.PREMIUM
        self.user.save(update_fields=["status"])
        self.account.balance = 0
        self.account.save(update_fields=["balance"])

        self.assertTrue(CreditService.check_credits(user=self.user, amount=1000))
        self.assertIsNone(CreditService.ensure_credits(user=self.user, amount=1000))
        transaction = CreditService.spend_credits(
            user=self.user,
            amount=1000,
            transaction_type=CreditTransactionType.AGENT_CHAT,
        )
        with CreditService.charge_agent_generation(
            user=self.user,
            amount=1000,
            transaction_type=CreditTransactionType.AGENT_CHAT,
            description="Premium generation",
        ):
            pass

        self.account.refresh_from_db()
        self.assertIsNone(transaction)
        self.assertEqual(self.account.balance, 0)
        self.assertFalse(self.account.transactions.exists())

    def test_monthly_credits_add_25_without_exceeding_100(self):
        for starting_balance, expected_amount in ((50, 25), (75, 25), (95, 5), (100, 0)):
            with self.subTest(starting_balance=starting_balance):
                self.account.balance = starting_balance
                self.account.save(update_fields=["balance"])
                CreditTransaction.objects.all().delete()

                reward = CreditService.add_monthly_credits(
                    user=self.user,
                    as_of=datetime(2026, 8, 1, tzinfo=datetime_timezone.utc),
                )

                self.account.refresh_from_db()
                self.assertEqual(self.account.balance, min(starting_balance + 25, 100))
                self.assertEqual(reward.amount, expected_amount)
                self.assertEqual(reward.metadata["reward_month"], "2026-08")

    def test_monthly_credits_are_only_applied_once_per_month(self):
        august = datetime(2026, 8, 1, tzinfo=datetime_timezone.utc)
        september = datetime(2026, 9, 1, tzinfo=datetime_timezone.utc)

        first_reward = CreditService.add_monthly_credits(user=self.user, as_of=august)
        duplicate_reward = CreditService.add_monthly_credits(user=self.user, as_of=august)
        next_reward = CreditService.add_monthly_credits(user=self.user, as_of=september)

        self.account.refresh_from_db()
        self.assertEqual(first_reward.amount, 25)
        self.assertIsNone(duplicate_reward)
        self.assertEqual(next_reward.amount, 25)
        self.assertEqual(self.account.balance, 100)
        self.assertEqual(self.account.transactions.count(), 2)

    def test_bulk_monthly_credits_skips_deactivated_users(self):
        inactive_user = User.objects.create_user(
            email="inactive-credits@example.com",
            password="testpass123",
        )
        inactive_user.mark_deleted()

        processed = CreditService.add_monthly_credits_to_all_users(
            as_of=datetime(2026, 8, 1, tzinfo=datetime_timezone.utc)
        )

        self.assertEqual(processed, 1)
        self.assertEqual(inactive_user.credit.balance, 100)
        self.assertFalse(
            inactive_user.credit.transactions.filter(
                transaction_type=CreditTransactionType.MONTHLY_REWARD
            ).exists()
        )
