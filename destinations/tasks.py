from celery import shared_task
from django.apps import apps
from django.core.exceptions import ObjectDoesNotExist
from django.core.files.storage import default_storage
from django.db import transaction

from vector_store.services.vectorize import DestinationVectorService
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
    except FileNotFoundError:
        return {
            "result": "skipped",
            "reason": "pending_file_missing",
            "storage_path": storage_path,
        }
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
    except FileNotFoundError:
        return {
            "result": "skipped",
            "reason": "pending_file_missing",
            "storage_path": storage_path,
        }
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


@shared_task
def upload_model_gallery_image(
    storage_path,
    app_label,
    parent_model_name,
    parent_object_id,
    image_model_name,
    relation_name,
    folder,
    public_id,
    sort_order,
    created_by_id=None,
):
    parent_model = apps.get_model(app_label, parent_model_name)
    image_model = apps.get_model(app_label, image_model_name)
    try:
        parent = parent_model.objects.get(pk=parent_object_id)
    except parent_model.DoesNotExist:
        default_storage.delete(storage_path)
        return {"result": "skipped", "reason": "object_missing"}

    try:
        with default_storage.open(storage_path, "rb") as image_file:
            upload = upload_image(image_file, folder=folder, public_id=public_id)
    except FileNotFoundError:
        return {
            "result": "skipped",
            "reason": "pending_file_missing",
            "storage_path": storage_path,
        }
    finally:
        default_storage.delete(storage_path)

    with transaction.atomic():
        image_model.objects.create(
            **{
                relation_name: parent,
                "image_url": upload["url"],
                "sort_order": sort_order,
                "created_by_id": created_by_id,
            }
        )

    return {"result": "uploaded", "url": upload["url"], "public_id": upload["public_id"]}


@shared_task
def process_vector_operations(operations):
    service = DestinationVectorService()

    for operation in operations:
        action = operation["action"]
        source_type = operation["source_type"]
        source_id = operation["source_id"]
        destination_id = operation["destination_id"]

        try:
            if action == "index_tree":
                service.index_destination_tree(source_id)
                continue

            if action == "delete_tree":
                service.remove_destination_tree(destination_id)
                continue

            if action == "index":
                if source_type == "attraction":
                    service.index_attraction(source_id)
                elif source_type == "activity":
                    service.index_activity(source_id)
                elif source_type == "cuisine":
                    service.index_cuisine(source_id)
                elif source_type == "destination":
                    service.index_destination(source_id)
                continue

            if action == "delete":
                service.remove_source(source_type, source_id)
        except ObjectDoesNotExist:
            continue

    return {"result": "processed", "count": len(operations)}
