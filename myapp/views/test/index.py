from rest_framework.views import APIView
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema,OpenApiParameter,OpenApiExample,OpenApiRequest
@extend_schema(tags=["用户管理"])
class UserHandler(APIView):
    def get(self, request): # 查找
        user = User(name="John", age=20)
        return Response(user.to_dict())
    def post(self, request):  # 创建
        return Response()

    def put(self, request, pk):  # 修改
        return Response()

    def delete(self, request, pk):  # 删除
        return Response()




# 测试集
class User:
    def __init__(self, name, age):
        self.name = name
        self.age = age
    def to_dict(self):
        return {
            "name": self.name,
            "age": self.age
        }