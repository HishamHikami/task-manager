"""Task state changes. Every change writes a timeline entry, so the history of
who held a task and when is never lost."""

from django.db import transaction
from django.utils import timezone

from .models import Update


@transaction.atomic
def record_created(task, note=""):
    return Update.objects.create(
        task=task,
        kind="created",
        body=note,
        to_holder=task.current_holder,
        to_stage=task.stage,
        occurred_at=task.created_at or timezone.now(),
    )


@transaction.atomic
def hand_off(task, to_holder, note="", occurred_at=None):
    """Move the task to another holder's desk."""
    occurred_at = occurred_at or timezone.now()
    from_holder = task.current_holder
    task.current_holder = to_holder
    task.holder_since = occurred_at
    task.save(update_fields=["current_holder", "holder_since", "updated_at"])
    return Update.objects.create(
        task=task,
        kind="handoff",
        body=note,
        from_holder=from_holder,
        to_holder=to_holder,
        occurred_at=occurred_at,
    )


@transaction.atomic
def change_stage(task, to_stage, note="", occurred_at=None):
    occurred_at = occurred_at or timezone.now()
    from_stage = task.stage
    task.stage = to_stage
    if to_stage.is_closed and not from_stage.is_closed:
        task.closed_at = occurred_at
    elif not to_stage.is_closed:
        task.closed_at = None
    task.save(update_fields=["stage", "closed_at", "updated_at"])
    return Update.objects.create(
        task=task,
        kind="stage",
        body=note,
        from_stage=from_stage,
        to_stage=to_stage,
        occurred_at=occurred_at,
    )


@transaction.atomic
def set_follow_up(task, date, note=""):
    task.follow_up_date = date
    task.follow_up_note = note
    task.save(update_fields=["follow_up_date", "follow_up_note", "updated_at"])
    if date:
        body = f"Follow up on {date:%d %b %Y}" + (f": {note}" if note else "")
    else:
        body = "Follow-up cleared"
    return Update.objects.create(task=task, kind="followup", body=body)


def touch(task):
    """Mark the task as updated (e.g. after adding a timeline note)."""
    task.save(update_fields=["updated_at"])
