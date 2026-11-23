from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path

from tracker.views import ThrottledLoginView, admin_login_redirect

urlpatterns = [
    path("login/", ThrottledLoginView.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    # The admin's own login form has no throttling; send it to ours instead.
    path("admin/login/", admin_login_redirect),
    path("admin/", admin.site.urls),
    path("", include("tracker.urls")),
]
