from django.urls import path

from . import views

app_name = "core"

urlpatterns = [
    path("", views.home, name="home"),
    path("about/", views.about, name="about"),
    path("app/", views.dashboard, name="dashboard"),
    path("app/queue/", views.doctor_queue, name="doctor_queue"),
    path("app/queue/call-next/", views.call_next, name="call_next"),
    path("healthz", views.healthz, name="healthz"),
]
