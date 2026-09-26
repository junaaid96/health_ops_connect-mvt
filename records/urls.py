from django.urls import path

from . import views

app_name = "records"

urlpatterns = [
    path("app/health/", views.health, name="health"),
    path("app/health/vitals/<int:pk>/delete/", views.delete_vital, name="delete_vital"),
    path("app/prescriptions/", views.prescriptions, name="prescriptions"),
    path("app/privacy/", views.privacy, name="privacy"),
    path("app/patients/<int:pk>/", views.patient_chart, name="patient_chart"),
    path("app/consult/<str:code>/", views.consult, name="consult"),
    path("app/visits/<str:code>/prescription/", views.prescription, name="prescription"),
    path("verify/<str:code>/", views.verify, name="verify"),
]
