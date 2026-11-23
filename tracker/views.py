from collections import OrderedDict
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_not_required
from django.core.cache import cache
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST

from . import services
from .forms import (
    ContactForm,
    FollowUpForm,
    HandoffForm,
    HolderForm,
    StageChangeForm,
    StageForm,
    TaskForm,
    UpdateForm,
    WorkspaceForm,
)
from .models import Contact, Holder, Stage, Task, Workspace


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


def _holder_from_query(request, workspace):
    holder_id = request.GET.get("holder", "")
    if holder_id.isdigit():
        return workspace.holders.filter(pk=holder_id, active=True).first()
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
        .select_related("workspace", "stage", "current_holder")
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

    by_holder = OrderedDict()
    for task in sorted(
        open_tasks,
        key=lambda t: (
            0 if t.with_me else 2 if t.current_holder is None else 1,
            (t.current_holder.name.lower() if t.current_holder else ""),
            -t.priority,
        ),
    ):
        if task.with_me:
            label = "On my desk"
        elif task.current_holder:
            label = task.current_holder.display_name
        else:
            label = "Not assigned to anyone"
        if not workspace and task.current_holder:
            label = f"{label} · {task.workspace.name}"
        by_holder.setdefault(label, []).append(task)

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
            "by_holder": by_holder,
            "open_count": len(open_tasks),
            "recent_closed": recent,
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
    picked = _holder_from_query(request, workspace)
    form = TaskForm(request.POST or None, workspace=workspace,
                    initial={"current_holder": picked.pk} if picked else None)
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
        Task.objects.select_related("workspace", "stage", "current_holder")
        .prefetch_related("current_holder__contacts"),
        pk=pk,
    )
    updates = task.updates.select_related("from_holder", "to_holder", "from_stage", "to_stage").prefetch_related(
        "from_holder__contacts", "to_holder__contacts"
    )
    picked = _holder_from_query(request, task.workspace)
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
            "handoff_form": HandoffForm(task=task, initial={"to_holder": picked.pk} if picked else None),
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
        holder = form.cleaned_data["to_holder"]
        services.hand_off(task, holder, form.cleaned_data["note"], form.cleaned_data.get("occurred_at"))
        if form.cleaned_data.get("follow_up_date"):
            services.set_follow_up(task, form.cleaned_data["follow_up_date"], f"Check with {holder.name}")
        messages.success(request, f"Task handed to {holder.name}.")
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
            url = dept.get_absolute_url()
            return redirect(_with_params(url, next=back_to) if back_to else url)
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
        holder.tasks.open().select_related("workspace", "stage", "current_holder")
        .prefetch_related("current_holder__contacts")
    )
    back_to = _safe_next(request)
    return render(
        request,
        "tracker/holder_detail.html",
        {"holder": holder, "workspace": holder.workspace, "contacts": holder.contacts.all(),
         "open_tasks": open_tasks,
         "back_to_task_url": _with_params(back_to, holder=holder.pk) if back_to and holder.active else None,
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
