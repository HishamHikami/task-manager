"""JSON API for the phone app.

Auth: POST /api/v1/auth/login with username + password returns a token; send it as
`Authorization: Bearer <token>` on every other call. Only a hash of the token is stored.
All writes reuse the same forms (validation) and services as the website.
"""

import json
from collections import OrderedDict
from datetime import timedelta
from functools import wraps

from django.conf import settings
from django.contrib.auth import authenticate
from django.contrib.auth.decorators import login_not_required
from django.core.cache import cache
from django.http import JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from . import ai, services
from . import capture as capture_logic
from .forms import (
    CaptureReviewForm,
    ContactForm,
    EventForm,
    FollowUpForm,
    HandoffForm,
    HolderForm,
    StageChangeForm,
    TaskForm,
    UpdateForm,
    desk_value,
)
from .models import ApiToken, AppSettings, Contact, Event, Holder, Task, Update, Workspace

API_VERSION = 1


# --- plumbing -----------------------------------------------------------------------

def _json_body(request):
    if not request.body:
        return {}
    try:
        data = json.loads(request.body)
    except (ValueError, UnicodeDecodeError):
        return None
    return data if isinstance(data, dict) else None


def _error(message, status=400, errors=None):
    payload = {"error": message}
    if errors:
        payload["errors"] = errors
    return JsonResponse(payload, status=status)


def _form_errors(form):
    out = {k: [e["message"] for e in v] for k, v in form.errors.get_json_data().items()}
    first = next(iter(out.values()))[0] if out else "Please check the form."
    return _error(first, 400, out)


def api_view(methods=("GET",), auth=True):
    """Token-authenticated JSON view. Puts parsed JSON in request.data."""

    def deco(fn):
        @csrf_exempt  # no cookies are used; requests carry a bearer token
        @login_not_required
        @wraps(fn)
        def wrapper(request, *args, **kwargs):
            if request.method not in methods:
                return _error("Method not allowed.", 405)
            if auth:
                header = request.headers.get("Authorization", "")
                raw = header[7:].strip() if header.lower().startswith("bearer ") else ""
                token = ApiToken.objects.select_related("user").filter(key_hash=ApiToken.hash(raw)).first() if raw else None
                if not token or not token.user.is_active:
                    return _error("Please log in again.", 401)
                request.user = token.user
                request.api_token = token
                now = timezone.now()
                if not token.last_used_at or now - token.last_used_at > timedelta(minutes=10):
                    ApiToken.objects.filter(pk=token.pk).update(last_used_at=now)
            request.data = {}
            if request.method in ("POST", "PATCH", "PUT"):
                data = _json_body(request)
                if data is None:
                    return _error("Send a JSON object.")
                request.data = data
            return fn(request, *args, **kwargs)

        return wrapper

    return deco


def _date(d):
    return d.isoformat() if d else None


def _dt(d):
    return timezone.localtime(d).isoformat() if d else None


# --- serializers --------------------------------------------------------------------

def ws_json(w):
    return {"id": w.pk, "name": w.name, "color": w.color, "ai_enabled": w.ai_enabled}


def person_json(p):
    if not p:
        return None
    return {"id": p.pk, "name": p.name, "role": getattr(p, "role", ""), "phone": p.phone, "email": p.email,
            "is_primary": getattr(p, "is_primary", False)}


def task_pill(t):
    if t.is_overdue:
        return {"label": f"Overdue · {t.due_date:%-d %b}", "tone": "red"}
    if t.follow_up_due:
        return {"label": "Follow up", "tone": "amber"}
    if t.due_date and not t.is_closed:
        return {"label": f"Due {t.due_date:%-d %b}", "tone": "neutral"}
    if t.follow_up_date and not t.is_closed:
        return {"label": f"Check {t.follow_up_date:%-d %b}", "tone": "ghost"}
    return None


def task_json(t):
    return {
        "id": t.pk, "title": t.title, "workspace": ws_json(t.workspace),
        "stage": {"id": t.stage_id, "name": t.stage.name, "closed": t.stage.is_closed},
        "desk": t.desk_name or ("Me" if t.with_me else ""), "with_me": t.with_me,
        "days_with_holder": t.days_with_holder if t.current_holder_id and not t.is_closed else None,
        "priority": t.priority, "priority_label": t.get_priority_display(),
        "my_role": t.my_role, "my_role_label": t.get_my_role_display(),
        "due_date": _date(t.due_date), "follow_up_date": _date(t.follow_up_date),
        "follow_up_note": t.follow_up_note, "is_overdue": t.is_overdue, "follow_up_due": t.follow_up_due,
        "is_closed": t.is_closed, "pill": task_pill(t),
    }


