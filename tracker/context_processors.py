from .models import AppSettings, Workspace


def workspaces(request):
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {}
    return {
        "nav_workspaces": Workspace.objects.filter(archived=False),
        "nav_selected_ws": request.session.get("ws"),
        "ai_ready": AppSettings.load().has_api_key,
    }
