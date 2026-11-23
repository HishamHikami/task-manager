import re
from collections import OrderedDict
from datetime import timedelta
from datetime import timezone as dt_timezone
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_not_required
from django.core.cache import cache
from django.db.models import Count, Q
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.templatetags.static import static
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST

from . import services
from .forms import (
    CaptureForm,
    CaptureReviewForm,
    ContactForm,
    EventForm,
    EventStatusForm,
    desk_value,
    FollowUpForm,
    HandoffForm,
    HolderForm,
    StageChangeForm,
    StageForm,
    TaskForm,
    UpdateForm,
    SettingsForm,
    WorkspaceForm,
)
from . import ai
from .models import AIUsage, AppSettings, Contact, Event, Holder, Stage, Task, Update, Workspace


# --- Login with simple throttling -------------------------------------------------

def _client_ip(request):
    # nginx sets X-Real-IP; fall back to the socket address.
    return request.META.get("HTTP_X_REAL_IP") or request.META.get("REMOTE_ADDR", "unknown")


@method_decorator(login_not_required, name="dispatch")
class ThrottledLoginView(auth_views.LoginView):
    template_name = "tracker/login.html"
    redirect_authenticated_user = True

    def _key(self):
        return f"login-fail:{_client_ip(self.request)}"

    def post(self, request, *args, **kwargs):
        if cache.get(self._key(), 0) >= settings.LOGIN_MAX_ATTEMPTS:
            form = self.get_form()
            form.add_error(None, "Too many failed attempts. Try again in a few minutes.")
            return self.render_to_response(self.get_context_data(form=form), status=429)
        return super().post(request, *args, **kwargs)

    def form_invalid(self, form):
        key = self._key()
        cache.set(key, cache.get(key, 0) + 1, settings.LOGIN_LOCKOUT_SECONDS)
        return super().form_invalid(form)

    def form_valid(self, form):
        cache.delete(self._key())
        return super().form_valid(form)


@login_not_required
def admin_login_redirect(request):
    url = reverse("login")
    if request.GET.get("next"):
        url += "?" + urlencode({"next": request.GET["next"]})
    return redirect(url)


# --- Helpers ----------------------------------------------------------------------

