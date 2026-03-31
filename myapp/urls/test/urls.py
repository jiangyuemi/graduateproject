from django.urls import path
from myapp.views.test.index import UserHandler
urlpatterns = [
    path('user/', UserHandler.as_view(), name='user'),
    path('user/<int:pk>/', UserHandler.as_view(), name='user'), 
]