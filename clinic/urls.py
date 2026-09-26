from django.urls import path

from . import views

app_name = "clinic"

urlpatterns = [
    path("doctors/", views.directory, name="directory"),
    path("doctors/<slug:slug>/", views.doctor_detail, name="doctor"),
    path("doctors/<slug:slug>/slots/", views.doctor_slots, name="slots"),
    path("doctors/<slug:slug>/waitlist/", views.join_waitlist, name="waitlist"),
    path("care-finder/", views.care_finder, name="care_finder"),
    path("app/schedule/", views.schedule, name="schedule"),
    path("app/schedule/time-off/<int:pk>/delete/", views.delete_time_off, name="delete_time_off"),
    path("app/visits/<str:code>/review/", views.review, name="review"),
]
