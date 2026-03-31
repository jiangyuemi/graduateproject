from django.urls import path
from myapp.views.generate.index import GenerateHandler
urlpatterns = [
    path('generate/', GenerateHandler.as_view(), name='generate'),
    path('generate/<int:pk>/', GenerateHandler.as_view(), name='generate'),
]