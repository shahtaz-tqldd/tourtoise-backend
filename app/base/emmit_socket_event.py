import logging

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.core.exceptions import ValidationError

from notification.models import Notification, NotificationType
from notification.api.v1.client.serializers import NotificationSerializer

logger = logging.getLogger(__name__)


def user_dashboard_group(user_id):
    return f"notifications.user.{user_id}"


def global_dashboard_group():
    return "notifications.global"


def emit_notification(notification):
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return

    payload = {
        "type": "notification.created",
        "notification": NotificationSerializer(notification).data,
    }

    try:
        if notification.notification_type == NotificationType.GLOBAL:
            async_to_sync(channel_layer.group_send)(global_dashboard_group(), payload)
            return

        async_to_sync(channel_layer.group_send)(
            user_dashboard_group(notification.recipient_id),
            payload,
        )
    except Exception:
        logger.exception("Failed to emit notification %s", notification.id)
