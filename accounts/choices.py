from django.db import models
from django.utils.translation import gettext_lazy as _

class AccountStatus(models.TextChoices):
    ACTIVE = "ACTIVE", _("Active")
    SUSPENDED = "SUSPENDED", _("Suspended")
    DEACTIVATED = "DEACTIVATED", _("Deactivated")
    PREMIUM = "PREMIUM", _("Premium")


class AccountProvider(models.TextChoices):
    PASSWORD = "password", _("Password")
    GOOGLE = "google", _("Google")


class TravelStyle(models.TextChoices):
    ADVENTURE = "ADVENTURE", _("Adventure")
    LUXURY = "LUXURY", _("Luxury")
    BUDGET = "BUDGET", _("Budget")
    CULTURAL = "CULTURAL", _("Cultural")
    FAMILY = "FAMILY", _("Family")
    SOLO = "SOLO", _("Solo")
    WELLNESS = "WELLNESS", _("Wellness")
    BUSINESS = "BUSINESS", _("Business")
