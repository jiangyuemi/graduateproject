"""
URL configuration for mysite project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/5.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView
from myapp.fronthandler import home, create, check, history, profile

urlpatterns = [
    path('admin/', admin.site.urls),
    # 前端页面路由
    path('', home, name='home'),
    path('api/create/', create, name='create'),
    path('api/check/', check, name='check'),
    path('api/history/', history, name='history'),
    path('api/profile/', profile, name='profile'),
    # API路由
    path('test/', include('myapp.urls.test.urls')),
    path('generate/', include('myapp.urls.generate.urls')),
    path('check/', include('myapp.urls.check.urls')),
    # 合同管理
    path('api/contract/', include('myapp.urls.contract.urls')),
    # 导出功能
    # 用户认证
    path('api/user/', include('myapp.urls.user.urls')),
    # Swagger 文档
    path('api/schema/', SpectacularAPIView.as_view(), name='schema'),
    path('api/docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
]