def _safe_next(request):
    """A same-site 'come back here' path from ?next=, or None."""
    nxt = request.GET.get("next") or request.POST.get("next") or ""
    if nxt.startswith("/") and url_has_allowed_host_and_scheme(
        nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return nxt
    return None


def _with_params(url, **params):
    """Add/replace query parameters on a path."""
    parts = urlsplit(url)
    query = dict(parse_qsl(parts.query))
    query.update({k: str(v) for k, v in params.items()})
    return urlunsplit(("", "", parts.path, urlencode(query), ""))


def _add_holder_url(workspace, back_to):
    """Link to add a department/person, returning to `back_to` afterwards."""
    return _with_params(reverse("holder_create", args=[workspace.pk]), next=back_to)


def _desk_from_query(request, workspace):
    """Desk picked on another page and passed back as ?contact=<id> or ?holder=<id>."""
    contact_id, holder_id = request.GET.get("contact", ""), request.GET.get("holder", "")
    if contact_id.isdigit():
        contact = Contact.objects.filter(pk=contact_id, holder__workspace=workspace, active=True).first()
        if contact:
            return desk_value(contact=contact)
    if holder_id.isdigit():
        holder = workspace.holders.filter(pk=holder_id, active=True).first()
        if holder:
            return desk_value(holder=holder)
    return None


def _selected_workspace(request):
    """Workspace filter from ?ws=<id>; remembered in the session. 'all' clears it."""
    ws = request.GET.get("ws")
    if ws == "all":
        request.session.pop("ws", None)
    elif ws and ws.isdigit():
        request.session["ws"] = int(ws)
    ws_id = request.session.get("ws")
    if ws_id:
        workspace = Workspace.objects.filter(pk=ws_id, archived=False).first()
        if workspace:
            return workspace
        request.session.pop("ws", None)
    return None


def _base_tasks(workspace):
    qs = (
        Task.objects.active_workspaces()
        .select_related("workspace", "stage", "current_holder", "current_contact__holder")
        .prefetch_related("current_holder__contacts")
    )
    if workspace:
        qs = qs.filter(workspace=workspace)
    return qs


# --- Dashboard & lists ------------------------------------------------------------

def dashboard(request):
    workspace = _selected_workspace(request)
    today = timezone.localdate()
    open_tasks = _base_tasks(workspace).open()

    overdue = [t for t in open_tasks if t.due_date and t.due_date < today]
    follow_ups = [t for t in open_tasks if t.follow_up_date and t.follow_up_date <= today]

    # One "needs attention" list: overdue or follow-up due, most urgent first, no duplicates.
    attention = sorted(
        {t.pk: t for t in overdue + follow_ups}.values(),
        key=lambda t: (not t.is_overdue, -t.priority, t.due_date or t.follow_up_date or today),
    )

    groups = OrderedDict()
    for task in sorted(
        open_tasks,
        key=lambda t: (
            0 if t.with_me else 2 if t.current_holder is None else 1,
            t.desk_name.lower(),
            -t.priority,
        ),
    ):
        if task.with_me:
            key, title = "me", "On my desk"
        elif task.current_holder:
            key, title = f"{task.current_holder_id}-{task.current_contact_id}", task.desk_name
        else:
            key, title = "none", "Not assigned to anyone"
        group = groups.setdefault(key, {"title": title, "workspace": task.workspace if task.current_holder else None,
                                        "tasks": []})
        group["tasks"].append(task)

    soon = timezone.now() + timedelta(days=14)
    upcoming_events = (
        _events_base(workspace).upcoming().filter(start__lte=soon).exclude(status__in=["declined", "cancelled"])
        .order_by("start")[:8]
    )
    open_invites = _events_base(workspace).upcoming().filter(status="invited").count()
    recent = (
        _base_tasks(workspace).closed().filter(closed_at__isnull=False).order_by("-closed_at")[:5]
    )
    return render(
        request,
        "tracker/dashboard.html",
        {
            "workspace": workspace,
            "overdue": overdue,
            "follow_ups": follow_ups,
            "attention": attention,
            "groups": list(groups.values()),
            "open_count": len(open_tasks),
            "recent_closed": recent,
            "upcoming_events": upcoming_events,
            "open_invites": open_invites,
            "today": today,
        },
    )


def task_list(request):
    workspace = _selected_workspace(request)
    qs = _base_tasks(workspace)
    status = request.GET.get("status", "open")
    if status == "open":
        qs = qs.open()
    elif status == "closed":
        qs = qs.closed()
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(
            Q(title__icontains=q)
            | Q(description__icontains=q)
            | Q(reference__icontains=q)
            | Q(updates__body__icontains=q)
            | Q(updates__summary__icontains=q)
            | Q(updates__source__icontains=q)
        ).distinct()
    holder_id = request.GET.get("holder")
    if holder_id and holder_id.isdigit():
        qs = qs.filter(current_holder_id=holder_id)
    role = request.GET.get("role")
    if role in dict(Task.ROLE_CHOICES):
        qs = qs.filter(my_role=role)

    holders = (
        Holder.objects.filter(active=True, workspace__archived=False)
        .select_related("workspace").prefetch_related("contacts")
    )
    if workspace:
        holders = holders.filter(workspace=workspace)
    return render(
        request,
        "tracker/task_list.html",
        {
            "workspace": workspace,
            "tasks": qs[:300],
            "status": status,
            "q": q,
            "holders": holders,
            "holder_id": holder_id or "",
            "role": role or "",
            "roles": Task.ROLE_CHOICES,
        },
    )


# --- Tasks ------------------------------------------------------------------------

def task_new(request):
    """Pick a workspace before creating a task (skipped when only one exists)."""
    workspaces = Workspace.objects.filter(archived=False)
    selected = _selected_workspace(request)
    if selected:
        return redirect("task_create", ws_pk=selected.pk)
    if workspaces.count() == 1:
        return redirect("task_create", ws_pk=workspaces.first().pk)
    if not workspaces.exists():
        messages.info(request, "Create a workspace first, e.g. “Company” or your organization.")
        return redirect("workspace_create")
    return render(request, "tracker/task_pick_workspace.html", {"workspaces": workspaces})


def task_create(request, ws_pk):
    workspace = get_object_or_404(Workspace, pk=ws_pk, archived=False)
    if not workspace.stages.exists():
        workspace.create_default_stages()
    picked = _desk_from_query(request, workspace)
    form = TaskForm(request.POST or None, workspace=workspace,
                    initial={"current_holder": picked} if picked else None)
    if request.method == "POST" and form.is_valid():
        task = form.save(commit=False)
        task.workspace = workspace
        if task.stage.is_closed:
            task.closed_at = timezone.now()
        task.save()
        services.record_created(task, form.cleaned_data.get("first_note", ""))
        messages.success(request, "Task registered.")
        return redirect(task)
    back_to = reverse("task_create", args=[workspace.pk])
    return render(
        request, "tracker/task_form.html",
        {"form": form, "workspace": workspace, "add_holder_url": _add_holder_url(workspace, back_to),
         "picked_holder": picked},
    )


def task_detail(request, pk):
    task = get_object_or_404(
        Task.objects.select_related("workspace", "stage", "current_holder", "current_contact__holder")
        .prefetch_related("current_holder__contacts"),
        pk=pk,
    )
    updates = task.updates.select_related("from_holder", "to_holder", "from_stage", "to_stage").prefetch_related(
        "from_holder__contacts", "to_holder__contacts"
    )
    picked = _desk_from_query(request, task.workspace)
    return render(
        request,
        "tracker/task_detail.html",
        {
            "task": task,
            "workspace": task.workspace,
            "updates": updates,
            "add_holder_url": _add_holder_url(task.workspace, task.get_absolute_url()),
            "open_panel": "handoff" if picked else None,
            "update_form": UpdateForm(),
            "handoff_form": HandoffForm(task=task, initial={"to_holder": picked} if picked else None),
            "stage_form": StageChangeForm(task=task),
            "followup_form": FollowUpForm(
                initial={"follow_up_date": task.follow_up_date, "follow_up_note": task.follow_up_note}
            ),
        },
    )


def task_edit(request, pk):
    task = get_object_or_404(Task, pk=pk)
    form = TaskForm(request.POST or None, instance=task, workspace=task.workspace)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Task saved.")
        return redirect(task)
    return render(request, "tracker/task_form.html", {"form": form, "workspace": task.workspace, "task": task})


def task_delete(request, pk):
    task = get_object_or_404(Task, pk=pk)
    if request.method == "POST":
        task.delete()
        messages.success(request, "Task deleted.")
        return redirect("dashboard")
    return render(request, "tracker/confirm_delete.html", {"object": task, "cancel_url": task.get_absolute_url()})


def _detail_with_errors(request, task, **forms):
    """Re-render the task page with a failed form's errors."""
    updates = task.updates.select_related("from_holder", "to_holder", "from_stage", "to_stage").prefetch_related(
        "from_holder__contacts", "to_holder__contacts"
    )
    context = {
        "task": task,
        "workspace": task.workspace,
        "updates": updates,
        "update_form": UpdateForm(),
        "handoff_form": HandoffForm(task=task),
        "stage_form": StageChangeForm(task=task),
        "followup_form": FollowUpForm(
            initial={"follow_up_date": task.follow_up_date, "follow_up_note": task.follow_up_note}
        ),
        "open_panel": next(iter(forms)).replace("_form", ""),
        "add_holder_url": _add_holder_url(task.workspace, task.get_absolute_url()),
    }
    context.update(forms)
    return render(request, "tracker/task_detail.html", context, status=400)


@require_POST
def task_add_update(request, pk):
    task = get_object_or_404(Task, pk=pk)
    form = UpdateForm(request.POST)
    if form.is_valid():
        update = form.save(commit=False)
        update.task = task
        update.save()
        services.touch(task)
        messages.success(request, "Update added to the timeline.")
        return redirect(task)
    return _detail_with_errors(request, task, update_form=form)


@require_POST
def task_handoff(request, pk):
    task = get_object_or_404(Task, pk=pk)
    form = HandoffForm(request.POST, task=task)
    if form.is_valid():
        holder, contact = form.cleaned_data["to_holder"]
        services.hand_off(task, holder, form.cleaned_data["note"], form.cleaned_data.get("occurred_at"),
                          to_contact=contact)
        who = contact.name if contact else holder.name
        if form.cleaned_data.get("follow_up_date"):
            services.set_follow_up(task, form.cleaned_data["follow_up_date"], f"Check with {who}")
        messages.success(request, f"Task handed to {task.desk_name}.")
        return redirect(task)
    return _detail_with_errors(request, task, handoff_form=form)


@require_POST
def task_change_stage(request, pk):
    task = get_object_or_404(Task, pk=pk)
    form = StageChangeForm(request.POST, task=task)
    if form.is_valid():
        services.change_stage(task, form.cleaned_data["stage"], form.cleaned_data["note"])
        messages.success(request, f"Moved to “{form.cleaned_data['stage'].name}”.")
        return redirect(task)
    return _detail_with_errors(request, task, stage_form=form)


@require_POST
def task_follow_up(request, pk):
    task = get_object_or_404(Task, pk=pk)
    form = FollowUpForm(request.POST)
    if form.is_valid():
        services.set_follow_up(task, form.cleaned_data["follow_up_date"], form.cleaned_data["follow_up_note"])
        messages.success(request, "Follow-up saved.")
        return redirect(task)
    return _detail_with_errors(request, task, followup_form=form)


# --- Workspaces, stages, holders --------------------------------------------------

def workspace_list(request):
    # distinct=True on both: two joined counts otherwise multiply each other.
    workspaces = Workspace.objects.annotate(
        open_count=Count("tasks", filter=Q(tasks__stage__is_closed=False), distinct=True),
        holder_count=Count("holders", distinct=True),
    )
    return render(request, "tracker/workspace_list.html", {"workspaces": workspaces})


def workspace_create(request):
    form = WorkspaceForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        workspace = form.save()
        workspace.create_default_stages()
        messages.success(request, "Workspace created with default stages. Add departments and people next.")
        return redirect(workspace)
    return render(request, "tracker/form.html", {"form": form, "title": "New workspace", "cancel_url": "/workspaces/"})


def workspace_detail(request, pk):
    workspace = get_object_or_404(Workspace, pk=pk)
    holders = workspace.holders.annotate(
        open_count=Count("tasks", filter=Q(tasks__stage__is_closed=False))
    ).prefetch_related("contacts")
    stages = workspace.stages.annotate(task_count=Count("tasks"))
    return render(
        request,
        "tracker/workspace_detail.html",
        {"workspace": workspace, "holders": holders, "stages": stages,
         "holder_form": HolderForm(workspace=workspace), "stage_form": StageForm(workspace=workspace,
                                                                                 initial={"order": stages.count()})},
    )


def workspace_edit(request, pk):
    workspace = get_object_or_404(Workspace, pk=pk)
    form = WorkspaceForm(request.POST or None, instance=workspace)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Workspace saved.")
        return redirect(workspace)
    return render(
        request, "tracker/form.html",
        {"form": form, "title": f"Edit {workspace.name}", "cancel_url": workspace.get_absolute_url()},
    )


def holder_create(request, ws_pk):
    workspace = get_object_or_404(Workspace, pk=ws_pk)
    back_to = _safe_next(request)
    form = HolderForm(request.POST or None, workspace=workspace)
    if request.method == "POST" and form.is_valid():
        if form.cleaned_data.get("department"):
            contact = form.save_into_department()
            dept = contact.holder
            messages.success(request, f"Added {contact.name} to {dept.name}.")
            if back_to:
                return redirect(_with_params(back_to, contact=contact.pk))
            return redirect(dept)
        holder = form.save(commit=False)
        holder.workspace = workspace
        holder.save()
        if holder.is_group:
            messages.success(request, f"Added {holder.name}. Now add the people who work there.")
            url = holder.get_absolute_url()
            return redirect(_with_params(url, next=back_to) if back_to else url)
        messages.success(request, f"Added {holder.name}.")
        if back_to:
            return redirect(_with_params(back_to, holder=holder.pk))
        return redirect(workspace)
    return render(
        request, "tracker/form.html",
        {"form": form, "title": f"Add department / person to {workspace.name}",
         "cancel_url": back_to or workspace.get_absolute_url(),
         "intro": "After saving you'll go back to your task." if back_to else ""},
    )


def holder_edit(request, pk):
    holder = get_object_or_404(Holder, pk=pk)
    form = HolderForm(request.POST or None, instance=holder)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Saved.")
        return redirect(holder if holder.is_group else holder.workspace)
    return render(
        request, "tracker/form.html",
        {"form": form, "title": f"Edit {holder.name}", "cancel_url": holder.workspace.get_absolute_url()},
    )


def stage_create(request, ws_pk):
    workspace = get_object_or_404(Workspace, pk=ws_pk)
    form = StageForm(request.POST or None, workspace=workspace)
    if request.method == "POST" and form.is_valid():
        stage = form.save(commit=False)
        stage.workspace = workspace
        stage.save()
        messages.success(request, f"Stage “{stage.name}” added.")
        return redirect(workspace)
    return render(
        request, "tracker/form.html",
        {"form": form, "title": f"Add stage to {workspace.name}", "cancel_url": workspace.get_absolute_url()},
    )


def stage_edit(request, pk):
    stage = get_object_or_404(Stage, pk=pk)
    form = StageForm(request.POST or None, instance=stage)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Stage saved.")
        return redirect(stage.workspace)
    return render(
        request, "tracker/form.html",
        {"form": form, "title": f"Edit stage “{stage.name}”", "cancel_url": stage.workspace.get_absolute_url()},
    )


@require_POST
def stage_delete(request, pk):
    stage = get_object_or_404(Stage, pk=pk)
    if stage.tasks.exists():
        messages.error(request, "This stage still has tasks. Move them to another stage first.")
    else:
        stage.delete()
        messages.success(request, "Stage removed.")
    return redirect(stage.workspace)


# --- People inside a department / committee ---------------------------------------

def holder_detail(request, pk):
    holder = get_object_or_404(Holder.objects.select_related("workspace"), pk=pk)
    open_tasks = (
        holder.tasks.open().select_related("workspace", "stage", "current_holder", "current_contact__holder")
        .prefetch_related("current_holder__contacts")
    )
    back_to = _safe_next(request)
    return render(
        request,
        "tracker/holder_detail.html",
        {"holder": holder, "workspace": holder.workspace, "contacts": holder.contacts.all(),
         "open_tasks": open_tasks,
         "back_to_task_url": _with_params(back_to, holder=holder.pk) if back_to and holder.active else None,
         "back_to": back_to,
         "add_person_url": _with_params(reverse("contact_create", args=[holder.pk]), next=back_to)
         if back_to else reverse("contact_create", args=[holder.pk])},
    )


def contact_create(request, holder_pk):
    holder = get_object_or_404(Holder, pk=holder_pk)
    back_to = _safe_next(request)
    holder_url = _with_params(holder.get_absolute_url(), next=back_to) if back_to else holder.get_absolute_url()
    is_first = not holder.contacts.exists()
    form = ContactForm(request.POST or None, initial={"is_primary": is_first})
    if request.method == "POST" and form.is_valid():
        contact = form.save(commit=False)
        contact.holder = holder
        contact.save()
        messages.success(request, f"Added {contact.name} to {holder.name}.")
        return redirect(holder_url)
    return render(
        request, "tracker/form.html",
        {"form": form, "title": f"Add a person to {holder.name}", "cancel_url": holder_url},
    )


def contact_edit(request, pk):
    contact = get_object_or_404(Contact.objects.select_related("holder"), pk=pk)
    form = ContactForm(request.POST or None, instance=contact)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Saved.")
        return redirect(contact.holder)
    return render(
        request, "tracker/form.html",
        {"form": form, "title": f"Edit {contact.name} ({contact.holder.name})",
         "cancel_url": contact.holder.get_absolute_url()},
    )


@require_POST
def contact_delete(request, pk):
    contact = get_object_or_404(Contact.objects.select_related("holder"), pk=pk)
    holder = contact.holder
    contact.delete()
    messages.success(request, f"Removed {contact.name}.")
    return redirect(holder)


# --- Events -----------------------------------------------------------------------

def _events_base(workspace):
    qs = Event.objects.filter(workspace__archived=False).select_related(
        "workspace", "organizer", "organizer_contact__holder"
    ).prefetch_related("organizer__contacts")
    return qs.filter(workspace=workspace) if workspace else qs


def event_list(request):
    workspace = _selected_workspace(request)
    show = request.GET.get("show", "upcoming")
    qs = _events_base(workspace)
    if show == "past":
        events = qs.past().order_by("-start")
    elif show == "invites":
        events = qs.filter(status="invited").order_by("start")
    else:
        show = "upcoming"
        events = qs.upcoming().order_by("start")
    role = request.GET.get("role", "")
    if role in dict(Event.ROLE_CHOICES):
        events = events.filter(my_role=role)
    return render(
        request, "tracker/event_list.html",
        {"workspace": workspace, "events": events[:300], "show": show, "role": role,
         "roles": Event.ROLE_CHOICES, "invite_count": qs.filter(status="invited").count()},
    )


def event_new(request):
    workspaces = Workspace.objects.filter(archived=False)
    selected = _selected_workspace(request)
    if selected:
        return redirect("event_create", ws_pk=selected.pk)
    if workspaces.count() == 1:
        return redirect("event_create", ws_pk=workspaces.first().pk)
    if not workspaces.exists():
        messages.info(request, "Create a workspace first.")
        return redirect("workspace_create")
    return render(request, "tracker/task_pick_workspace.html",
                  {"workspaces": workspaces, "for_events": True})


def event_create(request, ws_pk):
    workspace = get_object_or_404(Workspace, pk=ws_pk, archived=False)
    form = EventForm(request.POST or None, workspace=workspace)
    if request.method == "POST" and form.is_valid():
        event = form.save(commit=False)
        event.workspace = workspace
        event.save()
        messages.success(request, "Event saved.")
        return redirect(event)
    return render(request, "tracker/event_form.html", {"form": form, "workspace": workspace})


def event_detail(request, pk):
    event = get_object_or_404(_events_base(None), pk=pk)
    short = {"invited": "Invited", "tentative": "Maybe", "confirmed": "Going", "declined": "Declined",
             "done": "Attended", "cancelled": "Cancelled"}
    return render(request, "tracker/event_detail.html",
                  {"event": event, "workspace": event.workspace,
                   "statuses": [(v, short[v]) for v, _ in Event.STATUS_CHOICES]})


def event_edit(request, pk):
    event = get_object_or_404(Event, pk=pk)
    form = EventForm(request.POST or None, instance=event, workspace=event.workspace)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Event saved.")
        return redirect(event)
    return render(request, "tracker/event_form.html", {"form": form, "workspace": event.workspace, "event": event})


@require_POST
def event_status(request, pk):
    event = get_object_or_404(Event, pk=pk)
    form = EventStatusForm(request.POST)
    if form.is_valid():
        event.status = form.cleaned_data["status"]
        event.save(update_fields=["status", "updated_at"])
        messages.success(request, f"Marked as: {event.get_status_display()}.")
    return redirect(event)


def event_delete(request, pk):
    event = get_object_or_404(Event, pk=pk)
    if request.method == "POST":
        event.delete()
        messages.success(request, "Event deleted.")
        return redirect("event_list")
    return render(request, "tracker/confirm_delete.html",
                  {"object": event, "cancel_url": event.get_absolute_url(),
                   "warning": "This removes the event and its notes. It can't be undone."})


def _ics_text(value):
    return (value or "").replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def event_ics(request, pk):
    """Download the event as a calendar file (opens in phone/Outlook/Google calendar)."""
    event = get_object_or_404(_events_base(None), pk=pk)
    fmt = "%Y%m%dT%H%M%SZ"
    start = event.start.astimezone(dt_timezone.utc)
    end = (event.end or event.start + timedelta(hours=1)).astimezone(dt_timezone.utc)
    details = [f"My role: {event.get_my_role_display()}"]
    if event.my_topic:
        details.append(f"My topic: {event.my_topic}")
    if event.organizer_name:
        details.append(f"Organizer: {event.organizer_name}")
    if event.online_link:
        details.append(event.online_link)
    if event.description:
        details.append(event.description)
    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Task Manager//Events//EN", "BEGIN:VEVENT",
        f"UID:event-{event.pk}@{request.get_host()}",
        f"DTSTAMP:{timezone.now().astimezone(dt_timezone.utc).strftime(fmt)}",
        f"DTSTART:{start.strftime(fmt)}", f"DTEND:{end.strftime(fmt)}",
        f"SUMMARY:{_ics_text(event.title)}",
        f"LOCATION:{_ics_text(event.location)}",
        f"DESCRIPTION:{_ics_text(chr(10).join(details))}",
        "STATUS:" + ("CANCELLED" if event.is_off else "TENTATIVE" if event.status in {"invited", "tentative"}
                     else "CONFIRMED"),
        "END:VEVENT", "END:VCALENDAR",
    ]
    resp = HttpResponse("\r\n".join(lines) + "\r\n", content_type="text/calendar; charset=utf-8")
    resp["Content-Disposition"] = f'attachment; filename="event-{event.pk}.ics"'
    return resp


