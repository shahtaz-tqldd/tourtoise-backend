from django.db import transaction
from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from destinations.models import Activity, Attraction, Cuisine, Destination
from destinations.tasks import process_vector_operations


VECTOR_SIGNAL_STATE_ATTR = "_destination_vector_signal_state"


def _queue_vector_operation(operation):
    connection = transaction.get_connection()
    atomic_depth = len(getattr(connection, "savepoint_ids", []))
    state = getattr(connection, VECTOR_SIGNAL_STATE_ATTR, None)
    if state is not None and state.get("atomic_depth") != atomic_depth:
        state = None
        setattr(connection, VECTOR_SIGNAL_STATE_ATTR, None)

    if state is None:
        state = {
            "operations": [],
            "scheduled": False,
            "atomic_depth": atomic_depth,
        }
        setattr(connection, VECTOR_SIGNAL_STATE_ATTR, state)

    if operation not in state["operations"]:
        state["operations"].append(operation)

    if state["scheduled"]:
        return

    state["scheduled"] = True

    def flush():
        queued_state = getattr(connection, VECTOR_SIGNAL_STATE_ATTR, None)
        setattr(connection, VECTOR_SIGNAL_STATE_ATTR, None)
        operations = queued_state["operations"] if queued_state else []
        normalized_operations = _normalize_vector_operations(operations)
        if normalized_operations:
            process_vector_operations.delay(normalized_operations)

    transaction.on_commit(flush)


def _normalize_vector_operations(operations):
    destination_tree_ids = {
        operation["destination_id"]
        for operation in operations
        if operation["action"] == "index_tree"
    }
    deleted_destination_ids = {
        operation["destination_id"]
        for operation in operations
        if operation["action"] == "delete_tree"
    }

    normalized = []
    seen = set()

    for operation in operations:
        action = operation["action"]
        source_type = operation["source_type"]
        source_id = operation["source_id"]
        destination_id = operation["destination_id"]

        if action == "index" and destination_id in destination_tree_ids:
            continue
        if action == "delete" and destination_id in deleted_destination_ids:
            continue

        operation_key = (action, source_type, source_id, destination_id)
        if operation_key in seen:
            continue
        seen.add(operation_key)
        normalized.append(operation)

    return normalized


@receiver(post_save, sender=Destination)
def queue_destination_vector_index(sender, instance, created, **kwargs):
    if not created:
        return

    _queue_vector_operation(
        {
            "action": "index_tree",
            "source_type": "destination",
            "source_id": str(instance.id),
            "destination_id": str(instance.id),
        }
    )


@receiver(post_save, sender=Attraction)
def queue_attraction_vector_index(sender, instance, created, **kwargs):
    if not created:
        return

    _queue_vector_operation(
        {
            "action": "index",
            "source_type": "attraction",
            "source_id": str(instance.id),
            "destination_id": str(instance.destination_id),
        }
    )


@receiver(post_save, sender=Activity)
def queue_activity_vector_index(sender, instance, created, **kwargs):
    if not created:
        return

    _queue_vector_operation(
        {
            "action": "index",
            "source_type": "activity",
            "source_id": str(instance.id),
            "destination_id": str(instance.destination_id),
        }
    )


@receiver(post_save, sender=Cuisine)
def queue_cuisine_vector_index(sender, instance, created, **kwargs):
    if not created:
        return

    _queue_vector_operation(
        {
            "action": "index",
            "source_type": "cuisine",
            "source_id": str(instance.id),
            "destination_id": str(instance.destination_id),
        }
    )


@receiver(post_delete, sender=Destination)
def queue_destination_vector_delete(sender, instance, **kwargs):
    _queue_vector_operation(
        {
            "action": "delete_tree",
            "source_type": "destination",
            "source_id": str(instance.id),
            "destination_id": str(instance.id),
        }
    )


@receiver(post_delete, sender=Attraction)
def queue_attraction_vector_delete(sender, instance, **kwargs):
    _queue_vector_operation(
        {
            "action": "delete",
            "source_type": "attraction",
            "source_id": str(instance.id),
            "destination_id": str(instance.destination_id),
        }
    )


@receiver(post_delete, sender=Activity)
def queue_activity_vector_delete(sender, instance, **kwargs):
    _queue_vector_operation(
        {
            "action": "delete",
            "source_type": "activity",
            "source_id": str(instance.id),
            "destination_id": str(instance.destination_id),
        }
    )


@receiver(post_delete, sender=Cuisine)
def queue_cuisine_vector_delete(sender, instance, **kwargs):
    _queue_vector_operation(
        {
            "action": "delete",
            "source_type": "cuisine",
            "source_id": str(instance.id),
            "destination_id": str(instance.destination_id),
        }
    )
