from django.urls import path

from . import views

app_name = "appointments"

urlpatterns = [
    path("book/<slug:slug>/", views.book, name="book"),
    path("book-preview/", views.triage_preview, name="triage_preview"),
    path("app/visits/", views.appointment_list, name="list"),
    path("app/visits/<str:code>/", views.detail, name="detail"),
    path("app/visits/<str:code>/live/", views.live_status, name="live"),
    path("app/visits/<str:code>/cancel/", views.cancel, name="cancel"),
    path("app/visits/<str:code>/check-in/", views.check_in, name="check_in"),
    path("app/visits/<str:code>/reschedule/", views.reschedule, name="reschedule"),
    path("app/visits/<str:code>/calendar.ics", views.ics, name="ics"),
    path("app/visits/<str:code>/join/", views.join_video, name="join_video"),
]