def update_json(u, task):
    if u.kind == "handoff":
        frm = u.from_desk or ("Me" if task.my_role == "executing" else "Nobody")
        move = {"from": frm, "to": u.to_desk or "Nobody"}
    elif u.kind == "stage":
        move = {"from": u.from_stage.name if u.from_stage else "—", "to": u.to_stage.name if u.to_stage else "—"}
    elif u.kind == "created":
        move = {"stage": u.to_stage.name if u.to_stage else "",
                "with": u.to_desk or ("me" if task.my_role == "executing" else "")}
    else:
        move = None
    return {"id": u.pk, "kind": u.kind, "kind_label": u.get_kind_display(), "occurred_at": _dt(u.occurred_at),
            "source": u.source, "summary": u.summary, "body": u.body, "move": move,
            "can_summarize": bool(u.body and not u.summary and u.kind in Update.MANUAL_KINDS)}


def desk_options(workspace, exclude=None):
    """Grouped choices for 'who has it': [{label, options:[{value,label}]}]."""
    from .forms import DeskChoiceField

    f = DeskChoiceField(required=False)
    f.set_workspace(workspace, exclude=exclude)
    groups = []
    for value, label in f.choices:
        if isinstance(label, (list, tuple)):
            groups.append({"label": value, "options": [{"value": v, "label": l} for v, l in label]})
    return groups


def event_json(e):
    return {
        "id": e.pk, "title": e.title, "workspace": ws_json(e.workspace), "kind": e.kind,
        "kind_label": e.get_kind_display(), "my_role": e.my_role, "my_role_label": e.get_my_role_display(),
        "status": e.status, "status_label": e.get_status_display(), "status_short": e.status_short,
        "start": _dt(e.start), "end": _dt(e.end), "location": e.location, "online_link": e.online_link,
        "organizer": e.organizer_name, "is_off": e.is_off,
    }


# --- auth & bootstrap ---------------------------------------------------------------

def _client_ip(request):
    return request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR", "unknown")


@api_view(methods=("POST",), auth=False)
def login(request):
    key = f"api-login-fail:{_client_ip(request)}"
    if cache.get(key, 0) >= settings.LOGIN_MAX_ATTEMPTS:
        return _error("Too many failed attempts. Try again in a few minutes.", 429)
    user = authenticate(request, username=str(request.data.get("username", "")),
                        password=str(request.data.get("password", "")))
    if not user or not user.is_active:
        cache.set(key, cache.get(key, 0) + 1, settings.LOGIN_LOCKOUT_SECONDS)
        return _error("Wrong username or password.", 401)
    cache.delete(key)
    token = ApiToken.issue(user, device=str(request.data.get("device", "")))
    return JsonResponse({"token": token, "user": {"username": user.get_username()}})


@api_view(methods=("POST",))
def logout(request):
    request.api_token.delete()
    return JsonResponse({"ok": True})


@api_view()
def bootstrap(request):
    s = AppSettings.load()
    return JsonResponse({
        "api_version": API_VERSION,
        "user": {"username": request.user.get_username()},
        "workspaces": [ws_json(w) for w in Workspace.objects.filter(archived=False)],
        "ai_ready": s.has_api_key,
        "ai_model": s.ai_model,
        "task_roles": [{"value": v, "label": l} for v, l in Task.ROLE_CHOICES],
        "priorities": [{"value": v, "label": l} for v, l in Task.PRIORITY_CHOICES],
        "update_kinds": [{"value": v, "label": l} for v, l in Update.KIND_CHOICES if v in Update.MANUAL_KINDS],
        "event_roles": [{"value": v, "label": l} for v, l in Event.ROLE_CHOICES],
        "event_kinds": [{"value": v, "label": l} for v, l in Event.KIND_CHOICES],
        "event_statuses": [{"value": v, "label": l} for v, l in Event.STATUS_CHOICES],
        "holder_kinds": [{"value": v, "label": l} for v, l in Holder.KIND_CHOICES],
    })


def _workspace_param(request):
    ws = request.GET.get("ws", "")
    if ws.isdigit():
        return Workspace.objects.filter(pk=ws, archived=False).first()
    return None


