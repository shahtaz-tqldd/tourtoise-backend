from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.choices import CreditTransactionType
from accounts.models import CreditTransaction, UserCredit


class Command(BaseCommand):
    help = "Grant the one-time initial 100 credits to existing users not yet initialized."

    # python manage.py grant_initial_credits

    def handle(self, *args, **options):
        user_model = get_user_model()
        granted_count = 0
        skipped_count = 0

        for user in user_model.objects.only("id").iterator(chunk_size=500):
            if self._grant_to_user(user):
                granted_count += 1
            else:
                skipped_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Initial credits granted to {granted_count} user(s); "
                f"{skipped_count} already initialized user(s) skipped."
            )
        )

    @staticmethod
    @transaction.atomic
    def _grant_to_user(user):
        account, _ = UserCredit.objects.select_for_update().get_or_create(user=user)
        if account.transactions.filter(
            transaction_type=CreditTransactionType.INITIAL_GRANT
        ).exists():
            return False

        CreditTransaction.objects.create(
            account=account,
            transaction_type=CreditTransactionType.INITIAL_GRANT,
            amount=100,
            description="Initial credit grant for existing user",
            metadata={"source": "grant_initial_credits_command"},
        )
        account.balance += 100
        account.save(update_fields=["balance", "updated_at"])
        return True