# --- Quick capture (AI) -----------------------------------------------------------

def _shared_text(request):
    """Text arriving from Android's Share menu (?title=&text=&url=) or a plain ?text=."""
    parts = [request.GET.get(k, "").strip() for k in ("title", "text", "url")]
    seen, out = set(), []
    for p in parts:
        if p and p not in seen:
            seen.add(p)
            out.append(p)
    return "\n".join(out)


def _guess_kind(text):
    t = text.lower()
    if re.search(r"^\[?\d{1,2}[/.]\d{1,2}[/.]\d{2,4},? \d{1,2}:\d{2}", text, re.M) or "whatsapp" in t:
        return "whatsapp"
    if re.search(r"^(from|subject|to|sent):", t, re.M) or "dear " in t or "regards" in t:
        return "email"
    if "minutes" in t or "attendees" in t or "agenda" in t:
        return "meeting"
    return "note"


def capture(request):
    workspace = _selected_workspace(request) or Workspace.objects.filter(archived=False).first()
    if not workspace:
        messages.info(request, "Create a workspace first.")
        return redirect("workspace_create")
    form = CaptureForm(request.POST or None, initial={"text": _shared_text(request), "workspace": workspace})
    ai_ready = ai.is_configured()
    if request.method == "POST" and form.is_valid():
        ws = form.cleaned_data["workspace"]
        text = form.cleaned_data["text"]
        initial = {"workspace": ws, "body": text, "kind": _guess_kind(text), "action": "new_task",
                   "my_role": "following"}
        info = {}
        if "use_ai" in request.POST:
            try:
                suggestion, info = ai.suggest_for_capture(ws, text)
            except ai.AIError as exc:
                messages.error(request, str(exc))
                suggestion = None
            if suggestion:
                initial.update({
                    "summary": suggestion["summary"], "kind": suggestion["message_kind"],
                    "source": suggestion["sender"], "action": suggestion["action"],
                    "task": suggestion["task_id"], "new_task_title": suggestion["new_task_title"],
                    "desk": suggestion["desk"], "next_action": suggestion["next_action"],
                    "due_date": suggestion["due_date"], "follow_up_date": suggestion["follow_up_date"],
                    "event_title": suggestion["event_title"], "event_start": suggestion["event_start"],
                    "event_end": suggestion["event_end"], "event_location": suggestion["event_location"],
                    "event_my_role": suggestion["event_my_role"] or "guest",
                    "event_kind": suggestion["event_kind"] or "meeting",
                    "handoff": bool(suggestion["desk"]),
                })
                info["used_ai"] = True
        review = CaptureReviewForm(initial=initial, workspace=ws)
        return render(request, "tracker/capture_review.html",
                      {"form": review, "workspace": ws, "info": info, "text": text})
    return render(request, "tracker/capture.html", {"form": form, "ai_ready": ai_ready,
                                                     "ai_off_workspaces": Workspace.objects.filter(ai_enabled=False)})


