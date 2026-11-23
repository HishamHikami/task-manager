"""Quick capture logic shared by the web pages and the phone-app API."""

import re

from django.db import transaction

from . import ai, services
from .models import Event, Task, Update


def guess_kind(text):
    t = text.lower()
    if re.search(r"^\[?\d{1,2}[/.]\d{1,2}[/.]\d{2,4},? \d{1,2}:\d{2}", text, re.M) or "whatsapp" in t:
        return "whatsapp"
    if re.search(r"^(from|subject|to|sent):", t, re.M) or "dear " in t or "regards" in t:
        return "email"
    if "minutes" in t or "attendees" in t or "agenda" in t:
        return "meeting"
    return "note"


def suggest(ws, text, use_ai):
    """Initial values for the review form. Returns (initial, info, error)."""
    initial = {"workspace": ws, "body": text, "kind": guess_kind(text), "action": "new_task",
               "my_role": "following"}
    info, error = {}, ""
    if use_ai:
        try:
            s, info = ai.suggest_for_capture(ws, text)
        except ai.AIError as exc:
            error, s = str(exc), None
        if s:
            initial.update({
                "summary": s["summary"], "kind": s["message_kind"], "source": s["sender"],
                "action": s["action"], "task": s["task_id"], "new_task_title": s["new_task_title"],
                "desk": s["desk"], "next_action": s["next_action"], "due_date": s["due_date"],
                "follow_up_date": s["follow_up_date"], "event_title": s["event_title"],
                "event_start": s["event_start"], "event_end": s["event_end"],
                "event_location": s["event_location"], "event_my_role": s["event_my_role"] or "guest",
                "event_kind": s["event_kind"] or "meeting", "handoff": bool(s["desk"]),
            })
            info["used_ai"] = True
    return initial, info, error


def save(ws, d):
    """Save a reviewed capture (cleaned form data). Returns a small result dict."""
    holder, contact = d.get("desk") or (None, None)
    action = d["action"]
    notes = []

    if action == "new_event":
        event = Event.objects.create(
            workspace=ws, title=d["event_title"].strip(), kind=d.get("event_kind") or "meeting",
            my_role=d.get("event_my_role") or "guest", status="invited", start=d["event_start"],
            end=d.get("event_end"), location=d.get("event_location", ""), organizer=holder,
            organizer_contact=contact, organizer_other="" if holder else d.get("source", ""),
            description="\n\n".join(x for x in [d.get("summary", ""), d.get("body", "")] if x),
            preparation=d.get("next_action", ""),
        )
        return {"type": "event", "obj": event, "headline": "Event added", "title": event.title,
                "url": event.get_absolute_url(),
                "notes": [f"{event.start:%a %d %b, %H:%M}", event.get_my_role_display(),
                          "marked Invited — answer it when you decide"]}

    with transaction.atomic():
        if action == "new_task":
            with_me = d.get("my_role") == "executing"
            task = Task.objects.create(
                workspace=ws, title=d["new_task_title"].strip(), my_role=d.get("my_role") or "following",
                stage=ws.first_open_stage() or ws.stages.first(),
                current_holder=None if with_me else holder, current_contact=None if with_me else contact,
                due_date=d.get("due_date"),
            )
            services.record_created(task)
            notes.append("on my desk" if with_me else f"with {task.desk_name}" if holder else "not assigned yet")
        else:
            task = d["task"]
            if d.get("handoff") and holder and (holder, contact) != (task.current_holder, task.current_contact):
                services.hand_off(task, holder, "", to_contact=contact)
                notes.append(f"handed to {task.desk_name}")
            if d.get("due_date") and not task.due_date:
                task.due_date = d["due_date"]
                task.save(update_fields=["due_date", "updated_at"])
        Update.objects.create(task=task, kind=d["kind"], body=d.get("body", ""), summary=d.get("summary", ""),
                              source=d.get("source", ""))
        if d.get("follow_up_date"):
            services.set_follow_up(task, d["follow_up_date"], d.get("next_action", ""))
            notes.append(f"follow up {d['follow_up_date']:%a %d %b}")
        if d.get("due_date") and action == "new_task":
            notes.append(f"due {d['due_date']:%a %d %b}")
        services.touch(task)
    return {"type": "task", "obj": task,
            "headline": "Added to the timeline of" if action == "update_task" else "New task registered",
            "title": task.title, "url": task.get_absolute_url(), "notes": notes}
