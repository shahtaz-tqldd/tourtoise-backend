from celery import shared_task
from django.apps import apps
from django.core.files.storage import default_storage
from django.db import transaction

from app.utils.cloudinary import delete_image, upload_image


@shared_task
def upload_model_image(
    storage_path,
    app_label,
    model_name,
    object_id,
    field_name,
    folder,
    public_id,
    previous_image_url=None,
):
    model = apps.get_model(app_label, model_name)
    try:
        instance = model.objects.get(pk=object_id)
    except model.DoesNotExist:
        default_storage.delete(storage_path)
        return {"result": "skipped", "reason": "object_missing"}

    try:
        with default_storage.open(storage_path, "rb") as image_file:
            upload = upload_image(image_file, folder=folder, public_id=public_id)
    finally:
        default_storage.delete(storage_path)

    setattr(instance, field_name, upload["url"])
    instance.save(update_fields=[field_name, "updated_at"])

    if previous_image_url and previous_image_url != upload["url"]:
        delete_image(image_url=previous_image_url)

    return {"result": "uploaded", "url": upload["url"], "public_id": upload["public_id"]}


@shared_task
def upload_destination_gallery_image(
    storage_path,
    destination_id,
    folder,
    public_id,
    sort_order,
    created_by_id=None,
):
    Destination = apps.get_model("destinations", "Destination")
    DestinationImage = apps.get_model("destinations", "DestinationImage")
    try:
        destination = Destination.objects.get(pk=destination_id)
    except Destination.DoesNotExist:
        default_storage.delete(storage_path)
        return {"result": "skipped", "reason": "destination_missing"}

    try:
        with default_storage.open(storage_path, "rb") as image_file:
            upload = upload_image(image_file, folder=folder, public_id=public_id)
    finally:
        default_storage.delete(storage_path)

    with transaction.atomic():
        DestinationImage.objects.create(
            destination=destination,
            image_url=upload["url"],
            sort_order=sort_order,
            created_by_id=created_by_id,
        )

    return {"result": "uploaded", "url": upload["url"], "public_id": upload["public_id"]}