def _tasks(workspace):
    qs = (Task.objects.active_workspaces()
          .select_related("workspace", "stage", "current_holder", "current_contact__holder")
          .prefetch_related("current_holder__contacts"))
    return qs.filter(workspace=workspace) if workspace else qs


def _events(workspace):
    qs = Event.objects.filter(workspace__archived=False).select_related(
        "workspace", "organizer", "organizer_contact__holder").prefetch_related("organizer__contacts")
    return qs.filter(workspace=workspace) if workspace else qs


# --- dashboard ----------------------------------------------------------------------

@api_view()
def dashboard(request):
    workspace = _workspace_param(request)
    today = timezone.localdate()
    open_tasks = list(_tasks(workspace).open())
    attention = sorted(
        {t.pk: t for t in open_tasks if t.is_overdue or t.follow_up_due}.values(),
        key=lambda t: (not t.is_overdue, -t.priority, t.due_date or t.follow_up_date or today),
    )
    groups = OrderedDict()
    for t in sorted(open_tasks, key=lambda t: (0 if t.with_me else 2 if t.current_holder is None else 1,
                                               t.desk_name.lower(), -t.priority)):
        if t.with_me:
            key, title = "me", "On my desk"
        elif t.current_holder:
            key, title = f"{t.current_holder_id}-{t.current_contact_id}", t.desk_name
        else:
            key, title = "none", "Not assigned to anyone"
        g = groups.setdefault(key, {"title": title,
                                    "workspace": ws_json(t.workspace) if t.current_holder else None, "tasks": []})
        g["tasks"].append(task_json(t))
    soon = timezone.now() + timedelta(days=14)
    events = _events(workspace).upcoming()
    upcoming = list(events.filter(start__lte=soon).exclude(status__in=["declined", "cancelled"]).order_by("start")[:8])
    return JsonResponse({
        "today": today.isoformat(),
        "stats": {"attention": len(attention), "open": len(open_tasks), "events": len(upcoming),
                  "invites": events.filter(status="invited").count()},
        "attention": [task_json(t) for t in attention],
        "upcoming_events": [event_json(e) for e in upcoming],
        "groups": list(groups.values()),
    })


# --- tasks --------------------------------------------------------------------------

@api_view(methods=("GET", "POST"))
def tasks(request):
    if request.method == "POST":
        ws = get_object_or_404(Workspace, pk=request.data.get("workspace"), archived=False)
        if not ws.stages.exists():
            ws.create_default_stages()
        data = dict(request.data)
        data.setdefault("stage", (ws.first_open_stage() or ws.stages.first()).pk)
        data.setdefault("priority", 2)
        data.setdefault("my_role", "following")
        form = TaskForm(data, workspace=ws)
        if not form.is_valid():
            return _form_errors(form)
        task = form.save(commit=False)
        task.workspace = ws
        if task.stage.is_closed:
            task.closed_at = timezone.now()
        task.save()
        services.record_created(task, form.cleaned_data.get("first_note", ""))
        return JsonResponse({"task": task_json(task)}, status=201)

    workspace = _workspace_param(request)
    qs = _tasks(workspace)
    status = request.GET.get("status", "open")
    if status == "open":
        qs = qs.open()
    elif status == "closed":
        qs = qs.closed()
    q = request.GET.get("q", "").strip()
    if q:
        from django.db.models import Q
        qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q) | Q(reference__icontains=q)
                       | Q(updates__body__icontains=q) | Q(updates__summary__icontains=q)).distinct()
    if request.GET.get("role") in dict(Task.ROLE_CHOICES):
        qs = qs.filter(my_role=request.GET["role"])
    return JsonResponse({"tasks": [task_json(t) for t in qs[:300]]})


def _task_detail_json(task):
    updates = task.updates.select_related(
        "from_holder", "to_holder", "from_stage", "to_stage", "from_contact__holder", "to_contact__holder"
    ).prefetch_related("from_holder__contacts", "to_holder__contacts")
    h = task.current_holder
    person = task.desk_person
    contact_source = person if person and (person.phone or person.email) else h
    people = [person_json(c) for c in h.contacts.all() if c.active] if h and h.is_group else []
    return {
        **task_json(task),
        "description": task.description, "reference": task.reference,
        "holder": {"id": h.pk, "name": h.name, "kind": h.kind, "is_group": h.is_group} if h else None,
        "person": person_json(person),
        "contact": {"phone": contact_source.phone, "email": contact_source.email,
                    "is_department": contact_source is h} if contact_source else None,
        "people": people,
        "timeline": [update_json(u, task) for u in updates],
        "handoff_options": desk_options(task.workspace, exclude=desk_value(h, task.current_contact)),
        "stages": [{"id": s.pk, "name": s.name, "closed": s.is_closed} for s in task.workspace.stages.all()],
        "can_use_ai": AppSettings.load().has_api_key and task.workspace.ai_enabled,
    }


