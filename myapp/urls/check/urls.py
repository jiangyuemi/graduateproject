from django.urls import path
from myapp.views.check.index import CheckHandler
urlpatterns = [
    path('check/',CheckHandler.as_view(),name = "check"),
]