@require_POST
def capture_save(request):
    ws = get_object_or_404(Workspace, pk=request.POST.get("workspace"))
    form = CaptureReviewForm(request.POST, workspace=ws)
    if not form.is_valid():
        return render(request, "tracker/capture_review.html",
                      {"form": form, "workspace": ws, "info": {}, "text": request.POST.get("body", "")},
                      status=400)
    d = form.cleaned_data
    holder, contact = d.get("desk") or (None, None)
    action = d["action"]

    if action == "new_event":
        event = Event.objects.create(
            workspace=ws, title=d["event_title"].strip(), kind=d.get("event_kind") or "meeting",
            my_role=d.get("event_my_role") or "guest", status="invited", start=d["event_start"],
            end=d.get("event_end"), location=d.get("event_location", ""), organizer=holder,
            organizer_contact=contact, organizer_other="" if holder else d.get("source", ""),
            description="\n\n".join(x for x in [d.get("summary", ""), d.get("body", "")] if x),
            preparation=d.get("next_action", ""),
        )
        messages.success(request, "Event added. Mark it Confirmed or Declined when you've answered.")
        return redirect(event)

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
        else:
            task = d["task"]
            if d.get("handoff") and holder and (holder, contact) != (task.current_holder, task.current_contact):
                services.hand_off(task, holder, "", to_contact=contact)
            if d.get("due_date") and not task.due_date:
                task.due_date = d["due_date"]
                task.save(update_fields=["due_date", "updated_at"])
        Update.objects.create(task=task, kind=d["kind"], body=d.get("body", ""), summary=d.get("summary", ""),
                              source=d.get("source", ""))
        if d.get("follow_up_date"):
            services.set_follow_up(task, d["follow_up_date"], d.get("next_action", ""))
        services.touch(task)
    messages.success(request, "Saved to the task's timeline." if action == "update_task" else "Task registered.")
    return redirect(task)


