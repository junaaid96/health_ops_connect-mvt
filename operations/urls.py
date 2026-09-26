from django.urls import path

from . import views

app_name = "operations"

urlpatterns = [
    path("app/ops/", views.dashboard, name="dashboard"),
    path("app/ops/front-desk/", views.front_desk, name="front_desk"),
    path("app/ops/front-desk/<str:code>/", views.desk_action, name="desk_action"),
    path("app/ops/beds/", views.beds, name="beds"),
    path("app/ops/beds/<int:pk>/status/", views.bed_status, name="bed_status"),
    path("app/ops/admissions/<int:pk>/discharge/", views.discharge, name="discharge"),
    path("app/ops/doctors/", views.doctors, name="doctors"),
    path("app/ops/doctors/<int:pk>/verify/", views.verify_doctor, name="verify_doctor"),
    path("queue/", views.queue_display, name="queue_display"),
]
