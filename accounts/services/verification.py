import secrets
from datetime import timedelta

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.db import transaction
from django.template.loader import render_to_string
from django.utils import timezone

from accounts.choices import CreditTransactionType
from accounts.models import CreditTransaction, EmailVerificationOTP, User, UserCredit
from accounts.tasks import send_email_verification_otp
from notification.models import Notification, NotificationType


class InvalidVerificationOTP(ValueError):
    pass


def _deliver_verification_email(*, recipient_email, recipient_name, otp):
    context = {
        "recipient_name": recipient_name or recipient_email,
        "otp": otp,
        "expires_in_minutes": settings.EMAIL_VERIFICATION_OTP_TTL_MINUTES,
    }
    kwargs = {
        "recipient_email": recipient_email,
        "subject": "Verify your Tourtoise email",
        "message": render_to_string("emails/email_verification_otp.txt", context),
        "html_message": render_to_string("emails/email_verification_otp.html", context),
    }
    try:
        send_email_verification_otp.delay(**kwargs)
    except Exception:
        send_email_verification_otp(**kwargs)


def issue_email_verification_otp(user):
    """Replace any previous OTP and send a new four-digit code."""
    otp = f"{secrets.randbelow(10_000):04d}"
    EmailVerificationOTP.objects.update_or_create(
        user=user,
        defaults={
            "code_hash": make_password(otp),
            "expires_at": timezone.now()
            + timedelta(minutes=settings.EMAIL_VERIFICATION_OTP_TTL_MINUTES),
        },
    )
    transaction.on_commit(
        lambda: _deliver_verification_email(
            recipient_email=user.email,
            recipient_name=user.name,
            otp=otp,
        )
    )


@transaction.atomic
def complete_email_verification(user):
    """Mark an email verified and apply one-time account onboarding."""
    user = User.objects.select_for_update().get(pk=user.pk)
    if not user.is_email_verified:
        user.is_email_verified = True
        user.save(update_fields=["is_email_verified", "updated_at"])

    account, _ = UserCredit.objects.select_for_update().get_or_create(user=user)
    if not account.transactions.filter(
        transaction_type=CreditTransactionType.INITIAL_GRANT
    ).exists():
        CreditTransaction.objects.create(
            account=account,
            transaction_type=CreditTransactionType.INITIAL_GRANT,
            amount=100,
            description="Initial credit grant",
        )
        account.balance += 100
        account.save(update_fields=["balance", "updated_at"])

    Notification.objects.get_or_create(
        recipient=user,
        notification_type=NotificationType.GENERAL,
        title="Welcome to Tourtoise!",
        defaults={
            "message": "Your account is ready. Start exploring and planning your next adventure.",
            "metadata": {"show_app_feature": True},
        },
    )
    return user


@transaction.atomic
def verify_email_otp(*, email, otp):
    try:
        user = User.objects.select_for_update().get(email__iexact=email)
    except User.DoesNotExist as exc:
        raise InvalidVerificationOTP("Invalid email or OTP.") from exc

    if user.is_email_verified:
        raise InvalidVerificationOTP("Email is already verified.")

    try:
        verification = EmailVerificationOTP.objects.select_for_update().get(user=user)
    except EmailVerificationOTP.DoesNotExist as exc:
        raise InvalidVerificationOTP("Invalid email or OTP.") from exc

    if verification.expires_at <= timezone.now():
        verification.delete()
        raise InvalidVerificationOTP("OTP has expired.")
    if not check_password(otp, verification.code_hash):
        raise InvalidVerificationOTP("Invalid email or OTP.")

    user = complete_email_verification(user)
    user.last_login = timezone.now()
    user.save(update_fields=["last_login"])
    verification.delete()
    return user