def _get_task(pk):
    return get_object_or_404(
        Task.objects.select_related("workspace", "stage", "current_holder", "current_contact__holder")
        .prefetch_related("current_holder__contacts"), pk=pk)


@api_view(methods=("GET", "PATCH", "DELETE"))
def task_detail(request, pk):
    task = _get_task(pk)
    if request.method == "DELETE":
        task.delete()
        return JsonResponse({"ok": True})
    if request.method == "PATCH":
        fields = ["title", "description", "my_role", "priority", "due_date", "follow_up_date",
                  "follow_up_note", "reference"]
        data = {f: getattr(task, f) for f in fields}
        data.update({k: v for k, v in request.data.items() if k in fields})
        form = TaskForm(data, instance=task, workspace=task.workspace)
        if not form.is_valid():
            return _form_errors(form)
        form.save()
        task = _get_task(pk)
    return JsonResponse({"task": _task_detail_json(task)})


@api_view(methods=("POST",))
def task_handoff(request, pk):
    task = _get_task(pk)
    form = HandoffForm(request.data, task=task)
    if not form.is_valid():
        return _form_errors(form)
    holder, contact = form.cleaned_data["to_holder"]
    services.hand_off(task, holder, form.cleaned_data["note"], form.cleaned_data.get("occurred_at"),
                      to_contact=contact)
    if form.cleaned_data.get("follow_up_date"):
        services.set_follow_up(task, form.cleaned_data["follow_up_date"],
                               f"Check with {contact.name if contact else holder.name}")
    return JsonResponse({"task": _task_detail_json(_get_task(pk)), "message": f"Handed to {_get_task(pk).desk_name}."})


@api_view(methods=("POST",))
def task_stage(request, pk):
    task = _get_task(pk)
    form = StageChangeForm(request.data, task=task)
    if not form.is_valid():
        return _form_errors(form)
    services.change_stage(task, form.cleaned_data["stage"], form.cleaned_data["note"])
    return JsonResponse({"task": _task_detail_json(_get_task(pk)),
                         "message": f"Moved to {form.cleaned_data['stage'].name}."})


@api_view(methods=("POST",))
def task_follow_up(request, pk):
    task = _get_task(pk)
    form = FollowUpForm(request.data)
    if not form.is_valid():
        return _form_errors(form)
    services.set_follow_up(task, form.cleaned_data["follow_up_date"], form.cleaned_data["follow_up_note"])
    return JsonResponse({"task": _task_detail_json(_get_task(pk)), "message": "Follow-up saved."})


@api_view(methods=("POST",))
def task_add_update(request, pk):
    task = _get_task(pk)
    data = dict(request.data)
    now_if_missing = not data.get("occurred_at")
    if now_if_missing:
        data["occurred_at"] = timezone.localtime().isoformat(timespec="seconds")
    data.setdefault("kind", "note")
    form = UpdateForm(data)
    if not form.is_valid():
        return _form_errors(form)
    update = form.save(commit=False)
    update.task = task
    if now_if_missing:
        update.occurred_at = timezone.now()  # exact time, so it sorts after anything earlier
    update.save()
    services.touch(task)
    return JsonResponse({"task": _task_detail_json(_get_task(pk)), "message": "Added to the timeline."})


@api_view(methods=("POST",))
def update_summarize(request, pk):
    update = get_object_or_404(Update.objects.select_related("task__workspace"), pk=pk)
    try:
        update.summary = ai.summarize(update.body, update.task.workspace)
    except ai.AIError as exc:
        return _error(str(exc))
    update.save(update_fields=["summary"])
    return JsonResponse({"task": _task_detail_json(_get_task(update.task_id))})


# --- events -------------------------------------------------------------------------