@require_POST
def update_summarize(request, pk):
    update = get_object_or_404(Update.objects.select_related("task__workspace"), pk=pk)
    try:
        update.summary = ai.summarize(update.body, update.task.workspace)
        update.save(update_fields=["summary"])
        messages.success(request, "Summary added.")
    except ai.AIError as exc:
        messages.error(request, str(exc))
    return redirect(update.task)


def settings_view(request):
    s = AppSettings.load()
    form = SettingsForm(request.POST or None, initial={"ai_model": s.ai_model})
    if request.method == "POST" and "test" in request.POST:
        try:
            ai.test_connection()
            messages.success(request, "Connected — the AI key works.")
        except ai.AIError as exc:
            messages.error(request, str(exc))
        return redirect("settings")
    if request.method == "POST" and form.is_valid():
        if form.cleaned_data["remove_key"]:
            ai.save_api_key("")
            messages.success(request, "API key removed.")
        elif form.cleaned_data["api_key"]:
            ai.save_api_key(form.cleaned_data["api_key"])
            messages.success(request, "API key saved (encrypted). Use “Test the key” to check it.")
        s = AppSettings.load()
        s.ai_model = form.cleaned_data["ai_model"]
        s.save(update_fields=["ai_model", "updated_at"])
        return redirect("settings")
    return render(request, "tracker/settings.html", {
        "form": form, "s": s, "usage": ai.usage_this_month(),
        "workspaces": Workspace.objects.all(),
        "recent_errors": AIUsage.objects.filter(ok=False)[:5],
    })


