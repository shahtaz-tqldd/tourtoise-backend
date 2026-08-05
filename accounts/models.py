import uuid
from django.apps import apps
from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractBaseUser, PermissionsMixin
from django.core.validators import RegexValidator
from django.db import models, transaction
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from accounts.choices import AccountProvider, AccountStatus, CreditTransactionType
from app.base.validators import validate_timezone_name


phone_regex = RegexValidator(
    regex=r"^\+?\d{6,15}$",
    message=_("Phone number must be between 6 and 15 digits and may start with '+'."),
)

class UserManager(BaseUserManager):
    use_in_migrations = True

    @transaction.atomic
    def _create_user(self, email, password, **extra_fields):
        if not email:
            raise ValueError("The email field is required.")

        email = self.normalize_email(email)
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        apps.get_model("accounts", "UserProfile").objects.get_or_create(user=user)
        credit_account, created = apps.get_model("accounts", "UserCredit").objects.get_or_create(
            user=user,
            defaults={"balance": 100},
        )
        if created:
            apps.get_model("accounts", "CreditTransaction").objects.create(
                account=credit_account,
                transaction_type=CreditTransactionType.INITIAL_GRANT,
                amount=100,
                description="Initial credit grant",
            )
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("status", AccountStatus.ACTIVE)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        extra_fields.setdefault("is_active", True)
        extra_fields.setdefault("status", AccountStatus.ACTIVE)

        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")

        return self._create_user(email, password, **extra_fields)


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    email = models.EmailField(unique=True, verbose_name=_("Email address"))
    name = models.CharField(max_length=50, blank=True, verbose_name=_("Full Name"))
    phone = models.CharField(
        validators=[phone_regex],
        max_length=17,
        blank=True,
        verbose_name=_("Phone number"),
    )
    status = models.CharField(
        max_length=16,
        choices=AccountStatus.choices,
        default=AccountStatus.ACTIVE,
        verbose_name=_("Account status"),
    )
    is_email_verified = models.BooleanField(default=False, verbose_name=_("Email verified"))
    provider = models.CharField(
        max_length=20,
        choices=AccountProvider.choices,
        default=AccountProvider.PASSWORD,
        verbose_name=_("Auth provider"),
    )
    firebase_uid = models.CharField(
        max_length=128,
        unique=True,
        blank=True,
        null=True,
        verbose_name=_("Firebase UID"),
    )
    firebase_id_token = models.TextField(blank=True, verbose_name=_("Firebase ID token"))
    google_access_token = models.TextField(blank=True, verbose_name=_("Google access token"))
    is_active = models.BooleanField(default=True, verbose_name=_("Active"))
    is_staff = models.BooleanField(default=False, verbose_name=_("Staff status"))
    deleted_at = models.DateTimeField(null=True, blank=True, db_index=True, verbose_name=_("Deleted at"))
    created_at = models.DateTimeField(auto_now_add=True, verbose_name=_("Created at"))
    updated_at = models.DateTimeField(auto_now=True, verbose_name=_("Updated at"))

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    class Meta:
        verbose_name = _("User")
        verbose_name_plural = _("Users")
        ordering = ["-created_at"]

    def __str__(self):
        return self.name or self.email

    def mark_deleted(self):
        self.status = AccountStatus.DEACTIVATED
        self.deleted_at = timezone.now()
        self.save(update_fields=["status", "deleted_at", "updated_at"])

    def reactivate(self):
        self.is_active = True
        self.status = AccountStatus.ACTIVE
        self.deleted_at = None
        self.save(update_fields=["is_active", "status", "deleted_at", "updated_at"])


class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="profile")
    username = models.SlugField(max_length=50, unique=True, blank=True, null=True)
    avatar_url = models.URLField(blank=True)
    bio = models.TextField(blank=True)
    date_of_birth = models.DateField(blank=True, null=True)
    gender = models.CharField(max_length=30, blank=True)
    country_of_residence = models.CharField(max_length=100, blank=True)
    city = models.CharField(max_length=100, blank=True)
    preferred_language = models.CharField(max_length=20, blank=True, default="en")
    preferred_currency = models.CharField(max_length=10, blank=True, default="USD")
    timezone = models.CharField(
        max_length=64,
        default="UTC",
        validators=[validate_timezone_name],
        help_text="IANA timezone used for trip reminders, for example Asia/Dhaka.",
    )
    travel_interests = models.JSONField(default=list, blank=True)
    dietary_preferences = models.JSONField(default=list, blank=True)
    travel_pace = models.CharField(max_length=40, blank=True)
    mobility_constraints = models.JSONField(default=list, blank=True)
    emergency_contact_name = models.CharField(max_length=100, blank=True)
    emergency_contact_phone = models.CharField(
        max_length=17,
        blank=True,
        validators=[phone_regex],
    )
    is_public_profile = models.BooleanField(default=False)
    total_country_visited = models.PositiveIntegerField(default=0)
    visited_country_list = models.JSONField(default=list, blank=True)
    total_trip_count = models.PositiveIntegerField(default=0)
    total_journal_count = models.PositiveIntegerField(default=0)
    is_location_sharing_enabled = models.BooleanField(default=False)
    is_alert_notification_enabled = models.BooleanField(default=True)

    class Meta:
        verbose_name = _("User profile")
        verbose_name_plural = _("User profiles")
        ordering = ["user__created_at"]

    def __str__(self):
        return self.username or self.user.email

    @property
    def location(self):
        return ", ".join(filter(None, [self.city, self.country_of_residence]))


class UserCredit(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name="credit")
    balance = models.PositiveIntegerField(default=0)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("User credit")
        verbose_name_plural = _("User credits")

    def __str__(self):
        return f"{self.user.email} - {self.balance} credits"


class CreditTransaction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    account = models.ForeignKey(UserCredit, on_delete=models.CASCADE, related_name="transactions")
    transaction_type = models.CharField(
        max_length=30,
        choices=CreditTransactionType.choices,
    )

    # Positive means credit added; zero can mark a capped monthly refill.
    # Negative means credit spent.
    amount = models.IntegerField()

    description = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["account", "-created_at"]),
            models.Index(fields=["transaction_type", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.account.user.email} - {self.transaction_type} {self.amount}"
