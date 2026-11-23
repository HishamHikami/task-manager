from django.urls import path

from . import api

urlpatterns = [
    path("auth/login", api.login),
    path("auth/logout", api.logout),
    path("bootstrap", api.bootstrap),
    path("dashboard", api.dashboard),
    path("tasks", api.tasks),
    path("tasks/<int:pk>", api.task_detail),
    path("tasks/<int:pk>/handoff", api.task_handoff),
    path("tasks/<int:pk>/stage", api.task_stage),
    path("tasks/<int:pk>/follow-up", api.task_follow_up),
    path("tasks/<int:pk>/updates", api.task_add_update),
    path("updates/<int:pk>/summarize", api.update_summarize),
    path("events", api.events),
    path("events/<int:pk>", api.event_detail),
    path("workspaces", api.workspaces),
    path("workspaces/<int:pk>", api.workspace_detail),
    path("workspaces/<int:ws_pk>/desks", api.desks),
    path("workspaces/<int:ws_pk>/holders", api.holder_create),
    path("holders/<int:pk>", api.holder_detail),
    path("holders/<int:holder_pk>/people", api.contact_create),
    path("people/<int:pk>", api.contact_detail),
    path("capture/suggest", api.capture_suggest),
    path("capture/save", api.capture_save),
    path("settings", api.settings_info),
]