def _event_detail_json(e):
    p = e.organizer_person
    src = p if p and (p.phone or p.email) else e.organizer
    return {**event_json(e), "my_topic": e.my_topic, "duration_minutes": e.duration_minutes,
            "audience": e.audience, "description": e.description, "preparation": e.preparation,
            "organizer_person": person_json(p),
            "organizer_contact": {"phone": src.phone, "email": src.email} if src else None,
            "organizer_desk": desk_value(e.organizer, e.organizer_contact), "organizer_other": e.organizer_other,
            "presenting": e.is_presenting}


@api_view(methods=("GET", "POST"))
def events(request):
    if request.method == "POST":
        ws = get_object_or_404(Workspace, pk=request.data.get("workspace"), archived=False)
        form = EventForm(request.data, workspace=ws)
        if not form.is_valid():
            return _form_errors(form)
        event = form.save(commit=False)
        event.workspace = ws
        event.save()
        return JsonResponse({"event": _event_detail_json(event)}, status=201)
    workspace = _workspace_param(request)
    qs = _events(workspace)
    show = request.GET.get("show", "upcoming")
    if show == "past":
        qs = qs.past().order_by("-start")
    elif show == "invites":
        qs = qs.filter(status="invited").order_by("start")
    else:
        qs = qs.upcoming().order_by("start")
    return JsonResponse({"events": [event_json(e) for e in qs[:300]],
                         "invites": _events(workspace).filter(status="invited").count()})


@api_view(methods=("GET", "PATCH", "DELETE"))
def event_detail(request, pk):
    event = get_object_or_404(Event.objects.select_related("workspace", "organizer", "organizer_contact__holder"),
                              pk=pk)
    if request.method == "DELETE":
        event.delete()
        return JsonResponse({"ok": True})
    if request.method == "PATCH":
        if set(request.data) == {"status"}:
            if request.data["status"] not in dict(Event.STATUS_CHOICES):
                return _error("Unknown status.")
            event.status = request.data["status"]
            event.save(update_fields=["status", "updated_at"])
        else:
            fields = ["title", "kind", "my_role", "status", "start", "end", "location", "online_link",
                      "organizer_other", "my_topic", "duration_minutes", "audience", "description", "preparation"]
            data = {f: getattr(event, f) for f in fields}
            for f in ("start", "end"):
                if data[f]:
                    data[f] = timezone.localtime(data[f]).strftime("%Y-%m-%dT%H:%M")
            data["organizer_desk"] = desk_value(event.organizer, event.organizer_contact)
            data.update({k: v for k, v in request.data.items() if k in fields + ["organizer_desk"]})
            form = EventForm(data, instance=event, workspace=event.workspace)
            if not form.is_valid():
                return _form_errors(form)
            event = form.save()
    return JsonResponse({"event": _event_detail_json(event),
                         "organizer_options": desk_options(event.workspace)})


# --- workspaces & people ------------------------------------------------------------

@api_view()
def workspaces(request):
    from django.db.models import Count, Q

    qs = Workspace.objects.annotate(
        open_count=Count("tasks", filter=Q(tasks__stage__is_closed=False), distinct=True),
        holder_count=Count("holders", distinct=True))
    return JsonResponse({"workspaces": [{**ws_json(w), "description": w.description, "archived": w.archived,
                                         "open_count": w.open_count, "holder_count": w.holder_count} for w in qs]})


@api_view()
def workspace_detail(request, pk):
    from django.db.models import Count, Q

    w = get_object_or_404(Workspace, pk=pk)
    holders = w.holders.annotate(open_count=Count("tasks", filter=Q(tasks__stage__is_closed=False))
                                 ).prefetch_related("contacts")
    return JsonResponse({
        "workspace": {**ws_json(w), "description": w.description},
        "holders": [{"id": h.pk, "name": h.name, "kind": h.kind, "kind_label": h.get_kind_display(),
                     "is_group": h.is_group, "active": h.active, "open_count": h.open_count,
                     "people_count": len([c for c in h.contacts.all() if c.active]),
                     "main_contact": person_json(h.primary_contact)} for h in holders],
        "desks": desk_options(w),
        "tasks": [task_json(t) for t in _tasks(w).open()[:200]],
    })


def _holder_json(h):
    return {"id": h.pk, "name": h.name, "kind": h.kind, "kind_label": h.get_kind_display(), "is_group": h.is_group,
            "active": h.active, "phone": h.phone, "email": h.email, "notes": h.notes,
            "workspace": ws_json(h.workspace),
            "people": [person_json(c) | {"active": c.active, "notes": c.notes} for c in h.contacts.all()],
            "open_tasks": [task_json(t) for t in _tasks(h.workspace).open().filter(current_holder=h)]}