# --- Installable app (PWA) --------------------------------------------------------

@login_not_required
def manifest(request):
    icons = static("tracker/icons/")
    data = {
        "name": "Task Manager",
        "short_name": "Tasks",
        "id": "/",
        "start_url": "/?source=app",
        "scope": "/",
        "display": "standalone",
        "background_color": "#f4f6f9",
        "theme_color": "#1f3a5f",
        "description": "Track tasks, hand-offs and events.",
        "icons": [
            {"src": icons + "icon-192.png", "sizes": "192x192", "type": "image/png"},
            {"src": icons + "icon-512.png", "sizes": "512x512", "type": "image/png"},
            {"src": icons + "maskable-512.png", "sizes": "512x512", "type": "image/png", "purpose": "maskable"},
        ],
        "share_target": {
            "action": "/capture/",
            "method": "GET",
            "enctype": "application/x-www-form-urlencoded",
            "params": {"title": "title", "text": "text", "url": "url"},
        },
        "shortcuts": [
            {"name": "Quick capture", "url": "/capture/", "icons": [{"src": icons + "icon-192.png", "sizes": "192x192"}]},
            {"name": "New task", "url": "/tasks/new/", "icons": [{"src": icons + "icon-192.png", "sizes": "192x192"}]},
        ],
    }
    resp = JsonResponse(data, json_dumps_params={"indent": 1})
    resp["Content-Type"] = "application/manifest+json"
    return resp


