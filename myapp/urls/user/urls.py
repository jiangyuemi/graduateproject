from django.urls import path
from ...views.user.auth import RegisterView, LoginView, LogoutView, UserProfileView, CSRFTokenView, UserStatsView

urlpatterns = [
    path('register/', RegisterView.as_view(), name='register'),
    path('login/', LoginView.as_view(), name='login'),
    path('logout/', LogoutView.as_view(), name='logout'),
    path('profile/', UserProfileView.as_view(), name='profile'),
    path('csrf/', CSRFTokenView.as_view(), name='csrf'),
    path('stats/', UserStatsView.as_view(), name='stats'),
]
