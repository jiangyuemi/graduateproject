from django.urls import path
from django.http import JsonResponse


def test_view(request):
    return JsonResponse({
        'code': 200,
        'message': '测试接口正常工作'
    })


urlpatterns = [
    path('', test_view, name='test'),
]
