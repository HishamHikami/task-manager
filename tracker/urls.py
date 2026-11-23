from django.urls import path

from . import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("tasks/", views.task_list, name="task_list"),
    path("tasks/new/", views.task_new, name="task_new"),
    path("workspaces/<int:ws_pk>/tasks/new/", views.task_create, name="task_create"),
    path("tasks/<int:pk>/", views.task_detail, name="task_detail"),
    path("tasks/<int:pk>/edit/", views.task_edit, name="task_edit"),
    path("tasks/<int:pk>/delete/", views.task_delete, name="task_delete"),
    path("tasks/<int:pk>/update/", views.task_add_update, name="task_add_update"),
    path("tasks/<int:pk>/handoff/", views.task_handoff, name="task_handoff"),
    path("tasks/<int:pk>/stage/", views.task_change_stage, name="task_change_stage"),
    path("tasks/<int:pk>/follow-up/", views.task_follow_up, name="task_follow_up"),
    path("workspaces/", views.workspace_list, name="workspace_list"),
    path("workspaces/new/", views.workspace_create, name="workspace_create"),
    path("workspaces/<int:pk>/", views.workspace_detail, name="workspace_detail"),
    path("workspaces/<int:pk>/edit/", views.workspace_edit, name="workspace_edit"),
    path("workspaces/<int:ws_pk>/holders/new/", views.holder_create, name="holder_create"),
    path("holders/<int:pk>/", views.holder_detail, name="holder_detail"),
    path("holders/<int:pk>/edit/", views.holder_edit, name="holder_edit"),
    path("holders/<int:holder_pk>/people/new/", views.contact_create, name="contact_create"),
    path("people/<int:pk>/edit/", views.contact_edit, name="contact_edit"),
    path("people/<int:pk>/delete/", views.contact_delete, name="contact_delete"),
    path("workspaces/<int:ws_pk>/stages/new/", views.stage_create, name="stage_create"),
    path("stages/<int:pk>/edit/", views.stage_edit, name="stage_edit"),
    path("stages/<int:pk>/delete/", views.stage_delete, name="stage_delete"),
]
