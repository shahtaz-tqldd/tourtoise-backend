from django.db import transaction
from rest_framework import serializers

from accounts.services.user_profile import increment_user_journal_count
from app.utils.cloudinary import upload_image
from journals.models import ContentReport, Journal, JournalComment, JournalImage, JournalTag


class JournalAuthorSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    name = serializers.CharField(read_only=True)
    username = serializers.CharField(source="profile.username", read_only=True, allow_null=True)
    avatar_url = serializers.URLField(source="profile.avatar_url", read_only=True, allow_blank=True)


class JournalImageSerializer(serializers.ModelSerializer):
    class Meta:
        model = JournalImage
        fields = ("id", "image_url", "caption", "sort_order")
        read_only_fields = fields


class JournalListSerializer(serializers.ModelSerializer):
    author = JournalAuthorSerializer(read_only=True)
    tags = serializers.SlugRelatedField(many=True, read_only=True, slug_field="name")
    images = JournalImageSerializer(many=True, read_only=True)
    comments_count = serializers.IntegerField(read_only=True)
    saves_count = serializers.IntegerField(read_only=True)
    reactions_count = serializers.IntegerField(read_only=True)
    is_saved = serializers.BooleanField(read_only=True)
    is_reacted = serializers.BooleanField(read_only=True)

    class Meta:
        model = Journal
        fields = (
            "id",
            "author",
            "content",
            "visibility",
            "tags",
            "images",
            "comments_count",
            "saves_count",
            "reactions_count",
            "is_saved",
            "is_reacted",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class JournalWriteSerializer(serializers.ModelSerializer):
    tags = serializers.ListField(
        child=serializers.CharField(max_length=50, trim_whitespace=True),
        required=False,
        allow_empty=True,
        write_only=True,
    )
    image_urls = serializers.ListField(
        child=serializers.URLField(),
        required=False,
        allow_empty=True,
        write_only=True,
    )
    images = serializers.ListField(
        child=serializers.ImageField(),
        required=False,
        allow_empty=True,
        write_only=True,
    )
    remove_image_ids = serializers.ListField(
        child=serializers.UUIDField(),
        required=False,
        allow_empty=True,
        write_only=True,
    )

    class Meta:
        model = Journal
        fields = (
            "content",
            "visibility",
            "tags",
            "image_urls",
            "images",
            "remove_image_ids",
        )

    def validate_tags(self, values):
        cleaned = []
        seen = set()
        for value in values:
            value = " ".join(value.split())
            key = value.casefold()
            if value and key not in seen:
                cleaned.append(value)
                seen.add(key)
        return cleaned

    def validate(self, attrs):
        if self.instance is None and attrs.get("remove_image_ids"):
            raise serializers.ValidationError(
                {"remove_image_ids": "Images can only be removed while updating a journal."}
            )
        return attrs

    @transaction.atomic
    def create(self, validated_data):
        request = self.context["request"]
        tags, image_urls, image_files, _ = self._pop_related(validated_data)
        journal = Journal.objects.create(
            author=request.user,
            created_by=request.user,
            updated_by=request.user,
            **validated_data,
        )
        self._set_tags(journal, tags)
        self._add_images(journal, image_urls, image_files)
        increment_user_journal_count(request.user)
        return journal

    @transaction.atomic
    def update(self, instance, validated_data):
        tags, image_urls, image_files, remove_ids = self._pop_related(validated_data)
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.updated_by = self.context["request"].user
        instance.save()
        if tags is not None:
            self._set_tags(instance, tags)
        if remove_ids:
            instance.images.filter(id__in=remove_ids).delete()
        self._add_images(instance, image_urls or [], image_files or [])
        return instance

    def _pop_related(self, data):
        return (
            data.pop("tags", None),
            data.pop("image_urls", None),
            data.pop("images", None),
            data.pop("remove_image_ids", None),
        )

    def _set_tags(self, journal, names):
        if names is None:
            return
        tags = []
        for name in names:
            tag = JournalTag.objects.filter(name__iexact=name).first()
            if tag is None:
                tag = JournalTag.objects.create(
                    name=name,
                    created_by=self.context["request"].user,
                    updated_by=self.context["request"].user,
                )
            tags.append(tag)
        journal.tags.set(tags)

    def _add_images(self, journal, image_urls, image_files):
        request = self.context["request"]
        start_order = journal.images.count()
        urls = list(image_urls or [])
        for image_file in image_files or []:
            urls.append(upload_image(image_file, folder="journals")["url"])
        JournalImage.objects.bulk_create(
            [
                JournalImage(
                    journal=journal,
                    image_url=url,
                    sort_order=start_order + index,
                    created_by=request.user,
                )
                for index, url in enumerate(urls)
            ]
        )


class JournalCommentSerializer(serializers.ModelSerializer):
    author = JournalAuthorSerializer(read_only=True)
    replies_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = JournalComment
        fields = (
            "id",
            "author",
            "parent",
            "text",
            "image_url",
            "replies_count",
            "created_at",
            "updated_at",
        )
        read_only_fields = fields


class JournalCommentWriteSerializer(serializers.Serializer):
    text = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)
    image_url = serializers.URLField(required=False, allow_blank=True)
    image = serializers.ImageField(required=False, write_only=True)

    def validate(self, attrs):
        if not attrs.get("text") and not attrs.get("image_url") and not attrs.get("image"):
            raise serializers.ValidationError("A comment must contain text or an image.")
        if attrs.get("image_url") and attrs.get("image"):
            raise serializers.ValidationError(
                {"image": "Provide either image or image_url, not both."}
            )
        return attrs

    def create(self, validated_data):
        request = self.context["request"]
        image_file = validated_data.pop("image", None)
        if image_file:
            validated_data["image_url"] = upload_image(image_file, folder="journal-comments")["url"]
        return JournalComment.objects.create(
            journal=self.context["journal"],
            parent=self.context.get("parent"),
            author=request.user,
            created_by=request.user,
            updated_by=request.user,
            **validated_data,
        )

    def update(self, instance, validated_data):
        request = self.context["request"]
        image_file = validated_data.pop("image", None)
        if image_file:
            validated_data["image_url"] = upload_image(image_file, folder="journal-comments")["url"]
        for field, value in validated_data.items():
            setattr(instance, field, value)
        instance.updated_by = request.user
        instance.save()
        return instance


class ContentReportCreateSerializer(serializers.ModelSerializer):
    reason = serializers.CharField(max_length=2000, allow_blank=False, trim_whitespace=True)

    class Meta:
        model = ContentReport
        fields = ("id", "target_type", "reason", "status", "created_at")
        read_only_fields = ("id", "target_type", "status", "created_at")