@api_view(methods=("POST",))
def holder_create(request, ws_pk):
    ws = get_object_or_404(Workspace, pk=ws_pk)
    data = {"active": True, **request.data}
    form = HolderForm(data, workspace=ws)
    if not form.is_valid():
        return _form_errors(form)
    if form.cleaned_data.get("department"):
        contact = form.save_into_department()
        return JsonResponse({"contact": person_json(contact), "desk": desk_value(contact=contact),
                             "holder": _holder_json(contact.holder)}, status=201)
    holder = form.save(commit=False)
    holder.workspace = ws
    holder.save()
    return JsonResponse({"holder": _holder_json(holder), "desk": desk_value(holder=holder)}, status=201)


@api_view()
def holder_detail(request, pk):
    h = get_object_or_404(Holder.objects.select_related("workspace").prefetch_related("contacts"), pk=pk)
    return JsonResponse({"holder": _holder_json(h)})


@api_view(methods=("POST",))
def contact_create(request, holder_pk):
    h = get_object_or_404(Holder, pk=holder_pk)
    data = {"active": True, "is_primary": not h.contacts.exists(), **request.data}
    form = ContactForm(data)
    if not form.is_valid():
        return _form_errors(form)
    contact = form.save(commit=False)
    contact.holder = h
    contact.save()
    return JsonResponse({"contact": person_json(contact), "desk": desk_value(contact=contact)}, status=201)


@api_view(methods=("PATCH", "DELETE"))
def contact_detail(request, pk):
    c = get_object_or_404(Contact, pk=pk)
    if request.method == "DELETE":
        c.delete()
        return JsonResponse({"ok": True})
    data = {f: getattr(c, f) for f in ["name", "role", "is_primary", "phone", "email", "notes", "active"]}
    data.update(request.data)
    form = ContactForm(data, instance=c)
    if not form.is_valid():
        return _form_errors(form)
    form.save()
    return JsonResponse({"contact": person_json(c)})


@api_view()
def desks(request, ws_pk):
    return JsonResponse({"desks": desk_options(get_object_or_404(Workspace, pk=ws_pk))})


# --- quick capture ------------------------------------------------------------------

@api_view(methods=("POST",))
def capture_suggest(request):
    ws = get_object_or_404(Workspace, pk=request.data.get("workspace"), archived=False)
    text = str(request.data.get("text", "")).strip()
    if not text:
        return _error("There's no text.")
    initial, info, error = capture_logic.suggest(ws, text, bool(request.data.get("use_ai")))
    initial = {k: (v.pk if hasattr(v, "pk") else v) for k, v in initial.items()}
    open_tasks = _tasks(ws).open().order_by("-updated_at")[:100]
    return JsonResponse({
        "suggestion": initial, "used_ai": bool(info.get("used_ai")), "cached": bool(info.get("cached")),
        "shortened": bool(info.get("shortened")), "error": error,
        "tasks": [{"id": t.pk, "title": t.title, "desk": t.desk_name or ("Me" if t.with_me else "")}
                  for t in open_tasks],
        "desks": desk_options(ws),
    })


@api_view(methods=("POST",))
def capture_save(request):
    ws = get_object_or_404(Workspace, pk=request.data.get("workspace"), archived=False)
    form = CaptureReviewForm(request.data, workspace=ws)
    if not form.is_valid():
        return _form_errors(form)
    result = capture_logic.save(ws, form.cleaned_data)
    obj = result["obj"]
    return JsonResponse({"type": result["type"], "id": obj.pk, "headline": result["headline"],
                         "title": result["title"], "notes": result["notes"]}, status=201)


# --- settings -----------------------------------------------------------------------

@api_view()
def settings_info(request):
    s = AppSettings.load()
    return JsonResponse({"ai_ready": s.has_api_key, "key_hint": s.anthropic_key_hint, "ai_model": s.ai_model,
                         "usage": ai.usage_this_month(), "username": request.user.get_username(),
                         "devices": [{"device": t.device or "App", "created_at": _dt(t.created_at),
                                      "last_used_at": _dt(t.last_used_at), "current": t.pk == request.api_token.pk}
                                     for t in request.user.api_tokens.all()]})
