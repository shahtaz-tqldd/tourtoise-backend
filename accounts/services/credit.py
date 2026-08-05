from contextlib import contextmanager
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from accounts.choices import AccountStatus, CreditTransactionType
from accounts.models import CreditTransaction, User, UserCredit


class InsufficientCreditsError(Exception):
    pass


class CreditService:
    AGENT_CHAT_COST = 2
    TRIP_CHAT_COST = 1
    PREFERENCE_QUESTION_COST = 1
    RECOMMENDATION_COST = 4
    ITINERARY_COST = 3
    PREPARATION_COST = 2
    MONTHLY_CREDIT_AMOUNT = 25
    MAX_MONTHLY_BALANCE = 100

    @staticmethod
    def check_credits(*, user: User, amount: int) -> bool:
        if amount < 0:
            raise ValueError("Credit amount cannot be negative.")

        if user.status == AccountStatus.PREMIUM:
            return True

        account, _ = UserCredit.objects.get_or_create(user=user)
        return account.balance >= amount

    @staticmethod
    def ensure_credits(*, user: User, amount: int) -> int | None:
        """Return the current balance or raise before a credit-backed operation starts."""
        if amount <= 0:
            raise ValueError("Credit amount must be greater than zero.")

        if user.status == AccountStatus.PREMIUM:
            return None

        account, _ = UserCredit.objects.get_or_create(user=user)
        if account.balance < amount:
            raise InsufficientCreditsError(
                f"Required {amount} credits, available {account.balance}."
            )
        return account.balance

    @staticmethod
    @transaction.atomic
    def add_credits(
        *,
        user: User,
        amount: int,
        transaction_type: str,
        description: str = "",
        metadata: dict | None = None,
    ) -> CreditTransaction:
        if amount <= 0:
            raise ValueError("Credit amount must be greater than zero.")

        account, _ = UserCredit.objects.select_for_update().get_or_create(user=user)
        credit_transaction = CreditTransaction.objects.create(
            account=account,
            transaction_type=transaction_type,
            amount=amount,
            description=description,
            metadata=metadata or {},
        )

        account.balance += amount
        account.save(update_fields=["balance", "updated_at"])
        return credit_transaction

    @staticmethod
    @transaction.atomic
    def spend_credits(
        *,
        user: User,
        amount: int,
        transaction_type: str,
        description: str = "",
        metadata: dict | None = None,
    ) -> CreditTransaction | None:
        if amount <= 0:
            raise ValueError("Credit amount must be greater than zero.")

        if user.status == AccountStatus.PREMIUM:
            return None

        account, _ = UserCredit.objects.select_for_update().get_or_create(user=user)
        if account.balance < amount:
            raise InsufficientCreditsError(
                f"Required {amount} credits, available {account.balance}."
            )

        credit_transaction = CreditTransaction.objects.create(
            account=account,
            transaction_type=transaction_type,
            amount=-amount,
            description=description,
            metadata=metadata or {},
        )

        account.balance -= amount
        account.save(update_fields=["balance", "updated_at"])
        return credit_transaction

    @classmethod
    @contextmanager
    def charge_agent_generation(
        cls,
        *,
        user: User,
        amount: int,
        transaction_type: str,
        description: str,
        metadata: dict | None = None,
    ):
        """Charge an agent call and refund it when content generation raises an error."""
        if user.status == AccountStatus.PREMIUM:
            yield None
            return

        credit_transaction = cls.spend_credits(
            user=user,
            amount=amount,
            transaction_type=transaction_type,
            description=description,
            metadata=metadata,
        )
        try:
            yield credit_transaction
        except Exception:
            cls.add_credits(
                user=user,
                amount=amount,
                transaction_type=CreditTransactionType.REFUND,
                description=f"Refund for failed generation: {description}",
                metadata={
                    **(metadata or {}),
                    "refunded_transaction_id": str(credit_transaction.id),
                },
            )
            raise

    @classmethod
    @transaction.atomic
    def add_monthly_credits(
        cls,
        *,
        user: User,
        as_of: datetime | None = None,
    ) -> CreditTransaction | None:
        """Apply this month's refill once, adding up to 25 credits with a 100 cap."""
        as_of = as_of or timezone.now()
        if timezone.is_naive(as_of):
            as_of = timezone.make_aware(as_of, timezone.get_current_timezone())
        local_date = timezone.localtime(as_of).date()
        reward_month = local_date.strftime("%Y-%m")

        account, _ = UserCredit.objects.select_for_update().get_or_create(user=user)
        already_rewarded = account.transactions.filter(
            transaction_type=CreditTransactionType.MONTHLY_REWARD,
            metadata__reward_month=reward_month,
        ).exists()
        if already_rewarded:
            return None

        amount = min(
            cls.MONTHLY_CREDIT_AMOUNT,
            max(0, cls.MAX_MONTHLY_BALANCE - account.balance),
        )
        credit_transaction = CreditTransaction.objects.create(
            account=account,
            transaction_type=CreditTransactionType.MONTHLY_REWARD,
            amount=amount,
            description=f"Monthly credit refill for {reward_month}",
            metadata={"reward_month": reward_month},
        )

        if amount:
            account.balance += amount
            account.save(update_fields=["balance", "updated_at"])
        return credit_transaction

    @classmethod
    def add_monthly_credits_to_all_users(cls, *, as_of: datetime | None = None) -> int:
        """Apply the monthly refill to every active account and return the processed count."""
        users = User.objects.filter(
            is_active=True,
            status__in=[AccountStatus.ACTIVE, AccountStatus.PREMIUM],
        ).only("id")

        processed_count = 0
        for user in users.iterator():
            if cls.add_monthly_credits(user=user, as_of=as_of) is not None:
                processed_count += 1
        return processed_count
