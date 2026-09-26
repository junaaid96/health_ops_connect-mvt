from django.conf import settings
from django.contrib import admin
from django.urls import include, path, re_path
from django.views.static import serve

admin.site.site_header = "HealthOPS Connect admin"
admin.site.site_title = "HealthOPS Connect"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("accounts.urls")),
    path("", include("core.urls")),
    path("", include("clinic.urls")),
    path("", include("appointments.urls")),
    path("", include("records.urls")),
    path("", include("operations.urls")),
]

if settings.SERVE_MEDIA:
    urlpatterns += [re_path(r"^media/(?P<path>.*)$", serve, {"document_root": settings.MEDIA_ROOT})]
