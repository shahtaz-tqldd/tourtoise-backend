from django.db import migrations, models


def empty_usernames_to_null(apps, schema_editor):
    UserProfile = apps.get_model("accounts", "UserProfile")
    UserProfile.objects.filter(username="").update(username=None)


def null_usernames_to_empty(apps, schema_editor):
    UserProfile = apps.get_model("accounts", "UserProfile")
    for profile in UserProfile.objects.filter(username__isnull=True).only("pk"):
        UserProfile.objects.filter(pk=profile.pk).update(username=f"user-{profile.pk}")


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0002_user_is_active"),
    ]

    operations = [
        migrations.AlterField(
            model_name="userprofile",
            name="username",
            field=models.SlugField(blank=True, max_length=50, null=True, unique=True),
        ),
        migrations.RunPython(empty_usernames_to_null, null_usernames_to_empty),
    ]
