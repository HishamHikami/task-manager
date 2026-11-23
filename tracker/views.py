from collections import OrderedDict

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import views as auth_views
from django.contrib.auth.decorators import login_not_required
from django.core.cache import cache
from django.db.models import Count, Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.decorators import method_decorator
from django.views.decorators.http import require_POST

from . import services
from .forms import (
    FollowUpForm,
    HandoffForm,
    HolderForm,
    StageChangeForm,
    StageForm,
    TaskForm,
    UpdateForm,
    WorkspaceForm,
)
from .models import Holder, Stage, Task, Workspace


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


# --- Helpers ----------------------------------------------------------------------

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
    qs = Task.objects.active_workspaces().select_related("workspace", "stage", "current_holder")
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
            t.current_holder is None,
            (t.current_holder.name.lower() if t.current_holder else ""),
            -t.priority,
        ),
    ):
        label = task.current_holder.name if task.current_holder else "Not assigned to anyone"
        if not workspace and task.current_holder:
            label = f"{task.current_holder.name} · {task.workspace.name}"
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

    holders = Holder.objects.filter(active=True, workspace__archived=False).select_related("workspace")
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
    form = TaskForm(request.POST or None, workspace=workspace)
    if request.method == "POST" and form.is_valid():
        task = form.save(commit=False)
        task.workspace = workspace
        task.current_holder = form.resolve_holder(workspace)
        if task.stage.is_closed:
            task.closed_at = timezone.now()
        task.save()
        services.record_created(task, form.cleaned_data.get("first_note", ""))
        messages.success(request, "Task registered.")
        return redirect(task)
    return render(request, "tracker/task_form.html", {"form": form, "workspace": workspace})


def task_detail(request, pk):
    task = get_object_or_404(Task.objects.select_related("workspace", "stage", "current_holder"), pk=pk)
    updates = task.updates.select_related("from_holder", "to_holder", "from_stage", "to_stage")
    return render(
        request,
        "tracker/task_detail.html",
        {
            "task": task,
            "workspace": task.workspace,
            "updates": updates,
            "update_form": UpdateForm(),
            "handoff_form": HandoffForm(task=task),
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
    updates = task.updates.select_related("from_holder", "to_holder", "from_stage", "to_stage")
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
        holder = form.resolve_holder(task.workspace, field="to_holder")
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
    workspaces = Workspace.objects.annotate(
        open_count=Count("tasks", filter=Q(tasks__stage__is_closed=False)),
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
    holders = workspace.holders.annotate(open_count=Count("tasks", filter=Q(tasks__stage__is_closed=False)))
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
    form = HolderForm(request.POST or None, workspace=workspace)
    if request.method == "POST" and form.is_valid():
        holder = form.save(commit=False)
        holder.workspace = workspace
        holder.save()
        messages.success(request, f"Added {holder.name}.")
        return redirect(workspace)
    return render(
        request, "tracker/form.html",
        {"form": form, "title": f"Add department / person to {workspace.name}", "cancel_url": workspace.get_absolute_url()},
    )


def holder_edit(request, pk):
    holder = get_object_or_404(Holder, pk=pk)
    form = HolderForm(request.POST or None, instance=holder)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Saved.")
        return redirect(holder.workspace)
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
