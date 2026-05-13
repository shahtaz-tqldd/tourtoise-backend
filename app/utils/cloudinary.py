from pathlib import Path
from urllib.parse import urlparse

from django.conf import settings
from rest_framework import serializers


def _get_client():
    try:
        import cloudinary
        import cloudinary.uploader
    except ImportError as exc:
        raise serializers.ValidationError(
            {"image": "Cloudinary dependency is missing. Install requirements and rebuild the container."}
        ) from exc

    if not all(
        [
            settings.CLOUDINARY_CLOUD_NAME,
            settings.CLOUDINARY_API_KEY,
            settings.CLOUDINARY_API_SECRET,
        ]
    ):
        raise serializers.ValidationError(
            {"image": "Cloudinary configuration is incomplete."}
        )

    cloudinary.config(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
        secure=True,
    )
    return cloudinary.uploader


def upload_image(file_obj, folder=None, public_id=None):
    uploader = _get_client()
    upload_folder = folder or settings.CLOUDINARY_FOLDER
    options = {"folder": upload_folder, "resource_type": "image"}
    if public_id:
        options["public_id"] = public_id
        options["overwrite"] = True
    result = uploader.upload(file_obj, **options)
    return {
        "url": result.get("secure_url") or result.get("url"),
        "public_id": result.get("public_id"),
    }


def delete_image(public_id=None, image_url=None):
    resolved_public_id = public_id or extract_public_id(image_url)
    if not resolved_public_id:
        return {"result": "skipped"}

    uploader = _get_client()
    result = uploader.destroy(resolved_public_id, resource_type="image")
    return {"result": result.get("result"), "public_id": resolved_public_id}


def extract_public_id(image_url):
    if not image_url:
        return None

    parsed = urlparse(image_url)
    path_parts = [part for part in parsed.path.split("/") if part]
    try:
        upload_index = path_parts.index("upload")
    except ValueError:
        return None

    public_parts = path_parts[upload_index + 1 :]
    if public_parts and public_parts[0].startswith("v"):
        public_parts = public_parts[1:]
    if not public_parts:
        return None

    public_parts[-1] = str(Path(public_parts[-1]).with_suffix(""))
    return "/".join(public_parts)