SERVICE_WORKER = """
const CACHE = "tm-v2";
const OFFLINE = "/offline/";
self.addEventListener("install", (e) => {
  e.waitUntil(caches.open(CACHE).then((c) => c.addAll([OFFLINE])).then(() => self.skipWaiting()));
});
self.addEventListener("activate", (e) => {
  e.waitUntil(caches.keys().then((keys) => Promise.all(keys.filter((k) => k !== CACHE).map((k) => caches.delete(k))))
    .then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const req = e.request;
  if (req.method !== "GET") return;
  const url = new URL(req.url);
  if (url.origin !== location.origin) return;
  if (url.pathname.startsWith("/static/")) {
    // Static files: cache first, refresh in the background.
    e.respondWith(caches.open(CACHE).then(async (c) => {
      const hit = await c.match(req);
      const net = fetch(req).then((r) => { if (r.ok) c.put(req, r.clone()); return r; }).catch(() => hit);
      return hit || net;
    }));
    return;
  }
  if (req.mode === "navigate") {
    // Pages are always fetched fresh (they hold your data); offline page if there's no connection.
    e.respondWith(fetch(req).catch(() => caches.match(OFFLINE)));
  }
});
"""


@login_not_required
def service_worker(request):
    resp = HttpResponse(SERVICE_WORKER, content_type="application/javascript")
    resp["Cache-Control"] = "no-cache"
    resp["Service-Worker-Allowed"] = "/"
    return resp


@login_not_required
def offline(request):
    return render(request, "tracker/offline.html")
