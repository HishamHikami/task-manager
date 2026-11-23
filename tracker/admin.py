from django.contrib import admin

from .models import Holder, Stage, Task, Update, Workspace


class StageInline(admin.TabularInline):
    model = Stage
    extra = 0


class HolderInline(admin.TabularInline):
    model = Holder
    extra = 0


@admin.register(Workspace)
class WorkspaceAdmin(admin.ModelAdmin):
    list_display = ["name", "color", "ai_enabled", "archived", "order"]
    inlines = [StageInline, HolderInline]


class UpdateInline(admin.TabularInline):
    model = Update
    extra = 0
    fields = ["kind", "occurred_at", "source", "summary", "from_holder", "to_holder", "from_stage", "to_stage"]


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    list_display = ["title", "workspace", "stage", "current_holder", "priority", "due_date", "follow_up_date"]
    list_filter = ["workspace", "stage", "my_role", "priority"]
    search_fields = ["title", "description", "reference"]
    inlines = [UpdateInline]


@admin.register(Holder)
class HolderAdmin(admin.ModelAdmin):
    list_display = ["name", "workspace", "kind", "active"]
    list_filter = ["workspace", "kind", "active"]
    search_fields = ["name"]


@admin.register(Update)
class UpdateAdmin(admin.ModelAdmin):
    list_display = ["task", "kind", "occurred_at", "source"]
    list_filter = ["kind"]
    search_fields = ["body", "summary", "source"]
